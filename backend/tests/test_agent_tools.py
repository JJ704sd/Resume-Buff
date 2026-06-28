"""
core/agent_tools 模块测试 (R5-A Phase 1: Agent 工具注册表)

锁点(14 case):
  TestRegistrySchema (3 case):
    1. registry_has_4_required_tools          — AGENT_TOOLS 含 4 个核心工具
    2. each_tool_has_required_fields          — ToolSpec 5 字段都存在
    3. tool_names_are_strings_and_unique      — 名字唯一且都是 str

  TestExecuteAgentTool (7 case):
    4.  dispatch_to_parse_jd_returns_success  — mock parse_jd,验证 ToolResult 透传
    5.  dispatch_to_match_score               — 同上
    6.  dispatch_to_evaluate_bullet           — 同上
    7.  dispatch_to_rewrite_highlights        — 同上(无 key 走降级原文)
    8.  unknown_tool_returns_tool_not_allowed — 未知工具 → status=error, error_type=TOOL_NOT_ALLOWED
    9.  args_typeerror_returns_tool_args_invalid — mock tool 抛 TypeError
    10. runtime_exception_returns_tool_runtime_error — mock tool 抛 ValueError

  TestPrivacyGuarantee (1 case):
    11. tool_result_has_no_args_or_input_attrs — ToolResult dataclass 字段定义不含 args/input

  TestLatency (2 case):
    12. latency_ms_is_non_negative_int         — 成功时 latency >= 0
    13. latency_recorded_even_on_failure       — 失败时也记录 latency

  TestBackwardCompatibility (1 case):
    14. evaluate_bullet_jd_match_callable_directly — R4-F 测试不破

测试策略:
  - 用 monkeypatch 替换 AGENT_TOOLS 里的 callable(mock),不污染原注册表
  - mock 时注意:dataclass 是 frozen,替换字段不生效;只能 monkeypatch 字典里的 spec 引用
"""
import pytest

from core import agent_tools
from core.agent_tools import (
    AGENT_TOOLS,
    ToolErrorType,
    ToolResult,
    ToolSpec,
    execute_agent_tool,
    get_tool_spec,
    list_tools,
)


# =========================================================================
# TestRegistrySchema
# =========================================================================
class TestRegistrySchema:
    """R5-A Phase 1: Tool 注册表结构锁定"""

    def test_registry_has_4_required_tools(self):
        """AGENT_TOOLS 必须含 4 个核心工具(spec §4.2 推荐任务图)"""
        required = {"parse_jd", "match_score", "evaluate_bullet_jd_match", "rewrite_highlights"}
        actual = set(AGENT_TOOLS.keys())
        assert required <= actual, (
            f"AGENT_TOOLS 缺工具: {required - actual}, 实际: {actual}"
        )

    def test_each_tool_has_required_fields(self):
        """每个 ToolSpec 必须含 name / callable / permission / pii_risk / timeout_ms"""
        required_fields = {"name", "callable", "permission", "pii_risk", "timeout_ms"}
        for tool_name, spec in AGENT_TOOLS.items():
            assert isinstance(spec, ToolSpec), f"{tool_name} 不是 ToolSpec"
            # dataclass 字段名检查
            from dataclasses import fields
            actual_fields = {f.name for f in fields(ToolSpec)}
            assert required_fields <= actual_fields, (
                f"ToolSpec 缺字段: {required_fields - actual_fields}"
            )
            # 字段值类型校验
            assert isinstance(spec.name, str) and spec.name, f"{tool_name} name 空"
            assert callable(spec.callable), f"{tool_name} callable 不可调用"
            assert spec.permission in {
                "read_jd_text", "read_jd_and_materials", "read_bullet_and_jd_focus",
                "read_materials_and_jd_keywords",  # R5-A Phase 3: retrieve_evidence 新增
                # R5-C Phase 2: 外部简历工具新增 (spec §3.2 / §3.4)
                "read_external_resume",
                "read_jd_and_external_resume",
            }, f"{tool_name} permission 异常: {spec.permission}"
            assert spec.pii_risk in {"low", "medium", "high"}, f"{tool_name} pii_risk 异常"
            assert isinstance(spec.timeout_ms, int) and spec.timeout_ms > 0, (
                f"{tool_name} timeout_ms 应为正整数, 实际: {spec.timeout_ms}"
            )

    def test_tool_names_are_strings_and_unique(self):
        """工具名都是非空 str 且唯一"""
        names = list(AGENT_TOOLS.keys())
        assert all(isinstance(n, str) and n for n in names), "工具名必须是非空 str"
        assert len(set(names)) == len(names), f"工具名重复: {names}"


# =========================================================================
# TestExecuteAgentTool
# =========================================================================
class TestExecuteAgentTool:
    """R5-A Phase 1: 工具执行入口行为锁定"""

    def test_dispatch_to_parse_jd_returns_success(self, monkeypatch):
        """mock parse_jd, 验证 ToolResult 透传(成功路径)"""
        sentinel = {"raw_keywords": ["LLM"], "tier_info": {"required": [], "preferred": []}}
        monkeypatch.setitem(AGENT_TOOLS, "parse_jd",
                            ToolSpec(name="parse_jd", callable=lambda text: sentinel,
                                     permission="read_jd_text", pii_risk="medium", timeout_ms=300))

        result = execute_agent_tool("parse_jd", {"text": "sample jd"})
        assert isinstance(result, ToolResult)
        assert result.tool == "parse_jd"
        assert result.status == "success"
        assert result.output is sentinel  # 透传原对象
        assert result.error_type is None
        assert result.latency_ms >= 0

    def test_dispatch_to_match_score_returns_success(self, monkeypatch):
        """mock match_score, 验证 ToolResult 透传"""
        sentinel = {"score": 80, "coverage": 0.75, "recommendation": "high"}
        monkeypatch.setitem(AGENT_TOOLS, "match_score",
                            ToolSpec(name="match_score", callable=lambda text, role, materials: sentinel,
                                     permission="read_jd_and_materials", pii_risk="medium", timeout_ms=500))

        result = execute_agent_tool("match_score", {"text": "jd", "role": "tech_metric", "materials": {}})
        assert result.status == "success"
        assert result.output is sentinel

    def test_dispatch_to_evaluate_bullet_jd_match_returns_success(self, monkeypatch):
        """mock evaluate_bullet_jd_match, 验证 ToolResult 透传"""
        sentinel = {"matched": ["LLM"], "missing": ["Prompt"]}
        monkeypatch.setitem(AGENT_TOOLS, "evaluate_bullet_jd_match",
                            ToolSpec(name="evaluate_bullet_jd_match",
                                     callable=lambda bullet, jd_focus: sentinel,
                                     permission="read_bullet_and_jd_focus", pii_risk="low", timeout_ms=300))

        result = execute_agent_tool(
            "evaluate_bullet_jd_match",
            {"bullet": "做了 100 题评测", "jd_focus": {}},
        )
        assert result.status == "success"
        assert result.output is sentinel

    def test_dispatch_to_rewrite_highlights_returns_success(self, monkeypatch):
        """mock rewrite_highlights, 验证 ToolResult 透传(无 key 走降级原文)"""
        sentinel = ["改写后 1", "改写后 2"]
        monkeypatch.setitem(AGENT_TOOLS, "rewrite_highlights",
                            ToolSpec(name="rewrite_highlights", callable=lambda highlights, target_role: sentinel,
                                     permission="read_bullet_and_jd_focus", pii_risk="medium", timeout_ms=2000))

        result = execute_agent_tool(
            "rewrite_highlights",
            {"highlights": ["原 1", "原 2"], "target_role": "tech_metric"},
        )
        assert result.status == "success"
        assert result.output is sentinel

    def test_unknown_tool_returns_tool_not_allowed(self):
        """未知工具 → status=error, error_type=TOOL_NOT_ALLOWED, 不抛"""
        result = execute_agent_tool("hacker_tool", {"evil": "payload"})
        assert isinstance(result, ToolResult)
        assert result.status == "error"
        assert result.error_type == ToolErrorType.TOOL_NOT_ALLOWED
        assert result.output is None
        assert result.error_msg  # 错误消息非空

    def test_args_typeerror_returns_tool_args_invalid(self, monkeypatch):
        """工具 callable 抛 TypeError → error_type=TOOL_ARGS_INVALID"""
        def buggy_tool(**kwargs):
            raise TypeError("missing required arg: bullet")

        monkeypatch.setitem(AGENT_TOOLS, "evaluate_bullet_jd_match",
                            ToolSpec(name="evaluate_bullet_jd_match", callable=buggy_tool,
                                     permission="read_bullet_and_jd_focus", pii_risk="low", timeout_ms=300))

        result = execute_agent_tool("evaluate_bullet_jd_match", {})
        assert result.status == "error"
        assert result.error_type == ToolErrorType.TOOL_ARGS_INVALID
        assert result.output is None
        assert result.latency_ms >= 0  # 失败时也记录耗时

    def test_runtime_exception_returns_tool_runtime_error(self, monkeypatch):
        """工具 callable 抛 RuntimeError → error_type=TOOL_RUNTIME_ERROR"""
        def crashing_tool(text):
            raise ValueError("invalid JD format")

        monkeypatch.setitem(AGENT_TOOLS, "parse_jd",
                            ToolSpec(name="parse_jd", callable=crashing_tool,
                                     permission="read_jd_text", pii_risk="medium", timeout_ms=300))

        result = execute_agent_tool("parse_jd", {"text": "garbage"})
        assert result.status == "error"
        assert result.error_type == ToolErrorType.TOOL_RUNTIME_ERROR
        assert result.output is None


# =========================================================================
# TestPrivacyGuarantee
# =========================================================================
class TestPrivacyGuarantee:
    """R5-A Phase 1: 隐私边界锁定 — ToolResult 不存 args / input 原文"""

    def test_tool_result_has_no_args_or_input_attrs(self):
        """ToolResult dataclass 字段定义不含 args / input(防 PII 泄漏)"""
        from dataclasses import fields
        field_names = {f.name for f in fields(ToolResult)}
        forbidden = {"args", "input", "raw_args", "input_text", "arguments"}
        leaked = forbidden & field_names
        assert not leaked, (
            f"ToolResult 不应含 {leaked}, 实际字段: {field_names} — "
            f"PII 泄漏风险"
        )


# =========================================================================
# TestLatency
# =========================================================================
class TestLatency:
    """R5-A Phase 1: 延迟计时锁定"""

    def test_latency_ms_is_non_negative_int(self):
        """成功时 latency_ms >= 0(整型)"""
        result = execute_agent_tool("hacker", {})  # 走 allowlist 拒绝路径
        assert isinstance(result.latency_ms, int)
        assert result.latency_ms >= 0

    def test_latency_recorded_even_on_failure(self, monkeypatch):
        """失败时 latency_ms 也记录(spec §6.3 可观测)"""
        def slow_crash(**kwargs):
            import time
            time.sleep(0.01)  # 10ms
            raise ValueError("boom")

        monkeypatch.setitem(AGENT_TOOLS, "parse_jd",
                            ToolSpec(name="parse_jd", callable=slow_crash,
                                     permission="read_jd_text", pii_risk="medium", timeout_ms=300))

        result = execute_agent_tool("parse_jd", {"text": "x"})
        assert result.status == "error"
        assert result.latency_ms >= 10  # 至少 sleep 的耗时


# =========================================================================
# TestBackwardCompatibility
# =========================================================================
class TestBackwardCompatibility:
    """R5-A Phase 1: 不破坏 R4-F 既有 evaluate_bullet_jd_match 调用路径"""

    def test_evaluate_bullet_jd_match_callable_directly(self):
        """直接调底层 evaluate_bullet_jd_match(不通过 execute_agent_tool)仍正常工作"""
        # R4-F 测试用 jd_focus 必须含 matched 字段
        jd_focus = {"matched": ["LLM"], "missing": ["Prompt"], "tier_required": [], "tier_preferred": []}
        result = agent_tools.evaluate_bullet_jd_match("审核 200 条 AI 输出", jd_focus)
        assert isinstance(result, dict)
        # 真实函数返 matched_keywords / missing_keywords / suggestion(R4-F 测试已锁)
        assert "matched_keywords" in result
        assert "missing_keywords" in result
        assert "suggestion" in result


# =========================================================================
# TestHelpers
# =========================================================================
class TestHelpers:
    """R5-A Phase 1: list_tools / get_tool_spec 辅助函数"""

    def test_list_tools_returns_all_registered(self):
        tools = list_tools()
        assert set(tools) == set(AGENT_TOOLS.keys())
        assert len(tools) == len(AGENT_TOOLS)

    def test_get_tool_spec_returns_spec_for_known_tool(self):
        spec = get_tool_spec("parse_jd")
        assert spec is not None
        assert spec.name == "parse_jd"

    def test_get_tool_spec_returns_none_for_unknown_tool(self):
        assert get_tool_spec("nope") is None


# =========================================================================
# R5-B Phase 2A: Context 权限校验
# =========================================================================
class TestToolPermissionContext:
    """R5-B Phase 2A: context 权限边界 + affects_preview 元数据

    锁点 (round5-b-agent-capability-spec.md §3.2):
      - allow_jd_text / allow_materials / allow_external_resume / max_pii_risk
      - 权限不匹配返回 PRIVACY_VIOLATION (早于 schema 校验)
      - 错误描述只含字段名 + 权限名, 不含 args 原文
    """

    def test_default_context_allows_jd_and_materials(self):
        """缺省 context (无 context 参数) → JD / materials 工具可调用"""
        from core.generator import load_materials
        mats = load_materials()
        # parse_jd 不需要 materials, 但需要 allow_jd_text (默认 True)
        result = execute_agent_tool("parse_jd", args={"text": "熟悉大模型评测"})
        assert result.status == "success", (
            f"缺省 context 应允许 parse_jd, 实际: {result.error_msg}"
        )

    def test_deny_jd_text_blocks_parse_jd(self):
        """allow_jd_text=False → parse_jd 返回 PRIVACY_VIOLATION"""
        result = execute_agent_tool(
            "parse_jd",
            args={"text": "熟悉大模型评测"},
            context={"allow_jd_text": False, "allow_materials": True},
        )
        assert result.status == "error"
        assert result.error_type == ToolErrorType.PRIVACY_VIOLATION
        # 错误描述只含权限名, 不含 args 原文
        assert "jd" in result.error_msg.lower()
        assert "熟悉大模型评测" not in result.error_msg  # 不含 JD 原文

    def test_deny_materials_blocks_match_score(self):
        """allow_materials=False → match_score 返回 PRIVACY_VIOLATION"""
        result = execute_agent_tool(
            "match_score",
            args={"text": "熟悉 Python", "target_role": "tech_metric", "materials": {}},
            context={"allow_jd_text": True, "allow_materials": False},
        )
        assert result.status == "error"
        assert result.error_type == ToolErrorType.PRIVACY_VIOLATION
        assert "materials" in result.error_msg.lower()

    def test_max_pii_risk_low_blocks_medium_tools(self):
        """max_pii_risk=low → pii_risk=medium 的工具被拒"""
        # match_score pii_risk="medium", 低 context 应拒绝
        result = execute_agent_tool(
            "match_score",
            args={"text": "x", "target_role": "tech_metric", "materials": {}},
            context={"allow_jd_text": True, "allow_materials": True, "max_pii_risk": "low"},
        )
        assert result.status == "error"
        assert result.error_type == ToolErrorType.PRIVACY_VIOLATION
        assert "pii" in result.error_msg.lower() or "medium" in result.error_msg.lower()

    def test_max_pii_risk_high_allows_medium_tools(self):
        """max_pii_risk=high → medium 工具可调用(向后兼容)"""
        result = execute_agent_tool(
            "match_score",
            args={"text": "熟悉 Python", "target_role": "tech_metric", "materials": {}},
            context={"allow_jd_text": True, "allow_materials": True, "max_pii_risk": "high"},
        )
        assert result.status == "success", (
            f"high risk context 应允许 medium tool, 实际: {result.error_msg}"
        )

    def test_privacy_violation_does_not_call_tool(self):
        """PRIVACY_VIOLATION 不调用 callable (latency_ms=0)"""
        result = execute_agent_tool(
            "parse_jd",
            args={"text": "x"},
            context={"allow_jd_text": False},
        )
        assert result.latency_ms == 0
        assert result.output is None

    def test_external_resume_requires_allow_flag(self):
        """external_resume 相关工具需 allow_external_resume=True
        (当前无实际 external_resume 工具, 但 _check_permission_context 已实现该分支)"""
        # 直接测试 _check_permission_context helper (不通过 execute_agent_tool)
        from core.agent_tools import ToolSpec, _check_permission_context

        fake_ext_spec = ToolSpec(
            name="parse_external_resume",
            callable=lambda text: text,
            permission="read_external_resume",
            pii_risk="medium",
            timeout_ms=300,
        )
        # 默认 allow_external_resume=False → 拒绝
        assert _check_permission_context(fake_ext_spec, {}) is not None
        # 显式 True → 允许
        assert _check_permission_context(fake_ext_spec, {"allow_external_resume": True}) is None

    def test_context_check_runs_before_schema_check(self):
        """context 权限校验早于 schema 校验 — 避免敏感数据进入校验日志"""
        # 即使 args 类型错, 也应先返 PRIVACY_VIOLATION 而非 TOOL_ARGS_INVALID
        result = execute_agent_tool(
            "parse_jd",
            args={"text": 12345},  # type 错
            context={"allow_jd_text": False},  # 但权限先拒
        )
        assert result.status == "error"
        assert result.error_type == ToolErrorType.PRIVACY_VIOLATION, (
            f"权限校验应早于 schema 校验, 实际 error_type: {result.error_type}"
        )


# =========================================================================
# R5-B Phase 2A: affects_preview 元数据
# =========================================================================
class TestAffectsPreview:
    """R5-B Phase 2A: ToolSpec.metadata["affects_preview"] 控制 tools_used 语义"""

    def test_retrieve_evidence_affects_preview_true(self):
        """retrieve_evidence 是当前唯一真正影响 preview 的工具"""
        from core.agent_tools import affects_preview
        assert affects_preview("retrieve_evidence") is True

    def test_match_score_affects_preview_false(self):
        """match_score 当前是展示型 (output 未被 build_sections 消费)"""
        from core.agent_tools import affects_preview
        assert affects_preview("match_score") is False

    def test_parse_jd_affects_preview_false(self):
        """parse_jd 当前是展示型"""
        from core.agent_tools import affects_preview
        assert affects_preview("parse_jd") is False

    def test_rewrite_highlights_affects_preview_false(self):
        """rewrite_highlights 当前是展示型 (代表 bullet, 占位)"""
        from core.agent_tools import affects_preview
        assert affects_preview("rewrite_highlights") is False

    def test_evaluate_bullet_affects_preview_false(self):
        """evaluate_bullet_jd_match 当前是展示型 (representative 单条)"""
        from core.agent_tools import affects_preview
        assert affects_preview("evaluate_bullet_jd_match") is False

    def test_unknown_tool_returns_false(self):
        """未注册工具 → affects_preview 返 False (不抛)"""
        from core.agent_tools import affects_preview
        assert affects_preview("nonexistent_tool") is False


# =========================================================================
# R5-B Phase 2A: 完整 schema validator 集成 (execute_agent_tool 走通)
# =========================================================================
class TestExecuteAgentToolSchemaIntegration:
    """R5-B Phase 2A: execute_agent_tool 集成新 schema validator (type + range + items)"""

    def test_type_mismatch_returns_args_invalid(self):
        """字段类型错 → TOOL_ARGS_INVALID (早于 callable)"""
        # retrieve_evidence jd_keywords 必须是 array, 传 string 应拒
        result = execute_agent_tool(
            "retrieve_evidence",
            args={
                "jd_keywords": "not a list",  # type 错
                "role": "tech_metric",
                "materials": {},
            },
        )
        assert result.status == "error"
        assert result.error_type == ToolErrorType.TOOL_ARGS_INVALID
        # 错误描述含字段名 + 类型摘要, 不含 args 原文
        assert "jd_keywords" in result.error_msg
        assert "array" in result.error_msg
        assert "not a list" not in result.error_msg

    def test_range_violation_returns_args_invalid(self):
        """top_k 越界 → TOOL_ARGS_INVALID"""
        result = execute_agent_tool(
            "retrieve_evidence",
            args={
                "jd_keywords": ["LLM"],
                "role": "tech_metric",
                "materials": {},
                "top_k": 100,  # > maximum 50
            },
        )
        assert result.status == "error"
        assert result.error_type == ToolErrorType.TOOL_ARGS_INVALID
        assert "maximum" in result.error_msg

    def test_array_items_type_violation(self):
        """array items 类型错 → TOOL_ARGS_INVALID"""
        result = execute_agent_tool(
            "retrieve_evidence",
            args={
                "jd_keywords": ["LLM", 123],  # int 不应是 string
                "role": "tech_metric",
                "materials": {},
            },
        )
        assert result.status == "error"
        assert result.error_type == ToolErrorType.TOOL_ARGS_INVALID
        assert "string" in result.error_msg

    def test_valid_args_still_pass_through(self):
        """完整合法 args → 走通 validator 调 callable"""
        result = execute_agent_tool(
            "retrieve_evidence",
            args={
                "jd_keywords": ["LLM"],
                "role": "tech_metric",
                "materials": {"projects": [], "skills": {}},
                "top_k": 5,
                "min_confidence": 0.0,
            },
        )
        assert result.status == "success"
        assert result.output is not None  # 返 dict list
