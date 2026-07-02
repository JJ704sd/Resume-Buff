"""
Round 6-D: 机械拆分 LLM slot 抽取模块(行为不变)。

设计原则(R6-D 拆分边界):
  - 不 import core.interview_agent(运行时, 仅 TYPE_CHECKING 用类型注解, 防循环依赖)
  - 不 import core.llm_rewriter / core.agent_workflow / core.agent_tools
    / core.evidence / core.tool_schema / core.session(R5-E 字节级稳定边界)
  - 只 import stdlib + core.interview_prompts 公开常量
  - 反向依赖: interview_agent.py 从本模块 import LLM helper 给规则版共用
    + 重导出本模块符号保持向后兼容(test_interview_agent / scripts 等仍
    可 `from core.interview_agent import _attach_llm_slot_meta`)

包含符号:
  - mode 决策常量: INTERVIEW_MODE_RULES / INTERVIEW_MODE_LLM_ASSISTED
  - mode warning:   INTERVIEW_LLM_NO_KEY_WARNING
  - 默认 base_url / model 常量(plan §4.3):
      _INTERVIEW_LLM_DEFAULT_BASE_URL / _INTERVIEW_LLM_DEFAULT_MODEL
  - slot_meta confidence 常量(spec §5.2):
      INTERVIEW_SLOT_META_MIN_CONFIDENCE / INTERVIEW_SLOT_META_MAX_CONFIDENCE
      INTERVIEW_SLOT_META_RULES_CONFIDENCE_FALLBACK
      INTERVIEW_SLOT_META_LLM_DEFAULT_CONFIDENCE
  - R6-C.3 可观测性 schema: INTERVIEW_OBSERVABILITY_SCHEMA
  - 私有 helper(spec §5.2):
      _validate_confidence / _compute_source_span_hash / _make_slot_meta
  - API mode 决策(spec §5.3):
      _has_llm_api_key / _decide_interview_mode
  - LLM 配置 + 抽取主链路(plan §4.4 + R6-B Phase 1 §5.2 + R6-C.3):
      _resolve_interview_llm_config
      _validate_llm_extraction_payload
      _call_llm_for_slot_extraction
      _try_parse_llm_content
      _extract_slots_via_llm
      _attach_llm_slot_meta

行为不变保证(R6-D):
  - 所有 docstring 完整搬运, 仅调整模块级引用关系
  - 所有调用站点的 monkeypatch / mock 路径改为 core.interview_llm.* 命名空间
    (test_interview_agent.py 中相关 case 已平移到 test_interview_llm.py)
  - 不引入新依赖 / 不改 prompt / 不改默认 rules 路径
  - 老路径(llm_enabled=False / 默认)字节级一致, 不调本模块任何 LLM 函数
"""
from __future__ import annotations

import hashlib
import json
import os
import urllib.error
import urllib.request
from typing import TYPE_CHECKING, Any

from core.interview_prompts import (
    INTERVIEW_LLM_TIMEOUT_SEC,
    SLOT_EXTRACTION_SYSTEM_PROMPT,
    SLOT_LIST_KEYS,
    SLOT_STRING_KEYS,
)

if TYPE_CHECKING:
    # 仅用于类型注解, 运行时**不**import core.interview_agent(防循环依赖)。
    # interview_agent.py 在本模块之后 import, 故此处 TYPE_CHECKING 块安全。
    from core.interview_agent import InterviewSession


# ----------------------------------------------------------------------
# R6-A Phase 4: LLM slot 抽取本地常量(plan §4.3 配置口径)
# ----------------------------------------------------------------------
# 注: 这些常量值必须跟 core.llm_rewriter.DEFAULT_BASE_URL / DEFAULT_MODEL
# 字节级一致(由 tests/test_interview_llm.py 里的
# test_interview_llm_defaults_match_llm_rewriter 锁死)。本模块
# **不**直接 import llm_rewriter(R5-E 字节级稳定边界 — 文件任意位置不能出现
# `from core.llm_rewriter import ...` / `import core.llm_rewriter`)。

_INTERVIEW_LLM_DEFAULT_BASE_URL: str = "https://api.openai.com/v1"
"""LLM slot 抽取默认 base URL(plan §4.3) — 跟 core.llm_rewriter.DEFAULT_BASE_URL 同步。"""

_INTERVIEW_LLM_DEFAULT_MODEL: str = "gpt-4o-mini"
"""LLM slot 抽取默认 model(plan §4.3) — 跟 core.llm_rewriter.DEFAULT_MODEL 同步。"""


# ----------------------------------------------------------------------
# R6-B Phase 2: API mode 开关(spec §5.3 + §2.2)
# ----------------------------------------------------------------------
INTERVIEW_LLM_NO_KEY_WARNING: str = "智能抽取不可用, 已使用规则模式"
"""enable_interview_llm=True 但 env 无 LLM_API_KEY 时返回给前端的 warning 文案。"""

INTERVIEW_MODE_RULES: str = "rules"
"""mode 取值: 规则抽取路径(spec §5.3 限定值之一)。"""

INTERVIEW_MODE_LLM_ASSISTED: str = "llm_assisted"
"""mode 取值: LLM 辅助抽取路径(spec §5.3 限定值之一)。"""


# ----------------------------------------------------------------------
# R6-B Phase 1: slot_meta confidence 常量(spec §5.2)
# ----------------------------------------------------------------------
# 注意: INTERVIEW_SLOT_META_MAX 和 INTERVIEW_SLOT_META_RULES_CONFIDENCE_HIT 留在
# core.interview_agent(供规则版 / _append_slot_meta 用)。本模块只需要 fallback 常量
# + 范围常量 — fallback 路径要拼出"未识别走默认"的 meta。

INTERVIEW_SLOT_META_MIN_CONFIDENCE: float = 0.0
INTERVIEW_SLOT_META_MAX_CONFIDENCE: float = 1.0
"""confidence 合法范围 [0.0, 1.0]。bool 被拒绝(spec §5.2)。"""

INTERVIEW_SLOT_META_RULES_CONFIDENCE_FALLBACK: float = 0.40
"""规则抽取 fallback(没命中关键词, 走原文 fallback)时的 confidence 默认值。"""

INTERVIEW_SLOT_META_LLM_DEFAULT_CONFIDENCE: float = 0.60
"""LLM 未提供 confidence 时的默认值。"""


# ----------------------------------------------------------------------
# R6-C.3: LLM 抽取可观测性 schema(供 tests + scripts 引用)
# ----------------------------------------------------------------------
INTERVIEW_OBSERVABILITY_SCHEMA: dict[str, str] = {
    "slot_source_breakdown": "dict[str, int] — {rules: N, llm: M, mixed: K}",
    "llm_parse_retry_count": "int — 累计 JSON parse / schema retry 次数",
    "llm_to_rules_slot_fallback_count": "int — 累计 LLM 失败 fallback 规则版次数",
}
"""R6-C.3 LLM 抽取可观测性字段 schema(测试 + scripts 引用)。

边界:
  - 3 个字段全部存在默认值, 老测试构造 InterviewSession 时关键字缺省即可
  - 老路径(llm_enabled=False)字节级一致: 3 字段保持 0 / {} / {}
  - 字段值不写 user_message / source_span / draft_card / API key / prompt 正文
"""


# ----------------------------------------------------------------------
# R6-B Phase 1: slot_meta helper(spec §5.2) — 通用工具, 规则版 + LLM 版共用
# ----------------------------------------------------------------------
def _validate_confidence(value: Any) -> float | None:
    """
    校验 confidence 是否合法(spec §5.2):
      - 必须是 0.0-1.0 的 number
      - bool 是 int 子类, 必须**显式拒绝**(防止 True/False 被当成 1.0/0.0)

    返回:
      - 合法 → float(value)
      - 非法 → None(caller 决定 fallback 默认值)
    """
    # bool 先排除(防止 True/False 走 int 分支)
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        f = float(value)
        if INTERVIEW_SLOT_META_MIN_CONFIDENCE <= f <= INTERVIEW_SLOT_META_MAX_CONFIDENCE:
            return f
        return None
    return None


def _compute_source_span_hash(span: str | None) -> tuple[str | None, int | None]:
    """
    把 source_span 字符串转成 sha256 hash + length(spec §5.2)。

    隐私边界:
      - 输入 span 仅在本函数内访问, 函数返回后丢弃
      - 返回值只含 hash 字符串前缀 + 整数 length
      - 永不入 caller 的 session / trace / API response

    返回:
      - 合法 string → ("sha256:" + 16 字符 hex, len(span))
      - 空 / 非 string → (None, None)
    """
    if not isinstance(span, str) or not span:
        return (None, None)
    digest = hashlib.sha256(span.encode("utf-8")).hexdigest()[:16]
    return (f"sha256:{digest}", len(span))


def _make_slot_meta(
    *,
    extractor: str,
    confidence: Any,
    turn_index: int,
    reason_code: str,
    source_span_hash: str | None = None,
    source_span_len: int | None = None,
) -> dict[str, Any]:
    """
    构造一条 slot_meta entry(spec §5.2):
      {
        "extractor": "rules" | "llm",
        "confidence": 0.0-1.0 float (永远不是 bool),
        "turn_index": int,
        "reason_code": str,
        "source_span_hash": "sha256:..." | None,
        "source_span_len": int | None,
      }

    confidence 非法 → 用 fallback: llm → INTERVIEW_SLOT_META_LLM_DEFAULT_CONFIDENCE
    rules → INTERVIEW_SLOT_META_RULES_CONFIDENCE_FALLBACK。
    source_span_hash / source_span_len 只要一个为 None, 另一个也归 None(防止半残 meta)。
    """
    if extractor not in ("rules", "llm"):
        extractor = "rules"

    conf = _validate_confidence(confidence)
    if conf is None:
        conf = (
            INTERVIEW_SLOT_META_LLM_DEFAULT_CONFIDENCE
            if extractor == "llm"
            else INTERVIEW_SLOT_META_RULES_CONFIDENCE_FALLBACK
        )

    # source_span_hash / len 同步: 任一为 None → 都为 None(防半残)
    if source_span_hash is None or source_span_len is None:
        source_span_hash = None
        source_span_len = None

    return {
        "extractor": extractor,
        "confidence": conf,
        "turn_index": int(turn_index) if isinstance(turn_index, int) else 0,
        "reason_code": str(reason_code)[:50] if reason_code else "unknown",
        "source_span_hash": source_span_hash,
        "source_span_len": source_span_len,
    }


# ----------------------------------------------------------------------
# R6-B Phase 2: API mode 开关(spec §5.3)
# ----------------------------------------------------------------------
def _has_llm_api_key() -> bool:
    """检查 LLM_API_KEY 是否在 env(spec §5.3)。

    隐私边界:
      - 只读 env 不读文件 / 不读 LLM_BASE_URL / LLM_MODEL
      - 不返回 key 本身, 只返 bool
    """
    return bool(os.environ.get("LLM_API_KEY", "").strip())


def _decide_interview_mode(enable_interview_llm: bool) -> tuple[str, str | None]:
    """
    根据 enable_interview_llm + LLM_API_KEY env 决定 session.interview_mode(spec §5.3)。

    决策表:
      enable=False                   → ("rules", None)         旧路径字节级一致
      enable=True + env 有 key        → ("llm_assisted", None)  智能抽取模式
      enable=True + env 没 key        → ("rules", "智能抽取不可用, 已使用规则模式")

    隐私边界:
      - mode_warning 字面量是固定的, 不含 key 长度 / key 字符 / env var 名
      - 函数不返回 key 自身

    边界:
      - 失败不抛 — 老路径(enable=False)字节级一致
      - env 查 LLM_API_KEY, 不查 LLM_BASE_URL(避免 base_url 字符串泄漏)
    """
    if not enable_interview_llm:
        return (INTERVIEW_MODE_RULES, None)
    if _has_llm_api_key():
        return (INTERVIEW_MODE_LLM_ASSISTED, None)
    return (INTERVIEW_MODE_RULES, INTERVIEW_LLM_NO_KEY_WARNING)


# ----------------------------------------------------------------------
# R6-A Phase 4: LLM slot 抽取主链路(plan §4.4 + R6-B Phase 1 §5.2 + R6-C.3)
# ----------------------------------------------------------------------
def _resolve_interview_llm_config(
    *,
    llm_enabled: bool,
    llm_api_key: str | None,
    llm_base_url: str | None,
    llm_model: str | None,
) -> dict[str, Any]:
    """
    解析 LLM slot 抽取配置(plan §4.3 配置口径)。

    返回 dict(4 字段,字段口径对齐 evaluate_agent_workflow._get_llm_eval_config):
      - enabled_for_call: bool   (满足 llm_enabled + 有 api_key → True, 否则 False)
      - llm_enabled: bool        (用户意图)
      - model: str               (优先级: 显式入参 → LLM_MODEL env → DEFAULT_MODEL)
      - base_url: str            (优先级: 显式入参 → LLM_BASE_URL env → DEFAULT_BASE_URL)

    隐私边界(AGENTS.md):
      - api_key **绝不**出现在返回值里
      - 不读 / 不写日志

    默认值 fallback 跟 evaluate_prompt_versions.py 同源:
      - DEFAULT_BASE_URL = "https://api.openai.com/v1"
      - DEFAULT_MODEL    = "gpt-4o-mini"

    R5-E 边界保护(plan §1.3 / §4.4):
      - 不 import core.llm_rewriter(任何位置 — 顶层 / 延迟都不行)
      - 默认常量本地定义,值跟 llm_rewriter 同步(测试锁)
    """
    # 不 import llm_rewriter(R5-E 字节级稳定边界)— 用本地常量 fallback
    if not llm_enabled:
        return {
            "enabled_for_call": False,
            "llm_enabled": False,
            "model": "",
            "base_url": "",
        }

    api_key = (llm_api_key or os.environ.get("LLM_API_KEY", "")).strip()
    if not api_key:
        # llm_enabled=True 但没有 key → 走规则版(spec §4.4 "失败 fallback")
        return {
            "enabled_for_call": False,
            "llm_enabled": True,
            "model": "",
            "base_url": "",
        }

    base_url = (
        (llm_base_url or os.environ.get("LLM_BASE_URL", "")).strip()
        or _INTERVIEW_LLM_DEFAULT_BASE_URL
    )
    model = (
        (llm_model or os.environ.get("LLM_MODEL", "")).strip()
        or _INTERVIEW_LLM_DEFAULT_MODEL
    )

    return {
        "enabled_for_call": True,
        "llm_enabled": True,
        "model": model,
        "base_url": base_url,
    }


def _validate_llm_extraction_payload(
    parsed: object,
    current_slot: str,
) -> dict[str, Any] | None:
    """
    校验 LLM 返回的 dict 是否符合 slot 抽取 schema:
      - 必须是 dict
      - 含 current_slot key + 可选 _warnings (list[str])
      - 若 current_slot 在 SLOT_STRING_KEYS: value 必须是 str(≤200 字)
      - 若 current_slot 在 SLOT_LIST_KEYS: value 必须是 list[str](每条 ≤200 字)

    返回:
      - 校验通过的 dict(含 current_slot + _warnings)
      - None 校验失败
    """
    if not isinstance(parsed, dict):
        return None
    if current_slot not in SLOT_STRING_KEYS and current_slot not in SLOT_LIST_KEYS:
        # 未知 slot — 不交给 LLM 抽取路径
        return None
    val = parsed.get(current_slot)
    if current_slot in SLOT_STRING_KEYS:
        if not isinstance(val, str):
            return None
        if len(val) > 200:
            val = val[:200]
    else:  # list slot
        if not isinstance(val, list):
            return None
        if not all(isinstance(x, str) for x in val):
            return None
        # 每条 ≤200 字
        val = [str(x)[:200] for x in val]

    warnings_raw = parsed.get("_warnings")
    if isinstance(warnings_raw, list):
        warnings = [str(x)[:200] for x in warnings_raw if isinstance(x, str)]
    else:
        warnings = []
    return {current_slot: val, "_warnings": warnings}


def _call_llm_for_slot_extraction(
    *,
    user_payload: dict,
    model: str,
    base_url: str,
    api_key: str,
    timeout_sec: int,
) -> str | None:
    """
    调一次 LLM slot 抽取, 返回 content 字符串或 None(网络失败)。

    失败兜底:
      - 网络错 / HTTPError / URLError / TimeoutError → None
      - **不**做 JSON 解析 / schema 校验 / retry — caller 负责
        (让 caller 能区分"网络失败" vs "返回非 JSON" vs "schema 错" 3 类失败)

    R6-C.3 改动(可观测性增强):
      - request body 加 `response_format={"type": "json_object"}` 强约束
        OpenAI-compatible 端点返回合法 JSON, 降低 JSON parse retry 概率
      - temperature 仍 0.0(spec §4.4 字节级一致, 不动)
      - 字段顺序: model → messages → response_format → temperature
        (model + temperature 是已有的固定字段; 新字段插在中间避免破坏顺序)

    隐私边界(plan §4.3 + R6-C.3):
      - api_key 仅作 Authorization header, 不进返回值 / 日志 / 请求体可观测字段
      - 失败时不返回响应原文
      - response_format 是 OpenAI 标准字段, 不含用户原文
    """
    url = base_url.rstrip("/") + "/chat/completions"
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": SLOT_EXTRACTION_SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.0,
    }
    data = json.dumps(body).encode("utf-8")
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
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            raw = resp.read().decode("utf-8")
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, Exception):
        return None

    # 尝试从 OpenAI-style envelope 提取 content; 提取不到也返 raw(让 caller 自己判)
    try:
        resp_obj = json.loads(raw)
        if isinstance(resp_obj, dict):
            choices = resp_obj.get("choices") or []
            if isinstance(choices, list) and choices:
                msg = choices[0].get("message") or {}
                content = msg.get("content")
                if isinstance(content, str):
                    return content
    except (json.JSONDecodeError, TypeError, Exception):
        pass

    # envelope 提取失败, 把 raw 文本交给 caller(可能是非 JSON, 让 caller 决定 retry)
    return raw


def _try_parse_llm_content(raw_content: str) -> dict[str, Any] | None:
    """
    解析 LLM content 字符串 → dict; 失败返 None。
    不抛 — caller 决定 retry / fallback。
    """
    if not isinstance(raw_content, str) or not raw_content.strip():
        return None
    # 尝试直接 parse
    try:
        parsed = json.loads(raw_content)
        return parsed if isinstance(parsed, dict) else None
    except (json.JSONDecodeError, TypeError):
        return None


def _extract_slots_via_llm(
    *,
    user_message: str,
    current_slot: str,
    config: dict[str, Any],
    turn_index: int = 0,
    session: InterviewSession | None = None,
) -> dict[str, Any] | None:
    """
    Phase 4 LLM 抽取主路径(plan §4.4 + R6-B Phase 1 spec §5.2):
      1. 构造 user payload (含 slot + user_message,**不**含 jd_text)
      2. 调 _call_llm_for_slot_extraction
      3. 解析 response.content JSON
      4. _validate_llm_extraction_payload 校验
      5. schema retry 1 次 (strict_retry=True — 沿用 _call_with_retry 模式)
      6. 失败 → None(caller fallback 到 _extract_slots_by_rules)

    R6-B Phase 1 spec §5.2 隐私边界:
      - LLM 返回的 source_span 字符串**只在本函数内**访问, 立刻 _compute_source_span_hash
        转成 hash + length + turn_index
      - 函数返回后 source_span 明文不留在任何局部变量(走 dict 走 hash 后即丢)
      - 返回 dict 含 `_slot_meta` 字段, 携带 hash + len, **不**含 source_span 明文

    隐私边界(plan §4.3 + AGENTS.md):
      - payload 只含 slot + user_message,**不**含 jd_text / session / materials
      - api_key 永不入返回值 / trace
      - 失败不返回响应原文

    R6-C.3 可观测性接入:
      - session 不为 None 时, 第 1 次调 LLM 失败 → retry 1 次时 session.llm_parse_retry_count += 1
      - 网络错(URLError/HTTPError/TimeoutError)不 retry, 不计入 llm_parse_retry_count
        (caller fallback 时 +1 llm_to_rules_slot_fallback_count)
      - JSON 错 / schema 错 触发 retry, 计入 llm_parse_retry_count
      - session=None → 不写可观测性字段(测试用)

    R5-E 保护:
      - 不 import llm_rewriter 的 SYSTEM_PROMPT / PROMPT_VERSIONS
      - 不挂 evaluate_prompt_versions.py
    """
    if current_slot not in SLOT_STRING_KEYS and current_slot not in SLOT_LIST_KEYS:
        # 未知 slot — 不走 LLM 路径
        return None
    if not config.get("enabled_for_call"):
        return None

    user_payload = {
        "slot": current_slot,
        "user_message": user_message,
        "instructions": "只输出 JSON, schema 严格匹配 system prompt 描述。",
    }

    # api_key 显式从 env 读, **不入** config 返回值(隐私边界, 见 _resolve_interview_llm_config)。
    # 测试可通过 monkeypatch os.environ["LLM_API_KEY"] 注入。
    api_key = os.environ.get("LLM_API_KEY", "").strip()
    base_url = config.get("base_url", "")
    model = config.get("model", "")
    if not base_url or not model or not api_key:
        return None

    # 第 1 次调用
    raw_content = _call_llm_for_slot_extraction(
        user_payload=user_payload,
        model=model,
        base_url=base_url,
        api_key=api_key,
        timeout_sec=INTERVIEW_LLM_TIMEOUT_SEC,
    )
    if raw_content is None:
        # 网络失败 — 不 retry(spec §4.4 "网络错不 retry"), fallback 规则
        return None

    parsed = _try_parse_llm_content(raw_content)
    validated = (
        _validate_llm_extraction_payload(parsed, current_slot)
        if isinstance(parsed, dict)
        else None
    )

    if validated is not None:
        return _attach_llm_slot_meta(
            parsed=parsed,
            current_slot=current_slot,
            turn_index=turn_index,
        )

    # JSON / schema 都失败 → retry 1 次, 加强约束(strict_retry=True, 沿用 _call_with_retry)
    # R6-C.3: 记 +1 retry 计数(spec §4.4 一次 retry 算一次, 不算 round)
    if session is not None:
        session.llm_parse_retry_count += 1
    retry_payload = dict(user_payload)
    retry_payload["instructions"] = (
        "上一轮输出不是合法 JSON 或 schema 不符, 请只输出 JSON, "
        "不要任何其他文本 (markdown / 解释 / chain-of-thought 都不要)。"
        "schema 严格匹配 system prompt 描述。"
    )
    raw_content = _call_llm_for_slot_extraction(
        user_payload=retry_payload,
        model=model,
        base_url=base_url,
        api_key=api_key,
        timeout_sec=INTERVIEW_LLM_TIMEOUT_SEC,
    )
    if raw_content is None:
        return None
    parsed = _try_parse_llm_content(raw_content)
    if not isinstance(parsed, dict):
        return None
    validated = _validate_llm_extraction_payload(parsed, current_slot)
    if validated is None:
        return None
    return _attach_llm_slot_meta(
        parsed=parsed,
        current_slot=current_slot,
        turn_index=turn_index,
    )


def _attach_llm_slot_meta(
    *,
    parsed: dict[str, Any],
    current_slot: str,
    turn_index: int,
) -> dict[str, Any] | None:
    """
    R6-B Phase 1(spec §5.2): 给 LLM 抽取结果附加 _slot_meta。

    LLM 返回的 source_span(若存在)只在本函数内 hash 化:
      - 校验 parsed.source_span 必须是 string(不是 → 丢弃, 不写 meta.source_span_*)
      - 用 _compute_source_span_hash 转成 ("sha256:..." / len) 元组
      - 函数返回后原始 source_span 字符串不再保留(走 _make_slot_meta 后即丢)

    隐私边界:
      - 校验非法(source_span 不是 string / confidence 是 bool / 不在 [0,1])→ 走默认 meta,
        该条 source_span_* 字段为 None(spec §5.2 invalid source_span 降级)
      - _slot_meta 不入 trace(由 caller 写 session.slot_meta 时自己控制)
    """
    # 校验 source_span(只接受 string, 其他 → 降级)
    raw_span = parsed.get("source_span")
    h, ln = _compute_source_span_hash(raw_span if isinstance(raw_span, str) else None)

    # 校验 confidence(必须 0.0-1.0 number, bool 拒绝 — spec §5.2)
    raw_conf = parsed.get("confidence")
    conf = _validate_confidence(raw_conf)
    if conf is None:
        # 非法(包含 bool) → 走 _make_slot_meta 内置 fallback 到 LLM default 0.60
        conf_arg: Any = raw_conf  # 故意传入非法值让 _make_slot_meta 兜底
    else:
        conf_arg = conf

    # reason_code: LLM 给则用(截 50 字), 否则用通用 llm_extracted
    raw_reason = parsed.get("reason_code")
    if isinstance(raw_reason, str) and raw_reason.strip():
        reason_code = f"llm_{raw_reason.strip()[:45]}"
    else:
        reason_code = "llm_extracted"

    meta = _make_slot_meta(
        extractor="llm",
        confidence=conf_arg,
        turn_index=turn_index,
        reason_code=reason_code,
        source_span_hash=h,
        source_span_len=ln,
    )

    # 重新构造 validated 风格的 dict + _slot_meta
    val = parsed.get(current_slot)
    if current_slot in SLOT_STRING_KEYS:
        if not isinstance(val, str):
            return None
        if len(val) > 200:
            val = val[:200]
    else:  # list slot
        if not isinstance(val, list) or not all(isinstance(x, str) for x in val):
            return None
        val = [str(x)[:200] for x in val]

    warnings_raw = parsed.get("_warnings")
    if isinstance(warnings_raw, list):
        warnings = [str(x)[:200] for x in warnings_raw if isinstance(x, str)]
    else:
        warnings = []

    return {
        current_slot: val,
        "_warnings": warnings,
        "_slot_meta": [meta],
    }