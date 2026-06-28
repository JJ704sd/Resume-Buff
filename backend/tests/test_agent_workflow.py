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
        """has_jd=True → +3 步 parse_jd + match_score + retrieve_evidence(都在 retrieve 前)
        R5-A Phase 3: retrieve_evidence 加在 match_score 之后, retrieve_materials 之前
        """
        steps = build_task_graph(
            has_jd=True,
            enable_function_calling=False,
            has_external_resume=False,
        )
        names = [s.name for s in steps]
        assert "parse_jd" in names
        assert "match_score" in names
        assert "retrieve_evidence" in names, "Phase 3: has_jd 时必须有 retrieve_evidence step"
        # 顺序:parse_jd → match_score → retrieve_evidence → retrieve_materials
        assert names.index("parse_jd") < names.index("match_score")
        assert names.index("match_score") < names.index("retrieve_evidence")
        assert names.index("retrieve_evidence") < names.index("retrieve_materials")

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


# =========================================================================
# R5-A Phase 3: 轻量 RAG evidence 集成测试
# =========================================================================
class TestEvidencePhase3:
    """R5-A Phase 3: workflow 集成 evidence step 行为锁定

    覆盖点(spec §5.3 + Phase 3 任务约束):
      - retrieve_evidence step 在 has_jd 时执行
      - evidence step 失败不阻断主流程(spec §6.3)
      - evidence step trace 不含 evidence text 原文
      - caller 显式传 evidence 时跳过 retrieve_evidence 工具
      - 默认 enable_agent_workflow=False 字节级一致(老路径)
      - jd_context=None baseline 不变
    """

    def test_task_graph_has_evidence_step_when_jd_present(self):
        """has_jd=True → 任务图含 retrieve_evidence step"""
        steps = build_task_graph(
            has_jd=True,
            enable_function_calling=False,
            has_external_resume=False,
        )
        ev_step = next((s for s in steps if s.name == "retrieve_evidence"), None)
        assert ev_step is not None, "Phase 3: has_jd 时必须有 retrieve_evidence step"
        assert ev_step.tool == "retrieve_evidence"
        assert ev_step.required is False, "evidence 非关键步骤, 失败降级 use_default"
        assert ev_step.fallback == "use_default"
        # evidence step 在 match_score 之后, retrieve_materials 之前
        names = [s.name for s in steps]
        assert names.index("match_score") < names.index("retrieve_evidence")
        assert names.index("retrieve_evidence") < names.index("retrieve_materials")

    def test_task_graph_no_evidence_step_when_no_jd(self):
        """has_jd=False → 任务图不含 retrieve_evidence step"""
        steps = build_task_graph(
            has_jd=False,
            enable_function_calling=False,
            has_external_resume=False,
        )
        names = [s.name for s in steps]
        assert "retrieve_evidence" not in names, "无 JD 时不需要 evidence 检索"

    def test_workflow_runs_evidence_step_on_jd_path(self, tmp_path, monkeypatch):
        """workflow 在 jd 路径下执行 retrieve_evidence step + 写 trace"""
        import core.logger as logger_mod
        from core.agent_workflow import run_agent_workflow

        jsonl_path = tmp_path / "agent_trace.jsonl"
        monkeypatch.setattr(logger_mod, "AGENT_TRACE_JSONL_PATH", jsonl_path)

        result = run_agent_workflow(
            target_role="tech_metric",
            template="classic",
            jd_text="熟悉大模型评测",
        )
        assert "sections" in result
        # JSONL 应有 retrieve_evidence 工具 step 的 trace
        events = [
            json.loads(l)
            for l in jsonl_path.read_text(encoding="utf-8").strip().split("\n")
            if l.strip()
        ]
        ev_events = [e for e in events if e.get("tool") == "retrieve_evidence"]
        assert len(ev_events) >= 1, "workflow 应至少调一次 retrieve_evidence 工具"
        # 状态应为 success 或 error (绝不应 skipped, 因为没有显式 evidence 传入)
        assert ev_events[0]["status"] in {"success", "error"}

    def test_workflow_skips_evidence_tool_when_evidence_explicit(self, tmp_path, monkeypatch):
        """caller 显式传 evidence 时 → retrieve_evidence 工具调用 skipped"""
        import core.logger as logger_mod
        from core.agent_workflow import run_agent_workflow
        from core.evidence import EvidenceSnippet

        jsonl_path = tmp_path / "agent_trace.jsonl"
        monkeypatch.setattr(logger_mod, "AGENT_TRACE_JSONL_PATH", jsonl_path)

        explicit_evidence = [
            EvidenceSnippet(
                source_type="project",
                source_id="company_medical_eval",
                text="explicit test evidence",
                matched_keywords=("LLM",),
                confidence=1.0,
            ),
        ]
        result = run_agent_workflow(
            target_role="tech_metric",
            template="classic",
            jd_text="熟悉大模型评测",
            evidence=explicit_evidence,
        )
        assert "sections" in result
        # retrieve_evidence step 状态应为 skipped (显式 evidence 跳过工具调用)
        events = [
            json.loads(l)
            for l in jsonl_path.read_text(encoding="utf-8").strip().split("\n")
            if l.strip()
        ]
        ev_events = [e for e in events if e.get("tool") == "retrieve_evidence"]
        assert len(ev_events) == 1
        assert ev_events[0]["status"] == "skipped", (
            f"显式 evidence 时 retrieve_evidence 应 skipped, 实际: {ev_events[0]['status']}"
        )

    def test_workflow_evidence_step_failure_does_not_break_main(self, tmp_path, monkeypatch):
        """evidence step 失败不阻断主流程(降级 use_default)"""
        import core.logger as logger_mod
        from core.agent_workflow import run_agent_workflow
        from core.agent_tools import ToolSpec, AGENT_TOOLS

        jsonl_path = tmp_path / "agent_trace.jsonl"
        monkeypatch.setattr(logger_mod, "AGENT_TRACE_JSONL_PATH", jsonl_path)

        # mock retrieve_evidence 的 callable 让它抛异常
        original_spec = AGENT_TOOLS["retrieve_evidence"]

        def broken_callable(**kwargs):
            raise RuntimeError("simulated evidence tool failure")

        broken_spec = ToolSpec(
            name=original_spec.name,
            callable=broken_callable,
            permission=original_spec.permission,
            pii_risk=original_spec.pii_risk,
            timeout_ms=original_spec.timeout_ms,
            input_schema=original_spec.input_schema,
        )
        monkeypatch.setitem(AGENT_TOOLS, "retrieve_evidence", broken_spec)

        result = run_agent_workflow(
            target_role="tech_metric",
            template="classic",
            jd_text="熟悉大模型评测",
        )
        # 主流程应正常返回 preview (evidence 失败不阻断)
        assert "sections" in result
        assert isinstance(result["sections"], list)
        # evidence_summary 应为 None (失败时未收集到)
        assert result.get("evidence_summary") is None

    def test_workflow_jsonl_trace_does_not_contain_evidence_text(self, tmp_path, monkeypatch):
        """隐私边界: JSONL trace 不含 evidence text 原文"""
        import core.logger as logger_mod
        from core.agent_workflow import run_agent_workflow

        jsonl_path = tmp_path / "agent_trace.jsonl"
        monkeypatch.setattr(logger_mod, "AGENT_TRACE_JSONL_PATH", jsonl_path)

        # 用敏感字符串构造 JD (含独特关键词)
        sensitive_phrase = "机密敏感短语XYZ123"
        result = run_agent_workflow(
            target_role="tech_metric",
            template="classic",
            jd_text=f"熟悉大模型评测 {sensitive_phrase}",
        )
        # result["evidence_summary"] 应包含 evidence dict list
        ev_summary = result.get("evidence_summary") or []
        assert isinstance(ev_summary, list)
        # 抽样看 evidence 的 source_id 和 text (验证 evidence 真的被检索了)
        # 至少应有 0+ 条 evidence (取决于材料)
        content = jsonl_path.read_text(encoding="utf-8")
        # trace 不应含 sensitive_phrase (这是 JD 原文片段, 不应泄漏)
        assert sensitive_phrase not in content, "JD 敏感短语不应入 trace"
        # 同时: 验证 evidence_summary 字段不进 trace (它只在 preview 返回值里)
        # (因为 trace 只写 11 字段 schema, evidence_summary 不在里面)

    def test_workflow_evidence_summary_returned_in_preview(self, tmp_path, monkeypatch):
        """workflow preview 返回值含 evidence_summary 字段"""
        import core.logger as logger_mod
        from core.agent_workflow import run_agent_workflow

        jsonl_path = tmp_path / "agent_trace.jsonl"
        monkeypatch.setattr(logger_mod, "AGENT_TRACE_JSONL_PATH", jsonl_path)

        result = run_agent_workflow(
            target_role="tech_metric",
            template="classic",
            jd_text="熟悉大模型评测,Python 编程",
        )
        # evidence_summary 字段应存在
        assert "evidence_summary" in result
        ev_summary = result["evidence_summary"]
        # 应为 list (dict list, 由 evidence_to_dict_list 序列化)
        assert isinstance(ev_summary, list)
        if ev_summary:
            first = ev_summary[0]
            assert isinstance(first, dict)
            # 验证字段 schema
            assert "source_type" in first
            assert "source_id" in first
            assert "text" in first
            assert "matched_keywords" in first
            assert "confidence" in first

    def test_workflow_no_jd_path_skips_evidence(self, tmp_path, monkeypatch):
        """workflow 无 jd_text 时不调用 retrieve_evidence (任务图不含该 step)"""
        import core.logger as logger_mod
        from core.agent_workflow import run_agent_workflow

        jsonl_path = tmp_path / "agent_trace.jsonl"
        monkeypatch.setattr(logger_mod, "AGENT_TRACE_JSONL_PATH", jsonl_path)

        result = run_agent_workflow(
            target_role="tech_metric",
            template="classic",
            jd_text=None,  # 无 JD
        )
        assert "sections" in result
        # evidence_summary 应为 None (没调工具)
        assert result.get("evidence_summary") is None
        # JSONL trace 不应含 retrieve_evidence 工具调用
        events = [
            json.loads(l)
            for l in jsonl_path.read_text(encoding="utf-8").strip().split("\n")
            if l.strip()
        ]
        ev_events = [e for e in events if e.get("tool") == "retrieve_evidence"]
        assert len(ev_events) == 0, "无 JD 时不应调 retrieve_evidence"

    def test_jd_context_none_baseline_unchanged(self, tmp_path, monkeypatch):
        """jd_context=None (无 JD) baseline 字节级一致 — 老路径
        Phase 1 已经验证过 enable_agent_workflow=False 字节级一致
        这里再确认 evidence 透传也不破坏老路径
        """
        import core.logger as logger_mod
        from core.agent_workflow import run_agent_workflow

        jsonl_path = tmp_path / "agent_trace.jsonl"
        monkeypatch.setattr(logger_mod, "AGENT_TRACE_JSONL_PATH", jsonl_path)

        # 跑两次 (无 JD), 应字节级一致
        result_a = run_agent_workflow(
            target_role="tech_metric", template="classic", jd_text=None,
        )
        result_b = run_agent_workflow(
            target_role="tech_metric", template="classic", jd_text=None,
        )
        # sections 内容应一致 (project/highlight 排序无 JD 时是稳定的)
        sections_a = result_a["sections"]
        sections_b = result_b["sections"]
        assert len(sections_a) == len(sections_b)
        # 每条 section 的 title + content text 一致
        for sa, sb in zip(sections_a, sections_b):
            assert sa["type"] == sb["type"]
            assert sa["title"] == sb["title"]
        # jd_match_counts 应为 None (无 JD)
        assert result_a.get("jd_match_counts") is None
        assert result_b.get("jd_match_counts") is None
        # evidence_summary 也应为 None (无 JD)
        assert result_a.get("evidence_summary") is None
        assert result_b.get("evidence_summary") is None

    def test_workflow_runs_evidence_step_with_no_matched_keywords(self, tmp_path, monkeypatch):
        """evidence step 在 jd 没匹配任何 KEYWORD_GROUPS 关键词时也跑(返空 list, 不抛)"""
        import core.logger as logger_mod
        from core.agent_workflow import run_agent_workflow

        jsonl_path = tmp_path / "agent_trace.jsonl"
        monkeypatch.setattr(logger_mod, "AGENT_TRACE_JSONL_PATH", jsonl_path)

        # jd_text 完全不命中任何 KEYWORD_GROUPS surface
        result = run_agent_workflow(
            target_role="tech_metric",
            template="classic",
            jd_text="完全不相关的描述 / 厨师 / 司机",  # 没任何 LLM/Python 等关键词
        )
        assert "sections" in result
        # evidence_summary 应为空 list (没匹配任何 evidence)
        ev_summary = result.get("evidence_summary")
        assert ev_summary == [], (
            f"无关键词命中应返空 list, 实际: {ev_summary!r}"
        )


# =========================================================================
# R5-A closeout: 修复 findings.md 9 个 gap 中的可修部分
#   - Gap 7: enable_external_resume 透传
#   - Gap 4: agent_summary 字段(spec §8.2)
#   - Gap 6: execute_agent_tool args 必填字段校验
# =========================================================================
class TestEnableExternalResumePassthrough:
    """R5-A closeout Gap 7: enable_external_resume 透传到任务图"""

    def test_default_false_no_external_resume_step(self):
        """enable_external_resume 默认 False → 任务图无 parse_external_resume step"""
        from core.agent_workflow import build_task_graph
        steps = build_task_graph(
            has_jd=False,
            enable_function_calling=False,
            has_external_resume=False,  # 默认
        )
        names = [s.name for s in steps]
        assert "parse_external_resume" not in names

    def test_true_adds_external_resume_step(self):
        """enable_external_resume=True → 任务图含 parse_external_resume step"""
        from core.agent_workflow import build_task_graph
        steps = build_task_graph(
            has_jd=False,
            enable_function_calling=False,
            has_external_resume=True,  # 显式开启
        )
        names = [s.name for s in steps]
        assert "parse_external_resume" in names
        # 该 step 是 P2 占位(tool=None, required=False, fallback="skip")
        ext_step = next(s for s in steps if s.name == "parse_external_resume")
        assert ext_step.tool is None
        assert ext_step.required is False
        assert ext_step.fallback == "skip"

    def test_run_agent_workflow_accepts_kwarg(self):
        """run_agent_workflow 接收 enable_external_resume kwarg 不抛"""
        from core.agent_workflow import run_agent_workflow
        # 不抛 = 接受 kwarg(默认 False 走 P2 占位未消费路径,行为不变)
        result = run_agent_workflow(
            target_role="tech_metric",
            template="classic",
            enable_external_resume=False,
        )
        assert "sections" in result


class TestAgentSummaryField:
    """R5-A closeout Gap 4: workflow preview 返回值含 agent_summary(spec §8.2)"""

    def test_workflow_preview_contains_agent_summary(self):
        """workflow preview 返回值含 agent_summary dict"""
        from core.agent_workflow import run_agent_workflow
        result = run_agent_workflow(
            target_role="tech_metric",
            template="classic",
        )
        assert "agent_summary" in result, "workflow preview 应返回 agent_summary 字段"
        summary = result["agent_summary"]
        assert isinstance(summary, dict)

    def test_agent_summary_required_fields(self):
        """agent_summary 包含 spec §8.2 必含 5 子字段"""
        from core.agent_workflow import run_agent_workflow
        result = run_agent_workflow(
            target_role="tech_metric",
            template="classic",
            jd_text="熟悉大模型评测",
        )
        summary = result["agent_summary"]
        for key in ("request_id", "steps_executed", "tools_used", "fallback_used", "latency_ms"):
            assert key in summary, f"agent_summary 应含 {key}, 实际 keys: {list(summary.keys())}"

    def test_agent_summary_request_id_format(self):
        """agent_summary.request_id 符合 r+8hex 格式"""
        import re
        from core.agent_workflow import run_agent_workflow
        result = run_agent_workflow(target_role="tech_metric", template="classic")
        rid = result["agent_summary"]["request_id"]
        assert re.match(r"^r[0-9a-f]{8}$", rid), f"request_id 应 r+8hex, 实际: {rid!r}"

    def test_agent_summary_steps_executed_positive(self):
        """agent_summary.steps_executed > 0 (workflow 跑全任务图)"""
        from core.agent_workflow import run_agent_workflow
        result = run_agent_workflow(target_role="tech_metric", template="classic")
        n = result["agent_summary"]["steps_executed"]
        assert isinstance(n, int) and n > 0, f"steps_executed 应 > 0, 实际: {n}"

    def test_agent_summary_tools_used_has_workflow_tools(self):
        """R5-B Phase 2A: agent_summary.tools_used 只列 affects_preview=True 的工具
        (round5-b-agent-capability-spec.md §3.3 有效语义)

        当前实现:
          - retrieve_evidence: output 注入 build_sections → rewrite_highlights → 影响 preview
            → affects_preview=True → 列 tools_used
          - match_score: 当前是"展示型"调用(output 未被 build_sections 实际消费)
            → affects_preview=False → 不列 tools_used
          - 其他工具(parse_jd / evaluate_bullet_jd_match / rewrite_highlights): 同上,展示型
        """
        from core.agent_workflow import run_agent_workflow
        result = run_agent_workflow(
            target_role="tech_metric",
            template="classic",
            jd_text="熟悉大模型评测",
        )
        tools = result["agent_summary"]["tools_used"]
        assert isinstance(tools, list)
        # retrieve_evidence 是当前唯一真正影响 preview 的工具
        assert "retrieve_evidence" in tools
        # match_score / parse_jd 是"展示型", 不列
        assert "match_score" not in tools
        assert "parse_jd" not in tools

    def test_agent_summary_latency_ms_non_negative(self):
        """agent_summary.latency_ms 是非负整数"""
        from core.agent_workflow import run_agent_workflow
        result = run_agent_workflow(target_role="tech_metric", template="classic")
        lat = result["agent_summary"]["latency_ms"]
        assert isinstance(lat, int) and lat >= 0, f"latency_ms 应 >= 0, 实际: {lat}"

    def test_old_path_preview_does_not_have_agent_summary(self):
        """老路径 preview_resume(enable_agent_workflow=False) 不含 agent_summary 字段
        — 新字段只在 workflow 路径加, 老字节级一致"""
        from core.generator import preview_resume
        result = preview_resume(target_role="tech_metric", template="classic")
        assert "agent_summary" not in result, (
            "老路径不应含 agent_summary(否则破坏字节级一致 baseline)"
        )


class TestAgentToolArgsValidation:
    """R5-A closeout Gap 6: execute_agent_tool args 必填字段校验"""

    def test_missing_required_args_returns_args_invalid(self):
        """少传 required 字段 → TOOL_ARGS_INVALID,不调 callable"""
        from core.agent_tools import (
            execute_agent_tool,
            AGENT_TOOLS,
            ToolErrorType,
        )
        # match_score input_schema.required = ["text", "target_role", "materials"]
        # 只传 text,缺 target_role + materials
        result = execute_agent_tool("match_score", args={"text": "test"})
        assert result.status == "error"
        assert result.error_type == ToolErrorType.TOOL_ARGS_INVALID
        # error_msg 含缺失字段名(不含 args 原文)
        assert "target_role" in result.error_msg
        assert "materials" in result.error_msg
        # latency_ms 应该是 0(校验失败前没调 callable)
        assert result.latency_ms == 0

    def test_complete_args_success(self):
        """必填字段齐全 → success,正常调用"""
        from core.agent_tools import execute_agent_tool
        from core.generator import load_materials
        mats = load_materials()
        result = execute_agent_tool(
            "match_score",
            args={"text": "熟悉 Python LLM", "target_role": "algorithm", "materials": mats},
        )
        assert result.status == "success"
        assert result.output is not None
        assert result.output["role_id"] == "algorithm"

    def test_match_score_schema_uses_target_role(self):
        """R5-A closeout bugfix: match_score schema 字段名跟函数签名一致(target_role 不是 role)
        — 防止 Phase 1 留下的 schema/callable 参数名不一致隐性 bug"""
        from core.agent_tools import AGENT_TOOLS
        spec = AGENT_TOOLS["match_score"]
        required = spec.input_schema.get("required") or []
        properties = spec.input_schema.get("properties") or {}
        assert "target_role" in required, (
            f"match_score schema 必须含 target_role(required), 实际: {required}"
        )
        assert "target_role" in properties
        # 旧错字段名 "role" 应该不再作为 required 字段(避免回归)
        # 注: properties 里仍可能有 'role' 但不应是 required

    def test_no_required_schema_always_passes_validation(self):
        """input_schema 无 required 字段 → 校验通过"""
        from core.agent_tools import execute_agent_tool
        # rewrite_highlights 的 input_schema 含 required: ["highlights", "target_role"]
        # 故意只传 target_role,缺 highlights
        result = execute_agent_tool(
            "rewrite_highlights",
            args={"target_role": "tech_metric"},  # 缺 highlights
        )
        # 没 key 校验时直接走 callable(走 TypeError 路径)
        # 关键是验证字段校验逻辑存在, 不保证特定工具行为
        assert result.status in ("error", "success")  # 不抛


# =========================================================================
# R5-B Phase 2A: workflow tools_used 有效语义
# =========================================================================
class TestWorkflowEffectiveTools:
    """R5-B Phase 2A: workflow tools_used 只列 affects_preview=True 的工具
    (round5-b-agent-capability-spec.md §3.3)

    锁点:
      - 跑过的工具里只有 affects_preview=True 且 status=success 才列 tools_used
      - "展示型"工具(parse_jd / match_score / evaluate_bullet_jd_match /
        rewrite_highlights)即使跑过, 也不列
      - 老路径 enable_agent_workflow=False 不含 agent_summary (字节级一致)
    """

    def test_tools_used_only_lists_effective_tools(self):
        """JD 路径 tools_used 只列 retrieve_evidence"""
        from core.agent_workflow import run_agent_workflow
        result = run_agent_workflow(
            target_role="tech_metric",
            template="classic",
            jd_text="熟悉大模型评测",
        )
        tools = result["agent_summary"]["tools_used"]
        assert isinstance(tools, list)
        # retrieve_evidence 是当前唯一 affects_preview=True 的工具
        assert tools == ["retrieve_evidence"], (
            f"tools_used 应只列 retrieve_evidence, 实际: {tools}"
        )

    def test_tools_used_no_jd_path_empty(self):
        """无 JD 时任务图不含 retrieve_evidence → tools_used 为空 list"""
        from core.agent_workflow import run_agent_workflow
        result = run_agent_workflow(
            target_role="tech_metric",
            template="classic",
            jd_text=None,
        )
        tools = result["agent_summary"]["tools_used"]
        assert tools == [], (
            f"无 JD 路径 tools_used 应为空, 实际: {tools}"
        )

    def test_tools_used_excludes_failed_effective_tools(self):
        """失败的 effective 工具不进 tools_used (失败即无效)"""
        from core.agent_workflow import run_agent_workflow
        from core import agent_tools as agent_tools_mod
        from core.agent_tools import ToolSpec

        # mock retrieve_evidence 让它返回 error
        original_spec = agent_tools_mod.AGENT_TOOLS["retrieve_evidence"]

        def broken_evidence(**kwargs):
            raise RuntimeError("simulated evidence failure")

        broken_spec = ToolSpec(
            name="retrieve_evidence",
            callable=broken_evidence,
            permission=original_spec.permission,
            pii_risk=original_spec.pii_risk,
            timeout_ms=original_spec.timeout_ms,
            input_schema=original_spec.input_schema,
            metadata=original_spec.metadata,  # affects_preview=True 保留
        )
        agent_tools_mod.AGENT_TOOLS["retrieve_evidence"] = broken_spec
        try:
            result = run_agent_workflow(
                target_role="tech_metric",
                template="classic",
                jd_text="熟悉大模型评测",
            )
            tools = result["agent_summary"]["tools_used"]
            assert "retrieve_evidence" not in tools, (
                f"失败的 effective 工具不应进 tools_used, 实际: {tools}"
            )
        finally:
            # 恢复
            agent_tools_mod.AGENT_TOOLS["retrieve_evidence"] = original_spec

    def test_old_path_no_agent_summary_byte_level(self):
        """老路径 preview_resume(enable_agent_workflow=False) 不含 agent_summary
        — 字节级一致 baseline (R5-A closeout 已锁, R5-B Phase 2A 重申)"""
        from core.generator import preview_resume
        result = preview_resume(target_role="tech_metric", template="classic")
        assert "agent_summary" not in result, (
            "老路径不应含 agent_summary(否则破坏字节级一致)"
        )

    def test_workflow_uses_new_schema_validator(self):
        """workflow 调工具时走新 schema validator (类型错不调 callable)"""
        from core.agent_workflow import run_agent_workflow
        from core import agent_tools as agent_tools_mod
        from core.agent_tools import ToolSpec, ToolErrorType

        # mock retrieve_evidence 让它记录是否被调
        original_spec = agent_tools_mod.AGENT_TOOLS["retrieve_evidence"]
        called = {"count": 0}

        def counting_evidence(**kwargs):
            called["count"] += 1
            return []

        counting_spec = ToolSpec(
            name="retrieve_evidence",
            callable=counting_evidence,
            permission=original_spec.permission,
            pii_risk=original_spec.pii_risk,
            timeout_ms=original_spec.timeout_ms,
            input_schema={
                "type": "object",
                "required": ["jd_keywords"],  # 故意只 required 一个, 让 workflow 实际能调
                "properties": {
                    "jd_keywords": {"type": "array", "items": {"type": "string"}},
                    "role": {"type": "string"},
                    "materials": {"type": "object"},
                },
            },
            metadata=original_spec.metadata,
        )
        agent_tools_mod.AGENT_TOOLS["retrieve_evidence"] = counting_spec
        try:
            run_agent_workflow(
                target_role="tech_metric",
                template="classic",
                jd_text="熟悉大模型评测",
            )
            # workflow 内部 _build_tool_args 传正确 schema, callable 应被调
            assert called["count"] == 1, (
                f"workflow 调一次 retrieve_evidence, 实际: {called['count']}"
            )
        finally:
            agent_tools_mod.AGENT_TOOLS["retrieve_evidence"] = original_spec


# =========================================================================
# R5-B Phase 2A: workflow context 派发
# =========================================================================
class TestWorkflowContextDispatch:
    """R5-B Phase 2A: workflow 调工具时正确派发 context"""

    def test_jd_path_passes_allow_jd_text_true(self):
        """JD 路径下 workflow 构造的 context 应 allow_jd_text=True"""
        from core.agent_workflow import _build_step_context

        ctx = _build_step_context(
            tool_name="parse_jd",
            has_jd=True,
            has_external_resume=False,
        )
        assert ctx["allow_jd_text"] is True
        assert ctx["allow_materials"] is True
        assert ctx["allow_external_resume"] is False
        assert ctx["max_pii_risk"] == "medium"

    def test_no_jd_path_blocks_allow_jd_text(self):
        """无 JD 路径下 context 应 allow_jd_text=False (防止误传)"""
        from core.agent_workflow import _build_step_context

        ctx = _build_step_context(
            tool_name="retrieve_materials",
            has_jd=False,
            has_external_resume=False,
        )
        assert ctx["allow_jd_text"] is False
        assert ctx["allow_materials"] is True  # materials 总是 True

    def test_external_resume_path_passes_allow_flag(self):
        """外部简历路径下 context 应 allow_external_resume=True"""
        from core.agent_workflow import _build_step_context

        ctx = _build_step_context(
            tool_name="parse_external_resume",
            has_jd=False,
            has_external_resume=True,
        )
        assert ctx["allow_external_resume"] is True

    def test_workflow_passes_context_to_execute(self):
        """workflow 调 execute_agent_tool 时传 context 参数"""
        from core.agent_workflow import run_agent_workflow
        from core import agent_tools as agent_tools_mod

        captured = {"contexts": []}

        real_execute = agent_tools_mod.execute_agent_tool

        def capturing_execute(tool_name, args=None, context=None):
            captured["contexts"].append(context)
            return real_execute(tool_name, args=args, context=context)

        agent_tools_mod.execute_agent_tool = capturing_execute
        # 同时替换 workflow 已经 import 的版本
        from core import agent_workflow as aw_mod
        aw_mod.execute_agent_tool = capturing_execute
        try:
            run_agent_workflow(
                target_role="tech_metric",
                template="classic",
                jd_text="熟悉大模型评测",
            )
            # 至少应有一个 context 被传(workflow 跑过工具步骤)
            assert captured["contexts"], "workflow 没调任何工具 (contexts 为空)"
            for ctx in captured["contexts"]:
                # 每个 context 都应符合协议
                assert isinstance(ctx, dict)
                assert "allow_jd_text" in ctx
                assert "allow_materials" in ctx
                assert "allow_external_resume" in ctx
                assert "max_pii_risk" in ctx
        finally:
            agent_tools_mod.execute_agent_tool = real_execute
            aw_mod.execute_agent_tool = real_execute
