"""
LLM 智能改写模块 (Round 2 #3, R3-P 升级, R4-F Function Calling, R5-A Phase 3 evidence)

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

R4-F: Function Calling 协议接入
  - 暴露 1 个工具: evaluate_bullet_jd_match(bullet, jd_focus) → 匹配关键词/缺失关键词/建议
  - tools 字段只在 enable_function_calling=True AND jd_focus is not None 时挂载
    (默认路径字节级一致, 252 老测试不破)
  - LLM 返 tool_calls 时 → _extract_rewritten 返回 None → 走降级原文路径
    (R4-A 才会接 agent loop 真正调工具)

R4-A: Agent Loop (max_step=3) + 单工具约束 + trace 日志
  - 新增 _call_with_agent_loop(): 包装 _call_with_retry 加循环
  - 每个 step 调一次 LLM, 检查 tool_calls; 有工具就 execute 后继续 loop
  - 单步单工具: tool_calls[0] 执行, 其余忽略
  - 网络错误不进 loop, 立即降级
  - 全失败(3 步仍无 output)→ 降级原文
  - 每次 step 写一行 trace 到 backend/logs/agent_trace.log

R5-A Phase 3: 轻量 RAG evidence 约束
  - rewrite_highlights 加 evidence: Optional[list] = None kwarg
  - evidence 非空时:
      1) user_payload 加 "evidence_summary" 字段(summary 文本, ≤2000 字符)
      2) SYSTEM_PROMPT 加第 8 条硬性约束: "只能基于 evidence 中存在的事实改写"
  - evidence=None 时:
      1) 不注入 evidence_summary (字节级一致老路径)
      2) SYSTEM_PROMPT 不变 (字节级一致)
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

# R4-A: Agent Loop 硬上限,防 LLM 一直调工具不输出
# MAX_AGENT_STEPS=0 触发特殊行为 — rewrite_highlights 走 _call_with_retry 老路径
MAX_AGENT_STEPS = 3

# ----------------------------------------------------------------------
# R4-F: Function Calling — 工具 schema (OpenAI 标准 tools 字段格式)
# ----------------------------------------------------------------------
# MVP 只暴露 1 个工具: 评估单条 bullet 跟 JD 关键词的匹配度
# 给 LLM 主动"先看 bullet 跟 JD 差距, 再改写"的能力
# 协议: OpenAI function calling / Anthropic tool_use / MCP 协议栈都走相同 schema 结构
TOOL_EVALUATE_SCHEMA: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "evaluate_bullet_jd_match",
            "description": (
                "评估单条项目 bullet 跟 JD 关键词的匹配度, "
                "返回 bullet 中实际匹配的关键词、缺失关键词和具体改写建议。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "bullet": {
                        "type": "string",
                        "description": "项目亮点 / bullet 文本(待评估的那一条)",
                    },
                    "jd_focus": {
                        "type": "object",
                        "description": (
                            "JD 关键词焦点, 来自上一次匹配的 match_score 结果, "
                            "含 matched / missing / tier_required / tier_preferred"
                        ),
                        "properties": {
                            "matched": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "已匹配的 JD 关键词",
                            },
                            "missing": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "缺失的 JD 关键词",
                            },
                            "tier_required": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "必备关键词(高优先级)",
                            },
                            "tier_preferred": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "加分关键词(低优先级)",
                            },
                        },
                    },
                },
                "required": ["bullet", "jd_focus"],
            },
        },
    }
]


# R3-P: SYSTEM_PROMPT v2 — 加 2 个 few-shot 示例(基础 + jd_focus)
# 改写约束 4 条: 不编造事实 / 长度 20-50 字 / 中文 / 顺序一致
# jd_focus 约束 3 条: matched 必须保留 / 不为凑 missing 改写 / tier 优先级
# R5-A Phase 3: 第 8 条硬性约束 — 只能基于 evidence 中存在的事实改写
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
    "**若提供了 evidence 字段(轻量 RAG, R5-A Phase 3)**:\n"
    "8. **只能基于原 bullet 与 evidence 中存在的事实改写**, 不得引入 evidence 中没有的\n"
    "   数字、技能、公司、项目名;evidence 是事实摘录, 不是改写方向提示\n"
    "   (这条约束优先于 jd_focus 的 missing 倾斜 — 缺事实宁可少关键词也别硬塞)\n"
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


# R5-A Phase 3: evidence 约束后缀 — 当 evidence 非空时拼接(让 SYSTEM_PROMPT 含约束)
# 用单独的常量而非直接改 SYSTEM_PROMPT → 避免 evidence=None 时 SYSTEM_PROMPT 字符串字节级不一致
# 拼接时使用分隔符 (含双换行) → payload 字节级一致
EVIDENCE_CONSTRAINT_SUFFIX = (
    "\n"
    "**evidence 事实约束已激活**: "
    "你只能引用原 bullet 或上面 evidence 列表中已存在的事实点改写。\n"
    "若 evidence 列表为空, 不要编造数字 / 技能名 / 公司名, 保持保守改写。\n"
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
    tools: Optional[list[dict]] = None,
    history_messages: Optional[list[dict]] = None,
    evidence_summary: Optional[str] = None,  # R5-A Phase 3: evidence 摘要 (None 字节级一致)
) -> dict:
    """
    构造 chat/completions 请求体。

    Round 3 I: jd_focus 非 None 时,user message 注入 jd_focus 字段
    (matched / missing / tier_required / tier_preferred),
    引导 LLM 改写方向聚焦 JD 实际关心的关键词。
    jd_focus=None 时(老调用路径 / LLM 未启用焦点)→ user message 跟原 schema 完全一致。

    R3-P: strict_retry=True 时,user message 追加 schema 强约束(第 2 次重试用,
    引导 LLM 修正首次返回的 schema 错误)。

    R4-F: tools 非 None 时,挂载到 payload(OpenAI function calling 标准格式),
    同时设 tool_choice="auto"(LLM 决定要不要调工具)。tools=None → 老路径字节级一致。

    R4-M: history_messages 非 None 时,prepend 到 messages(system 之后, current user 之前)。
    history_messages=None → 老路径字节级一致(messages 只有 system + current user)。

    R5-A Phase 3: evidence_summary 非 None 时,
      1) user_payload 加 evidence_summary 字段 (LLM 改写时参考的事实摘录)
      2) system prompt 末尾追加 EVIDENCE_CONSTRAINT_SUFFIX (激活"只能基于 evidence 改写"约束)
    evidence_summary=None → 老路径字节级一致 (payload schema 不变, system prompt 不变)。
    """
    user_payload: dict = {
        "target_role": target_role,
        "jd_context": jd_text or "",
        "bullets": highlights,
    }
    if jd_focus is not None:
        user_payload["jd_focus"] = jd_focus

    # R5-A Phase 3: evidence 字段注入 (放在 jd_focus 后)
    if evidence_summary is not None:
        user_payload["evidence_summary"] = evidence_summary

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

    current_user_msg = {
        "role": "user",
        "content": json.dumps(user_payload, ensure_ascii=False),
    }

    # R5-A Phase 3: system prompt 在 evidence_summary 非空时追加约束后缀
    if evidence_summary is not None:
        system_content = SYSTEM_PROMPT + EVIDENCE_CONSTRAINT_SUFFIX
    else:
        system_content = SYSTEM_PROMPT

    # R4-M: 拼装 messages — history_messages 非空时插在 system 和 current user 之间
    if history_messages:
        messages: list[dict] = (
            [{"role": "system", "content": system_content}]
            + list(history_messages)
            + [current_user_msg]
        )
    else:
        # 老路径: 字节级一致 (system + current user)
        messages = [
            {"role": "system", "content": system_content},
            current_user_msg,
        ]

    payload: dict = {
        "model": model,
        "temperature": 0.3,
        "response_format": {"type": "json_object"},
        "messages": messages,
    }
    # R4-F: Function Calling 挂载
    # 协议扩展: tools / tool_choice 是 OpenAI 标准, 不传时老路径字节级一致
    if tools is not None:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    return payload


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

    R4-F 升级: 检测 tool_calls — 当 LLM 决定调工具而非直接返 rewritten 时,
    视为"未交付最终改写" → 返回 None(让 caller 走降级原文路径)。
    R4-A 才会接 agent loop 真正执行工具调用。
    """
    parsed_obj: Optional[dict | list] = None

    if isinstance(response, list):
        parsed_obj = response
    elif isinstance(response, dict):
        # OpenAI 标准 chat/completions 响应: choices[0].message.{content | tool_calls}
        choices = response.get("choices") or []
        if choices and isinstance(choices, list):
            msg = choices[0].get("message") or {}

            # R4-F: tool_calls 优先于 content — LLM 决定调工具, 没有最终改写
            tool_calls = msg.get("tool_calls")
            if tool_calls:
                return None  # R4-A agent loop 才处理工具执行

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


def _get_session_history(session_id: Optional[str]) -> list[dict]:
    """
    R4-M: 从 session.py 拉历史 messages(供 LLM payload prepend)。

    session_id 为 None / 空字符串 / 不存在 → 返空 list(走老路径字节级一致)。

    不抛 — session 内容由调用方负责,本函数只是安全拉取。
    """
    if not session_id:
        return []
    # 局部 import 防循环依赖(generator.py -> llm_rewriter.py -> session.py 是单向 OK,
    # 但仍用 lazy import 让测试 mock 更干净)
    from core import session as _session
    return _session.get_messages(session_id)


def rewrite_highlights(
    highlights: list[str],
    target_role: str,
    jd_text: str = "",
    max_per_call: int = 6,
    jd_focus: Optional[dict] = None,
    enable_function_calling: bool = False,
    session_id: Optional[str] = None,
    evidence: Optional[list] = None,  # R5-A Phase 3: list[EvidenceSnippet], None 字节级一致
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

    R4-F: enable_function_calling(默认 False)开启时,挂载 TOOL_EVALUATE_SCHEMA;
    仅在 enable_function_calling=True AND jd_focus is not None 时挂载
    (空 jd_focus 没工具执行的意义,走老路径字节级一致)。
    enable_function_calling=False → 字节级一致老路径(252 测试不破)。

    R4-A: enable_function_calling=True AND jd_focus is not None AND MAX_AGENT_STEPS > 0
    时,走 _call_with_agent_loop (Agent Loop, max_step=3, 单工具约束, trace 日志);
    其他情况走 _call_with_retry 老路径(保留 R3-P retry 行为)。

    R4-M: session_id(可选)非空时,从 session.py 拉历史 messages 拼到 LLM messages
    (system 之后, current user 之前)。session_id=None(默认)→ 不拼接,老路径字节级一致。
    session 内容由调用方(API 层)负责不写 PII。

    R5-A Phase 3: evidence(可选, list[EvidenceSnippet])非空时,
    把 evidence 转成 summary 文本, 注入 user_payload + 激活 SYSTEM_PROMPT 第 8 条约束
    ("只能基于 evidence 中存在的事实改写")。
    evidence=None → 老路径字节级一致 (不注入 summary, 不改 system prompt)。
    """
    if not highlights:
        return highlights
    if not is_llm_enabled():
        return highlights

    # R4-M: 一次性拉 session 历史(同 session 多次 chunk 调用复用同一份 history)
    history_messages = _get_session_history(session_id)

    # R5-A Phase 3: 把 evidence list 转成 summary 文本 (供 prompt 注入)
    # evidence=None → summary=None → payload / system 字节级一致
    # evidence=[] → summary="" → 不激活约束 (空 evidence 等价于"无 evidence", 跟 None 一致)
    evidence_summary: Optional[str] = None
    if evidence is not None:
        # 局部 import 避免循环(llm_rewriter 不依赖 evidence 模块顶级路径)
        from core.evidence import _summarize_evidence_for_prompt, EvidenceSnippet
        # 防御: caller 可能传 dict list (来自 workflow), 需转 EvidenceSnippet
        snippet_objs: list = []
        for ev in evidence:
            if isinstance(ev, EvidenceSnippet):
                snippet_objs.append(ev)
            elif isinstance(ev, dict):
                # 来自 evidence_to_dict_list 的输出 → 重建 EvidenceSnippet
                try:
                    snippet_objs.append(EvidenceSnippet(
                        source_type=str(ev.get("source_type", "")),
                        source_id=str(ev.get("source_id", "")),
                        text=str(ev.get("text", "")),
                        matched_keywords=tuple(ev.get("matched_keywords") or []),
                        confidence=float(ev.get("confidence", 0.0)),
                    ))
                except Exception:
                    continue  # 防御性: 单条解析失败跳过
            else:
                continue
        evidence_summary = _summarize_evidence_for_prompt(snippet_objs)
        # 空 summary (无 evidence 或全空) → 视同 None, 不激活约束
        if not evidence_summary:
            evidence_summary = None

    n = len(highlights)
    chunk_size = max(1, max_per_call)
    rewritten: list[Optional[str]] = [None] * n

    api_key = _env("LLM_API_KEY")
    base_url = _env("LLM_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
    model = _env("LLM_MODEL", DEFAULT_MODEL)
    url = f"{base_url}/chat/completions"

    # R4-A: 决定走 agent loop 还是老路径
    # 三个条件全部满足才进 loop:
    #   1) enable_function_calling=True (用户明确开启)
    #   2) jd_focus is not None (有改写焦点 — 没焦点调工具没意义)
    #   3) MAX_AGENT_STEPS > 0 (loop 没关闭, 测试场景)
    use_agent_loop = (
        enable_function_calling
        and jd_focus is not None
        and MAX_AGENT_STEPS > 0
    )

    for start in range(0, n, chunk_size):
        chunk = highlights[start : start + chunk_size]
        if use_agent_loop:
            # R4-A: agent loop 路径(单步单工具, max_step=3, trace 日志)
            got = _call_with_agent_loop(
                url, api_key, model, chunk, target_role, jd_text, jd_focus,
                history_messages=history_messages,
                evidence_summary=evidence_summary,  # R5-A Phase 3
            )
        else:
            # 老路径: 走 _call_with_retry (保留 R3-P retry)
            got = _call_with_retry(
                url, api_key, model, chunk, target_role, jd_text, jd_focus,
                enable_function_calling=enable_function_calling,
                history_messages=history_messages,
                evidence_summary=evidence_summary,  # R5-A Phase 3
            )

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
    *,
    enable_function_calling: bool = False,
    history_messages: Optional[list[dict]] = None,
    evidence_summary: Optional[str] = None,  # R5-A Phase 3: 透传到 _build_request_payload
) -> Optional[list[str]]:
    """
    R3-P: 单次 chunk 调用 + 失败 retry 一次。
    流程:
      1. 正常请求 → _extract_rewritten 成功 → 返回
      2. 正常请求 → 解析失败 → strict_retry=True 再试一次
      3. retry 也失败 → 返回 None(降级原文)

    R4-F: enable_function_calling=True AND jd_focus is not None 时,
    把 TOOL_EVALUATE_SCHEMA 挂到 payload(LLM 可主动调 evaluate_bullet_jd_match)。
    R4-A 才会接 agent loop 真正执行工具调用 — 本轮只是把工具暴露给 LLM。

    R4-M: history_messages 非 None 时透传给 _build_request_payload,拼到 messages。
    history_messages=None → 字节级一致老路径。

    R5-A Phase 3: evidence_summary 非 None 时透传给 _build_request_payload,
    注入 user_payload + 激活 system prompt 第 8 条约束。None → 字节级一致老路径。
    """
    # R4-F: 决定是否挂载 tools
    tools: Optional[list[dict]] = None
    if enable_function_calling and jd_focus is not None:
        tools = TOOL_EVALUATE_SCHEMA

    payload = _build_request_payload(
        chunk, target_role, jd_text, model, jd_focus=jd_focus, tools=tools,
        history_messages=history_messages,
        evidence_summary=evidence_summary,  # R5-A Phase 3
    )
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

    # R4-F: retry 时也保留 tools 挂载(LLM 第二次也允许调工具)
    strict_payload = _build_request_payload(
        chunk, target_role, jd_text, model, jd_focus=jd_focus,
        strict_retry=True, tools=tools,
        evidence_summary=evidence_summary,  # R5-A Phase 3: retry 时也保留 evidence
    )
    try:
        resp2 = _http_post_json(url, strict_payload, api_key, REQUEST_TIMEOUT_SEC)
        return _extract_rewritten(resp2, len(chunk))
    except RuntimeError:
        return None


# ======================================================================
# R4-A: Agent Loop (max_step=3) + 单工具约束 + trace 日志
# ======================================================================
def _extract_message_for_history(response: dict) -> Optional[dict]:
    """
    R4-A: 从 LLM 响应里提取 assistant message(整段),供 agent loop 拼接到 messages 历史。
    跟 _extract_rewritten 不同 — 后者只取最终改写,前者保留 tool_calls 用于回放。
    """
    if not isinstance(response, dict):
        return None
    choices = response.get("choices") or []
    if not choices or not isinstance(choices, list):
        return None
    msg = choices[0].get("message") or {}
    # 必须有 content 或 tool_calls(任一存在)才算合法 message
    if msg.get("content") is not None or msg.get("tool_calls") is not None:
        return msg
    return None


def _execute_tool_call(
    tool_call: dict,
    chunk: list[str],
    jd_focus: Optional[dict],
) -> dict:
    """
    R4-A: 执行 tool_calls[0] 的工具调用(MVP 只支持 evaluate_bullet_jd_match)。

    Args:
        tool_call:  LLM 返的 tool_call dict (含 id / type / function.{name, arguments})
        chunk:      当前改写的 bullets 列表(bullet 参数缺省时兜底用 chunk[0])
        jd_focus:   LLM 改写方向的焦点(工具缺 jd_focus 时兜底用)

    Returns:
        工具执行结果 dict(JSON 友好)— 失败也返回 dict(带 error 字段)
        不会抛异常(MVP 设计:工具执行失败 → 返回错误 dict → agent loop 继续)

    工具注册表(显式枚举 — 加新工具时这里加 case):
      - evaluate_bullet_jd_match: 调 core.jd_parser.evaluate_bullet_jd_match
      - 未知工具: 返回 {"error": "unknown tool: <name>"}
    """
    # 局部 import 避免循环(jd_parser 引用了 generator 链)
    from core.jd_parser import evaluate_bullet_jd_match

    fn = tool_call.get("function") or {}
    name = fn.get("name", "")
    args_str = fn.get("arguments", "{}")

    # 1) 解析 arguments
    if isinstance(args_str, dict):
        args = args_str
    elif isinstance(args_str, str):
        try:
            args = json.loads(args_str) if args_str.strip() else {}
        except json.JSONDecodeError:
            return {"error": f"工具 {name} arguments 解析失败"}
    else:
        args = {}

    # 2) 工具分发
    if name == "evaluate_bullet_jd_match":
        bullet = args.get("bullet", "")
        # bullet 参数缺省 → 兜底用 chunk[0](LLM 偶尔会忘记传 bullet)
        if not bullet and chunk:
            bullet = chunk[0]
        focus = args.get("jd_focus") or jd_focus or {}
        try:
            return evaluate_bullet_jd_match(bullet, focus)
        except Exception as e:
            return {"error": f"evaluate_bullet_jd_match 失败: {type(e).__name__}"}

    return {"error": f"unknown tool: {name}"}


def _call_with_agent_loop(
    url: str,
    api_key: str,
    model: str,
    chunk: list[str],
    target_role: str,
    jd_text: str,
    jd_focus: Optional[dict],
    *,
    history_messages: Optional[list[dict]] = None,
    evidence_summary: Optional[str] = None,  # R5-A Phase 3: 透传到 initial_payload
) -> Optional[list[str]]:
    """
    R4-A: Agent Loop — 包装 _call_with_retry 的能力, 加循环让 LLM 可多轮调工具。

    流程(伪代码):
      for step in range(MAX_AGENT_STEPS):  # 3
          resp = LLM(messages + tools, ...)
          if resp 有 tool_calls:
              tool_result = execute(tool_calls[0])  # 单步单工具
              messages.append(tool_result)
              continue
          else:
              extracted = _extract_rewritten(resp, expected_count)
              if extracted: return extracted
              break  # 失败 → 降级原文
      return None  # 全失败降级

    关键约束:
      - max_step=3 硬上限, 防 LLM 一直调工具不输出
      - 单步单工具(只取 tool_calls[0]), 避免单轮 token 爆
      - 网络错误不进入 loop(避免 token 浪费), 立即降级
      - trace 每次 step 写一行: session_id / step / tool_name / latency_ms / outcome

    R4-M: history_messages 非 None 时透传给 _build_request_payload 拼到 messages
    (system 之后, current user 之前)。trace 的 session_id 改用真实 session_id
    (或 fallback 到临时 uuid — 仅当 history_messages=None 时)。

    R5-A Phase 3: evidence_summary 非 None 时透传给 _build_request_payload,
    initial system+user 已含 evidence 约束;后续 step 的 payload 复用 messages
    (含 system+history+initial_user), evidence 不重新注入(避免 prompt 重复)。
    """
    # 局部 import — logger 是稳定依赖, 这里 import 仅为避免循环(lazy 安全)
    import time
    import uuid

    from core.logger import log_agent_trace

    # 1) 构造 messages 列表(从 _build_request_payload 拿初始 system+user)
    initial_payload = _build_request_payload(
        chunk, target_role, jd_text, model,
        jd_focus=jd_focus, tools=TOOL_EVALUATE_SCHEMA,
        history_messages=history_messages,
        evidence_summary=evidence_summary,  # R5-A Phase 3
    )
    messages: list[dict] = list(initial_payload["messages"])

    # 2) session_id 优先级: 真实 session_id > 临时 uuid(per-call fallback)
    #    历史消息存在时, 用真实 session_id 便于 trace 关联
    if history_messages:
        # 找 caller 传入的 session_id 不容易(函数签名没暴露), 用 messages 长度 proxy
        # 这里用稳定 hash 避免每次都换 uuid
        session_id = "agent_session"
    else:
        session_id = f"agent_{uuid.uuid4().hex[:8]}"

    # 3) 主循环
    for step in range(MAX_AGENT_STEPS):
        t0 = time.time()

        # 3a) 构造当前 step 的 payload(messages 累积, tools 始终挂载)
        payload = {
            "model": model,
            "temperature": 0.3,
            "response_format": {"type": "json_object"},
            "messages": messages,
            "tools": TOOL_EVALUATE_SCHEMA,
            "tool_choice": "auto",
        }

        # 3b) 调一次 LLM(不 retry, 节省 token — loop 已经给了 3 次机会)
        try:
            resp = _http_post_json(url, payload, api_key, REQUEST_TIMEOUT_SEC)
        except RuntimeError:
            # 网络错误 → 不重试, 立即降级
            latency_ms = int((time.time() - t0) * 1000)
            log_agent_trace(session_id, step, "no_tool", latency_ms, "network_error_fallback")
            return None

        latency_ms = int((time.time() - t0) * 1000)

        # 3c) 检查 tool_calls
        msg = _extract_message_for_history(resp)
        if msg is None:
            # 响应格式异常(无 content 也无 tool_calls) → 降级
            log_agent_trace(session_id, step, "no_tool", latency_ms, "schema_fail_fallback")
            return None

        tool_calls = msg.get("tool_calls")
        if tool_calls:
            # 单步单工具约束: 只执行 tool_calls[0]
            tc = tool_calls[0]
            fn = tc.get("function") or {}
            tool_name = fn.get("name", "unknown")

            # 3d) 执行工具
            tool_result = _execute_tool_call(tc, chunk, jd_focus)

            # 3e) 把 assistant message + tool 响应拼到 messages
            messages.append({
                "role": "assistant",
                "content": msg.get("content") or "",
                "tool_calls": tool_calls,
            })
            messages.append({
                "role": "tool",
                "tool_call_id": tc.get("id", ""),
                "content": json.dumps(tool_result, ensure_ascii=False),
            })

            log_agent_trace(session_id, step, tool_name, latency_ms, "tool_executed")
            continue  # 进入下一 step

        # 3f) 无 tool_calls → 提取 rewritten
        extracted = _extract_rewritten(resp, len(chunk))
        if extracted is not None:
            log_agent_trace(session_id, step, "no_tool", latency_ms, "success_rewrite")
            return extracted

        # 3g) 解析失败 → 降级(不 retry, 节省 token)
        log_agent_trace(session_id, step, "no_tool", latency_ms, "schema_fail_fallback")
        return None

    # 4) MAX_AGENT_STEPS 用完仍无 output → 降级
    log_agent_trace(session_id, MAX_AGENT_STEPS, "no_tool", 0, "max_step_exhausted")
    return None