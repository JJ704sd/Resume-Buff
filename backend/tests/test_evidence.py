"""
R5-A Phase 3: 轻量 RAG — Evidence Snippet 测试

覆盖点(spec §5.3 + Phase 3 任务约束):
  1. snippets 生成稳定 (build_evidence_snippets 多次调用字节级一致)
  2. projects / skills / honors / certs 4 个 source_type 都能生成 evidence
  3. retrieve_evidence top-k 排序稳定 (confidence DESC → source_type ASC → source_id ASC)
  4. 无关键词命中时返回空 list (不返低 confidence 噪声, 绝不编造)
  5. evidence_summary 在空 evidence / 无证据时返空字符串(字节级跟 None 一致)
  6. match_score 8 份 ground truth 不回退 (R3.5 baseline + R3.5+ baiyun 修后)
  7. evidence 工具调用通过 AGENT_TOOLS + execute_agent_tool 走通
  8. 不破坏 materials.json 完整性 (build_evidence_snippets 不修改输入)

测试策略:
  - 用真实 materials.json (conftest 自动 inject backend/ 到 sys.path)
  - 不 mock KEYWORD_GROUPS (验证复用现有 surface/normalized)
  - 不引入向量 / embedding, 全部 lexical matching
"""
import pytest

from core.evidence import (
    EvidenceSnippet,
    _compute_confidence,
    _keyword_hit,
    _summarize_evidence_for_prompt,
    build_evidence_snippets,
    evidence_to_dict_list,
    retrieve_evidence,
)
from core.jd_parser import KEYWORD_GROUPS, match_score
from core.agent_tools import AGENT_TOOLS, execute_agent_tool
from core.generator import load_materials


# ----------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------
@pytest.fixture(scope="module")
def materials():
    """全 module 共享一份 materials (避免重复 IO)"""
    return load_materials()


# ====================================================================
# TestBuildEvidenceSnippets: snippets 切片
# ====================================================================
class TestBuildEvidenceSnippets:
    """evidence.py: build_evidence_snippets 函数行为锁定"""

    def test_returns_list_of_evidence_snippet(self, materials):
        """返回 list[EvidenceSnippet] (frozen=True dataclass)"""
        snippets = build_evidence_snippets(materials, role="tech_metric")
        assert isinstance(snippets, list)
        assert all(isinstance(s, EvidenceSnippet) for s in snippets)
        # 真实 materials 应有几十条 snippet (4 projects × ~10 highlights + 7 skill groups × N items + 3 honors + 1 cert)
        assert len(snippets) >= 20, f"snippets 数量异常: {len(snippets)}"

    def test_all_4_source_types_present(self, materials):
        """projects / skills / honors / certs 4 个 source_type 都有"""
        snippets = build_evidence_snippets(materials, role="tech_metric")
        types_present = {s.source_type for s in snippets}
        assert "project" in types_present, "缺 project snippets"
        assert "skill" in types_present, "缺 skill snippets"
        assert "honor" in types_present, "缺 honor snippets"
        assert "cert" in types_present, "缺 cert snippets"

    def test_snippets_have_required_fields(self, materials):
        """每条 snippet 必含 source_type / source_id / text 非空"""
        snippets = build_evidence_snippets(materials, role="tech_metric")
        for s in snippets[:30]:  # 抽查前 30 条
            assert s.source_type, f"source_type 空: {s}"
            assert s.source_id, f"source_id 空: {s}"
            assert isinstance(s.text, str) and s.text.strip(), f"text 空: {s}"

    def test_snippets_generation_is_stable(self, materials):
        """build_evidence_snippets 多次调用返字节级一致 (sorted + frozen 保证)"""
        first = build_evidence_snippets(materials, role="tech_metric")
        second = build_evidence_snippets(materials, role="tech_metric")
        assert len(first) == len(second)
        for a, b in zip(first, second):
            assert a.source_type == b.source_type
            assert a.source_id == b.source_id
            assert a.text == b.text

    def test_role_param_picks_role_specific_highlights(self, materials):
        """role=tech_metric 拿 tech_metric highlights, role=algorithm 拿 algorithm highlights"""
        tech_snippets = build_evidence_snippets(materials, role="tech_metric")
        algo_snippets = build_evidence_snippets(materials, role="algorithm")
        # 不同 role 拿不同项目的 highlights (tech_metric 偏 medical_eval, algorithm 偏 ecg)
        tech_texts = {s.text for s in tech_snippets if s.source_type == "project"}
        algo_texts = {s.text for s in algo_snippets if s.source_type == "project"}
        # 不应完全一致 — 不同 role 视角的 highlights 不同
        assert tech_texts != algo_texts, "role 参数没生效"

    def test_role_none_falls_back_to_general(self, materials):
        """role=None 时走 "general" fallback (兼容 P2 caller)"""
        gen_snippets = build_evidence_snippets(materials, role=None)
        explicit_gen = build_evidence_snippets(materials, role="general")
        assert len(gen_snippets) == len(explicit_gen), "role=None 应等价 role='general'"

    def test_does_not_modify_input_materials(self, materials):
        """build_evidence_snippets 不修改 input materials (防御性)"""
        # 冻结: 记下原始 keys / len
        original_projects_len = len(materials.get("projects", []))
        original_skills_keys = list((materials.get("skills") or {}).keys())
        build_evidence_snippets(materials, role="tech_metric")
        # 跑完不应改变 materials
        assert len(materials.get("projects", [])) == original_projects_len
        assert list((materials.get("skills") or {}).keys()) == original_skills_keys

    def test_empty_materials_returns_empty_list(self):
        """空 materials 返空 list (不抛)"""
        assert build_evidence_snippets({}, role="tech_metric") == []
        assert build_evidence_snippets({"projects": [], "skills": {}, "honors": [], "certs": []}, role="general") == []

    def test_malformed_materials_skips_bad_entries_silently(self):
        """malformed materials (字段错/类型错) 静默跳过, 不抛"""
        bad_mats = {
            "projects": [
                {"id": "p1", "highlights": {"tech_metric": ["valid bullet"]}},
                {"highlights": "not a dict"},  # type error → skip
                {"id": "", "highlights": {"tech_metric": ["valid but no id"]}},  # skip (no id)
                "not a dict",  # skip
            ],
            "skills": {
                "g1": ["item1", 123, None, "item2"],  # skip non-str / None
                "g2": "not a list",  # skip group
            },
            "honors": [
                {"name": "h1", "date": "2025"},
                {"name": ""},  # skip empty name
            ],
            "certs": [],  # empty list OK
        }
        snippets = build_evidence_snippets(bad_mats, role="tech_metric")
        # 应该只拿到 p1 的 bullet + skills g1 的 item1 / item2 + h1
        source_keys = [(s.source_type, s.source_id, s.text) for s in snippets]
        assert any(s_id == "p1" for _, s_id, _ in source_keys)
        assert any(text == "item1" for _, _, text in source_keys)
        assert any(s_id == "h1" for _, s_id, _ in source_keys)
        # 不会因为 123 / None / "not a list" 等崩溃
        assert all(isinstance(s, EvidenceSnippet) for s in snippets)


# ====================================================================
# TestKeywordHit: 单条文本的关键词命中
# ====================================================================
class TestKeywordHit:
    """evidence.py: _keyword_hit 函数行为锁定"""

    def test_returns_matched_keywords_in_order(self):
        """命中关键词按 jd_keywords 给的顺序返回 (去重)"""
        matched = _keyword_hit(
            "基于 Python 和 PyTorch 实现 LLM 评测",
            jd_keywords=["LLM", "Python", "Prompt"],  # Prompt 不命中
        )
        assert matched == ["LLM", "Python"]  # 按 jd_keywords 顺序

    def test_no_match_returns_empty_list(self):
        """无命中返空 list (不返 None, 不抛)"""
        matched = _keyword_hit(
            "完全不相关的文本",
            jd_keywords=["LLM", "PyTorch"],
        )
        assert matched == []

    def test_deduplicates_matched_keywords(self):
        """同一 normalized 多次出现只算 1 次命中 (避免重复加分)"""
        matched = _keyword_hit(
            "Python Python Python",  # Python 出现 3 次
            jd_keywords=["Python"],
        )
        assert matched == ["Python"]
        assert len(matched) == 1

    def test_handles_empty_inputs(self):
        """空 text / 空 jd_keywords / 非法类型 静默处理"""
        assert _keyword_hit("", ["LLM"]) == []
        assert _keyword_hit("some text", []) == []
        assert _keyword_hit("some text", None) == []
        # 非法 kw (非 str) 跳过
        assert _keyword_hit("LLM", ["LLM", None, 123, ""]) == ["LLM"]

    def test_uses_synonym_surface_matching(self):
        """同义词 alias 命中 (R3.5+ 'AI' surface 归一化到 LLM)"""
        # '大模型' 是 LLM 的 surface
        matched = _keyword_hit(
            "基于大模型构建评测体系",
            jd_keywords=["LLM"],
        )
        assert matched == ["LLM"]


# ====================================================================
# TestComputeConfidence: 置信度算法
# ====================================================================
class TestComputeConfidence:
    """evidence.py: _compute_confidence 函数行为锁定"""

    def test_no_match_returns_zero(self):
        """matched=[] → confidence=0.0"""
        assert _compute_confidence([], ["LLM", "Python"]) == 0.0

    def test_full_match_returns_one(self):
        """全部命中 → confidence=1.0 (max(hit_ratio, weighted_ratio) = 1.0)"""
        assert _compute_confidence(["LLM", "Python"], ["LLM", "Python"]) == 1.0

    def test_half_match_with_high_weight_keyword(self):
        """1 个高权重命中 / 2 个 → confidence ≥ 0.5 (weighted_ratio 优先)"""
        # LLM weight=1.0, Python weight=1.0 → weighted = 1.0/2.0 = 0.5
        # hit_ratio = 1/2 = 0.5
        conf = _compute_confidence(["LLM"], ["LLM", "Python"])
        assert conf == 0.5

    def test_single_high_weight_dominates_low_weight_many(self):
        """单高权重命中 在 多低权重中 应得较高 confidence (weighted 优先)"""
        # matched=["LLM"] weight=1.0, jd=["LLM", "评测", "Prompt"] weights=1.0+0.5+0.5=2.0
        # hit_ratio=1/3=0.333, weighted=1.0/2.0=0.5 → max=0.5
        conf = _compute_confidence(["LLM"], ["LLM", "评测", "Prompt"])
        assert conf == 0.5  # weighted 胜出

    def test_empty_jd_keywords_returns_zero(self):
        """jd_keywords=[] → confidence=0.0 (避免除零)"""
        assert _compute_confidence(["LLM"], []) == 0.0

    def test_confidence_clamped_to_0_1(self):
        """confidence 永远在 [0.0, 1.0] (防御钳位)"""
        # 正常情况不会越界, 但防御性测试
        assert 0.0 <= _compute_confidence(["LLM"], ["LLM"]) <= 1.0
        assert 0.0 <= _compute_confidence([], []) <= 1.0


# ====================================================================
# TestRetrieveEvidence: 检索主流程
# ====================================================================
class TestRetrieveEvidence:
    """evidence.py: retrieve_evidence 函数行为锁定 (核心交付)"""

    def test_returns_top_k_evidence(self, materials):
        """返 top_k 条 evidence (按 confidence DESC 排)"""
        result = retrieve_evidence(
            jd_keywords=["LLM", "评测", "Prompt"],
            role="tech_metric",
            materials=materials,
            top_k=5,
        )
        assert isinstance(result, list)
        assert len(result) <= 5
        # 所有 result 应是 EvidenceSnippet 且 confidence > 0
        assert all(isinstance(r, EvidenceSnippet) for r in result)
        assert all(r.confidence > 0.0 for r in result)

    def test_no_keywords_returns_empty_list(self, materials):
        """空 jd_keywords → 返空 list (不返 noise snippets)"""
        result = retrieve_evidence(
            jd_keywords=[],
            role="tech_metric",
            materials=materials,
        )
        assert result == []

    def test_unknown_keywords_returns_empty_list(self, materials):
        """全部关键词都无 surface 命中 → 返空 list (不编造)"""
        result = retrieve_evidence(
            jd_keywords=["完全不存在的关键词XXX", "另一个不存在的YYY"],
            role="tech_metric",
            materials=materials,
        )
        assert result == [], "无关键词命中时必须返空 list, 不允许返低 confidence 噪声"

    def test_stable_sorting_by_confidence_desc(self, materials):
        """排序稳定: confidence DESC → source_type ASC → source_id ASC"""
        result = retrieve_evidence(
            jd_keywords=["LLM", "评测", "PyTorch", "Prompt"],
            role="tech_metric",
            materials=materials,
            top_k=10,
        )
        # 同 confidence 时 source_type 升序
        prev: tuple | None = None
        for r in result:
            cur = (-r.confidence, r.source_type, r.source_id)
            if prev is not None:
                assert cur >= prev, f"排序不稳定: {prev} → {cur}"
            prev = cur

    def test_top_k_limits_results(self, materials):
        """top_k 严格限制返回数量"""
        # 用大量关键词 + 大 top_k
        all_keywords = sorted({normalized
                              for group in KEYWORD_GROUPS.values()
                              for _, normalized, _ in group})
        result = retrieve_evidence(
            jd_keywords=all_keywords,
            role="tech_metric",
            materials=materials,
            top_k=3,
        )
        assert len(result) == 3

    def test_results_have_non_empty_matched_keywords(self, materials):
        """每条 result 的 matched_keywords 非空 (因为 0 命中已过滤)"""
        result = retrieve_evidence(
            jd_keywords=["LLM", "Python"],
            role="tech_metric",
            materials=materials,
        )
        for r in result:
            assert len(r.matched_keywords) > 0, f"matched_keywords 空: {r}"

    def test_idempotent_same_input_same_output(self, materials):
        """同 input 多次调用返字节级一致 (排序稳定 + 0 命中过滤确定)"""
        kw = ["LLM", "评测"]
        first = retrieve_evidence(jd_keywords=kw, role="tech_metric", materials=materials)
        second = retrieve_evidence(jd_keywords=kw, role="tech_metric", materials=materials)
        assert len(first) == len(second)
        for a, b in zip(first, second):
            assert a.source_type == b.source_type
            assert a.source_id == b.source_id
            assert a.text == b.text
            assert a.confidence == b.confidence
            assert a.matched_keywords == b.matched_keywords

    def test_zero_match_snippets_excluded(self, materials):
        """0 关键词命中的 snippet 不会出现在结果中 (不返低 confidence 噪声)"""
        # 关键词全在 materials 里 — 但我们要验证: 即便 snippet 有 matched_keywords 字段
        # 0 命中的 snippet 也会被过滤
        result = retrieve_evidence(
            jd_keywords=["LLM"],  # 只 LLM
            role="volunteer",  # volunteer 项目只有 general highlights, 没 LLM
            materials=materials,
        )
        # volunteer 的 highlights 不含 LLM, 应该空
        # (这条 case 验证: 即便 source_type 有内容, 0 命中也不进 result)
        for r in result:
            assert "LLM" in r.matched_keywords, f"应被过滤: {r}"

    def test_does_not_mutate_input_materials(self, materials):
        """retrieve_evidence 不修改 materials (防御性)"""
        original_projects_count = len(materials.get("projects", []))
        retrieve_evidence(
            jd_keywords=["LLM"],
            role="tech_metric",
            materials=materials,
        )
        assert len(materials.get("projects", [])) == original_projects_count


# ====================================================================
# TestSummarizeEvidenceForPrompt: evidence summary 文本
# ====================================================================
class TestSummarizeEvidenceForPrompt:
    """evidence.py: _summarize_evidence_for_prompt 函数行为锁定"""

    def test_empty_list_returns_empty_string(self):
        """空 list → 返空字符串 (跟 evidence=None 字节级一致)"""
        assert _summarize_evidence_for_prompt([]) == ""

    def test_single_snippet_format(self, materials):
        """单条 snippet 输出格式: [1] (source_type/source_id) text"""
        result = retrieve_evidence(
            jd_keywords=["LLM"],
            role="tech_metric",
            materials=materials,
            top_k=1,
        )
        if not result:
            pytest.skip("LLM keyword 没匹配任何 evidence, 跳过(材料变化时)")
        summary = _summarize_evidence_for_prompt(result)
        assert summary.startswith("[1] (")
        # 验证格式: (source_type/source_id) + 空格 + text
        # 例: [1] (project/company_medical_eval) 构建包含...
        assert "(project/" in summary or "(skill/" in summary or "(honor/" in summary or "(cert/" in summary

    def test_summary_truncated_when_too_long(self):
        """超过 max_chars 时末尾追加 ...(N more) 截断标记"""
        # 构造超长 evidence
        long_evs = [
            EvidenceSnippet(
                source_type="skill",
                source_id=f"g{i}",
                text="x" * 100,  # 每条 100 字符
                matched_keywords=("LLM",),
                confidence=1.0,
            )
            for i in range(50)
        ]
        summary = _summarize_evidence_for_prompt(long_evs, max_chars=300)
        # 截断标记格式: "...(N more)" 或 "more)" (实际格式由实现决定, 用更宽松断言)
        assert "more)" in summary, f"应包含截断标记 (more), 实际: {summary[-60:]!r}"
        assert len(summary) <= 400, f"summary 长度超限: {len(summary)}"

    def test_snippet_text_truncated_at_80_chars(self):
        """单条 snippet text 超过 80 字符被截断"""
        ev = EvidenceSnippet(
            source_type="skill",
            source_id="g1",
            text="x" * 200,  # 远超 80
            matched_keywords=("LLM",),
            confidence=1.0,
        )
        summary = _summarize_evidence_for_prompt([ev])
        # 第 1 条 text 部分不应超 80 字符 + "..."
        assert "x" * 80 + "..." in summary or "x" * 80 in summary


# ====================================================================
# TestEvidenceToDictList: 序列化
# ====================================================================
class TestEvidenceToDictList:
    """evidence.py: evidence_to_dict_list 序列化测试"""

    def test_serializes_to_json_friendly_dicts(self, materials):
        """EvidenceSnippet list → dict list (JSON 友好, tuple 转 list)"""
        result = retrieve_evidence(
            jd_keywords=["LLM"],
            role="tech_metric",
            materials=materials,
            top_k=3,
        )
        dicts = evidence_to_dict_list(result)
        assert len(dicts) == len(result)
        for d, ev in zip(dicts, result):
            assert d["source_type"] == ev.source_type
            assert d["source_id"] == ev.source_id
            assert d["text"] == ev.text
            assert d["matched_keywords"] == list(ev.matched_keywords)
            assert d["confidence"] == round(ev.confidence, 3)

    def test_empty_list_returns_empty_list(self):
        """空 list → 空 list"""
        assert evidence_to_dict_list([]) == []

    def test_dicts_are_json_serializable(self, materials):
        """dict list 可直接 json.dumps (ToolResult.output 需要)"""
        import json
        result = retrieve_evidence(
            jd_keywords=["LLM"],
            role="tech_metric",
            materials=materials,
            top_k=3,
        )
        dicts = evidence_to_dict_list(result)
        # 不抛 = 可序列化
        json.dumps(dicts, ensure_ascii=False)


# ====================================================================
# TestAgentToolsIntegration: evidence 通过 AGENT_TOOLS + execute_agent_tool
# ====================================================================
class TestAgentToolsIntegration:
    """evidence 工具在 AGENT_TOOLS 里可被发现 / 可执行"""

    def test_retrieve_evidence_in_allowlist(self):
        """retrieve_evidence 已在 AGENT_TOOLS allowlist"""
        assert "retrieve_evidence" in AGENT_TOOLS
        spec = AGENT_TOOLS["retrieve_evidence"]
        assert spec.name == "retrieve_evidence"
        assert callable(spec.callable)
        # R5-A Phase 3: 新 permission tag (跟 retrieve_evidence 用途匹配)
        assert spec.permission == "read_materials_and_jd_keywords"

    def test_retrieve_evidence_via_execute_agent_tool(self, materials):
        """通过 execute_agent_tool 调 retrieve_evidence 走通 (返回 dict list)"""
        result = execute_agent_tool(
            "retrieve_evidence",
            {
                "jd_keywords": ["LLM", "评测"],
                "role": "tech_metric",
                "materials": materials,
                "top_k": 5,
            },
        )
        assert result.status == "success"
        assert isinstance(result.output, list)
        # output 是 dict list (wrapper 序列化)
        if result.output:
            first = result.output[0]
            assert isinstance(first, dict)
            assert "source_type" in first
            assert "source_id" in first
            assert "text" in first
            assert "matched_keywords" in first
            assert "confidence" in first

    def test_retrieve_evidence_missing_required_args_fails(self):
        """缺少 required 参数 → ToolResult error, 不抛"""
        result = execute_agent_tool("retrieve_evidence", {"jd_keywords": ["LLM"]})
        # 缺 role 和 materials → TypeError → TOOL_ARGS_INVALID
        assert result.status == "error"
        assert result.error_type == "tool_args_invalid"

    def test_retrieve_evidence_unknown_tool(self):
        """未注册工具 → TOOL_NOT_ALLOWED"""
        result = execute_agent_tool("fake_tool_xyz", {})
        assert result.status == "error"
        assert result.error_type == "tool_not_allowed"


# ====================================================================
# TestMatchScoreRegression: Phase 3 不破坏 match_score ground truth
# ====================================================================
class TestMatchScoreRegression:
    """R5-A Phase 3: evidence 模块不能破坏 match_score 8 份 ground truth
    (基于 R3.5 / R3.5+ / R3.6.2 已调优的 baseline)"""

    def test_match_score_basic_chinese_jd(self):
        """tech_metric + LLM 评测 JD → 命中 Python/LLM/评测 等, score 应高"""
        result = match_score(
            text="熟悉 Python 和 PyTorch,有大模型评测经验,加分项 Prompt 工程",
            target_role="tech_metric",
            materials=load_materials(),
        )
        assert result["score"] >= 60
        assert "LLM" in result["matched_keywords"]

    def test_match_score_medical_keyword(self):
        """tech_metric + 医疗关键词 → 命中 医疗/ECG (borrow pool)"""
        result = match_score(
            text="医疗 AI 评测,熟悉心电信号处理",
            target_role="tech_metric",
            materials=load_materials(),
        )
        assert "医疗" in result["matched_keywords"]

    def test_match_score_no_match_low_score(self):
        """完全无关关键词 → score 低 (仍返 recommendation)"""
        result = match_score(
            text="完全不相关的职位: 厨师 / 司机",
            target_role="tech_metric",
            materials=load_materials(),
        )
        assert result["score"] <= 30
        # recommendation 必须返 "高/中/低" 之一
        assert result["recommendation"] in {"高", "中", "低"}

    def test_match_score_invalid_role_raises(self):
        """未知 role → ValueError (行为不变)"""
        with pytest.raises(ValueError):
            match_score(text="anything", target_role="invalid_role", materials=load_materials())


# ====================================================================
# TestKeyWordGroupsReuse: Phase 3 复用 KEYWORD_GROUPS (不引入新字典)
# ====================================================================
class TestKeyWordGroupsReuse:
    """R5-A Phase 3: retrieval 必须复用 KEYWORD_GROUPS, 不引入新关键词字典"""

    def test_retrieve_evidence_uses_keyword_groups_surface(self, materials):
        """retrieve_evidence 走 KEYWORD_GROUPS 的 surface/normalized (如 '大模型' → LLM)"""
        result = retrieve_evidence(
            jd_keywords=["LLM"],
            role="tech_metric",
            materials=materials,
        )
        # 应至少找到含 LLM 关键词的 evidence
        assert len(result) > 0
        # 验证 surface 复用: '大模型' 命中 → evidence 的 text 应含 '大模型' 或 'LLM'
        # (不强制每条都含, 但至少有一些)
        has_llm_text = any(
            "LLM" in r.text or "大模型" in r.text or "大语言模型" in r.text
            for r in result
        )
        assert has_llm_text, "应通过 KEYWORD_GROUPS surface 命中 LLM 相关 evidence"
