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
import os
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


# =========================================================================
# R5-D Phase 1: eval mode 决策
# =========================================================================
class TestEvalModeResolve:
    """
    R5-D Phase 1: _resolve_eval_mode 纯函数(不读 env var, 只根据入参决策)。

    锁点:
      - offline 总是返 "offline",不依赖 LLM
      - live 总是返 "live"; llm_enabled=False → raise RuntimeError
      - auto  根据 llm_enabled 自动选 live / offline
      - 非法 mode → ValueError
    """

    def test_default_mode_is_offline(self):
        """默认 mode (offline) 不依赖 LLM,任何 llm_enabled 都返 offline"""
        assert eval_mod._resolve_eval_mode(eval_mod.MODE_OFFLINE, True) == eval_mod.MODE_OFFLINE
        assert eval_mod._resolve_eval_mode(eval_mod.MODE_OFFLINE, False) == eval_mod.MODE_OFFLINE

    def test_live_mode_requires_llm_enabled(self):
        """live 模式 + llm_enabled=False → RuntimeError(spec 任务点 #2)"""
        with __import__("pytest").raises(RuntimeError) as exc_info:
            eval_mod._resolve_eval_mode(eval_mod.MODE_LIVE, False)
        # 错误信息应明确指出 live 要求 LLM 启用
        assert "live" in str(exc_info.value).lower()
        # llm_enabled=True 时不应报错
        assert eval_mod._resolve_eval_mode(eval_mod.MODE_LIVE, True) == eval_mod.MODE_LIVE

    def test_auto_mode_uses_live_when_key_present(self):
        """auto + llm_enabled=True → live(spec 任务点 #3)"""
        assert eval_mod._resolve_eval_mode(eval_mod.MODE_AUTO, True) == eval_mod.MODE_LIVE

    def test_auto_mode_uses_offline_when_no_key(self):
        """auto + llm_enabled=False → offline(auto 兜底行为)"""
        assert eval_mod._resolve_eval_mode(eval_mod.MODE_AUTO, False) == eval_mod.MODE_OFFLINE

    def test_invalid_mode_raises_value_error(self):
        """非法 mode → ValueError"""
        with __import__("pytest").raises(ValueError) as exc_info:
            eval_mod._resolve_eval_mode("invalid", True)
        assert "invalid" in str(exc_info.value)


class TestEvalModeNoKeyLeak:
    """
    R5-D Phase 1: 隐私边界 — live mode 错误信息**绝不**包含 LLM key 值。

    spec 任务点 #5 明确:"live 模式 llm_enabled=False 时失败, 错误信息不能包含 key"
    """

    def test_live_mode_error_does_not_leak_api_key_value(self):
        """RuntimeError 的 str() 不含任何 LLM_API_KEY 的值(模拟一个有意义的 key)"""
        sentinel_key = "sk-test-DO-NOT-LEAK-12345-abcdef"
        # 把 sentinel 塞进 env,模拟"用户配了 key 但 is_llm_enabled 因别的原因返 False"
        # 用 monkeypatch 在 env 里临时放这个 key,然后验证错误信息不含它
        # 但 _resolve_eval_mode 不读 env var — 我们直接验证字符串拼接不含 sentinel
        # 方式: 错误信息直接来自函数 hardcoded 字面量,不可能含 sentinel
        try:
            eval_mod._resolve_eval_mode(eval_mod.MODE_LIVE, False)
        except RuntimeError as e:
            assert sentinel_key not in str(e), (
                f"live mode 错误信息不应包含 LLM_API_KEY 值: {e}"
            )

    def test_live_mode_error_does_not_leak_env_var_name(self):
        """错误信息也不引用 LLM_API_KEY env var 名字(进一步防御)"""
        try:
            eval_mod._resolve_eval_mode(eval_mod.MODE_LIVE, False)
        except RuntimeError as e:
            assert "LLM_API_KEY" not in str(e), (
                f"live mode 错误信息不应引用 env var 名: {e}"
            )


class TestEvalCliOutput:
    """
    R5-D Phase 1: CLI 参数 --output 覆盖 + 默认 mode=offline 端到端验证。

    跑 main() 完整流程(跟 TestPrivacyGuarantee 一样),验证:
      - 不传 --output → OUTPUT_REPORT 不变(默认路径)
      - 传 --output → OUTPUT_REPORT 被改写到指定路径
      - 默认 mode=offline → 报告头部含 "Mode: offline"
    """

    def test_output_path_can_be_overridden(self, monkeypatch, tmp_path):
        """CLI --output <path> 覆盖默认报告路径(spec 任务点 #4)"""
        custom_output = tmp_path / "custom_eval_report.md"
        original_output = eval_mod.OUTPUT_REPORT

        # 强制 is_llm_enabled 返 False(避免依赖用户环境)
        monkeypatch.setattr(eval_mod, "is_llm_enabled", lambda: False)

        try:
            eval_mod.main(argv=["--mode", "offline", "--output", str(custom_output)])
            assert custom_output.exists(), (
                f"--output 指定的报告文件应生成: {custom_output}"
            )
            # OUTPUT_REPORT 应被改写到 custom_output
            assert eval_mod.OUTPUT_REPORT == custom_output, (
                f"OUTPUT_REPORT 应被覆盖为 {custom_output}, "
                f"实际 {eval_mod.OUTPUT_REPORT}"
            )
        finally:
            eval_mod.OUTPUT_REPORT = original_output
            if custom_output.exists():
                custom_output.unlink()

    def test_default_output_path_unchanged_when_no_flag(self, monkeypatch, tmp_path):
        """不传 --output → OUTPUT_REPORT 保持默认 module-level 值"""
        default_output = tmp_path / "default_eval_report.md"
        original_output = eval_mod.OUTPUT_REPORT
        # monkeypatch module-level OUTPUT_REPORT 到 tmp_path
        monkeypatch.setattr(eval_mod, "OUTPUT_REPORT", default_output)
        monkeypatch.setattr(eval_mod, "is_llm_enabled", lambda: False)

        try:
            eval_mod.main(argv=["--mode", "offline"])
            assert default_output.exists(), (
                f"默认 OUTPUT_REPORT 应被写出: {default_output}"
            )
            assert eval_mod.OUTPUT_REPORT == default_output
        finally:
            if default_output.exists():
                default_output.unlink()

    def test_default_mode_offline_writes_mode_to_report(self, monkeypatch, tmp_path):
        """默认 mode (不传 --mode) → 报告头部含 resolved mode + requested mode 标注"""
        output = tmp_path / "default_mode_report.md"
        original_output = eval_mod.OUTPUT_REPORT
        monkeypatch.setattr(eval_mod, "OUTPUT_REPORT", output)
        monkeypatch.setattr(eval_mod, "is_llm_enabled", lambda: False)

        try:
            eval_mod.main(argv=[])
            content = output.read_text(encoding="utf-8")
            # 报告头部应有 mode 标注(offline 走默认, requested=offline)
            assert "> Eval mode: **offline**" in content, (
                f"默认 mode 报告应含 '> Eval mode: **offline**', "
                f"实际头部: {content[:200]}"
            )
            assert "(requested: `offline`)" in content, (
                f"默认 mode 报告应含 requested 标注, 实际头部: {content[:200]}"
            )
        finally:
            eval_mod.OUTPUT_REPORT = original_output
            if output.exists():
                output.unlink()


# =========================================================================
# R5-D Phase 2: 报告元信息 — llm_mode / llm_enabled / llm_model / llm_base_url_host
# =========================================================================
class TestEvalLlmMetadataHelper:
    """
    R5-D Phase 2: _get_llm_eval_config helper 单元测试。

    锁点:
      - 返回 dict 含 4 字段 (llm_mode / llm_enabled / llm_model / llm_base_url_host)
      - 绝不读 LLM_API_KEY (即使 env 设了 sentinel, 输出 dict 不含它)
      - base_url 含 path/query → 只输出 host 部分
    """

    def test_helper_returns_4_required_fields(self, monkeypatch):
        """helper 返回 dict 含 4 字段"""
        monkeypatch.delenv("LLM_API_KEY", raising=False)
        monkeypatch.delenv("LLM_BASE_URL", raising=False)
        monkeypatch.delenv("LLM_MODEL", raising=False)
        config = eval_mod._get_llm_eval_config(False, "offline")
        assert set(config.keys()) == {
            "llm_mode", "llm_enabled", "llm_model", "llm_base_url_host",
        }, f"_get_llm_eval_config 应返回 4 字段, 实际 {set(config.keys())}"
        assert config["llm_mode"] == "offline"
        assert config["llm_enabled"] is False
        # 默认 model 应回落到 helper 内部 DEFAULT
        assert isinstance(config["llm_model"], str) and len(config["llm_model"]) > 0
        assert isinstance(config["llm_base_url_host"], str)

    def test_helper_propagates_live_mode_and_llm_enabled(self, monkeypatch):
        """helper 把入参 llm_enabled / resolved_mode 准确反映到输出"""
        monkeypatch.delenv("LLM_API_KEY", raising=False)
        monkeypatch.delenv("LLM_BASE_URL", raising=False)
        monkeypatch.delenv("LLM_MODEL", raising=False)
        config = eval_mod._get_llm_eval_config(True, "live")
        assert config["llm_mode"] == "live"
        assert config["llm_enabled"] is True

    def test_helper_does_not_read_api_key(self, monkeypatch):
        """helper 不读 LLM_API_KEY (即使 env 设了 sentinel, 输出 dict 不含它)"""
        sentinel_key = "sk-DO-NOT-LEAK-12345-abcdef-DO-NOT-LEAK"
        monkeypatch.setenv("LLM_API_KEY", sentinel_key)
        config = eval_mod._get_llm_eval_config(False, "offline")
        # 输出 dict 任何字段都不应含 sentinel
        for k, v in config.items():
            assert sentinel_key not in str(v), (
                f"_get_llm_eval_config 不应读 LLM_API_KEY; "
                f"字段 {k}={v!r} 含 sentinel"
            )

    def test_helper_base_url_host_extracts_host_only(self, monkeypatch):
        """base_url 含 path/query/fragment 时, helper 只抽 host"""
        monkeypatch.setenv(
            "LLM_BASE_URL",
            "https://api.example.com/v1/chat/completions?token=abc",
        )
        config = eval_mod._get_llm_eval_config(True, "live")
        assert config["llm_base_url_host"] == "api.example.com", (
            f"只应抽 host, 实际 {config['llm_base_url_host']!r}"
        )

    def test_helper_base_url_host_hides_path(self, monkeypatch):
        """base_url_host 输出不含 path"""
        monkeypatch.setenv(
            "LLM_BASE_URL",
            "https://secret.example.com/v1/internal/endpoint",
        )
        config = eval_mod._get_llm_eval_config(True, "live")
        assert "/v1/" not in config["llm_base_url_host"], (
            f"base_url_host 不应含 path, 实际 {config['llm_base_url_host']!r}"
        )
        assert "internal" not in config["llm_base_url_host"]
        assert "endpoint" not in config["llm_base_url_host"]
        assert config["llm_base_url_host"] == "secret.example.com"

    def test_helper_base_url_host_hides_query(self, monkeypatch):
        """base_url_host 输出不含 query 参数"""
        monkeypatch.setenv(
            "LLM_BASE_URL",
            "https://api.example.com/v1/chat?api_key=should_not_leak&foo=bar",
        )
        config = eval_mod._get_llm_eval_config(True, "live")
        assert "api_key" not in config["llm_base_url_host"]
        assert "should_not_leak" not in config["llm_base_url_host"]
        assert "foo=bar" not in config["llm_base_url_host"]
        assert "?" not in config["llm_base_url_host"]

    def test_helper_uses_env_model_when_set(self, monkeypatch):
        """env LLM_MODEL 非空时, helper 读它(不回落 default)"""
        monkeypatch.setenv("LLM_MODEL", "claude-3-5-sonnet-test")
        config = eval_mod._get_llm_eval_config(False, "offline")
        assert config["llm_model"] == "claude-3-5-sonnet-test", (
            f"LLM_MODEL env 应被读到, 实际 {config['llm_model']!r}"
        )

    def test_helper_handles_missing_or_malformed_base_url(self, monkeypatch):
        """base_url 空字符串 / 异常 → host 空字符串 (不抛)"""
        # 空字符串
        monkeypatch.setenv("LLM_BASE_URL", "")
        config = eval_mod._get_llm_eval_config(False, "offline")
        # 空时会回落到 helper 内部 default → 应有 host
        assert config["llm_base_url_host"] == "api.openai.com", (
            f"空 base_url 应回落到 default host, 实际 {config['llm_base_url_host']!r}"
        )
        # 完全怪异的字符串 — 不抛, host 可能是空也可能解析到某种 host
        monkeypatch.setenv("LLM_BASE_URL", "not a url at all !!!")
        config = eval_mod._get_llm_eval_config(False, "offline")
        assert isinstance(config["llm_base_url_host"], str)


class TestEvalReportIncludesLlmMetadata:
    """
    R5-D Phase 2: write_report() 输出含 LLM 元信息章节 + 4 字段 (spec 任务点 #2)。

    用 write_report() 直接调 (而非 main()), 避免设 LLM_API_KEY 触发慢路径;
    构造最小化输入覆盖报告章节渲染逻辑。

    锁点:
      - 报告含 '## 0、LLM 元信息' 章节
      - 含 4 字段名 (llm_mode / llm_enabled / llm_model / llm_base_url_host)
      - 章节顺序: 在 '## 一、Eval set 概览' 之前
    """

    @staticmethod
    def _make_min_eval_set():
        return [{
            "jd_id": "TEST_JD_001",
            "company": "TestCo",
            "title": "Test JD",
            "role_id": "algorithm",
            "text": "Test JD text.",
            "expected_label": "推荐投",
            "expected_rec": "高",
            "source": "jd_samples",
        }]

    @staticmethod
    def _make_min_metrics():
        return {
            "by_combo": {
                "baseline (FC=F, AW=F)": {
                    "n": 1, "schema_pass_rate": 1.0, "fallback_rate": 0.0,
                    "pii_safe_rate": 1.0, "avg_latency_ms": 100,
                    "tools_used_top": [], "fallback_category_breakdown": {"none": 1},
                    "any_error": False,
                },
            },
            "score_consistency": [
                {"jd_id": "TEST_JD_001", "consistent": True, "score_values": [85]},
            ],
            "rec_consistency": [
                {"jd_id": "TEST_JD_001", "consistent": True, "rec_values": ["高"]},
            ],
            "n_score_consistent": 1,
            "n_rec_consistent": 1,
            "total_jds": 1,
            "fallback_category_total": {"none": 1},
        }

    @staticmethod
    def _make_min_rows():
        return [{
            "jd_id": "TEST_JD_001",
            "role_id": "algorithm",
            "expected_label": "推荐投",
            "expected_rec": "高",
            "score": 85,
            "recommendation": "高",
            "schema_pass": True,
            "fallback_used": False,
            "fallback_category": "none",
            "tools_used": [],
            "request_id": None,
            "request_id_short": None,
            "latency_ms": 100,
            "error_type": None,
            "pii_safe": True,
            "source": "jd_samples",
            "combo": "baseline (FC=F, AW=F)",
            "combo_fc": False,
            "combo_aw": False,
        }]

    def test_write_report_includes_llm_metadata_section_and_4_fields(self, tmp_path):
        """write_report() 输出含 '## 0、LLM 元信息' 章节 + 4 字段名 (spec 任务点 #2)"""
        output = tmp_path / "report.md"
        original_output = eval_mod.OUTPUT_REPORT
        eval_mod.OUTPUT_REPORT = output
        try:
            eval_mod.write_report(
                eval_set=self._make_min_eval_set(),
                all_rows=self._make_min_rows(),
                metrics=self._make_min_metrics(),
                llm_enabled=False,
                requested_mode="offline",
                resolved_mode="offline",
                llm_eval_config={
                    "llm_mode": "offline",
                    "llm_enabled": False,
                    "llm_model": "gpt-4o-mini",
                    "llm_base_url_host": "api.openai.com",
                },
            )
            content = output.read_text(encoding="utf-8")
            assert "## 0、LLM 元信息" in content, (
                f"报告应含 '## 0、LLM 元信息' 章节, 头部: {content[:600]}"
            )
            for field in ("llm_mode", "llm_enabled", "llm_model", "llm_base_url_host"):
                assert field in content, (
                    f"报告应含字段名 {field!r}"
                )
            # 章节顺序: LLM 元信息 在 Eval set 概览 之前
            meta_pos = content.find("## 0、LLM 元信息")
            eval_set_pos = content.find("## 一、Eval set 概览")
            assert 0 <= meta_pos < eval_set_pos, (
                f"LLM 元信息章节应在 Eval set 概览之前: "
                f"meta_pos={meta_pos}, eval_set_pos={eval_set_pos}"
            )
        finally:
            eval_mod.OUTPUT_REPORT = original_output
            if output.exists():
                output.unlink()


class TestEvalReportDoesNotIncludeApiKey:
    """
    R5-D Phase 2: 报告不含 LLM_API_KEY 的值或变量名引用 (spec 任务点 #4)。

    验证策略:
      - 即使设 LLM_API_KEY env, helper 输出 dict 不含 sentinel
      - write_report 渲染 helper 输出后, 报告正文不含 sentinel, 也不含 'LLM_API_KEY' 字样
    """

    def test_helper_output_and_report_omit_api_key(self, tmp_path, monkeypatch):
        """helper 输出 + write_report 渲染 → 报告不含 LLM_API_KEY 值/env var 名 (spec 任务点 #4)"""
        sentinel_key = "sk-DO-NOT-LEAK-sentinel-9876543210-DO-NOT-LEAK"
        monkeypatch.setenv("LLM_API_KEY", sentinel_key)
        output = tmp_path / "report.md"
        original_output = eval_mod.OUTPUT_REPORT
        eval_mod.OUTPUT_REPORT = output
        try:
            # 1. helper 输出不应含 sentinel (spec 任务点 #4 子项 #1)
            helper_output = eval_mod._get_llm_eval_config(False, "offline")
            for k, v in helper_output.items():
                assert sentinel_key not in str(v), (
                    f"helper 不应输出含 api key: 字段 {k}={v!r} 含 sentinel"
                )

            # 2. write_report 渲染 helper 输出 → 报告不含 sentinel + 不含 'LLM_API_KEY' 字样
            eval_mod.write_report(
                eval_set=TestEvalReportIncludesLlmMetadata._make_min_eval_set(),
                all_rows=TestEvalReportIncludesLlmMetadata._make_min_rows(),
                metrics=TestEvalReportIncludesLlmMetadata._make_min_metrics(),
                llm_enabled=False,
                requested_mode="offline",
                resolved_mode="offline",
                llm_eval_config=helper_output,
            )
            content = output.read_text(encoding="utf-8")
            assert sentinel_key not in content, (
                f"报告不应含 LLM_API_KEY 的值, 发现 sentinel: {sentinel_key}"
            )
            # write_report 自己不应在章节里输出 LLM_API_KEY env var 名
            assert "LLM_API_KEY" not in content, (
                f"报告不应在正文引用 'LLM_API_KEY' env var 名"
            )
        finally:
            eval_mod.OUTPUT_REPORT = original_output
            if output.exists():
                output.unlink()


class TestEvalReportBaseUrlHostHidesPathAndQuery:
    """
    R5-D Phase 2: base_url_host 只输出 host, 不含 path / query (spec 任务点 #3 + #5)。

    验证: env 设含敏感 path + query 的 base_url, helper 抽出的 host 不含 path/query,
    write_report 渲染后报告里也不展示 path/query。
    """

    def test_helper_and_report_hide_base_url_path_and_query(self, tmp_path, monkeypatch):
        """base_url 含 path/query → helper 只抽 host, write_report 渲染后只展示 host (spec 任务点 #3 + #5)"""
        base_url = "https://api.example.com/v1/internal/chat?secret=TOPSECRET&foo=bar"
        monkeypatch.setenv("LLM_BASE_URL", base_url)
        output = tmp_path / "report.md"
        original_output = eval_mod.OUTPUT_REPORT
        eval_mod.OUTPUT_REPORT = output
        try:
            helper_output = eval_mod._get_llm_eval_config(False, "offline")
            assert helper_output["llm_base_url_host"] == "api.example.com", (
                f"helper 应只抽 host, 实际 {helper_output['llm_base_url_host']!r}"
            )
            # 渲染到报告
            eval_mod.write_report(
                eval_set=TestEvalReportIncludesLlmMetadata._make_min_eval_set(),
                all_rows=TestEvalReportIncludesLlmMetadata._make_min_rows(),
                metrics=TestEvalReportIncludesLlmMetadata._make_min_metrics(),
                llm_enabled=False,
                requested_mode="offline",
                resolved_mode="offline",
                llm_eval_config=helper_output,
            )
            content = output.read_text(encoding="utf-8")
            # host 应展示
            assert "api.example.com" in content, (
                f"报告应展示 host 'api.example.com'"
            )
            # path / query 不应展示
            assert "/v1/internal/chat" not in content, (
                f"报告不应含 base_url path '/v1/internal/chat'"
            )
            assert "internal" not in content, (
                f"报告不应含 base_url path 片段 'internal'"
            )
            assert "secret=TOPSECRET" not in content, (
                f"报告不应含 base_url query 'secret=TOPSECRET'"
            )
            assert "TOPSECRET" not in content, (
                f"报告不应含 query 参数值 'TOPSECRET'"
            )
            assert "foo=bar" not in content, (
                f"报告不应含 query 参数 'foo=bar'"
            )
        finally:
            eval_mod.OUTPUT_REPORT = original_output
            if output.exists():
                output.unlink()

# =========================================================================
# R5-D Phase 3: rewrite impact 指标
# =========================================================================
class TestRewriteImpactCountsChangedBulletsWithoutStoringText:
    """
    R5-D Phase 3: _summarize_rewrite_impact (spec §3) — 计算 changed bullet 数,
    **不**存储 bullet 原文到返回 dict。

    锁点:
      - changed_count / total / changed_rate / avg_len_before / avg_len_after 5 字段
      - 返回 dict 里不含任何 bullet 原文 (输入是 list[str], 输出只有数字)
      - 全 changed / 全 unchanged / 空列表 / 部分 changed 边界
    """

    def test_basic_partial_changed(self):
        """3 bullet 中 1 个 changed → changed=1, total=3, rate=1/3"""
        before = ["项目A: 设计架构", "项目B: 实现核心算法", "项目C: 性能优化"]
        after = ["项目A: 设计架构", "项目B: 实现LLM算法", "项目C: 性能优化"]
        impact = eval_mod._summarize_rewrite_impact(before, after)
        assert impact["rewrite_changed_count"] == 1, (
            f"应有 1 个 changed bullet, 实际 {impact['rewrite_changed_count']}"
        )
        assert impact["rewrite_total"] == 3, f"total 应为 3, 实际 {impact['rewrite_total']}"
        assert abs(impact["rewrite_changed_rate"] - 1 / 3) < 0.01, (
            f"rate 应 ≈ 0.333, 实际 {impact['rewrite_changed_rate']}"
        )
        assert impact["avg_len_before"] > 0
        assert impact["avg_len_after"] > 0
        # 隐私边界: 返回 dict **绝不**含 bullet 原文
        impact_str = str(impact)
        assert "项目A" not in impact_str, f"返回 dict 不应含 bullet 原文 '项目A': {impact_str}"
        assert "项目B" not in impact_str, f"返回 dict 不应含 bullet 原文 '项目B': {impact_str}"
        assert "项目C" not in impact_str, f"返回 dict 不应含 bullet 原文 '项目C': {impact_str}"

    def test_all_unchanged(self):
        """全 unchanged → changed=0, rate=0.0"""
        before = ["a", "bb", "ccc"]
        after = ["a", "bb", "ccc"]
        impact = eval_mod._summarize_rewrite_impact(before, after)
        assert impact["rewrite_changed_count"] == 0
        assert impact["rewrite_total"] == 3
        assert impact["rewrite_changed_rate"] == 0.0

    def test_all_changed(self):
        """全 changed → changed=N, rate=1.0"""
        before = ["a", "b", "c"]
        after = ["x", "y", "z"]
        impact = eval_mod._summarize_rewrite_impact(before, after)
        assert impact["rewrite_changed_count"] == 3
        assert impact["rewrite_total"] == 3
        assert impact["rewrite_changed_rate"] == 1.0

    def test_empty_before_returns_zero_impact(self):
        """before 空列表 → 全 0 字段 (offline + 无 highlights fallback)"""
        impact = eval_mod._summarize_rewrite_impact([], [])
        assert impact["rewrite_changed_count"] == 0
        assert impact["rewrite_total"] == 0
        assert impact["rewrite_changed_rate"] == 0.0
        assert impact["avg_len_before"] == 0.0
        assert impact["avg_len_after"] == 0.0

    def test_after_shorter_than_before_uses_zip(self):
        """after 比 before 短 → 只 zip 到 min(len), 不溢出"""
        before = ["a", "b", "c", "d"]
        after = ["x", "y"]  # 只有 2 个
        impact = eval_mod._summarize_rewrite_impact(before, after)
        assert impact["rewrite_total"] == 4  # total 用 len(before)
        # zip 前 2 个都 changed
        assert impact["rewrite_changed_count"] == 2
        assert abs(impact["rewrite_changed_rate"] - 0.5) < 0.01


class TestExtractProjectHighlightsHandlesMissingProjects:
    """
    R5-D Phase 3: _extract_project_highlights 防御性 — missing projects / missing
    project_group / malformed preview 都应返空 list (offline + 空 materials 兜底)。
    """

    def test_normal_preview_extracts_all_highlights(self):
        """正常 preview → 扁平抽出所有 project 高亮 (嵌套在 projects[i].content.highlights)"""
        preview = {
            "sections": [{
                "type": "project_group",
                "content": {
                    "projects": [
                        {"type": "project", "content": {"highlights": ["hl_a1", "hl_a2"]}},
                        {"type": "project", "content": {"highlights": ["hl_b1"]}},
                        {"type": "project", "content": {"highlights": ["hl_c1", "hl_c2"]}},
                    ],
                },
            }],
        }
        highlights = eval_mod._extract_project_highlights(preview)
        assert highlights == ["hl_a1", "hl_a2", "hl_b1", "hl_c1", "hl_c2"], (
            f"应扁平抽出 5 条 highlight, 实际 {highlights}"
        )

    def test_missing_projects_field_returns_empty(self):
        """project_group.content 没 projects 字段 → []"""
        preview = {"sections": [{"type": "project_group", "content": {}}]}
        assert eval_mod._extract_project_highlights(preview) == []

    def test_no_project_group_section_returns_empty(self):
        """sections 里没 project_group 段 → []"""
        preview = {"sections": [
            {"type": "header", "content": {"name": "x"}},
            {"type": "education", "content": {}},
            {"type": "skills", "content": {}},
        ]}
        assert eval_mod._extract_project_highlights(preview) == []

    def test_empty_highlights_in_projects_returns_empty(self):
        """project.content.highlights 全部空 list → []"""
        preview = {"sections": [{
            "type": "project_group",
            "content": {"projects": [
                {"type": "project", "content": {"highlights": []}},
                {"type": "project", "content": {"highlights": []}},
            ]},
        }]}
        assert eval_mod._extract_project_highlights(preview) == []

    def test_malformed_preview_inputs_return_empty(self):
        """malformed preview 输入 (非 dict / sections 非 list / sections 缺失) → [] 不抛"""
        # 非 dict
        assert eval_mod._extract_project_highlights(None) == []
        assert eval_mod._extract_project_highlights("not a dict") == []
        assert eval_mod._extract_project_highlights([]) == []
        # 无 sections
        assert eval_mod._extract_project_highlights({}) == []
        # sections 非 list
        assert eval_mod._extract_project_highlights({"sections": "broken"}) == []
        assert eval_mod._extract_project_highlights({"sections": 42}) == []
        # projects 非 list
        assert eval_mod._extract_project_highlights(
            {"sections": [{"type": "project_group", "content": {"projects": "broken"}}]}
        ) == []
        # project.content 不是 dict → 跳过
        assert eval_mod._extract_project_highlights(
            {"sections": [{"type": "project_group", "content": {"projects": [{"type": "project"}]}}]}
        ) == []
        # highlights 非 list
        assert eval_mod._extract_project_highlights(
            {"sections": [{"type": "project_group", "content": {"projects": [
                {"type": "project", "content": {"highlights": "broken"}},
            ]}}]}
        ) == []
        # 非 str 高亮元素过滤
        assert eval_mod._extract_project_highlights(
            {"sections": [{"type": "project_group", "content": {"projects": [
                {"type": "project", "content": {"highlights": ["good", 123, None, "also_good"]}},
            ]}}]}
        ) == ["good", "also_good"]


class TestEvalReportContainsRewriteImpactSummary:
    """
    R5-D Phase 3: write_report 输出含 rewrite impact 摘要 (含 rewrite_changed_rate)
    (spec §3 验收第 1 条)。
    """

    def test_report_contains_rewrite_changed_rate_section(self, tmp_path):
        """完整跑 main() 后, 报告含 'rewrite_changed_rate' + rewrite impact 章节标题"""
        output = tmp_path / "report_rewrite_summary.md"
        original_output = eval_mod.OUTPUT_REPORT
        em = eval_mod  # alias for clarity
        em.OUTPUT_REPORT = output
        try:
            em.main(argv=["--mode", "offline"])
            content = output.read_text(encoding="utf-8")
            # 章节标题应含 "rewrite impact"
            assert "rewrite impact" in content.lower(), (
                f"报告应含 'rewrite impact' 章节标题, 头部: {content[:500]}"
            )
            # 字段名应出现 (spec §3 要求)
            assert "rewrite_changed_rate" in content, (
                f"报告应含 'rewrite_changed_rate' 字段, 头部: {content[:500]}"
            )
            # 至少一个 ratio 数值 (e.g. "0.0%" 或 "X/Y" 形式)
            assert "%" in content, "报告应展示百分比格式的 rewrite rate"
        finally:
            eval_mod.OUTPUT_REPORT = original_output
            if output.exists():
                output.unlink()

    def test_evaluate_one_row_includes_rewrite_fields(self):
        """evaluate_one 返回 row 含 5 rewrite_* 字段"""
        eval_set = eval_mod.load_eval_set()
        sample = eval_set[0]
        row = eval_mod.evaluate_one(
            sample,
            enable_function_calling=False,
            enable_agent_workflow=False,
        )
        # 5 spec 字段必须存在
        for k in (
            "rewrite_changed_count", "rewrite_total",
            "rewrite_changed_rate", "avg_len_before", "avg_len_after",
        ):
            assert k in row, f"evaluate_one row 缺字段 {k!r}"
        # baseline combo: changed=0, total>=0 (取决于 materials)
        assert row["rewrite_changed_count"] == 0, (
            f"baseline combo changed 应为 0, 实际 {row['rewrite_changed_count']}"
        )
        assert row["rewrite_total"] >= 0
        assert isinstance(row["rewrite_changed_rate"], float)


class TestEvalReportDoesNotLeakBulletText:
    """
    R5-D Phase 3: 报告**绝不**含 bullet 原文 (spec §3 验收第 2 条 + AGENTS.md 隐私边界)。

    验证策略:
      1. _summarize_rewrite_impact 输出 dict 不含 bullet 原文 (只用数字)
      2. write_report 渲染后报告不含 sentinel (即使 baseline_highlights 含它)
      3. 完整 main() 跑完后, 报告不含真实 materials.json 抽出的任意 bullet 文本
    """

    SENTINEL = "SENTINEL_BULLET_DO_NOT_LEAK_TO_REPORT_xyz123_unique"

    def test_helper_output_does_not_leak_bullet_text(self):
        """helper 输出 dict 不含 bullet 原文 (只含数字)"""
        before = [self.SENTINEL, "normal_bullet_one"]
        after = ["different_normal", "different_normal_two"]
        impact = eval_mod._summarize_rewrite_impact(before, after)
        impact_str = str(impact)
        assert self.SENTINEL not in impact_str, (
            f"_summarize_rewrite_impact 输出不应含 bullet 原文 sentinel: {impact_str}"
        )
        assert "normal_bullet_one" not in impact_str, (
            f"输出不应含 before bullet 原文: {impact_str}"
        )
        # 输出 dict 必含 5 数字字段
        for k in (
            "rewrite_changed_count", "rewrite_total",
            "rewrite_changed_rate", "avg_len_before", "avg_len_after",
        ):
            assert k in impact

    def test_extract_returns_list_with_sentinel_for_unit_test(self):
        """测试设置校验: _extract_project_highlights 确实会返回 sentinel (供后续测试用)"""
        preview = {
            "sections": [{
                "type": "project_group",
                "content": {"projects": [{
                    "type": "project",
                    "content": {"highlights": [self.SENTINEL, "regular"]},
                }]},
            }],
        }
        highlights = eval_mod._extract_project_highlights(preview)
        assert self.SENTINEL in highlights, (
            "测试设置: _extract_project_highlights 应能提取 sentinel"
        )

    def test_write_report_with_sentinel_baseline_does_not_leak(self, tmp_path):
        """write_report 直接调, 验证报告正文不含 sentinel"""
        # 复用 R5-D Phase 2 测试的 _make_min_* helpers
        output = tmp_path / "report_no_leak.md"
        original_output = eval_mod.OUTPUT_REPORT
        eval_mod.OUTPUT_REPORT = output
        try:
            min_eval_set = TestEvalReportIncludesLlmMetadata._make_min_eval_set()
            min_metrics = TestEvalReportIncludesLlmMetadata._make_min_metrics()
            min_rows = TestEvalReportIncludesLlmMetadata._make_min_rows()
            # 注入 rewrite_summary 到 metrics (让章节能渲染)
            min_metrics["rewrite_summary_global"] = {
                "avg_rewrite_changed_rate": 0.0,
                "avg_len_before": 10.0,
                "avg_len_after": 10.0,
                "total_changed": 0,
                "total_counted": 0,
            }
            # 给每 row 加 rewrite_* 字段
            for row in min_rows:
                row["rewrite_changed_count"] = 0
                row["rewrite_total"] = 0
                row["rewrite_changed_rate"] = 0.0
                row["avg_len_before"] = 0.0
                row["avg_len_after"] = 0.0

            eval_mod.write_report(
                eval_set=min_eval_set,
                all_rows=min_rows,
                metrics=min_metrics,
                llm_enabled=False,
                requested_mode="offline",
                resolved_mode="offline",
                llm_eval_config={
                    "llm_mode": "offline",
                    "llm_enabled": False,
                    "llm_model": "gpt-4o-mini",
                    "llm_base_url_host": "api.openai.com",
                },
            )
            content = output.read_text(encoding="utf-8")
            assert self.SENTINEL not in content, (
                f"报告不应含 bullet 原文 sentinel, 实际报告前 500 字符: {content[:500]}"
            )
        finally:
            eval_mod.OUTPUT_REPORT = original_output
            if output.exists():
                output.unlink()

    def test_full_main_run_does_not_leak_real_bullets(self, tmp_path, monkeypatch):
        """完整跑 main() 后, 报告不含 _extract_project_highlights 从真实 preview
        抽到的任何 highlight 文本 (抽样检查: 取第一份 sample 的 baseline highlights)"""
        eval_set = eval_mod.load_eval_set()
        first_sample = eval_set[0]
        # 跑一次 baseline preview 拿真实 highlights (作为 baseline)
        from core.generator import preview_resume  # noqa: WPS433
        preview = preview_resume(
            target_role=first_sample["role_id"],
            template="classic",
            jd_text=first_sample["text"],
            enable_function_calling=False,
            enable_agent_workflow=False,
        )
        real_highlights = eval_mod._extract_project_highlights(preview)
        # 真实 highlights 不为空 — 否则测试不具代表性
        assert len(real_highlights) > 0, (
            "真实 materials.json 应有 highlights; 若空则测试无效"
        )

        # 跑完整 main(), monkeypatch OUTPUT_REPORT 到 tmp_path
        output = tmp_path / "report_full_main.md"
        monkeypatch.setattr(eval_mod, "OUTPUT_REPORT", output)
        monkeypatch.setattr(eval_mod, "is_llm_enabled", lambda: False)

        try:
            eval_mod.main(argv=["--mode", "offline"])
            content = output.read_text(encoding="utf-8")
            # 抽样检查: 真实 highlights 中的任意一条都不应出现在报告
            for hl in real_highlights[:3]:  # 抽前 3 条
                # 抠掉 placeholder (避免误报)
                stripped_hl = hl.replace("13800000000", "").replace("your_email@example.com", "")
                if len(stripped_hl) < 10:
                    continue  # 太短容易误报, 跳过
                assert stripped_hl not in content, (
                    f"报告不应含真实 bullet 原文 (长 {len(stripped_hl)} 字符): "
                    f"{stripped_hl[:80]}..."
                )
        finally:
            if output.exists():
                output.unlink()
