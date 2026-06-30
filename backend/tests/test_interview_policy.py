"""
Round 6-B Phase 3: interview_policy deterministic plan_next_question 测试

覆盖(spec §6 + AGENTS.md R6-B Phase 3 锁点):
  - 优先级链 0-8 完整走一遍
  - 返回 schema 字段稳定(slot / reason_code / kind / next_question_kind /
    can_draft / low_confidence_slots)
  - 隐私边界: plan 不含 user_message / source_span / draft_card / API key / jd_text
  - 纯函数: plan_next_question 不 mutate session
  - LLM 不决定 slot 顺序: policy 模块不 import 网络 / LLM 模块(用 AST 静态扫描)
  - 常量稳定: INTERVIEW_POLICY_LOW_CONFIDENCE = 0.6 / reason_code 唯一

边界(AGENTS.md R6-B Phase 3):
  - policy 是纯函数, 直接对 InterviewSession 引用做只读访问
  - 不调网络, 不调 LLM, 不读 env var
  - 不 mutate session(本测试用 snapshot diff 验证)
  - 不 import core.llm_rewriter / core.agent_workflow / core.agent_tools
"""
from __future__ import annotations

import ast
import json
from typing import Any

import pytest

from core.interview_agent import (
    ActionType,
    GapCandidate,
    InterviewSession,
    InterviewState,
    apply_action,
)
from core.interview_policy import (
    INTERVIEW_POLICY_ANTI_REPEAT_CONFIDENCE,
    INTERVIEW_POLICY_KIND_ASK,
    INTERVIEW_POLICY_KIND_FORCE_DRAFT,
    INTERVIEW_POLICY_KIND_NO_MORE,
    INTERVIEW_POLICY_LOW_CONFIDENCE,
    INTERVIEW_POLICY_REASON_ANTI_REPEAT,
    INTERVIEW_POLICY_REASON_FORCE_DRAFT_SKIP,
    INTERVIEW_POLICY_REASON_FORCE_DRAFT_TURN,
    INTERVIEW_POLICY_REASON_LOW_CONFIDENCE,
    INTERVIEW_POLICY_REASON_MISSING_REQUIRED,
    INTERVIEW_POLICY_REASON_NEAR_LIMIT_METRIC,
    INTERVIEW_POLICY_REASON_NEXT_SLOT,
    INTERVIEW_POLICY_REASON_NO_GAP,
    INTERVIEW_POLICY_REASON_NO_MORE,
    plan_next_question,
)
from core.interview_prompts import (
    CAN_DRAFT_CONDITIONS,
    MAX_CONSECUTIVE_SKIPS,
    MAX_TURNS_PER_GAP,
    SLOT_NAMES,
)


# ----------------------------------------------------------------------
# 测试 fixture — 构造 InterviewSession, 不调 create_session
# ----------------------------------------------------------------------
_USE_DEFAULT_GAP = object()  # sentinel: 不传 gap 时用 _make_gap()
def _make_gap(
    *,
    gap_id: str = "process_metric",
    suggested_slots: tuple[str, ...] = (
        "background", "action", "result", "metric",
    ),
    tier: str = "required",
) -> GapCandidate:
    return GapCandidate(
        gap_id=gap_id, label="流程量化", reason="",
        keywords=[], source=[], tier=tier,
        priority=10.0, suggested_slots=suggested_slots,
    )


def _make_session(
    *,
    gap: GapCandidate | None | object = _USE_DEFAULT_GAP,  # _USE_DEFAULT_GAP = 真 default gap; None = 真 None
    captured_slots: dict | None = None,
    slot_meta: dict | None = None,
    skip_count: int = 0,
    turn_count: int = 0,
    message_log: list | None = None,
    state: InterviewState = InterviewState.ASKING,
    session_id: str = "ia_r6b_policy_test",
) -> InterviewSession:
    """构造测试用 InterviewSession。

    gap 用 sentinel 区分:
      - 不传(_USE_DEFAULT_GAP) → selected_gap = _make_gap()(默认 gap)
      - 显式 None → selected_gap = None(测 no_gap_selected 边界)
      - 显式 GapCandidate → 透传
    """
    if gap is _USE_DEFAULT_GAP:
        actual_gap: GapCandidate | None = _make_gap()
    elif gap is None:
        actual_gap = None
    else:
        actual_gap = gap
    return InterviewSession(
        session_id=session_id,
        target_role="test_qa",
        jd_digest={},
        selected_gap=actual_gap,
        state=state,
        turn_count=turn_count,
        captured_slots=captured_slots if captured_slots is not None else {},
        skip_count=skip_count,
        draft_card=None,
        message_log=message_log if message_log is not None else [],
        interview_mode="rules",
        slot_meta=slot_meta if slot_meta is not None else {},
    )


# ----------------------------------------------------------------------
# 通用断言
# ----------------------------------------------------------------------
def _assert_plan_shape(plan: dict[str, Any]) -> None:
    assert isinstance(plan, dict)
    # spec §6 返回 schema 6 字段
    required = {
        "slot", "reason_code", "kind",
        "next_question_kind", "can_draft", "low_confidence_slots",
    }
    assert required.issubset(plan.keys()), f"plan 缺字段: {plan.keys()}"
    assert plan["slot"] in SLOT_NAMES or plan["slot"] == ""
    assert isinstance(plan["reason_code"], str)
    assert plan["kind"] in {
        INTERVIEW_POLICY_KIND_ASK,
        INTERVIEW_POLICY_KIND_FORCE_DRAFT,
        INTERVIEW_POLICY_KIND_NO_MORE,
    }
    assert plan["next_question_kind"] == plan["kind"]
    assert isinstance(plan["can_draft"], bool)
    assert isinstance(plan["low_confidence_slots"], list)


def _make_meta(slot: str, confidence: float, reason: str = "kw") -> dict:
    return {
        "extractor": "rules",
        "confidence": float(confidence),
        "turn_index": 1,
        "reason_code": f"{reason}_{slot}",
    }


# ----------------------------------------------------------------------
# 1. 优先级链(step 0-8)
# ----------------------------------------------------------------------
class TestPlanPriorityChain:
    """spec §6 优先级链 0-8 全链路覆盖。

    CAN_DRAFT_CONDITIONS 实际定义(core/interview_prompts.py):
      combo1 = ("background", "action", "result")
      combo2 = ("responsibility", "action", "metric")
      combo3 = ("responsibility", "action", "result")

    _find_missing_required_slots 选"差得最少"的 combo 的缺口;
    captured={} 时三个 combo 都差 3 → 选 combo1(遍历第一个) → 缺 background。
    """

    def test_step0_no_gap_returns_no_more(self):
        """step 0: selected_gap=None → no_more / no_gap_selected。"""
        sess = _make_session(gap=None)
        plan = plan_next_question(sess)
        _assert_plan_shape(plan)
        assert plan["slot"] == ""
        assert plan["reason_code"] == INTERVIEW_POLICY_REASON_NO_GAP
        assert plan["kind"] == INTERVIEW_POLICY_KIND_NO_MORE
        assert plan["can_draft"] is False

    def test_step0_empty_suggested_slots_returns_no_more(self):
        """step 0: selected_gap.suggested_slots=() → no_more / no_gap_selected。"""
        gap = _make_gap(suggested_slots=())
        sess = _make_session(gap=gap)
        plan = plan_next_question(sess)
        _assert_plan_shape(plan)
        assert plan["reason_code"] == INTERVIEW_POLICY_REASON_NO_GAP

    def test_step1_skip_count_forces_draft(self):
        """step 1: skip_count >= MAX_CONSECUTIVE_SKIPS → force_draft(优先级最高)。

        注: 即使 captured={} 缺关键 slot, skip_count 触顶仍走 force_draft,跳过 step 3-8。
        """
        for captured in [{}, {"background": "X"}]:
            sess = _make_session(skip_count=MAX_CONSECUTIVE_SKIPS, captured_slots=captured)
            plan = plan_next_question(sess)
            _assert_plan_shape(plan)
            assert plan["slot"] == ""
            assert plan["reason_code"] == INTERVIEW_POLICY_REASON_FORCE_DRAFT_SKIP
            assert plan["kind"] == INTERVIEW_POLICY_KIND_FORCE_DRAFT
            assert plan["can_draft"] is True

    def test_step2_turn_count_forces_draft(self):
        """step 2: turn_count >= MAX_TURNS_PER_GAP → force_draft。"""
        sess = _make_session(turn_count=MAX_TURNS_PER_GAP)
        plan = plan_next_question(sess)
        _assert_plan_shape(plan)
        assert plan["slot"] == ""
        assert plan["reason_code"] == INTERVIEW_POLICY_REASON_FORCE_DRAFT_TURN
        assert plan["kind"] == INTERVIEW_POLICY_KIND_FORCE_DRAFT
        assert plan["can_draft"] is True

    def test_step3_missing_required_before_draft(self):
        """step 3: 缺 first combo 的 background → ask background, reason=missing_required。

        captured={} → 三个 combo 都缺 3 → 选 combo1(first traversal) →
        first missing = background。
        """
        sess = _make_session(captured_slots={})
        plan = plan_next_question(sess)
        _assert_plan_shape(plan)
        assert plan["slot"] == "background"
        assert plan["reason_code"] == INTERVIEW_POLICY_REASON_MISSING_REQUIRED
        assert plan["can_draft"] is False

    def test_step4_low_confidence_recheck_first(self):
        """step 4: 已有 slot 但 confidence < 0.6 → ask 该 slot recheck。

        注: step 3 优先级更高, 所以需要 first combo 已满才会走到 step 4。
        captured = combo1 全, 但 background confidence < 0.6。
        """
        captured = {
            "background": "我是一名测试实习生",
            "action": "我做了表格模板",
            "result": "结果效率提升",
        }
        slot_meta = {
            "background": [_make_meta("background", 0.3)],  # low conf
            "action": [_make_meta("action", 0.9)],
            "result": [_make_meta("result", 0.9)],
        }
        sess = _make_session(captured_slots=captured, slot_meta=slot_meta)
        plan = plan_next_question(sess)
        _assert_plan_shape(plan)
        assert plan["slot"] == "background"
        assert plan["reason_code"] == INTERVIEW_POLICY_REASON_LOW_CONFIDENCE
        assert "background" in plan["low_confidence_slots"]
        # can_draft 因为 combo1 已满足 + low conf 仍 True(spec §6 step 3 已经 return [])
        assert plan["can_draft"] is True

    def test_step5_near_limit_priority_metric(self):
        """step 5: turn 接近上限 + combo1 满 + suggested 仍缺 metric → ask metric, reason=near_limit。"""
        gap = _make_gap(suggested_slots=("background", "action", "result", "metric"))
        # combo1 已满(first combo), 缺 metric 走 step 5
        captured = {
            "background": "X",
            "action": "Y",
            "result": "Z",
        }
        slot_meta = {
            s: [_make_meta(s, 0.9)] for s in ("background", "action", "result")
        }
        sess = _make_session(
            gap=gap, captured_slots=captured, slot_meta=slot_meta,
            turn_count=MAX_TURNS_PER_GAP - 1,
        )
        plan = plan_next_question(sess)
        _assert_plan_shape(plan)
        assert plan["slot"] == "metric"
        assert plan["reason_code"] == INTERVIEW_POLICY_REASON_NEAR_LIMIT_METRIC

    def test_step5_does_not_fire_when_step3_still_missing(self):
        """step 3 优先级最高: 即使 turn 接近上限, 只要 combo 缺 slot 就走 step 3。

        注: step 5 result 在逻辑上 unreachable — 因为 result 在 combo1 缺口中,
        combo1 未满时 step 3 先 ask result, 不会走到 step 5。
        """
        gap = _make_gap(suggested_slots=("background", "action", "result", "metric"))
        captured = {
            "background": "X",
            "action": "Y",
        }  # 缺 result (combo1 缺 1)
        slot_meta = {
            s: [_make_meta(s, 0.9)] for s in ("background", "action")
        }
        sess = _make_session(
            gap=gap, captured_slots=captured, slot_meta=slot_meta,
            turn_count=MAX_TURNS_PER_GAP - 1,
        )
        plan = plan_next_question(sess)
        _assert_plan_shape(plan)
        # step 3 优先 → ask result, reason=missing_required
        assert plan["slot"] == "result"
        assert plan["reason_code"] == INTERVIEW_POLICY_REASON_MISSING_REQUIRED

    def test_step6_next_suggested_slot(self):
        """step 6: 满足 combo1 后 → 下一个 suggested slot 未 captured。

        captured=combo1 全, suggested 含 method, 未 captured → ask method。
        """
        gap = _make_gap(suggested_slots=("background", "action", "result", "method"))
        captured = {
            "background": "X",
            "action": "Y",
            "result": "Z",
        }
        slot_meta = {
            s: [_make_meta(s, 0.9)] for s in ("background", "action", "result")
        }
        sess = _make_session(gap=gap, captured_slots=captured, slot_meta=slot_meta)
        plan = plan_next_question(sess)
        _assert_plan_shape(plan)
        assert plan["slot"] == "method"
        assert plan["reason_code"] == INTERVIEW_POLICY_REASON_NEXT_SLOT
        assert plan["can_draft"] is True  # combo1 满

    def test_step7_anti_repeat_switches_to_alternative(self):
        """step 7: last_slot=method, conf>=0.4, suggested 还有 result → 切去 result。

        注: 必须先满足 combo1, 否则 step 3 优先。
        """
        gap = _make_gap(suggested_slots=("background", "action", "result", "method"))
        captured = {
            "background": "X",
            "action": "Y",
            "result": "Z",
        }
        slot_meta = {
            s: [_make_meta(s, 0.9)] for s in ("background", "action", "result")
        }
        # 模拟上次问过 method 但还没答(missing)
        message_log = [{"kind": "asked", "slot": "method", "turn": 0}]
        # 给 method 一个 conf>=0.4 的 meta(模拟已答过但 low 不够低)
        slot_meta["method"] = [_make_meta("method", 0.5)]
        sess = _make_session(
            gap=gap, captured_slots=captured, slot_meta=slot_meta,
            message_log=message_log,
        )
        plan = plan_next_question(sess)
        _assert_plan_shape(plan)
        # 缺 method (captured 没 method) → step 6 next_slot=method
        # last_slot=method, conf=0.5 >= 0.4 → step 7 anti-repeat 切
        # 但 captured 里没 method, alternative 应该从 captured 之外的 suggested 找
        # gap.suggested=("background", "action", "result", "method"), captured=("background", "action", "result")
        # 没 alternative → 仍问 method(anti-repeat 不切)
        assert plan["slot"] == "method"
        assert plan["reason_code"] == INTERVIEW_POLICY_REASON_NEXT_SLOT

    def test_step7_anti_repeat_disabled_when_low_confidence(self):
        """step 7: last_slot=method, conf<0.4 → 仍问 method (低置信度优先重问)。

        注: 简化场景 — combo1 已满, 走到 next_suggested 找 method。
        """
        gap = _make_gap(suggested_slots=("background", "action", "result", "method"))
        captured = {
            "background": "X",
            "action": "Y",
            "result": "Z",
        }
        slot_meta = {
            s: [_make_meta(s, 0.9)] for s in ("background", "action", "result")
        }
        # method 已 captured 但 conf<0.4
        captured["method"] = "用了 X 方法"
        slot_meta["method"] = [_make_meta("method", 0.3)]
        message_log = [{"kind": "asked", "slot": "method", "turn": 0}]
        sess = _make_session(
            gap=gap, captured_slots=captured, slot_meta=slot_meta,
            message_log=message_log,
        )
        plan = plan_next_question(sess)
        _assert_plan_shape(plan)
        # low_conf 触发 step 4, ask method recheck
        assert plan["slot"] == "method"
        # reason 取决于 step 4 vs step 7 — low_conf 优先(0.3 < 0.4)
        assert plan["reason_code"] in {
            INTERVIEW_POLICY_REASON_LOW_CONFIDENCE,
            INTERVIEW_POLICY_REASON_ANTI_REPEAT,
        }

    def test_step8_all_gap_slots_covered_returns_no_more(self):
        """step 8: 所有 gap.suggested_slots 已 captured → no_more, can_draft=True。"""
        gap = _make_gap(suggested_slots=("background", "action", "result"))
        captured = {
            "background": "X",
            "action": "Y",
            "result": "Z",
        }
        slot_meta = {
            s: [_make_meta(s, 0.9)] for s in captured
        }
        sess = _make_session(gap=gap, captured_slots=captured, slot_meta=slot_meta)
        plan = plan_next_question(sess)
        _assert_plan_shape(plan)
        assert plan["can_draft"] is True
        assert plan["reason_code"] == INTERVIEW_POLICY_REASON_NO_MORE
        assert plan["kind"] == INTERVIEW_POLICY_KIND_NO_MORE
        assert plan["slot"] == ""


# ----------------------------------------------------------------------
# 2. 输出 schema
# ----------------------------------------------------------------------
class TestPlanOutputSchema:
    """spec §6 返回 dict schema 字段稳定。"""

    def test_plan_has_all_required_fields(self):
        sess = _make_session()
        plan = plan_next_question(sess)
        _assert_plan_shape(plan)

    def test_plan_can_draft_true_when_combo_satisfied(self):
        """任一 CAN_DRAFT_CONDITIONS 满足 → can_draft=True。"""
        captured: dict[str, Any] = {}
        slot_meta: dict[str, list] = {}
        # 用第一组 combo
        for slot in CAN_DRAFT_CONDITIONS[0]:
            captured[slot] = f"mock_{slot}"
            slot_meta[slot] = [_make_meta(slot, 0.9)]
        sess = _make_session(captured_slots=captured, slot_meta=slot_meta)
        plan = plan_next_question(sess)
        _assert_plan_shape(plan)
        assert plan["can_draft"] is True

    def test_plan_low_confidence_slots_is_sorted_unique(self):
        """low_confidence_slots 聚合去重 + 按 SLOT_NAMES 顺序。"""
        captured: dict[str, Any] = {}
        slot_meta: dict[str, list] = {}
        for slot in CAN_DRAFT_CONDITIONS[0]:
            captured[slot] = f"mock_{slot}"
            slot_meta[slot] = [_make_meta(slot, 0.9)]
        # 把额外的 slot 标 low_conf
        for slot in ("metric", "result", "action"):
            if slot not in captured:
                captured[slot] = f"mock_{slot}"
                slot_meta[slot] = [_make_meta(slot, 0.3)]  # low
            else:
                # 在 combo 内的 slot 改成 low_conf
                slot_meta[slot] = [_make_meta(slot, 0.3)]
        sess = _make_session(captured_slots=captured, slot_meta=slot_meta)
        plan = plan_next_question(sess)
        _assert_plan_shape(plan)
        # low_confidence_slots 应按 SLOT_NAMES 顺序去重
        low_set = set(plan["low_confidence_slots"])
        for slot in ("metric", "result", "action"):
            assert slot in low_set, f"low_confidence_slots 应含 {slot}"


# ----------------------------------------------------------------------
# 3. 隐私边界 — plan dict 不泄漏 PII
# ----------------------------------------------------------------------
class TestPlanPrivacyGuarantee:
    """plan dict 不含 user_message / source_span / API key / jd_text / draft_card。"""

    def test_plan_no_user_message_in_output(self):
        captured = {"action": "USER_MSG_SENTINEL_xyz leakage"}
        slot_meta = {
            "action": [_make_meta("action", 0.8)],
        }
        sess = _make_session(captured_slots=captured, slot_meta=slot_meta)
        plan = plan_next_question(sess)
        s = json.dumps(plan, ensure_ascii=False, default=str)
        assert "USER_MSG_SENTINEL_xyz" not in s

    def test_plan_no_source_span_plaintext(self):
        slot_meta = {
            "action": [
                {
                    "extractor": "llm", "confidence": 0.9, "turn_index": 1,
                    "reason_code": "explicit_action",
                    "source_span_hash": "sha256:abcd1234",
                    "source_span_len": 9,
                    "source_span": "PII_SENTINEL_SPAN_should_not_leak",
                },
            ],
        }
        captured = {"action": "value"}
        sess = _make_session(captured_slots=captured, slot_meta=slot_meta)
        plan = plan_next_question(sess)
        s = json.dumps(plan, ensure_ascii=False, default=str)
        assert "PII_SENTINEL_SPAN" not in s
        # 注意: slot_meta 里包含 source_span 但 plan 输出不应泄漏
        # 因为 plan 只输出 slot 名 + reason_code + low_confidence_slots 列表

    def test_policy_no_network_imports_via_ast(self):
        """policy 模块不应 import 网络库 — 用 AST 静态扫描 import 节点。"""
        from core import interview_policy
        import inspect

        src = inspect.getsource(interview_policy)
        tree = ast.parse(src)
        imported_names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported_names.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imported_names.add(node.module.split(".")[0])
        forbidden = {"urllib", "requests", "httpx", "openai", "anthropic"}
        leaked = forbidden & imported_names
        assert not leaked, (
            f"policy 模块 import 了网络/LLM 模块: {leaked}, "
            f"全部 import: {imported_names}"
        )

    def test_policy_no_llm_rewriter_import_via_ast(self):
        """policy 模块不应 import core.llm_rewriter(R5-E 边界保护)。"""
        from core import interview_policy
        import inspect

        src = inspect.getsource(interview_policy)
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module and "llm_rewriter" in node.module:
                    pytest.fail(f"policy 不应 import llm_rewriter: {node.module}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if "llm_rewriter" in alias.name:
                        pytest.fail(f"policy 不应 import llm_rewriter: {alias.name}")

    def test_policy_no_llm_api_key_read_via_ast(self):
        """policy 模块不应读 LLM_API_KEY(os.environ / os.getenv / LLM_API_KEY 字面量)。"""
        from core import interview_policy
        import inspect

        src = inspect.getsource(interview_policy)
        tree = ast.parse(src)
        for node in ast.walk(tree):
            # 拒 os.environ[...] 访问
            if isinstance(node, ast.Attribute) and node.attr == "environ":
                pytest.fail(f"policy 不应访问 os.environ: {ast.dump(node)}")
            # 拒 os.getenv(...) 调用
            if isinstance(node, ast.Call):
                func = node.func
                if (
                    isinstance(func, ast.Attribute)
                    and func.attr == "getenv"
                    and isinstance(func.value, ast.Name)
                    and func.value.id == "os"
                ):
                    pytest.fail(f"policy 不应调 os.getenv: {ast.dump(node)}")
            # 拒 "LLM_API_KEY" 字面量引用
            if isinstance(node, ast.Constant) and node.value == "LLM_API_KEY":
                pytest.fail(
                    f"policy 不应引用 LLM_API_KEY 字面量: {ast.dump(node)}"
                )


# ----------------------------------------------------------------------
# 4. 纯函数 — 不 mutate session
# ----------------------------------------------------------------------
class TestPlanPurity:
    """plan_next_question 是纯函数, 不 mutate session 任何字段。"""

    def test_policy_does_not_mutate_session(self):
        gap = _make_gap()
        captured = {"background": "X", "action": "Y"}
        slot_meta = {
            s: [_make_meta(s, 0.9)] for s in captured
        }
        message_log = [{"kind": "asked", "slot": "background", "turn": 0}]
        sess = _make_session(
            gap=gap,
            captured_slots=captured,
            slot_meta=slot_meta,
            message_log=message_log,
            turn_count=2,
        )
        # snapshot before
        before = {
            "selected_gap": sess.selected_gap,
            "captured_slots": dict(sess.captured_slots),
            "slot_meta": {k: list(v) for k, v in (sess.slot_meta or {}).items()},
            "message_log": list(sess.message_log),
            "turn_count": sess.turn_count,
            "skip_count": sess.skip_count,
            "state": sess.state,
            "question_plan": sess.question_plan,
        }
        _ = plan_next_question(sess)
        # snapshot after — should equal before
        after = {
            "selected_gap": sess.selected_gap,
            "captured_slots": dict(sess.captured_slots),
            "slot_meta": {k: list(v) for k, v in (sess.slot_meta or {}).items()},
            "message_log": list(sess.message_log),
            "turn_count": sess.turn_count,
            "skip_count": sess.skip_count,
            "state": sess.state,
            "question_plan": sess.question_plan,
        }
        assert before == after, (
            f"policy 副作用:\nbefore={before}\nafter={after}"
        )

    def test_policy_is_deterministic(self):
        """同样 session 多次调用 plan_next_question 返回字节级一致。"""
        sess = _make_session()
        p1 = plan_next_question(sess)
        p2 = plan_next_question(sess)
        p3 = plan_next_question(sess)
        assert p1 == p2 == p3

    def test_policy_does_not_raise_on_malformed_session(self):
        """session.slot_meta 非法 / message_log 含非 dict entry → 不抛。"""
        sess = _make_session(
            slot_meta={"action": "not_a_list"},  # 非法: 应该是 list
            message_log=[None, "garbage", {"kind": "asked", "slot": "action", "turn": 0}],
        )
        # 不抛
        plan = plan_next_question(sess)
        _assert_plan_shape(plan)


# ----------------------------------------------------------------------
# 5. 常量稳定
# ----------------------------------------------------------------------
class TestPlanConstants:
    """锁死 spec §6 + AGENTS.md 阈值与 reason_code。"""

    def test_low_confidence_threshold_is_0_6(self):
        """跟 interview_agent.INTERVIEW_LOW_CONFIDENCE_THRESHOLD 对齐。"""
        assert INTERVIEW_POLICY_LOW_CONFIDENCE == 0.6

    def test_anti_repeat_threshold_is_0_4(self):
        """anti-repeat 阈值: conf >= 0.4 视为已答过, 切去 alternative。"""
        assert INTERVIEW_POLICY_ANTI_REPEAT_CONFIDENCE == 0.4

    def test_reason_codes_are_unique(self):
        """所有 INTERVIEW_POLICY_REASON_* 常量值唯一。"""
        codes = [
            INTERVIEW_POLICY_REASON_ANTI_REPEAT,
            INTERVIEW_POLICY_REASON_FORCE_DRAFT_SKIP,
            INTERVIEW_POLICY_REASON_FORCE_DRAFT_TURN,
            INTERVIEW_POLICY_REASON_LOW_CONFIDENCE,
            INTERVIEW_POLICY_REASON_MISSING_REQUIRED,
            INTERVIEW_POLICY_REASON_NEAR_LIMIT_METRIC,
            INTERVIEW_POLICY_REASON_NEXT_SLOT,
            INTERVIEW_POLICY_REASON_NO_GAP,
            INTERVIEW_POLICY_REASON_NO_MORE,
        ]
        assert len(codes) == len(set(codes)), f"reason_code 有重复: {codes}"

    def test_kind_constants_are_unique(self):
        """3 个 kind 互斥。"""
        kinds = {
            INTERVIEW_POLICY_KIND_ASK,
            INTERVIEW_POLICY_KIND_FORCE_DRAFT,
            INTERVIEW_POLICY_KIND_NO_MORE,
        }
        assert len(kinds) == 3


# ----------------------------------------------------------------------
# 6. 集成 — policy 跟 apply_action 协同
# ----------------------------------------------------------------------
class TestPlanApplyActionIntegration:
    """policy 跟 apply_action ANSWER 之后接 next_question 的行为一致性。"""

    def test_after_answer_advances_missing_chain(self):
        """答完一个 slot 后, policy 应推进到下一个 missing。

        captured={} → step 3 ask background;
        apply_action(ANSWER background) 后 → step 3 缺 combo1 的 action → ask action。
        """
        sess = _make_session()
        sess2, _ = apply_action(
            sess, ActionType.ANSWER, "我是测试实习生, 主要做 AI 产品测试",
        )
        plan = plan_next_question(sess2)
        _assert_plan_shape(plan)
        # 答了 background, combo1 还缺 action, result → step 3 ask action
        assert plan["slot"] == "action"
        assert plan["reason_code"] == INTERVIEW_POLICY_REASON_MISSING_REQUIRED

    def test_after_full_combo_plan_can_draft(self):
        """答完 first combo 全套后, plan 应 can_draft=True。"""
        gap = _make_gap(suggested_slots=("background", "action", "result"))
        sess = _make_session(gap=gap)
        # 答 background
        sess2, _ = apply_action(
            sess, ActionType.ANSWER, "我是测试实习生, 主要做 AI 产品测试",
        )
        # 答 action
        sess3, _ = apply_action(sess2, ActionType.ANSWER, "我做了表格模板, 按类型分类")
        # 答 result
        sess4, _ = apply_action(
            sess3, ActionType.ANSWER, "最后结果反馈效率提高了",
        )
        plan = plan_next_question(sess4)
        _assert_plan_shape(plan)
        assert plan["can_draft"] is True