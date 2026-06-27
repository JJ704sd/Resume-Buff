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