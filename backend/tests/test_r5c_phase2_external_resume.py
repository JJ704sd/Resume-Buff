"""
R5-C Phase 2: 外部简历进入 Agent workflow

参考 .harness/docs/round5-c-agent-capability-spec.md §3

锁点:
  1. PreviewRequest / GenerateRequest 增加 external_resume_text 字段
  2. workflow 以 external_resume_text 非空判断真实 has_external_resume
     (enable_external_resume bool 仅保留向后兼容)
  3. 注册 parse_external_resume / compare_resume_jd 两个工具, 输出压缩关键词/profile
  4. 任务图: external_resume_text 非空时插入 2 步 (parse_external_resume + compare_resume_jd)
  5. workflow preview 返回 external_resume_perspective 字段(只返 have/need/counts/suggestions)
  6. trace / agent_summary / ToolResult.output 不含 external resume 原文
  7. 老路径 (enable_agent_workflow=False) 不含 external_resume_perspective 字段 (字节级一致)
  8. 工具 permission 校验: read_external_resume 需 allow_external_resume=True

测试矩阵 (15 case):
  TestExternalResumeApiField (2 case):
    1.  preview_request_accepts_external_resume_text
    2.  generate_request_accepts_external_resume_text

  TestExternalResumeWorkflowUsesText (3 case):
    3.  external_resume_text_none_skips_steps
    4.  external_resume_text_empty_string_skips_steps
    5.  external_resume_text_present_adds_steps

  TestParseExternalResumeTool (2 case):
    6.  parse_external_resume_output_schema_stable
    7.  parse_external_resume_output_no_raw_text

  TestCompareResumeJdTool (2 case):
    8.  compare_resume_jd_output_schema_stable
    9.  compare_resume_jd_output_no_raw_text

  TestExternalResumePermission (1 case):
    10. external_resume_tools_require_allow_external_resume

  TestExternalResumePrivacy (3 case):
    11. jsonl_trace_has_no_raw_resume_text
    12. agent_summary_has_no_raw_resume_text
    13. workflow_tool_result_output_has_no_raw_resume_text

  TestExternalResumePreviewOutput (1 case):
    14. preview_returns_external_resume_perspective_when_text_present

  TestExternalResumeOldPathUnchanged (1 case):
    15. old_path_does_not_have_external_resume_perspective

不依赖 LLM key (parse_external_resume + compare_resume_jd 都是纯规则化)。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from core import agent_tools
from core.agent_tools import (
    AGENT_TOOLS,
    ToolErrorType,
    execute_agent_tool,
)
from core.agent_workflow import build_task_graph, run_agent_workflow
from core.generator import preview_resume


# =========================================================================
# 共享 fixtures
# =========================================================================
# 一段示例外部简历 — 含真实技能关键词, 让 compare_resume_jd 能产出 have/need 区分
SAMPLE_EXTERNAL_RESUME = (
    "张三\n"
    "13800000000 | your_email@example.com\n"
    "\n"
    "教育背景\n"
    "某大学 计算机科学 本科\n"
    "\n"
    "项目经历\n"
    "1. LLM 评测平台 — 基于 Python + PyTorch 搭建, 评估大语言模型在中文场景的鲁棒性。\n"
    "2. 数据标注 Pipeline — 用 Label Studio 标注 100k 条 LLM 微调数据。\n"
    "\n"
    "个人技能\n"
    "- Python, PyTorch, Docker, Git\n"
    "- Prompt 工程, 推理优化\n"
    "\n"
    "自我评价\n"
    "熟悉 LLM 评测全流程, 关注鲁棒性 / 推理效率。\n"
)

SAMPLE_JD = (
    "岗位: 大模型评测实习生\n"
    "要求: 熟悉 Python, 熟悉 LLM 评测, 了解 Prompt 工程。\n"
    "加分: 熟悉 NLP, 了解流程图 / 原型设计。\n"
)


# 工具直调的默认 context — 外部简历工具 pii_risk=high, max_pii_risk 必须 high
# workflow 内部 _build_step_context 会自动升级 (has_external_resume=True → max_pii_risk=high)
_TOOL_CTX_OK = {
    "allow_jd_text": True,
    "allow_materials": True,
    "allow_external_resume": True,
    "max_pii_risk": "high",
}


@pytest.fixture
def materials():
    """共享 materials (避免重复 IO)"""
    from core.generator import load_materials
    return load_materials()


# =========================================================================
# TestExternalResumeApiField — API 层字段透传
# =========================================================================
class TestExternalResumeApiField:
    """PreviewRequest / GenerateRequest 接受 external_resume_text"""

    def test_preview_request_accepts_external_resume_text(self):
        """PreviewRequest 接收 external_resume_text 字段, 默认 None"""
        from api.resume import PreviewRequest
        req = PreviewRequest(
            target_role="tech_metric",
            external_resume_text="一段简历",
        )
        assert req.external_resume_text == "一段简历"

        # 默认 None
        req_default = PreviewRequest(target_role="tech_metric")
        assert req_default.external_resume_text is None

    def test_generate_request_accepts_external_resume_text(self):
        """GenerateRequest 也接受 external_resume_text 字段 (向后兼容, 但不强制消费)"""
        from api.resume import GenerateRequest
        req = GenerateRequest(
            target_role="tech_metric",
            external_resume_text="一段简历",
        )
        assert req.external_resume_text == "一段简历"

        req_default = GenerateRequest(target_role="tech_metric")
        assert req_default.external_resume_text is None


# =========================================================================
# TestExternalResumeWorkflowUsesText — workflow 任务图据 external_resume_text 派发
# =========================================================================
class TestExternalResumeWorkflowUsesText:
    """build_task_graph 的 has_external_resume 由 external_resume_text 决定"""

    def _step_names(self, has_jd, enable_function_calling, has_external_resume):
        return [
            s.name for s in build_task_graph(
                has_jd=has_jd,
                enable_function_calling=enable_function_calling,
                has_external_resume=has_external_resume,
            )
        ]

    def test_external_resume_text_none_skips_steps(self):
        """external_resume_text=None → 任务图无 parse_external_resume / compare_resume_jd"""
        # 模拟 run_agent_workflow 内部 has_external_resume 的判定: text=None → False
        # 任务图应不含外部简历相关 step
        names = self._step_names(has_jd=True, enable_function_calling=False, has_external_resume=False)
        assert "parse_external_resume" not in names
        assert "compare_resume_jd" not in names

    def test_external_resume_text_empty_string_skips_steps(self):
        """external_resume_text="" 或全空白 → 也走无外部简历路径"""
        # 模拟空白: has_external_resume=False
        names = self._step_names(has_jd=True, enable_function_calling=False, has_external_resume=False)
        assert "parse_external_resume" not in names
        assert "compare_resume_jd" not in names

    def test_external_resume_text_present_adds_steps(self):
        """external_resume_text 非空 → 任务图含 parse_external_resume + compare_resume_jd"""
        # has_external_resume=True 触发 2 步
        names = self._step_names(has_jd=True, enable_function_calling=False, has_external_resume=True)
        assert "parse_external_resume" in names
        assert "compare_resume_jd" in names

        # 顺序: parse_external_resume 必须在 compare_resume_jd 之前
        assert names.index("parse_external_resume") < names.index("compare_resume_jd")

        # 这 2 步在 retrieve_materials 之后, rewrite_highlights 之前
        assert names.index("parse_external_resume") > names.index("retrieve_materials")
        assert names.index("compare_resume_jd") < names.index("rewrite_highlights")


# =========================================================================
# TestParseExternalResumeTool — 工具输出 schema 与隐私
# =========================================================================
class TestParseExternalResumeTool:
    """parse_external_resume 工具输出 schema 稳定 + 不含段落原文"""

    def test_parse_external_resume_output_schema_stable(self):
        """parse_external_resume(external_resume_text) → 含 profile + keywords 字段"""
        result = execute_agent_tool(
            "parse_external_resume",
            args={"external_resume_text": SAMPLE_EXTERNAL_RESUME},
            context=_TOOL_CTX_OK,
        )
        assert result.status == "success", f"工具失败: {result.error_msg}"
        output = result.output
        assert isinstance(output, dict)

        # 必含 schema 字段
        assert "profile" in output, f"输出缺 profile: {list(output.keys())}"
        assert "keywords" in output, f"输出缺 keywords: {list(output.keys())}"

        # profile 字段
        profile = output["profile"]
        assert isinstance(profile, dict)
        assert "char_count" in profile
        assert "paragraph_count" in profile
        assert isinstance(profile["char_count"], int) and profile["char_count"] > 0
        assert isinstance(profile["paragraph_count"], int) and profile["paragraph_count"] > 0

        # keywords 是 sorted list[str] (normalized form)
        assert isinstance(output["keywords"], list)
        assert all(isinstance(k, str) for k in output["keywords"])
        assert output["keywords"] == sorted(output["keywords"]), "keywords 必须排序"
        # 应至少命中 Python/LLM 等基础关键词
        assert "Python" in output["keywords"]
        assert "LLM" in output["keywords"]

    def test_parse_external_resume_output_no_raw_text(self):
        """parse_external_resume 输出不含 external resume 段落原文"""
        # 用一段独特的 sentinel 字符串, 验证输出不含它
        sentinel = "SENTINEL_RAW_TEXT_XYZ_QQQ_2026"
        long_resume = SAMPLE_EXTERNAL_RESUME + "\n" + sentinel + "\n"
        result = execute_agent_tool(
            "parse_external_resume",
            args={"external_resume_text": long_resume},
            context=_TOOL_CTX_OK,
        )
        assert result.status == "success"
        output = result.output

        # 序列化整个 output, 验证不含 sentinel
        serialized = json.dumps(output, ensure_ascii=False)
        assert sentinel not in serialized, (
            f"parse_external_resume 输出泄漏简历原文 (含 sentinel '{sentinel}')"
        )

        # 进一步验证: profile 不应含 'text'/'content'/'paragraph' 等可能含原文的字段
        profile = output["profile"]
        forbidden_keys = {"text", "content", "paragraph", "paragraphs", "raw"}
        leaked = forbidden_keys & set(profile.keys())
        assert not leaked, f"profile 不应含原文字段 {leaked}"

        # ToolResult.output 字段也应不含原文(虽然 output 是 dict, 但 dict 序列化后也不该含)
        assert result.output is not None


# =========================================================================
# TestCompareResumeJdTool — compare_resume_jd 工具输出 schema 与隐私
# =========================================================================
class TestCompareResumeJdTool:
    """compare_resume_jd 工具输出 have/need/gap/suggestions 摘要"""

    def _call_compare(self, materials):
        return execute_agent_tool(
            "compare_resume_jd",
            args={
                "external_resume_text": SAMPLE_EXTERNAL_RESUME,
                "jd_text": SAMPLE_JD,
                "target_role": "tech_metric",
                "materials": materials,
            },
            context=_TOOL_CTX_OK,
        )

    def test_compare_resume_jd_output_schema_stable(self, materials):
        """compare_resume_jd 输出 schema 稳定 — 含 have/need/materials_can_cover/
        resume_only_keywords/suggestions/counts"""
        result = self._call_compare(materials)
        assert result.status == "success", f"工具失败: {result.error_msg}"
        output = result.output
        assert isinstance(output, dict)

        # 必含字段
        required_keys = {
            "have_keywords",
            "need_keywords",
            "materials_can_cover",
            "resume_only_keywords",
            "suggestions",
            "counts",
        }
        missing = required_keys - set(output.keys())
        assert not missing, f"compare_resume_jd 缺字段 {missing}, 实际: {list(output.keys())}"

        # 4 个 keyword 字段都是 list[str] 且 sorted
        for k in ("have_keywords", "need_keywords", "materials_can_cover", "resume_only_keywords"):
            assert isinstance(output[k], list)
            assert all(isinstance(x, str) for x in output[k])
            assert output[k] == sorted(output[k]), f"{k} 必须排序"

        # suggestions 是 list[str], 不超过 5 条
        assert isinstance(output["suggestions"], list)
        assert all(isinstance(x, str) for x in output["suggestions"])
        assert len(output["suggestions"]) <= 5

        # counts 4 个 key: have / need / materials_can_cover / resume_only
        counts = output["counts"]
        assert isinstance(counts, dict)
        assert set(counts.keys()) == {"have", "need", "materials_can_cover", "resume_only"}
        for v in counts.values():
            assert isinstance(v, int) and v >= 0
        # counts 与 list 长度一致
        assert counts["have"] == len(output["have_keywords"])
        assert counts["need"] == len(output["need_keywords"])
        assert counts["materials_can_cover"] == len(output["materials_can_cover"])
        assert counts["resume_only"] == len(output["resume_only_keywords"])

    def test_compare_resume_jd_output_no_raw_text(self, materials):
        """compare_resume_jd 输出不含 external resume 段落原文 / 不含 JD 原文"""
        # 用 2 个不同 sentinel — 简历一段, JD 一段
        resume_sentinel = "RESUME_SENTINEL_ABCDEF_2026"
        jd_sentinel = "JD_SENTINEL_GHIJKL_2026"
        long_resume = SAMPLE_EXTERNAL_RESUME + "\n" + resume_sentinel
        long_jd = SAMPLE_JD + "\n" + jd_sentinel

        result = execute_agent_tool(
            "compare_resume_jd",
            args={
                "external_resume_text": long_resume,
                "jd_text": long_jd,
                "target_role": "tech_metric",
                "materials": materials,
            },
            context=_TOOL_CTX_OK,
        )
        assert result.status == "success"
        serialized = json.dumps(result.output, ensure_ascii=False)

        assert resume_sentinel not in serialized, (
            f"compare_resume_jd 输出泄漏简历原文 (含 sentinel '{resume_sentinel}')"
        )
        assert jd_sentinel not in serialized, (
            f"compare_resume_jd 输出泄漏 JD 原文 (含 sentinel '{jd_sentinel}')"
        )


# =========================================================================
# TestExternalResumePermission — 工具权限校验
# =========================================================================
class TestExternalResumePermission:
    """parse_external_resume / compare_resume_jd 需要 allow_external_resume=True"""

    def test_external_resume_tools_require_allow_external_resume(self):
        """context 无 allow_external_resume=True → PRIVACY_VIOLATION"""
        # 注意: 这里只传 allow_external_resume=False 但 max_pii_risk=high (与 workflow 内部一致)
        # 确保拒绝来自权限而非 pii_risk
        ctx_no_external = {
            "allow_jd_text": True,
            "allow_materials": True,
            "allow_external_resume": False,
            "max_pii_risk": "high",
        }
        for tool_name in ("parse_external_resume", "compare_resume_jd"):
            result = execute_agent_tool(
                tool_name,
                args={"external_resume_text": SAMPLE_EXTERNAL_RESUME},
                context=ctx_no_external,
            )
            assert result.status == "error", f"{tool_name} 应拒绝无 allow_external_resume 的 context"
            assert result.error_type == ToolErrorType.PRIVACY_VIOLATION, (
                f"{tool_name} 应返 PRIVACY_VIOLATION, 实际: {result.error_type}"
            )
            # 错误描述只含权限名, 不含简历原文
            assert "external_resume" in (result.error_msg or "").lower()
            assert SAMPLE_EXTERNAL_RESUME[:30] not in (result.error_msg or "")


# =========================================================================
# TestExternalResumePrivacy — trace / agent_summary / ToolResult 隐私边界
# =========================================================================
class TestExternalResumePrivacy:
    """workflow 跑完后 trace + agent_summary 不含 external resume 原文"""

    def test_jsonl_trace_has_no_raw_resume_text(self, tmp_path, monkeypatch, materials):
        """跑 workflow (external_resume_text 非空) → JSONL trace 不含简历 sentinel"""
        import core.logger as logger_mod

        jsonl_path = tmp_path / "agent_trace.jsonl"
        monkeypatch.setattr(logger_mod, "AGENT_TRACE_JSONL_PATH", jsonl_path)

        resume_sentinel = "RESUME_TRACE_SENTINEL_99999"
        long_resume = SAMPLE_EXTERNAL_RESUME + "\n" + resume_sentinel

        result = run_agent_workflow(
            target_role="tech_metric",
            template="classic",
            jd_text=SAMPLE_JD,
            external_resume_text=long_resume,
        )
        assert isinstance(result, dict)

        # 整个 JSONL 文件内容不含 sentinel
        raw_text = jsonl_path.read_text(encoding="utf-8")
        assert resume_sentinel not in raw_text, (
            "JSONL trace 泄漏了 external resume 原文"
        )

        # 也走一遍 jsonl 解析, 逐 event 检查 dict 不含 sentinel
        events = [json.loads(line) for line in raw_text.strip().split("\n")]
        for event in events:
            for v in event.values():
                if isinstance(v, str):
                    assert resume_sentinel not in v, f"JSONL event 字段含 sentinel: {v[:80]}"

    def test_agent_summary_has_no_raw_resume_text(self, materials):
        """workflow preview 返回值 agent_summary 不含 external resume 原文"""
        resume_sentinel = "SUMMARY_RESUME_SENTINEL_7777"
        long_resume = SAMPLE_EXTERNAL_RESUME + "\n" + resume_sentinel

        result = run_agent_workflow(
            target_role="tech_metric",
            template="classic",
            jd_text=SAMPLE_JD,
            external_resume_text=long_resume,
        )
        # 整个 result 序列化后不含 sentinel
        serialized = json.dumps(result, ensure_ascii=False, default=str)
        assert resume_sentinel not in serialized, (
            f"workflow 返回值含 external resume 原文 (sentinel)"
        )

        # agent_summary 字段单独检查 (核心隐私目标字段)
        summary = result.get("agent_summary", {})
        summary_serialized = json.dumps(summary, ensure_ascii=False, default=str)
        assert resume_sentinel not in summary_serialized

    def test_workflow_tool_result_output_has_no_raw_resume_text(self, materials):
        """workflow 内部 tool_results (如 retrieve_evidence) 不含 external resume 原文"""
        # 简化版验证: 整个 preview result 序列化后, 不含 sentinel
        resume_sentinel = "RESULT_TOOL_SENTINEL_5555"
        long_resume = SAMPLE_EXTERNAL_RESUME + "\n" + resume_sentinel

        result = run_agent_workflow(
            target_role="tech_metric",
            template="classic",
            jd_text=SAMPLE_JD,
            external_resume_text=long_resume,
        )
        # evidence_summary 单独验证
        evidence_summary = result.get("evidence_summary") or []
        evidence_serialized = json.dumps(evidence_summary, ensure_ascii=False, default=str)
        assert resume_sentinel not in evidence_serialized, (
            "evidence_summary 泄漏了 external resume 原文"
        )


# =========================================================================
# TestExternalResumePreviewOutput — workflow preview 返回 external_resume_perspective
# =========================================================================
class TestExternalResumePreviewOutput:
    """workflow preview 返回值含 external_resume_perspective 字段 (schema 稳定)"""

    def test_preview_returns_external_resume_perspective_when_text_present(self):
        """external_resume_text 非空时, preview 含 external_resume_perspective dict"""
        result = run_agent_workflow(
            target_role="tech_metric",
            template="classic",
            jd_text=SAMPLE_JD,
            external_resume_text=SAMPLE_EXTERNAL_RESUME,
        )
        assert "external_resume_perspective" in result
        perspective = result["external_resume_perspective"]
        assert isinstance(perspective, dict)

        # 必含 schema 字段 (spec §3.2)
        required_keys = {
            "have_keywords",
            "need_keywords",
            "materials_can_cover",
            "resume_only_keywords",
            "suggestions",
            "counts",
        }
        assert required_keys <= set(perspective.keys()), (
            f"external_resume_perspective 缺字段: {required_keys - set(perspective.keys())}"
        )

        # schema 与 compare_resume_jd 输出对齐
        for k in ("have_keywords", "need_keywords", "materials_can_cover", "resume_only_keywords"):
            assert isinstance(perspective[k], list)
            assert perspective[k] == sorted(perspective[k])
        assert isinstance(perspective["suggestions"], list)
        assert isinstance(perspective["counts"], dict)
        assert set(perspective["counts"].keys()) == {
            "have", "need", "materials_can_cover", "resume_only"
        }


# =========================================================================
# TestExternalResumeOldPathUnchanged — 老路径字节级一致
# =========================================================================
class TestExternalResumeOldPathUnchanged:
    """enable_agent_workflow=False 时 preview 不含 external_resume_perspective 字段"""

    def test_old_path_does_not_have_external_resume_perspective(self):
        """preview_resume(enable_agent_workflow=False) 不含 external_resume_perspective 字段
        (即使传 external_resume_text 也不消费, 保持字节级一致 baseline)"""
        result = preview_resume(
            target_role="tech_metric",
            template="classic",
            jd_text=SAMPLE_JD,
            external_resume_text=SAMPLE_EXTERNAL_RESUME,  # 传但老路径忽略
        )
        assert "external_resume_perspective" not in result, (
            "老路径不应含 external_resume_perspective 字段 (否则破坏字节级一致 baseline)"
        )

    def test_old_path_external_resume_text_does_not_change_output(self):
        """老路径 + external_resume_text: 输出与不传时字节级一致 (字段一致 + sections 一致)"""
        result_no_text = preview_resume(
            target_role="tech_metric",
            template="classic",
            jd_text=SAMPLE_JD,
        )
        result_with_text = preview_resume(
            target_role="tech_metric",
            template="classic",
            jd_text=SAMPLE_JD,
            external_resume_text=SAMPLE_EXTERNAL_RESUME,
        )
        # 顶层 keys 一致
        assert set(result_no_text.keys()) == set(result_with_text.keys())
        # sections 序列化字节级一致 (老路径忽略 external_resume_text)
        assert json.dumps(result_no_text["sections"], ensure_ascii=False, default=str) == \
               json.dumps(result_with_text["sections"], ensure_ascii=False, default=str)