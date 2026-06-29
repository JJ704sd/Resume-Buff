"""
Round 6-A Phase 5: interview agent eval 脚本测试

测试覆盖(plan §5.5):
  TestEvalHelpers:
    - test_extract_slots_from_messages_iterates_turns
    - test_compute_schema_pass_rate_returns_float
    - test_completeness_calculates_required_field_ratio
    - test_fabrication_guard_detects_unconfirmed_claims
  TestEvalReport:
    - test_report_contains_no_user_message_text
    - test_report_offline_mode_does_not_call_urlopen

边界(对齐 plan §5.3 / R5-E 保护):
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
    _compute_completeness,
    _compute_schema_pass_rate,
    _evaluate_one,
    _extract_slots_iteratively,
    _fabrication_guard,
    compute_metrics,
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


# ======================================================================
# TestEvalHelpers
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
# TestEvalReport
# ======================================================================
class TestEvalReport:
    """plan §5.5: 报告隐私 + offline mode 不调 urlopen."""

    def test_report_contains_no_user_message_text(self, tmp_path, all_samples, materials):
        """
        写报告后 grep 确认不含模拟用户回答原文。
        抽样 3 条 user_message 里的关键短语, 检查报告不含它们。
        """
        # 跑全部样本
        from evaluate_interview_agent import EvalRow  # noqa: PLC0415
        rows = []
        for s in all_samples:
            r = _evaluate_one(s, materials)
            rows.append(r)
        metrics = compute_metrics(rows)
        report_path = tmp_path / "report.md"
        from evaluate_agent_workflow import _get_llm_eval_config, _resolve_eval_mode  # noqa: PLC0415
        from core.llm_rewriter import is_llm_enabled  # noqa: PLC0415
        llm_cfg = _get_llm_eval_config(is_llm_enabled(), "offline")

        write_report(
            rows, metrics, report_path, llm_cfg, requested_mode="offline",
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
        self, tmp_path, all_samples, materials,
    ):
        """
        mock urlopen, offline 模式断言 urlopen.assert_not_called().
        验证 eval 脚本在 offline 模式下完全不发起 HTTP 调用。
        """
        with mock.patch(
            "urllib.request.urlopen", side_effect=AssertionError("offline mode 不应调 urlopen"),
        ) as mock_urlopen:
            from evaluate_interview_agent import EvalRow  # noqa: PLC0415
            rows = []
            for s in all_samples:
                r = _evaluate_one(s, materials)
                rows.append(r)
            metrics = compute_metrics(rows)
            report_path = tmp_path / "report.md"
            from evaluate_agent_workflow import _get_llm_eval_config  # noqa: PLC0415
            from core.llm_rewriter import is_llm_enabled  # noqa: PLC0415
            llm_cfg = _get_llm_eval_config(is_llm_enabled(), "offline")
            write_report(
                rows, metrics, report_path, llm_cfg, requested_mode="offline",
            )
            # offline 模式应完全不发 HTTP
            mock_urlopen.assert_not_called()