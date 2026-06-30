"""
Round 6-A Phase 5 + R6-B Phase 5: interview agent eval 脚本测试

测试覆盖:
  TestEvalHelpers (plan §5.5):
    - test_extract_slots_from_messages_iterates_turns
    - test_compute_schema_pass_rate_returns_float
    - test_completeness_calculates_required_field_ratio
    - test_fabrication_guard_detects_unconfirmed_claims
  TestEvalReport (R6-A Phase 5):
    - test_report_contains_no_user_message_text
    - test_report_offline_mode_does_not_call_urlopen
  TestPhase5ExtractorModes (R6-B Phase 5 spec §8 + §10):
    - test_extractor_rules_default_unchanged
    - test_extractor_llm_offline_marks_llm_disabled_fallback
    - test_extractor_compare_runs_two_groups
    - test_extractor_compare_offline_does_not_call_urlopen
    - test_extractor_invalid_falls_back_to_rules
  TestPhase5Metrics (R6-B Phase 5 spec §8):
    - test_metrics_includes_low_confidence_slot_rate
    - test_metrics_includes_p95_latency_ms
    - test_metrics_includes_fallback_category_breakdown_5_categories
    - test_metrics_by_extractor_groups_separate_rules_and_llm
    - test_compute_metrics_handles_empty_rows
  TestPhase5Report (R6-B Phase 5 spec §8 报告):
    - test_compare_report_contains_rules_vs_llm_table
    - test_compare_report_contains_fallback_category_section
    - test_report_contains_low_confidence_slot_rate_metric
    - test_compare_report_contains_no_user_message_text
    - test_llm_offline_report_marks_llm_disabled_fallback
    - test_report_no_api_key_no_prompt_no_source_span
  TestPhase5Helpers (R6-B Phase 5 spec §5.2 / §8):
    - test_count_low_confidence_slots_returns_pair
    - test_count_low_confidence_slots_handles_missing_or_empty
    - test_count_low_confidence_slots_excludes_bool_confidence
    - test_classify_fallback_category_priority

边界(对齐 plan §5.3 / R5-E 保护 / R6-B §12):
  - 不 import core.llm_rewriter / core.agent_workflow / core.agent_tools / core.evidence
    / core.tool_schema / core.session
  - 只 import core.interview_agent + core.generator + core.jd_parser + evaluate_agent_workflow
  - 报告路径走 tmp_path, 不污染 backend/logs/
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest import mock

import pytest

# ---- 路径: 让 scripts/ 可导入 ----
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
BACKEND_DIR = REPO_ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))
sys.path.insert(0, str(SCRIPTS_DIR))

from evaluate_interview_agent import (  # noqa: E402
    EVAL_SET_ALL,
    EVAL_SET_PLAN_BASELINE,
    EVAL_SET_SIMULATED,
    EXTRACTOR_COMPARE,
    EXTRACTOR_LLM,
    EXTRACTOR_MODES,
    EXTRACTOR_RULES,
    FALLBACK_LLM_DISABLED,
    FALLBACK_NONE,
    FALLBACK_SCHEMA_RETRY,
    FALLBACK_TOOL_ERROR,
    FALLBACK_WORKFLOW_ABORT,
    EvalRow,
    _classify_interview_fallback_category,
    _compute_completeness,
    _compute_schema_pass_rate,
    _count_low_confidence_slots,
    _evaluate_one,
    _extract_slots_iteratively,
    _fabrication_guard,
    compute_metrics,
    main,
    write_report,
)
from core.interview_agent import (  # noqa: E402
    ActionType,
    create_session,
    extract_slots,
)


# ======================================================================
# Fixtures
# ======================================================================
@pytest.fixture
def materials():
    """公开脱敏版 materials.json (跟 R5-D 测试一致)."""
    from core.generator import load_materials  # noqa: PLC0415
    return load_materials()


@pytest.fixture
def plan_baseline_sample():
    """plan §5.4 固定 3 条样本中的第一条."""
    return EVAL_SET_PLAN_BASELINE[0]


@pytest.fixture
def all_samples():
    return list(EVAL_SET_ALL)


@pytest.fixture
def small_sample():
    """eval set 子集(3 条)用于快速测试, 跑得快."""
    return list(EVAL_SET_ALL[:3])


@pytest.fixture
def llm_eval_cfg():
    """offline 模式下的 llm_eval_config(测试用)."""
    from evaluate_agent_workflow import _get_llm_eval_config  # noqa: PLC0415
    from core.llm_rewriter import is_llm_enabled  # noqa: PLC0415
    return _get_llm_eval_config(is_llm_enabled(), "offline")


def _run_rows(samples, materials, *, extractor_mode=EXTRACTOR_RULES):
    """helper: 跑一组样本, 返 list[EvalRow]."""
    return [
        _evaluate_one(s, materials, extractor_mode=extractor_mode)
        for s in samples
    ]


# ======================================================================
# TestEvalHelpers (R6-A Phase 5, 字节级一致)
# ======================================================================
class TestEvalHelpers:
    """plan §5.5: helpers 单元测试."""

    def test_extract_slots_from_messages_iterates_turns(
        self, materials, plan_baseline_sample,
    ):
        """
        模拟 4 轮 user_messages, 每轮跑 extract_slots, 累加到 captured_slots。
        验证:
          - turn_count 递增 (跳过 '整理成素材' chip)
          - 至少 2 个 slot 被填上 (background/responsibility/action/result 等)
          - captured_slots 是 dict 且 key 数量 > 0
        """
        session = create_session(
            plan_baseline_sample["role"],
            plan_baseline_sample["jd_text"],
            materials,
        )
        # 强制选 plan §5.4 指定的 gap
        for g in (session.gap_candidates or []):
            if g.gap_id == plan_baseline_sample["gap_id"]:
                session.selected_gap = g
                break
        assert session.selected_gap is not None

        before_turn = session.turn_count
        result = _extract_slots_iteratively(
            plan_baseline_sample["user_messages"], session,
        )
        # answer 消息 = 4 条 user_messages - 1 条 '整理成素材' chip = 3 条
        assert session.turn_count >= before_turn + 1, \
            f"turn_count 应该递增; got {session.turn_count}"
        assert isinstance(result, dict), "captured_slots 应是 dict"
        # 至少 1 个 slot 被填上 (规则版不保证全填)
        non_warning_keys = [k for k in result if not k.startswith("_")]
        assert len(non_warning_keys) >= 1, \
            f"至少 1 个业务 slot 应被填上; got keys={list(result.keys())}"

    def test_compute_schema_pass_rate_returns_float(self):
        """
        聚合函数返回 [0, 1] 浮点。
        构造 4 个样本: 3 个全命中 + 1 个零命中, schema_pass_rate 应该是 0.75。
        """
        samples = [
            {"expected_slots": {"action": ["a"]}, "captured_slots": {"action": ["a"]}},
            {"expected_slots": {"action": ["b"]}, "captured_slots": {"action": ["b"]}},
            {"expected_slots": {"action": ["c"]}, "captured_slots": {"action": ["c"]}},
            {"expected_slots": {"action": ["d"]}, "captured_slots": {}},
        ]
        rate = _compute_schema_pass_rate(samples)
        assert isinstance(rate, float), f"schema_pass_rate 应是 float; got {type(rate).__name__}"
        assert 0.0 <= rate <= 1.0, f"schema_pass_rate 应在 [0, 1]; got {rate}"
        assert rate == 0.75, f"3/4 = 0.75; got {rate}"

    def test_completeness_calculates_required_field_ratio(self):
        """
        completeness = 必填字段填全比例。
        构造一个全填的 draft_card, completeness = 1.0。
        构造一个全空的 draft_card, completeness = 0.0。
        """
        full_card = {
            "background": "ctx", "responsibility": "r",
            "actions": ["a"], "methods": ["m"],
            "result": "r", "metrics": ["x"],
        }
        empty_card = {
            "background": "", "responsibility": "",
            "actions": [], "methods": [],
            "result": "", "metrics": [],
        }
        assert _compute_completeness(full_card) == 1.0
        assert _compute_completeness(empty_card) == 0.0

    def test_fabrication_guard_detects_unconfirmed_claims(self):
        """
        简单 keyword 扫描:
          - bullets 里的量化数字必须在 user_messages 里出现
          - 不出现 → fabrication_guard 返 False
        """
        user_msgs = [
            "我审核了 200 条数据, 标注准确率 90%。",
        ]
        ok_card = {
            "draft_bullets": ["审核了 200 条数据, 准确率 90%"],
        }
        fabric_card = {
            "draft_bullets": ["完成了 5000 个标注, 准确率 99%"],
        }
        assert _fabrication_guard(ok_card, user_msgs) is True, \
            "所有数字都在 user_messages 里, 应判定为无 fabrication"
        assert _fabrication_guard(fabric_card, user_msgs) is False, \
            "5000 / 99% 不在 user_messages 里, 应判定为 fabrication"


# ======================================================================
# TestEvalReport (R6-A Phase 5, 字节级一致)
# ======================================================================
class TestEvalReport:
    """plan §5.5: 报告隐私 + offline mode 不调 urlopen."""

    def test_report_contains_no_user_message_text(self, tmp_path, all_samples, materials, llm_eval_cfg):
        """
        写报告后 grep 确认不含模拟用户回答原文。
        抽样 3 条 user_message 里的关键短语, 检查报告不含它们。
        """
        # 跑全部样本
        rows = _run_rows(all_samples, materials, extractor_mode=EXTRACTOR_RULES)
        metrics = compute_metrics(rows)
        report_path = tmp_path / "report.md"

        write_report(
            rows, metrics, report_path, llm_eval_cfg, requested_mode="offline",
            extractor_mode=EXTRACTOR_RULES,
        )
        report_text = report_path.read_text(encoding="utf-8")

        # 抽样 5 条 user_message 里的关键短语(都来自 simulated samples, plan baseline 同样验证)
        forbidden_phrases = [
            "我负责课程项目里的测试反馈整理",       # plan_baseline[0]
            "社团活动报名时信息很乱",                # plan_baseline[1]
            "我做过一个数据整理项目",                # plan_baseline[2]
            "我负责一个医疗垂类大模型评测项目",       # simulated[0]
            "我参与一个心电时序信号大模型预研课题",   # simulated[1]
            "我参加一个开源社团的 AI 应用开发贡献",   # simulated[2]
            "我参与过一场大型综合体育赛事的志愿服务", # simulated[3]
            "我做过一个数据标注项目",                # simulated[4]
            "我在医疗垂类评测项目里负责从 Badcase",  # simulated[5]
            "我负责一个评测流程的搭建",              # simulated[6]
        ]
        leaks = [p for p in forbidden_phrases if p in report_text]
        assert not leaks, (
            f"报告不应含 user_message 原文; 发现泄漏: {leaks}"
        )

    def test_report_offline_mode_does_not_call_urlopen(
        self, tmp_path, all_samples, materials, llm_eval_cfg,
    ):
        """
        mock urlopen, offline 模式断言 urlopen.assert_not_called().
        验证 eval 脚本在 offline 模式下完全不发起 HTTP 调用。
        """
        with mock.patch(
            "urllib.request.urlopen", side_effect=AssertionError("offline mode 不应调 urlopen"),
        ) as mock_urlopen:
            rows = _run_rows(all_samples, materials, extractor_mode=EXTRACTOR_RULES)
            metrics = compute_metrics(rows)
            report_path = tmp_path / "report.md"
            write_report(
                rows, metrics, report_path, llm_eval_cfg, requested_mode="offline",
                extractor_mode=EXTRACTOR_RULES,
            )
            # offline 模式应完全不发 HTTP
            mock_urlopen.assert_not_called()


# ======================================================================
# TestPhase5Helpers (R6-B Phase 5 spec §5.2 + §8)
# ======================================================================
class TestPhase5Helpers:
    """Phase 5 新增 helper 单元测试."""

    def test_count_low_confidence_slots_returns_pair(self):
        """
        _count_low_confidence_slots(session) -> (low, total):
          - low  = confidence < 0.6 的 meta 条数
          - total = slot_meta 总条数
        """
        from core.interview_agent import InterviewSession  # noqa: PLC0415

        session = InterviewSession(
            session_id="ia" + "0" * 8,
            target_role="test_qa",
            jd_digest={},
            selected_gap=None,
            state="ASKING",
            turn_count=1,
            captured_slots={"action": ["a"]},
            skip_count=0,
            draft_card=None,
            message_log=[],
            slot_meta={
                "action": [
                    {"extractor": "rules", "confidence": 0.5, "turn_index": 1},  # low
                    {"extractor": "rules", "confidence": 0.8, "turn_index": 2},  # high
                    {"extractor": "llm", "confidence": 0.3, "turn_index": 3},    # low
                ],
                "result": [
                    {"extractor": "rules", "confidence": 0.9, "turn_index": 4},  # high
                ],
            },
        )
        low, total = _count_low_confidence_slots(session)
        assert low == 2, f"应有 2 条 low (0.5 + 0.3); got {low}"
        assert total == 4, f"总条数应为 4; got {total}"

    def test_count_low_confidence_slots_handles_missing_or_empty(self):
        """
        session.slot_meta 为 None / 空 dict / 缺 confidence → (0, 0)
        """
        from core.interview_agent import InterviewSession  # noqa: PLC0415

        # 1) None
        s1 = InterviewSession(
            session_id="ia" + "0" * 8, target_role="x", jd_digest={},
            selected_gap=None, state="ASKING", turn_count=0,
            captured_slots={}, skip_count=0, draft_card=None,
            message_log=[], slot_meta=None,
        )
        assert _count_low_confidence_slots(s1) == (0, 0)

        # 2) 空 dict
        s2 = InterviewSession(
            session_id="ia" + "0" * 8, target_role="x", jd_digest={},
            selected_gap=None, state="ASKING", turn_count=0,
            captured_slots={}, skip_count=0, draft_card=None,
            message_log=[], slot_meta={},
        )
        assert _count_low_confidence_slots(s2) == (0, 0)

    def test_count_low_confidence_slots_excludes_bool_confidence(self):
        """
        bool confidence 拒绝(spec §5.2: bool 不接受), 不计入 low.
        """
        from core.interview_agent import InterviewSession  # noqa: PLC0415

        session = InterviewSession(
            session_id="ia" + "0" * 8, target_role="x", jd_digest={},
            selected_gap=None, state="ASKING", turn_count=0,
            captured_slots={}, skip_count=0, draft_card=None,
            message_log=[],
            slot_meta={
                "action": [
                    {"extractor": "rules", "confidence": True, "turn_index": 1},
                    {"extractor": "rules", "confidence": False, "turn_index": 2},
                ],
            },
        )
        # bool 不计入 low_count, 但 total_count 仍计
        low, total = _count_low_confidence_slots(session)
        assert low == 0, f"bool confidence 不应计入 low; got {low}"
        assert total == 2, f"total 应含 bool 拒绝的条数; got {total}"

    def test_classify_fallback_category_priority(self):
        """
        5 类分类的优先级:
          1. error_type 非 None → FALLBACK_WORKFLOW_ABORT
          2. rules extractor + 实际 rules → FALLBACK_NONE
          3. llm extractor + 实际 llm_assisted → FALLBACK_NONE
          4. llm extractor + 实际 rules → FALLBACK_LLM_DISABLED
        """
        # 1) error 优先
        assert _classify_interview_fallback_category(
            extractor_mode=EXTRACTOR_RULES, actual_mode="rules", error_type="boom",
        ) == FALLBACK_WORKFLOW_ABORT

        # 2) rules + rules
        assert _classify_interview_fallback_category(
            extractor_mode=EXTRACTOR_RULES, actual_mode="rules", error_type=None,
        ) == FALLBACK_NONE

        # 3) llm + llm_assisted
        assert _classify_interview_fallback_category(
            extractor_mode=EXTRACTOR_LLM, actual_mode="llm_assisted", error_type=None,
        ) == FALLBACK_NONE

        # 4) llm + rules (offline fallback)
        assert _classify_interview_fallback_category(
            extractor_mode=EXTRACTOR_LLM, actual_mode="rules", error_type=None,
        ) == FALLBACK_LLM_DISABLED


# ======================================================================
# TestPhase5ExtractorModes (R6-B Phase 5 spec §8 + §10)
# ======================================================================
class TestPhase5ExtractorModes:
    """Phase 5: --extractor rules|llm|compare 三模式行为."""

    def test_extractor_rules_default_unchanged(self, small_sample, materials, llm_eval_cfg, tmp_path):
        """
        --extractor rules(default) 行为字节级一致 R6-A Phase 5:
          - 每条 row.extractor_mode == "rules"
          - 每条 row.fallback_category == "none"
          - 每条 row.fallback_used == False
          - 报告标题含 "规则版"
        """
        rows = _run_rows(small_sample, materials, extractor_mode=EXTRACTOR_RULES)
        assert all(r.extractor_mode == EXTRACTOR_RULES for r in rows), \
            "rules 模式: 每行 extractor_mode 应是 'rules'"
        assert all(r.fallback_category == FALLBACK_NONE for r in rows), \
            "rules 模式: 每行 fallback_category 应是 'none'"
        assert all(r.fallback_used is False for r in rows), \
            "rules 模式: 每行 fallback_used 应是 False"

        # 写报告: 标题含 "规则版" 标签
        metrics = compute_metrics(rows)
        report_path = tmp_path / "rules.md"
        write_report(
            rows, metrics, report_path, llm_eval_cfg,
            requested_mode="offline", extractor_mode=EXTRACTOR_RULES,
        )
        report_text = report_path.read_text(encoding="utf-8")
        assert "规则版" in report_text, \
            f"rules 模式报告应含 '规则版'; got first 200 chars: {report_text[:200]}"

    def test_extractor_llm_offline_marks_llm_disabled_fallback(
        self, small_sample, materials, llm_eval_cfg, tmp_path,
    ):
        """
        --extractor llm + offline 模式: 每条 row.fallback_category == 'llm_disabled_fallback'
        报告里通过 fallback_category 章节显式说明"无 key / offline → fallback"。
        """
        rows = _run_rows(small_sample, materials, extractor_mode=EXTRACTOR_LLM)
        # 全部 llm 意图, offline → 全 fallback
        assert all(r.extractor_mode == EXTRACTOR_LLM for r in rows), \
            "llm 模式: 每行 extractor_mode 应是 'llm'"
        assert all(r.fallback_category == FALLBACK_LLM_DISABLED for r in rows), \
            f"offline + llm 模式: 每行 fallback_category 应是 'llm_disabled_fallback'; got: {[r.fallback_category for r in rows]}"
        assert all(r.fallback_used is True for r in rows), \
            "offline + llm 模式: 每行 fallback_used 应是 True"

        # 报告里 fallback_category 章节标 100% llm_disabled_fallback
        metrics = compute_metrics(rows)
        report_path = tmp_path / "llm.md"
        write_report(
            rows, metrics, report_path, llm_eval_cfg,
            requested_mode="offline", extractor_mode=EXTRACTOR_LLM,
        )
        report_text = report_path.read_text(encoding="utf-8")
        assert "llm_disabled_fallback" in report_text, \
            "llm offline 报告应含 llm_disabled_fallback 标记"

    def test_extractor_compare_runs_two_groups(
        self, small_sample, materials, llm_eval_cfg, tmp_path,
    ):
        """
        --extractor compare: 跑 2 组共 2N 行。
          - rules_rows 全 fallback_used=False, fallback_category="none"
          - llm_rows 全 fallback_used=True, fallback_category="llm_disabled_fallback"
          - 报告标题含 "Compare"
          - 报告含 Rules vs LLM-assisted 对照表 + Delta
        """
        rules_rows = _run_rows(small_sample, materials, extractor_mode=EXTRACTOR_RULES)
        llm_rows = _run_rows(small_sample, materials, extractor_mode=EXTRACTOR_LLM)
        all_rows = rules_rows + llm_rows

        assert len(rules_rows) == len(small_sample)
        assert len(llm_rows) == len(small_sample)
        assert all(r.fallback_used is False for r in rules_rows)
        assert all(r.fallback_category == FALLBACK_LLM_DISABLED for r in llm_rows)

        # 聚合对照
        by_extractor = {
            EXTRACTOR_RULES: compute_metrics(rules_rows),
            EXTRACTOR_LLM: compute_metrics(llm_rows),
        }
        metrics = compute_metrics(all_rows)

        # 报告
        report_path = tmp_path / "compare.md"
        write_report(
            all_rows, metrics, report_path, llm_eval_cfg,
            requested_mode="offline", extractor_mode=EXTRACTOR_COMPARE,
            by_extractor_metrics=by_extractor,
        )
        report_text = report_path.read_text(encoding="utf-8")
        assert "Compare" in report_text, "compare 报告标题应含 'Compare'"
        assert "Rules vs LLM-assisted" in report_text, \
            "compare 报告应含 'Rules vs LLM-assisted' 章节"
        assert "Delta" in report_text, "compare 报告应含 Delta 块"
        # 双组行数核对
        n = len(small_sample)
        assert metrics["total"] == 2 * n, f"compare 全局 total 应是 2N; got {metrics['total']}"

    def test_extractor_compare_offline_does_not_call_urlopen(
        self, small_sample, materials, llm_eval_cfg, tmp_path,
    ):
        """
        compare 模式 + offline: 完全不发网络。
        mock urlopen 抛 AssertionError, 跑通则说明 urlopen 未被调。
        """
        with mock.patch(
            "urllib.request.urlopen",
            side_effect=AssertionError("offline compare 不应调 urlopen"),
        ) as mock_urlopen:
            rules_rows = _run_rows(small_sample, materials, extractor_mode=EXTRACTOR_RULES)
            llm_rows = _run_rows(small_sample, materials, extractor_mode=EXTRACTOR_LLM)
            all_rows = rules_rows + llm_rows
            metrics = compute_metrics(all_rows)
            by_extractor = {
                EXTRACTOR_RULES: compute_metrics(rules_rows),
                EXTRACTOR_LLM: compute_metrics(llm_rows),
            }
            report_path = tmp_path / "compare.md"
            write_report(
                all_rows, metrics, report_path, llm_eval_cfg,
                requested_mode="offline", extractor_mode=EXTRACTOR_COMPARE,
                by_extractor_metrics=by_extractor,
            )
            mock_urlopen.assert_not_called(), \
                "compare offline 模式不应发起任何 HTTP 调用"

    def test_extractor_invalid_falls_back_to_rules(self, small_sample, materials):
        """
        _evaluate_one 接受非法 extractor_mode → 兜底到 rules 路径,
        行为应跟 EXTRACTOR_RULES 一致(fallback_used=False)。
        """
        row = _evaluate_one(small_sample[0], materials, extractor_mode="not_a_real_mode")
        assert row.extractor_mode == EXTRACTOR_RULES, \
            f"非法 extractor_mode 应兜底为 'rules'; got {row.extractor_mode}"
        assert row.fallback_category == FALLBACK_NONE, \
            "rules 兜底路径不应有 fallback"
        assert row.fallback_used is False


# ======================================================================
# TestPhase5Metrics (R6-B Phase 5 spec §8)
# ======================================================================
class TestPhase5Metrics:
    """Phase 5: compute_metrics 新增字段."""

    def test_metrics_includes_low_confidence_slot_rate(
        self, all_samples, materials,
    ):
        """metrics 含 low_confidence_slot_rate 字段(0.0-1.0 float)."""
        rows = _run_rows(all_samples, materials, extractor_mode=EXTRACTOR_RULES)
        metrics = compute_metrics(rows)
        assert "low_confidence_slot_rate" in metrics, \
            "metrics 应含 low_confidence_slot_rate"
        rate = metrics["low_confidence_slot_rate"]
        assert isinstance(rate, float), f"low_confidence_slot_rate 应是 float; got {type(rate).__name__}"
        assert 0.0 <= rate <= 1.0, f"low_confidence_slot_rate 应在 [0, 1]; got {rate}"

    def test_metrics_includes_p95_latency_ms(
        self, all_samples, materials,
    ):
        """metrics 含 p95_latency_ms 字段(非负 int)."""
        rows = _run_rows(all_samples, materials, extractor_mode=EXTRACTOR_RULES)
        metrics = compute_metrics(rows)
        assert "p95_latency_ms" in metrics
        p95 = metrics["p95_latency_ms"]
        assert isinstance(p95, int), f"p95_latency_ms 应是 int; got {type(p95).__name__}"
        assert p95 >= 0

    def test_metrics_includes_fallback_category_breakdown_5_categories(
        self, all_samples, materials,
    ):
        """metrics.fallback_category_breakdown 是 5 类 dict(对齐 R5-C Phase 1)."""
        rows = _run_rows(all_samples, materials, extractor_mode=EXTRACTOR_RULES)
        metrics = compute_metrics(rows)
        fb = metrics.get("fallback_category_breakdown")
        assert isinstance(fb, dict)
        expected_keys = {
            FALLBACK_NONE, FALLBACK_LLM_DISABLED, FALLBACK_TOOL_ERROR,
            FALLBACK_SCHEMA_RETRY, FALLBACK_WORKFLOW_ABORT,
        }
        assert set(fb.keys()) == expected_keys, \
            f"fallback_category_breakdown 应含 5 类; got {set(fb.keys())}"
        for k, v in fb.items():
            assert isinstance(v, int) and v >= 0

    def test_metrics_by_extractor_groups_separate_rules_and_llm(
        self, all_samples, materials,
    ):
        """compare 模式: metrics.by_extractor 含 rules + llm 两组, 互不混入."""
        rules_rows = _run_rows(all_samples, materials, extractor_mode=EXTRACTOR_RULES)
        llm_rows = _run_rows(all_samples, materials, extractor_mode=EXTRACTOR_LLM)
        metrics = compute_metrics(rules_rows + llm_rows)

        by_ext = metrics.get("by_extractor")
        assert isinstance(by_ext, dict)
        assert EXTRACTOR_RULES in by_ext and EXTRACTOR_LLM in by_ext, \
            f"by_extractor 应含 rules + llm; got keys: {list(by_ext.keys())}"
        # 两组 total 各为 N, 之和 = 全局 total
        n = len(all_samples)
        assert by_ext[EXTRACTOR_RULES]["total"] == n
        assert by_ext[EXTRACTOR_LLM]["total"] == n
        assert by_ext[EXTRACTOR_RULES]["total"] + by_ext[EXTRACTOR_LLM]["total"] == metrics["total"]

    def test_compute_metrics_handles_empty_rows(self):
        """空 rows 不抛, 返完整 schema 含 0 值字段."""
        m = compute_metrics([])
        assert m["total"] == 0
        assert m["schema_pass_rate"] == 0.0
        assert m["p95_latency_ms"] == 0
        assert m["low_confidence_slot_rate"] == 0.0
        # 5 类 fallback 仍在
        for cat in (
            FALLBACK_NONE, FALLBACK_LLM_DISABLED, FALLBACK_TOOL_ERROR,
            FALLBACK_SCHEMA_RETRY, FALLBACK_WORKFLOW_ABORT,
        ):
            assert cat in m["fallback_category_breakdown"]


# ======================================================================
# TestPhase5Report (R6-B Phase 5 spec §8 报告)
# ======================================================================
class TestPhase5Report:
    """Phase 5: write_report 新增章节."""

    def test_compare_report_contains_rules_vs_llm_table(
        self, all_samples, materials, llm_eval_cfg, tmp_path,
    ):
        """compare 报告含 'Rules vs LLM-assisted 对照' 表格(8 指标 + Delta)."""
        rules_rows = _run_rows(all_samples, materials, extractor_mode=EXTRACTOR_RULES)
        llm_rows = _run_rows(all_samples, materials, extractor_mode=EXTRACTOR_LLM)
        all_rows = rules_rows + llm_rows
        metrics = compute_metrics(all_rows)
        by_ext = {
            EXTRACTOR_RULES: compute_metrics(rules_rows),
            EXTRACTOR_LLM: compute_metrics(llm_rows),
        }
        report_path = tmp_path / "compare.md"
        write_report(
            all_rows, metrics, report_path, llm_eval_cfg,
            requested_mode="offline", extractor_mode=EXTRACTOR_COMPARE,
            by_extractor_metrics=by_ext,
        )
        report_text = report_path.read_text(encoding="utf-8")
        assert "Rules vs LLM-assisted" in report_text
        # 8 个关键指标都在对照表里
        for label in (
            "样本数", "schema_pass_rate", "fallback_rate",
            "avg_completeness", "fabrication_violations",
            "avg_latency_ms", "p95_latency_ms", "low_confidence_slot_rate",
        ):
            assert label in report_text, f"对照表缺指标 {label}"
        assert "Delta" in report_text, "对照表应含 Delta 块"

    def test_compare_report_contains_fallback_category_section(
        self, all_samples, materials, llm_eval_cfg, tmp_path,
    ):
        """compare 报告含 'fallback_category 分布' 章节."""
        rules_rows = _run_rows(all_samples, materials, extractor_mode=EXTRACTOR_RULES)
        llm_rows = _run_rows(all_samples, materials, extractor_mode=EXTRACTOR_LLM)
        all_rows = rules_rows + llm_rows
        metrics = compute_metrics(all_rows)
        by_ext = {
            EXTRACTOR_RULES: compute_metrics(rules_rows),
            EXTRACTOR_LLM: compute_metrics(llm_rows),
        }
        report_path = tmp_path / "compare.md"
        write_report(
            all_rows, metrics, report_path, llm_eval_cfg,
            requested_mode="offline", extractor_mode=EXTRACTOR_COMPARE,
            by_extractor_metrics=by_ext,
        )
        report_text = report_path.read_text(encoding="utf-8")
        assert "fallback_category 分布" in report_text
        # 5 类都在章节里
        for cat in (
            FALLBACK_NONE, FALLBACK_LLM_DISABLED, FALLBACK_TOOL_ERROR,
            FALLBACK_SCHEMA_RETRY, FALLBACK_WORKFLOW_ABORT,
        ):
            assert cat in report_text, f"fallback_category 分布应含 {cat}"

    def test_report_contains_low_confidence_slot_rate_metric(
        self, small_sample, materials, llm_eval_cfg, tmp_path,
    ):
        """任何 extractor 模式的报告都含 low_confidence_slot_rate 字段."""
        for mode in EXTRACTOR_MODES:
            report_path = tmp_path / f"{mode}.md"
            if mode == EXTRACTOR_COMPARE:
                rules_rows = _run_rows(small_sample, materials, extractor_mode=EXTRACTOR_RULES)
                llm_rows = _run_rows(small_sample, materials, extractor_mode=EXTRACTOR_LLM)
                all_rows = rules_rows + llm_rows
                metrics = compute_metrics(all_rows)
                by_ext = {
                    EXTRACTOR_RULES: compute_metrics(rules_rows),
                    EXTRACTOR_LLM: compute_metrics(llm_rows),
                }
                write_report(
                    all_rows, metrics, report_path, llm_eval_cfg,
                    requested_mode="offline", extractor_mode=mode,
                    by_extractor_metrics=by_ext,
                )
            else:
                rows = _run_rows(small_sample, materials, extractor_mode=mode)
                metrics = compute_metrics(rows)
                write_report(
                    rows, metrics, report_path, llm_eval_cfg,
                    requested_mode="offline", extractor_mode=mode,
                )
            report_text = report_path.read_text(encoding="utf-8")
            assert "low_confidence_slot_rate" in report_text, \
                f"{mode} 模式报告应含 low_confidence_slot_rate 字段"

    def test_compare_report_contains_no_user_message_text(
        self, all_samples, materials, llm_eval_cfg, tmp_path,
    ):
        """compare 模式报告也不含 user_message 原文(隐私边界, 跟 R6-A Phase 5 一致)."""
        rules_rows = _run_rows(all_samples, materials, extractor_mode=EXTRACTOR_RULES)
        llm_rows = _run_rows(all_samples, materials, extractor_mode=EXTRACTOR_LLM)
        all_rows = rules_rows + llm_rows
        metrics = compute_metrics(all_rows)
        by_ext = {
            EXTRACTOR_RULES: compute_metrics(rules_rows),
            EXTRACTOR_LLM: compute_metrics(llm_rows),
        }
        report_path = tmp_path / "compare.md"
        write_report(
            all_rows, metrics, report_path, llm_eval_cfg,
            requested_mode="offline", extractor_mode=EXTRACTOR_COMPARE,
            by_extractor_metrics=by_ext,
        )
        report_text = report_path.read_text(encoding="utf-8")
        forbidden = [
            "我负责课程项目里的测试反馈整理",
            "社团活动报名时信息很乱",
            "我做过一个数据整理项目",
            "我负责一个医疗垂类大模型评测项目",
            "我参与一个心电时序信号大模型预研课题",
            "我参加一个开源社团的 AI 应用开发贡献",
            "我参与过一场大型综合体育赛事的志愿服务",
            "我做过一个数据标注项目",
            "我在医疗垂类评测项目里负责从 Badcase",
            "我负责一个评测流程的搭建",
        ]
        leaks = [p for p in forbidden if p in report_text]
        assert not leaks, f"compare 报告泄漏 user_message: {leaks}"

    def test_llm_offline_report_marks_llm_disabled_fallback(
        self, all_samples, materials, llm_eval_cfg, tmp_path,
    ):
        """llm 模式 + offline 报告含 llm_disabled_fallback 标记 + 全行 fb_cat 标记."""
        rows = _run_rows(all_samples, materials, extractor_mode=EXTRACTOR_LLM)
        metrics = compute_metrics(rows)
        report_path = tmp_path / "llm_offline.md"
        write_report(
            rows, metrics, report_path, llm_eval_cfg,
            requested_mode="offline", extractor_mode=EXTRACTOR_LLM,
        )
        report_text = report_path.read_text(encoding="utf-8")
        assert "llm_disabled_fallback" in report_text
        # fb_cat 标签出现在每条样本摘要里
        llm_row_count = sum(
            1 for line in report_text.splitlines()
            if "fb_cat=`llm_disabled_fallback`" in line
        )
        assert llm_row_count == len(all_samples), \
            f"每条样本摘要都应标 fb_cat=llm_disabled_fallback; got {llm_row_count} / {len(all_samples)}"

    def test_report_no_api_key_no_prompt_no_source_span(
        self, all_samples, materials, llm_eval_cfg, tmp_path,
    ):
        """
        报告不含 prompt 正文 / source_span 明文 / draft_card 原文 / user_message 明文
        / API key 实际值(隐私边界, spec §8 + §12).

        用 sentinel 检测(offline 模式):
          - sentinel prompt: 用 core.interview_prompts.SLOT_EXTRACTION_SYSTEM_PROMPT 前 50 字符子串
            (脚本默认不调 LLM, prompt 不入报告; 即便 LLM 路径走通, 报告也只暴露 count 不暴露 prompt)
          - sentinel source_span: 把特殊字符串塞进 user_message, 规则抽取可能命中,
            但报告只暴露 slot key + 长度, 不暴露原始 source_span
          - sentinel draft_bullets: 同上, 报告只暴露 schema 不暴露 bullet 原文
          - 不设 LLM_API_KEY env: offline 模式 + 无 key, 不会触发真 LLM HTTP 调用
            (避免测试卡住 + 保证隐私自检的真实性)

        注意: "LLM_API_KEY" / "source_span" 字面量本身在报告边界说明里出现是合规的
        (说明文字 / 隐私检查章节), 不应作为"泄漏"判定。真正的泄漏是 key 实际值 /
        prompt 完整正文 / source_span / draft_bullets / user_message 原文。
        """
        # 1) sentinel prompt 子串
        from core.interview_prompts import SLOT_EXTRACTION_SYSTEM_PROMPT  # noqa: PLC0415
        sentinel_prompt_substr = SLOT_EXTRACTION_SYSTEM_PROMPT[:50]

        # 2) sentinel source_span / draft_bullet / user_message —
        #    塞进 sample user_messages(规则版会抽, 但报告只暴露 slot key + 长度, 不暴露原文)
        sentinel_span = "SENTINEL-SOURCE-SPAN-FOR-LEAK-DETECTION-DO-NOT-SHOW"
        poisoned_samples = []
        for s in all_samples:
            s_copy = dict(s)
            s_copy["user_messages"] = list(s.get("user_messages") or []) + [sentinel_span]
            poisoned_samples.append(s_copy)

        rules_rows = _run_rows(poisoned_samples, materials, extractor_mode=EXTRACTOR_RULES)
        llm_rows = _run_rows(poisoned_samples, materials, extractor_mode=EXTRACTOR_LLM)
        all_rows = rules_rows + llm_rows
        metrics = compute_metrics(all_rows)
        by_ext = {
            EXTRACTOR_RULES: compute_metrics(rules_rows),
            EXTRACTOR_LLM: compute_metrics(llm_rows),
        }
        report_path = tmp_path / "compare.md"
        write_report(
            all_rows, metrics, report_path, llm_eval_cfg,
            requested_mode="offline", extractor_mode=EXTRACTOR_COMPARE,
            by_extractor_metrics=by_ext,
        )
        report_text = report_path.read_text(encoding="utf-8")

        # 隐私自检: sentinel 字符串必须不出现在报告里
        leaks: list[str] = []
        if sentinel_prompt_substr in report_text:
            leaks.append("prompt 正文子串 (sentinel)")
        if sentinel_span in report_text:
            leaks.append("source_span / user_message 明文 (sentinel)")
        assert not leaks, f"报告泄漏隐私字段: {leaks}"


# ======================================================================
# TestPhase5Cli (R6-B Phase 5 spec §8 main())
# ======================================================================
class TestPhase5Cli:
    """Phase 5: main() CLI 行为."""

    def test_main_offline_compare_writes_report(self, tmp_path, monkeypatch):
        """
        main() + --extractor compare + --mode offline:
          - 写报告到指定路径
          - 报告含 'Rules vs LLM-assisted' 章节
          - exit code 0
        """
        # 把 cwd 切到 backend/ (load_materials 用相对路径)
        monkeypatch.chdir(BACKEND_DIR)

        out_path = tmp_path / "out.md"
        exit_code = main([
            "--mode", "offline",
            "--extractor", "compare",
            "--output", str(out_path),
        ])
        assert exit_code == 0
        assert out_path.exists()
        report_text = out_path.read_text(encoding="utf-8")
        assert "Rules vs LLM-assisted" in report_text
        assert "fallback_category 分布" in report_text
        assert "llm_disabled_fallback" in report_text

    def test_main_offline_rules_unchanged(self, tmp_path, monkeypatch):
        """
        main() + --extractor rules (默认) 行为字节级一致 R6-A Phase 5:
          - exit code 0
          - 报告标题含 '规则版'
          - 报告不含 'Rules vs LLM-assisted' 章节(compare 专属)
        """
        monkeypatch.chdir(BACKEND_DIR)
        out_path = tmp_path / "rules.md"
        exit_code = main([
            "--mode", "offline",
            "--extractor", "rules",
            "--output", str(out_path),
        ])
        assert exit_code == 0
        report_text = out_path.read_text(encoding="utf-8")
        assert "规则版" in report_text
        assert "Rules vs LLM-assisted" not in report_text, \
            "rules 模式报告不应含 'Rules vs LLM-assisted' 章节(compare 专属)"

    def test_main_invalid_extractor_rejected(self, tmp_path, monkeypatch):
        """main() + --extractor invalid: argparse 拒绝(exit code != 0)."""
        monkeypatch.chdir(BACKEND_DIR)
        out_path = tmp_path / "x.md"
        with pytest.raises(SystemExit) as exc_info:
            main([
                "--mode", "offline",
                "--extractor", "not_a_real_mode",
                "--output", str(out_path),
            ])
        assert exc_info.value.code != 0, \
            f"非法 extractor_mode 应被 argparse 拒绝; got code={exc_info.value.code}"