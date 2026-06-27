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
