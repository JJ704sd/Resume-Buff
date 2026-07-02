"""
Round 6-A Phase 1+4: JD-driven interview agent 状态机 + LLM slot 抽取

设计原则(plan §1.3 + §4.4):
  - 不 import core.llm_rewriter / core.agent_workflow / core.agent_tools / core.evidence
    / core.tool_schema / core.session (R5-E 字节级稳定边界)
  - 只 import core.jd_parser 公开符号(parse_jd / match_score) + core.generator.load_materials
    + core.logger.log_agent_trace_jsonl
  - 缺口选择只基于 parse_jd + match_score,不调 _evaluate_top_bullets
    不读 agent_summary / external_resume_perspective / bullet_evaluations
  - 进程内 _INTERVIEW_SESSIONS 独立命名空间,与 core.session._SESSIONS 隔离
  - trace 走 core.logger.log_agent_trace_jsonl,workflow="interview",只存 size 不存原文

Phase 4 LLM slot 抽取(plan §4.4):
  - extract_slots 新增 keyword-only 4 参数: llm_enabled / llm_api_key / llm_base_url / llm_model
  - llm_enabled=False → 走 _extract_slots_by_rules(Phase 1 字节级一致)
  - llm_enabled=True + key 有效 → 调 stdlib urllib POST /chat/completions
  - 失败 fallback 到规则版,不抛(spec §4.4 "失败不阻断主流程")
  - LLM prompt 走 core.interview_prompts.SLOT_EXTRACTION_SYSTEM_PROMPT(独立常量,**不进** PROMPT_VERSIONS)
  - 模板只含 {slot} + {user_message},**不**含 {jd_text}(隐私边界)

公开 API:
  - InterviewState (str Enum)        EMPTY / DIAGNOSING / ASKING / DRAFT_READY / SAVED / ABORTED
  - ActionType   (str Enum)          ANSWER / SKIP_QUESTION / REPHRASE_QUESTION / SWITCH_GAP / DRAFT_NOW
  - GapCandidate (@dataclass frozen)  8 字段
  - InterviewSession (@dataclass)     16 字段(R6-B Phase 1 加 5 个可信增强字段, 默认值)
  - create_session / select_gap / next_question / extract_slots
  - can_draft / build_draft_card / apply_action
  - get_session / reset_session / save_card
  - _resolve_interview_llm_config     (Phase 4 helper, 测试用)

Round 6-B Phase 1: slot_meta provenance(spec §5.1+§5.2):
  - InterviewSession.interview_mode 默认 "rules"(R6-B Phase 2 才接 API 开关)
  - InterviewSession.slot_meta 存放 per-slot provenance, list 形态, 单 slot 最多 5 条
  - extract_slots 返回 dict 带 _slot_meta(list[dict]), apply_action 把它写入 session
  - LLM source_span 只在当前函数内验证并 sha256 hash + length + turn_index, 不得存明文
  - confidence 必须是 0.0-1.0 number(bool 不接受), 拒绝时降级到规则版
  - rules / llm extraction 各自生成 reason_code(spec §5.2)
  - 隐私边界: session.slot_meta / trace / API response 均不含 user_message / source_span 明文

Round 6-B Phase 2: API mode 开关(spec §5.3):
  - create_session 新增 keyword-only 参数 enable_interview_llm: bool = False
  - _decide_interview_mode: enable=False → rules(老路径字节级一致);
    enable=True + LLM_API_KEY 在 env → llm_assisted;
    enable=True + 无 key → rules + mode_warning(用户可见, 不含 key 字符)
  - _do_answer 根据 session.interview_mode == "llm_assisted" 决定 llm_enabled
  - _build_extraction_summary: 构造 spec §5.3 schema(extractor / fallback_used / captured_slots / low_confidence_slots)
  - _build_question_plan: Phase 2 占位实现(返回 slot + reason_code="phase2_placeholder" + low_confidence_slots 聚合)
  - ReplyResponse 走 spec §5.3 字段名; 不存 user_message / source_span / API key / prompt

Round 6-B Phase 4: draft verifier 接入(spec §7):
  - _do_draft_now 在 build_draft_card 之后调 verify_draft_card(card, session)
    把 verification (5 字段) + confidence_notes (list[str]) 注入到 sess.draft_card
    同时缓存到 sess.verification_summary 供 save_card 写 _interview_meta
  - save_card 从 session.verification_summary 读摘要写入 _interview_meta.verification
    (只存 4 个计数 + warnings list[str] + extraction_mode 字面量, 不存原文)
  - 老路径(verification_summary=None)字节级一致 — save_card 跳过 verification meta
  - verifier 默认不调 LLM(pure stdlib), unsupported_claims 不阻止保存

Round 6-C.3: LLM 抽取可观测性(2026-07-02 落地):
  - InterviewSession 新增 3 个 LLM 抽取层可观测性字段(均有默认值, 保持旧测试构造兼容):
      * slot_source_breakdown: dict[str, int]
        = {rules: N, llm: M, mixed: K}
        每轮 answer 完成后 +1 — rules 永远 +1(主路径), LLM 成功 +1 llm,
        rules fallback 也算 rules(不重复), 失败透传算 mixed (罕见).
      * llm_parse_retry_count: int
        = 累计 JSON parse / schema retry 次数(spec §4.4 "失败 retry 1 次"
          一次调 urlopen 算 1, 不算 round; 网络错不 retry 故不计入)
      * llm_to_rules_slot_fallback_count: int
        = LLM 抽取出错 fallback 规则版的次数(网络错 + JSON 错 + schema 错都算)
  - _call_llm_for_slot_extraction: request body 加
    response_format={"type": "json_object"} 强约束 JSON 输出(OpenAI-compatible),
    temperature 仍 0.0(spec §4.4)
  - 隐私边界: 3 个可观测字段只存整数 / 短字符串, 不含 user_message / source_span /
    draft_card / API key / prompt 正文 / raw response. eval 报告只展示计数 / 比率.
  - 老路径(llm_enabled=False / 默认)字节级一致: 3 字段保持 0 / {} / {}, 因为
    _extract_slots_by_rules 不写 session 的 LLM 可观测字段.
"""
from __future__ import annotations

import hashlib
import json
import os
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from core.generator import load_materials  # noqa: F401  re-export for tests
from core.interview_policy import (  # noqa: F401  re-export for tests
    INTERVIEW_POLICY_KIND_ASK,
    INTERVIEW_POLICY_KIND_NO_MORE,
)
from core.jd_parser import match_score, parse_jd
from core.logger import log_agent_trace_jsonl

import core.interview_prompts as prompts
from core.interview_prompts import (
    CAN_DRAFT_CONDITIONS,
    GAP_CANDIDATES_FIELDS,
    GAP_KEYWORD_RULES,
    GAP_LABELS,
    GAP_REASONS,
    GAP_SUGGESTED_SLOTS,
    INTERVIEWABLE_GAP_IDS,
    INTERVIEW_LLM_TIMEOUT_SEC,
    INTERVIEW_MAX_MESSAGE_LEN,
    MAX_CONSECUTIVE_SKIPS,
    MAX_TURNS_PER_GAP,
    NON_INTERVIEWABLE_GAP_IDS,
    QUESTION_TEMPLATES,
    QUICK_REPLIES_BY_SLOT,
    SLOT_EXTRACTION_SYSTEM_PROMPT,
    SLOT_EXTRACTION_USER_TEMPLATE,
    SLOT_LIST_KEYS,
    SLOT_NAMES,
    SLOT_STRING_KEYS,
)


# ----------------------------------------------------------------------
# 公开 enum
# ----------------------------------------------------------------------
class InterviewState(str, Enum):
    EMPTY = "EMPTY"
    DIAGNOSING = "DIAGNOSING"
    ASKING = "ASKING"
    DRAFT_READY = "DRAFT_READY"
    SAVED = "SAVED"
    ABORTED = "ABORTED"


class ActionType(str, Enum):
    ANSWER = "answer"
    SKIP_QUESTION = "skip_question"
    REPHRASE_QUESTION = "rephrase_question"
    SWITCH_GAP = "switch_gap"
    DRAFT_NOW = "draft_now"


# ----------------------------------------------------------------------
# 公开 dataclass
# ----------------------------------------------------------------------
@dataclass(frozen=True)
class GapCandidate:
    gap_id: str
    label: str
    reason: str
    keywords: list[str]
    source: list[str]
    tier: str  # "required" / "preferred" / "bonus"
    priority: float
    suggested_slots: tuple[str, ...]


@dataclass
class InterviewSession:
    session_id: str
    target_role: str
    jd_digest: dict
    selected_gap: GapCandidate | None
    state: InterviewState
    turn_count: int
    captured_slots: dict[str, Any]
    skip_count: int
    draft_card: dict | None
    message_log: list[dict]
    # 测试 / Phase 2 用: 允许外部覆盖候选集(默认 None → 走 4 个固定 gap)
    gap_candidates: list[GapCandidate] | None = None

    # R6-B Phase 1: 可信增强层(spec §5.1)— 必须有默认值,保持旧测试构造兼容
    interview_mode: str = "rules"
    """抽取模式: 'rules' / 'llm_assisted'。Phase 2 才通过 API 层切换。"""
    mode_warning: str | None = None
    """用户可见摘要: 例如 '智能抽取不可用, 已使用规则模式'。"""
    slot_meta: dict[str, Any] = field(default_factory=dict)
    """per-slot provenance 字典:
      {slot: [meta_entry, ...]} 单 slot 最多保留 INTERVIEW_SLOT_META_MAX 条。
      meta_entry 字段: extractor / confidence / turn_index / reason_code /
                       source_span_hash(可选) / source_span_len(可选)。
      不存 user_message / source_span 明文(spec §5.2 隐私边界)。
    """
    question_plan: dict[str, Any] | None = None
    """下一问策略输出(spec §6, Phase 3 才填充)。"""
    verification_summary: dict[str, Any] | None = None
    """draft_card 核验摘要(spec §7, Phase 4 才填充)。"""

    # R6-C.3: LLM 抽取可观测性字段(3 个)
    # 全部含默认值, 老测试构造兼容(关键字缺省即可)
    slot_source_breakdown: dict[str, int] = field(default_factory=dict)
    """R6-C.3 LLM 抽取可观测性: 每轮 answer 抽取完成后, 在 session 上记录来源分布。
       schema: {rules: int, llm: int, mixed: int}
         - rules: 走 _extract_slots_by_rules 的次数(含 LLM fallback 到规则版)
         - llm: 走 LLM 且成功的次数(由 _extract_slots_via_llm 返非 None 时计数)
         - mixed: 同一轮里不同 slot 来源不一致的次数(罕见, 当前实现未触发, 保留字段位)
       默认 {}; 老路径(llm_enabled=False)字节级一致 → 累计只 +rules.
       不含 user_message / source_span / draft_card 原文(隐私边界)。
    """
    llm_parse_retry_count: int = 0
    """R6-C.3 LLM 抽取可观测性: 累计 LLM JSON parse / schema retry 次数。
       每次 _extract_slots_via_llm 第 1 次调 LLM 失败后 retry 1 次, retry 1 次 +1。
       网络错(URLError/HTTPError/TimeoutError)不 retry, 不计入此字段。
       默认 0; 老路径字节级一致 → 永远 0(因为不走 LLM)。
    """
    llm_to_rules_slot_fallback_count: int = 0
    """R6-C.3 LLM 抽取可观测性: 累计 LLM 失败 fallback 规则版的次数。
       触发条件: LLM 网络错 / JSON 错 / schema 错 — 任意一种导致 _extract_slots_via_llm 返 None,
       caller fallback _extract_slots_by_rules 时 +1。
       默认 0; 老路径字节级一致 → 永远 0。
    """


# ----------------------------------------------------------------------
# 进程内 session 存储(独立命名空间,与 core.session._SESSIONS 隔离)
# ----------------------------------------------------------------------
_INTERVIEW_SESSIONS: dict[str, InterviewSession] = {}


# ----------------------------------------------------------------------
# Round 6-A Phase 2: save_card 写库相关常量
# ----------------------------------------------------------------------
DEFAULT_MATERIALS_PATH: Path = (
    Path(__file__).resolve().parent.parent / "data" / "materials.json"
)
"""save_card 默认写入路径 — 跟 core.generator.MATERIALS_PATH 同源。

测试 / 冒烟禁止直接改这个文件;请通过 save_card(..., materials_path=tmp_path) 注入临时路径。
"""

INTERVIEW_BULLET_MAX_LEN: int = 200
"""draft_bullets 单条字符上限(plan §2.3)。"""

INTERVIEW_REQUIRED_EDITED_KEYS: tuple[str, ...] = (
    "title", "responsibility", "actions", "draft_bullets",
)
"""edited_card 必填字段集合。"""


# ----------------------------------------------------------------------
# R6-B Phase 1: slot_meta provenance 常量 + helpers(spec §5.2)
# ----------------------------------------------------------------------
INTERVIEW_SLOT_META_MAX: int = 5
"""per slot 最多保留的 meta 条数(spec §5.2 "list slot 最多保留 5 条 meta")。"""

INTERVIEW_SLOT_META_MIN_CONFIDENCE: float = 0.0
INTERVIEW_SLOT_META_MAX_CONFIDENCE: float = 1.0
"""confidence 合法范围 [0.0, 1.0]。bool 被拒绝(spec §5.2)。"""

INTERVIEW_SLOT_META_RULES_CONFIDENCE_HIT: float = 0.80
"""规则抽取命中关键词 / regex 时的 confidence 默认值。"""

INTERVIEW_SLOT_META_RULES_CONFIDENCE_FALLBACK: float = 0.40
"""规则抽取 fallback(没命中关键词, 走原文 fallback)时的 confidence 默认值。"""

INTERVIEW_SLOT_META_LLM_DEFAULT_CONFIDENCE: float = 0.60
"""LLM 未提供 confidence 时的默认值。"""


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


def _append_slot_meta(
    session: InterviewSession,
    slot: str,
    new_entries: list[dict[str, Any]],
) -> None:
    """
    写 session.slot_meta[slot], 保留最近 INTERVIEW_SLOT_META_MAX 条。
    旧条目在前, 新条目在后(按 turn_index 升序, 同 turn 内新条目在后)。

    隐私边界(spec §5.2 + AGENTS.md):
      - new_entries 来自 _make_slot_meta, 不含 user_message / source_span 明文
      - session.slot_meta 是 dataclass 字段, 不写 trace / API response
    """
    if not slot or not isinstance(new_entries, list) or not new_entries:
        return
    if session.slot_meta is None or not isinstance(session.slot_meta, dict):
        session.slot_meta = {}
    existing = list(session.slot_meta.get(slot) or [])
    # 新条目按 turn_index 排序后追加(防止 caller 顺序乱)
    ordered = sorted(
        list(new_entries),
        key=lambda e: (e.get("turn_index", 0), 0),
    )
    combined = existing + ordered
    # 保留最后 INTERVIEW_SLOT_META_MAX 条(最近 N 条最有诊断价值)
    session.slot_meta[slot] = combined[-INTERVIEW_SLOT_META_MAX:]


# ----------------------------------------------------------------------
# R6-A Phase 4: LLM slot 抽取本地常量(plan §4.3 配置口径)
# ----------------------------------------------------------------------
# 注: 这些常量值必须跟 core.llm_rewriter.DEFAULT_BASE_URL / DEFAULT_MODEL
# 字节级一致(由 tests/test_interview_agent.py::TestInterviewPromptRegistry
# 里的 test_interview_llm_defaults_match_llm_rewriter 锁死)。在 interview_agent.py
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
"""用户可见摘要: enable_interview_llm=True 但 LLM_API_KEY 不在 env 时(spec §5.1)。"""

INTERVIEW_MODE_RULES: str = "rules"
INTERVIEW_MODE_LLM_ASSISTED: str = "llm_assisted"
"""spec §5.1 锁死的两个 mode 值; ReplyResponse / StartResponse 都用这俩。"""


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
# R6-B Phase 2: extraction_summary / question_plan helpers(spec §5.3)
# ----------------------------------------------------------------------
INTERVIEW_LOW_CONFIDENCE_THRESHOLD: float = 0.6
"""低置信度阈值: confidence < 0.6 视为 low_confidence(供前端 warning / eval 用)。"""


def _build_extraction_summary(
    *,
    new_meta_entries: list[dict[str, Any]] | None,
    captured_delta: dict[str, Any] | None,
    intended_mode: str,
) -> dict[str, Any] | None:
    """
    构造 ReplyResponse.extraction_summary(spec §5.3 schema):
      {
        "extractor": "rules" | "llm" | "mixed",
        "fallback_used": bool,
        "captured_slots": list[str],
        "low_confidence_slots": list[str]
      }

    参数:
      new_meta_entries:  本轮 _do_answer 写 session.slot_meta 的新条目 list
      captured_delta:    本轮填进 captured_slots 的字段 dict(去 _warnings/_slot_meta)
      intended_mode:     session.interview_mode("rules" / "llm_assisted") —
                         用于判断 fallback_used (LLM 意图 + 实际 rules = fallback)

    返回:
      None — 当 new_meta_entries 为空 / 不是 list(代表本轮没发生 answer 抽取,
             例如 skip / rephrase / switch_gap / draft_now)

    隐私边界:
      - 不存 user_message / source_span 明文
      - low_confidence_slots 只列 slot 名字符串
      - confidence 不进 dict(spec §5.3 schema 限定)

    边界:
      - new_meta_entries 空 → 返 None(API 层把 None 传给 Optional 字段)
      - 不抛:任何内部异常 → 返 None(spec §6.3 "失败不阻断主流程")
    """
    if not isinstance(new_meta_entries, list) or not new_meta_entries:
        return None
    try:
        extractors = sorted({str(m.get("extractor", "rules")) for m in new_meta_entries})
        # "rules" / "llm" / "mixed" — 用集合基数判断(混合只可能是 rules + llm)
        if extractors == ["rules"]:
            extractor_label = "rules"
        elif extractors == ["llm"]:
            extractor_label = "llm"
        else:
            extractor_label = "mixed"

        # fallback_used: intended_mode == llm_assisted 但实际 extractor 不是 llm
        fallback_used = (
            intended_mode == INTERVIEW_MODE_LLM_ASSISTED
            and extractor_label != "llm"
        )

        # captured_slots: 从 captured_delta 抽出顶层业务 key(spec §5.3 schema 限定 list[str])
        captured_slots: list[str] = []
        if isinstance(captured_delta, dict):
            for k in captured_delta.keys():
                if not isinstance(k, str) or k.startswith("_"):
                    continue
                if k not in captured_slots:
                    captured_slots.append(k)

        # low_confidence_slots: meta.confidence < 0.6 的 slot(spec §5.3)
        low_confidence_slots: list[str] = []
        for m in new_meta_entries:
            try:
                conf_val = m.get("confidence")
                if not isinstance(conf_val, (int, float)) or isinstance(conf_val, bool):
                    continue
                if conf_val < INTERVIEW_LOW_CONFIDENCE_THRESHOLD:
                    low_confidence_slots.append("low_confidence")
            except Exception:
                continue

        return {
            "extractor": extractor_label,
            "fallback_used": bool(fallback_used),
            "captured_slots": captured_slots,
            "low_confidence_slots": low_confidence_slots,
        }
    except Exception:
        return None


def _build_question_plan(session: InterviewSession) -> dict[str, Any] | None:
    """
    构造 ReplyResponse.question_plan(spec §5.3 schema + §6 deterministic policy)。

    R6-B Phase 3:
      委托 core.interview_policy.plan_next_question 选 slot / reason_code,
      返回 spec §5.3 限定的 3 字段子集:
        {slot, reason_code, low_confidence_slots}

    不抛(spec §6.3 "失败不阻断主流程") — 内部异常返 None。

    隐私边界(spec §5.3 + AGENTS.md):
      - 不存 user_message / source_span 明文
      - 不含 API key / prompt 文本 / confidence 数字 / jd_text
      - 只列 slot 名 / reason_code / 简单 list[str]

    与 Phase 2 占位实现的差异:
      - 旧(reason_code="phase2_placeholder") 永远返同一 reason_code
      - 新(reason_code ∈ INTERVIEW_POLICY_REASON_*) 真正反映 plan 决策
      - low_confidence_slots 聚合算法同 Phase 2(sorting 一致)
    """
    try:
        # 延迟 import: 避免 circular import(interview_policy 也会 import interview_prompts)
        from core.interview_policy import plan_next_question

        plan = plan_next_question(session)
        if not isinstance(plan, dict):
            return None
        return {
            "slot": str(plan.get("slot", "") or ""),
            "reason_code": str(plan.get("reason_code", "") or ""),
            "low_confidence_slots": list(
                plan.get("low_confidence_slots", []) or []
            ),
        }
    except Exception:
        return None


# ----------------------------------------------------------------------
# 内部:trace 写入(只存 size, 不存原文)
# ----------------------------------------------------------------------
def _log_interview_trace(
    session: InterviewSession,
    *,
    step: int,
    tool: str,
    status: str,
    error_type: str | None,
    input_size: int,
    output_size: int,
) -> None:
    """写一条 trace 到 backend/logs/agent_trace.jsonl。失败静默(spec §6.3)。"""
    event = {
        "request_id": session.session_id,
        "session_id": session.session_id,
        "workflow": "interview",
        "step": step,
        "tool": tool,
        "latency_ms": 0,
        "status": status,
        "error_type": error_type,
        "input_size": input_size,
        "output_size": output_size,
    }
    try:
        log_agent_trace_jsonl(event)
    except Exception:
        # spec §6.3: trace 写失败不能影响主流程
        pass


# ----------------------------------------------------------------------
# Round 6-A Phase 2: save_card 写库 helpers(plan §2.3)
# ----------------------------------------------------------------------
def _load_materials_for_save(materials_path: Path) -> dict:
    """从指定路径读 materials.json — 仅 save_card 用,不 import api.materials._load。"""
    with open(materials_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _atomic_save_materials(data: dict, materials_path: Path) -> None:
    """原子写: tmp file + os.replace(plan §2.3 步骤 8)。"""
    tmp_path = materials_path.with_suffix(materials_path.suffix + ".tmp")
    # 先写 tmp 再 replace,确保半写不会破坏原文件
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, materials_path)


def _validate_edited_card(edited_card: Any) -> None:
    """校验 edited_card 字段 + draft_bullets 非空 + 每条 ≤200 字(plan §2.3)。"""
    if not isinstance(edited_card, dict):
        raise ValueError(f"edited_card 必须是 dict, 实际 {type(edited_card).__name__}")
    for key in INTERVIEW_REQUIRED_EDITED_KEYS:
        if key not in edited_card:
            raise ValueError(f"edited_card 缺必填字段: {key!r}")
    bullets = edited_card.get("draft_bullets")
    if not isinstance(bullets, list) or len(bullets) == 0:
        raise ValueError("draft_bullets 必须是非空 list")
    for i, b in enumerate(bullets):
        if not isinstance(b, str) or not b.strip():
            raise ValueError(f"draft_bullets[{i}] 必须是非空 str")
        if len(b) > INTERVIEW_BULLET_MAX_LEN:
            raise ValueError(
                f"draft_bullets[{i}] 长度 {len(b)} 超过上限 {INTERVIEW_BULLET_MAX_LEN}"
            )


def _generate_project_id(materials: dict) -> str:
    """生成 'interview_YYYYMMDD_NNN' 形式的 project id,查现有 id 避免冲突(plan §2.3 步骤 4)。"""
    today = datetime.now().strftime("%Y%m%d")
    prefix = f"interview_{today}_"
    existing = {str(p.get("id", "")) for p in materials.get("projects", []) or []}
    # 连续 2 次 save_card 也可能同一天 — 按 3 位序号递推找空位
    for i in range(1, 1000):
        candidate = f"{prefix}{i:03d}"
        if candidate not in existing:
            return candidate
    raise RuntimeError(f"project id 序号在 {prefix}NNN 已耗尽, 无法生成新 id")


def save_card(
    session: InterviewSession,
    edited_card: dict,
    save_mode: str,
    *,
    materials_path: Path | None = None,
) -> dict:
    """
    Phase 2 save-card 写库闭环(plan §2.3):
      1. 校验 save_mode / edited_card
      2. 生成不冲突 project id
      3. 构造新 project(highlights dict + category + tags + _interview_meta)
      4. 追加 projects + 更新 _meta.last_updated
      5. 原子写: tmp + os.replace
      6. session.state = SAVED
      7. 写 trace: workflow="interview", tool="save_card", input/output 字节数
      8. 返 {ok, material_ref, refresh, preview_score_delta}

    参数:
      session:      当前 InterviewSession(必须有 selected_gap + target_role)
      edited_card:  前端编辑过的 draft_card(必填 title/responsibility/actions/draft_bullets)
      save_mode:    Phase 2 只接受 "append_project", 其他 ValueError
      materials_path: 测试 / 冒烟时传临时路径;None → DEFAULT_MATERIALS_PATH

    返回:
      {
        "ok": True,
        "material_ref": {"type": "project", "id": "interview_YYYYMMDD_NNN"},
        "refresh": {"should_refresh_preview": True, "should_refresh_match": True},
        "preview_score_delta": None,  # Phase 2 暂不算 score delta,留接口
      }

    异常:
      ValueError  — save_mode 错误 / edited_card 字段错 / draft_bullets 空 / 超长
                    (由 api/interview.py 翻译成 400 或 422)
      RuntimeError — IO 错(原子写失败)/ project id 耗尽
    """
    if session is None:
        raise ValueError("session 不能为 None")

    # 1. save_mode 校验 — 错误信息包含 "save_mode" 字面量,API 层据此判 400
    if save_mode != "append_project":
        raise ValueError(
            f"save_mode {save_mode!r} 不支持, Phase 2 只接受 'append_project'"
        )

    # 2. edited_card 字段校验 — 422 风格错误(API 层据此判 422)
    _validate_edited_card(edited_card)

    # 3. 解析目标路径
    target_path = (
        Path(materials_path) if materials_path is not None
        else DEFAULT_MATERIALS_PATH
    )

    # 4. 读现有 materials
    materials = _load_materials_for_save(target_path)
    materials.setdefault("projects", [])

    # 5. 生成 id
    new_id = _generate_project_id(materials)

    # 6. 构造新 project(决策点 D1)
    bullets = list(edited_card["draft_bullets"])
    skills = list(edited_card.get("skills") or [])
    tags = ["interview_agent"] + skills
    interview_meta: dict[str, Any] = {
        "source_gap_id": session.selected_gap.gap_id if session.selected_gap else "",
        "source_session_id": session.session_id,
        "created_at": datetime.now().astimezone().isoformat(),
        "warnings": list(edited_card.get("warnings") or []),
    }

    # R6-B Phase 4(spec §7): 把 verification 摘要写入 _interview_meta
    # 老路径(verification_summary=None, 比如保存未走 /draft)—— 字节级一致, 跳过
    # 摘要字段: 4 数字 + extraction_mode + warnings list[str] (不含 draft_card 原文)
    verification_summary = getattr(session, "verification_summary", None)
    if isinstance(verification_summary, dict):
        interview_meta["extraction_mode"] = str(
            getattr(session, "interview_mode", "rules") or "rules"
        )
        # 4 个数字 + warnings 摘要(spec §5.3 schema 限定)
        # 故意只写 spec 限定的字段, 防止把 confidence 数字 / source_span / jd_text 副作用间接写进
        interview_meta["verification"] = {
            "claims_total": int(verification_summary.get("claims_total", 0) or 0),
            "claims_supported": int(
                verification_summary.get("claims_supported", 0) or 0
            ),
            "low_confidence_claims": int(
                verification_summary.get("low_confidence_claims", 0) or 0
            ),
            "unsupported_claims": int(
                verification_summary.get("unsupported_claims", 0) or 0
            ),
            "warnings": list(verification_summary.get("warnings") or []),
        }

    new_project = {
        "id": new_id,
        "name": str(edited_card.get("title", ""))[:200],
        "period": "",  # 用户没填, 留空
        "role": str(edited_card.get("responsibility", ""))[:200],
        "category": "interview_captured",  # 新增 category 枚举值
        "summary": str(edited_card.get("summary", "")),
        # 关键: 按 role 分类的 dict(双写入, 换 role 不丢)
        "highlights": {
            session.target_role: bullets,
            "general": bullets,
        },
        "tags": tags,
        # 审计字段(不进 build_sections, 仅留档)
        "_interview_meta": interview_meta,
    }

    # 7. 追加 + 更新 _meta.last_updated(不动 version / source_files)
    materials["projects"].append(new_project)
    if "_meta" in materials and isinstance(materials["_meta"], dict):
        materials["_meta"]["last_updated"] = datetime.now().strftime("%Y-%m-%d")

    # 8. 原子写
    _atomic_save_materials(materials, target_path)

    # 9. session.state = SAVED
    session.state = InterviewState.SAVED

    # 10. trace: workflow="interview", step 数字(续接 slot_extract 之后),
    #     tool="save_card", input_size=edited_card 字节数, output_size=new_project 字节数
    input_size = len(json.dumps(edited_card, ensure_ascii=False).encode("utf-8"))
    output_size = len(json.dumps(new_project, ensure_ascii=False).encode("utf-8"))
    _log_interview_trace(
        session,
        step=(session.turn_count or 0) + 10,
        tool="save_card",
        status="success",
        error_type=None,
        input_size=input_size,
        output_size=output_size,
    )

    # 11. 返回
    return {
        "ok": True,
        "material_ref": {"type": "project", "id": new_id},
        "refresh": {
            "should_refresh_preview": True,
            "should_refresh_match": True,
        },
        "preview_score_delta": None,
    }


# ----------------------------------------------------------------------
# 内部:缺口打分 / 选择
# ----------------------------------------------------------------------
def _infer_tier(gap: GapCandidate, parsed: dict) -> str:
    """
    根据 gap.keywords 命中 parsed.tier_info 的情况推断 tier。
    兜底:'preferred'(plan §1.3 默认行为)。
    """
    tier_info = parsed.get("tier_info") or {}
    req = set(tier_info.get("required") or [])
    pref = set(tier_info.get("preferred") or [])
    bonus = set(tier_info.get("bonus") or [])
    hit = set(gap.keywords) & (req | pref | bonus)
    if not hit:
        return "preferred"
    if hit & req:
        return "required"
    if hit & pref:
        return "preferred"
    return "bonus"


def _score_gap(gap: GapCandidate, parsed: dict, missing: list[str]) -> float:
    """
    缺口优先级打分(plan §1.3 核心算法):
      +4 tier=required / +2 preferred / +1 bonus
      +3 gap.keywords 出现在 match_score.missing_keywords
      +2 命中 raw_keywords 中同类 >= 2
      +2 gap_id 在 INTERVIEWABLE_GAP_IDS 白名单
      -5 gap_id 在 NON_INTERVIEWABLE_GAP_IDS 白名单
    """
    score = 0.0
    tier = gap.tier or _infer_tier(gap, parsed)
    if tier == "required":
        score += 4
    elif tier == "preferred":
        score += 2
    else:
        score += 1

    raw_keywords = set(parsed.get("raw_keywords") or [])
    missing_set = set(missing or [])

    # missing_keywords 命中(plan §1.3: +3)
    if any(k in missing_set for k in gap.keywords):
        score += 3

    # 同类关键词 >= 2(plan §1.3: +2)
    hit_count = sum(1 for k in gap.keywords if k in raw_keywords)
    if hit_count >= 2:
        score += 2

    # 可追问白名单(plan §1.3: +2)
    if gap.gap_id in INTERVIEWABLE_GAP_IDS:
        score += 2

    # 不该追问白名单(plan §1.3: -5, 即使 tier=required 也会落选)
    if gap.gap_id in NON_INTERVIEWABLE_GAP_IDS:
        score -= 5

    return score


def _select_gap_from_candidates(
    candidates: list[GapCandidate],
    parsed: dict,
    missing: list[str],
) -> GapCandidate:
    """纯函数:从候选集选 Top 1(priority desc, gap_id asc)。"""
    if not candidates:
        raise ValueError("candidates 不能为空")
    scored = [(c, _score_gap(c, parsed, missing)) for c in candidates]
    scored.sort(key=lambda x: (-x[1], x[0].gap_id))
    return scored[0][0]


def _default_candidates() -> list[GapCandidate]:
    """4 个固定 gap 候选 — Phase 1 不接受外部 gap(plan §1.3)。"""
    out: list[GapCandidate] = []
    for gap_id in INTERVIEWABLE_GAP_IDS:
        out.append(
            GapCandidate(
                gap_id=gap_id,
                label=GAP_LABELS[gap_id],
                reason=GAP_REASONS[gap_id],
                keywords=list(GAP_KEYWORD_RULES[gap_id]),
                source=["manual"],
                tier="preferred",  # 默认, _infer_tier 在 _score_gap 里覆盖
                priority=0.0,
                suggested_slots=tuple(GAP_SUGGESTED_SLOTS[gap_id]),
            )
        )
    return out


# ----------------------------------------------------------------------
# 内部:progress / state helpers
# ----------------------------------------------------------------------
def _progress(session: InterviewSession) -> dict[str, Any]:
    captured: dict[str, bool] = {}
    for slot in SLOT_NAMES:
        v = session.captured_slots.get(slot)
        if isinstance(v, str):
            captured[slot] = bool(v.strip())
        elif isinstance(v, list):
            captured[slot] = len(v) > 0
        else:
            captured[slot] = False
    return {
        "captured": captured,
        "turn_count": session.turn_count,
        "can_draft": can_draft(session),
    }


def _current_slot(session: InterviewSession) -> str | None:
    """返回当前应追问的 slot(按 gap.suggested_slots 顺序,跳过已捕获的)。"""
    gap = session.selected_gap
    if gap is None:
        return None
    asked = set(session.captured_slots.keys())
    for slot in gap.suggested_slots:
        if slot not in asked:
            return slot
    return None


# ----------------------------------------------------------------------
# 公开 API 1:session CRUD
# ----------------------------------------------------------------------
def get_session(session_id: str) -> InterviewSession | None:
    return _INTERVIEW_SESSIONS.get(session_id)


def reset_session(session_id: str) -> bool:
    if session_id in _INTERVIEW_SESSIONS:
        del _INTERVIEW_SESSIONS[session_id]
        return True
    return False


def create_session(
    target_role: str,
    jd_text: str,
    materials: dict,
    *,
    enable_interview_llm: bool = False,
) -> InterviewSession:
    """
    创建 session:
      - parse_jd + match_score 抽取 JD 摘要
      - select_gap 自动选 Top 1 gap
      - 写 trace (tool=gap_select)

    R6-B Phase 2(spec §5.3):
      - 新增 keyword-only 参数 enable_interview_llm, 默认 False
      - enable=False → session.interview_mode="rules", mode_warning=None(老路径字节级一致)
      - enable=True + LLM_API_KEY 在 env → session.interview_mode="llm_assisted"
      - enable=True + 无 key → session.interview_mode="rules", mode_warning="智能抽取不可用, 已使用规则模式"
      - 决策走 _decide_interview_mode, 本函数不读 key 原文(spec 隐私边界)
    """
    parsed = parse_jd(jd_text)
    ms = match_score(
        jd_text, target_role,
        materials=materials, include_borrowed=True,
    )
    jd_digest: dict[str, Any] = {
        "parsed": parsed,
        "missing_keywords": ms.get("missing_keywords") or [],
        "tier_info": ms.get("tier_info") or {},
        "score": ms.get("score"),
    }

    # R6-B Phase 2: API mode 开关(spec §5.3)
    decided_mode, decided_warning = _decide_interview_mode(enable_interview_llm)

    session = InterviewSession(
        session_id="ia" + uuid.uuid4().hex[:8],
        target_role=target_role,
        jd_digest=jd_digest,
        selected_gap=None,
        state=InterviewState.DIAGNOSING,
        turn_count=0,
        captured_slots={},
        skip_count=0,
        draft_card=None,
        message_log=[],
        gap_candidates=None,
        # R6-B Phase 1: 可信增强层默认值
        # R6-B Phase 2: enable_interview_llm + env 决定 mode/warning
        interview_mode=decided_mode,
        mode_warning=decided_warning,
        slot_meta={},
        question_plan=None,
        verification_summary=None,
    )
    # 选缺口
    candidates = session.gap_candidates or _default_candidates()
    session.selected_gap = _select_gap_from_candidates(
        candidates,
        parsed=session.jd_digest.get("parsed", {}),
        missing=session.jd_digest.get("missing_keywords", []),
    )
    session.state = InterviewState.ASKING
    _INTERVIEW_SESSIONS[session.session_id] = session

    # trace: gap_select (step=0)
    _log_interview_trace(
        session,
        step=0,
        tool="gap_select",
        status="success",
        error_type=None,
        input_size=len((jd_text or "").encode("utf-8")),
        output_size=0,
    )
    return session


# ----------------------------------------------------------------------
# 公开 API 2:选缺口
# ----------------------------------------------------------------------
def select_gap(session: InterviewSession) -> GapCandidate:
    """从 session.gap_candidates 或默认 4 个里选 Top 1。"""
    candidates = session.gap_candidates or _default_candidates()
    return _select_gap_from_candidates(
        candidates,
        parsed=session.jd_digest.get("parsed", {}),
        missing=session.jd_digest.get("missing_keywords", []),
    )


# ----------------------------------------------------------------------
# 公开 API 3:下一问
# ----------------------------------------------------------------------
def next_question(session: InterviewSession) -> dict[str, Any]:
    """
    返回:
      {
        "slot": str,         # 当前追问的 slot
        "text": str,         # 问题文本
        "quick_replies": list[str],
      }
    全部 slot 都已问过 / 没有 gap / policy 强制 draft → 返空 dict(text="")

    R6-B Phase 3 增强(spec §6):
      - 内部用 interview_policy.plan_next_question 选 slot
      - 优先级: 强制 draft > 缺必要 slot > 低置信度 > gap suggested 未覆盖 >
                接近轮数上限 result/metric > next > anti-repeat
      - 旧前端的 message 输出结构完全保持兼容({slot, text, quick_replies} 三 key)
      - session.message_log 追加一条 {"kind": "asked", "slot": ..., "turn": ...}
        供 plan_next_question 的 anti-repeat 逻辑读取
      - rephrase_question / switch_gap 不调 next_question(路径独立, 各自行为见 _do_*)
    """
    # 延迟 import 防循环: interview_policy 也在 interview_agent 反向引用
    from core.interview_policy import plan_next_question

    gap = session.selected_gap
    if gap is None:
        # selected_gap 为空 → 仍要写 session.question_plan(便于前端审计 no_more)
        session.question_plan = {
            "slot": "",
            "reason_code": "no_gap_selected",
            "low_confidence_slots": [],
            "kind": INTERVIEW_POLICY_KIND_NO_MORE,
            "can_draft": False,
        }
        return {"slot": "", "text": "", "quick_replies": []}

    plan = plan_next_question(session)
    slot = str(plan.get("slot", "") or "")
    # 无论 slot 是否为空, 都写 session.question_plan(policy 决策审计)
    # no_more / force_draft 也需记录 reason_code 给前端
    if not isinstance(session.message_log, list):
        session.message_log = []
    session.question_plan = {
        "slot": slot,
        "reason_code": str(plan.get("reason_code", "") or ""),
        "low_confidence_slots": list(plan.get("low_confidence_slots", []) or []),
        "kind": str(plan.get("kind", INTERVIEW_POLICY_KIND_ASK)),
        "can_draft": bool(plan.get("can_draft", False)),
    }
    if not slot:
        # no_more / force_draft → 不渲染问题, 但 plan 已写
        return {"slot": "", "text": "", "quick_replies": []}

    # 写 session.message_log: 供 plan_next_question 的 anti-repeat 逻辑读
    session.message_log.append({
        "kind": "asked",
        "slot": slot,
        "turn": int(session.turn_count or 0),
    })

    text = QUESTION_TEMPLATES.get(
        (gap.gap_id, slot),
        f"请讲讲你在 {slot} 这一块的情况。",
    )
    return {
        "slot": slot,
        "text": text,
        "quick_replies": list(QUICK_REPLIES_BY_SLOT.get(slot, ())),
    }


# ----------------------------------------------------------------------
# 公开 API 4:槽位抽取(纯函数, 不 mutate session)
# ----------------------------------------------------------------------
def extract_slots(
    user_message: str,
    current_slot: str,
    session: InterviewSession | None = None,
    *,
    llm_enabled: bool = False,
    llm_api_key: str | None = None,
    llm_base_url: str | None = None,
    llm_model: str | None = None,
    turn_index: int = 0,
) -> dict[str, Any]:
    """
    按 current_slot 抽取 user_message,返回要写入 captured_slots 的 dict。
    不修改 session 业务字段(captured_slots / slot_meta)— 由 apply_action 负责 mutate。
    R6-C.3 起, session 不为 None 时, 本函数会更新 3 个 LLM 可观测性字段:
      - session.slot_source_breakdown: 每轮 answer 完成后 +1 (rules / llm / mixed)
      - session.llm_parse_retry_count: 累计 retry 次数
      - session.llm_to_rules_slot_fallback_count: 累计 fallback 次数

    Phase 1 行为(llm_enabled=False / 默认):规则抽取,字节级一致。
    Phase 4 行为(llm_enabled=True + 有 key):调 LLM,schema retry 1 次,
      失败 fallback 规则抽取,不抛(spec §4.4 "失败不阻断主流程")。

    R6-B Phase 1 增强(spec §5.2):
      - 返回 dict 新增 `_slot_meta` 字段, list[dict], 单元素 schema 见 _make_slot_meta
      - turn_index: 当前轮数, 默认 0;  写入 slot_meta 供 audit
      - 旧 key (background / responsibility / action / method / difficulty / result / metric / _warnings) 字节级一致

    规则版 schema(plan §1.3):
      - background / responsibility / difficulty / result: 单 string
      - action / method / metric: list
      未命中关键词 → 加 1 条 warning("未识别槽位内容, 已存原文供用户编辑")

    边界保护:
      - session=None → 不写任何可观测性字段(默认 tests 不传 session)
      - 老路径(llm_enabled=False) → slot_source_breakdown 只 +rules,
        llm_parse_retry_count / llm_to_rules_slot_fallback_count 永远 0
      - LLM 失败 → 仍走规则版, 但 slot_source_breakdown +rules (LLM 已 fallback)
        且 llm_to_rules_slot_fallback_count +1
    """
    # R6-C.3 可观测性 helper: 写 session.slot_source_breakdown[key] += 1
    def _bump_source(source_key: str) -> None:
        if session is None or not isinstance(session.slot_source_breakdown, dict):
            return
        session.slot_source_breakdown[source_key] = (
            session.slot_source_breakdown.get(source_key, 0) + 1
        )

    # Phase 4: 默认 / LLM 关闭 → 走规则版(Phase 1 字节级一致)
    config = _resolve_interview_llm_config(
        llm_enabled=llm_enabled,
        llm_api_key=llm_api_key,
        llm_base_url=llm_base_url,
        llm_model=llm_model,
    )
    if not config["enabled_for_call"]:
        _bump_source("rules")
        return _extract_slots_by_rules(user_message, current_slot, turn_index=turn_index)

    # Phase 4 LLM 路径: 失败 fallback 规则版
    parsed = _extract_slots_via_llm(
        user_message=user_message,
        current_slot=current_slot,
        config=config,
        turn_index=turn_index,
        session=session,
    )
    if parsed is None:
        # LLM 失败 fallback 规则版 — 同时记 rules 路径 +1, fallback 计数 +1
        _bump_source("rules")
        if session is not None:
            session.llm_to_rules_slot_fallback_count += 1
        return _extract_slots_by_rules(user_message, current_slot, turn_index=turn_index)
    _bump_source("llm")
    return parsed


def _extract_slots_by_rules(
    user_message: str,
    current_slot: str,
    *,
    turn_index: int = 0,
) -> dict[str, Any]:
    """
    Phase 1 规则版抽取(plan §1.3)— LLM 关闭 / LLM 失败时走这里。

    R6-B Phase 1 增强(spec §5.2):
      - 命中关键词 / regex 时 confidence = INTERVIEW_SLOT_META_RULES_CONFIDENCE_HIT(0.80)
      - fallback 路径 confidence = INTERVIEW_SLOT_META_RULES_CONFIDENCE_FALLBACK(0.40)
      - 命中证据片段时记 source_span_hash + source_span_len(spec §5.2 "规则抽取没精确 span 时,
        可使用当前 user_message 中命中的最短证据片段; 找不到时只记 extractor / confidence / turn_index")
      - 返回 dict 新增 `_slot_meta` 字段(list, 通常 1 条)
    """
    msg = user_message or ""
    warnings: list[str] = []

    def _hit_meta(reason_code: str, span: str | None) -> dict[str, Any]:
        """命中关键词 / regex 的 slot_meta — 带 source_span_hash。"""
        h, ln = _compute_source_span_hash(span)
        return _make_slot_meta(
            extractor="rules",
            confidence=INTERVIEW_SLOT_META_RULES_CONFIDENCE_HIT,
            turn_index=turn_index,
            reason_code=reason_code,
            source_span_hash=h,
            source_span_len=ln,
        )

    def _fb_meta(reason_code: str) -> dict[str, Any]:
        """fallback 路径 slot_meta — 无 source_span。"""
        return _make_slot_meta(
            extractor="rules",
            confidence=INTERVIEW_SLOT_META_RULES_CONFIDENCE_FALLBACK,
            turn_index=turn_index,
            reason_code=reason_code,
        )

    if current_slot == "background":
        val = msg.strip()[:200] if msg.strip() else ""
        if not val:
            warnings.append("未识别槽位内容, 已存原文供用户编辑")
            val = msg.strip()[:200]
            meta = _fb_meta("background_fallback")
        else:
            meta = _hit_meta("background_text", val if val else None)
        return {"background": val, "_warnings": warnings, "_slot_meta": [meta]}

    if current_slot == "responsibility":
        # 找 ["负责" / "主管" / "owner" / "主导"] 后面到下一个标点前的短语
        val = ""
        for kw in ("负责", "主管", "owner", "主导"):
            idx = msg.find(kw)
            if idx >= 0:
                # 找到下一个标点
                rest = msg[idx + len(kw):]
                for ch in (",", "。", ";", "\n", "，", "；"):
                    p = rest.find(ch)
                    if p >= 0:
                        val = rest[:p].strip()
                        break
                if not val:
                    val = rest.strip()
                break
        if not val:
            val = msg.strip()[:200]
            warnings.append("未识别责任描述关键词, 已存原文供用户编辑")
            meta = _fb_meta("responsibility_fallback")
        else:
            meta = _hit_meta("keyword_responsibility", val)
        return {"responsibility": val, "_warnings": warnings, "_slot_meta": [meta]}

    if current_slot == "action":
        # 按 ; / 。 / , / \n 切
        import re
        parts = re.split(r"[;。，,\n]", msg)
        actions = [p.strip() for p in parts if p.strip()]
        if not actions:
            actions = [msg.strip()]
            warnings.append("未识别动作描述, 已存原文供用户编辑")
            meta = _fb_meta("action_fallback")
        else:
            meta = _hit_meta("punctuation_split_action", "; ".join(actions))
        # 单数 key (与 slot_name 一致), captured_slots["action"] = [...]
        return {"action": actions, "_warnings": warnings, "_slot_meta": [meta]}

    if current_slot == "method":
        # 找 ["用了" / "采用" / "基于" / "通过"] 后面到句末
        methods: list[str] = []
        for kw in ("用了", "采用", "基于", "通过"):
            idx = msg.find(kw)
            if idx < 0:
                continue
            rest = msg[idx + len(kw):]
            # 句末:第一个句号/换行
            for ch in ("。", "\n", ";"):
                p = rest.find(ch)
                if p >= 0:
                    rest = rest[:p]
                    break
            m = rest.strip()
            if m:
                methods.append(f"{kw}{m}")
        if not methods:
            warnings.append("未识别方法描述, 已存原文供用户编辑")
            methods = [msg.strip()]
            meta = _fb_meta("method_fallback")
        else:
            meta = _hit_meta("keyword_method", " | ".join(methods))
        # 单数 key, captured_slots["method"] = [...]
        return {"method": methods, "_warnings": warnings, "_slot_meta": [meta]}

    if current_slot == "difficulty":
        # 找 ["难" / "坑" / "卡" / "问题"] 周围 30 字窗口
        val = ""
        for kw in ("难", "坑", "卡", "问题"):
            idx = msg.find(kw)
            if idx >= 0:
                start = max(0, idx - 30)
                end = min(len(msg), idx + 30)
                val = msg[start:end].strip()
                break
        if not val:
            val = msg.strip()[:200]
            warnings.append("未识别难点关键词, 已存原文供用户编辑")
            meta = _fb_meta("difficulty_fallback")
        else:
            meta = _hit_meta("keyword_difficulty", val)
        return {"difficulty": val, "_warnings": warnings, "_slot_meta": [meta]}

    if current_slot == "result":
        # 找 ["结果" / "最后" / "最终" / "产出"] 后面到句末
        val = ""
        for kw in ("结果", "最后", "最终", "产出"):
            idx = msg.find(kw)
            if idx >= 0:
                rest = msg[idx + len(kw):]
                for ch in ("。", "\n", ";"):
                    p = rest.find(ch)
                    if p >= 0:
                        rest = rest[:p]
                        break
                val = rest.strip()
                break
        if not val:
            val = msg.strip()[:200]
            warnings.append("未识别结果关键词, 已存原文供用户编辑")
            meta = _fb_meta("result_fallback")
        else:
            meta = _hit_meta("keyword_result", val)
        return {"result": val, "_warnings": warnings, "_slot_meta": [meta]}

    if current_slot == "metric":
        # regex 数字 + 单位
        import re
        pattern = r"(\d+(?:\.\d+)?)\s*(人|%|倍|小时|天|次|万|个|条|例)"
        matches = re.findall(pattern, msg)
        metrics: list[str] = []
        for num, unit in matches:
            metrics.append(f"{num}{unit}")
        if not metrics:
            warnings.append("未识别量化数据, 已存原文供用户编辑")
            metrics = [msg.strip()] if msg.strip() else []
            meta = _fb_meta("metric_fallback")
        else:
            meta = _hit_meta("regex_metric", " ".join(metrics))
        # 单数 key, captured_slots["metric"] = [...]
        return {"metric": metrics, "_warnings": warnings, "_slot_meta": [meta]}

    # 未知 slot:返空 + 无 meta(spec §5.2 不强记)
    return {}


# ----------------------------------------------------------------------
# R6-A Phase 4: LLM slot 抽取 helpers(plan §4.4)
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


# ----------------------------------------------------------------------
# 公开 API 5:can_draft / build_draft_card
# ----------------------------------------------------------------------
def can_draft(session: InterviewSession) -> bool:
    """满足 CAN_DRAFT_CONDITIONS 任一组合 → True。"""
    slots = session.captured_slots or {}
    for combo in CAN_DRAFT_CONDITIONS:
        ok = True
        for slot in combo:
            val = slots.get(slot)
            if slot in ("background", "responsibility", "difficulty", "result"):
                if not val or not isinstance(val, str) or not val.strip():
                    ok = False
                    break
            else:  # list slot
                if not val or not isinstance(val, list) or len(val) == 0:
                    ok = False
                    break
        if ok:
            return True
    return False


def build_draft_card(session: InterviewSession) -> dict[str, Any]:
    """
    生成可编辑素材卡(dict, 不写入 materials.json — Phase 1 不写库)。
    Phase 2 save-card 端点负责把这个 dict 追加为新 project。

    字段命名:
      - captured_slots 用单数 key (action / method / metric) 与 slot_name 一致
      - draft_card 输出用复数 key (actions / methods / metrics) 便于业务侧消费
    """
    gap = session.selected_gap
    slots = session.captured_slots or {}
    responsibility = slots.get("responsibility") or slots.get("background") or ""
    title = f"{responsibility or '新经历'}({gap.label if gap else '草稿'})"
    # captured_slots 单数 key, draft_card 复数 key
    actions = list(slots.get("action") or [])
    methods = list(slots.get("method") or [])
    metrics = list(slots.get("metric") or [])

    warnings: list[str] = []
    if not metrics:
        warnings.append("缺少量化数据, 建议补一个数字(人数/比例/时长/次数)")
    if not slots.get("result"):
        warnings.append("缺少结果描述, 建议补一句带来的变化")
    if not methods:
        warnings.append("缺少方法描述, 建议补一句你具体怎么做的")
    if not actions:
        warnings.append("缺少动作描述, 建议拆成 2-3 个具体步骤")

    # draft_bullets: 把 actions 拼成 bullet, 每条 ≤200 字
    draft_bullets: list[str] = []
    for a in actions:
        bullet = a.strip()
        if methods and slots.get("result"):
            bullet = f"{bullet}(用 {'/'.join(methods[:2])}, 最终 {slots['result']})"
        elif methods:
            bullet = f"{bullet}(用 {'/'.join(methods[:2])})"
        elif slots.get("result"):
            bullet = f"{bullet}(最终 {slots['result']})"
        if metrics:
            bullet = f"{bullet}, 量化: {', '.join(metrics[:2])}"
        draft_bullets.append(bullet[:200])

    return {
        "title": title[:200],
        "target_role": session.target_role,
        "source_gap_id": gap.gap_id if gap else "",
        "background": slots.get("background") or "",
        "responsibility": responsibility,
        "actions": actions,
        "methods": methods,
        "difficulty": slots.get("difficulty") or "",
        "result": slots.get("result") or "",
        "metrics": metrics,
        "skills": [],
        "draft_bullets": draft_bullets,
        "warnings": warnings,
    }


# ----------------------------------------------------------------------
# 公开 API 6:apply_action (状态机统一入口)
# ----------------------------------------------------------------------
def _do_answer(session: InterviewSession, user_message: str) -> tuple[InterviewSession, dict]:
    sess = session
    slot = _current_slot(sess)
    # turn_index 用当前 turn_count + 1(spec §5.2 turn_index 反映这一轮是第几轮)
    # 注意: extract_slots 返回之后 turn_count 还没自增, 所以 turn_index = turn_count + 1
    next_turn_index = (sess.turn_count or 0) + 1
    # R6-B Phase 2(spec §5.3): reply 沿用 session.interview_mode 决定 llm_enabled
    # 老路径(sess.interview_mode == "rules") 字节级一致: llm_enabled=False 走 _extract_slots_by_rules
    use_llm = (sess.interview_mode == INTERVIEW_MODE_LLM_ASSISTED)
    # R6-C.3: 传 sess 让 extract_slots 写 3 个可观测性字段
    # (slot_source_breakdown / llm_parse_retry_count / llm_to_rules_slot_fallback_count)
    delta = extract_slots(
        user_message, slot or "", sess,
        turn_index=next_turn_index,
        llm_enabled=use_llm,
    )
    # 清掉 _warnings(它不属于 captured_slots 业务字段)
    delta.pop("_warnings", None)
    # R6-B Phase 1(spec §5.2): 把 _slot_meta 写入 session.slot_meta[slot],
    # 然后从 delta 删掉,避免污染 captured_slots(spec §5.2 + AGENTS.md 隐私边界)
    new_meta_entries = delta.pop("_slot_meta", None)
    if isinstance(new_meta_entries, list) and new_meta_entries and slot:
        _append_slot_meta(sess, slot, new_meta_entries)
    sess.captured_slots.update(delta)
    sess.turn_count += 1

    _log_interview_trace(
        sess,
        step=sess.turn_count,
        tool="slot_extract",
        status="success",
        error_type=None,
        input_size=len((user_message or "").encode("utf-8")),
        output_size=len(json.dumps(delta, ensure_ascii=False).encode("utf-8")),
    )

    # R6-B Phase 2(spec §5.3): 构造 extraction_summary + question_plan
    extraction_summary = _build_extraction_summary(
        new_meta_entries=new_meta_entries if isinstance(new_meta_entries, list) else None,
        captured_delta=delta,
        intended_mode=sess.interview_mode,
    )
    question_plan = _build_question_plan(sess)

    # 决定下一步
    force = (
        can_draft(sess)
        or sess.turn_count >= MAX_TURNS_PER_GAP
        or (sess.skip_count >= MAX_CONSECUTIVE_SKIPS)
    )
    if force:
        sess.state = InterviewState.DRAFT_READY
        nxt = next_question(sess)
        return sess, {
            "state": sess.state.value,
            "message": nxt if nxt.get("text") else None,
            "captured_delta": delta,
            "progress": _progress(sess),
            "can_draft": can_draft(sess),
            "force_draft": True,
            "extraction_summary": extraction_summary,
            "question_plan": question_plan,
        }
    nxt = next_question(sess)
    return sess, {
        "state": sess.state.value,
        "message": nxt,
        "captured_delta": delta,
        "progress": _progress(sess),
        "can_draft": can_draft(sess),
        "force_draft": False,
        "extraction_summary": extraction_summary,
        "question_plan": question_plan,
    }


def _do_skip(session: InterviewSession) -> tuple[InterviewSession, dict]:
    sess = session
    sess.skip_count += 1
    sess.turn_count += 1

    _log_interview_trace(
        sess,
        step=sess.turn_count,
        tool="slot_extract",
        status="skipped",
        error_type=None,
        input_size=0,
        output_size=0,
    )

    force = (
        sess.skip_count >= MAX_CONSECUTIVE_SKIPS
        or sess.turn_count >= MAX_TURNS_PER_GAP
    )
    if force:
        sess.state = InterviewState.DRAFT_READY
    nxt = next_question(sess)
    return sess, {
        "state": sess.state.value,
        "message": nxt if nxt.get("text") else None,
        "captured_delta": None,
        "progress": _progress(sess),
        "can_draft": can_draft(sess),
        "force_draft": force,
        # R6-B Phase 2: skip 不发生抽取, extraction_summary=None
        "extraction_summary": None,
        "question_plan": _build_question_plan(sess),
    }


def _do_rephrase(session: InterviewSession) -> tuple[InterviewSession, dict]:
    """同一 slot, text 加 '[换个问法]' 前缀(R6-B Phase 3: 不换 slot)。

    实现(spec §6 防重复): 不调 next_question()(会让 policy 跑 anti-repeat
    切换 slot), 直接从 session.question_plan.slot 拿当前 slot 渲染。

    边界:
      - session.question_plan 为 None(还没 next_question 跑过):
        fallback 到 _current_slot(session), 仍 None 就 fallback 到 gap.suggested_slots[0]
      - session.selected_gap 为 None: 返空 message
      - 不调 next_question, 因此不会写 session.message_log / 更新 session.question_plan.slot,
        确保 "rephrase 不换 slot" 这条边界(spec §6 防重复)
    """
    sess = session
    slot = ""
    qp = sess.question_plan or {}
    if isinstance(qp, dict) and isinstance(qp.get("slot"), str) and qp.get("slot"):
        slot = qp["slot"]
    elif sess.selected_gap is not None:
        cs = _current_slot(sess)
        if cs:
            slot = cs
        elif sess.selected_gap.suggested_slots:
            slot = sess.selected_gap.suggested_slots[0]
    if not slot or sess.selected_gap is None:
        return sess, {
            "state": sess.state.value,
            "message": {"slot": "", "text": "", "quick_replies": []},
            "captured_delta": None,
            "progress": _progress(sess),
            "can_draft": can_draft(sess),
            "force_draft": False,
            "extraction_summary": None,
            "question_plan": _build_question_plan(sess),
        }
    text = QUESTION_TEMPLATES.get(
        (sess.selected_gap.gap_id, slot),
        f"请讲讲你在 {slot} 这一块的情况。",
    )
    return sess, {
        "state": sess.state.value,
        "message": {
            "slot": slot,
            "text": f"[换个问法] {text}",
            "quick_replies": list(QUICK_REPLIES_BY_SLOT.get(slot, ())),
        },
        "captured_delta": None,
        "progress": _progress(sess),
        "can_draft": can_draft(sess),
        "force_draft": False,
        "extraction_summary": None,
        "question_plan": _build_question_plan(sess),
    }


def _do_switch_gap(session: InterviewSession) -> tuple[InterviewSession, dict]:
    """重置 captured_slots / skip_count / turn_count, 选新 gap(排除当前)。

    R6-B Phase 3 隔离旧 gap 的所有 plan 状态(spec §6 "switch_gap 后清空
    或隔离旧 gap 的 question plan, 避免跨 gap 混用"):
      - captured_slots / skip_count / turn_count / draft_card (Phase 1 已有)
      - slot_meta / question_plan (Phase 1 已有)
      - message_log (Phase 3 新增: 清空 last_asked_slot, 避免跨 gap
        anti-repeat 误判 / 新 gap 第一问被错误跳过)
    """
    sess = session
    current_gap_id = sess.selected_gap.gap_id if sess.selected_gap else None
    all_candidates = sess.gap_candidates or _default_candidates()
    other = [c for c in all_candidates if c.gap_id != current_gap_id]
    if not other:
        other = all_candidates
    parsed = sess.jd_digest.get("parsed", {})
    missing = sess.jd_digest.get("missing_keywords", [])
    sess.selected_gap = _select_gap_from_candidates(other, parsed, missing)
    sess.captured_slots = {}
    sess.skip_count = 0
    sess.turn_count = 0
    sess.state = InterviewState.ASKING
    sess.draft_card = None
    # R6-B Phase 1+3: 隔离旧 gap 的 question_plan / slot_meta / message_log
    sess.slot_meta = {}
    sess.question_plan = None
    sess.message_log = []
    nxt = next_question(sess)
    return sess, {
        "state": sess.state.value,
        "message": nxt,
        "captured_delta": None,
        "progress": _progress(sess),
        "can_draft": False,
        "force_draft": False,
        "extraction_summary": None,
        "question_plan": _build_question_plan(sess),
    }


def _do_draft_now(session: InterviewSession) -> tuple[InterviewSession, dict]:
    """强制 draft_now — can_draft=False 时抛 ValueError (api 层捕获 → 400)。

    R6-B Phase 4(spec §7): build_draft_card 之后调 verify_draft_card
    把 verification + confidence_notes 注入到 sess.draft_card(供 DraftResponse 返回),
    同时缓存到 sess.verification_summary 供后续 save_card 写 _interview_meta.verification。

    边界:
      - verifier 默认不调 LLM(stdlib + regex), 失败不阻断(spec §6.3)
      - 注入的 verification / confidence_notes 不含 draft_card 原文 / user_message /
        source_span 明文 / API key
      - 老路径不会触发 _do_draft_now 时与 Phase 1 一致(verifier 只挂在 _do_draft_now + /draft)
    """
    sess = session
    if not can_draft(sess):
        raise ValueError("can_draft=False, 不允许 draft_now")
    sess.draft_card = build_draft_card(sess)

    # R6-B Phase 4(spec §7): 注入 verification + confidence_notes 到 draft_card
    # 延迟 import 防 circular: interview_verifier 未来若反向 import interview_agent 会安全
    from core.interview_verifier import (
        compute_confidence_notes,
        verify_draft_card,
    )

    verification = verify_draft_card(sess.draft_card, sess)
    confidence_notes = compute_confidence_notes(sess)
    # 缓存到 session(供 save_card 写 _interview_meta.verification 摘要)
    sess.verification_summary = verification
    # 注入到 card dict(DraftResponse.draft_card 直接挂在 card 里)
    if isinstance(sess.draft_card, dict):
        sess.draft_card["verification"] = verification
        sess.draft_card["confidence_notes"] = confidence_notes

    sess.state = InterviewState.DRAFT_READY

    output_size = len(
        json.dumps(sess.draft_card, ensure_ascii=False).encode("utf-8")
    )
    _log_interview_trace(
        sess,
        step=sess.turn_count + 1,
        tool="draft_card",
        status="success",
        error_type=None,
        input_size=0,
        output_size=output_size,
    )
    return sess, {
        "state": sess.state.value,
        "message": None,
        "captured_delta": None,
        "progress": _progress(sess),
        "can_draft": True,
        "force_draft": True,
        "extraction_summary": None,
        "question_plan": None,
    }


def apply_action(
    session: InterviewSession,
    action: ActionType,
    user_message: str | None = None,
) -> tuple[InterviewSession, dict]:
    """状态机统一入口。返回 (session, response_dict)。"""
    if action == ActionType.ANSWER:
        return _do_answer(session, user_message or "")
    if action == ActionType.SKIP_QUESTION:
        return _do_skip(session)
    if action == ActionType.REPHRASE_QUESTION:
        return _do_rephrase(session)
    if action == ActionType.SWITCH_GAP:
        return _do_switch_gap(session)
    if action == ActionType.DRAFT_NOW:
        return _do_draft_now(session)
    raise ValueError(f"未知 action: {action!r}")


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
# 暴露模块级符号, 供 from core.interview_agent import * 测试用
# ----------------------------------------------------------------------
__all__ = [
    "InterviewState", "ActionType",
    "GapCandidate", "InterviewSession",
    "create_session", "select_gap", "next_question", "extract_slots",
    "can_draft", "build_draft_card", "apply_action",
    "get_session", "reset_session", "save_card",
    "DEFAULT_MATERIALS_PATH",
    "INTERVIEW_BULLET_MAX_LEN", "INTERVIEW_REQUIRED_EDITED_KEYS",
    "MAX_TURNS_PER_GAP",
    # R6-A Phase 4: LLM slot 抽取(plan §4.4)
    "_resolve_interview_llm_config",
    "_extract_slots_by_rules",
    "_extract_slots_via_llm",
    "_call_llm_for_slot_extraction",
    "_try_parse_llm_content",
    "_validate_llm_extraction_payload",
    # R6-B Phase 1: slot_meta provenance(spec §5.2)
    "INTERVIEW_SLOT_META_MAX",
    "INTERVIEW_SLOT_META_RULES_CONFIDENCE_HIT",
    "INTERVIEW_SLOT_META_RULES_CONFIDENCE_FALLBACK",
    "INTERVIEW_SLOT_META_LLM_DEFAULT_CONFIDENCE",
    "_validate_confidence",
    "_compute_source_span_hash",
    "_make_slot_meta",
    "_append_slot_meta",
    "_attach_llm_slot_meta",
    # R6-B Phase 2: API mode 开关(spec §5.3)
    "INTERVIEW_LLM_NO_KEY_WARNING",
    "INTERVIEW_MODE_RULES",
    "INTERVIEW_MODE_LLM_ASSISTED",
    "INTERVIEW_LOW_CONFIDENCE_THRESHOLD",
    "_has_llm_api_key",
    "_decide_interview_mode",
    "_build_extraction_summary",
    "_build_question_plan",
    # 测试用内部 helper
    "_score_gap", "_select_gap_from_candidates",
    "_default_candidates", "_INTERVIEW_SESSIONS",
    "_log_interview_trace",
    "_validate_edited_card", "_generate_project_id",
    # R6-C.3: LLM 抽取可观测性字段名(供 tests + scripts 引用)
    "INTERVIEW_OBSERVABILITY_SCHEMA",
]