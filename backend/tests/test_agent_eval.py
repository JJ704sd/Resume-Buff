"""
R5-A Phase 4: Agent eval 离线评测脚本测试

锁点(11 case):
  TestEvalSetLoading (3 case):
    1.  eval set 加载成功, >= 8 份 (jd_samples 8 份非公告型)
    2.  每份 sample 含必需字段 (jd_id / role_id / text / expected_label)
    3.  公告型 JD 不进 eval set

  TestSingleEvaluation (4 case):
    4.  evaluate_one 返回 dict 含必需指标 (11 字段)
    5.  schema_pass=True for baseline 路径 (LLM disabled)
    6.  pii_safe=True for placeholder whitelist 路径
    7.  latency_ms >= 0 且为整数

  TestPiiScanner (2 case):
    8.  PII scanner 命中真实手机号/email/学校名 → 标不安全
    9.  PII scanner 对 placeholder (13800000000 / your_email@example.com) → 标安全

  TestPrivacyGuarantee (2 case):
    10. 报告不含 11 位真实手机号
    11. 报告不含真实邮箱模式

策略:
  - 不污染全局状态(用 monkeypatch)
  - 直接 import scripts/evaluate_agent_workflow (避免 import side effect 跑 main)
"""
import re
import sys
from pathlib import Path

# 把 scripts/ 加到 sys.path 让 evaluate_agent_workflow 可导
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import evaluate_agent_workflow as eval_mod  # noqa: E402


# =========================================================================
# TestEvalSetLoading
# =========================================================================
class TestEvalSetLoading:
    """R5-A Phase 4: eval set 加载稳定性"""

    def test_eval_set_loads_with_minimum_8_jds(self):
        """eval set 至少 8 份 JD (jd_samples 8 份非公告型)"""
        eval_set = eval_mod.load_eval_set()
        assert len(eval_set) >= 8, (
            f"eval set 至少 8 份, 实际 {len(eval_set)}"
        )
        # 应含 jd_samples 来源
        sources = {s["source"] for s in eval_set}
        assert "jd_samples" in sources, "eval set 应含 jd_samples 来源"

    def test_eval_set_samples_have_required_fields(self):
        """每份 sample 必含 jd_id / role_id / text / expected_label"""
        eval_set = eval_mod.load_eval_set()
        required_keys = {"jd_id", "role_id", "text", "expected_label"}
        for s in eval_set:
            missing = required_keys - set(s.keys())
            assert not missing, (
                f"sample {s.get('jd_id', '?')} 缺字段: {missing}"
            )
            assert isinstance(s["text"], str) and len(s["text"]) > 0, (
                f"sample {s.get('jd_id', '?')} text 为空"
            )

    def test_eval_set_excludes_announcement_samples(self):
        """jd_samples 公告型 2 份(bytedance_2026_announcement / alibaba_2027_intern_post)不进 eval set"""
        eval_set = eval_mod.load_eval_set()
        jd_ids = {s["jd_id"] for s in eval_set}
        assert "bytedance_2026_announcement" not in jd_ids, (
            "公告型 bytedance_2026_announcement 不应进 eval set"
        )
        assert "alibaba_2027_intern_post" not in jd_ids, (
            "公告型 alibaba_2027_intern_post 不应进 eval set"
        )


# =========================================================================
# TestSingleEvaluation
# =========================================================================
class TestSingleEvaluation:
    """R5-A Phase 4: 单样本 × 单组合评测"""

    def test_evaluate_one_returns_required_metric_fields(self):
        """evaluate_one 返回 dict 含必需指标"""
        eval_set = eval_mod.load_eval_set()
        sample = eval_set[0]  # 第一份
        row = eval_mod.evaluate_one(
            sample,
            enable_function_calling=False,
            enable_agent_workflow=False,
        )
        required_keys = {
            "jd_id", "role_id", "expected_label",
            "score", "recommendation", "schema_pass",
            "fallback_used", "tools_used", "latency_ms",
            "error_type", "pii_safe", "source",
        }
        missing = required_keys - set(row.keys())
        assert not missing, f"evaluate_one 返回缺字段: {missing}"

    def test_baseline_path_schema_pass_true(self):
        """baseline 路径 (FC=F, AW=F) 在无 LLM key 时 schema_pass=True"""
        eval_set = eval_mod.load_eval_set()
        sample = eval_set[0]
        row = eval_mod.evaluate_one(
            sample,
            enable_function_calling=False,
            enable_agent_workflow=False,
        )
        assert row["schema_pass"] is True, (
            f"baseline 应 schema_pass=True, 实际 {row['schema_pass']}, "
            f"error_type={row.get('error_type')}"
        )

    def test_placeholder_whitelist_pii_safe(self):
        """公开脱敏版 placeholder (13800000000 / your_email@example.com) 走 PII 白名单"""
        # 模拟 preview dict 含 placeholder
        preview_with_placeholder = {
            "target_role": "algorithm",
            "template": "classic",
            "sections": [
                {
                    "type": "header",
                    "title": "header",
                    "content": {
                        "name": "示例同学",
                        "contact": "13800000000  |  your_email@example.com  |  现居 深圳市",
                    },
                },
            ],
        }
        safe = eval_mod._check_pii_safe(preview_with_placeholder)
        assert safe is True, f"placeholder 应被白名单, 实际 safe={safe}"

    def test_latency_is_non_negative_int(self):
        """latency_ms >= 0 且为整数"""
        eval_set = eval_mod.load_eval_set()
        sample = eval_set[0]
        row = eval_mod.evaluate_one(
            sample,
            enable_function_calling=False,
            enable_agent_workflow=False,
        )
        assert isinstance(row["latency_ms"], int), (
            f"latency_ms 应为 int, 实际 {type(row['latency_ms'])}"
        )
        assert row["latency_ms"] >= 0, f"latency_ms 应 >= 0, 实际 {row['latency_ms']}"


# =========================================================================
# TestPiiScanner
# =========================================================================
class TestPiiScanner:
    """R5-A Phase 4: PII scanner 准确性"""

    def test_real_pii_patterns_flagged_unsafe(self):
        """真实手机号 / email / 学校名 → 标不安全"""
        # 真实手机号
        assert eval_mod._check_pii_safe("联系我 13912345678") is False, \
            "11 位真实手机号应被标不安全"
        # 真实 email
        assert eval_mod._check_pii_safe("邮箱 zhangsan@gmail.com") is False, \
            "真实 email 应被标不安全"
        # 国内常见学校名
        assert eval_mod._check_pii_safe("毕业于 清华大学 计算机系") is False, \
            "学校名 '清华' 应被标不安全"

    def test_placeholder_patterns_ignored(self):
        """placeholder (13800000000 / your_email@example.com) → 标安全"""
        # 公开脱敏版 placeholder
        assert eval_mod._check_pii_safe("电话 13800000000") is True, \
            "placeholder 13800000000 应被白名单, 标安全"
        assert eval_mod._check_pii_safe("邮箱 your_email@example.com") is True, \
            "placeholder your_email@example.com 应被白名单, 标安全"


# =========================================================================
# TestPrivacyGuarantee
# =========================================================================
class TestPrivacyGuarantee:
    """R5-A Phase 4: 报告产出隐私边界"""

    def test_report_no_real_mobile(self):
        """eval 脚本生成的 markdown 报告不含 11 位真实手机号"""
        # 跑完整流程, 看输出文件
        eval_mod.OUTPUT_REPORT = REPO_ROOT / "AI岗位JD库_test_no_real_mobile.md"
        try:
            eval_mod.main()
            content = (REPO_ROOT / "AI岗位JD库_test_no_real_mobile.md").read_text(
                encoding="utf-8"
            )
            # 11 位真实手机号不应出现 (placeholder 13800000000 是脱敏版, 不算)
            real_mobile_re = re.compile(r"\b1[3-9]\d{9}\b")
            # 抠掉 placeholder
            stripped = content.replace("13800000000", "")
            hits = real_mobile_re.findall(stripped)
            assert not hits, f"报告含 11 位真实手机号: {hits}"
        finally:
            # 清理临时报告
            tmp_report = REPO_ROOT / "AI岗位JD库_test_no_real_mobile.md"
            if tmp_report.exists():
                tmp_report.unlink()
            # 恢复原始 OUTPUT_REPORT 路径
            eval_mod.OUTPUT_REPORT = REPO_ROOT / "AI岗位JD库_agent_eval报告.md"

    def test_report_no_real_email(self):
        """eval 脚本生成的 markdown 报告不含真实 email (placeholder 例外)"""
        eval_mod.OUTPUT_REPORT = REPO_ROOT / "AI岗位JD库_test_no_real_email.md"
        try:
            eval_mod.main()
            content = (REPO_ROOT / "AI岗位JD库_test_no_real_email.md").read_text(
                encoding="utf-8"
            )
            email_re = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
            # 抠掉 placeholder
            stripped = content.replace("your_email@example.com", "")
            hits = email_re.findall(stripped)
            assert not hits, f"报告含真实 email: {hits}"
        finally:
            tmp_report = REPO_ROOT / "AI岗位JD库_test_no_real_email.md"
            if tmp_report.exists():
                tmp_report.unlink()
            eval_mod.OUTPUT_REPORT = REPO_ROOT / "AI岗位JD库_agent_eval报告.md"


# =========================================================================
# R5-C Phase 1: eval request_id 精确关联 + fallback taxonomy
# =========================================================================
class TestEvalUsesAgentSummaryRequestId:
    """R5-C Phase 1: eval 优先使用 preview['agent_summary']['request_id'],
    不再通过 JSONL 最后一条 trace 反推主 request"""

    def test_extract_request_id_from_preview_returns_summary_value(self):
        """preview 含 agent_summary.request_id 时, 直接返回它"""
        preview = {
            "target_role": "algorithm",
            "sections": [{"type": "header", "title": "header", "content": {}}],
            "agent_summary": {
                "request_id": "rabcdef12",
                "tools_used": ["retrieve_evidence"],
                "fallback_used": False,
            },
        }
        rid = eval_mod._extract_request_id_from_preview(preview)
        assert rid == "rabcdef12", (
            f"应直接从 agent_summary 提取 request_id, 实际 {rid}"
        )

    def test_extract_request_id_returns_none_for_old_path(self):
        """老路径 preview 不含 agent_summary → 返 None (调用方应转用 JSONL 反查)"""
        preview = {
            "target_role": "algorithm",
            "sections": [{"type": "header", "title": "header", "content": {}}],
            # 无 agent_summary (enable_agent_workflow=False 路径)
        }
        rid = eval_mod._extract_request_id_from_preview(preview)
        assert rid is None, (
            f"老路径无 agent_summary 应返 None, 实际 {rid}"
        )

    def test_extract_request_id_returns_none_for_malformed_preview(self):
        """malformed preview (非 dict 或 summary 非 dict) → 返 None 不抛"""
        assert eval_mod._extract_request_id_from_preview(None) is None
        assert eval_mod._extract_request_id_from_preview("not a dict") is None
        assert eval_mod._extract_request_id_from_preview([]) is None
        # agent_summary 不是 dict
        assert eval_mod._extract_request_id_from_preview(
            {"agent_summary": "broken"}
        ) is None
        # request_id 不是 str
        assert eval_mod._extract_request_id_from_preview(
            {"agent_summary": {"request_id": 12345}}
        ) is None


class TestEvalToolsUsedPrefersAgentSummary:
    """R5-C Phase 1: tools_used 优先来自 preview['agent_summary']['tools_used'],
    而不是从 JSONL trace 反查"""

    def test_extract_tools_used_returns_summary_value(self):
        preview = {
            "agent_summary": {
                "tools_used": ["retrieve_evidence", "parse_jd"],
            },
        }
        tools = eval_mod._extract_tools_used_from_preview(preview)
        assert tools == ["retrieve_evidence", "parse_jd"], (
            f"应直接从 agent_summary 提取 tools_used, 实际 {tools}"
        )

    def test_extract_tools_used_returns_none_for_old_path(self):
        preview = {"target_role": "algorithm"}  # 无 agent_summary
        assert eval_mod._extract_tools_used_from_preview(preview) is None

    def test_extract_tools_used_filters_non_strings(self):
        """tools_used list 里非 str 元素应被过滤(防御性)"""
        preview = {"agent_summary": {"tools_used": ["a", 1, None, "b", ""]}}
        tools = eval_mod._extract_tools_used_from_preview(preview)
        # 空字符串也保留 — 跟原始 list 顺序一致; 仅过滤非 str
        assert tools == ["a", "b", ""]

    def test_extract_tools_used_handles_empty_list(self):
        """空 list 也算有效(无工具) — 跟 None 区分"""
        preview = {"agent_summary": {"tools_used": []}}
        tools = eval_mod._extract_tools_used_from_preview(preview)
        assert tools == []

    def test_short_request_id_truncates_to_4_chars(self):
        """request_id 应截短到 4 字符用于报告(完整 9 字符不入报告)"""
        assert eval_mod._short_request_id("rabcdef12") == "rabc"
        assert eval_mod._short_request_id("ra") == "ra"  # 短于 4 字符原样保留
        assert eval_mod._short_request_id(None) is None
        assert eval_mod._short_request_id("") is None


class TestEvalFallbackCategoryNone:
    """R5-C Phase 1: fallback_category='none'"""

    def test_fallback_category_none_when_no_fallback_and_llm_enabled(self):
        """workflow 跑通 + LLM 启用 + 无 fallback → 'none'"""
        preview = {
            "agent_summary": {
                "request_id": "rxxx",
                "fallback_used": False,
                "fallback_reason": None,
                "tools_used": ["retrieve_evidence"],
            },
        }
        cat = eval_mod._classify_fallback_category(
            preview=preview,
            llm_enabled=True,
            enable_function_calling=True,
            enable_agent_workflow=True,
            error_type=None,
        )
        assert cat == "none", f"无 fallback 应返 'none', 实际 {cat!r}"

    def test_fallback_category_none_baseline_path(self):
        """baseline 老路径 (AW=F, FC=F, LLM off 但 AW=F 不需要 LLM) → 'none'"""
        preview = {"target_role": "algorithm"}  # 老路径, 无 agent_summary
        cat = eval_mod._classify_fallback_category(
            preview=preview,
            llm_enabled=False,
            enable_function_calling=False,
            enable_agent_workflow=False,
            error_type=None,
        )
        assert cat == "none"

    def test_fallback_category_llm_off_baseline(self):
        """baseline (AW=F, FC=F) + LLM off → 'none' (baseline 不需要 LLM)"""
        cat = eval_mod._classify_fallback_category(
            preview={"target_role": "algorithm"},
            llm_enabled=False,
            enable_function_calling=False,
            enable_agent_workflow=False,
            error_type=None,
        )
        assert cat == "none"


class TestEvalFallbackCategoryLlmDisabled:
    """R5-C Phase 1: fallback_category='llm_disabled_fallback'"""

    def test_fallback_category_llm_disabled_when_aw_needs_llm(self):
        """LLM 关闭 + AW=T (workflow 路径需要 LLM 改写) → 'llm_disabled_fallback'"""
        preview = {
            "agent_summary": {
                "request_id": "rxxx",
                "fallback_used": False,  # workflow 走原文 fallback 但 agent_summary 没标 fallback_used=True
                "tools_used": ["retrieve_evidence"],
            },
        }
        cat = eval_mod._classify_fallback_category(
            preview=preview,
            llm_enabled=False,
            enable_function_calling=False,
            enable_agent_workflow=True,
            error_type=None,
        )
        assert cat == "llm_disabled_fallback"

    def test_fallback_category_llm_disabled_when_fc_needs_llm(self):
        """LLM 关闭 + FC=T (FC 路径需要 LLM tools) → 'llm_disabled_fallback'"""
        preview = {"agent_summary": {"fallback_used": False, "tools_used": []}}
        cat = eval_mod._classify_fallback_category(
            preview=preview,
            llm_enabled=False,
            enable_function_calling=True,
            enable_agent_workflow=False,
            error_type=None,
        )
        assert cat == "llm_disabled_fallback"

    def test_fallback_category_tool_error_when_summary_marks_fallback(self):
        """fallback_used=True + fallback_reason 含 'tool_error' → 'tool_error_fallback'"""
        preview = {
            "agent_summary": {
                "fallback_used": True,
                "fallback_reason": "match_score:TOOL_ARGS_INVALID",
                "tools_used": [],
            },
        }
        cat = eval_mod._classify_fallback_category(
            preview=preview,
            llm_enabled=True,
            enable_function_calling=True,
            enable_agent_workflow=True,
            error_type=None,
        )
        assert cat == "tool_error_fallback"

    def test_fallback_category_workflow_abort_when_exception(self):
        """evaluate_one 抛 exception → 'workflow_abort_fallback'"""
        cat = eval_mod._classify_fallback_category(
            preview={"target_role": "algorithm"},
            llm_enabled=True,
            enable_function_calling=False,
            enable_agent_workflow=False,
            error_type="ValueError",  # preview_resume 抛
        )
        assert cat == "workflow_abort_fallback"


class TestEvalReportNoRawRequestIdLeak:
    """R5-C Phase 1: 报告不含完整 request_id 全文(只短串)"""

    def test_report_no_raw_request_id_leak(self):
        """完整跑 main() 后, 报告不含完整 request_id (r + 8 hex)"""
        eval_mod.OUTPUT_REPORT = REPO_ROOT / "AI岗位JD库_test_no_raw_rid.md"
        try:
            eval_mod.main()
            content = (REPO_ROOT / "AI岗位JD库_test_no_raw_rid.md").read_text(
                encoding="utf-8"
            )
            # R5-A closeout 约定的 request_id 格式: r + 8 位 hex (9 字符)
            rid_full_re = re.compile(r"\br[0-9a-f]{8}\b")
            hits = rid_full_re.findall(content)
            assert not hits, (
                f"报告含完整 request_id 全文 (r + 8 hex): {hits}; "
                f"应只用前 4 字符"
            )
        finally:
            tmp_report = REPO_ROOT / "AI岗位JD库_test_no_raw_rid.md"
            if tmp_report.exists():
                tmp_report.unlink()
            eval_mod.OUTPUT_REPORT = REPO_ROOT / "AI岗位JD库_agent_eval报告.md"

    def test_report_includes_fallback_category_field(self):
        """报告里 row 列表应新增 'fallback_category' 列"""
        eval_mod.OUTPUT_REPORT = REPO_ROOT / "AI岗位JD库_test_fb_category.md"
        try:
            eval_mod.main()
            content = (REPO_ROOT / "AI岗位JD库_test_fb_category.md").read_text(
                encoding="utf-8"
            )
            # 报告应展示 fallback_category 列名 + 至少一个分类值
            assert "fallback_category" in content, (
                "报告应含 'fallback_category' 字段(列名或章节)"
            )
        finally:
            tmp_report = REPO_ROOT / "AI岗位JD库_test_fb_category.md"
            if tmp_report.exists():
                tmp_report.unlink()
            eval_mod.OUTPUT_REPORT = REPO_ROOT / "AI岗位JD库_agent_eval报告.md"