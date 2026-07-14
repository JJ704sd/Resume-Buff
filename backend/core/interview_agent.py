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

Round 6-D: 机械拆分 LLM slot 抽取模块(行为不变, 2026-07-02 落地):
  - 新建 backend/core/interview_llm.py, 物理分离以下符号(全部 LLM slot extraction 相关):
      * mode 决策: INTERVIEW_MODE_RULES / INTERVIEW_MODE_LLM_ASSISTED /
        INTERVIEW_LLM_NO_KEY_WARNING + _has_llm_api_key + _decide_interview_mode
      * 默认 base_url / model: _INTERVIEW_LLM_DEFAULT_BASE_URL / _INTERVIEW_LLM_DEFAULT_MODEL
      * slot_meta confidence 常量: INTERVIEW_SLOT_META_MIN_CONFIDENCE /
        INTERVIEW_SLOT_META_MAX_CONFIDENCE / INTERVIEW_SLOT_META_RULES_CONFIDENCE_FALLBACK /
        INTERVIEW_SLOT_META_LLM_DEFAULT_CONFIDENCE
      * R6-C.3 可观测性 schema: INTERVIEW_OBSERVABILITY_SCHEMA
      * slot_meta helper(规则版 + LLM 版共用): _validate_confidence /
        _compute_source_span_hash / _make_slot_meta
      * LLM 抽取主链路: _resolve_interview_llm_config / _validate_llm_extraction_payload /
        _call_llm_for_slot_extraction / _try_parse_llm_content / _extract_slots_via_llm /
        _attach_llm_slot_meta
  - 本模块(interview_agent.py)通过 from core.interview_llm import ... 重导出全部上述符号,
    保持向后兼容(test_interview_agent / scripts 仍可 `from core.interview_agent import ...`)。
  - 边界:
      * core.interview_llm 不得 import core.interview_agent(仅 TYPE_CHECKING 类型注解)
      * core.interview_llm 不得 import core.llm_rewriter(R5-E 边界保持)
      * 行为完全不变: 老路径(llm_enabled=False / 默认)字节级一致, 3 个可观测字段保持 0 / {} / {}
      * 测试平移: TestLLMSlotExtraction / TestSlotMetaLlmR6B / TestSlotMetaUnitR6B /
        TestPhaseC3LLMObservability / TestInterviewPromptRegistry + trace 隐私 2 case
        平移到 test_interview_llm.py, mock urlopen 路径从 core.interview_agent.urllib
        改为 core.interview_llm.urllib
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

# R6-D: 重导出 LLM slot extraction 相关符号, 保持向后兼容。
# 物理实现搬到 core.interview_llm, 本模块通过 import 暴露同名符号,
# 让现有 `from core.interview_agent import _attach_llm_slot_meta` 仍工作。
from core.interview_llm import (  # noqa: F401  re-export for backward compat
    INTERVIEW_LLM_NO_KEY_WARNING,
    INTERVIEW_MODE_LLM_ASSISTED,
    INTERVIEW_MODE_RULES,
    INTERVIEW_OBSERVABILITY_SCHEMA,
    INTERVIEW_SLOT_META_LLM_DEFAULT_CONFIDENCE,
    INTERVIEW_SLOT_META_MAX_CONFIDENCE,
    INTERVIEW_SLOT_META_MIN_CONFIDENCE,
    INTERVIEW_SLOT_META_RULES_CONFIDENCE_FALLBACK,
    _INTERVIEW_LLM_DEFAULT_BASE_URL,
    _INTERVIEW_LLM_DEFAULT_MODEL,
    _attach_llm_slot_meta,
    _call_llm_for_slot_extraction,
    _compute_source_span_hash,
    _decide_interview_mode,
    _extract_slots_via_llm,
    _has_llm_api_key,
    _make_slot_meta,
    _resolve_interview_llm_config,
    _try_parse_llm_content,
    _validate_confidence,
    _validate_llm_extraction_payload,
)

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

INTERVIEW_SLOT_META_RULES_CONFIDENCE_HIT: float = 0.80
"""规则抽取命中关键词 / regex 时的 confidence 默认值。"""

# 注意: INTERVIEW_SLOT_META_MIN_CONFIDENCE / MAX_CONFIDENCE / RULES_CONFIDENCE_FALLBACK /
# LLM_DEFAULT_CONFIDENCE 已在 R6-D 搬到 core.interview_llm, 本模块通过
# `from core.interview_llm import ...` 重导出(spec §5.2 + §5.3)。


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
    # R6-E Phase 4 fix: slot 选择优先用 sess.question_plan["slot"](policy 决策结果),
    # 而不是按 gap.suggested_slots 顺序跳过 captured 的 _current_slot 兜底。
    #
    # 为什么需要这个修复:
    #   - 缺口选择走 plan_next_question(spec §6 优先级链), 它按 CAN_DRAFT_CONDITIONS
    #     找"差得最少"的 combo, 然后问 combo 里第一个未 captured 的 slot。
    #   - 例如 communication gap (suggested=("background","action","method","result"))
    #     走到第 3 轮时, policy 已经满足 combo1 (background, action, result) 中前两个,
    #     缺的是 result, 所以 policy 在 question_plan.slot 写 "result"(UI 也问 result)。
    #   - 但 _current_slot 按 suggested 顺序跳 background + action, 返回 "method"
    #     (第一个未 captured),导致抽取把用户答的 result 内容塞进 method slot,
    #     result slot 永远空, combo1 永远不满, can_draft=False, /draft 端点 400。
    #
    # 修复策略(最小侵入):
    #   1. 优先用 sess.question_plan["slot"](policy 决定要问哪个 slot)
    #   2. fallback 到 _current_slot(sess)(spec 兼容: 老测试 / 非 policy 路径仍能用)
    #   3. 再 fallback 到 ""(extract_slots 在未知 slot 时返空 dict,不抛)
    #
    # 不动 _current_slot 本体(_do_rephrase 还在用), 不动 next_question / plan_next_question
    # (R6-B Phase 3 / R6-C.2B 锁定), 不动 slot 抽取逻辑(R6-C.3 / Phase 1 锁定)。
    plan = sess.question_plan if isinstance(sess.question_plan, dict) else None
    plan_slot = str((plan or {}).get("slot") or "").strip()
    if plan_slot:
        slot = plan_slot
    else:
        current = _current_slot(sess)
        slot = current or ""
    # turn_index 用当前 turn_count + 1(spec §5.2 turn_index 反映这一轮是第几轮)
    # 注意: extract_slots 返回之后 turn_count 还没自增, 所以 turn_index = turn_count + 1
    next_turn_index = (sess.turn_count or 0) + 1
    # R6-B Phase 2(spec §5.3): reply 沿用 session.interview_mode 决定 llm_enabled
    # 老路径(sess.interview_mode == "rules") 字节级一致: llm_enabled=False 走 _extract_slots_by_rules
    use_llm = (sess.interview_mode == INTERVIEW_MODE_LLM_ASSISTED)
    # R6-K: circuit breaker 强制降级
    # circuit open + 当前 session 想用 LLM → 强制 mode="rules" + mode_warning 提示用户
    # 避免 32 min 端点卡场景下 user 看到 30+ 秒的 hang 后才 fallback
    # 不动 retry/schema/token 路径 (R6-H §6), 仅在 _do_answer 入口改 mode 让 extract_slots
    # 走 rules 路径 (extract_slots 内部 llm_enabled=False 时不调 LLM)
    from core.llm_circuit_breaker import get_circuit  # 局部 import 防循环依赖
    circuit = get_circuit()
    if use_llm and not circuit.allow_request():
        # 强制降级 rules
        use_llm = False
        remaining = circuit.time_until_probe()
        # 隐私边界 (R6-K spec §2.5 + AGENTS.md):
        # - 不含 LLM_API_KEY 字面量
        # - 不含 user_message 原文
        # - 不含 source_span / prompt
        # 通用描述 "LLM 端点" + circuit 状态 + 倒计时
        sess.interview_mode = "rules"
        sess.mode_warning = (
            f"LLM 端点暂不可用 (circuit {circuit.state()}, "
            f"距下次试探 {int(remaining)}s), 已使用规则模式"
        )
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