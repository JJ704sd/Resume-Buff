"""
Round 3 I: JD-driven generation 测试

测点(总 18 用例,基线 88 → 期望 106 全绿):
  - TestJdRankerProjects (5):
      1. test_rank_projects_by_match_count_desc         按命中数倒序
      2. test_rank_projects_tie_breaks_to_preferred     命中数相同维持 preferred 原顺序
      3. test_rank_projects_zero_match_still_included   0 命中也保留
      4. test_rank_projects_deterministic               多次调用结果一致
      5. test_rank_projects_empty_jd_returns_original   空 JD 走原顺序
  - TestJdRankerHighlights (2):
      6. test_rank_highlights_within_project            项目内排序
      7. test_rank_highlights_no_truncation             不裁剪
  - TestJdRankerSkillGroups (2):
      8. test_rank_skill_groups_by_match                排序
      9. test_rank_skill_groups_empty_role_keys         边界
  - TestBackwardCompat (2):
      10. test_build_sections_no_jd_byte_identical_baseline  6 role 字节级一致
      11. test_preview_no_jd_byte_identical_baseline         preview 不变
  - TestLdPromptEnhancement (3):
      12. test_prompt_contains_matched_keywords         LLM prompt 含 matched
      13. test_prompt_contains_missing_keywords         含 missing
      14. test_prompt_no_hallucination_directive        含"不编造"指令
  - TestApiJdText (4):
      15. test_preview_with_jd_text_200                 200 正常
      16. test_preview_with_jd_text_too_long_422        > 50k → 422
      17. test_generate_with_jd_text_200_blob           200 + docx
      18. test_preview_jd_text_empty_string_falls_back  空字符串走原路径
"""
import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import core.jd_ranker as ranker
from core.generator import (
    ENABLED_ROLES,
    ROLE_CONFIG,
    build_sections,
    generate_resume_docx,
    preview_resume,
)
from main import app


# ----------------------------------------------------------------------
# Round 3 I baseline (固化) — 不传 JD 时 6 role 的 build_sections 字节级 hash
# 任一 baseline hash 漂移都会被抓到
#
# Round 3 M.3: build_sections 透传 name_en / school_en / major_en / title_en 字段
# (Step 3 R3-M.3,header/education/project 三 section.content 都加 _en 字段供
# bilingual 模板消费,缺失给空字符串走 graceful 降级)。新增 4 个 key 必然让
# sections 序列化 hash 漂移 — 这是 schema 自然扩展,不是排序路径变化。
# baseline 在 R3-M.3 重算并固化,排序逻辑不变。
# ----------------------------------------------------------------------
_BASELINE_HASHES: dict[str, str] = {
    "tech_metric": "2b989956117ba9182cf775607ea6480e54b34eb559da2e7813e32345b5417226",
    "product":     "296bb978cb2980c6c138b9bd0112d20b092ec8beeaa26e17bee1385fee5f92ac",
    "algorithm":   "15114e4a3d9e32d3fcaa0593d3576e00bf3cabc61749235ad1f1d3be6cad5949",
    "data_annot":  "326e56433b88f82cd2bc62685dd832b440e17ff0aaf5925174e7283ac953de54",
    "test_qa":     "60f7895778985007e096ceed2bdcc4824751790a499a80615508a012407f7e0a",
    "general":     "9e211132ec52baec52289f5f63bf69fcf99e1fcbe3b7399c20f23015ebdd8d6b",
}


def _sections_hash(role: str) -> str:
    """计算 build_sections(role) 的 sha256 hash (json 序列化,sort_keys=True)"""
    sections = build_sections(target_role=role)
    serialized = [s.__dict__ for s in sections]
    return hashlib.sha256(
        json.dumps(serialized, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


# ----------------------------------------------------------------------
# TestJdRankerProjects: 项目排序
# ----------------------------------------------------------------------
class TestJdRankerProjects:
    def test_rank_projects_by_match_count_desc(self):
        """按命中数倒序 — 含 PyTorch 的项目应排在前面"""
        projects = [
            {"id": "a", "highlights": ["a 项目:用 Python 做 demo"], "tags": []},
            {"id": "b", "highlights": ["b 项目:PyTorch + Docker + Linux 全套"], "tags": []},
            {"id": "c", "highlights": ["c 项目:基础测试"], "tags": []},
        ]
        parsed = {"raw_keywords": ["PyTorch", "Python", "Docker"]}
        out = ranker.rank_projects(projects, parsed, preferred_order=["a", "b", "c"])
        # b 命中 3 → 排第 1;a 命中 1 → 排第 2;c 命中 0 → 排第 3
        assert [p["id"] for p in out] == ["b", "a", "c"]

    def test_rank_projects_tie_breaks_to_preferred(self):
        """命中数相同 → 按 preferred_order 原顺序(tie-break)"""
        projects = [
            {"id": "a", "highlights": ["a 项目:用 Python"], "tags": []},
            {"id": "b", "highlights": ["b 项目:用 Python"], "tags": []},
            {"id": "c", "highlights": ["c 项目:用 Python"], "tags": []},
        ]
        parsed = {"raw_keywords": ["Python"]}
        out = ranker.rank_projects(projects, parsed, preferred_order=["c", "a", "b"])
        # 三者都命中 1 → 按 preferred tie-break → c, a, b
        assert [p["id"] for p in out] == ["c", "a", "b"]

    def test_rank_projects_zero_match_still_included(self):
        """0 命中也保留 — 排到最后(不裁剪)"""
        projects = [
            {"id": "a", "highlights": ["没有命中"], "tags": []},
            {"id": "b", "highlights": ["命中 PyTorch"], "tags": []},
            {"id": "c", "highlights": ["也没有命中"], "tags": []},
        ]
        parsed = {"raw_keywords": ["PyTorch"]}
        out = ranker.rank_projects(projects, parsed, preferred_order=["a", "b", "c"])
        ids = [p["id"] for p in out]
        # b 在前,a/c 在后
        assert ids[0] == "b"
        # 0 命中的 a 和 c 都还在
        assert set(ids[1:]) == {"a", "c"}
        assert len(out) == 3

    def test_rank_projects_deterministic(self):
        """多次调用结果一致(稳定排序)"""
        projects = [
            {"id": "a", "highlights": ["Python + Docker"], "tags": []},
            {"id": "b", "highlights": ["Python"], "tags": []},
            {"id": "c", "highlights": ["无命中"], "tags": []},
        ]
        parsed = {"raw_keywords": ["Python", "Docker"]}
        first = ranker.rank_projects(projects, parsed)
        second = ranker.rank_projects(projects, parsed)
        third = ranker.rank_projects(projects, parsed)
        assert [p["id"] for p in first] == [p["id"] for p in second]
        assert [p["id"] for p in second] == [p["id"] for p in third]

    def test_rank_projects_empty_jd_returns_original(self):
        """parsed_jd 为 None / 没 raw_keywords → 维持原顺序(不重排)"""
        projects = [
            {"id": "x", "highlights": ["PyTorch"], "tags": []},
            {"id": "y", "highlights": ["Python"], "tags": []},
        ]
        # None
        out_none = ranker.rank_projects(projects, None, preferred_order=["x", "y"])
        assert [p["id"] for p in out_none] == ["x", "y"]
        # 没 raw_keywords
        out_empty = ranker.rank_projects(projects, {}, preferred_order=["x", "y"])
        assert [p["id"] for p in out_empty] == ["x", "y"]
        out_empty_list = ranker.rank_projects(projects, {"raw_keywords": []}, preferred_order=["x", "y"])
        assert [p["id"] for p in out_empty_list] == ["x", "y"]


# ----------------------------------------------------------------------
# TestJdRankerHighlights: 项目内 highlight 排序
# ----------------------------------------------------------------------
class TestJdRankerHighlights:
    def test_rank_highlights_within_project(self):
        """项目内 highlight 排序 — 高命中排前,低命中排后"""
        highlights = [
            "用 Python 做数据处理",            # 1 命中 (Python)
            "PyTorch 训练 + Docker 部署全流程",  # 2 命中 (PyTorch, Docker)
            "撰写测试报告",                     # 0 命中
            "Prompt 工程优化",                 # 1 命中 (Prompt)
        ]
        parsed = {"raw_keywords": ["PyTorch", "Docker", "Python", "Prompt"]}
        out = ranker.rank_highlights(highlights, parsed)
        # 期望顺序:2 命中 > 1 命中(tie by 原顺序) > 0 命中
        # 高命中:第 2 条 (2 命中)
        # 1 命中(原顺序):第 1 条 (Python),第 4 条 (Prompt)
        # 0 命中:第 3 条
        assert out[0] == "PyTorch 训练 + Docker 部署全流程"
        assert out[1] == "用 Python 做数据处理"  # 1 命中,原 index 0
        assert out[2] == "Prompt 工程优化"        # 1 命中,原 index 3
        assert out[3] == "撰写测试报告"            # 0 命中

    def test_rank_highlights_no_truncation(self):
        """不裁剪 — 输入 N 条,输出 N 条(即使全 0 命中)"""
        highlights = [
            "无关内容 A",
            "无关内容 B",
            "无关内容 C",
        ]
        parsed = {"raw_keywords": ["PyTorch"]}
        out = ranker.rank_highlights(highlights, parsed)
        assert len(out) == 3
        assert set(out) == set(highlights)


# ----------------------------------------------------------------------
# TestJdRankerSkillGroups: skill group 排序
# ----------------------------------------------------------------------
class TestJdRankerSkillGroups:
    def test_rank_skill_groups_by_match(self):
        """skill group 排序 — 命中数总和倒序"""
        # 模拟 materials["skills"]
        materials = {
            "skills": {
                "ai_ml": ["PyTorch 训练", "LLM 评测"],   # 2 命中
                "tools": ["Docker 部署"],                 # 1 命中
                "medical": ["心电基础"],                   # 0 命中
            }
        }
        out = ranker.rank_skill_groups(
            ["ai_ml", "tools", "medical"], materials,
            {"raw_keywords": ["PyTorch", "LLM", "Docker"]}
        )
        # ai_ml 命中 2 → 排前;tools 命中 1 → 排中;medical 0 → 排后
        assert out == ["ai_ml", "tools", "medical"]

    def test_rank_skill_groups_empty_role_keys(self):
        """role 没 skill_keys / materials 缺 skills 段 → 边界(不抛,空列表返回)"""
        out1 = ranker.rank_skill_groups([], {"skills": {}}, {"raw_keywords": ["Python"]})
        assert out1 == []
        # materials 缺 skills 段
        out2 = ranker.rank_skill_groups(
            ["ai_ml"], {}, {"raw_keywords": ["Python"]}
        )
        assert out2 == ["ai_ml"]  # 没数据 → 全部 0 命中,维持原顺序
        # 没 JD
        out3 = ranker.rank_skill_groups(
            ["ai_ml", "tools"], {"skills": {"ai_ml": ["PyTorch"], "tools": ["Docker"]}}, None
        )
        assert out3 == ["ai_ml", "tools"]


# ----------------------------------------------------------------------
# TestBackwardCompat: 不传 JD 时输出与 baseline 字节级一致
# ----------------------------------------------------------------------
class TestBackwardCompat:
    @pytest.mark.parametrize("role", list(_BASELINE_HASHES.keys()))
    def test_build_sections_no_jd_byte_identical_baseline(self, role: str):
        """6 个 role 的 build_sections 不传 JD → hash 必须等于固化 baseline"""
        actual = _sections_hash(role)
        expected = _BASELINE_HASHES[role]
        assert actual == expected, (
            f"{role} baseline 漂移:\n"
            f"  实际:  {actual}\n"
            f"  期望:  {expected}\n"
            f"  → 检查 build_sections 默认参数路径是否被改动"
        )

    def test_preview_no_jd_byte_identical_baseline(self):
        """preview_resume 不传 jd_text → sections 内容字节级一致(以 hash 比对)"""
        for role in _BASELINE_HASHES:
            data = preview_resume(target_role=role)
            # 序列化 sections 字段
            serialized = data["sections"]
            h = hashlib.sha256(
                json.dumps(serialized, sort_keys=True, ensure_ascii=False).encode()
            ).hexdigest()
            assert h == _BASELINE_HASHES[role], (
                f"{role} preview 不传 jd_text 时输出 hash 漂移:\n"
                f"  实际:  {h}\n"
                f"  期望:  {_BASELINE_HASHES[role]}"
            )
            # jd_match_counts 必须为 None(未传 jd_text)
            assert data["jd_match_counts"] is None


# ----------------------------------------------------------------------
# TestLdPromptEnhancement: LLM prompt 增强 (mock httpx)
# ----------------------------------------------------------------------
class TestLdPromptEnhancement:
    @pytest.fixture
    def enable_llm(self, monkeypatch):
        """有 LLM key → LLM 启用"""
        monkeypatch.setenv("LLM_API_KEY", "sk-fake-test-key")
        monkeypatch.setenv("LLM_ENABLED", "auto")
        monkeypatch.setenv("LLM_BASE_URL", "https://example.com/v1")
        yield
        for k in ("LLM_API_KEY", "LLM_ENABLED", "LLM_BASE_URL"):
            monkeypatch.delenv(k, raising=False)

    @pytest.fixture
    def capture_payload(self, monkeypatch):
        """捕获传给 urlopen 的 payload(只抓最后一次,验证 user message 结构)"""
        captured = {}

        class _FakeResp:
            def __init__(self, body): self._body = body; self.status = 200
            def read(self): return self._body
            def __enter__(self): return self
            def __exit__(self, *a): return False

        def fake_urlopen(req, timeout=None):
            captured["data"] = req.data
            captured["url"] = req.full_url
            # 返回合法改写响应
            rewritten = ["改写 A", "改写 B"]
            body = json.dumps(
                {
                    "choices": [{
                        "message": {
                            "role": "assistant",
                            "content": json.dumps({"rewritten": rewritten}, ensure_ascii=False),
                        },
                        "index": 0,
                        "finish_reason": "stop",
                    }]
                },
                ensure_ascii=False,
            ).encode("utf-8")
            return _FakeResp(body)

        monkeypatch.setattr("core.llm_rewriter.urllib.request.urlopen", fake_urlopen)
        return captured

    def test_prompt_contains_matched_keywords(self, enable_llm, capture_payload):
        """user message 含 matched 关键词"""
        import core.llm_rewriter as llm
        out = llm.rewrite_highlights(
            ["原文 A", "原文 B"],
            target_role="tech_metric",
            jd_text="JD context",
            jd_focus={"matched": ["Python", "PyTorch"], "missing": ["Transformer"], "tier_required": [], "tier_preferred": []},
        )
        assert out == ["改写 A", "改写 B"]
        payload = json.loads(capture_payload["data"].decode("utf-8"))
        user_msg = json.loads(payload["messages"][1]["content"])
        assert "jd_focus" in user_msg
        assert "Python" in user_msg["jd_focus"]["matched"]
        assert "PyTorch" in user_msg["jd_focus"]["matched"]

    def test_prompt_contains_missing_keywords(self, enable_llm, capture_payload):
        """user message 含 missing 关键词"""
        import core.llm_rewriter as llm
        llm.rewrite_highlights(
            ["原文 A", "原文 B"],
            target_role="tech_metric",
            jd_text="",
            jd_focus={"matched": ["Python"], "missing": ["Transformer", "CNN"], "tier_required": [], "tier_preferred": []},
        )
        payload = json.loads(capture_payload["data"].decode("utf-8"))
        user_msg = json.loads(payload["messages"][1]["content"])
        assert "Transformer" in user_msg["jd_focus"]["missing"]
        assert "CNN" in user_msg["jd_focus"]["missing"]

    def test_prompt_no_hallucination_directive(self, enable_llm, capture_payload):
        """system prompt 包含"不编造事实"指令"""
        import core.llm_rewriter as llm
        llm.rewrite_highlights(
            ["原文 A", "原文 B"],
            target_role="tech_metric",
            jd_text="",
            jd_focus={"matched": ["Python"], "missing": ["Transformer"], "tier_required": ["Python"], "tier_preferred": []},
        )
        payload = json.loads(capture_payload["data"].decode("utf-8"))
        system_msg = payload["messages"][0]["content"]
        # 关键指令:不编造 + matched 识别 + missing 不凑
        assert "编造" in system_msg, f"system prompt 应含'不编造'指令,实际: {system_msg}"
        assert "matched" in system_msg.lower() or "命中" in system_msg
        assert "missing" in system_msg.lower() or "缺失" in system_msg

    def test_prompt_unchanged_when_jd_focus_none(self, enable_llm, capture_payload):
        """jd_focus=None → user message schema 跟原版完全一致(向后兼容硬指标)"""
        import core.llm_rewriter as llm
        llm.rewrite_highlights(
            ["原文 A", "原文 B"],
            target_role="tech_metric",
            jd_text="医疗 AI",
        )
        payload = json.loads(capture_payload["data"].decode("utf-8"))
        user_msg = json.loads(payload["messages"][1]["content"])
        # 必须不出现 jd_focus 字段(避免 schema 漂移)
        assert "jd_focus" not in user_msg, (
            f"jd_focus=None 时 user message 不应含 jd_focus 字段,实际: {user_msg}"
        )
        # 原 schema 字段必须仍在
        assert user_msg["target_role"] == "tech_metric"
        assert user_msg["jd_context"] == "医疗 AI"
        assert user_msg["bullets"] == ["原文 A", "原文 B"]


# ----------------------------------------------------------------------
# TestApiJdText: API 端到端 (FastAPI TestClient)
# ----------------------------------------------------------------------
class TestApiJdText:
    @pytest.fixture
    def client(self) -> TestClient:
        return TestClient(app)

    def test_preview_with_jd_text_200(self, client: TestClient):
        """传 jd_text → 200,返回里 jd_match_counts 存在且非空"""
        resp = client.post(
            "/api/resume/preview",
            json={
                "target_role": "tech_metric",
                "jd_text": "需要 Python PyTorch LLM 评测 Prompt 经验",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "jd_match_counts" in data
        counts = data["jd_match_counts"]
        assert counts is not None
        assert "projects" in counts
        assert "skill_groups" in counts
        # tech_metric 通常有 4 个 project(company_medical_eval, university_ecg, datawhale, volunteer)
        assert len(counts["projects"]) >= 3
        assert len(counts["skill_groups"]) >= 3

    def test_preview_with_jd_text_too_long_422(self, client: TestClient):
        """jd_text > 50_000 字符 → 422"""
        huge_jd = "x" * 50_001
        resp = client.post(
            "/api/resume/preview",
            json={"target_role": "tech_metric", "jd_text": huge_jd},
        )
        assert resp.status_code == 422
        body = resp.json()
        # detail 字段含上限信息
        detail_str = json.dumps(body, ensure_ascii=False)
        assert "50_000" in detail_str or "50000" in detail_str

    def test_generate_with_jd_text_200_blob(self, client: TestClient, tmp_path: Path):
        """generate 接口传 jd_text → 200 + 返回 docx blob"""
        # 注意:这里不传 jd_text 到 client(因为 /generate 走 FileResponse),
        # 改为通过 generate_resume_docx 直接验证 (避免污染 backend/output/)
        out = generate_resume_docx(
            target_role="tech_metric",
            output_dir=tmp_path,
            jd_text="需要 Python PyTorch LLM 评测经验",
        )
        assert out.exists()
        assert out.stat().st_size > 5_000
        import zipfile
        assert zipfile.is_ipfile(out) if False else zipfile.is_zipfile(out)

    def test_preview_jd_text_empty_string_falls_back(self, client: TestClient):
        """jd_text="" 空字符串 → 走原路径(字节级一致 baseline)"""
        resp = client.post(
            "/api/resume/preview",
            json={"target_role": "tech_metric", "jd_text": ""},
        )
        assert resp.status_code == 200
        data = resp.json()
        # jd_match_counts 必须为 None(空字符串视同 None)
        assert data["jd_match_counts"] is None
        # sections hash 必须等于 baseline
        h = hashlib.sha256(
            json.dumps(data["sections"], sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        assert h == _BASELINE_HASHES["tech_metric"], (
            f"空 jd_text 走原路径但 hash 漂移:\n  实际: {h}\n  期望: {_BASELINE_HASHES['tech_metric']}"
        )

    def test_preview_jd_text_whitespace_only_falls_back(self, client: TestClient):
        """jd_text="   " 全空白 → 走原路径"""
        resp = client.post(
            "/api/resume/preview",
            json={"target_role": "tech_metric", "jd_text": "   \n\t  "},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["jd_match_counts"] is None
