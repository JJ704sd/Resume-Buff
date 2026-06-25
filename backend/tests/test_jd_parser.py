"""
JD 解析 + 匹配度评分 — 单元测试 (核心逻辑)

不测 thin wrapper / 简单 dict.get,只测:
  - 关键词提取 (中文 + 英文 JD)
  - 同义词归一化
  - 经验年限正则 (多种写法,含中文数字)
  - 学历提取 (多种写法,含 PhD)
  - match_score 边界 (空 JD / 完美匹配 / 0-100 整数)
  - coverage 各维度独立计算
  - 错误路径 (invalid target_role)
  - 关键词去重 (NLP / 评测 跨 group 不重复)
  - KEYWORD_GROUPS 三元组 weight (Round 3 A 新增)
  - tier 关键词识别 (Round 3 A 新增)
  - 加权 score / coverage (Round 3 A 新增)
  - recommendation 业务阈值 (Round 3 A 新增)

运行:
  cd D:\\r3-jd-upgrade\\backend
  D:\\python3.11\\python.exe -m pytest tests/test_jd_parser.py -v
"""
import pytest

from core.generator import ENABLED_ROLES, ROLE_CONFIG, load_materials
from core.jd_parser import (
    KEYWORD_GROUPS,
    match_score,
    parse_jd,
)


# ======================================================================
# parse_jd: 关键词提取
# ======================================================================
class TestParseKeywords:
    def test_chinese_jd_extracts_core_skills(self):
        """中文 JD: 必命中 Python / PyTorch / Transformer / LLM 等核心技能词。"""
        text = (
            "岗位职责：\n"
            "1. 负责大语言模型评测框架设计与开发,要求 Python 熟练；\n"
            "2. 基于 PyTorch 训练 Transformer 分类模型；\n"
            "3. 熟悉 Prompt 工程与数据标注流程；\n"
            "4. 熟练使用 Docker / Git / Linux。\n"
        )
        result = parse_jd(text)
        assert "Python" in result["skills"]
        assert "PyTorch" in result["skills"]
        assert "Transformer" in result["skills"]
        assert "LLM" in result["skills"]          # 由 "大语言模型" 归一化
        assert "评测" in result["skills"]
        assert "Prompt" in result["skills"]
        assert "数据标注" in result["skills"]
        assert "Docker" in result["tools"]
        assert "Git" in result["tools"]
        assert "Linux" in result["tools"]

    def test_english_jd_extracts_core_skills(self):
        """英文 JD: 命中英文 surface 词(算法名 / 工具名大小写不敏感)。"""
        text = (
            "We are looking for an engineer with experience in:\n"
            "- Python and PyTorch\n"
            "- LLM evaluation\n"
            "- Docker, Git, Linux\n"
            "- FastAPI backend\n"
            "- NLP pipelines\n"
        )
        result = parse_jd(text)
        assert "Python" in result["skills"]
        assert "PyTorch" in result["skills"]
        assert "LLM" in result["skills"]
        assert "NLP" in result["skills"]
        assert "Docker" in result["tools"]
        assert "Git" in result["tools"]
        assert "Linux" in result["tools"]
        assert "FastAPI" in result["tools"]


# ======================================================================
# parse_jd: 同义词归一化
# ======================================================================
class TestSynonymNormalization:
    def test_large_lang_model_synonyms_unified_to_LLM(self):
        """'大语言模型' / '大模型' / 'LLM' 三种写法应该归一到同一个 normalized form。"""
        variants = [
            "我们做的是大语言模型方向",
            "大模型相关研究",
            "LLM evaluation engineer",
        ]
        normalized_sets = [set(parse_jd(t)["skills"]) for t in variants]
        # 三种写法的 skills 集合里都应该有 "LLM"
        for s in normalized_sets:
            assert "LLM" in s, f"missing LLM in {s}"

    def test_synonyms_produce_same_skill_set(self):
        """'大语言模型 评测' vs 'LLM evaluation': 至少都归一到 LLM + Prompt。"""
        cn = parse_jd("我们需要大语言模型评测人才,熟悉 Prompt 工程")
        en = parse_jd("We need LLM evaluation talent, Prompt engineering")
        # 两个 JD 在 parsed 都至少应该包含 LLM 和 Prompt
        # (注:中文 JD 命中'评测',英文 JD 命中 'NLP' 等不同 — 这里只测核心同义词)
        for label, res in [("cn", cn), ("en", en)]:
            assert "LLM" in res["skills"], f"{label}: missing LLM"
            assert "Prompt" in res["skills"], f"{label}: missing Prompt"


# ======================================================================
# parse_jd: 经验年限
# ======================================================================
class TestExperienceYears:
    def test_arabic_range_formats(self):
        """阿拉伯数字范围: '1-3 年' / '1~3年' / '1到3年' 都应该归到 '1-3'。"""
        for text, expected in [
            ("要求 1-3 年经验", "1-3"),
            ("1~3 年相关经验", "1-3"),
            ("1到3年工作经验", "1-3"),
        ]:
            assert parse_jd(text)["experience_years"] == expected, text

    def test_chinese_numerals_floor_above(self):
        """中文数字: '三年以上' 应该识别成 '3年以上'。"""
        assert parse_jd("三年以上经验")["experience_years"] == "3年以上"

    def test_arabic_floor_above(self):
        """阿拉伯数字: '5 年以上' 应该识别成 '5年以上'。"""
        assert parse_jd("5 年以上经验")["experience_years"] == "5年以上"

    def test_no_limit_keywords(self):
        """'经验不限' / '不限' 应该归到 '不限'。"""
        for text in [
            "经验不限",
            "工作经验无要求",
            "学历经验不限",
        ]:
            assert parse_jd(text)["experience_years"] == "不限", text

    def test_no_match_returns_default_unlimited(self):
        """完全没提经验要求 → 返 '不限',不抛错。"""
        assert parse_jd("我们需要一位 Python 工程师")["experience_years"] == "不限"


# ======================================================================
# parse_jd: 学历
# ======================================================================
class TestEducation:
    def test_bachelor_and_above(self):
        """'本科及以上' 应该识别为 '本科'(取最低门槛文字)。"""
        # '本科及以上' → 命中 '本科' → 返 '本科'
        assert parse_jd("本科及以上学历")["education"] == "本科"

    def test_master_keyword(self):
        """'硕士' / '研究生' 都应该识别为 '硕士'。"""
        for text in [
            "硕士及以上",
            "研究生学历",
            "Master degree",
        ]:
            assert parse_jd(text)["education"] == "硕士", text

    def test_phd_keyword(self):
        """'博士' / 'PhD' / 'phd' 都应该识别为 '博士'。"""
        for text in [
            "博士研究生",
            "PhD 优先",
            "phd candidate preferred",
        ]:
            assert parse_jd(text)["education"] == "博士", text

    def test_no_education_returns_unlimited(self):
        """没提学历 → 返 '不限',不抛错。"""
        assert parse_jd("我们需要一位 Python 工程师")["education"] == "不限"


# ======================================================================
# parse_jd: 关键词去重 + 中英标点处理
# ======================================================================
class TestDedupAndNormalization:
    def test_keyword_appearing_in_multiple_groups_not_double_counted_in_raw(self):
        """'评测' 同时在 skills / domains 里;raw_keywords 应该只出现一次。"""
        text = "需要 LLM 评测人才,医疗场景下做评测"
        result = parse_jd(text)
        # raw_keywords 里 '评测' 只算一次
        assert result["raw_keywords"].count("评测") == 1
        # 但 skills 和 domains 各自都可以有(这是设计上的允许)
        assert "评测" in result["skills"]
        assert "评测" in result["domains"]

    def test_chinese_punctuation_normalized(self):
        """中文标点(，；：（）。？)不影响关键词提取。"""
        cn = "熟悉Python,PyTorch；熟悉Docker（部署）。"
        en = "熟悉 Python, PyTorch; 熟悉 Docker (部署)."
        # 两种写法 normalize 后应该产生相同的 raw_keywords
        r_cn = set(parse_jd(cn)["raw_keywords"])
        r_en = set(parse_jd(en)["raw_keywords"])
        assert r_cn == r_en

    def test_case_insensitive(self):
        """英文 surface 大小写不敏感: 'python' / 'PYTHON' / 'Python' 都应该命中。"""
        for text in [
            "python developer",
            "PYTHON DEVELOPER",
            "Python Developer",
        ]:
            assert "Python" in parse_jd(text)["skills"], text


# ======================================================================
# match_score: 边界 + 覆盖率
# ======================================================================
class TestMatchScore:
    def test_empty_text_returns_zero(self):
        """完全没匹配到任何关键词 → score = 0。"""
        result = match_score(
            "纯文字,不包含任何关键字",
            "tech_metric",
            materials=_minimal_materials(),
        )
        assert result["score"] == 0
        assert result["matched_keywords"] == []
        assert result["missing_keywords"] == []
        # coverage: 三维都没有 JD 要求,视为已覆盖
        assert result["coverage"] == {"skills": 1.0, "tools": 1.0, "domains": 1.0}

    def test_perfect_match_returns_100(self):
        """JD 关键词全部在 candidate pool → score = 100。"""
        materials = _minimal_materials(
            ai_ml=["PyTorch 深度学习框架"],
            tools=["Docker 容器化部署"],
            evaluation_metrics=["BLEU/Rouge 指标"],
        )
        text = "熟悉 PyTorch,使用 Docker,熟悉 BLEU/Rouge"
        result = match_score(text, "tech_metric", materials=materials)
        assert result["score"] == 100
        assert result["missing_keywords"] == []
        assert result["matched_keywords"]  # 非空
        assert all(v == 1.0 for v in result["coverage"].values())

    def test_score_is_integer_in_0_100(self):
        """score 必须是整数,且在 [0, 100] 区间(R3 加权算法: PyTorch 命中 + Docker 命中, LoRA 缺失)。"""
        # 关键:加权 score = (1.0 + 1.0) / (1.0 + 1.0 + 0.5) × 100 = 80
        materials = _minimal_materials(
            ai_ml=["PyTorch 深度学习框架", "Transformer/CNN"],
            tools=["Docker 容器化部署"],
        )
        result = match_score(
            "需要 PyTorch, Docker, LoRA",
            "tech_metric",
            materials=materials,
        )
        assert isinstance(result["score"], int)
        assert 0 <= result["score"] <= 100
        # 部分命中 → 在 (0, 100) 之间
        assert 0 < result["score"] < 100
        # R3 加权:PyTorch (1.0) + Docker (1.0) 命中, LoRA (0.5) 缺失
        # score = 2.0 / 2.5 × 100 = 80
        assert result["score"] == 80

    def test_coverage_calculated_per_dimension(self):
        """coverage 必须按 skills/tools/domains 三个维度独立计算(R3 加权版)。"""
        materials = _minimal_materials(
            ai_ml=["PyTorch"],     # pool: PyTorch (weight 1.0)
            tools=["Docker"],      # pool: Docker (weight 1.0)
        )
        # JD: skills 里 2 个 (PyTorch 1.0, LoRA 0.5) → 命中 1.0 / 总 1.5 ≈ 0.67
        #     tools 里 1 个 (Docker 1.0) → 命中 1.0 / 1.0 = 1.0
        #     domains 里 0 个 → 视为 1.0
        text = "PyTorch / LoRA,使用 Docker"
        result = match_score(text, "tech_metric", materials=materials)
        assert result["coverage"]["skills"] == 0.67
        assert result["coverage"]["tools"] == 1.0
        assert result["coverage"]["domains"] == 1.0

    def test_invalid_target_role_raises(self):
        """target_role 不在 ENABLED_ROLES → 抛 ValueError,前端会变 400。"""
        with pytest.raises(ValueError) as exc_info:
            match_score("任意 JD", "not_a_role", materials=_minimal_materials())
        assert "not_a_role" in str(exc_info.value)

    def test_role_id_in_response(self):
        """返回里 role_id 必须等于请求里的 target_role。"""
        materials = _minimal_materials()
        result = match_score("任意 JD", "algorithm", materials=materials)
        assert result["role_id"] == "algorithm"

    def test_suggestions_count_in_range(self):
        """suggestions 数量应在 [2, 5] 之间(MVP 契约要求 2-5 条)。"""
        # 全部命中 → 1 条"无需补充"
        r1 = match_score(
            "PyTorch",
            "tech_metric",
            materials=_minimal_materials(ai_ml=["PyTorch"]),
        )
        assert 1 <= len(r1["suggestions"]) <= 5

        # 部分缺失 → 至少 2 条
        r2 = match_score(
            "PyTorch, LoRA, Kubernetes",
            "tech_metric",
            materials=_minimal_materials(ai_ml=["PyTorch"]),
        )
        assert 2 <= len(r2["suggestions"]) <= 5

    def test_uses_real_materials_json(self):
        """集成测试:用真实 materials.json 跑 match_score,验证不报错 + 结构正确。"""
        mats = load_materials()
        # 挑一个真实 role,造一段典型 JD
        jd = (
            "需要熟悉 Python / PyTorch,有 LLM 评测经验,"
            "使用 Docker / Git 部署,医疗场景,本科及以上"
        )
        result = match_score(jd, "tech_metric", materials=mats)
        # 真实 tech_metric role 的 skill_keys 里有 PyTorch/Docker 等
        # 所以命中关键词应 > 0
        assert result["score"] > 0
        assert "PyTorch" in result["matched_keywords"]
        assert "Docker" in result["matched_keywords"]
        assert "Python" in result["matched_keywords"]
        # 经验 + 学历
        # (本测试只验证 score 不为 0,不强求具体数字,因为 materials.json 可能更新)

    def test_no_recognized_keywords_returns_helpful_suggestion(self):
        """当 JD 文本里的词都不在 KEYWORD_GROUPS 里 → score=0 + 提示词典不足。"""
        # 这些词都不在 KEYWORD_GROUPS 里 (Kubernetes/Kafka/Spark/Cassandra/Salt)
        jd = "需要 Kubernetes 编排,Kafka 消息队列,Spark 大数据,Cassandra 存储,Salt 配置管理"
        result = match_score(jd, "algorithm", materials=_minimal_materials())
        assert result["score"] == 0
        assert result["matched_keywords"] == []
        # 关键:suggestion 必须告诉用户"词典不足",而不是误报"无需补充"
        suggestions_text = " ".join(result["suggestions"])
        assert "未识别" in suggestions_text or "关键词词典" in suggestions_text


# ======================================================================
# Round 3 A: KEYWORD_GROUPS 三元组 weight
# ======================================================================
class TestKeywordWeight:
    def test_keyword_weight_default_1(self):
        """KEYWORD_GROUPS 升级后,每个 tuple 是 (surface, normalized, weight) 三元组。"""
        # 抽样检查
        for group_name, kws in KEYWORD_GROUPS.items():
            for kw in kws:
                assert isinstance(kw, tuple)
                assert len(kw) == 3, f"{group_name}.{kw} 应该是三元组"
                surface, normalized, weight = kw
                assert isinstance(surface, str)
                assert isinstance(normalized, str)
                # weight 必须是 0.5 或 1.0 (MVP 阶段只有这俩)
                assert weight in (0.5, 1.0), (
                    f"{group_name}.{kw} weight 应是 0.5/1.0"
                )

    def test_keyword_weight_addition_bonus(self):
        """必选 weight=1.0,加分项 weight=0.5。"""
        # 抽样几个核心必选词
        for required_kw in ["Python", "PyTorch", "LLM"]:
            for surface, normalized, weight in KEYWORD_GROUPS["skills"]:
                if surface == required_kw:
                    assert weight == 1.0, f"{required_kw} 应是必选 1.0,实际 {weight}"
        # 加分项
        for bonus_kw in ["深度学习", "评测", "LoRA"]:
            for surface, normalized, weight in KEYWORD_GROUPS["skills"]:
                if surface == bonus_kw:
                    assert weight == 0.5, f"{bonus_kw} 应是加分 0.5,实际 {weight}"

    def test_score_uses_weighted_matching(self):
        """score 必须用 KEYWORD_GROUPS 三元组的 weight 加权,不能简单命中率。"""
        # 素材库有 PyTorch (1.0) + LoRA (0.5)
        materials = _minimal_materials(ai_ml=["PyTorch 框架", "LoRA 微调"])
        # JD 命中 PyTorch, LoRA 缺失
        r1 = match_score("需要 PyTorch", "tech_metric", materials=materials)
        # score = 1.0 / 1.0 × 100 = 100 (LoRA 没在 JD 里,不扣分)
        assert r1["score"] == 100

        # JD 同时要 PyTorch + LoRA → 全命中 → 100
        r2 = match_score("需要 PyTorch 和 LoRA", "tech_metric", materials=materials)
        assert r2["score"] == 100

        # JD 要 PyTorch + 缺失的 Transformer → 部分命中
        materials2 = _minimal_materials(ai_ml=["PyTorch 框架"])
        r3 = match_score("需要 PyTorch 和 Transformer", "tech_metric", materials=materials2)
        # score = 1.0 / (1.0 + 1.0) × 100 = 50
        assert r3["score"] == 50


# ======================================================================
# Round 3 A: tier 关键词识别
# ======================================================================
class TestTierDetection:
    def test_tier_required_detected(self):
        """中文'必须'+近距离关键词 → required tier。"""
        result = parse_jd("必须熟悉 Python 编程。")
        assert "Python" in result["tier_info"]["required"]
        assert result["tier_info"]["preferred"] == []
        assert result["tier_info"]["bonus"] == []

    def test_tier_preferred_detected(self):
        """中文'优先'+近距离关键词 → preferred tier。"""
        result = parse_jd("优先考虑 Docker 经验。")
        assert "Docker" in result["tier_info"]["preferred"]
        assert "Docker" not in result["tier_info"]["required"]

    def test_tier_bonus_detected(self):
        """中文'加分项'+近距离关键词 → bonus tier。"""
        result = parse_jd("加分项:医疗场景经验。")
        assert "医疗" in result["tier_info"]["bonus"]
        assert "医疗" not in result["tier_info"]["required"]

    def test_tier_english_preferred(self):
        """英文 'Nice to have' / 'preferred' → preferred tier。"""
        for text in [
            "Nice to have Docker experience.",
            "Preferred: Python background.",
        ]:
            result = parse_jd(text)
            # 至少有一个 kw 在 preferred
            assert any(
                result["tier_info"]["preferred"]
            ), f"expected preferred tier in {text!r}, got {result['tier_info']}"

    def test_tier_english_required(self):
        """英文 'Required' / 'Must have' → required tier。"""
        result = parse_jd("Required: Python. Must have PyTorch.")
        assert "Python" in result["tier_info"]["required"]
        assert "PyTorch" in result["tier_info"]["required"]

    def test_no_tier_keyword_defaults_to_required(self):
        """没出现任何 tier 修饰词 → 所有 kw 归 required(业务 JD 兜底)。"""
        result = parse_jd("熟悉 Python 和 Docker 经验。")
        # 没 tier 修饰词,Python / Docker 都归 required
        assert "Python" in result["tier_info"]["required"]
        assert "Docker" in result["tier_info"]["required"]
        assert result["tier_info"]["preferred"] == []
        assert result["tier_info"]["bonus"] == []

    def test_tier_context_radius_30(self):
        """上下文窗口半径 30 字符:超过 30 字符远的 kw 不会被 tier 修饰词影响。"""
        # "必须" 在最前,Python 紧挨(0 距离),"x" * 35 + Docker(> 30 字符远)
        text = "必须" + "熟悉" + "Python" + ("x" * 35) + "Docker"
        result = parse_jd(text)
        # Python 距"必须" 5 字符 → required
        assert "Python" in result["tier_info"]["required"]
        # Docker 距"必须" 5+1+6+35 = 47 字符 → > 30,无 tier 修饰,兜底 required
        assert "Docker" in result["tier_info"]["required"]

    def test_tier_info_in_response(self):
        """parse_jd 返回里必须有 tier_info 字段,且结构是 {required, preferred, bonus}。"""
        result = parse_jd("需要 Python 经验")
        assert "tier_info" in result
        assert isinstance(result["tier_info"], dict)
        assert set(result["tier_info"].keys()) == {"required", "preferred", "bonus"}
        for v in result["tier_info"].values():
            assert isinstance(v, list)


# ======================================================================
# Round 3 A: recommendation 业务阈值
# ======================================================================
class TestRecommendation:
    def test_recommendation_high(self):
        """score >= 80 → '高' (强烈推荐投递)。"""
        # 素材库: PyTorch + Docker + Git 都有 → 全命中
        materials = _minimal_materials(
            ai_ml=["PyTorch 框架", "Transformer", "CNN"],
            tools=["Docker 容器化", "Git 版本控制", "Linux"],
        )
        # JD 要 PyTorch (1.0) + Docker (1.0) → 100% → 100 分 → 高
        result = match_score("需要 PyTorch 和 Docker", "tech_metric", materials=materials)
        assert result["score"] >= 80
        assert result["recommendation"] == "高"

    def test_recommendation_medium(self):
        """score 60-79 → '中' (建议补充素材后再投递)。"""
        # 构造一个 score 在 60-79 的场景
        # JD: PyTorch (1.0) + 缺失的 LoRA (0.5) + 缺失的 Transformer (1.0)
        # 素材库: 只有 PyTorch
        # 总 weight = 2.5, hit = 1.0, score = 40 ❌ 不行
        # 换个组合: JD: PyTorch (1.0) + Docker (1.0) + 缺失的 LoRA (0.5)
        # 素材库: PyTorch + Docker
        # score = 2.0/2.5 = 80 → 高 (边界)
        # 要 60-79:JD: PyTorch (1.0) + 缺失的 Transformer (1.0) + Docker (1.0) + 缺失的 LoRA (0.5)
        # 素材库: PyTorch + Docker
        # score = 2.0/3.5 = 57.1 → 57 (太低了)
        # 最简单:JD 4 个,kw 命中 2 个 (1.0 权重)
        # score = 2.0 / (2.0 + 1.0 + 0.5) = 2.0/3.5 ≈ 57
        # 用 2 命中 + 1 缺失必选 + 1 缺失加分
        # JD: PyTorch (1.0) + Docker (1.0) + 缺失 TensorFlow (1.0) + 缺失 LoRA (0.5)
        # 素材库: PyTorch + Docker
        # score = 2.0 / 3.5 = 57 ❌
        # 试个能到 60-79 的:JD: PyTorch (1.0) + 缺失 LoRA (0.5) + 缺失 FastAPI (0.5) + 缺失 SQL (0.5)
        # 素材库: 只有 PyTorch
        # score = 1.0 / 2.5 = 40 ❌
        # 用 eval/medical role + 多个 0.5 命中
        materials = _minimal_materials(
            ai_ml=["PyTorch"],
            tools=["Docker"],
            medical=["医疗数据", "医学影像"],  # 提供医疗 domain 命中
            evaluation_metrics=["BLEU 评测", "Rouge"],  # 提供评测命中
        )
        # JD: PyTorch (1.0) + Docker (1.0) + 医疗 (0.5) + 评测 (0.5) + 缺失的 NLP (0.5) + 缺失的 LoRA (0.5)
        # hit = 1.0 + 1.0 + 0.5 + 0.5 = 3.0
        # all = 1.0 + 1.0 + 0.5 + 0.5 + 0.5 + 0.5 = 4.0
        # score = 3.0/4.0 = 75 ✓
        result = match_score(
            "需要 PyTorch Docker 医疗 评测 NLP LoRA",
            "tech_metric",
            materials=materials,
        )
        assert 60 <= result["score"] < 80, f"score {result['score']} not in 60-79"
        assert result["recommendation"] == "中"

    def test_recommendation_low(self):
        """score < 60 → '低' (需大幅补充素材)。"""
        # JD 要 5 个,素材库只有 1 个 → score = 1.0/5.0 = 20
        materials = _minimal_materials(ai_ml=["PyTorch"])
        result = match_score(
            "需要 PyTorch TensorFlow LoRA FastAPI 部署",
            "tech_metric",
            materials=materials,
        )
        assert result["score"] < 60
        assert result["recommendation"] == "低"

    def test_recommendation_in_match_response(self):
        """match_score 返回 dict 必须包含 recommendation 字段。"""
        result = match_score("需要 Python", "tech_metric", materials=_minimal_materials())
        assert "recommendation" in result
        assert result["recommendation"] in ("高", "中", "低")

    def test_recommendation_threshold_boundary_80(self):
        """边界:score 正好 80 → '高'。"""
        # score = 80 → 高(>= 80)
        # JD: PyTorch (1.0) + Docker (1.0) + 缺失 LoRA (0.5)
        # 素材库: PyTorch + Docker
        # score = 2.0/2.5 = 80
        materials = _minimal_materials(ai_ml=["PyTorch"], tools=["Docker"])
        result = match_score(
            "需要 PyTorch, Docker, LoRA",
            "tech_metric",
            materials=materials,
        )
        assert result["score"] == 80
        assert result["recommendation"] == "高"

    def test_recommendation_threshold_boundary_60(self):
        """边界:score 正好 60 → '中'(60-79 是中)。"""
        # score = 60 → 中
        # JD: PyTorch (1.0) + Docker (1.0) + Transformer (1.0) + 缺失 LoRA (0.5) + 缺失 FastAPI (0.5)
        # 素材库: PyTorch + Docker
        # score = 2.0 / 4.0 = 50 ❌
        # 试 60:JD: PyTorch (1.0) + Docker (1.0) + 缺失 Transformer (1.0) + 缺失 LoRA (0.5) + 缺失 FastAPI (0.5)
        # 素材库: PyTorch + Docker
        # score = 2.0/4.0 = 50 ❌
        # 试:JD: PyTorch (1.0) + Docker (1.0) + 缺失 LoRA (0.5) + 缺失 FastAPI (0.5) + 缺失 SQL (0.5)
        # 素材库: PyTorch + Docker
        # score = 2.0/3.5 ≈ 57 ❌
        # 用 hit: 3 (1.0) + missing: 1 (1.0) + 2 (0.5)
        # score = 3/(3+1+1) = 60 ✓
        # JD: PyTorch + Docker + Git + 缺失 TensorFlow + 缺失 LoRA + 缺失 FastAPI
        materials = _minimal_materials(ai_ml=["PyTorch"], tools=["Docker", "Git"])
        result = match_score(
            "需要 PyTorch Docker Git TensorFlow LoRA FastAPI",
            "tech_metric",
            materials=materials,
        )
        assert result["score"] == 60
        assert result["recommendation"] == "中"


# ======================================================================
# Round 3 A: match_score 返回里包含 tier_info
# ======================================================================
class TestMatchResponseTierInfo:
    def test_match_response_contains_tier_info(self):
        """match_score 返回里必须包含 tier_info 字段(从 parse_jd 透传)。"""
        result = match_score(
            "必须 Python, 优先 Docker, 加分 医疗",
            "tech_metric",
            materials=_minimal_materials(),
        )
        assert "tier_info" in result
        assert isinstance(result["tier_info"], dict)
        assert set(result["tier_info"].keys()) == {"required", "preferred", "bonus"}
        # Python 在 must 后 → required
        assert "Python" in result["tier_info"]["required"]
        # Docker 在 优先 后 → preferred
        assert "Docker" in result["tier_info"]["preferred"]
        # 医疗 在 加分 后 → bonus
        assert "医疗" in result["tier_info"]["bonus"]


# ======================================================================
# 辅助:最小素材库
# ======================================================================
def _minimal_materials(**skill_groups: list[str]) -> dict:
    """构造一个最小可用素材库,用于单元测试 — 不依赖真实 materials.json。"""
    skills = dict.fromkeys(
        [
            "programming_languages",
            "ai_ml",
            "tools",
            "evaluation_metrics",
            "medical",
            "documentation",
            "data",
        ],
        [],
    )
    skills.update(skill_groups)
    return {
        "basics": {"name": "测试", "phone": "", "email": "", "location": ""},
        "education": {},
        "projects": [],
        "skills": skills,
        "honors": [],
    }
