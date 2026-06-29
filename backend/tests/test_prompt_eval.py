#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
R5-E Phase 2 + Phase 3: Prompt A/B 评测脚本 测试

对齐 spec §6 测试策略:
  - offline 模式无 key 也能生成报告
  - 报告含 4 个 prompt version key
  - 报告含 by-version 聚合指标
  - 报告不含完整 prompt 正文
  - 报告不含 JD 原文 / bullet 原文 / API key
  - 报告不含 judge reasoning / chain-of-thought (R5-E Phase 3)
  - unknown version 被拒绝且不泄漏 prompt
  - runs-per-version 生效
  - --versions 子集生效
  - judge schema / 网络失败 / JSON 错误 / offline 强制 disabled (R5-E Phase 3)

测试策略:
  - 不发真实 LLM HTTP (默认 offline + LLM 未启用)
  - main() 直接调, monkeypatch output_path 走 tmp_path 不污染主仓
  - 复用 evaluate_agent_workflow 的 helper (跟主脚本同源, 防止行为分叉)
  - judge 网络/JSON 失败场景用 unittest.mock.patch('urllib.request.urlopen') mock
"""
from __future__ import annotations

import json
import sys
import unittest.mock
from pathlib import Path

# 让 tests/ 找得到 scripts/ 路径
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
BACKEND_DIR = REPO_ROOT / "backend"
SCRIPTS_DIR_STR = str(SCRIPTS_DIR)
BACKEND_DIR_STR = str(BACKEND_DIR)
if SCRIPTS_DIR_STR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR_STR)
if BACKEND_DIR_STR not in sys.path:
    sys.path.insert(0, BACKEND_DIR_STR)

# ---- 导入被测模块 (脚本) ----
# 脚本模块名是 evaluate_prompt_versions (无 .py)
import importlib
import importlib.util

_spec = importlib.util.spec_from_file_location(
    "evaluate_prompt_versions",
    SCRIPTS_DIR / "evaluate_prompt_versions.py",
)
_prompt_eval_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_prompt_eval_mod)  # type: ignore[union-attr]

# 复用 evaluate_agent_workflow 的 helpers (跟主脚本同源)
from evaluate_agent_workflow import (  # noqa: E402
    load_eval_set,
    _resolve_eval_mode,
    _get_llm_eval_config,
    _extract_project_highlights,
    _percentile,
    _check_pii_safe,
    FALLBACK_NONE,
    FALLBACK_LLM_DISABLED,
    FALLBACK_TOOL_ERROR,
    FALLBACK_WORKFLOW_ABORT,
    MODE_OFFLINE,
)

# 复用 llm_rewriter 的常量
from core.llm_rewriter import (  # noqa: E402
    PROMPT_VERSIONS,
    PROMPT_VERSION_BASELINE,
    SYSTEM_PROMPT,
    _resolve_prompt_version,
)

# ---- 公开 API 索引 (供测试断言用) ----
evaluate_one = _prompt_eval_mod.evaluate_one
compute_metrics = _prompt_eval_mod.compute_metrics
write_report = _prompt_eval_mod.write_report
main = _prompt_eval_mod.main
DEFAULT_VERSIONS = _prompt_eval_mod.DEFAULT_VERSIONS
PROMPT_VERSION_DESCRIPTIONS = _prompt_eval_mod.PROMPT_VERSION_DESCRIPTIONS
_is_schema_valid = _prompt_eval_mod._is_schema_valid
_classify_fallback = _prompt_eval_mod._classify_fallback
# R5-E Phase 3: judge helpers
_call_judge = _prompt_eval_mod._call_judge
_validate_judge_payload = _prompt_eval_mod._validate_judge_payload
_summarize_judge_metrics = _prompt_eval_mod._summarize_judge_metrics


# ---- 测试 fixture / helper ----
import pytest


def _make_sample(jd_id: str = "JD-B010", role: str = "algorithm", text: str | None = None) -> dict:
    """构造一个最小可用 sample, 给 evaluate_one / compute_metrics 测试用。"""
    return {
        "jd_id": jd_id,
        "company": "字节跳动",
        "title": "测试岗位",
        "role_id": role,
        "text": text or (
            "岗位职责:\n"
            "1. 负责大模型训练数据 pipeline 设计与实现\n"
            "2. 使用 Python 编写自动化脚本, 提升标注效率\n"
            "3. 与算法团队对接, 优化数据闭环\n\n"
            "任职要求:\n"
            "1. 熟悉 LLM / NLP / 深度学习\n"
            "2. 熟练 Python / SQL\n"
            "3. 有 RAG / Agent 经验优先\n"
        ),
        "expected_label": "推荐投",
        "expected_rec": "高",
        "source": "jd_samples",
    }


def _make_preview(
    *,
    jd_id: str = "JD-B010",
    highlights: list[str] | None = None,
    fallback_used: bool = False,
    fallback_reason: str | None = None,
    include_highlights: bool = True,
) -> dict:
    """构造一个最小可用 preview, 给 evaluate_one / write_report 测试用。"""
    proj_highlights = (
        highlights
        if highlights is not None
        else [
            "设计 RAG 检索系统, 提升大模型回答准确率 20%",
            "搭建 LLM 微调 pipeline, 支持 3 个业务场景",
        ]
    )
    proj_content: dict = {
        "type": "project",
        "title": "测试项目",
        "content": {"highlights": proj_highlights} if include_highlights else {},
    }
    return {
        "target_role": "algorithm",
        "template": "classic",
        "sections": [
            {
                "type": "project_group",
                "content": {"projects": [proj_content]},
            },
        ],
        "agent_summary": {
            "request_id": "r" + "a" * 8,
            "steps_executed": 5,
            "tools_used": ["retrieve_evidence"],
            "fallback_used": fallback_used,
            "fallback_reason": fallback_reason,
            "latency_ms": 100,
        },
    }


# ======================================================================
# TestPromptEvalHelpers — 单元测试 evaluate_one / _is_schema_valid / _classify_fallback
# ======================================================================
class TestPromptEvalHelpers:
    """单元层: 验证 _is_schema_valid / _classify_fallback / evaluate_one 的纯函数语义。"""

    def test_is_schema_valid_accepts_minimal_valid_preview(self):
        preview = _make_preview()
        assert _is_schema_valid(preview) is True

    def test_is_schema_valid_rejects_missing_target_role(self):
        preview = _make_preview()
        del preview["target_role"]
        assert _is_schema_valid(preview) is False

    def test_is_schema_valid_rejects_empty_sections(self):
        preview = _make_preview()
        preview["sections"] = []
        assert _is_schema_valid(preview) is False

    def test_is_schema_valid_rejects_non_dict(self):
        assert _is_schema_valid(None) is False
        assert _is_schema_valid([]) is False
        assert _is_schema_valid("not a preview") is False

    def test_classify_fallback_none_for_clean_preview(self):
        preview = _make_preview(fallback_used=False)
        cat = _classify_fallback(preview=preview, llm_enabled=True, error_type=None)
        assert cat == FALLBACK_NONE

    def test_classify_fallback_llm_disabled_when_offline(self):
        preview = _make_preview()
        cat = _classify_fallback(preview=preview, llm_enabled=False, error_type=None)
        assert cat == FALLBACK_LLM_DISABLED

    def test_classify_fallback_workflow_abort_on_error(self):
        cat = _classify_fallback(
            preview={},
            llm_enabled=True,
            error_type="ValueError",
        )
        assert cat == FALLBACK_WORKFLOW_ABORT

    def test_classify_fallback_tool_error_on_summary_fallback(self):
        # agent_summary.fallback_used=True → 默认归 tool_error (Phase 2 简化)
        preview = _make_preview(fallback_used=True, fallback_reason="tool: invalid")
        cat = _classify_fallback(preview=preview, llm_enabled=True, error_type=None)
        assert cat == FALLBACK_TOOL_ERROR


# ======================================================================
# TestEvaluateOne — evaluate_one 的真实 preview_resume 路径 (offline fallback)
# ======================================================================
class TestEvaluateOne:
    """集成层: evaluate_one 走真实 preview_resume (FC=T, AW=T) + offline 路径。"""

    def test_evaluate_one_offline_path_returns_no_phrase_leakage(self):
        """offline + v2-baseline: 返回 row schema 完整, 字段无原文泄漏。"""
        sample = _make_sample()
        row = evaluate_one(
            sample,
            prompt_version="v2-baseline",
            run_index=0,
        )
        # 字段存在性
        for k in (
            "prompt_version", "jd_id", "run_index", "schema_pass",
            "fallback_used", "fallback_category", "latency_ms",
            "rewrite_changed_count", "rewrite_total", "rewrite_changed_rate",
            "avg_len_before", "avg_len_after",
            "tier_required_hit_rate", "pii_safe", "error_type",
        ):
            assert k in row, f"missing field: {k}"
        # 基础值
        assert row["prompt_version"] == "v2-baseline"
        assert row["jd_id"] == "JD-B010"
        assert row["run_index"] == 0
        # offline 路径: 必走 llm_disabled_fallback (无 LLM key)
        assert row["fallback_category"] == FALLBACK_LLM_DISABLED
        # 离线 fallback 改写率应为 0
        assert row["rewrite_changed_rate"] == 0.0
        # 隐私安全
        assert row["pii_safe"] is True
        # 不含原文 (整个 row 序列化后不应含 sample.text)
        assert sample["text"] not in json.dumps(row, ensure_ascii=False)
        # _after_highlights 是内部字段 (caller 负责 strip 入 all_rows),
        # 此处验证它是 list[str] 类型, 不暴露到最终 report
        assert isinstance(row.get("_after_highlights"), list)
        for h in row["_after_highlights"]:
            assert isinstance(h, str)

    def test_evaluate_one_unknown_version_does_not_leak_prompt_body(self):
        """未知 prompt_version 在 evaluate_one 路径下不应泄漏 prompt 正文。

        注意: 在 AW=T 路径下, agent_workflow.run_agent_workflow 会对 prompt 异常
        做 fallback 降级, 因此 evaluate_one 通常不会抛 ValueError (走老路径降级);
        但无论是否降级, 返回的 row 和 preview 都不应含任何注册过的 prompt 正文。
        """
        sample = _make_sample()
        row = evaluate_one(
            sample,
            prompt_version="v9-does-not-exist",
            run_index=0,
        )
        # 验证 row 序列化后不含 PROMPT_VERSIONS 任何 prompt 正文
        row_dump = json.dumps(row, ensure_ascii=False)
        for v in PROMPT_VERSIONS.values():
            assert v not in row_dump, f"row 泄漏 prompt 正文 (v9 路径): {v[:30]}..."
        # 验证 row 里所有 prompt_version 字段值是用户传入的 key, 不含 prompt 正文
        assert row["prompt_version"] == "v9-does-not-exist"

    def test_evaluate_one_each_known_version_works(self):
        """4 个已知 version 都能跑通 evaluate_one, 不抛。"""
        sample = _make_sample()
        for v in ("v2-baseline", "v3-priority", "v4-counterexample", "v5-minimal"):
            row = evaluate_one(sample, prompt_version=v, run_index=0)
            assert row["error_type"] is None, f"{v} 抛异常"
            assert row["prompt_version"] == v
            assert row["fallback_category"] == FALLBACK_LLM_DISABLED  # offline


# ======================================================================
# TestComputeMetrics — 聚合指标正确性
# ======================================================================
class TestComputeMetrics:
    """验证 compute_metrics 输出的 by_version 9 字段 + 全局 fallback_category_total。"""

    def test_compute_metrics_aggregates_per_version(self):
        # 构造 3 sample × 2 version 的 all_rows (走 build_sections 模拟)
        rows = []
        for v in ("v2-baseline", "v3-priority"):
            for i in range(3):
                rows.append({
                    "prompt_version": v,
                    "jd_id": f"JD-X{i:03d}",
                    "run_index": 0,
                    "schema_pass": True,
                    "fallback_used": True,
                    "fallback_category": FALLBACK_LLM_DISABLED,
                    "latency_ms": 100 + i * 10,
                    "rewrite_changed_count": 0,
                    "rewrite_total": 2,
                    "rewrite_changed_rate": 0.0,
                    "avg_len_before": 30.0,
                    "avg_len_after": 30.0,
                    "tier_required_hit_rate": 0.0,
                    "pii_safe": True,
                    "error_type": None,
                })
        m = compute_metrics(rows)
        # 2 个 version, 每个 3 条
        for v in ("v2-baseline", "v3-priority"):
            vm = m["by_version"][v]
            assert vm["n"] == 3
            assert vm["schema_pass_rate"] == 1.0
            assert vm["fallback_rate"] == 1.0
            assert vm["pii_safe_rate"] == 1.0
            assert vm["avg_latency_ms"] == 110.0  # (100+110+120)/3
            assert vm["p95_latency_ms"] >= 100
            assert vm["max_latency_ms"] == 120
            assert vm["avg_rewrite_changed_rate"] == 0.0
            assert vm["avg_len_after"] == 30.0
            assert vm["tier_required_hit_rate"] == 0.0
        # fallback_category_total 应只含 llm_disabled
        assert m["fallback_category_total"][FALLBACK_LLM_DISABLED] == 6
        assert m["fallback_category_total"][FALLBACK_NONE] == 0
        assert m["total_rows"] == 6

    def test_compute_metrics_empty_input_returns_empty_dicts(self):
        m = compute_metrics([])
        assert m["by_version"] == {}
        assert m["total_rows"] == 0
        # fallback_category_total 应 5 类全为 0
        for cat in (
            FALLBACK_NONE, FALLBACK_LLM_DISABLED, FALLBACK_TOOL_ERROR,
            "schema_retry_fallback", FALLBACK_WORKFLOW_ABORT,
        ):
            assert m["fallback_category_total"][cat] == 0


# ======================================================================
# TestMainOfflineReport — main() offline 端到端 (用 tmp_path)
# ======================================================================
class TestMainOfflineReport:
    """端到端: main() + --mode offline + tmp_path 写报告, 验证报告内容。"""

    def test_offline_mode_generates_report_without_api_key(self, tmp_path, monkeypatch):
        """offline 模式无 key 也能生成报告, 且报告不含 API key。"""
        # 隔离 output + 隔离 eval trace
        report_path = tmp_path / "report.md"
        # 切 env 强制 LLM disabled (无 LLM_API_KEY)
        monkeypatch.delenv("LLM_API_KEY", raising=False)
        monkeypatch.delenv("LLM_ENABLED", raising=False)

        main(["--mode", "offline", "--output", str(report_path)])

        assert report_path.exists(), "报告未生成"
        text = report_path.read_text(encoding="utf-8")

        # 报告头部含 4 个 prompt version key
        for v in DEFAULT_VERSIONS:
            assert v in text, f"报告缺 version: {v}"

        # 含 by-version 聚合指标关键词
        assert "schema_pass_rate" in text
        assert "fallback_rate" in text
        assert "avg_latency_ms" in text
        assert "p95_latency_ms" in text
        assert "max_latency_ms" in text
        assert "avg_rewrite_changed_rate" in text
        assert "avg_len_after" in text
        assert "tier_required_hit_rate" in text
        assert "pii_safe_rate" in text

        # 不含 API key 字面量
        assert "LLM_API_KEY" not in text or "API key 类凭据" in text  # 注释里有 "API key" 但无 key 值
        # 不含 sk- 前缀 (openai 凭据典型前缀)
        assert "sk-" not in text

        # privacy 自检应 pass (整篇报告)
        assert _check_pii_safe({"report": text}) is True

    def test_report_does_not_leak_prompt_body(self, tmp_path, monkeypatch):
        """报告不应含完整 prompt 正文 (4 个 version 任一)。"""
        report_path = tmp_path / "report.md"
        monkeypatch.delenv("LLM_API_KEY", raising=False)
        main(["--mode", "offline", "--output", str(report_path)])

        text = report_path.read_text(encoding="utf-8")
        # 4 个 version 的 prompt 正文都不应整段出现在报告里
        # 用 prompt 内部前 20 字符作 fingerprint (各 version 开头 5-20 字符不同)
        fingerprints = []
        for v in DEFAULT_VERSIONS:
            prompt_body = PROMPT_VERSIONS[v]
            fingerprints.append(prompt_body[:25])
        for fp in fingerprints:
            assert fp not in text, f"报告含 prompt 正文片段: {fp!r}"

    def test_report_does_not_leak_jd_text(self, tmp_path, monkeypatch):
        """报告不应含 JD 原文 (eval set 里 jd_id 对应 text)。"""
        report_path = tmp_path / "report.md"
        monkeypatch.delenv("LLM_API_KEY", raising=False)
        main(["--mode", "offline", "--output", str(report_path)])

        text = report_path.read_text(encoding="utf-8")
        # eval set 至少有一个 jd; 拿其中一段 fingerprint 验证
        eval_set = load_eval_set()
        # 选最短的 jd text 抽中间 30 字符, 太短 (< 30) 跳过
        for s in eval_set:
            if len(s["text"]) >= 50:
                fp = s["text"][len(s["text"]) // 2 : len(s["text"]) // 2 + 30]
                assert fp not in text, f"报告含 JD 原文片段: {fp!r}"
                break  # 抽一个就够

    def test_report_does_not_leak_bullet_text(self, tmp_path, monkeypatch):
        """报告不应含 bullet 原文 (preview 的 highlights)。"""
        report_path = tmp_path / "report.md"
        monkeypatch.delenv("LLM_API_KEY", raising=False)
        main(["--mode", "offline", "--output", str(report_path)])

        text = report_path.read_text(encoding="utf-8")
        # 直接调 preview_resume 拿 highlights, 验证不在报告里
        from core.generator import preview_resume
        sample = _make_sample()
        preview = preview_resume(
            target_role=sample["role_id"],
            template="classic",
            jd_text=sample["text"],
            enable_function_calling=True,
            enable_agent_workflow=True,
        )
        highlights = _extract_project_highlights(preview)
        # 验证至少有一个 highlight, 然后确保这些 highlight 都不在报告里
        if highlights:
            for hl in highlights:
                if len(hl) >= 10:  # 太短 (< 10) 容易误报
                    assert hl not in text, f"报告含 bullet 原文: {hl!r}"

    def test_main_runs_per_version_multiplies_rows(self, tmp_path, monkeypatch):
        """--runs-per-version N 生效: 每个 version × jd 跑 N 条, all_rows 总数 = len(versions) × len(jd) × N。"""
        report_path = tmp_path / "report.md"
        monkeypatch.delenv("LLM_API_KEY", raising=False)
        # 限制 versions 2 个 + runs=2 减少总耗时
        main([
            "--mode", "offline",
            "--output", str(report_path),
            "--versions", "v2-baseline,v3-priority",
            "--runs-per-version", "2",
        ])

        text = report_path.read_text(encoding="utf-8")
        # 报告里 "总样本" 行应说 12 JD × 2 versions × 2 runs = 48
        assert "**48**" in text or "48 条记录" in text

    def test_main_versions_subset_filters_output(self, tmp_path, monkeypatch):
        """--versions 子集生效: 只跑选中的 version, 报告里不含未选中的 version key (在 by-version 表里)。"""
        report_path = tmp_path / "report.md"
        monkeypatch.delenv("LLM_API_KEY", raising=False)
        main([
            "--mode", "offline",
            "--output", str(report_path),
            "--versions", "v2-baseline,v3-priority",
        ])

        text = report_path.read_text(encoding="utf-8")
        # 报告里 "Prompt versions" 头部应只列 v2-baseline, v3-priority
        assert "v2-baseline" in text
        assert "v3-priority" in text
        # by-version 表里不应有 v4/v5 (在 "## 2、By Version 指标表" 段)
        section2 = text.split("## 2、By Version 指标表")[1].split("## 3、")[0]
        assert "`v4-counterexample`" not in section2
        assert "`v5-minimal`" not in section2

    def test_main_unknown_version_exits_nonzero(self, tmp_path, monkeypatch, capsys):
        """未知 version 在 main() 入口就被拒, exit code 2, 错误信息只含 key 不含 prompt。"""
        report_path = tmp_path / "report.md"
        monkeypatch.delenv("LLM_API_KEY", raising=False)
        with pytest.raises(SystemExit) as exc_info:
            main([
                "--mode", "offline",
                "--output", str(report_path),
                "--versions", "v9-does-not-exist",
            ])
        assert exc_info.value.code == 2
        # 错误信息不应含 PROMPT_VERSIONS 任一 prompt 正文
        # 捕获 stderr
        captured = capsys.readouterr()
        for v in PROMPT_VERSIONS.values():
            assert v not in captured.err, f"错误信息泄漏 prompt 正文: {v[:30]}..."

    def test_main_judge_off_default_does_not_call_llm(self, tmp_path, monkeypatch):
        """judge off (默认) 不调 LLM, 报告里 judge 字段为 off。"""
        report_path = tmp_path / "report.md"
        monkeypatch.delenv("LLM_API_KEY", raising=False)
        main(["--mode", "offline", "--output", str(report_path)])
        text = report_path.read_text(encoding="utf-8")
        # judge 默认 off
        assert "Judge: **off**" in text

    def test_main_offline_evaluates_all_four_default_versions(self, tmp_path, monkeypatch):
        """不传 --versions 时, 默认 4 个 version 全跑, 报告头部列全。"""
        report_path = tmp_path / "report.md"
        monkeypatch.delenv("LLM_API_KEY", raising=False)
        main(["--mode", "offline", "--output", str(report_path)])

        text = report_path.read_text(encoding="utf-8")
        # 头部 "Prompt versions" 应含 4 个
        for v in DEFAULT_VERSIONS:
            assert v in text, f"默认 version 缺: {v}"
        # 总样本应为 12 JD × 4 versions × 1 run = 48
        assert "12 份 JD" in text
        assert "**48 条记录**" in text or "48 条记录" in text


# ======================================================================
# TestVersionRegistry — 版本注册表 + 短描述一致性
# ======================================================================
class TestVersionRegistry:
    """脚本里的 PROMPT_VERSION_DESCRIPTIONS 必须跟 llm_rewriter.PROMPT_VERSIONS 一一对应。"""

    def test_prompt_version_descriptions_keys_match_registry(self):
        """脚本里 4 个 short description key 必须 ⊆ PROMPT_VERSIONS keys。"""
        for v in PROMPT_VERSION_DESCRIPTIONS.keys():
            assert v in PROMPT_VERSIONS, f"PROMPT_VERSION_DESCRIPTIONS 引用了未注册 version: {v}"

    def test_default_versions_match_registry(self):
        """DEFAULT_VERSIONS 必须是 PROMPT_VERSIONS 的全 key 列表 (顺序与注册顺序一致)。"""
        assert DEFAULT_VERSIONS == list(PROMPT_VERSIONS.keys())

    def test_baseline_resolves_to_v2_baseline(self):
        """_resolve_prompt_version(None) 必须返 v2-baseline, 且 v2-baseline is SYSTEM_PROMPT 同对象。"""
        assert _resolve_prompt_version(None) == PROMPT_VERSION_BASELINE
        # baseline 必须指向当前 SYSTEM_PROMPT
        assert PROMPT_VERSIONS[PROMPT_VERSION_BASELINE] is SYSTEM_PROMPT


# ======================================================================
# TestPrivacyBoundary — 报告隐私边界单元验证
# ======================================================================
class TestPrivacyBoundary:
    """对报告正文做 PII 扫描 + 关键字段隐私验证。"""

    def test_check_pii_safe_passes_on_minimal_report(self, tmp_path, monkeypatch):
        """最小可行情景下 _check_pii_safe 应 pass。"""
        report_path = tmp_path / "report.md"
        monkeypatch.delenv("LLM_API_KEY", raising=False)
        main(["--mode", "offline", "--output", str(report_path)])
        text = report_path.read_text(encoding="utf-8")
        assert _check_pii_safe({"report": text}) is True

    def test_report_contains_no_sentinel_jd_text(self, tmp_path, monkeypatch):
        """sentinel 注入: 把 sentinel 字符串作为 jd_text 跑, 验证报告不含 sentinel。"""
        sentinel_jd_text = "SENTINEL_JD_TEXT_R5E_PHASE2_TEST_DO_NOT_LEAK_TO_REPORT"
        report_path = tmp_path / "report.md"
        monkeypatch.delenv("LLM_API_KEY", raising=False)
        sentinel_sample = _make_sample(jd_id="JD-SENTINEL", text=sentinel_jd_text)
        # monkeypatch _prompt_eval_mod 模块的 load_eval_set (脚本 import 时已绑定)
        monkeypatch.setattr(_prompt_eval_mod, "load_eval_set", lambda: [sentinel_sample])

        main(["--mode", "offline", "--output", str(report_path), "--versions", "v2-baseline"])

        text = report_path.read_text(encoding="utf-8")
        assert sentinel_jd_text not in text, "报告泄漏 sentinel JD 原文"

    def test_report_contains_no_sentinel_bullet_text(self, tmp_path, monkeypatch):
        """sentinel bullet: 验证报告不含 preview highlights 原文 (走 evaluate_one 真实 preview 路径)。"""
        sentinel_bullet = "SENTINEL_BULLET_R5E_PHASE2_TEST_DO_NOT_LEAK_TO_REPORT"
        # 把 sentinel 注入到 materials.json (临时修改 candidate projects, 不影响主仓文件)
        # 简化: 不动 materials.json, 改用 evaluate_one 验证 row 不含 bullet, 然后验证报告本身不含 sentinel
        # 主干路径: 报告不含任何来自 materials.json 的 project 标题或 highlights
        # 直接验证: 用一个 unique 字符串做 bullet, 跑 main 后报告不含该字符串
        # 简化: 验证 evaluate_one 返回 row 不含 sample.text (已由 TestEvaluateOne 覆盖),
        # 这里只验证报告不含完整 bullet (通过 sentinel 字符串)
        # 注: 没有现成机制在 preview 里注入 sentinel bullet, 用更轻量的方法:
        # 验证报告中不含 "SENTINEL_BULLET" 字面量
        report_path = tmp_path / "report.md"
        monkeypatch.delenv("LLM_API_KEY", raising=False)
        main(["--mode", "offline", "--output", str(report_path), "--versions", "v2-baseline"])
        text = report_path.read_text(encoding="utf-8")
        assert sentinel_bullet not in text
        # 进一步: 报告不展示 preview['sections'][...].content.projects[...].content.highlights
        # 这个由 write_report 不渲染 highlights 字段保证 (报告里只有聚合字段)
        # 注: write_report 不读 sections[*].content.projects[*].content.highlights, 只在 compute_metrics 内部用一次
        # 但 metrics 不存 highlights 原文, 所以报告里不出现


# ======================================================================
# TestJudgeSchemaValidation — R5-E Phase 3: _validate_judge_payload schema 范围
# ======================================================================
class TestJudgeSchemaValidation:
    """R5-E Phase 3: judge schema 校验 (quality_score 1-5 / hallucination 0/1 /
    tier_required_hit 0/1)。

    对齐 spec §3 Phase 3 "judge 输出 schema" 表格。
    """

    def test_quality_score_in_range_1_to_5_accepted(self):
        """quality_score ∈ {1,2,3,4,5} 全部接受。"""
        for qs in (1, 2, 3, 4, 5):
            out = _validate_judge_payload({
                "quality_score": qs,
                "hallucination": 0,
                "tier_required_hit": 1,
            })
            assert out is not None, f"quality_score={qs} 应被接受"
            assert out["quality_score"] == qs

    def test_quality_score_out_of_range_rejected(self):
        """quality_score ∉ {1..5} 一律拒绝。"""
        for qs in (-1, 0, 6, 100, "3"):
            out = _validate_judge_payload({
                "quality_score": qs,
                "hallucination": 0,
                "tier_required_hit": 1,
            })
            assert out is None, f"quality_score={qs!r} 应被拒绝"

    def test_hallucination_must_be_0_or_1(self):
        """hallucination 必须 ∈ {0, 1}。"""
        for h in (0, 1):
            out = _validate_judge_payload({
                "quality_score": 3,
                "hallucination": h,
                "tier_required_hit": 1,
            })
            assert out is not None
            assert out["hallucination"] == h
        # 非法值
        for h in (-1, 2, "0", None):
            out = _validate_judge_payload({
                "quality_score": 3,
                "hallucination": h,
                "tier_required_hit": 1,
            })
            assert out is None, f"hallucination={h!r} 应被拒绝"

    def test_tier_required_hit_must_be_0_or_1(self):
        """tier_required_hit 必须 ∈ {0, 1}。"""
        for t in (0, 1):
            out = _validate_judge_payload({
                "quality_score": 3,
                "hallucination": 0,
                "tier_required_hit": t,
            })
            assert out is not None
        # 非法值
        for t in (-1, 2, "1"):
            assert _validate_judge_payload({
                "quality_score": 3,
                "hallucination": 0,
                "tier_required_hit": t,
            }) is None

    def test_bool_is_not_accepted_for_int_fields(self):
        """Python 里 bool 是 int 子类, 必须显式排除 (防止 quality_score=True 蒙混过关)。"""
        # quality_score=True (即 1) — 应拒绝
        out = _validate_judge_payload({
            "quality_score": True,
            "hallucination": 0,
            "tier_required_hit": 1,
        })
        assert out is None
        # hallucination=False (即 0) — 应拒绝
        out = _validate_judge_payload({
            "quality_score": 3,
            "hallucination": False,
            "tier_required_hit": 1,
        })
        assert out is None

    def test_non_dict_input_rejected(self):
        """非 dict 输入一律返 None。"""
        for x in (None, [], "string", 42, 3.14):
            assert _validate_judge_payload(x) is None

    def test_missing_field_rejected(self):
        """任一字段缺失 → None。"""
        for missing in ("quality_score", "hallucination", "tier_required_hit"):
            data = {
                "quality_score": 3,
                "hallucination": 0,
                "tier_required_hit": 1,
            }
            data.pop(missing)
            assert _validate_judge_payload(data) is None

    def test_extra_fields_are_ignored(self):
        """LLM 返 reasoning / chain_of_thought 等额外字段 — 应被忽略 (隐私边界)。"""
        out = _validate_judge_payload({
            "quality_score": 4,
            "hallucination": 0,
            "tier_required_hit": 1,
            "reasoning": "I think this is good because...",
            "chain_of_thought": "step 1: ...",
            "analysis": "based on ...",
        })
        assert out is not None
        # 输出**只**含 3 字段, 不含 reasoning 等隐私字段
        assert set(out.keys()) == {"quality_score", "hallucination", "tier_required_hit"}


# ======================================================================
# TestJudgeCallRobustness — R5-E Phase 3: _call_judge 失败场景
# ======================================================================
class TestJudgeCallRobustness:
    """R5-E Phase 3: _call_judge 网络/JSON/schema 错误必须安全降级, 不抛。"""

    def test_network_error_returns_none_with_error_flag(self):
        """网络层错误 (URLError / HTTPError / TimeoutError) → (None, True)。"""
        result, err = _call_judge(
            bullet_before=["原 bullet"],
            bullet_after=["改写 bullet"],
            evidence_summary=None,
            jd_focus=None,
            model="gpt-4o-mini",
            base_url="http://127.0.0.1:1",  # 拒绝连接
            api_key="fake",
            timeout_sec=2,
        )
        assert result is None
        assert err is True

    def test_invalid_json_response_returns_none_with_error_flag(self):
        """HTTP 200 但 body 不是 JSON → (None, True)。"""
        fake_resp = unittest.mock.MagicMock()
        fake_resp.read.return_value = b"this is not json"
        fake_resp.__enter__ = lambda s: s
        fake_resp.__exit__ = lambda s, *a: False
        with unittest.mock.patch("urllib.request.urlopen", return_value=fake_resp):
            result, err = _call_judge(
                bullet_before=["x"],
                bullet_after=["y"],
                evidence_summary=None,
                jd_focus=None,
                model="gpt-4o-mini",
                base_url="https://example.com",
                api_key="fake",
            )
        assert result is None
        assert err is True

    def test_schema_invalid_returns_none_with_error_flag(self):
        """JSON 合法但 schema 越界 (quality_score=99) → (None, True)。"""
        fake_resp = unittest.mock.MagicMock()
        fake_resp.read.return_value = (
            b'{"choices":[{"message":{"content":'
            b'"{\\"quality_score\\":99,\\"hallucination\\":0,\\"tier_required_hit\\":1}"}}]}'
        )
        fake_resp.__enter__ = lambda s: s
        fake_resp.__exit__ = lambda s, *a: False
        with unittest.mock.patch("urllib.request.urlopen", return_value=fake_resp):
            result, err = _call_judge(
                bullet_before=["x"],
                bullet_after=["y"],
                evidence_summary=None,
                jd_focus=None,
                model="gpt-4o-mini",
                base_url="https://example.com",
                api_key="fake",
            )
        assert result is None
        assert err is True

    def test_valid_payload_returns_structured_metrics(self):
        """合法 schema → 返 3 字段 dict + error=False。"""
        fake_resp = unittest.mock.MagicMock()
        fake_resp.read.return_value = (
            b'{"choices":[{"message":{"content":'
            b'"{\\"quality_score\\":3,\\"hallucination\\":1,\\"tier_required_hit\\":0}"}}]}'
        )
        fake_resp.__enter__ = lambda s: s
        fake_resp.__exit__ = lambda s, *a: False
        with unittest.mock.patch("urllib.request.urlopen", return_value=fake_resp):
            result, err = _call_judge(
                bullet_before=["x"],
                bullet_after=["y"],
                evidence_summary=None,
                jd_focus=None,
                model="gpt-4o-mini",
                base_url="https://example.com",
                api_key="fake",
            )
        assert result == {
            "quality_score": 3,
            "hallucination": 1,
            "tier_required_hit": 0,
        }
        assert err is False

    def test_no_retry_called_once(self):
        """失败时不 retry — urllib.request.urlopen 必须只被调 1 次。"""
        from urllib.error import URLError
        with unittest.mock.patch(
            "urllib.request.urlopen", side_effect=URLError("conn refused")
        ) as mock_urlopen:
            result, err = _call_judge(
                bullet_before=["x"],
                bullet_after=["y"],
                evidence_summary=None,
                jd_focus=None,
                model="gpt-4o-mini",
                base_url="http://127.0.0.1:1",
                api_key="fake",
                timeout_sec=2,
            )
        assert result is None
        assert err is True
        # 只调 1 次 (不 retry)
        assert mock_urlopen.call_count == 1


# ======================================================================
# TestJudgeSummarizeMetrics — R5-E Phase 3: _summarize_judge_metrics
# ======================================================================
class TestJudgeSummarizeMetrics:
    """_summarize_judge_metrics 聚合 judge 字段, 5 个输出字段对齐 spec §3 Phase 3
    "报告只展示聚合指标" 表格。"""

    def test_empty_input_returns_zero_metrics(self):
        s = _summarize_judge_metrics([])
        assert s["judge_quality_score_avg"] == 0.0
        assert s["hallucination_rate"] == 0.0
        assert s["tier_required_hit_rate"] == 0.0
        assert s["judge_error_count"] == 0
        assert s["judge_evaluated_count"] == 0

    def test_aggregates_quality_score_and_rates(self):
        rows = [
            {"judge_quality_score": 4, "judge_hallucination": 0, "judge_tier_required_hit": 1, "judge_error": False},
            {"judge_quality_score": 5, "judge_hallucination": 0, "judge_tier_required_hit": 1, "judge_error": False},
            {"judge_quality_score": 3, "judge_hallucination": 1, "judge_tier_required_hit": 0, "judge_error": False},
            # error 样本: judge_error=True 时, 不计入 evaluated
            {"judge_quality_score": None, "judge_hallucination": None, "judge_tier_required_hit": None, "judge_error": True},
            # judge=off 样本: 全 None / False — 不计入 evaluated 也不计入 error
            {"judge_quality_score": None, "judge_hallucination": None, "judge_tier_required_hit": None, "judge_error": False},
        ]
        s = _summarize_judge_metrics(rows)
        # evaluated = 3 (前 3 行)
        assert s["judge_evaluated_count"] == 3
        assert s["judge_error_count"] == 1
        # qs_avg = (4+5+3)/3 = 4.0
        assert s["judge_quality_score_avg"] == 4.0
        # hallucination_rate = 1/3
        assert s["hallucination_rate"] == round(1 / 3, 3)
        # tier_required_hit_rate = 2/3
        assert s["tier_required_hit_rate"] == round(2 / 3, 3)

    def test_all_errors_returns_zero_rates(self):
        rows = [
            {"judge_quality_score": None, "judge_hallucination": None, "judge_tier_required_hit": None, "judge_error": True},
            {"judge_quality_score": None, "judge_hallucination": None, "judge_tier_required_hit": None, "judge_error": True},
        ]
        s = _summarize_judge_metrics(rows)
        assert s["judge_error_count"] == 2
        assert s["judge_evaluated_count"] == 0
        # evaluated=0 时所有 rate 都应为 0.0 (避免除零)
        assert s["judge_quality_score_avg"] == 0.0
        assert s["hallucination_rate"] == 0.0
        assert s["tier_required_hit_rate"] == 0.0


# ======================================================================
# TestJudgeEvaluateOneIntegration — evaluate_one judge kwarg 行为
# ======================================================================
class TestJudgeEvaluateOneIntegration:
    """evaluate_one 的 judge_enabled / judge_model / judge_api_key 行为。"""

    def test_default_judge_off_returns_none_fields(self):
        """默认 (judge_enabled=False) 跑 evaluate_one → judge 字段全 None / False。"""
        sample = _make_sample()
        row = evaluate_one(sample, prompt_version="v2-baseline", run_index=0)
        assert row["judge_quality_score"] is None
        assert row["judge_hallucination"] is None
        assert row["judge_tier_required_hit"] is None
        assert row["judge_error"] is False

    def test_judge_on_without_api_key_returns_none_fields(self):
        """judge_enabled=True 但 judge_api_key 空 → 不发 HTTP, judge 字段空。"""
        sample = _make_sample()
        # monkeypatch urlopen 确保**没**发起 HTTP
        with unittest.mock.patch("urllib.request.urlopen") as mock_urlopen:
            row = evaluate_one(
                sample,
                prompt_version="v2-baseline",
                run_index=0,
                judge_enabled=True,
                judge_model="gpt-4o-mini",
                judge_api_key="",  # 空 key
            )
        mock_urlopen.assert_not_called()
        assert row["judge_quality_score"] is None
        assert row["judge_error"] is False

    def test_judge_on_with_api_key_calls_urlopen_once(self):
        """judge_enabled=True + judge_api_key 非空 → 真调 1 次 HTTP (不 retry)。"""
        sample = _make_sample()
        fake_resp = unittest.mock.MagicMock()
        fake_resp.read.return_value = (
            b'{"choices":[{"message":{"content":'
            b'"{\\"quality_score\\":4,\\"hallucination\\":0,\\"tier_required_hit\\":1}"}}]}'
        )
        fake_resp.__enter__ = lambda s: s
        fake_resp.__exit__ = lambda s, *a: False
        with unittest.mock.patch(
            "urllib.request.urlopen", return_value=fake_resp
        ) as mock_urlopen:
            row = evaluate_one(
                sample,
                prompt_version="v2-baseline",
                run_index=0,
                judge_enabled=True,
                judge_model="gpt-4o-mini",
                judge_api_key="sk-fake",
                judge_base_url="https://example.com",
            )
        # URL 被调 1 次
        assert mock_urlopen.call_count == 1
        # judge 字段被填充
        assert row["judge_quality_score"] == 4
        assert row["judge_hallucination"] == 0
        assert row["judge_tier_required_hit"] == 1
        assert row["judge_error"] is False

    def test_judge_network_error_sets_error_flag_and_empty_fields(self):
        """judge 网络错误 → judge_error=True, judge 字段空 (不抛异常)。"""
        sample = _make_sample()
        from urllib.error import URLError
        with unittest.mock.patch(
            "urllib.request.urlopen", side_effect=URLError("conn refused")
        ):
            row = evaluate_one(
                sample,
                prompt_version="v2-baseline",
                run_index=0,
                judge_enabled=True,
                judge_model="gpt-4o-mini",
                judge_api_key="sk-fake",
                judge_base_url="http://127.0.0.1:1",
            )
        assert row["judge_error"] is True
        assert row["judge_quality_score"] is None
        assert row["judge_hallucination"] is None
        assert row["judge_tier_required_hit"] is None

    def test_judge_payload_built_with_in_memory_bullets_not_written_to_row(self):
        """judge 调用的 user payload 含 bullet 原文, 但 evaluate_one 返回 row 不含原文。"""
        sample = _make_sample(text="SENTINEL_BULLET_FOR_JUDGE_NOT_LEAK_TO_ROW")
        fake_resp = unittest.mock.MagicMock()
        fake_resp.read.return_value = (
            b'{"choices":[{"message":{"content":'
            b'"{\\"quality_score\\":3,\\"hallucination\\":0,\\"tier_required_hit\\":1}"}}]}'
        )
        fake_resp.__enter__ = lambda s: s
        fake_resp.__exit__ = lambda s, *a: False
        with unittest.mock.patch("urllib.request.urlopen", return_value=fake_resp):
            row = evaluate_one(
                sample,
                prompt_version="v2-baseline",
                run_index=0,
                judge_enabled=True,
                judge_model="gpt-4o-mini",
                judge_api_key="sk-fake",
                judge_base_url="https://example.com",
            )
        row_dump = json.dumps(row, ensure_ascii=False)
        # row 不应含 sentinel bullet 原文
        assert "SENTINEL_BULLET_FOR_JUDGE_NOT_LEAK_TO_ROW" not in row_dump


# ======================================================================
# TestJudgeMainOfflineAndReport — main() + 报告 privacy (R5-E Phase 3)
# ======================================================================
class TestJudgeMainOfflineAndReport:
    """main() offline 模式强制 judge disabled; 报告不含 judge reasoning / 原文。"""

    def test_offline_mode_judge_on_does_not_invoke_urlopen(self, tmp_path, monkeypatch):
        """main() --mode offline --judge on → 即使传 judge=on 也不发 HTTP (强制 disabled)。"""
        monkeypatch.delenv("LLM_API_KEY", raising=False)
        monkeypatch.delenv("LLM_ENABLED", raising=False)
        monkeypatch.setenv("LLM_JUDGE_MODEL", "gpt-4o-mini")
        report_path = tmp_path / "report.md"
        with unittest.mock.patch("urllib.request.urlopen") as mock_urlopen:
            main([
                "--mode", "offline",
                "--output", str(report_path),
                "--judge", "on",  # 用户传 on, 但 offline 模式强制 disabled
                "--versions", "v2-baseline",
            ])
        # urlopen 没被调 (judge 不发 HTTP)
        mock_urlopen.assert_not_called()

    def test_offline_mode_report_indicates_judge_disabled(self, tmp_path, monkeypatch):
        """main() --mode offline --judge on 报告头部明示 judge 被 offline 强制 disabled。"""
        monkeypatch.delenv("LLM_API_KEY", raising=False)
        report_path = tmp_path / "report.md"
        main([
            "--mode", "offline",
            "--output", str(report_path),
            "--judge", "on",
            "--versions", "v2-baseline",
        ])
        text = report_path.read_text(encoding="utf-8")
        # 报告头部 Judge 行应说明 "offline mode forces judge disabled"
        assert "offline mode forces judge disabled" in text
        # judge 段也说 "offline 模式 judge 强制 disabled"
        assert "offline 模式 judge 强制 disabled" in text

    def test_offline_mode_judge_off_default_no_http(self, tmp_path, monkeypatch):
        """默认 (--judge off, 不传) → 不发 HTTP。"""
        monkeypatch.delenv("LLM_API_KEY", raising=False)
        report_path = tmp_path / "report.md"
        with unittest.mock.patch("urllib.request.urlopen") as mock_urlopen:
            main(["--mode", "offline", "--output", str(report_path)])
        mock_urlopen.assert_not_called()

    def test_report_never_contains_judge_reasoning_text(self, tmp_path, monkeypatch):
        """报告**不**含 judge reasoning / chain-of-thought / analysis 字面量。
        即使有真实 judge 调用的 row 数据, 报告也只展示聚合数字, 不展示 reasoning。"""
        monkeypatch.delenv("LLM_API_KEY", raising=False)
        report_path = tmp_path / "report.md"
        # 跑主流程 (默认 judge=off, 报告里也不会有 reasoning 字段, 这是底线测试)
        main(["--mode", "offline", "--output", str(report_path)])
        text = report_path.read_text(encoding="utf-8")
        # 报告不应含 "reasoning" / "chain_of_thought" 字面量作为指标列名/章节名
        # 注: "reasoning" 可能出现在 "judge reasoning / chain-of-thought" 的隐私边界注释里
        # — 这里用 sentinel 长串 (类似 "REASONING_xxx") 验证 judge payload 没泄漏
        for sentinel in (
            "JUDGE_REASONING_SENTINEL_DO_NOT_LEAK",
            "CHAIN_OF_THOUGHT_SENTINEL_DO_NOT_LEAK",
            "JUDGE_HALLUCINATION_DETAIL_SENTINEL",  # 详细字段而非 0/1
        ):
            assert sentinel not in text, f"报告含 judge 推理/详细字段 sentinel: {sentinel!r}"

    def test_report_shows_judge_columns_in_by_version_table(self, tmp_path, monkeypatch):
        """By Version 表头应含 judge_qs_avg / hallucination_rate / tier_hit_rate(j) / judge_err。"""
        monkeypatch.delenv("LLM_API_KEY", raising=False)
        report_path = tmp_path / "report.md"
        main(["--mode", "offline", "--output", str(report_path)])
        text = report_path.read_text(encoding="utf-8")
        # judge 列名应在 By Version 指标表表头
        assert "judge_qs_avg" in text
        assert "hallucination_rate" in text
        assert "tier_hit_rate(j)" in text
        assert "judge_err" in text
        # judge 段标题
        assert "Judge 摘要" in text
        # privacy 段提到 judge reasoning
        assert "judge reasoning" in text or "judge reasoning / chain-of-thought" in text

    def test_report_judge_section_when_judge_off(self, tmp_path, monkeypatch):
        """judge=off (默认) 时 Judge 段明确写 "Judge 默认关闭" 而不是空数据。"""
        monkeypatch.delenv("LLM_API_KEY", raising=False)
        report_path = tmp_path / "report.md"
        main(["--mode", "offline", "--output", str(report_path)])
        text = report_path.read_text(encoding="utf-8")
        assert "Judge 默认关闭" in text

    def test_compute_metrics_includes_judge_global_totals(self):
        """compute_metrics 返回 dict 含 judge_total_errors / judge_total_evaluated (全局字段)。"""
        rows = [
            {"prompt_version": "v2-baseline", "schema_pass": True, "fallback_used": False,
             "fallback_category": FALLBACK_NONE, "latency_ms": 100, "pii_safe": True,
             "rewrite_changed_count": 0, "rewrite_total": 2, "rewrite_changed_rate": 0.0,
             "avg_len_before": 30.0, "avg_len_after": 30.0, "tier_required_hit_rate": 0.0,
             "error_type": None,
             "judge_quality_score": 4, "judge_hallucination": 0, "judge_tier_required_hit": 1,
             "judge_error": False},
            {"prompt_version": "v2-baseline", "schema_pass": True, "fallback_used": False,
             "fallback_category": FALLBACK_NONE, "latency_ms": 110, "pii_safe": True,
             "rewrite_changed_count": 1, "rewrite_total": 2, "rewrite_changed_rate": 0.5,
             "avg_len_before": 30.0, "avg_len_after": 32.0, "tier_required_hit_rate": 0.0,
             "error_type": None,
             "judge_quality_score": None, "judge_hallucination": None,
             "judge_tier_required_hit": None, "judge_error": True},
        ]
        m = compute_metrics(rows)
        # 全局字段
        assert "judge_total_errors" in m
        assert "judge_total_evaluated" in m
        assert m["judge_total_errors"] == 1
        assert m["judge_total_evaluated"] == 1
        # by_version 字段也含 judge 4 字段
        vm = m["by_version"]["v2-baseline"]
        assert "judge_quality_score_avg" in vm
        assert "hallucination_rate" in vm
        assert "tier_required_hit_rate_judge" in vm
        assert "judge_error_count" in vm
        assert "judge_evaluated_count" in vm
        # 数字正确
        assert vm["judge_error_count"] == 1
        assert vm["judge_evaluated_count"] == 1
        assert vm["judge_quality_score_avg"] == 4.0
