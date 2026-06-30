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
  - InterviewSession (@dataclass)     11 字段(可 mutate,Phase 1 in-place)
  - create_session / select_gap / next_question / extract_slots
  - can_draft / build_draft_card / apply_action
  - get_session / reset_session / save_card
  - _resolve_interview_llm_config     (Phase 4 helper, 测试用)
"""
from __future__ import annotations

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
        "_interview_meta": {
            "source_gap_id": session.selected_gap.gap_id if session.selected_gap else "",
            "source_session_id": session.session_id,
            "created_at": datetime.now().astimezone().isoformat(),
            "warnings": list(edited_card.get("warnings") or []),
        },
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
) -> InterviewSession:
    """
    创建 session:
      - parse_jd + match_score 抽取 JD 摘要
      - select_gap 自动选 Top 1 gap
      - 写 trace (tool=gap_select)
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
    全部 slot 都已问过 / 没有 gap → 返空 dict(text="")
    """
    gap = session.selected_gap
    if gap is None:
        return {"slot": "", "text": "", "quick_replies": []}
    slot = _current_slot(session)
    if slot is None:
        return {"slot": "", "text": "", "quick_replies": []}
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
    session: InterviewSession | None = None,  # noqa: ARG001  Phase 1+4 不使用,保留扩展位
    *,
    llm_enabled: bool = False,
    llm_api_key: str | None = None,
    llm_base_url: str | None = None,
    llm_model: str | None = None,
) -> dict[str, Any]:
    """
    按 current_slot 抽取 user_message,返回要写入 captured_slots 的 dict。
    不修改 session — 由 apply_action 负责 mutate。

    Phase 1 行为(llm_enabled=False / 默认):规则抽取,字节级一致。
    Phase 4 行为(llm_enabled=True + 有 key):调 LLM,schema retry 1 次,
      失败 fallback 规则抽取,不抛(spec §4.4 "失败不阻断主流程")。

    规则版 schema(plan §1.3):
      - background / responsibility / difficulty / result: 单 string
      - action / method / metric: list
      未命中关键词 → 加 1 条 warning("未识别槽位内容, 已存原文供用户编辑")
    """
    # Phase 4: 默认 / LLM 关闭 → 走规则版(Phase 1 字节级一致)
    config = _resolve_interview_llm_config(
        llm_enabled=llm_enabled,
        llm_api_key=llm_api_key,
        llm_base_url=llm_base_url,
        llm_model=llm_model,
    )
    if not config["enabled_for_call"]:
        return _extract_slots_by_rules(user_message, current_slot)

    # Phase 4 LLM 路径: 失败 fallback 规则版
    parsed = _extract_slots_via_llm(
        user_message=user_message,
        current_slot=current_slot,
        config=config,
    )
    if parsed is None:
        return _extract_slots_by_rules(user_message, current_slot)
    return parsed


def _extract_slots_by_rules(
    user_message: str,
    current_slot: str,
) -> dict[str, Any]:
    """Phase 1 规则版抽取(plan §1.3)— LLM 关闭 / LLM 失败时走这里。"""
    msg = user_message or ""
    warnings: list[str] = []

    if current_slot == "background":
        val = msg.strip()[:200] if msg.strip() else ""
        if not val:
            warnings.append("未识别槽位内容, 已存原文供用户编辑")
            val = msg.strip()[:200]
        return {"background": val, "_warnings": warnings}

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
        return {"responsibility": val, "_warnings": warnings}

    if current_slot == "action":
        # 按 ; / 。 / , / \n 切
        import re
        parts = re.split(r"[;。，,\n]", msg)
        actions = [p.strip() for p in parts if p.strip()]
        if not actions:
            actions = [msg.strip()]
            warnings.append("未识别动作描述, 已存原文供用户编辑")
        # 单数 key (与 slot_name 一致), captured_slots["action"] = [...]
        return {"action": actions, "_warnings": warnings}

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
        # 单数 key, captured_slots["method"] = [...]
        return {"method": methods, "_warnings": warnings}

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
        return {"difficulty": val, "_warnings": warnings}

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
        return {"result": val, "_warnings": warnings}

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
        # 单数 key, captured_slots["metric"] = [...]
        return {"metric": metrics, "_warnings": warnings}

    # 未知 slot:返空
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

    隐私边界(plan §4.3):
      - api_key 仅作 Authorization header, 不进返回值 / 日志
      - 失败时不返回响应原文
    """
    url = base_url.rstrip("/") + "/chat/completions"
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": SLOT_EXTRACTION_SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
        ],
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
) -> dict[str, Any] | None:
    """
    Phase 4 LLM 抽取主路径(plan §4.4):
      1. 构造 user payload (含 slot + user_message,**不**含 jd_text)
      2. 调 _call_llm_for_slot_extraction
      3. 解析 response.content JSON
      4. _validate_llm_extraction_payload 校验
      5. schema retry 1 次 (strict_retry=True — 沿用 _call_with_retry 模式)
      6. 失败 → None(caller fallback 到 _extract_slots_by_rules)

    隐私边界(plan §4.3 + AGENTS.md):
      - payload 只含 slot + user_message,**不**含 jd_text / session / materials
      - api_key 永不入返回值 / trace
      - 失败不返回响应原文

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
    validated = _validate_llm_extraction_payload(parsed, current_slot) if isinstance(parsed, dict) else None

    if validated is not None:
        return validated

    # JSON / schema 都失败 → retry 1 次, 加强约束(strict_retry=True, 沿用 _call_with_retry)
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
    return _validate_llm_extraction_payload(parsed, current_slot)


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
    delta = extract_slots(user_message, slot or "")
    # 清掉 _warnings(它不属于 captured_slots 业务字段)
    delta.pop("_warnings", None)
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
        }
    nxt = next_question(sess)
    return sess, {
        "state": sess.state.value,
        "message": nxt,
        "captured_delta": delta,
        "progress": _progress(sess),
        "can_draft": can_draft(sess),
        "force_draft": False,
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
    }


def _do_rephrase(session: InterviewSession) -> tuple[InterviewSession, dict]:
    """同一 slot, text 加 '[换个问法]' 前缀(简易实现)。"""
    sess = session
    nxt = next_question(sess)
    if nxt.get("text"):
        nxt["text"] = f"[换个问法] {nxt['text']}"
    return sess, {
        "state": sess.state.value,
        "message": nxt,
        "captured_delta": None,
        "progress": _progress(sess),
        "can_draft": can_draft(sess),
        "force_draft": False,
    }


def _do_switch_gap(session: InterviewSession) -> tuple[InterviewSession, dict]:
    """重置 captured_slots / skip_count / turn_count, 选新 gap(排除当前)。"""
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
    nxt = next_question(sess)
    return sess, {
        "state": sess.state.value,
        "message": nxt,
        "captured_delta": None,
        "progress": _progress(sess),
        "can_draft": False,
        "force_draft": False,
    }


def _do_draft_now(session: InterviewSession) -> tuple[InterviewSession, dict]:
    """强制 draft_now — can_draft=False 时抛 ValueError (api 层捕获 → 400)。"""
    sess = session
    if not can_draft(sess):
        raise ValueError("can_draft=False, 不允许 draft_now")
    sess.draft_card = build_draft_card(sess)
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
    # 测试用内部 helper
    "_score_gap", "_select_gap_from_candidates",
    "_default_candidates", "_INTERVIEW_SESSIONS",
    "_log_interview_trace",
    "_validate_edited_card", "_generate_project_id",
]