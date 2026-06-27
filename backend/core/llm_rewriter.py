"""
LLM 智能改写模块 (Round 2 #3, R3-P 升级)

设计原则:
  - MVP: 没 key / 没启用 / 调用失败 → 全部静默降级,绝不抛异常给上层
  - 只走 OpenAI 兼容 HTTP 协议,纯 stdlib (urllib + json),不引入第三方包
  - 每次最多 max_per_call 条,剩余保留原文,避免单次 prompt 太大超时/超 token
  - 不写任何调用日志到磁盘 (避免 PII 泄漏)

R3-P 升级:
  - SYSTEM_PROMPT v2: 加 few-shot 示例(2 个, 基础改写 + jd_focus 改写)
  - 显式 JSON schema: {"rewritten": [{"index": i, "text": "..."}]} 唯一规范
  - 失败 retry 一次(更严格指令);仍失败 → 降级原文
  - 旧 schema(顶层 array / {"rewritten": [...]} / {"bullets": [...]})保留兼容
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

# R3-P: max 1 retry on invalid response(总最多 2 次尝试,避免 key 成本失控)
MAX_RETRY_ON_INVALID = 1

# R3-P: SYSTEM_PROMPT v2 — 加 2 个 few-shot 示例(基础 + jd_focus)
# 改写约束 4 条: 不编造事实 / 长度 20-50 字 / 中文 / 顺序一致
# jd_focus 约束 3 条: matched 必须保留 / 不为凑 missing 改写 / tier 优先级
SYSTEM_PROMPT = (
    "你是简历润色专家,根据目标岗位改写项目亮点(bullets 列表)。\n"
    "\n"
    "**硬性约束**:\n"
    "1. **绝不**编造事实: 改写后的句子必须能在原 bullet 找到对应事实点\n"
    "2. 每条 bullet 一句话,中文,20-50 字\n"
    "3. 输出 JSON 格式必须严格按 schema:\n"
    '   {"rewritten": [{"index": 0, "text": "..."}, {"index": 1, "text": "..."}, ...]}\n'
    "   - index 从 0 开始,顺序与输入 bullets 完全一致\n"
    "   - 数量必须等于输入 bullets 的数量,不可增删\n"
    "   - text 是字符串,不能是空字符串\n"
    "\n"
    "**若提供了 jd_focus 字段**:\n"
    "4. matched 关键词在改写后必须仍可被识别(术语不要替换为同义但不等价的词)\n"
    "5. **不要**为凑 missing 关键词而编造事实;missing 仅作为措辞倾斜方向参考,无事实不补\n"
    "6. tier_required 的关键词在 bullet 中应至少出现一次(无事实依据则不改写为该关键词)\n"
    "7. tier_preferred 关键词为加分项,尽量靠拢,做不到不强求\n"
    "\n"
    "## 示例 1: 基础改写(无 jd_focus)\n"
    "输入 bullets:\n"
    '  ["做了 100 题评测,准确率 90%","优化了模型推理速度,提升 20%","参加了 ACM 比赛"]\n'
    "target_role: tech_metric\n"
    "输出:\n"
    '  {"rewritten": [\n'
    '    {"index": 0, "text": "构建 100 题评测集,模型准确率达 90%,验证评估方法可靠性"},\n'
    '    {"index": 1, "text": "优化模型推理路径,推理速度提升 20%,降低服务响应延迟"},\n'
    '    {"index": 2, "text": "参与 ACM 区域赛,负责算法设计与代码实现"}]}\n'
    "\n"
    "## 示例 2: jd_focus 改写(投 LLM 评测岗,缺失\"Prompt\")\n"
    "输入 bullets:\n"
    '  ["审核了 200 条 AI 输出,错误率低","整理了 badcase 报告","写了测试用例"]\n'
    "target_role: tech_metric\n"
    "jd_focus: {\"matched\":[\"LLM\",\"评测\"],\"missing\":[\"Prompt\"],\"tier_required\":[\"LLM\"],\"tier_preferred\":[\"评测\"]}\n"
    "输出:\n"
    '  {"rewritten": [\n'
    '    {"index": 0, "text": "基于 LLM 输出特性审核 200 条 AI 内容,识别错误并标注风险等级"},\n'
    '    {"index": 1, "text": "系统整理 badcase 报告,分类高频错误模式,辅助评测迭代"},\n'
    '    {"index": 2, "text": "运用结构化 Prompt 设计测试用例,覆盖典型与边缘场景"}]}\n'
    "(说明: index 2 的 \"Prompt\" 关键词是顺着原文\"写了测试用例\"自然延伸,不是为凑关键词而硬塞)\n"
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
    jd_focus: Optional[dict] = None,
    *,
    strict_retry: bool = False,
) -> dict:
    """
    构造 chat/completions 请求体。

    Round 3 I: jd_focus 非 None 时,user message 注入 jd_focus 字段
    (matched / missing / tier_required / tier_preferred),
    引导 LLM 改写方向聚焦 JD 实际关心的关键词。
    jd_focus=None 时(老调用路径 / LLM 未启用焦点)→ user message 跟原 schema 完全一致。

    R3-P: strict_retry=True 时,user message 追加 schema 强约束(第 2 次重试用,
    引导 LLM 修正首次返回的 schema 错误)。
    """
    user_payload: dict = {
        "target_role": target_role,
        "jd_context": jd_text or "",
        "bullets": highlights,
    }
    if jd_focus is not None:
        user_payload["jd_focus"] = jd_focus

    if strict_retry:
        user_payload["_retry_hint"] = (
            f"你刚才的返回不符合 schema 约束。必须严格按以下格式返回:\n"
            f'{{"rewritten": [{{"index": 0, "text": "..."}}, '
            f'{{"index": 1, "text": "..."}}, ..., '
            f'{{"index": {len(highlights) - 1}, "text": "..."}}]}}\n'
            f"- index 必须从 0 到 {len(highlights) - 1},不重复,不缺失\n"
            f"- text 必须是字符串,不能为空\n"
            f"- 数量必须等于 {len(highlights)},与输入 bullets 一一对应"
        )

    return {
        "model": model,
        "temperature": 0.3,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": json.dumps(user_payload, ensure_ascii=False),
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
    R3-P 升级: 优先识别新 schema {"rewritten": [{"index": i, "text": "..."}]},
    旧 schema 保留兼容({"rewritten": [...]} / {"bullets": [...]} / 顶层 array)。
    任一条 schema 命中且 length/index/text 全部合法才返回,否则 None。
    """
    parsed_obj: Optional[dict | list] = None

    if isinstance(response, list):
        parsed_obj = response
    elif isinstance(response, dict):
        # OpenAI 标准 chat/completions 响应: choices[0].message.content 是 str
        choices = response.get("choices") or []
        if choices and isinstance(choices, list):
            msg = choices[0].get("message") or {}
            content = msg.get("content")
            if isinstance(content, str):
                try:
                    parsed_obj = json.loads(content)
                except json.JSONDecodeError:
                    parsed_obj = None
            elif isinstance(content, list):
                parsed_obj = content
        # 兼容直传 {"rewritten": [...]}
        if parsed_obj is None:
            for key in ("rewritten", "bullets", "items"):
                if key in response:
                    parsed_obj = response
                    break

    if parsed_obj is None:
        return None

    # 优先尝试新 schema: {"rewritten": [{"index": i, "text": "..."}]}
    if isinstance(parsed_obj, dict):
        rewritten = parsed_obj.get("rewritten")
        if isinstance(rewritten, list) and _validate_new_schema(rewritten, expected_count):
            return [item["text"].strip() for item in rewritten]

    # Fallback: 旧 schema — 顶层 array
    if isinstance(parsed_obj, list):
        if _validate_legacy_schema(parsed_obj, expected_count):
            return [x.strip() for x in parsed_obj]

    # Fallback: 旧 schema — {"rewritten": [...]} / {"bullets": [...]} / {"items": [...]}(list of str)
    if isinstance(parsed_obj, dict):
        for key in ("rewritten", "bullets", "items", "result"):
            v = parsed_obj.get(key)
            if isinstance(v, list) and _validate_legacy_schema(v, expected_count):
                return [x.strip() for x in v]

    return None


def _validate_new_schema(items: list, expected_count: int) -> bool:
    """
    验证新 schema: [{"index": i, "text": "..."}, ...]
    - 长度等于 expected_count
    - 每个 item 是 dict,含 int index (0..expected_count-1 唯一)+ non-empty str text
    - index 必须是 0..expected_count-1,无重复(隐含顺序)
    """
    if len(items) != expected_count:
        return False
    seen_indexes: set[int] = set()
    for item in items:
        if not isinstance(item, dict):
            return False
        idx = item.get("index")
        text = item.get("text")
        if not isinstance(idx, int) or idx < 0 or idx >= expected_count:
            return False
        if idx in seen_indexes:
            return False  # 重复 index
        seen_indexes.add(idx)
        if not isinstance(text, str) or not text.strip():
            return False
    return True


def _validate_legacy_schema(items: list, expected_count: int) -> bool:
    """
    验证旧 schema: list of str
    - 长度等于 expected_count
    - 每个 item 是 non-empty str
    """
    if len(items) != expected_count:
        return False
    return all(isinstance(x, str) and x.strip() for x in items)


def rewrite_highlights(
    highlights: list[str],
    target_role: str,
    jd_text: str = "",
    max_per_call: int = 6,
    jd_focus: Optional[dict] = None,
) -> list[str]:
    """
    把 highlights 按 target_role 视角改写。
    - 输入输出长度一致。
    - 没启用 / 调用失败 / 超时 / JSON 解析失败 / 长度对不上 → 返回原 highlights (不抛)。
    - 每次最多处理 max_per_call 条,剩余保持原样。

    Round 3 I: jd_focus(可选)注入 user message 引导改写方向。
    - jd_focus=None(默认)→ user message schema 跟原版完全一致(向后兼容,字节级一致)
    - jd_focus=dict → 注入到 user message(供 LLM 倾斜方向)

    R3-P: 失败 retry 一次(strict_retry=True,更严格 schema 指令);
    仍失败 → 降级原文(单次 chunk 全部回退)。
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
        got = _call_with_retry(url, api_key, model, chunk, target_role, jd_text, jd_focus)

        if got is not None:
            for i, txt in enumerate(got):
                rewritten[start + i] = txt

    # 任一位置没拿到改写 → 回退原文
    return [rewritten[i] if rewritten[i] is not None else highlights[i] for i in range(n)]


def _call_with_retry(
    url: str,
    api_key: str,
    model: str,
    chunk: list[str],
    target_role: str,
    jd_text: str,
    jd_focus: Optional[dict],
) -> Optional[list[str]]:
    """
    R3-P: 单次 chunk 调用 + 失败 retry 一次。
    流程:
      1. 正常请求 → _extract_rewritten 成功 → 返回
      2. 正常请求 → 解析失败 → strict_retry=True 再试一次
      3. retry 也失败 → 返回 None(降级原文)
    """
    payload = _build_request_payload(chunk, target_role, jd_text, model, jd_focus=jd_focus)
    try:
        resp = _http_post_json(url, payload, api_key, REQUEST_TIMEOUT_SEC)
        got = _extract_rewritten(resp, len(chunk))
        if got is not None:
            return got
    except RuntimeError:
        # 网络/超时/HTTP 错误 → 不 retry(浪费 token),直接降级
        return None

    # 解析成功但 schema 校验失败 → retry 一次
    if MAX_RETRY_ON_INVALID <= 0:
        return None

    strict_payload = _build_request_payload(
        chunk, target_role, jd_text, model, jd_focus=jd_focus, strict_retry=True,
    )
    try:
        resp2 = _http_post_json(url, strict_payload, api_key, REQUEST_TIMEOUT_SEC)
        return _extract_rewritten(resp2, len(chunk))
    except RuntimeError:
        return None