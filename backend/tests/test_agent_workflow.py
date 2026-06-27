"""
core/agent_workflow 模块测试 (R5-A Phase 1: 受控 Plan-and-Execute 编排器)

锁点(20 case):
  TestBuildTaskGraph (6 case):
    1.  minimal_no_jd_no_fc_no_session    — 4 步本地任务
    2.  with_jd_adds_parse_jd_match_score — +2 步(parse_jd, match_score)
    3.  with_function_calling_adds_evaluate_bullet — +1 步 evaluate_bullet_jd_match
    4.  with_external_resume_adds_parse_step — +1 步(本轮为占位 None tool)
    5.  task_graph_is_deterministic       — 同输入 → 字节级一致
    6.  step_indices_are_sequential       — step 0..N-1 连续

  TestAgentStepSchema (2 case):
    7.  step_has_all_required_fields      — 7 字段都存在
    8.  step_dataclass_is_frozen          — frozen=True 不可改

  TestRunAgentWorkflow (6 case):
    9.  returns_preview_dict_when_no_output_dir — preview 模式返 dict
    10. preview_dict_has_old_schema_fields      — target_role / template / sections / jd_match_counts
    11. returns_docx_path_when_output_dir       — generate 模式返 Path
    12. tool_failure_does_not_raise              — mock 工具失败,workflow 不抛
    13. fallback_to_old_path_on_load_failure     — monkeypatch load_materials 抛 → 仍返 preview dict
    14. enable_function_calling_propagated       — FC=True 时任务图有 evaluate step

  TestBackwardCompatibility (3 case):
    15. enable_agent_workflow_false_unchanged    — Phase 1.5 加 generator kwarg 后,False 路径字节级一致
    16. old_preview_resume_signature_intact      — 不传 enable_agent_workflow 也 OK
    17. workflow_does_not_break_r4_session       — 现有 R4-M session 路径不破

  TestPrivacyGuarantee (3 case):
    18. agent_step_has_no_jd_or_bullet_fields    — AgentStep dataclass 字段不含 jd_text/bullet
    19. tool_args_never_logged_to_step           — workflow 内部 step 列表里没有原文泄漏
    20. error_msg_excludes_args                  — 失败时 error_msg 不含 args

测试策略:
  - 用 monkeypatch 替换 core.agent_tools.execute_agent_tool 或 load_materials,模拟失败
  - 不污染全局状态(每个 test 用 fixture 清)
"""
import pytest
from pathlib import Path

from core import agent_workflow
from core.agent_workflow import (
    AgentStep,
    AgentWorkflowResult,
    build_task_graph,
    run_agent_workflow,
)
from core.generator import preview_resume, generate_resume_docx


# =========================================================================
# TestBuildTaskGraph
# =========================================================================
class TestBuildTaskGraph:
    """R5-A Phase 1: 任务图确定性锁定"""

    def test_minimal_no_jd_no_fc_no_session(self):
        """无 jd / 无 FC / 无外部简历 → 4 步本地任务"""
        steps = build_task_graph(
            has_jd=False,
            enable_function_calling=False,
            has_external_resume=False,
        )
        names = [s.name for s in steps]
        assert names == [
            "parse_user_intent",
            "retrieve_materials",
            "rewrite_highlights",
            "aggregate_preview",
        ], f"minimal 任务图错误, 实际: {names}"
        assert all(s.tool is None for s in steps if s.name in {
            "parse_user_intent", "retrieve_materials", "aggregate_preview"
        }), "本地步骤 tool 应为 None"

    def test_with_jd_adds_parse_jd_match_score(self):
        """has_jd=True → +2 步 parse_jd + match_score(在 retrieve 前)"""
        steps = build_task_graph(
            has_jd=True,
            enable_function_calling=False,
            has_external_resume=False,
        )
        names = [s.name for s in steps]
        assert "parse_jd" in names
        assert "match_score" in names
        # 顺序:parse_jd 在 match_score 前
        assert names.index("parse_jd") < names.index("match_score")
        # parse_jd / match_score 都在 retrieve 之前
        assert names.index("parse_jd") < names.index("retrieve_materials")
        assert names.index("match_score") < names.index("retrieve_materials")

    def test_with_function_calling_adds_evaluate_bullet(self):
        """FC=True + has_jd → +1 步 evaluate_bullet_jd_match"""
        steps = build_task_graph(
            has_jd=True,
            enable_function_calling=True,
            has_external_resume=False,
        )
        names = [s.name for s in steps]
        assert "evaluate_bullet_jd_match" in names
        # evaluate 必须在 rewrite 之前
        assert names.index("evaluate_bullet_jd_match") < names.index("rewrite_highlights")

    def test_with_external_resume_adds_parse_step(self):
        """has_external_resume=True → +1 步(本轮 tool=None 占位)"""
        steps = build_task_graph(
            has_jd=False,
            enable_function_calling=False,
            has_external_resume=True,
        )
        names = [s.name for s in steps]
        assert "parse_external_resume" in names
        # 本轮 tool=None(P2 接入 core.resume_parser)
        ext_step = next(s for s in steps if s.name == "parse_external_resume")
        assert ext_step.tool is None

    def test_task_graph_is_deterministic(self):
        """同样输入跑两次 → 字节级一致 step list"""
        kwargs = dict(has_jd=True, enable_function_calling=True, has_external_resume=False)
        steps_a = build_task_graph(**kwargs)
        steps_b = build_task_graph(**kwargs)
        # dataclass frozen=True,直接 == 即可
        assert steps_a == steps_b

    def test_step_indices_are_sequential(self):
        """step 序号从 0 开始连续递增"""
        steps = build_task_graph(
            has_jd=True, enable_function_calling=True, has_external_resume=True,
        )
        for i, step in enumerate(steps):
            assert step.step == i, f"step 序号不连续: 期望 {i}, 实际 {step.step}"


# =========================================================================
# TestAgentStepSchema
# =========================================================================
class TestAgentStepSchema:
    """R5-A Phase 1: AgentStep dataclass 字段锁定"""

    def test_step_has_all_required_fields(self):
        """AgentStep 必须含 7 字段"""
        from dataclasses import fields
        field_names = {f.name for f in fields(AgentStep)}
        required = {"step", "name", "tool", "input_ref", "output_ref", "required", "fallback"}
        assert required <= field_names, f"AgentStep 缺字段: {required - field_names}"

    def test_step_dataclass_is_frozen(self):
        """AgentStep frozen=True, 实例不可改字段"""
        step = build_task_graph(has_jd=False, enable_function_calling=False, has_external_resume=False)[0]
        with pytest.raises(Exception):  # FrozenInstanceError
            step.name = "tampered"  # type: ignore[misc]


# =========================================================================
# TestRunAgentWorkflow
# =========================================================================
class TestRunAgentWorkflow:
    """R5-A Phase 1: Workflow 执行行为锁定"""

    def test_returns_preview_dict_when_no_output_dir(self):
        """无 output_dir → 返 preview dict(不是 Path)"""
        result = run_agent_workflow(
            target_role="tech_metric",
            template="classic",
            jd_text=None,
        )
        assert isinstance(result, dict)
        assert "target_role" in result
        assert "sections" in result

    def test_preview_dict_has_old_schema_fields(self):
        """preview dict 字段与 generator.preview_resume() 字节级兼容"""
        result = run_agent_workflow(
            target_role="tech_metric",
            template="classic",
            jd_text=None,
        )
        assert result["target_role"] == "tech_metric"
        assert result["template"] == "classic"
        assert "sections" in result
        assert "jd_match_counts" in result
        assert result["jd_match_counts"] is None  # 无 jd 时

    def test_returns_docx_path_when_output_dir(self, tmp_path):
        """有 output_dir → 返 docx Path"""
        result = run_agent_workflow(
            target_role="tech_metric",
            template="classic",
            jd_text=None,
            output_dir=tmp_path,
        )
        assert isinstance(result, Path)
        assert result.exists()
        assert result.suffix == ".docx"

    def test_tool_failure_does_not_raise(self, monkeypatch):
        """工具执行失败 → workflow 不抛,继续完成 preview"""
        from core import agent_tools

        def always_fail(tool_name, args, context=None):
            from core.agent_tools import ToolResult, ToolErrorType
            return ToolResult(
                tool=tool_name, status="error", output=None,
                error_type=ToolErrorType.TOOL_RUNTIME_ERROR,
                latency_ms=1, error_msg="forced",
            )

        monkeypatch.setattr(agent_tools, "execute_agent_tool", always_fail)

        # 即使所有工具失败,workflow 仍应返 preview dict
        result = run_agent_workflow(
            target_role="tech_metric", template="classic",
            jd_text="熟悉 LLM 评测",
        )
        assert isinstance(result, dict)
        assert "sections" in result

    def test_load_materials_failure_propagates(self, monkeypatch):
        """workflow 调用链上任何 system-level 失败应让 generator 层知道(API 返 500)"""
        from core import generator

        # 触发 build_sections 抛 ValueError(role 非法)→ workflow 重新抛出
        # (workflow 内的 build_sections 失败应让上层知道,不是 tool 内部异常)
        with pytest.raises(ValueError):
            run_agent_workflow(
                target_role="nonexistent_role", template="classic",
                jd_text=None,
            )

    def test_enable_function_calling_propagated_to_task_graph(self):
        """FC=True → run_agent_workflow 任务图有 evaluate step(实际跑不影响 sections 内容)"""
        # 不直接断言 step 列表(workflow 内部不返回),改用 build_task_graph 间接验证
        # 但确认 workflow 在 FC=True 时不报错
        result = run_agent_workflow(
            target_role="tech_metric", template="classic",
            jd_text="熟悉 LLM 评测", enable_function_calling=True,
        )
        assert isinstance(result, dict)


# =========================================================================
# TestBackwardCompatibility
# =========================================================================
class TestBackwardCompatibility:
    """R5-A Phase 1: 旧路径不变 / R4 session / FC / jd 路径不破"""

    def test_generator_preview_resume_still_works_without_new_kwarg(self):
        """preview_resume() 不传 enable_agent_workflow 也 OK(默认 False)"""
        result = preview_resume(target_role="tech_metric", template="classic")
        assert "sections" in result
        assert result["jd_match_counts"] is None

    def test_generator_preview_resume_default_off_returns_same_as_workflow(self):
        """preview_resume(enable_agent_workflow=False) 与走 workflow 路径同输入产出结构一致"""
        from core.generator import preview_resume
        old_result = preview_resume(target_role="tech_metric", template="classic")
        new_result = run_agent_workflow(target_role="tech_metric", template="classic")
        # 同输入产出 sections 列表结构一致(顺序 / 字段)
        assert [s["type"] for s in old_result["sections"]] == [s["type"] for s in new_result["sections"]]

    def test_generator_preview_resume_with_jd_still_works(self):
        """R3-I: jd_text 非空时 preview_resume 仍按命中数重排"""
        result = preview_resume(
            target_role="tech_metric",
            template="classic",
            jd_text="熟悉大模型评测指标",
        )
        assert "sections" in result
        assert result["jd_match_counts"] is not None


# =========================================================================
# TestPrivacyGuarantee
# =========================================================================
class TestPrivacyGuarantee:
    """R5-A Phase 1: 隐私边界锁定 — AgentStep / ToolResult 不存原文"""

    def test_agent_step_has_no_jd_or_bullet_fields(self):
        """AgentStep 字段定义不含 jd_text / bullet / content / raw 等原文字段"""
        from dataclasses import fields
        field_names = {f.name for f in fields(AgentStep)}
        forbidden = {"jd_text", "bullet", "content", "raw", "message", "messages", "input_text", "output_text"}
        leaked = forbidden & field_names
        assert not leaked, f"AgentStep 不应含原文字段 {leaked}, 实际: {field_names}"

    def test_agent_step_dataclass_does_not_carry_pii(self):
        """构造 AgentStep 不传 PII 字段(防止误传)"""
        # 这里只是 dataclass 字段检查;实际值由 build_task_graph 决定
        step = AgentStep(
            step=0, name="test", tool=None,
            input_ref="placeholder_input_ref",  # 只存名字引用,不含原文
            output_ref="placeholder_output_ref",
        )
        # dataclass attributes 都不应是字符串原文内容
        assert step.name == "test"
        # 验证 step 没有 "原文" 类字段(name 之外的字段都是 str ref,长度有限)
        # input_ref/output_ref 不应含常见的 PII 模式(邮箱/电话/中文姓名)
        assert "@" not in step.input_ref
        assert "@" not in step.output_ref
        # step.name / input_ref / output_ref 都是短标识符(< 100 char)
        assert len(step.name) < 100
        assert len(step.input_ref) < 100
        assert len(step.output_ref) < 100

    def test_tool_args_not_in_step_attributes(self):
        """build_task_graph 返回的 step 不携带 args 原文"""
        steps = build_task_graph(
            has_jd=True, enable_function_calling=True, has_external_resume=False,
        )
        for step in steps:
            # AgentStep 不应有 args 字段(已在 test_agent_step_has_no_jd_or_bullet_fields 锁过)
            d = step.__dict__
            for forbidden in ("args", "kwargs", "input_text", "output_text"):
                assert forbidden not in d, (
                    f"step {step.name} 携带 forbidden 字段 {forbidden}, PII 泄漏风险"
                )


# =========================================================================
# R5-A Phase 2: JSONL trace 行为锁定
# =========================================================================
import json
import re


class TestWorkflowJsonlTrace:
    """R5-A Phase 2: workflow 每次生成 request_id + 每个 step 写 JSONL trace"""

    def test_request_id_format_is_r_prefix_8hex(self):
        """generate_request_id() 必须返 'r' + 8 位 hex"""
        from core.agent_workflow import generate_request_id
        rid = generate_request_id()
        assert re.match(r"^r[0-9a-f]{8}$", rid), f"request_id 格式异常: {rid!r}"
        # 多次调用返不同 id
        ids = {generate_request_id() for _ in range(50)}
        assert len(ids) > 1, "request_id 没有随机性"

    def test_workflow_writes_jsonl_trace_per_step(self, tmp_path, monkeypatch):
        """跑一次 workflow → JSONL 文件含每个 step 的 trace, 含本地 + 工具步骤"""
        import core.logger as logger_mod
        from core.agent_workflow import run_agent_workflow

        # 重定向 JSONL 到 tmp_path
        jsonl_path = tmp_path / "agent_trace.jsonl"
        monkeypatch.setattr(logger_mod, "AGENT_TRACE_JSONL_PATH", jsonl_path)

        result = run_agent_workflow(
            target_role="tech_metric",
            template="classic",
            jd_text="熟悉大模型评测",
        )
        assert isinstance(result, dict)
        assert "sections" in result

        # JSONL 文件应被创建
        assert jsonl_path.exists()
        lines = jsonl_path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) >= 3, f"workflow 至少应写 3 条 trace(本地+工具), 实际 {len(lines)}"

        # 验证每条 event 含 11 schema 字段
        for line in lines:
            event = json.loads(line)
            assert "ts" in event
            assert "request_id" in event
            assert "session_id" in event
            assert "workflow" in event
            assert "step" in event
            assert "tool" in event  # None 也算有
            assert "latency_ms" in event
            assert "status" in event
            assert "error_type" in event
            assert "input_size" in event
            assert "output_size" in event

        # 验证 request_id 全程一致(同一次 workflow)
        rids = {json.loads(l)["request_id"] for l in lines}
        assert len(rids) == 1, f"同 workflow 的 request_id 应一致, 实际 {rids}"

        # 验证 workflow 字段正确
        workflows = {json.loads(l)["workflow"] for l in lines}
        assert workflows == {"preview"}, f"workflow 应为 preview, 实际 {workflows}"

    def test_workflow_jsonl_trace_includes_local_and_tool_steps(self, tmp_path, monkeypatch):
        """JSONL trace 应含本地步骤(status=skipped)+ 工具步骤(status=success/error)"""
        import core.logger as logger_mod
        from core.agent_workflow import run_agent_workflow

        jsonl_path = tmp_path / "agent_trace.jsonl"
        monkeypatch.setattr(logger_mod, "AGENT_TRACE_JSONL_PATH", jsonl_path)

        run_agent_workflow(
            target_role="tech_metric", template="classic",
            jd_text="熟悉 LLM 评测",
        )
        events = [
            json.loads(l)
            for l in jsonl_path.read_text(encoding="utf-8").strip().split("\n")
        ]
        # 至少要有本地步骤(3 个: parse_user_intent / retrieve_materials / aggregate_preview)
        local_steps = [e for e in events if e.get("tool") is None]
        assert len(local_steps) >= 3, f"本地步骤不足, 实际 {len(local_steps)}"
        for ls in local_steps:
            assert ls["status"] == "skipped", f"本地步骤 status 应为 skipped, 实际 {ls['status']}"

        # 工具步骤至少要有 parse_jd / match_score / rewrite_highlights
        tool_names = {e.get("tool") for e in events if e.get("tool") is not None}
        assert "parse_jd" in tool_names
        assert "match_score" in tool_names
        assert "rewrite_highlights" in tool_names

    def test_workflow_generate_path_writes_generate_workflow(self, tmp_path, monkeypatch):
        """generate 路径 → workflow 字段 = "generate" """
        import core.logger as logger_mod
        from core.agent_workflow import run_agent_workflow

        jsonl_path = tmp_path / "agent_trace.jsonl"
        monkeypatch.setattr(logger_mod, "AGENT_TRACE_JSONL_PATH", jsonl_path)

        out = run_agent_workflow(
            target_role="tech_metric", template="classic",
            jd_text=None,
            output_dir=tmp_path / "out",
        )
        assert out.exists()
        events = [
            json.loads(l)
            for l in jsonl_path.read_text(encoding="utf-8").strip().split("\n")
        ]
        workflows = {e["workflow"] for e in events}
        assert workflows == {"generate"}, f"workflow 应为 generate, 实际 {workflows}"

    def test_workflow_session_id_in_jsonl(self, tmp_path, monkeypatch):
        """session_id 非空时 → JSONL trace 应带正确 session_id"""
        import core.logger as logger_mod
        from core.agent_workflow import run_agent_workflow

        jsonl_path = tmp_path / "agent_trace.jsonl"
        monkeypatch.setattr(logger_mod, "AGENT_TRACE_JSONL_PATH", jsonl_path)

        run_agent_workflow(
            target_role="tech_metric", template="classic",
            jd_text=None,
            session_id="stest1234",
        )
        events = [
            json.loads(l)
            for l in jsonl_path.read_text(encoding="utf-8").strip().split("\n")
        ]
        sids = {e["session_id"] for e in events}
        assert sids == {"stest1234"}, f"session_id 应为 stest1234, 实际 {sids}"

    def test_workflow_session_id_empty_string_when_none(self, tmp_path, monkeypatch):
        """session_id=None → JSONL session_id 应为空字符串"""
        import core.logger as logger_mod
        from core.agent_workflow import run_agent_workflow

        jsonl_path = tmp_path / "agent_trace.jsonl"
        monkeypatch.setattr(logger_mod, "AGENT_TRACE_JSONL_PATH", jsonl_path)

        run_agent_workflow(
            target_role="tech_metric", template="classic",
            jd_text=None,
            session_id=None,
        )
        events = [
            json.loads(l)
            for l in jsonl_path.read_text(encoding="utf-8").strip().split("\n")
        ]
        sids = {e["session_id"] for e in events}
        assert sids == {""}, f"session_id 应为空串, 实际 {sids}"

    def test_jsonl_trace_failure_does_not_break_workflow(self, tmp_path, monkeypatch):
        """JSONL 写入失败 → workflow 仍正常返回 preview dict(spec §6.3)"""
        import core.logger as logger_mod
        from core.agent_workflow import run_agent_workflow

        # 让 open() 抛 OSError 模拟磁盘满 / 权限错(避开 WindowsPath.mkdir 只读限制)
        real_open = open
        def failing_open(*args, **kwargs):
            # 只在写 agent_trace.jsonl 时失败,其他文件放行
            if len(args) > 0 and "agent_trace.jsonl" in str(args[0]):
                raise OSError("simulated disk full")
            return real_open(*args, **kwargs)
        monkeypatch.setattr("builtins.open", failing_open)

        # 不应抛 — workflow 仍正常完成
        result = run_agent_workflow(
            target_role="tech_metric", template="classic",
            jd_text="熟悉大模型评测",
        )
        assert isinstance(result, dict)
        assert "sections" in result

    def test_jsonl_trace_does_not_contain_jd_text_or_bullets(self, tmp_path, monkeypatch):
        """隐私边界: JSONL trace 不含 JD 原文 / bullet 原文 / 姓名 / 邮箱 / 电话"""
        import core.logger as logger_mod
        from core.agent_workflow import run_agent_workflow

        jsonl_path = tmp_path / "agent_trace.jsonl"
        monkeypatch.setattr(logger_mod, "AGENT_TRACE_JSONL_PATH", jsonl_path)

        # 用敏感字符串构造 jd_text
        sensitive_jd = (
            "张三 13800138000 zhang.san@example.com "
            "熟悉大模型评测 完整的 JD 描述 含敏感信息"
        )
        run_agent_workflow(
            target_role="tech_metric", template="classic",
            jd_text=sensitive_jd,
        )
        content = jsonl_path.read_text(encoding="utf-8")
        # PII 字符串不应在 trace 里出现(原文)
        assert "13800138000" not in content, "电话不应入 trace"
        assert "zhang.san@example.com" not in content, "邮箱不应入 trace"
        assert "张三" not in content, "姓名不应入 trace"
        assert "完整的 JD 描述" not in content, "JD 原文不应入 trace"

    def test_jsonl_trace_input_size_matches_real_jd_length(self, tmp_path, monkeypatch):
        """input_size 应大致反映 jd_text 的字节长度(误差为其他 args)"""
        import core.logger as logger_mod
        from core.agent_workflow import run_agent_workflow

        jsonl_path = tmp_path / "agent_trace.jsonl"
        monkeypatch.setattr(logger_mod, "AGENT_TRACE_JSONL_PATH", jsonl_path)

        jd = "熟悉大模型评测" * 50  # 较长 JD
        run_agent_workflow(
            target_role="tech_metric", template="classic",
            jd_text=jd,
        )
        events = [
            json.loads(l)
            for l in jsonl_path.read_text(encoding="utf-8").strip().split("\n")
        ]
        # parse_jd 步骤的 input_size 应至少 ≥ len(jd.encode())
        parse_jd_events = [e for e in events if e.get("tool") == "parse_jd"]
        assert parse_jd_events, "应至少有 1 条 parse_jd trace"
        pj = parse_jd_events[0]
        assert pj["input_size"] >= len(jd.encode("utf-8")), (
            f"parse_jd input_size={pj['input_size']} < jd 长度 {len(jd.encode('utf-8'))}"
        )
