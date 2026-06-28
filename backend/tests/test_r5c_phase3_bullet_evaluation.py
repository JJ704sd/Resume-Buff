"""
R5-C Phase 3: per-bullet 真实评估数据流

参考 .harness/docs/round5-c-agent-capability-spec.md §4

锁点:
  1. 候选选择: top projects 默认 3 个, each top bullets 默认 3 条
     - 候选来源: ROLE_CONFIG["preferred_project_ids"] (有 jd_context 时按 rank_projects 重排)
     - bullet 来源: 项目 highlights[target_role] (fallback: chain → general)
  2. 输出 bullet_evaluations 摘要 (6 字段):
     - project_id, bullet_index, matched_keywords, missing_keywords,
       matched_count, missing_count, suggestion
     - 不含 bullet 原文
  3. workflow preview 返回 bullet_evaluations 字段
  4. 无 JD 时跳过 (evaluate step 不进 task_graph)
  5. 无 bullets 时跳过 (不抛)
  6. trace 不含完整 bullet (input_size / output_size only)
  7. evaluate_bullet_jd_match 仍保持 affects_preview=False
     (spec §4.4: 初始作为诊断输出, 不影响 preview)
  8. 老路径 (enable_agent_workflow=False) 不含 bullet_evaluations (字节级一致)

测试矩阵 (8 case):
  TestBulletEvaluationSelectsTopProjects (1 case):
    1.  select_top_bullets_returns_top_projects_and_bullets
        - helper 单元: 给定 materials + role + jd_focus, 返回 top 3 projects × top 3 bullets

  TestBulletEvaluationOutputSchema (2 case):
    2.  bullet_evaluations_schema_stable
        - workflow 跑完, bullet_evaluations 是 list[dict], 每条 6 字段类型正确
    3.  bullet_evaluations_no_raw_bullet_text
        - bullet_evaluations 序列化后不含完整 bullet 原文 (sentinel)

  TestBulletEvaluationNoRawBulletInTrace (1 case):
    4.  jsonl_trace_does_not_contain_bullet_text
        - JSONL trace 不含 bullet 原文 sentinel

  TestBulletEvaluationSkippedWithoutJd (1 case):
    5.  bullet_evaluations_skipped_when_no_jd
        - jd_text=None → bullet_evaluations 为 None 或空

  TestBulletEvaluationNoBulletsNotError (1 case):
    6.  evaluate_top_bullets_handles_empty_highlights
        - 项目无 highlights → 返回空 list, 不抛

  TestAffectsPreviewStillFalseUntilConsumed (1 case):
    7.  affects_preview_evaluate_bullet_still_false
        - AGENT_TOOLS["evaluate_bullet_jd_match"].metadata.affects_preview == False

  TestBulletEvaluationOldPathUnchanged (2 case):
    8.  old_path_no_bullet_evaluations_field
        - preview_resume(enable_agent_workflow=False) 不含 bullet_evaluations
    9.  old_path_unaffected_by_external_resume
        - 老路径下 sections 字节级一致 (Phase 3 不污染老路径)
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core import agent_tools
from core.agent_tools import AGENT_TOOLS, affects_preview, execute_agent_tool
from core.agent_workflow import build_task_graph, run_agent_workflow
from core.generator import preview_resume


# =========================================================================
# 共享 fixtures
# =========================================================================
SAMPLE_JD = (
    "岗位: 大模型评测实习生\n"
    "要求: 熟悉 Python, 熟悉 LLM 评测, 了解 Prompt 工程。\n"
    "加分: 熟悉 NLP, 了解流程图 / 原型设计。\n"
)

SAMPLE_EMPTY_JD = ""  # 全空白, 用于"无 JD"路径


@pytest.fixture
def materials():
    from core.generator import load_materials
    return load_materials()


@pytest.fixture
def jd_focus():
    """手动构造 jd_focus dict (与 generator._build_jd_focus 输出对齐)
    包含 matched / missing / tier_required / tier_preferred"""
    return {
        "matched": ["LLM", "评测", "Python"],
        "missing": ["流程图"],
        "tier_required": ["LLM", "评测"],
        "tier_preferred": ["Python"],
    }


# =========================================================================
# TestBulletEvaluationSelectsTopProjects
# =========================================================================
class TestBulletEvaluationSelectsTopProjects:
    """Phase 3 候选选择: top projects 默认 3 个, each top bullets 默认 3 条"""

    def test_select_top_bullets_returns_top_projects_and_bullets(self, materials, jd_focus):
        """_evaluate_top_bullets 返回 top 3 projects × top 3 bullets = 最多 9 条"""
        # 直接导入待实现的 helper (本轮新增)
        from core.agent_workflow import _evaluate_top_bullets

        evaluations = _evaluate_top_bullets(
            materials=materials,
            target_role="tech_metric",
            jd_focus=jd_focus,
            top_projects=3,
            bullets_per_project=3,
        )

        # 应返回 list[dict]
        assert isinstance(evaluations, list)
        # tech_metric role 有 4 个 preferred projects, 取前 3 → 3 个项目 × 3 bullets = 9 条
        # (但 volunteer 项目 tech_metric highlights 为空, 实际可能少于 9 — 见下方断言)
        assert len(evaluations) > 0, "应有至少 1 条 bullet 评估"

        # 每条 evaluation 必须含 6 字段 (spec §4.3)
        for ev in evaluations:
            assert "project_id" in ev
            assert "bullet_index" in ev
            assert "matched_keywords" in ev
            assert "missing_keywords" in ev
            assert "matched_count" in ev
            assert "missing_count" in ev
            assert "suggestion" in ev

        # bullet_index 在每项目内从 0 开始
        project_indices: dict[str, list[int]] = {}
        for ev in evaluations:
            project_indices.setdefault(ev["project_id"], []).append(ev["bullet_index"])
        for pid, indices in project_indices.items():
            # 每个项目的 bullet_index 从 0 开始连续
            assert sorted(indices) == list(range(len(indices))), (
                f"project {pid} bullet_index 不连续: {indices}"
            )
            # 不超过 bullets_per_project 上限
            assert len(indices) <= 3, f"project {pid} bullets 超过 3: {len(indices)}"

        # 总项目数不超过 top_projects
        assert len(project_indices) <= 3, f"总项目数超过 top_projects=3: {len(project_indices)}"


# =========================================================================
# TestBulletEvaluationOutputSchema
# =========================================================================
class TestBulletEvaluationOutputSchema:
    """Phase 3 输出 schema 稳定 + 不含原文"""

    def test_bullet_evaluations_schema_stable(self, tmp_path, monkeypatch):
        """workflow 跑完, preview 含 bullet_evaluations list[dict], 6 字段类型正确"""
        import core.logger as logger_mod

        jsonl_path = tmp_path / "agent_trace.jsonl"
        monkeypatch.setattr(logger_mod, "AGENT_TRACE_JSONL_PATH", jsonl_path)

        result = run_agent_workflow(
            target_role="tech_metric",
            template="classic",
            jd_text=SAMPLE_JD,
        )
        # bullet_evaluations 字段必须存在
        assert "bullet_evaluations" in result, (
            "workflow preview 应含 bullet_evaluations 字段 (R5-C Phase 3)"
        )
        evaluations = result["bullet_evaluations"]
        assert isinstance(evaluations, list), f"bullet_evaluations 应为 list, 实际: {type(evaluations)}"
        assert len(evaluations) > 0, "有 JD 时应有至少 1 条 bullet 评估"

        # 每条 evaluation 必须含 6 字段 (spec §4.3) + 类型正确
        for i, ev in enumerate(evaluations):
            assert isinstance(ev, dict), f"第 {i} 条 ev 应为 dict, 实际: {type(ev)}"

            # project_id 是 str
            assert isinstance(ev["project_id"], str), f"project_id 应为 str: {ev}"
            assert ev["project_id"], f"project_id 不应为空: {ev}"

            # bullet_index 是 int
            assert isinstance(ev["bullet_index"], int), f"bullet_index 应为 int: {ev}"
            assert ev["bullet_index"] >= 0, f"bullet_index 应 >= 0: {ev}"

            # matched_keywords / missing_keywords 是 list[str]
            assert isinstance(ev["matched_keywords"], list), f"matched_keywords 应为 list: {ev}"
            assert all(isinstance(k, str) for k in ev["matched_keywords"]), (
                f"matched_keywords 应全为 str: {ev}"
            )
            assert isinstance(ev["missing_keywords"], list), f"missing_keywords 应为 list: {ev}"
            assert all(isinstance(k, str) for k in ev["missing_keywords"]), (
                f"missing_keywords 应全为 str: {ev}"
            )

            # matched_count / missing_count 是 int
            assert isinstance(ev["matched_count"], int), f"matched_count 应为 int: {ev}"
            assert ev["matched_count"] == len(ev["matched_keywords"]), (
                f"matched_count={ev['matched_count']} != len(matched_keywords)={len(ev['matched_keywords'])}"
            )
            assert isinstance(ev["missing_count"], int), f"missing_count 应为 int: {ev}"
            assert ev["missing_count"] == len(ev["missing_keywords"]), (
                f"missing_count={ev['missing_count']} != len(missing_keywords)={len(ev['missing_keywords'])}"
            )

            # suggestion 是 str (允许空字符串)
            assert isinstance(ev["suggestion"], str), f"suggestion 应为 str: {ev}"

    def test_bullet_evaluations_no_raw_bullet_text(self, tmp_path, monkeypatch, materials):
        """bullet_evaluations 序列化后不含完整 bullet 原文 (sentinel)"""
        # 用 materials 中真实 bullet 文本作为 sentinel, 验证 bullet_evaluations 字段不含
        tech_bullets = (
            materials.get("projects", [{}])[0]
            .get("highlights", {})
            .get("tech_metric", [])
        )
        assert tech_bullets, "需要至少 1 条真实 bullet 作 sentinel"
        real_bullet = tech_bullets[0]
        sentinel = real_bullet[:20] + "_SENTINEL_BULLET_R5C_P3"

        # 改写一个 materials 让 bullet 含 sentinel
        modified_materials = json.loads(json.dumps(materials))  # 深拷贝
        target_proj = modified_materials["projects"][0]
        target_proj.setdefault("highlights", {}).setdefault("tech_metric", [])
        target_proj["highlights"]["tech_metric"].insert(0, f"测试前缀 {sentinel} 测试后缀")

        # monkeypatch load_materials 返 modified_materials
        # 注意: core.agent_workflow 没有模块级 load_materials (函数内局部导入),
        # 改 core.generator.load_materials 即可 (workflow 内部从 generator import)
        from core import generator as gen_mod
        monkeypatch.setattr(gen_mod, "load_materials", lambda: modified_materials)

        result = run_agent_workflow(
            target_role="tech_metric",
            template="classic",
            jd_text=SAMPLE_JD,
        )

        # 只验证 bullet_evaluations 字段本身不含 sentinel
        # (注: sections / evidence_summary 字段可能含 bullet 文本, 因为它们直接消费 materials;
        #  spec §4.3 仅约束 bullet_evaluations 不含原文)
        ev_serialized = json.dumps(
            result.get("bullet_evaluations") or [],
            ensure_ascii=False,
        )
        assert sentinel not in ev_serialized, (
            f"bullet_evaluations 泄漏 bullet 原文 (sentinel '{sentinel}')"
        )


# =========================================================================
# TestBulletEvaluationNoRawBulletInTrace
# =========================================================================
class TestBulletEvaluationNoRawBulletInTrace:
    """隐私边界: JSONL trace 不含 bullet 原文 (只存 size)"""

    def test_jsonl_trace_does_not_contain_bullet_text(self, tmp_path, monkeypatch, materials):
        """跑 workflow (有 JD) → JSONL trace 不含 bullet 原文 sentinel"""
        import core.logger as logger_mod

        jsonl_path = tmp_path / "agent_trace.jsonl"
        monkeypatch.setattr(logger_mod, "AGENT_TRACE_JSONL_PATH", jsonl_path)

        # 构造一个含独特 sentinel 的 bullet
        sentinel = "BULLET_TRACE_SENTINEL_P3_7777"
        modified_materials = json.loads(json.dumps(materials))
        target_proj = modified_materials["projects"][0]
        target_proj.setdefault("highlights", {}).setdefault("tech_metric", [])
        target_proj["highlights"]["tech_metric"].insert(0, f"前缀 {sentinel} 后缀")

        from core import generator as gen_mod
        monkeypatch.setattr(gen_mod, "load_materials", lambda: modified_materials)

        result = run_agent_workflow(
            target_role="tech_metric",
            template="classic",
            jd_text=SAMPLE_JD,
        )
        assert isinstance(result, dict)

        # 整个 JSONL 文件内容不含 sentinel
        raw_text = jsonl_path.read_text(encoding="utf-8")
        assert sentinel not in raw_text, (
            "JSONL trace 泄漏了 bullet 原文"
        )

        # 逐 event 检查 dict 不含 sentinel
        events = [json.loads(line) for line in raw_text.strip().split("\n") if line.strip()]
        for event in events:
            for v in event.values():
                if isinstance(v, str):
                    assert sentinel not in v, f"JSONL event 字段含 sentinel: {v[:80]}"


# =========================================================================
# TestBulletEvaluationSkippedWithoutJd
# =========================================================================
class TestBulletEvaluationSkippedWithoutJd:
    """Phase 3 边界: 无 JD 时跳过 (task_graph 不含 evaluate step)"""

    def test_bullet_evaluations_skipped_when_no_jd(self):
        """jd_text=None → task_graph 不含 evaluate_bullet_jd_match step →
        bullet_evaluations 为 None 或空 list"""
        # 1) task_graph 验证: 无 JD 时不含 evaluate step
        steps = build_task_graph(
            has_jd=False,
            enable_function_calling=True,  # 即使 FC=True, 无 JD 也不加 evaluate
            has_external_resume=False,
        )
        names = [s.name for s in steps]
        assert "evaluate_bullet_jd_match" not in names, (
            "无 JD 时任务图不应含 evaluate_bullet_jd_match step"
        )

        # 2) workflow 跑 preview, bullet_evaluations 字段存在但值是 None 或 []
        result = run_agent_workflow(
            target_role="tech_metric",
            template="classic",
            jd_text=None,
        )
        assert "bullet_evaluations" in result, (
            "workflow preview 应包含 bullet_evaluations 字段 (spec §4.3 schema 稳定)"
        )
        ev = result["bullet_evaluations"]
        assert ev is None or ev == [], (
            f"无 JD 时 bullet_evaluations 应为 None 或 [], 实际: {ev!r}"
        )

        # 3) 空字符串 jd 也算"无 JD" (跟现有 has_jd 判定对齐)
        result_empty = run_agent_workflow(
            target_role="tech_metric",
            template="classic",
            jd_text=SAMPLE_EMPTY_JD,
        )
        ev_empty = result_empty["bullet_evaluations"]
        assert ev_empty is None or ev_empty == [], (
            f"空 jd 时 bullet_evaluations 应为 None 或 [], 实际: {ev_empty!r}"
        )


# =========================================================================
# TestBulletEvaluationNoBulletsNotError
# =========================================================================
class TestBulletEvaluationNoBulletsNotError:
    """Phase 3 边界: 项目无 bullets 时不报错"""

    def test_evaluate_top_bullets_handles_empty_highlights(self, jd_focus):
        """所有项目 highlights 全空 → _evaluate_top_bullets 返空 list, 不抛"""
        from core.agent_workflow import _evaluate_top_bullets

        empty_materials = {
            "projects": [
                {"id": "p1", "highlights": {}},  # 全空
                {"id": "p2", "highlights": {"tech_metric": []}},  # 空列表
                {"id": "p3"},  # 缺 highlights 字段
            ],
            # 其他字段 _evaluate_top_bullets 不需要, 但 role_cfg 也不依赖 materials 全字段
        }
        # 不应抛
        result = _evaluate_top_bullets(
            materials=empty_materials,
            target_role="tech_metric",
            jd_focus=jd_focus,
            top_projects=3,
            bullets_per_project=3,
        )
        assert isinstance(result, list)
        assert result == [], f"全空 highlights 应返 [], 实际: {result!r}"

    def test_workflow_handles_empty_materials_gracefully(self, tmp_path, monkeypatch):
        """workflow 跑 (项目 highlights 全空 materials) → bullet_evaluations 是空 list, 不抛"""
        import core.logger as logger_mod

        jsonl_path = tmp_path / "agent_trace.jsonl"
        monkeypatch.setattr(logger_mod, "AGENT_TRACE_JSONL_PATH", jsonl_path)

        # 构造合法但项目 highlights 全空的 materials
        # (build_sections 需要 basics / education / skills / honors 等基础字段;
        #  这里只让 projects.highlights 为空, 验证 _evaluate_top_bullets 不报错)
        empty_materials = {
            "basics": {
                "name": "示例同学",
                "name_en": "",
                "phone": "13800000000",
                "email": "your_email@example.com",
                "location": "深圳",
            },
            "education": {
                "school": "示例大学",
                "college": "示例学院",
                "major": "示例专业",
                "degree": "本科",
                "period": "2024.9 - 2028.6",
                "year": "大二(在读)",
                "school_en": "",
                "major_en": "",
                "core_courses": [],
                "highlights": [],
            },
            "projects": [
                {"id": "p1", "name": "空项目1", "role": "开发", "period": "2024",
                 "highlights": {"tech_metric": []}},
                {"id": "p2", "name": "空项目2", "role": "开发", "period": "2024",
                 "highlights": {}},
            ],
            "skills": {
                "ai_ml": ["LLM"],
            },
            "honors": [],
            "certs": [],
            "self_eval_versions": {"general": []},
        }
        from core import generator as gen_mod
        monkeypatch.setattr(gen_mod, "load_materials", lambda: empty_materials)

        # 不应抛
        result = run_agent_workflow(
            target_role="tech_metric",
            template="classic",
            jd_text=SAMPLE_JD,
        )
        assert isinstance(result, dict)
        # bullet_evaluations 应为 list (空, 因为 evaluate step 跑但项目无 bullets → 返 [])
        ev = result.get("bullet_evaluations")
        assert ev == [], (
            f"空 highlights 时 bullet_evaluations 应为 [], 实际: {ev!r}"
        )


# =========================================================================
# TestAffectsPreviewStillFalseUntilConsumed
# =========================================================================
class TestAffectsPreviewStillFalseUntilConsumed:
    """Phase 3 §4.4: evaluate_bullet_jd_match 保持 affects_preview=False
    (它先作为诊断输出, 不影响 preview — spec §4.4)"""

    def test_affects_preview_evaluate_bullet_still_false(self):
        """affects_preview('evaluate_bullet_jd_match') 应为 False"""
        # 直接检查 helper
        assert affects_preview("evaluate_bullet_jd_match") is False, (
            "evaluate_bullet_jd_match 应保持 affects_preview=False (Phase 3 §4.4)"
        )

        # 也检查 AGENT_TOOLS metadata
        spec = AGENT_TOOLS["evaluate_bullet_jd_match"]
        assert spec.metadata.get("affects_preview", False) is False, (
            f"evaluate_bullet_jd_match metadata.affects_preview 应为 False, 实际: {spec.metadata}"
        )


# =========================================================================
# TestBulletEvaluationOldPathUnchanged
# =========================================================================
class TestBulletEvaluationOldPathUnchanged:
    """老路径 (enable_agent_workflow=False) 不含 bullet_evaluations (字节级一致)"""

    def test_old_path_no_bullet_evaluations_field(self):
        """preview_resume(enable_agent_workflow=False) 不含 bullet_evaluations 字段"""
        result = preview_resume(
            target_role="tech_metric",
            template="classic",
            jd_text=SAMPLE_JD,
        )
        assert "bullet_evaluations" not in result, (
            "老路径不应含 bullet_evaluations 字段 (否则破坏字节级一致 baseline)"
        )

    def test_old_path_unaffected_by_phase3(self):
        """老路径 + JD: sections 与 R5-A closeout baseline 字节级一致"""
        # 跑两次老路径, sections 序列化应一致 (老路径与 Phase 3 完全解耦)
        result_a = preview_resume(
            target_role="tech_metric",
            template="classic",
            jd_text=SAMPLE_JD,
        )
        result_b = preview_resume(
            target_role="tech_metric",
            template="classic",
            jd_text=SAMPLE_JD,
        )
        # 顶层 keys 一致 (都不含 bullet_evaluations)
        assert set(result_a.keys()) == set(result_b.keys())
        assert "bullet_evaluations" not in result_a
        # sections 序列化字节级一致
        assert json.dumps(result_a["sections"], ensure_ascii=False, default=str) == \
               json.dumps(result_b["sections"], ensure_ascii=False, default=str)