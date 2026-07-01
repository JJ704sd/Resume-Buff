"""
Round 6-B Phase 3: confidence-aware deterministic next-question policy 
Round 6-C.2B: gap-specific critical slot 补足(R6-C.1 contract warning 触发的 policy 调整)

设计原则(spec §6 + AGENTS.md):
  - 完全 deterministic, **不调用网络**, **不调用 LLM**
  - LLM 不决定 slot 顺序(policy 是唯一决策者, 后续 Phase 4+ 可能让 LLM 改写 text 但**不**改 slot)
  - 输入: InterviewSession 状态(纯只读, 不 mutate)
  - 输出: dict, 字段与 spec §5.3 一致 + 扩展("can_draft" / "kind" 给 _build_question_plan 复用)

R6-C.2B 增量(spec §4.5 contract warning 分布):
  - 新增 INTERVIEW_POLICY_GAP_CRITICAL_SLOTS 补足集合(tech_metric + communication)
  - 新增 INTERVIEW_POLICY_REASON_GAP_CRITICAL_SLOT reason_code
  - 新增 step 4.5: 在 missing_required + low_confidence 之后, near_limit + next_suggested
    之前, 主动追问 gap-critical slot
  - 不修改 GAP_SUGGESTED_SLOTS(那是 interview_prompts 设计常量, 改它会污染 LLM 抽取链路)
  - 不修改 CAN_DRAFT_CONDITIONS / MAX_TURNS_PER_GAP / SLOT_NAMES

公开 API:
  - plan_next_question(session) -> dict   spec §6 priority chain

强制约束(AGENTS.md / spec §13):
  - 不调用网络 (no urllib / no requests / no httpx / no openai)
  - 不调用 LLM(不读 LLM_API_KEY / 不调任何 model API)
  - 不读 env var
  - 不写文件
  - 不 mutate session(纯函数: 输入 session 引用, 只读其字段)
  - 不 import core.llm_rewriter / core.agent_workflow / core.agent_tools(沿用 R5-E 边界)

隐私边界(spec §6 / §12 + AGENTS.md):
  - 返回 dict 不含 user_message / source_span / draft_card 原文
  - 不含 API key / LLM prompt / 任何 user_message 原文
  - 只列 slot 名 / reason_code / 简单计数 — 不暴露 PII

R5-E 边界保护(R6-B Phase 1/2 已落地, Phase 3 继续保持):
  - 不出现在 prompt versioning 链路(PROMPT_VERSIONS 不加新 key)
  - 不修改 core.llm_rewriter / core.agent_workflow
  - 不修改 core.interview_prompts 中的常量(只用其读视角)
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from core.interview_prompts import (
    CAN_DRAFT_CONDITIONS,
    MAX_CONSECUTIVE_SKIPS,
    MAX_TURNS_PER_GAP,
    SLOT_NAMES,
)

if TYPE_CHECKING:
    # 避免循环 import — 仅用于类型提示; 运行时 duck type 即可
    from core.interview_agent import InterviewSession


# ----------------------------------------------------------------------
# 常量 — 阈值 / reason_code
# ----------------------------------------------------------------------
# 跟 interview_agent.INTERVIEW_LOW_CONFIDENCE_THRESHOLD 一致(本模块不 import
# interview_agent 防循环, 复制 0.6 跟 AGENTS.md 已锁死的 "≥0.6 视为低置信度" 对齐)。
INTERVIEW_POLICY_LOW_CONFIDENCE: float = 0.6
"""confidence < 0.6 视为低置信度, 优先 re-ask(spec §6 step 2)。"""

# 抗重复阈值(spec §6 "防重复"): 上次同 slot 答得 confidence >= 0.4
# 就视作已经"答过", 切去 alternative slot。
INTERVIEW_POLICY_ANTI_REPEAT_CONFIDENCE: float = 0.4
"""anti-repeat 阈值, 跟 spec §6 "上一次 confidence < 0.4 才允许再问" 对齐。"""

# reason_code: spec §6 priority chain 每个 step 的稳定标识符
INTERVIEW_POLICY_REASON_MISSING_REQUIRED = "missing_required_before_draft"
INTERVIEW_POLICY_REASON_LOW_CONFIDENCE = "low_confidence_recheck"
INTERVIEW_POLICY_REASON_NEAR_LIMIT_METRIC = "near_limit_priority_result_metric"
INTERVIEW_POLICY_REASON_ANTI_REPEAT = "anti_repeat_switch_slot"
INTERVIEW_POLICY_REASON_NEXT_SLOT = "next_suggested_slot"
INTERVIEW_POLICY_REASON_FORCE_DRAFT_SKIP = "force_draft_skip_limit"
INTERVIEW_POLICY_REASON_FORCE_DRAFT_TURN = "force_draft_turn_limit"
INTERVIEW_POLICY_REASON_NO_GAP = "no_gap_selected"
INTERVIEW_POLICY_REASON_NO_MORE = "all_gap_slots_covered"

# R6-C.2B: gap-specific critical slot 追问优先级(reason_code 锁, 与 spec §6 兼容)
INTERVIEW_POLICY_REASON_GAP_CRITICAL_SLOT = "gap_critical_slot_priority"
"""R6-C.2B: gap 维度 critical slot 主动追问(reason_code)。

Rationale (R6-C.1 contract warning 报告 §4.5):
  - tech_metric 缺 `metric` (3 sample unreachable) + `method` 在 suggested position 3 (2 sample beyond_3)
  - communication 缺 `responsibility` (1 sample unreachable)
  改 GAP_SUGGESTED_SLOTS 会污染 LLM 抽取链路(suggested 是 LLM 抽取端的引导顺序,
  interview_prompts 设计常量, 不在 R6-C.2B 改动范围)。
  policy 通过 step 4.5 在三轮内主动追问 critical slot, 让 schema_pass_rate 在
  不修改 expected_slots 评测合同的前提下提升。
"""


# R6-C.2B: gap-specific critical slots 补足集合(R6-C.1 contract warning 触发的 policy 调整)
# 列表内顺序 = 追问优先级: 前面的 slot 先问, 后面的 slot 在前面 captured 后再问
INTERVIEW_POLICY_GAP_CRITICAL_SLOTS: dict[str, tuple[str, ...]] = {
    # tech_metric: 三轮内必须追问 metric(量化结果) + method(方法论)
    #   - metric: 不在 suggested 中(unreachable_expected_slot)
    #   - method: 在 suggested position 3 (beyond_three_turns_expected_slot)
    # priority: metric > method(metric 是合同中最难主动拿到的, 优先抢一轮)
    "tech_metric": ("metric", "method"),
    # communication: 三轮内必须追问 responsibility(角色/职责)
    #   - responsibility: 不在 suggested 中(unreachable_expected_slot)
    "communication": ("responsibility",),
}
"""R6-C.2B gap-specific critical slots 补足集合 — policy 内部维护, 弥补 GAP_SUGGESTED_SLOTS
未含的关键 slot, 让评测合同 expected_slots 在三轮内更可达。

deterministic 纯 dict lookup, 无网络 / 无 LLM / 无 env var。
不影响 GAP_SUGGESTED_SLOTS(那是 interview_prompts 的设计常量, 改它会污染 LLM 抽取链路)。

补足 vs GAP_SUGGESTED_SLOTS 的关系:
  - GAP_SUGGESTED_SLOTS 是"理想追问顺序"(由 gap 类型决定的语义优先级)
  - INTERVIEW_POLICY_GAP_CRITICAL_SLOTS 是"合同硬要求"(由评测合同 expected_slots 触发)
  - 两套配置正交, 在三轮内不会冲突(step 4.5 优先级低于 step 3 missing + step 4 low_conf,
    高于 step 5 near_limit + step 6 next_suggested)
"""

# next_question_kind 枚举(供 _build_question_plan 摘要 / 前端显示)
INTERVIEW_POLICY_KIND_ASK = "ask_slot"
INTERVIEW_POLICY_KIND_FORCE_DRAFT = "force_draft"
INTERVIEW_POLICY_KIND_NO_MORE = "no_more"


# ----------------------------------------------------------------------
# 辅助 — slot / confidence 处理
# ----------------------------------------------------------------------
def _slot_has_value(slot: str, captured: dict[str, Any]) -> bool:
    """判断 captured_slots[slot] 是否有有效值。

    行为对齐 interview_agent.can_draft 内的字符串/列表分支:
      - str: 非空 strip
      - list: 长度 > 0
    """
    v = captured.get(slot)
    if isinstance(v, str):
        return bool(v.strip())
    if isinstance(v, list):
        return len(v) > 0
    return False


def _latest_confidence(session: "InterviewSession", slot: str) -> float | None:
    """取 session.slot_meta[slot] 最后一条 entry 的 confidence(归一化)。

    边界:
      - session.slot_meta 不是 dict / slot 没条目 → None(没人答过)
      - 最后一条 confidence 不是 number(bool 拒绝) → None
      - confidence 在 [0.0, 1.0] → 返回 float; 范围外视为非法 None
    """
    entries = (session.slot_meta or {}).get(slot) or []
    if not isinstance(entries, list):
        return None
    for m in reversed(entries):
        if not isinstance(m, dict):
            continue
        c = m.get("confidence")
        if isinstance(c, bool):
            continue
        if isinstance(c, (int, float)):
            f = float(c)
            if 0.0 <= f <= 1.0:
                return f
            return None
        # 非 number 类型(字符串等) → 跳过这条, 找前一条
    return None


def _slot_is_low_confidence(
    session: "InterviewSession",
    slot: str,
    threshold: float = INTERVIEW_POLICY_LOW_CONFIDENCE,
) -> bool:
    """session.captured_slots[slot] 已有值 但 confidence < threshold → True。"""
    captured = session.captured_slots or {}
    if not _slot_has_value(slot, captured):
        return False
    latest = _latest_confidence(session, slot)
    if latest is None:
        # 没记录 confidence → 视为"未确认", 暂不进入 low_confidence 集合
        # (避免跟 rules fallback (0.40) 误关联)
        return False
    return latest < threshold


# ----------------------------------------------------------------------
# 辅助 — CAN_DRAFT_CONDITIONS / low_confidence / last_asked 查询
# ----------------------------------------------------------------------
def _already_can_draft(session: "InterviewSession") -> bool:
    """跟 interview_agent.can_draft 同样的最小复现(避免 import 循环)。

    边界: 任一 CAN_DRAFT_CONDITIONS combo 所有 slot 都满足 → True。
    """
    captured = session.captured_slots or {}
    for combo in CAN_DRAFT_CONDITIONS:
        ok = True
        for slot in combo:
            if not _slot_has_value(slot, captured):
                ok = False
                break
        if ok:
            return True
    return False


def _find_missing_required_slots(
    session: "InterviewSession",
) -> list[str]:
    """找任一 CAN_DRAFT_CONDITIONS combo 仍未满足的 slot 列表(差得最少的最优先)。

    返回: 缺失 slot 的有序 list(按 combo 内顺序); 若任一 combo 已完全满足 → []。

    策略:
      - 遍历所有 combo, 跳过已完全满足的(combo 可作为"已就绪"提交 draft, 不缺 slot)
      - 选"差得最少"的 combo 作为下一步追问的依据
      - 遇到缺口 = 1 立即返回(最优解)
    """
    captured = session.captured_slots or {}
    best: list[str] | None = None
    best_gap = None  # type: ignore[var-annotated]

    for combo in CAN_DRAFT_CONDITIONS:
        missing = [s for s in combo if not _slot_has_value(s, captured)]
        if not missing:
            return []  # 任一 combo 已就绪 → 不缺 slot
        gap = len(missing)
        if best is None or gap < best_gap:  # type: ignore[operator]
            best = missing
            best_gap = gap
            if gap == 1:
                break  # 最优解 — 1 个就 draft

    return best or []


def _find_low_confidence_slots(
    session: "InterviewSession",
    threshold: float = INTERVIEW_POLICY_LOW_CONFIDENCE,
) -> list[str]:
    """captured 但 confidence < threshold 的 slot 列表(按 SLOT_NAMES 顺序)。"""
    captured = session.captured_slots or {}
    out: list[str] = []
    for slot in SLOT_NAMES:
        if _slot_has_value(slot, captured) and _slot_is_low_confidence(
            session, slot, threshold=threshold,
        ):
            out.append(slot)
    return out


def _find_missing_critical_slots(session: "InterviewSession") -> list[str]:
    """R6-C.2B: 当前 gap 的 critical slot 集合中, 未 captured 的 slot 列表(按配置顺序)。

    返回:
      - selected_gap = None → []
      - gap_id 不在 INTERVIEW_POLICY_GAP_CRITICAL_SLOTS → []
      - 否则: 按 INTERVIEW_POLICY_GAP_CRITICAL_SLOTS[gap_id] 配置顺序,
              过滤掉 _slot_has_value(slot, captured) 已 captured 的 slot, 返回剩下的
    """
    gap = session.selected_gap
    if gap is None:
        return []
    critical = INTERVIEW_POLICY_GAP_CRITICAL_SLOTS.get(gap.gap_id, ())
    if not critical:
        return []
    captured = session.captured_slots or {}
    return [s for s in critical if not _slot_has_value(s, captured)]


def _get_last_asked_slot(session: "InterviewSession") -> str | None:
    """读 session.message_log[-1].slot(最近一条 kind="asked" entry)。

    session.message_log 是 list[dict]; 由 next_question() 写入
    `{"kind": "asked", "slot": str, "turn": int}` 形条目。
    rephrase_question 不写 message_log(只是同 slot 改写);
    switch_gap 清空 message_log(spec §6 "switch_gap 后清空或隔离旧的 question plan")。
    """
    log = session.message_log or []
    for entry in reversed(log):
        if not isinstance(entry, dict):
            continue
        if entry.get("kind") == "asked":
            slot = entry.get("slot")
            if isinstance(slot, str) and slot in SLOT_NAMES:
                return slot
    return None


def _last_asked_slot_confidence(
    session: "InterviewSession",
    slot: str | None,
) -> float | None:
    """最近被问的 slot 在 session.slot_meta 里的最新 confidence(若有)。

    注: 这是"用户对 last_slot 的最新回答的 confidence",
    不从 message_log entry 读(那只是 ask 时的 snapshot)。
    """
    if slot is None:
        return None
    return _latest_confidence(session, slot)


# ----------------------------------------------------------------------
# 辅助 — gap suggested_slots 内的选择
# ----------------------------------------------------------------------
def _next_suggested_slot(session: "InterviewSession") -> str | None:
    """按 gap.suggested_slots 顺序找第一个未 captured 的 slot。"""
    gap = session.selected_gap
    if gap is None:
        return None
    captured = session.captured_slots or {}
    for slot in gap.suggested_slots:
        if not _slot_has_value(slot, captured):
            return slot
    return None


def _near_limit_metric_slot(session: "InterviewSession") -> str | None:
    """turn_count >= MAX_TURNS_PER_GAP - 1 时, 找 suggested 里第一个未 captured 的 result/metric。

    spec §6 step 4: "接近轮数上限时 result/metric 优先"。
    """
    gap = session.selected_gap
    if gap is None:
        return None
    captured = session.captured_slots or {}
    for slot in ("metric", "result"):
        if slot in gap.suggested_slots and not _slot_has_value(slot, captured):
            return slot
    return None


def _pick_alternative_slot(
    session: "InterviewSession",
    *,
    exclude: str | None,
) -> str | None:
    """从 gap.suggested_slots 中找一个未 captured 的 slot(exclude 跳过)。"""
    gap = session.selected_gap
    if gap is None:
        return None
    captured = session.captured_slots or {}
    for slot in gap.suggested_slots:
        if slot == exclude:
            continue
        if not _slot_has_value(slot, captured):
            return slot
    return None


# ----------------------------------------------------------------------
# 辅助 — 输出构造
# ----------------------------------------------------------------------
def _make_empty_plan(
    reason_code: str,
    *,
    kind: str = INTERVIEW_POLICY_KIND_NO_MORE,
    session: "InterviewSession" | None = None,
) -> dict[str, Any]:
    """构造"无 slot 可问 / 强制 draft"的 plan dict。

    can_draft 字段语义:
      - kind=FORCE_DRAFT → True(强制 draft, 前端应允许)
      - kind=NO_MORE + session 提供 → 用 _already_can_draft(session)
        计算(避免 step 8 "所有 suggested captured" 时 can_draft 误报 False,
        让前端误以为还不能 draft)
      - kind=NO_MORE + session=None → False(保守默认)
    """
    if kind == INTERVIEW_POLICY_KIND_FORCE_DRAFT:
        can_draft = True
    elif session is not None:
        can_draft = _already_can_draft(session)
    else:
        can_draft = False
    return {
        "slot": "",
        "reason_code": reason_code,
        "kind": kind,
        "next_question_kind": kind,
        "can_draft": can_draft,
        "low_confidence_slots": [],
    }


def _make_ask_plan(
    slot: str,
    reason_code: str,
    *,
    session: "InterviewSession",
    low_confidence_slots: list[str] | None = None,
) -> dict[str, Any]:
    """构造"ask 一个 slot"的 plan dict。"""
    return {
        "slot": slot,
        "reason_code": reason_code,
        "kind": INTERVIEW_POLICY_KIND_ASK,
        "next_question_kind": INTERVIEW_POLICY_KIND_ASK,
        "can_draft": _already_can_draft(session),
        "low_confidence_slots": sorted(set(low_confidence_slots or [])),
    }


# ----------------------------------------------------------------------
# 公开 API
# ----------------------------------------------------------------------
def plan_next_question(session: "InterviewSession") -> dict[str, Any]:
    """R6-B Phase 3 deterministic next-question policy(spec §6)。

    优先级链(spec §6 "优先级" 5 条, 加 step 0/7 防边界, R6-C.2B 加 step 4.5):
      0. session.selected_gap 为空 / suggested_slots 空 → no_more(reason: no_gap_selected)
      1. skip_count >= MAX_CONSECUTIVE_SKIPS → force_draft(reason: force_draft_skip_limit)
      2. turn_count >= MAX_TURNS_PER_GAP → force_draft(reason: force_draft_turn_limit)
      3. 缺必要 slot(任一 CAN_DRAFT_CONDITIONS 未满) → ask 缺的那个
         reason: missing_required_before_draft
      4. 低置信度 slot(captured 但 confidence < 0.6) → ask 重新确认
         reason: low_confidence_recheck
      4.5. R6-C.2B gap-specific critical slot 优先级补足
         — 当前 gap 在 INTERVIEW_POLICY_GAP_CRITICAL_SLOTS 有配置, 且有未 captured 的 slot
         → ask 配置顺序的第一个未 captured critical slot
         reason: gap_critical_slot_priority
         (这条优先级介于 step 4 low_confidence 与 step 5 near_limit 之间 —
         低于 missing/low_conf(硬合规) 但高于 near_limit/suggested(合同软要求),
         因为 critical slot 是评测合同硬要求, 应该优先抢一轮)
      5. 接近轮数上限 + suggested 仍有 result/metric 未覆盖 → ask result/metric
         reason: near_limit_priority_result_metric
      6. 按 gap.suggested_slots 顺序 → ask 下一个未 captured 的 slot
         reason: next_suggested_slot
      7. anti-repeat(spec §6): 同 slot 不连续问两次, 除非上次 confidence < 0.4
         → 切去 suggested 里另一个未 captured 的 slot, reason: anti_repeat_switch_slot
         (若无 alternative → 仍问同一个 slot, reason 保留 next_suggested_slot)
      8. 全部 captured / 没有 empty slot → no_more
         reason: all_gap_slots_covered(can_draft = _already_can_draft)

    返回 schema(供 _build_question_plan 透传给 API response, 字段对齐 spec §5.3 + 扩展):
      {
        "slot": str,                              # 当前追问的 slot; "" = no_more / force_draft
        "reason_code": str,                       # 一个 INTERVIEW_POLICY_REASON_* 常量
        "kind": "ask_slot" | "force_draft" | "no_more",
        "next_question_kind": str,                # 跟 "kind" 同义, 保留 spec §6 字段名
        "can_draft": bool,                        # 当前 session 是否满足 CAN_DRAFT_CONDITIONS
        "low_confidence_slots": list[str],        # 当前 session 聚合的低置信度 slot
      }

    边界(AGENTS.md / spec §13):
      - 不调用网络 (no urllib / no requests / no httpx)
      - 不调用 LLM(不调任何 model API, 不读 LLM_API_KEY env)
      - 不 mutate session(纯只读: 输入 session 引用, 输出 dict)
      - LLM 不决定 slot 顺序(plan_next_question 是唯一决策者)
      - 返回 dict 不含 user_message / source_span / draft_card / API key / jd_text

    决策表完整示例(便于 review):
      | 状态                                              | plan                              |
      |--------------------------------------------------|-----------------------------------|
      | gap=None                                         | no_more / no_gap_selected         |
      | skip_count=2                                     | force_draft / force_draft_skip_limit |
      | turn_count=3                                     | force_draft / force_draft_turn_limit |
      | 缺 responsibility                                | ask responsibility / missing_required_before_draft |
      | action 已 captured, conf=0.4                     | ask action / low_confidence_recheck |
      | turn_count=2, suggested 仍有 metric               | ask metric / near_limit_priority_result_metric |
      | last_asked=action, captured 仍空, policy 想再问 action | ask other slot / anti_repeat_switch_slot |
      | 所有 gap.suggested_slots 都已 captured            | no_more / all_gap_slots_covered   |
    """
    gap = session.selected_gap
    if gap is None or not gap.suggested_slots:
        return _make_empty_plan(INTERVIEW_POLICY_REASON_NO_GAP)

    # 1. 连续 skip 触顶 — 用户已不能继续回答, 强推 draft
    if session.skip_count >= MAX_CONSECUTIVE_SKIPS:
        return _make_empty_plan(
            INTERVIEW_POLICY_REASON_FORCE_DRAFT_SKIP,
            kind=INTERVIEW_POLICY_KIND_FORCE_DRAFT,
        )

    # 2. 单缺口轮数触顶 — 同上, 让出 slot 给 draft
    if session.turn_count >= MAX_TURNS_PER_GAP:
        return _make_empty_plan(
            INTERVIEW_POLICY_REASON_FORCE_DRAFT_TURN,
            kind=INTERVIEW_POLICY_KIND_FORCE_DRAFT,
        )

    low_conf = _find_low_confidence_slots(session)

    # 3. 缺必要 slot(spec §6 step 1) — 最高追问你优先级
    missing = _find_missing_required_slots(session)
    if missing:
        slot = missing[0]
        return _make_ask_plan(
            slot,
            INTERVIEW_POLICY_REASON_MISSING_REQUIRED,
            session=session,
            low_confidence_slots=low_conf,
        )

    # 4. 低置信度 slot(spec §6 step 2)
    if low_conf:
        slot = low_conf[0]
        return _make_ask_plan(
            slot,
            INTERVIEW_POLICY_REASON_LOW_CONFIDENCE,
            session=session,
            low_confidence_slots=low_conf,
        )

    # 4.5. R6-C.2B gap-specific critical slot 补足(reason: gap_critical_slot_priority)
    #   - 配置在 INTERVIEW_POLICY_GAP_CRITICAL_SLOTS 的 slot 不一定在 gap.suggested_slots 内
    #   - 评测合同 expected_slots 要求这些 critical slot 三轮内可达
    #   - 优先级: 在 missing_required 和 low_confidence 之后(合规优先级),
    #     在 near_limit 和 next_suggested 之前(critical 是合同硬要求, 应优先抢一轮)
    critical = _find_missing_critical_slots(session)
    if critical:
        return _make_ask_plan(
            critical[0],
            INTERVIEW_POLICY_REASON_GAP_CRITICAL_SLOT,
            session=session,
            low_confidence_slots=low_conf,
        )

    # 5. 接近轮数上限 + suggested 仍 result/metric 未覆盖(spec §6 step 4)
    if session.turn_count >= MAX_TURNS_PER_GAP - 1:
        slot = _near_limit_metric_slot(session)
        if slot is not None:
            return _make_ask_plan(
                slot,
                INTERVIEW_POLICY_REASON_NEAR_LIMIT_METRIC,
                session=session,
                low_confidence_slots=low_conf,
            )

    # 6. 按 gap.suggested_slots 顺序找下一个未 captured
    next_slot = _next_suggested_slot(session)
    if next_slot is None:
        # 所有 gap.suggested_slots 都已 captured → no_more, 但要正确计算 can_draft
        # (任一 CAN_DRAFT_CONDITIONS 满足 → can_draft=True, 让前端知道可以 draft)
        return _make_empty_plan(
            INTERVIEW_POLICY_REASON_NO_MORE,
            kind=INTERVIEW_POLICY_KIND_NO_MORE,
            session=session,
        )

    # 7. anti-repeat(spec §6 "防重复"): 同 slot 不连续问两次, 除非上次 conf < 0.4
    last_slot = _get_last_asked_slot(session)
    if last_slot == next_slot:
        last_conf = _last_asked_slot_confidence(session, last_slot)
        if (
            last_conf is not None
            and last_conf >= INTERVIEW_POLICY_ANTI_REPEAT_CONFIDENCE
        ):
            alt = _pick_alternative_slot(session, exclude=last_slot)
            if alt is not None:
                return _make_ask_plan(
                    alt,
                    INTERVIEW_POLICY_REASON_ANTI_REPEAT,
                    session=session,
                    low_confidence_slots=low_conf,
                )
            # 无 alternative → 仍允许再问同一个 spec §6 step 3 (anti-repeat off)

    return _make_ask_plan(
        next_slot,
        INTERVIEW_POLICY_REASON_NEXT_SLOT,
        session=session,
        low_confidence_slots=low_conf,
    )
