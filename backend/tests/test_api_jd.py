"""
api/jd.py 集成测试 — Round 3 A
用 TestClient (FastAPI) 测端点是否暴露新字段 (tier_info + recommendation)。

不测 thin wrapper / URL 字符串,只测:
  - /api/jd/match 返回里必须包含 recommendation 字段
  - /api/jd/match 返回里必须包含 tier_info 字段
  - /api/jd/match 真实跑出来的 score/recommendation 关系 (高/中/低)

运行:
  cd D:\\r3-jd-upgrade\\backend
  D:\\python3.11\\python.exe -m pytest tests/test_api_jd.py -v
"""
import pytest
from fastapi.testclient import TestClient

from main import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


class TestMatchResponseNewFields:
    def test_recommendation_in_match_response(self, client: TestClient):
        """/api/jd/match 返回里必须包含 recommendation 字段(高/中/低)。"""
        resp = client.post(
            "/api/jd/match",
            json={"text": "需要 Python 和 PyTorch 经验", "target_role": "tech_metric"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "recommendation" in data
        assert data["recommendation"] in ("高", "中", "低")

    def test_tier_info_in_match_response(self, client: TestClient):
        """/api/jd/match 返回里必须包含 tier_info 字段(从 parse_jd 透传)。"""
        resp = client.post(
            "/api/jd/match",
            json={
                "text": "必须 Python, 优先 Docker, 加分 医疗",
                "target_role": "tech_metric",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "tier_info" in data
        tier = data["tier_info"]
        assert set(tier.keys()) == {"required", "preferred", "bonus"}
        # Python 在 must 后 → required
        assert "Python" in tier["required"]
        # Docker 在 优先 后 → preferred
        assert "Docker" in tier["preferred"]
        # 医疗 在 加分 后 → bonus
        assert "医疗" in tier["bonus"]

    def test_recommendation_matches_score_threshold(self, client: TestClient):
        """/api/jd/match 端到端跑出来,recommendation 必须跟 score 阈值一致。"""
        # 用一个几乎全命中的 JD → 应该高
        resp = client.post(
            "/api/jd/match",
            json={
                "text": "需要 Python PyTorch 经验",
                "target_role": "tech_metric",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        score = data["score"]
        rec = data["recommendation"]
        if score >= 80:
            assert rec == "高"
        elif score >= 60:
            assert rec == "中"
        else:
            assert rec == "低"
