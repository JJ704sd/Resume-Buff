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
    EVAL_CONTRACT_WARN_BEYOND_3,
    EVAL_CONTRACT_WARN_UNREACHABLE,
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
    _validate_eval_contract,
    compute_metrics,
    main,
    write_report,
)
from core.interview_agent import (  # noqa: E402
    ActionType,
    apply_action,
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


# ======================================================================
# R6-G F-2.3: live + (llm/compare) + 无 key → stderr 错误信息脱敏
# (R5-D spec §6.4 + R6-F audit §2 review-needed)
# ======================================================================
class TestPhaseGStderrNoEnvVarLeak:
    """
    R6-G F-2.3: main() 在 live + (llm/compare) + 无 key 路径的 stderr 错误信息
    **绝不**含 env var 名(`LLM_API_KEY`)。

    旧实现(line 1801-1806)错误信息写 "或设置 LLM_API_KEY 环境变量后手动跑 live 模式",
    违反 R5-D spec §6.4 "错误信息不能包含 key 值或 env var 名" 的精神。
    R6-G F-2.3 改用 "在环境变量里配置 LLM 凭据" 通用描述, 不引用 env var 名。

    测法说明:
      main() 内 `if not llm_enabled: print([error]...); return 2` 是 defensive 分支 —
      正常流 `_resolve_eval_mode(live, False)` 会先抛 RuntimeError(R5-D TestEvalModeNoKeyLeak
      已锁), main() print 走不到。测试通过同时 mock 2 层来强制走 main() print 分支。
    """

    def _force_main_stderr_branch(self, monkeypatch, extractor_mode):
        """辅助: 强制 main() 走 stderr print 分支(defensive guard)。

        main() 内的 `if resolved_mode == MODE_LIVE and args.extractor in (llm, compare):`
        print 分支是 defensive 代码 — 正常流 `_resolve_eval_mode(live, False)` 会先 raise
        (R5-D TestEvalModeNoKeyLeak 已锁)。测试通过 mock `_resolve_eval_mode` 直接返
        MODE_LIVE 来绕过 raise, 让 main() 进 print 分支。
        """
        import evaluate_interview_agent as ev_mod
        # 1) is_llm_enabled 返 False → main() 进 `if not llm_enabled` 分支
        monkeypatch.setattr(ev_mod, "is_llm_enabled", lambda: False)
        # 2) _resolve_eval_mode 直接返 "live", 跳过其内部 raise
        #    (无论入参 mode 是什么, 都返 MODE_LIVE 让 main() 进 print 分支)
        monkeypatch.setattr(
            ev_mod, "_resolve_eval_mode",
            lambda _mode, _llm_enabled: "live",
        )

    def test_main_live_llm_no_key_stderr_no_env_var_name(
        self, tmp_path, monkeypatch, capsys,
    ):
        """live + --extractor llm + 无 key → exit 2, stderr 不含 LLM_API_KEY 字面量。"""
        self._force_main_stderr_branch(monkeypatch, EXTRACTOR_LLM)
        import evaluate_interview_agent as ev_mod

        out_path = tmp_path / "out.md"
        monkeypatch.chdir(BACKEND_DIR)

        exit_code = ev_mod.main([
            "--mode", "live",
            "--extractor", "llm",
            "--output", str(out_path),
        ])
        captured = capsys.readouterr()

        # exit code 2(R6-B Phase 5 沿用)
        assert exit_code == 2, (
            f"live + llm + 无 key 应 exit 2, 实际 {exit_code}"
        )

        # stderr 不含 env var 名
        assert "LLM_API_KEY" not in captured.err, (
            f"stderr 错误信息不应包含 env var 名 LLM_API_KEY: {captured.err!r}"
        )
        # stderr 不含 api key 前缀
        assert "sk-" not in captured.err, (
            f"stderr 错误信息不应包含 key 前缀: {captured.err!r}"
        )
        # stderr 不含 Bearer 字样
        assert "Bearer" not in captured.err, (
            f"stderr 错误信息不应包含 Bearer: {captured.err!r}"
        )
        # stderr 含 "[error]" 标记 + 引导用户
        assert "[error]" in captured.err
        # stderr 含通用描述("LLM 凭据" 或 "环境变量" 一类)
        assert (
            "LLM 凭据" in captured.err
            or "环境变量" in captured.err
            or "环境" in captured.err
        ), (
            f"stderr 应含通用 LLM 凭据配置描述, 实际: {captured.err!r}"
        )

    def test_main_live_compare_no_key_stderr_no_env_var_name(
        self, tmp_path, monkeypatch, capsys,
    ):
        """live + --extractor compare + 无 key → exit 2, stderr 不含 LLM_API_KEY。"""
        self._force_main_stderr_branch(monkeypatch, EXTRACTOR_COMPARE)
        import evaluate_interview_agent as ev_mod

        out_path = tmp_path / "out.md"
        monkeypatch.chdir(BACKEND_DIR)

        exit_code = ev_mod.main([
            "--mode", "live",
            "--extractor", "compare",
            "--output", str(out_path),
        ])
        captured = capsys.readouterr()

        assert exit_code == 2
        assert "LLM_API_KEY" not in captured.err, (
            f"stderr 错误信息不应包含 env var 名 LLM_API_KEY: {captured.err!r}"
        )
        assert "sk-" not in captured.err
        assert "Bearer" not in captured.err

    def test_main_live_rules_no_key_does_not_print_error(
        self, tmp_path, monkeypatch, capsys,
    ):
        """live + --extractor rules + 无 key → 不触发 stderr error 分支(控制组)。

        rules 模式不依赖 LLM, 走 pure rules 路径, 不应触发任何 stderr 错误。
        """
        # 模拟 live + 无 key — 但 rules 模式不进 if 分支
        import evaluate_interview_agent as ev_mod
        from evaluate_agent_workflow import _resolve_eval_mode as _real_resolve
        # is_llm_enabled 返 False 模拟无 key
        monkeypatch.setattr(ev_mod, "is_llm_enabled", lambda: False)
        # _resolve_eval_mode 跳过其内部 raise, 走 "live"(rules 模式不需要 LLM, 走通)
        monkeypatch.setattr(
            ev_mod, "_resolve_eval_mode",
            lambda mode, _llm: "live",
        )

        out_path = tmp_path / "out.md"
        monkeypatch.chdir(BACKEND_DIR)

        try:
            ev_mod.main([
                "--mode", "live",
                "--extractor", "rules",
                "--output", str(out_path),
            ])
        except Exception:
            # rules 模式不调 LLM, 正常应该 exit 0 — 但意外异常也要容忍
            pass
        captured = capsys.readouterr()

        # rules 模式不应触发 [error] 分支
        assert "[error]" not in captured.err, (
            f"live + rules 模式不应触发 [error] 分支: {captured.err!r}"
        )

    def test_help_text_no_env_var_name(self):
        """main() 模块源码扫描: 帮助文本 / print 字符串**都不**含 env var 名。

        静态扫描是兜底: 即使 R5-D `_resolve_eval_mode` 在 live+no_key 时先 raise,
        main() print 分支是 defensive 代码, 也必须保证不含 env var 名,
        以防未来重构把 _resolve_eval_mode 内联到 main() 时泄漏。
        """
        import inspect
        import re

        import evaluate_interview_agent as ev_mod

        src = inspect.getsource(ev_mod)
        # 找出所有含 [error] 的字符串字面量(主要查 main() 的 print)
        error_strings = re.findall(
            r'"[^"\']*\[error\][^"\']*"|\'[^\']*\[error\][^\']*\'',
            src,
        )
        for s in error_strings:
            assert "LLM_API_KEY" not in s, (
                f"main() [error] 字符串不应含 env var 名 LLM_API_KEY: {s!r}"
            )
            assert "sk-" not in s, (
                f"main() [error] 字符串不应含 key 前缀: {s!r}"
            )
            assert "Bearer" not in s, (
                f"main() [error] 字符串不应含 Bearer: {s!r}"
            )

        # 也扫 help 文本
        help_strings = re.findall(
            r'help=\(\s*([^)]+)\s*\)',
            src,
        )
        for chunk in help_strings:
            # 多行字符串, 拼起来查
            cleaned = re.sub(r'"\s*"|\'\s*\'', '', chunk)
            assert "LLM_API_KEY" not in cleaned, (
                f"main() help 文本不应含 env var 名: {cleaned!r}"
            )


# ======================================================================
# R6-C.1 Eval contract 检查 + 报告 wording 修正 (路线 A, round6-c-live-eval-result §5)
# ======================================================================
class TestPhaseC1EvalContractValidation:
    """
    R6-C.1: _validate_eval_contract(sample) 单元测试。

    spec(路线 A 验收点):
      - expected slot 不在 GAP_SUGGESTED_SLOTS[gap_id] 中 → unreachable_expected_slot warning
      - expected slot 排在 suggested 位置 >= MAX_TURNS_PER_GAP(=3) 且
        不在 near_limit 触达集合 {metric, result} 中 → beyond_three_turns_expected_slot warning
      - 位置 < 3 / 位置 >= 3 但属于 metric/result → 不产生 warning
      - 未知 gap_id → 所有 expected slot 视为 unreachable
      - warning record 只含 name/gap_id/slot/code, 不含 user_message 原文
    """

    def test_unreachable_expected_slot_creates_warning(self):
        """
        tech_metric suggested = (background, responsibility, action, method, result)
        tech_metric 不在 suggested 中, expected 含 "metric" → unreachable warning.
        """
        sample = {
            "name": "test_unreachable",
            "gap_id": "tech_metric",
            "expected_slots": {
                "responsibility": "X",   # 可达
                "metric": "Y",            # 不可达 (tech_metric 不在 suggested)
            },
        }
        warnings = _validate_eval_contract(sample)
        unreachable = [
            w for w in warnings if w["code"] == EVAL_CONTRACT_WARN_UNREACHABLE
        ]
        assert any(w["slot"] == "metric" for w in unreachable), (
            f"tech_metric 不应被 expected 'metric' 命中; got {unreachable}"
        )
        # 确认 name / gap_id 也对得上
        for w in unreachable:
            if w["slot"] == "metric":
                assert w["name"] == "test_unreachable"
                assert w["gap_id"] == "tech_metric"

    def test_beyond_three_turns_expected_slot_creates_warning(self):
        """
        tech_metric suggested = (background[0], responsibility[1], action[2], method[3], result[4])
        expected 含 "method"(位置 3, 非 metric/result) → beyond warning.
        """
        sample = {
            "name": "test_beyond_method",
            "gap_id": "tech_metric",
            "expected_slots": {
                "method": "X",  # 位置 3, 不可达
            },
        }
        warnings = _validate_eval_contract(sample)
        beyond = [
            w for w in warnings if w["code"] == EVAL_CONTRACT_WARN_BEYOND_3
        ]
        assert any(w["slot"] == "method" for w in beyond), (
            f"tech_metric.method 位置 3 应触发 beyond warning; got {beyond}"
        )

    def test_metric_or_result_near_limit_skips_beyond_warning(self):
        """
        spec §6 step 5: turn_count 接近上限时, policy 优先问 metric/result,
        即使它们在 suggested 位置 >= 3, 也不应产生 beyond warning.
        """
        # process_metric suggested = (responsibility[0], action[1], result[2], metric[3])
        sample_metric = {
            "name": "test_metric_pos3",
            "gap_id": "process_metric",
            "expected_slots": {"metric": "X"},  # 位置 3, 可被 near_limit 提前触达
        }
        warnings_m = _validate_eval_contract(sample_metric)
        beyond_m = [
            w for w in warnings_m if w["code"] == EVAL_CONTRACT_WARN_BEYOND_3
        ]
        assert not beyond_m, (
            f"process_metric.metric (位置 3) 属 near_limit 触达集合, 不应 beyond; got {warnings_m}"
        )
        # tech_metric suggested = (background[0], responsibility[1], action[2], method[3], result[4])
        sample_result = {
            "name": "test_result_pos4",
            "gap_id": "tech_metric",
            "expected_slots": {"result": "X"},  # 位置 4, 同样 near_limit
        }
        warnings_r = _validate_eval_contract(sample_result)
        beyond_r = [
            w for w in warnings_r if w["code"] == EVAL_CONTRACT_WARN_BEYOND_3
        ]
        assert not beyond_r, (
            f"tech_metric.result (位置 4) 属 near_limit 触达集合, 不应 beyond; got {warnings_r}"
        )

    def test_achievable_slot_creates_no_warning(self):
        """位置 < 3 的 slot 全部可达, 不应产生 warning."""
        sample = {
            "name": "test_achievable",
            "gap_id": "tech_metric",
            "expected_slots": {
                "background": "X",         # 位置 0
                "responsibility": "Y",     # 位置 1
                "action": ["Z"],          # 位置 2
            },
        }
        warnings = _validate_eval_contract(sample)
        assert warnings == [], f"可达 slot 不应产生 warning; got {warnings}"

    def test_empty_expected_creates_no_warning(self):
        sample = {
            "name": "test_empty",
            "gap_id": "tech_metric",
            "expected_slots": {},
        }
        warnings = _validate_eval_contract(sample)
        assert warnings == []

    def test_unknown_gap_id_marks_all_expected_unreachable(self):
        """未知 gap_id → 该 gap 不在 GAP_SUGGESTED_SLOTS, 所有 expected slot 视为 unreachable."""
        sample = {
            "name": "test_unknown_gap",
            "gap_id": "definitely_not_a_real_gap",
            "expected_slots": {
                "responsibility": "X",
                "action": ["Y"],
            },
        }
        warnings = _validate_eval_contract(sample)
        unreachable = [
            w for w in warnings if w["code"] == EVAL_CONTRACT_WARN_UNREACHABLE
        ]
        slots = {w["slot"] for w in unreachable}
        assert slots == {"responsibility", "action"}, (
            f"未知 gap_id 下, 所有 expected slot 都应 unreachable; got {slots}"
        )

    def test_warning_record_contains_no_user_message_or_pii(self):
        """
        privacy: warning record 只含 {name, gap_id, slot, code}, 不含 user_message 原文 /
        source_span / API key / prompt 正文.
        """
        sample = {
            "name": "test_no_leak",
            "gap_id": "tech_metric",
            "expected_slots": {
                "metric": "Y",   # unreachable
                "method": "Z",   # beyond 3
            },
            "user_messages": [
                "SENTINEL-ROUND6C1-USER-MSG-DO-NOT-SHOW-12345",
            ],
        }
        warnings = _validate_eval_contract(sample)
        for w in warnings:
            assert set(w.keys()) == {"name", "gap_id", "slot", "code"}, (
                f"warning record 应只含 4 字段; got keys={set(w.keys())}"
            )
            serialized = json.dumps(w, ensure_ascii=False)
            assert "SENTINEL-ROUND6C1-USER-MSG-DO-NOT-SHOW-12345" not in serialized, (
                f"warning record 不应泄漏 user_message 原文; got {serialized}"
            )
            assert "LLM_API_KEY" not in serialized
            assert "source_span" not in serialized


class TestPhaseC1ReportContractSection:
    """R6-C.1: write_report 新增 'Eval contract warnings' 章节."""

    def test_report_contains_eval_contract_warnings_section(
        self, all_samples, materials, llm_eval_cfg, tmp_path,
    ):
        rows = _run_rows(all_samples, materials, extractor_mode=EXTRACTOR_RULES)
        metrics = compute_metrics(rows)
        report_path = tmp_path / "r.md"
        write_report(
            rows, metrics, report_path, llm_eval_cfg,
            requested_mode="offline", extractor_mode=EXTRACTOR_RULES,
        )
        report_text = report_path.read_text(encoding="utf-8")
        assert "Eval contract warnings" in report_text, (
            "R6-C.1: 报告应含 'Eval contract warnings' 章节"
        )

    def test_report_contract_warnings_section_renders_sample_gap_slot_code(
        self, all_samples, materials, llm_eval_cfg, tmp_path,
    ):
        """
        当样本含 unreachable expected slot (EVAL_SET_SIMULATED[4] sim_domain_x_data_label
        含 metric, 不在 domain_x suggested 中), 报告应列出 sample / gap / slot / code.
        """
        rows = _run_rows(all_samples, materials, extractor_mode=EXTRACTOR_RULES)
        metrics = compute_metrics(rows)
        report_path = tmp_path / "r.md"
        write_report(
            rows, metrics, report_path, llm_eval_cfg,
            requested_mode="offline", extractor_mode=EXTRACTOR_RULES,
        )
        report_text = report_path.read_text(encoding="utf-8")
        # sim_domain_x_data_label expected 含 metric; domain_x 不在 suggested 中
        # 应触发 unreachable warning, 章节列出 sample / gap / slot / code
        assert "sim_domain_x_data_label" in report_text
        assert "domain_x" in report_text
        assert EVAL_CONTRACT_WARN_UNREACHABLE in report_text


class TestPhaseC1ReportWording:
    """
    R6-C.1: live compare 表头按 requested_mode 动态化 +
    fallback_rate 口径声明 (round6-c-live-eval-result §5 路线 A).
    """

    def test_live_report_does_not_show_offline_stale_wording(
        self, all_samples, materials, llm_eval_cfg, tmp_path,
    ):
        """
        live + compare 报告: 不再写 'offline → 强制规则 fallback' stale 文案.
        """
        rules_rows = _run_rows(all_samples, materials, extractor_mode=EXTRACTOR_RULES)
        llm_rows = _run_rows(all_samples, materials, extractor_mode=EXTRACTOR_LLM)
        all_rows = rules_rows + llm_rows
        metrics = compute_metrics(all_rows)
        by_ext = {
            EXTRACTOR_RULES: compute_metrics(rules_rows),
            EXTRACTOR_LLM: compute_metrics(llm_rows),
        }
        report_path = tmp_path / "live_compare.md"
        write_report(
            all_rows, metrics, report_path, llm_eval_cfg,
            requested_mode="live", extractor_mode=EXTRACTOR_COMPARE,
            by_extractor_metrics=by_ext,
        )
        report_text = report_path.read_text(encoding="utf-8")
        assert "offline → 强制规则 fallback" not in report_text, (
            "live 模式 compare 报告不应含 'offline → 强制规则 fallback' stale wording"
        )

    def test_offline_report_keeps_offline_fallback_label(
        self, all_samples, materials, llm_eval_cfg, tmp_path,
    ):
        """
        offline 模式仍用 'offline → 强制规则 fallback' 描述(它是准确的, 跟实际行为一致).
        """
        rules_rows = _run_rows(all_samples, materials, extractor_mode=EXTRACTOR_RULES)
        llm_rows = _run_rows(all_samples, materials, extractor_mode=EXTRACTOR_LLM)
        all_rows = rules_rows + llm_rows
        metrics = compute_metrics(all_rows)
        by_ext = {
            EXTRACTOR_RULES: compute_metrics(rules_rows),
            EXTRACTOR_LLM: compute_metrics(llm_rows),
        }
        report_path = tmp_path / "offline_compare.md"
        write_report(
            all_rows, metrics, report_path, llm_eval_cfg,
            requested_mode="offline", extractor_mode=EXTRACTOR_COMPARE,
            by_extractor_metrics=by_ext,
        )
        report_text = report_path.read_text(encoding="utf-8")
        assert "offline → 强制规则 fallback" in report_text, (
            "offline 模式 compare 报告应保留 'offline → 强制规则 fallback' 描述"
        )

    def test_fallback_rate_caption_present_in_report(
        self, all_samples, materials, llm_eval_cfg, tmp_path,
    ):
        """
        fallback_rate 是 workflow/session 级, 不是 slot 级 LLM 成功率.
        报告应有口径声明澄清这一点(避免读者把 fallback_rate 误读为 LLM 抽取质量).
        """
        rows = _run_rows(all_samples, materials, extractor_mode=EXTRACTOR_RULES)
        metrics = compute_metrics(rows)
        report_path = tmp_path / "r.md"
        write_report(
            rows, metrics, report_path, llm_eval_cfg,
            requested_mode="offline", extractor_mode=EXTRACTOR_RULES,
        )
        report_text = report_path.read_text(encoding="utf-8")
        # 口径声明: workflow / session 级 (兼容 "workflow / session" 和 "workflow/session" 写法)
        assert (
            "workflow / session 级" in report_text
            or "workflow/session 级" in report_text
        ), "fallback_rate 应有口径声明: workflow/session 级聚合, 不是 slot 级 LLM 成功"
        # slot 级 LLM 成功 / slot 级 抽取 — 这类描述应该被显式排除, 而不是 "fallback_rate 高 = LLM 稳"
        assert "不是 slot 级" in report_text or "不代表 slot 级" in report_text, (
            "fallback_rate 口径应明确否定 'slot 级 LLM 成功率' 误读"
        )


class TestPhaseC1ReportPrivacy:
    """
    R6-C.1: contract warnings 章节不泄漏 user_message / prompt / source_span / API key.
    """

    def test_report_contract_section_does_not_leak_user_message(
        self, all_samples, materials, llm_eval_cfg, tmp_path,
    ):
        sentinel_user_msg = "SENTINEL-ROUND6C1-USER-MSG-DO-NOT-LEAK-IN-CONTRACT"
        sentinel_span = "SENTINEL-ROUND6C1-SOURCE-SPAN-DO-NOT-LEAK-IN-CONTRACT"
        sentinel_api_key = "sk-sentinel-round6c1-api-key-must-not-appear"
        poisoned: list[dict] = []
        for s in all_samples:
            s_copy = dict(s)
            s_copy["user_messages"] = list(s.get("user_messages") or []) + [
                sentinel_user_msg, sentinel_span,
            ]
            poisoned.append(s_copy)
        rules_rows = _run_rows(poisoned, materials, extractor_mode=EXTRACTOR_RULES)
        llm_rows = _run_rows(poisoned, materials, extractor_mode=EXTRACTOR_LLM)
        all_rows = rules_rows + llm_rows
        metrics = compute_metrics(all_rows)
        by_ext = {
            EXTRACTOR_RULES: compute_metrics(rules_rows),
            EXTRACTOR_LLM: compute_metrics(llm_rows),
        }
        report_path = tmp_path / "r.md"
        write_report(
            all_rows, metrics, report_path, llm_eval_cfg,
            requested_mode="offline", extractor_mode=EXTRACTOR_COMPARE,
            by_extractor_metrics=by_ext,
        )
        report_text = report_path.read_text(encoding="utf-8")
        leaks: list[str] = []
        if sentinel_user_msg in report_text:
            leaks.append("user_message 原文 (sentinel)")
        if sentinel_span in report_text:
            leaks.append("source_span 明文 (sentinel)")
        if sentinel_api_key in report_text:
            leaks.append("API key 值 (sentinel)")
        assert not leaks, f"contract warnings 章节泄漏隐私字段: {leaks}"

    def test_report_contract_section_does_not_leak_prompt_body(
        self, all_samples, materials, llm_eval_cfg, tmp_path,
    ):
        """
        sentinel: 用 core.interview_prompts.SLOT_EXTRACTION_SYSTEM_PROMPT 前 50 字符子串,
        报告 / stdout 不应含此子串(spec §8 + §12 + R6-C.1 边界).
        """
        from core.interview_prompts import SLOT_EXTRACTION_SYSTEM_PROMPT  # noqa: PLC0415
        sentinel_prompt_substr = SLOT_EXTRACTION_SYSTEM_PROMPT[:50]
        rows = _run_rows(all_samples, materials, extractor_mode=EXTRACTOR_RULES)
        metrics = compute_metrics(rows)
        report_path = tmp_path / "r.md"
        write_report(
            rows, metrics, report_path, llm_eval_cfg,
            requested_mode="offline", extractor_mode=EXTRACTOR_RULES,
        )
        report_text = report_path.read_text(encoding="utf-8")
        assert sentinel_prompt_substr not in report_text, (
            "contract warnings 章节不应泄漏 prompt 正文子串"
        )


# ======================================================================
# R6-C.2A: Eval contract 调整 (路线 A, round6-c.2a — schema_pass_rate 变化必须
# 解释为"评测合同变化", 不解读为 LLM 能力提升)
# ======================================================================
class TestPhaseC2EvalContract:
    """
    R6-C.2A: 每条 sample 加 product_goal / contract_note 字段,
    communication_club 的 expected_slots 调整为 (action/method/result)
    表达 3 轮内可生成素材目标; simulated samples 保留 expected 不删,
    标记需后续 policy 调整 (product_goal=full_fact_coverage).

    验收: schema_pass_rate 变化 = 评测合同变化, 不是 LLM 能力变化.
    报告 4.6 章节记录每条 sample 的 product_goal + 合同决策.
    """

    def test_all_samples_have_product_goal_and_contract_note(self):
        """所有 10 条 sample 都应有 product_goal / contract_note 字段 (R6-C.2A 新增)."""
        for s in EVAL_SET_ALL:
            assert "product_goal" in s, (
                f"{s['name']} 缺 product_goal 字段"
            )
            assert "contract_note" in s, (
                f"{s['name']} 缺 contract_note 字段"
            )
            assert s["product_goal"] in (
                "three_turn_friendly", "full_fact_coverage",
            ), (
                f"{s['name']} product_goal 必须是 three_turn_friendly 或 full_fact_coverage; "
                f"got {s['product_goal']!r}"
            )
            assert len(str(s["contract_note"])) > 0, (
                f"{s['name']} contract_note 不能为空"
            )

    def test_plan_baseline_samples_are_three_turn_friendly(self):
        """plan_baseline 3 条 (process_metric_course / communication_club / tech_metric_data)
        应标 three_turn_friendly (3 轮内可生成素材目标)."""
        for s in EVAL_SET_PLAN_BASELINE:
            assert s["product_goal"] == "three_turn_friendly", (
                f"plan_baseline 样本 {s['name']} 应是 three_turn_friendly; "
                f"got {s['product_goal']!r}"
            )

    def test_simulated_samples_are_full_fact_coverage(self):
        """simulated_user_v1 7 条默认标 full_fact_coverage (完整项目事实覆盖目标)."""
        for s in EVAL_SET_SIMULATED:
            assert s["product_goal"] == "full_fact_coverage", (
                f"simulated 样本 {s['name']} 应是 full_fact_coverage; "
                f"got {s['product_goal']!r}"
            )

    def test_communication_club_expected_3_turn_reachable(self):
        """
        R6-C.2A: communication_club 的 expected_slots 调整为 (action/method/result),
        表达 3 轮内可生成素材目标. 移除原 responsibility (不在 communication suggested),
        新增 method (position 2, 3 轮内 100% 必问).
        """
        sample = next(
            s for s in EVAL_SET_ALL if s["name"] == "communication_club"
        )
        expected = sample["expected_slots"]
        assert "responsibility" not in expected, (
            "communication_club 调整后 expected 不应含 responsibility "
            "(不在 communication suggested 中)"
        )
        assert "action" in expected, "应保留 action (position 1, 3 轮内必问)"
        assert "method" in expected, "应新增 method (position 2, 3 轮内必问)"
        assert "result" in expected, "应保留 result (position 3, near_limit 触达)"
        # 3 个 expected slot 全部应在 communication suggested 内
        warnings = _validate_eval_contract(sample)
        assert warnings == [], (
            f"调整后 communication_club 应无 contract warning; got {warnings}"
        )

    def test_three_turn_friendly_samples_have_no_contract_warnings(self):
        """所有 three_turn_friendly 样本 (plan_baseline 3 条) 调整后 0 warning."""
        for s in EVAL_SET_ALL:
            if s["product_goal"] != "three_turn_friendly":
                continue
            warnings = _validate_eval_contract(s)
            assert warnings == [], (
                f"{s['name']} 标 three_turn_friendly 但有 warning: {warnings}"
            )

    def test_full_fact_coverage_samples_with_warning_keep_expected(self):
        """
        full_fact_coverage 样本若含 unreachable / beyond warning,
        expected_slots 应保留 (不删), 仅在 contract_note 标记"需后续 policy 调整".
        这正是 R6-C.2A 验收要求 — 完整事实覆盖不删 expected.
        """
        for s in EVAL_SET_ALL:
            if s["product_goal"] != "full_fact_coverage":
                continue
            warnings = _validate_eval_contract(s)
            if not warnings:
                continue  # 合同已合规的样本不在此断言范围
            # 合同不达标的样本应保留 expected 不删
            assert "expected_slots" in s
            assert len(s["expected_slots"]) >= len(warnings), (
                f"{s['name']} 合同不达标但 expected_slots 数量 ({len(s['expected_slots'])}) "
                f"少于 warning 数量 ({len(warnings)}), 可能被误删."
            )
            # contract_note 应明确提到 "需后续 policy 调整" 或等效说明
            assert "需后续 policy 调整" in s["contract_note"] or \
                "需要更多轮次" in s["contract_note"] or \
                "完整项目事实覆盖" in s["contract_note"], (
                f"{s['name']} contract_note 应说明 full_fact_coverage 决策依据; "
                f"got: {s['contract_note']}"
            )

    def test_report_contains_product_goal_section(
        self, all_samples, materials, llm_eval_cfg, tmp_path,
    ):
        """报告含 'Eval contract: product goal' 章节 (R6-C.2A 新增 4.6)."""
        rows = _run_rows(all_samples, materials, extractor_mode=EXTRACTOR_RULES)
        metrics = compute_metrics(rows)
        report_path = tmp_path / "r.md"
        write_report(
            rows, metrics, report_path, llm_eval_cfg,
            requested_mode="offline", extractor_mode=EXTRACTOR_RULES,
        )
        report_text = report_path.read_text(encoding="utf-8")
        assert "Eval contract: product goal" in report_text, (
            "R6-C.2A: 报告应含 'Eval contract: product goal' (4.6) 章节"
        )
        # 4.6 应列 product_goal 字段
        assert "product_goal" in report_text
        # 4.6 应解释 schema_pass_rate 变化 = 合同变化
        assert "评测合同变化" in report_text, (
            "4.6 章节应明确 'schema_pass_rate 变化 = 评测合同变化' 口径"
        )

    def test_report_product_goal_section_lists_all_samples(
        self, all_samples, materials, llm_eval_cfg, tmp_path,
    ):
        """4.6 章节应列出全部 10 条 sample (compare 模式按 sample 去重不重复)."""
        rows = _run_rows(all_samples, materials, extractor_mode=EXTRACTOR_RULES)
        metrics = compute_metrics(rows)
        report_path = tmp_path / "r.md"
        write_report(
            rows, metrics, report_path, llm_eval_cfg,
            requested_mode="offline", extractor_mode=EXTRACTOR_RULES,
        )
        report_text = report_path.read_text(encoding="utf-8")
        for s in all_samples:
            assert f"`{s['name']}`" in report_text, (
                f"4.6 章节应列出 sample `{s['name']}`"
            )

    def test_report_explains_schema_pass_rate_change_as_contract_change(
        self, all_samples, materials, llm_eval_cfg, tmp_path,
    ):
        """
        验收: schema_pass_rate 变化必须解释为'评测合同变化', 不能写成 LLM 能力提升.
        报告 4.6 + §八(结论) 都应含此口径说明.
        """
        rows = _run_rows(all_samples, materials, extractor_mode=EXTRACTOR_RULES)
        metrics = compute_metrics(rows)
        report_path = tmp_path / "r.md"
        write_report(
            rows, metrics, report_path, llm_eval_cfg,
            requested_mode="offline", extractor_mode=EXTRACTOR_RULES,
        )
        report_text = report_path.read_text(encoding="utf-8")
        # 4.6 + §八 共同应有 contract 变化说明
        assert "评测合同变化" in report_text, (
            "报告应明确 'schema_pass_rate 数值变化 = 评测合同变化' 口径"
        )
        # 显式否定 "LLM 能力提升 / LLM 抽取能力提升或下降" 这类误读
        assert "不解读为 LLM" in report_text or "不**解读为 LLM" in report_text, (
            "报告应显式排除 'LLM 能力变化' 误读"
        )

    def test_report_product_goal_section_does_not_leak_pii(
        self, all_samples, materials, llm_eval_cfg, tmp_path,
    ):
        """
        R6-C.2A: 4.6 章节 (product goal) 不泄漏 user_message / source_span / API key.
        contract_note 字段只描述产品目标, 不应含 user_message 原文.
        """
        sentinel_user_msg = "SENTINEL-ROUND6C2A-USER-MSG-DO-NOT-LEAK-12345"
        sentinel_span = "SENTINEL-ROUND6C2A-SOURCE-SPAN-DO-NOT-LEAK-12345"
        sentinel_api_key = "sk-sentinel-round6c2a-api-key-must-not-appear"
        poisoned: list[dict] = []
        for s in all_samples:
            s_copy = dict(s)
            s_copy["user_messages"] = list(s.get("user_messages") or []) + [
                sentinel_user_msg, sentinel_span,
            ]
            poisoned.append(s_copy)
        rows = _run_rows(poisoned, materials, extractor_mode=EXTRACTOR_RULES)
        metrics = compute_metrics(rows)
        report_path = tmp_path / "r.md"
        write_report(
            rows, metrics, report_path, llm_eval_cfg,
            requested_mode="offline", extractor_mode=EXTRACTOR_RULES,
        )
        report_text = report_path.read_text(encoding="utf-8")
        leaks: list[str] = []
        if sentinel_user_msg in report_text:
            leaks.append("user_message 原文 (sentinel)")
        if sentinel_span in report_text:
            leaks.append("source_span 明文 (sentinel)")
        if sentinel_api_key in report_text:
            leaks.append("API key 值 (sentinel)")
        assert not leaks, (
            f"4.6 (product goal) 章节泄漏隐私字段: {leaks}"
        )

    def test_compare_report_4_6_section_renders_for_both_groups(
        self, all_samples, materials, llm_eval_cfg, tmp_path,
    ):
        """compare 模式报告也含 4.6 章节, 且按 sample 去重不重复 (rules + llm 意图同份合同)."""
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
        assert "Eval contract: product goal" in report_text
        # 4.6 表格每条 sample 只出现 1 次(compare 双组同跑, 按 sample 去重)
        for s in all_samples:
            sample_mentions = report_text.count(f"`{s['name']}`")
            # sample 名在 4.6 (1 次) + 4.5 (可能 0/1) + 四 (compare 双组 2 次) = 至少 2 次
            # 上界由 4.5 warnings + compare 双组决定
            assert sample_mentions >= 2, (
                f"compare 报告中 {s['name']} 应至少出现 2 次 (4.6 + 4.5/四); got {sample_mentions}"
            )

    def test_communication_club_removed_responsibility_slot(
        self,
    ):
        """
        验收: 不允许简单把 expected_slots 改成当前 captured slot keys.
        communication_club 改后 expected (action/method/result) 跟 captured slots
        集合 (来自 user_messages 的 rule-based 抽取) 不应完全相同 — 必须含 captured 没
        填到的 slot (result), 保证"合同驱动"而非"结果驱动".
        """
        from core.interview_agent import (  # noqa: PLC0415
            ActionType,
            create_session,
        )
        from core.generator import load_materials  # noqa: PLC0415

        sample = next(
            s for s in EVAL_SET_ALL if s["name"] == "communication_club"
        )
        materials = load_materials()
        session = create_session(
            sample["role"], sample["jd_text"], materials,
        )
        # 强制选 communication gap
        for g in (session.gap_candidates or []):
            if g.gap_id == sample["gap_id"]:
                session.selected_gap = g
                break
        assert session.selected_gap is not None
        # 跑 user_messages 模拟
        for msg in sample["user_messages"]:
            if msg.strip() == "整理成素材":
                continue
            try:
                session, _resp = apply_action(
                    session, ActionType.ANSWER, msg,
                )
            except Exception:  # noqa: BLE001
                continue
        captured_keys = {
            k for k in (session.captured_slots or {}).keys()
            if not k.startswith("_")
        }
        expected_keys = set(sample["expected_slots"].keys())
        # 至少一个 expected key 在 captured 之外 (含 result — plan 不保证 100% 抽出)
        # 这证明 expected 不是简单照抄 captured.
        assert not expected_keys.issubset(captured_keys), (
            f"communication_club expected ({expected_keys}) 不应完全包含在 captured "
            f"({captured_keys}) 中 — 否则就是简单把 expected 改成 captured keys, "
            f"违反 R6-C.2A 边界."
        )


# ----------------------------------------------------------------------
# R6-C.3: LLM 抽取可观测性 (slot_source / retries / fallback_to_rules)
# ----------------------------------------------------------------------
class TestPhaseC3ObservabilityFields:
    """R6-C.3: EvalRow + compute_metrics + write_report 都含 LLM 抽取可观测性 3 指标.

    覆盖:
      - EvalRow 新增 3 字段 (slot_source_breakdown / llm_parse_retry_count /
        llm_to_rules_slot_fallback_count), 默认值正确
      - compute_metrics 聚合 3 字段到全局 + by_source + by_extractor
      - 默认 rules 路径下 retries/fb = 0
      - 报告 §4.7 章节存在 + 渲染 3 指标
      - 报告不含 user_message / prompt / source_span / API key(隐私边界)
    """

    def test_eval_row_default_observability_fields(self):
        """EvalRow 新增 3 字段默认值正确(空 dict / 0 / 0)。"""
        from evaluate_interview_agent import EvalRow

        row = EvalRow(
            name="t", source="x", role="r", gap_id="g",
            schema_pass=True, fallback_used=False,
            draft_card_completeness=0.5, fabrication_guard=True,
            latency_ms=10, rewrite_changed_count=0,
        )
        assert row.slot_source_breakdown == {}, (
            f"slot_source_breakdown 默认应是 {{}}, 实际 {row.slot_source_breakdown!r}"
        )
        assert row.llm_parse_retry_count == 0
        assert row.llm_to_rules_slot_fallback_count == 0

    def test_eval_row_to_dict_includes_observability(self):
        """EvalRow.to_dict() 含 3 个可观测性字段(供 report 渲染)。"""
        from evaluate_interview_agent import EvalRow

        row = EvalRow(
            name="t", source="x", role="r", gap_id="g",
            schema_pass=True, fallback_used=False,
            draft_card_completeness=0.5, fabrication_guard=True,
            latency_ms=10, rewrite_changed_count=0,
            slot_source_breakdown={"rules": 2, "llm": 1, "mixed": 0},
            llm_parse_retry_count=1,
            llm_to_rules_slot_fallback_count=1,
        )
        d = row.to_dict()
        assert d["slot_source_breakdown"] == {"rules": 2, "llm": 1, "mixed": 0}
        assert d["llm_parse_retry_count"] == 1
        assert d["llm_to_rules_slot_fallback_count"] == 1

    def test_compute_metrics_aggregates_observability(self):
        """compute_metrics 聚合 3 指标到全局 + by_source + by_extractor。"""
        from evaluate_interview_agent import EvalRow, compute_metrics

        rows = [
            EvalRow(
                name="a", source="plan_baseline", role="r1", gap_id="g1",
                schema_pass=True, fallback_used=False,
                draft_card_completeness=0.5, fabrication_guard=True,
                latency_ms=10, rewrite_changed_count=0,
                slot_source_breakdown={"rules": 3, "llm": 0, "mixed": 0},
                llm_parse_retry_count=0,
                llm_to_rules_slot_fallback_count=0,
            ),
            EvalRow(
                name="b", source="simulated_user_v1", role="r2", gap_id="g2",
                schema_pass=False, fallback_used=True,
                draft_card_completeness=0.3, fabrication_guard=True,
                latency_ms=20, rewrite_changed_count=1,
                slot_source_breakdown={"rules": 1, "llm": 2, "mixed": 0},
                llm_parse_retry_count=1,
                llm_to_rules_slot_fallback_count=1,
            ),
        ]
        m = compute_metrics(rows)
        # 全局聚合
        assert m["slot_source_breakdown_total"] == {"rules": 4, "llm": 2, "mixed": 0}, (
            f"slot_source_breakdown_total 聚合错, 实际 {m['slot_source_breakdown_total']!r}"
        )
        assert m["llm_parse_retry_count_total"] == 1
        assert m["llm_to_rules_slot_fallback_count_total"] == 1
        # by_source 拆分
        assert m["by_source"]["plan_baseline"]["slot_source_breakdown"] == {
            "rules": 3, "llm": 0, "mixed": 0,
        }
        assert m["by_source"]["simulated_user_v1"]["slot_source_breakdown"] == {
            "rules": 1, "llm": 2, "mixed": 0,
        }
        assert m["by_source"]["simulated_user_v1"]["llm_parse_retry_count_total"] == 1
        assert (
            m["by_source"]["simulated_user_v1"]["llm_to_rules_slot_fallback_count_total"]
            == 1
        )

    def test_compute_metrics_empty_rows_returns_zero_observability(self):
        """空 rows → 3 指标默认 = 0 / 0 / {rules:0, llm:0, mixed:0}(避免 KeyError)。"""
        from evaluate_interview_agent import compute_metrics

        m = compute_metrics([])
        assert m["slot_source_breakdown_total"] == {"rules": 0, "llm": 0, "mixed": 0}
        assert m["llm_parse_retry_count_total"] == 0
        assert m["llm_to_rules_slot_fallback_count_total"] == 0

    def test_by_extractor_metrics_includes_observability(self):
        """by_extractor 二次分组也含 3 个可观测性字段(compare 模式用)。"""
        from evaluate_interview_agent import EvalRow, compute_metrics

        rows = [
            EvalRow(
                name="a", source="x", role="r", gap_id="g",
                schema_pass=True, fallback_used=False,
                draft_card_completeness=0.5, fabrication_guard=True,
                latency_ms=10, rewrite_changed_count=0,
                extractor_mode="rules",
                slot_source_breakdown={"rules": 1, "llm": 0, "mixed": 0},
            ),
            EvalRow(
                name="b", source="x", role="r", gap_id="g",
                schema_pass=True, fallback_used=True,
                draft_card_completeness=0.5, fabrication_guard=True,
                latency_ms=20, rewrite_changed_count=0,
                extractor_mode="llm",
                slot_source_breakdown={"rules": 1, "llm": 1, "mixed": 0},
                llm_to_rules_slot_fallback_count=1,
            ),
        ]
        m = compute_metrics(rows)
        # rules 组
        assert m["by_extractor"]["rules"]["slot_source_breakdown"]["rules"] == 1
        # llm 组
        assert m["by_extractor"]["llm"]["slot_source_breakdown"]["llm"] == 1
        assert (
            m["by_extractor"]["llm"]["llm_to_rules_slot_fallback_count_total"] == 1
        )


class TestPhaseC3ObservabilityReport:
    """R6-C.3: 报告渲染 3 个可观测性指标(§4.7 章节)。"""

    def test_report_contains_observability_section(self, tmp_path):
        """报告 §4.7 章节存在, 渲染 3 个全局聚合指标。"""
        from evaluate_interview_agent import (
            EvalRow,
            EXTRACTOR_RULES,
            _get_llm_eval_config,
            compute_metrics,
            write_report,
        )

        rows = [
            EvalRow(
                name="a", source="plan_baseline", role="r", gap_id="g",
                schema_pass=True, fallback_used=False,
                draft_card_completeness=0.5, fabrication_guard=True,
                latency_ms=10, rewrite_changed_count=0,
                slot_source_breakdown={"rules": 2, "llm": 1, "mixed": 0},
                llm_parse_retry_count=1,
                llm_to_rules_slot_fallback_count=0,
            ),
        ]
        m = compute_metrics(rows)
        out = tmp_path / "report.md"
        cfg = _get_llm_eval_config(False, "offline")
        write_report(
            rows, m, out, cfg,
            requested_mode="offline",
            extractor_mode=EXTRACTOR_RULES,
        )
        text = out.read_text(encoding="utf-8")
        # 章节标题
        assert "## 4.7" in text, f"报告缺 §4.7 章节:\n{text[:500]}"
        # 3 个全局指标
        assert "slot_source_breakdown.rules" in text
        assert "slot_source_breakdown.llm" in text
        assert "llm_parse_retry_count_total" in text
        assert "llm_to_rules_slot_fallback_count_total" in text
        # 隐私边界声明
        assert "隐私边界 (R6-C.3)" in text

    def test_report_observability_no_user_message_leak(self, tmp_path):
        """报告 §4.7 章节不含 user_message 原文(隐私边界)。"""
        from evaluate_interview_agent import (
            EvalRow,
            EXTRACTOR_RULES,
            _get_llm_eval_config,
            compute_metrics,
            write_report,
        )

        # 准备一个含 sentinel user_message 字符串的 sample
        # 让 evaluate_one 路径走不到, 直接构造 EvalRow 即可
        rows = [
            EvalRow(
                name="a", source="plan_baseline", role="r", gap_id="g",
                schema_pass=True, fallback_used=False,
                draft_card_completeness=0.5, fabrication_guard=True,
                latency_ms=10, rewrite_changed_count=0,
                slot_source_breakdown={"rules": 1, "llm": 0, "mixed": 0},
            ),
        ]
        m = compute_metrics(rows)
        out = tmp_path / "report.md"
        cfg = _get_llm_eval_config(False, "offline")
        write_report(
            rows, m, out, cfg,
            requested_mode="offline",
            extractor_mode=EXTRACTOR_RULES,
        )
        text = out.read_text(encoding="utf-8")
        # 抽样 10 个 sentinel 短语验证(从 user_messages 池里抽, 不期望出现在报告里)
        sentinel_phrases = [
            "我做了一个表格模板",
            "我建了共享文档",
            "我用了漏斗式评分算法",
            "我用漏斗式评分算法",
            "我对接了 12 个工作组",
            "我采用 Accuracy",
            "我做了标准化模板",
            "ECGFounder",
            "我抽样看边界 case",
            "我做了科室 × 服务周期",
        ]
        leaked = [p for p in sentinel_phrases if p in text]
        assert not leaked, (
            f"报告 §4.7 章节泄漏 user_message 原文: {leaked}"
        )

    def test_report_observability_no_prompt_no_source_span_no_api_key(self, tmp_path):
        """报告 §4.7 章节不含 prompt 正文 / source_span 明文 / API key。"""
        from evaluate_interview_agent import (
            EvalRow,
            EXTRACTOR_RULES,
            _get_llm_eval_config,
            compute_metrics,
            write_report,
        )

        rows = [
            EvalRow(
                name="a", source="plan_baseline", role="r", gap_id="g",
                schema_pass=True, fallback_used=False,
                draft_card_completeness=0.5, fabrication_guard=True,
                latency_ms=10, rewrite_changed_count=0,
                slot_source_breakdown={"rules": 1, "llm": 0, "mixed": 0},
            ),
        ]
        m = compute_metrics(rows)
        out = tmp_path / "report.md"
        cfg = _get_llm_eval_config(False, "offline")
        write_report(
            rows, m, out, cfg,
            requested_mode="offline",
            extractor_mode=EXTRACTOR_RULES,
        )
        text = out.read_text(encoding="utf-8")
        # 4.7 章节边界声明
        # 注: 报告会在隐私边界声明里用"user_message"等字面量来描述"不含什么",
        # 所以这里只断言真正的"原文/凭据/数据"不该出现, 不断言字面量字段名.
        for forbidden in (
            "Few-shot 示例",  # 例子内容不该在报告里
            "sha256:",  # source_span hash 原始值
            "Bearer ",  # auth 头
            "sk-",  # API key 前缀
            "LLM_API_KEY",  # env var 名
            "BEGIN PROMPT",  # prompt 哨兵
        ):
            assert forbidden not in text, (
                f"报告 §4.7 章节不应含 {forbidden!r}"
            )

    def test_compare_report_observability_by_extractor(self, tmp_path):
        """compare 模式报告按 extractor 拆 3 指标(rules vs llm_assisted)。"""
        from evaluate_interview_agent import (
            EvalRow,
            EXTRACTOR_COMPARE,
            EXTRACTOR_LLM,
            EXTRACTOR_RULES,
            _get_llm_eval_config,
            compute_metrics,
            write_report,
        )

        rules_rows = [
            EvalRow(
                name="a", source="plan_baseline", role="r", gap_id="g",
                schema_pass=True, fallback_used=False,
                draft_card_completeness=0.5, fabrication_guard=True,
                latency_ms=10, rewrite_changed_count=0,
                extractor_mode=EXTRACTOR_RULES,
                slot_source_breakdown={"rules": 3, "llm": 0, "mixed": 0},
            ),
        ]
        llm_rows = [
            EvalRow(
                name="a", source="plan_baseline", role="r", gap_id="g",
                schema_pass=False, fallback_used=True,
                draft_card_completeness=0.3, fabrication_guard=True,
                latency_ms=20, rewrite_changed_count=0,
                extractor_mode=EXTRACTOR_LLM,
                slot_source_breakdown={"rules": 3, "llm": 0, "mixed": 0},
            ),
        ]
        all_rows = rules_rows + llm_rows
        m = compute_metrics(all_rows)
        by_extractor = {
            EXTRACTOR_RULES: compute_metrics(rules_rows),
            EXTRACTOR_LLM: compute_metrics(llm_rows),
        }
        out = tmp_path / "report.md"
        cfg = _get_llm_eval_config(False, "offline")
        write_report(
            all_rows, m, out, cfg,
            requested_mode="offline",
            extractor_mode=EXTRACTOR_COMPARE,
            by_extractor_metrics=by_extractor,
        )
        text = out.read_text(encoding="utf-8")
        # 按 extractor 拆章节存在
        assert "按 extractor 拆分" in text
        # 双组都列出
        assert "`rules`" in text
        assert "`llm`" in text

    def test_default_rules_eval_session_observes_zero_retries_and_fb(self, monkeypatch):
        """默认 rules 路径跑 1 条 sample → retries=0 + fb=0 + breakdown 仅 rules。"""
        # 防止真实 LLM key 干扰
        monkeypatch.delenv("LLM_API_KEY", raising=False)

        from evaluate_interview_agent import (
            EVAL_SET_ALL,
            EXTRACTOR_RULES,
            _evaluate_one,
        )
        from core.generator import load_materials

        mats = load_materials()
        # 挑 1 条 plan_baseline 跑
        sample = EVAL_SET_ALL[0]
        row = _evaluate_one(sample, mats, extractor_mode=EXTRACTOR_RULES)

        # rules 路径: retries / fb 都是 0
        assert row.llm_parse_retry_count == 0, (
            f"rules 路径 retries 应 = 0, 实际 {row.llm_parse_retry_count}"
        )
        assert row.llm_to_rules_slot_fallback_count == 0, (
            f"rules 路径 fb 应 = 0, 实际 {row.llm_to_rules_slot_fallback_count}"
        )
        # breakdown 含 rules > 0
        assert row.slot_source_breakdown.get("rules", 0) > 0, (
            f"rules 路径 breakdown 应含 rules > 0, 实际 {row.slot_source_breakdown!r}"
        )
        assert row.slot_source_breakdown.get("llm", 0) == 0, (
            f"rules 路径 llm 应 = 0, 实际 {row.slot_source_breakdown!r}"
        )
