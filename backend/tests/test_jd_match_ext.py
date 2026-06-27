"""
core/jd_parser match_score + external_resume_text 单元测试 — R3-G
测核心逻辑: have/need 算法 + 素材库双计避免 + 不传时为 None

不测 thin wrapper / 简单 dict.get,只测:
  - 简历里有的关键词 → have_keywords
  - 简历里没有 + 素材库也没有 → need_keywords
  - 简历里没有 + 素材库能提供 → 不算 need(避免双计)
  - 不传 external_resume_text → resume_perspective 为 None
  - 部分命中场景
  - _build_resume_perspective 边界(空 / 无 JD 关键词)

运行:
  cd D:\\r3g-resume-upload\\backend
  D:\\python3.11\\python.exe -m pytest tests/test_jd_match_ext.py -v
"""
import pytest

from core.jd_parser import match_score, _build_resume_perspective


# 复用 R3-A 的 helper(本文件独立复制,避免 tests 之间的 import 耦合)
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


# ======================================================================
# _build_resume_perspective: 单元测试
# ======================================================================
class TestBuildResumePerspective:
    def test_returns_none_when_no_external_resume(self):
        """不传 external_resume_text → None。"""
        # 素材库里有 Python + Docker
        mats = _minimal_materials(
            ai_ml=["PyTorch 深度学习框架"],
            tools=["Docker 容器化部署"],
        )
        result = match_score(
            "需要 Python 和 Docker",
            "tech_metric",
            materials=mats,
        )
        assert result["resume_perspective"] is None

    def test_returns_none_when_empty_string(self):
        """传空字符串 → None(避免空匹配)。"""
        result = match_score(
            "需要 Python",
            "tech_metric",
            materials=_minimal_materials(),
            external_resume_text="",
        )
        assert result["resume_perspective"] is None

    def test_returns_none_when_whitespace_only(self):
        """纯空白字符串 → None。"""
        result = match_score(
            "需要 Python",
            "tech_metric",
            materials=_minimal_materials(),
            external_resume_text="   \n\t  ",
        )
        assert result["resume_perspective"] is None

    def test_have_keywords_when_resume_mentions_jd_terms(self):
        """简历里出现 JD 要求的关键词 → 计入 have_keywords。"""
        mats = _minimal_materials()  # 素材库空
        result = match_score(
            "需要 Python 和 PyTorch 经验",
            "tech_metric",
            materials=mats,
            external_resume_text=(
                "我在项目中使用了 Python 脚本,\n"
                "并基于 PyTorch 训练了深度学习模型。\n"
            ),
        )
        rp = result["resume_perspective"]
        assert rp is not None
        # 简历里出现 Python + PyTorch → 都进 have
        assert "Python" in rp["have_keywords"]
        assert "PyTorch" in rp["have_keywords"]
        assert rp["have_count"] == 2
        # need_keywords 为空(都命中了)
        assert rp["need_keywords"] == []
        assert rp["need_count"] == 0

    def test_need_keywords_when_resume_missing_and_pool_missing(self):
        """简历里没 + 素材库也没 → need_keywords。"""
        mats = _minimal_materials()  # 完全空素材库
        result = match_score(
            "必须掌握 PyTorch 和 Spark,熟悉 Docker",
            "tech_metric",
            materials=mats,
            external_resume_text="我是一名学生,学习过计算机基础课程",
        )
        rp = result["resume_perspective"]
        assert rp is not None
        # 简历里完全没有 PyTorch/Spark/Docker
        assert rp["have_keywords"] == []
        # 素材库也没有 → 全部进 need
        assert set(rp["need_keywords"]) == {"PyTorch", "Docker"}
        # Spark 不在 KEYWORD_GROUPS 里 → 不计入 have/need(关键词词典范围)
        assert "Spark" not in rp["have_keywords"]
        assert "Spark" not in rp["need_keywords"]

    def test_no_double_count_when_pool_already_provides(self):
        """简历里没 + 素材库能提供 → 不进 need(避免双计)。
        这是 R3-G 的关键设计:用户既写简历,又有素材库 → 不重复算 missing。"""
        mats = _minimal_materials(
            ai_ml=["PyTorch 深度学习框架"],
        )
        result = match_score(
            "需要 PyTorch 经验",
            "tech_metric",
            materials=mats,
            external_resume_text="我是一个转行新人,无 AI 经验",
        )
        rp = result["resume_perspective"]
        assert rp is not None
        # 简历里没有 PyTorch
        assert "PyTorch" not in rp["have_keywords"]
        # 但素材库里有 → 不应该出现在 need(避免双计)
        assert "PyTorch" not in rp["need_keywords"]
        # 全部为 0
        assert rp["have_count"] == 0
        assert rp["need_count"] == 0

    def test_partial_coverage(self):
        """部分命中:有 Python 但没 PyTorch,素材库也提供 PyTorch。"""
        mats = _minimal_materials(
            ai_ml=["PyTorch 训练框架"],
        )
        # 简历里只字不提 PyTorch(连"没用过"也避免 — 表面命中)
        result = match_score(
            "需要 Python + PyTorch 经验",
            "tech_metric",
            materials=mats,
            external_resume_text="我熟练使用 Python 写后端,以及一些基础的数据分析工作",
        )
        rp = result["resume_perspective"]
        assert rp is not None
        # Python 在简历里 → have
        assert "Python" in rp["have_keywords"]
        # PyTorch 不在简历里、但素材库有 → 不在 need(避免双计)
        assert "PyTorch" not in rp["need_keywords"]
        assert "PyTorch" not in rp["have_keywords"]
        # have_count=1, need_count=0
        assert rp["have_count"] == 1
        assert rp["need_count"] == 0

    def test_synonym_normalization(self):
        """同义词归一化:'大语言模型' 应被视为 LLM 命中。"""
        mats = _minimal_materials()
        result = match_score(
            "需要 LLM 经验",
            "tech_metric",
            materials=mats,
            external_resume_text="我做过大语言模型的微调工作",
        )
        rp = result["resume_perspective"]
        assert rp is not None
        # "大语言模型" surface 归一化为 "LLM" → 命中
        assert "LLM" in rp["have_keywords"]

    def test_keywords_sorted_alphabetically(self):
        """have/need 列表应按字母序排序(展示稳定)。"""
        mats = _minimal_materials()
        result = match_score(
            "需要 Python PyTorch Transformer LLM 经验",
            "tech_metric",
            materials=mats,
            external_resume_text="",
        )
        # 不传 external_resume → None
        assert result["resume_perspective"] is None

        # 传一个命中所有关键词的简历
        result = match_score(
            "需要 Python PyTorch Transformer LLM 经验",
            "tech_metric",
            materials=mats,
            external_resume_text="Python PyTorch Transformer LLM 全部都会",
        )
        rp = result["resume_perspective"]
        assert rp is not None
        # 排序应稳定
        assert rp["have_keywords"] == sorted(rp["have_keywords"])

    def test_empty_jd_keywords_returns_empty_lists(self):
        """JD 文本里没有 KEYWORD_GROUPS 词汇 → have/need 都为空。"""
        mats = _minimal_materials()
        result = match_score(
            "招聘一个认真负责的同事",
            "tech_metric",
            materials=mats,
            external_resume_text="我是候选人,做事认真",
        )
        rp = result["resume_perspective"]
        assert rp is not None
        # 没有 JD 关键词 → 全空(不让 UI 困惑)
        assert rp["have_keywords"] == []
        assert rp["need_keywords"] == []
        assert rp["have_count"] == 0
        assert rp["need_count"] == 0

    def test_chinese_punctuation_normalized(self):
        """中文标点不影响匹配(底层 _normalize_text 会转成英文标点)。"""
        mats = _minimal_materials()
        result = match_score(
            "需要 Python,PyTorch 经验。",
            "tech_metric",
            materials=mats,
            external_resume_text="我会 Python(熟练),也用过 PyTorch;",
        )
        rp = result["resume_perspective"]
        assert rp is not None
        assert "Python" in rp["have_keywords"]
        assert "PyTorch" in rp["have_keywords"]


# ======================================================================
# match_score 端到端 + 已有字段不变
# ======================================================================
class TestMatchScoreBackwardCompat:
    def test_match_score_without_external_resume_unchanged(self):
        """不传 external_resume_text → 行为与 R3-A 完全一致(不影响老调用)。"""
        mats = _minimal_materials(ai_ml=["PyTorch 框架"])
        result = match_score(
            "需要 Python 和 PyTorch",
            "tech_metric",
            materials=mats,
        )
        # R3-A 老字段都在
        assert "score" in result
        assert "matched_keywords" in result
        assert "missing_keywords" in result
        assert "coverage" in result
        assert "suggestions" in result
        assert "role_id" in result
        assert "tier_info" in result
        assert "recommendation" in result
        # R3-G 新字段
        assert "resume_perspective" in result
        assert result["resume_perspective"] is None

    def test_match_score_with_external_resume_adds_perspective(self):
        """传 external_resume_text → 加上 resume_perspective 字段。"""
        mats = _minimal_materials()
        result = match_score(
            "需要 Python 和 Docker",
            "tech_metric",
            materials=mats,
            external_resume_text="我会用 Python 写脚本",
        )
        # 老字段都还在
        assert "score" in result
        assert "matched_keywords" in result
        # 新字段
        rp = result["resume_perspective"]
        assert rp is not None
        assert "have_keywords" in rp
        assert "need_keywords" in rp
        assert "have_count" in rp
        assert "need_count" in rp

    def test_external_resume_does_not_change_score(self):
        """传 external_resume_text 不应影响 score(只新增视角分析)。"""
        mats = _minimal_materials(ai_ml=["PyTorch 框架"])
        text = "需要 Python PyTorch 经验"
        without = match_score(text, "tech_metric", materials=mats)
        with_ = match_score(
            text, "tech_metric", materials=mats,
            external_resume_text="我会用 PyTorch 也熟悉 Python",
        )
        # score 不变(只多 resume_perspective 字段)
        assert with_["score"] == without["score"]
        assert with_["matched_keywords"] == without["matched_keywords"]
        assert with_["missing_keywords"] == without["missing_keywords"]
        # 但 resume_perspective 不同
        assert without["resume_perspective"] is None
        assert with_["resume_perspective"] is not None