"""
LLM 智能改写模块 (Round 2 #3)

设计原则:
  - MVP: 没 key / 没启用 / 调用失败 → 全部静默降级,绝不抛异常给上层
  - 只走 OpenAI 兼容 HTTP 协议,纯 stdlib (urllib + json),不引入第三方包
  - 每次最多 max_per_call 条,剩余保留原文,避免单次 prompt 太大超时/超 token
  - 不写任何调用日志到磁盘 (避免 PII 泄漏)
"""
import json
import os
import urllib.error
import urllib.request
from typing import Optional


# ----------------------------------------------------------------------
# 配置: 全部走 env var,不读 yaml/toml (无状态,易测试)
# ----------------------------------------------------------------------
DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4o-mini"
REQUEST_TIMEOUT_SEC = 15

SYSTEM_PROMPT = (
    "你是简历润色专家,根据目标岗位改写项目亮点。"
    "**只**调整措辞/顺序/重点强调,**绝不**编造事实。"
    "改写后的句子必须能在原文找到对应事实点。"
    "每条 bullet 一句话,中文,20-50 字。"
    "返回 JSON 数组,顺序与输入一致。"
)


def _env(name: str, default: str = "") -> str:
    """读 env var,strip 空白,空字符串视同未设置"""
    v = os.environ.get(name, default)
    return v.strip() if isinstance(v, str) else default


def is_llm_enabled() -> bool:
    """
    LLM 启用判定:
      - LLM_ENABLED == "false" → 强制关闭
      - 否则看是否有 LLM_API_KEY (非空)
      - 默认 LLM_ENABLED == "auto": 有 key 就开,没 key 就关
    """
    flag = _env("LLM_ENABLED", "auto").lower()
    if flag == "false":
        return False
    return bool(_env("LLM_API_KEY"))


def _build_request_payload(
    highlights: list[str],
    target_role: str,
    jd_text: str,
    model: str,
) -> dict:
    """构造 chat/completions 请求体"""
    return {
        "model": model,
        "temperature": 0.3,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "target_role": target_role,
                        "jd_context": jd_text or "",
                        "bullets": highlights,
                    },
                    ensure_ascii=False,
                ),
            },
        ],
    }


def _http_post_json(url: str, payload: dict, api_key: str, timeout: int) -> dict:
    """
    发 POST 请求 (stdlib urllib),返回解析后的 JSON dict。
    失败抛 RuntimeError (网络/超时/HTTP 非 2xx/JSON 解析) — 由 generator 静默捕获。
    """
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            status = resp.status
    except urllib.error.HTTPError as e:
        # 服务端返 4xx/5xx — 读 body 帮助诊断
        try:
            body = e.read().decode("utf-8", errors="replace")
        except Exception:
            body = ""
        raise RuntimeError(f"LLM HTTP {e.code}: {body[:200]}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"LLM URLError: {e.reason}") from e
    except TimeoutError as e:
        raise RuntimeError(f"LLM timeout after {timeout}s") from e

    if status < 200 or status >= 300:
        raise RuntimeError(f"LLM HTTP {status}: {raw[:200]}")

    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"LLM invalid JSON: {raw[:200]}") from e


def _extract_rewritten(response: dict, expected_count: int) -> Optional[list[str]]:
    """
    从 LLM 响应里提取改写后的 bullet list。
    兼容两种 schema:
      - {"rewritten": ["...", "..."]}
      - {"bullets": ["...", "..."]}
      - 顶层就是 array: ["...", "..."]
    任一条 schema 命中且长度等于 expected_count 才返回,否则 None。
    """
    candidates: list = []

    if isinstance(response, list):
        candidates.append(response)
    elif isinstance(response, dict):
        # OpenAI 标准 chat/completions 响应: choices[0].message.content 是 str
        choices = response.get("choices") or []
        if choices and isinstance(choices, list):
            msg = choices[0].get("message") or {}
            content = msg.get("content")
            if isinstance(content, str):
                # content 本身是字符串,尝试再 parse 一层 JSON
                try:
                    parsed = json.loads(content)
                except json.JSONDecodeError:
                    parsed = None
                if isinstance(parsed, list):
                    candidates.append(parsed)
                elif isinstance(parsed, dict):
                    for key in ("rewritten", "bullets", "items", "result"):
                        v = parsed.get(key)
                        if isinstance(v, list):
                            candidates.append(v)
                            break
            elif isinstance(content, list):
                # 某些模型直接返回 content list
                candidates.append(content)
        # 兼容直传 {"rewritten": [...]}
        for key in ("rewritten", "bullets", "items"):
            v = response.get(key)
            if isinstance(v, list):
                candidates.append(v)

    for c in candidates:
        if (
            len(c) == expected_count
            and all(isinstance(x, str) and x.strip() for x in c)
        ):
            return [x.strip() for x in c]
    return None


def rewrite_highlights(
    highlights: list[str],
    target_role: str,
    jd_text: str = "",
    max_per_call: int = 6,
) -> list[str]:
    """
    把 highlights 按 target_role 视角改写。
    - 输入输出长度一致。
    - 没启用 / 调用失败 / 超时 / JSON 解析失败 / 长度对不上 → 返回原 highlights (不抛)。
    - 每次最多处理 max_per_call 条,剩余保持原样。
    """
    if not highlights:
        return highlights
    if not is_llm_enabled():
        return highlights

    n = len(highlights)
    chunk_size = max(1, max_per_call)
    rewritten: list[Optional[str]] = [None] * n

    api_key = _env("LLM_API_KEY")
    base_url = _env("LLM_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
    model = _env("LLM_MODEL", DEFAULT_MODEL)
    url = f"{base_url}/chat/completions"

    for start in range(0, n, chunk_size):
        chunk = highlights[start : start + chunk_size]
        payload = _build_request_payload(chunk, target_role, jd_text, model)
        try:
            resp = _http_post_json(url, payload, api_key, REQUEST_TIMEOUT_SEC)
            got = _extract_rewritten(resp, len(chunk))
        except RuntimeError:
            # 任一 chunk 失败 → 该 chunk 全部降级回原文,继续下一 chunk
            continue

        if got is not None:
            for i, txt in enumerate(got):
                rewritten[start + i] = txt

    # 任一位置没拿到改写 → 回退原文
    return [rewritten[i] if rewritten[i] is not None else highlights[i] for i in range(n)]