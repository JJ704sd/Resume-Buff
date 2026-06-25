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

运行:
  cd D:\\r2-jd\\backend
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
        """score 必须是整数,且在 [0, 100] 区间。"""
        # 素材库里有 PyTorch + Docker (命中);LoRA 没有 (缺失) → 部分命中
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
        # 命中 2/3 → ~67
        assert 60 <= result["score"] <= 70

    def test_coverage_calculated_per_dimension(self):
        """coverage 必须按 skills/tools/domains 三个维度独立计算。"""
        materials = _minimal_materials(
            ai_ml=["PyTorch"],     # pool: PyTorch
            tools=["Docker"],      # pool: Docker
        )
        # JD: skills 里 2 个 (PyTorch, LoRA) → 命中 1 / 2 = 0.5
        #     tools 里 1 个 (Docker) → 命中 1 / 1 = 1.0
        #     domains 里 0 个 → 视为 1.0
        text = "PyTorch / LoRA,使用 Docker"
        result = match_score(text, "tech_metric", materials=materials)
        assert result["coverage"]["skills"] == 0.5
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
