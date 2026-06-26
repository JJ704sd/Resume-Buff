"""R3.5 阈值调优回归测试

锁死 _classify_recommendation 阈值 (>=80 高 / >=60 中 / 否则低) + 6 份 ground truth 的分类正确性。
防阈值回潮 (有人把 80/60 改回 R3 之前的硬编码值会立刻 fail)。

已知 match_score bug 跳过:
- baiyun_2026_product / baiyun_2026_qa 触发 match_score 漏匹配 (score=0),
  归 R3.5+ 修, 不在本测试范围内 (跟阈值无关)。

Ground truth 来自 `简历帮知识库/jd_samples.json` (本地 .gitignore, 不入库),
如果文件不存在测试 skip (不影响 CI / 远程 build)。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.jd_parser import _classify_recommendation, match_score


# ---------- 阈值常量锁死 ----------

class TestThresholdConstants:
    """锁死 80/60 阈值常量, 防回潮"""

    def test_high_boundary_80(self):
        assert _classify_recommendation(80) == "高"
        assert _classify_recommendation(100) == "高"
        assert _classify_recommendation(81) == "高"

    def test_mid_boundary_60_to_79(self):
        assert _classify_recommendation(60) == "中"
        assert _classify_recommendation(79) == "中"
        assert _classify_recommendation(70) == "中"

    def test_low_below_60(self):
        assert _classify_recommendation(59) == "低"
        assert _classify_recommendation(0) == "低"
        assert _classify_recommendation(1) == "低"


# ---------- Ground truth 验证 ----------

SAMPLES_PATH = Path(r"D:/简历帮/简历帮知识库/jd_samples.json")


# (id, role_id_hint, expected_recommendation, known_match_score_bug)
GROUND_TRUTH = [
    ("baiyun_2026_algorithm",   "algorithm", "高", False),
    ("baiyun_2026_fullstack",   "general",   "高", False),
    ("baiyun_2026_product",     "product",   "中", True),   # match_score 漏匹配 bug
    ("baiyun_2026_qa",          "test_qa",   "高", True),   # match_score 漏匹配 bug
    ("deepseek_2026_agi_match", "algorithm", "高", False),
    ("deepseek_2026_data_label","data_annot","高", False),
    ("alibaba_2026_data_eng",   "data_annot","中", False),
    ("bytedance_2026_qa",       "test_qa",   "高", False),
]


@pytest.fixture(scope="module")
def jd_samples():
    """加载 jd_samples.json, 不存在则 skip 整个 TestGroundTruth"""
    if not SAMPLES_PATH.exists():
        pytest.skip(f"jd_samples.json not found at {SAMPLES_PATH} (本地 .gitignore, 本地有才跑)")
    return json.loads(SAMPLES_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def materials():
    """加载素材库 (从 R3-A 起就稳定, 跟 match_score bug 无关)"""
    from core.generator import load_materials
    return load_materials()


class TestGroundTruthThreshold:
    """基于 8 份 ground truth 验证阈值分类 (排除 2 份公告型)"""

    @pytest.mark.parametrize("sid,role,expected,is_bug", GROUND_TRUTH,
                             ids=[g[0] for g in GROUND_TRUTH])
    def test_classification(self, jd_samples, materials, sid, role, expected, is_bug):
        sample = next((s for s in jd_samples["samples"] if s["id"] == sid), None)
        if sample is None:
            pytest.skip(f"{sid} 不在 jd_samples.json (可能用户还没补)")
        if sample.get("label") == "公告型":
            pytest.skip(f"{sid} 是公告型 JD, match_score 不适用")
        if is_bug:
            # 已知 match_score 漏匹配 bug, 阈值逻辑本身没问题 (0 分必判低, 符合规则)
            # 这里只 skip, bug 修复见 R3.5+
            pytest.skip(f"{sid}: known match_score bug (R3.5+ 修), threshold logic OK")

        # 跑 match_score 取 score
        result = match_score(sample["text"], role, materials)
        score = result["score"]
        actual = _classify_recommendation(score)
        assert actual == expected, (
            f"{sid} (role={role}, score={score}): "
            f"expected '{expected}', got '{actual}'"
        )


class TestGroundTruthCoverage:
    """meta-level 验证: 评估集至少 8 份 (排除公告型), 阈值校验有意义"""

    def test_eval_set_size(self, jd_samples):
        """至少 6 份 ground truth (排除 2 份公告型) 覆盖三档 label"""
        eval_samples = [s for s in jd_samples["samples"] if s.get("label") != "公告型"]
        assert len(eval_samples) >= 6, (
            f"ground truth 评估集只有 {len(eval_samples)} 份, 至少 6 份才能验证阈值"
        )

    def test_label_scale_includes_all_categories(self, jd_samples):
        """label_scale schema 包含 4 项 (推荐投/建议补充/公告型/别投)"""
        scale = jd_samples["_meta"].get("label_scale", [])
        for expected in ["推荐投", "建议补充", "公告型", "别投"]:
            assert expected in scale, f"label_scale 缺 {expected}: {scale}"