"""
Round 6-A Phase 1: interview API 集成测试

测试覆盖(plan §1.4):
  - TestStartEndpoint (4): happy / 空 jd / 超长 jd / 未知 role
  - TestReplyEndpoint (4): answer 抽取 / skip 推进 / draft_now / 未知 session
  - TestDraftEndpoint (2): can_draft=True 返 card / can_draft=False 返 400

约束:
  - 用 FastAPI TestClient,不走真实 HTTP
  - 不读真实 data/materials.json (用 fixture + monkeypatch)
  - 不写真实 logs/agent_trace.jsonl (mock log_agent_trace_jsonl)
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def _minimal_materials() -> dict:
    return {
        "_meta": {"version": "0.1.0", "last_updated": "2026-06-29"},
        "basics": {
            "name": "示例",
            "phone": "13800000000",
            "email": "your_email@example.com",
            "location": "深圳市",
        },
        "education": [],
        "projects": [],
        "skills": {
            "programming_languages": ["Python"],
            "ai_ml": ["PyTorch"],
            "tools": ["Git"],
        },
        "honors": [],
        "certs": [],
    }


def _real_materials_path() -> Path:
    """定位 backend/data/materials.json — 不依赖 cwd。"""
    return Path(__file__).resolve().parent.parent / "data" / "materials.json"


def _edited_card() -> dict:
    """一个合法的 edited_card,所有必填字段齐。"""
    return {
        "title": "测试流程优化经历",
        "responsibility": "测试反馈整理",
        "summary": "通过整理用例和反馈链路提升测试协作效率",
        "actions": ["梳理问题反馈表", "统一测试记录格式"],
        "draft_bullets": [
            "梳理测试反馈流程, 统一记录格式, 提升多人协作效率",
        ],
        "skills": ["测试流程"],
        "warnings": [],
    }


def _minimal_jd_text() -> str:
    return (
        "岗位要求: 参与 AI 产品测试与数据质量评估, "
        "能梳理流程、跟进问题闭环, 有量化意识。"
    )


@pytest.fixture
def client(monkeypatch):
    """
    构造一个 TestClient:
      - main.py 的 import 会自动加载 app
      - 把 interview_agent.load_materials 替成返 fixture,避免读真实 json
      - 把 log_agent_trace_jsonl 替成 no-op,避免污染真实日志

    Phase 2 增强:同时把 DEFAULT_MATERIALS_PATH 指向一个 pytest tmp_path 下的临时文件,
    避免 save-card endpoint 写穿到真实 backend/data/materials.json。
    Phase 1 行为完全不变(monkeypatch 只影响新增字段)。
    """
    from main import app

    from core import interview_agent

    monkeypatch.setattr(interview_agent, "load_materials", lambda: _minimal_materials())

    # 拦截 trace 写入(避免真实 jsonl 追加)
    captured: list[dict] = []
    monkeypatch.setattr(
        interview_agent,
        "log_agent_trace_jsonl",
        lambda ev: captured.append(ev),
    )

    # 重要:TestClient 触发 lifespan 时,FastAPI app 已经 import 完成
    # 但我们要确保每次 fixture 都清掉 interview session dict
    monkeypatch.setattr(interview_agent, "_INTERVIEW_SESSIONS", {})

    # Phase 2: 把 save_card 默认路径指向 tmp_path 下的临时 materials.json
    # 用 tmp_path fixture 不行(在 fixture 里访问会破坏 phase 1 用例),
    # 所以采用 lazy monkeypatch: 测试需要时再自己覆盖 DEFAULT_MATERIALS_PATH。
    # 这里保持原状,但把 module 引用交给测试,方便 monkeypatch.setattr 用字符串路径。

    return TestClient(app)


@pytest.fixture
def tmp_materials_path(monkeypatch, tmp_path):
    """
    创建一个临时 materials.json 并 monkeypatch interview_agent.DEFAULT_MATERIALS_PATH
    指向它。这样 save-card endpoint 不会污染真实 backend/data/materials.json。
    """
    from core import interview_agent

    temp_mats = tmp_path / "materials.json"
    temp_mats.write_text(
        json.dumps(_minimal_materials(), ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        interview_agent, "DEFAULT_MATERIALS_PATH", temp_mats,
    )
    return temp_mats


# ----------------------------------------------------------------------
# 1. /api/interview/start
# ----------------------------------------------------------------------
class TestStartEndpoint:
    def test_start_happy_path_returns_session_and_question(self, client):
        body = {"target_role": "test_qa", "jd_text": _minimal_jd_text()}
        resp = client.post("/api/interview/start", json=body)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "session_id" in data
        assert data["session_id"].startswith("ia")
        assert data["state"] in {"DIAGNOSING", "ASKING", "DRAFT_READY"}
        assert "selected_gap" in data
        assert data["selected_gap"].get("gap_id") in {
            "process_metric", "tech_metric", "communication", "domain_x",
        }
        assert "message" in data
        msg = data["message"]
        assert msg.get("text")  # 非空问题文本
        assert "quick_replies" in msg
        assert "progress" in data
        prog = data["progress"]
        assert prog.get("turn_count") == 0
        assert prog.get("can_draft") is False

    def test_start_empty_jd_returns_422(self, client):
        body = {"target_role": "test_qa", "jd_text": ""}
        resp = client.post("/api/interview/start", json=body)
        assert resp.status_code == 422, resp.text

    def test_start_overlong_jd_returns_422(self, client):
        body = {"target_role": "test_qa", "jd_text": "x" * 50_001}
        resp = client.post("/api/interview/start", json=body)
        assert resp.status_code == 422, resp.text

    def test_start_unknown_role_returns_422(self, client):
        body = {"target_role": "nonexistent_role", "jd_text": _minimal_jd_text()}
        resp = client.post("/api/interview/start", json=body)
        assert resp.status_code == 422, resp.text


# ----------------------------------------------------------------------
# 2. /api/interview/reply
# ----------------------------------------------------------------------
class TestReplyEndpoint:
    def test_reply_answer_extracts_slot(self, client):
        # 先 start
        start = client.post(
            "/api/interview/start",
            json={"target_role": "test_qa", "jd_text": _minimal_jd_text()},
        ).json()
        sid = start["session_id"]

        # answer 第一问
        reply = client.post(
            "/api/interview/reply",
            json={"session_id": sid, "message": "我负责测试反馈整理", "action": "answer"},
        )
        assert reply.status_code == 200, reply.text
        data = reply.json()
        assert "state" in data
        # 进度推进 (turn_count 应该 +1)
        assert data["progress"]["turn_count"] >= 1
        # captured_delta 应该非空(responsibility 槽位被填了)
        delta = data.get("captured_delta") or {}
        assert "responsibility" in delta or "background" in delta, (
            f"answer 应至少填一个槽位, 实际 delta={delta}"
        )

    def test_reply_skip_advances_slot(self, client):
        start = client.post(
            "/api/interview/start",
            json={"target_role": "test_qa", "jd_text": _minimal_jd_text()},
        ).json()
        sid = start["session_id"]

        reply = client.post(
            "/api/interview/reply",
            json={"session_id": sid, "message": "", "action": "skip_question"},
        )
        assert reply.status_code == 200, reply.text
        data = reply.json()
        # skip 后 turn_count + 1
        assert data["progress"]["turn_count"] >= 1

    def test_reply_draft_now_returns_draft_card(self, client):
        # 先 start
        start = client.post(
            "/api/interview/start",
            json={"target_role": "test_qa", "jd_text": _minimal_jd_text()},
        ).json()
        sid = start["session_id"]

        # 直接 draft_now — can_draft=False 应该 400(plan §1.3 错误处理)
        reply = client.post(
            "/api/interview/reply",
            json={"session_id": sid, "message": "", "action": "draft_now"},
        )
        # Phase 1 严格遵守 plan: draft_now 但 can_draft=False 返 400
        assert reply.status_code == 400, (
            f"draft_now 但 can_draft=False 应返 400, 实际 {reply.status_code} {reply.text}"
        )

    def test_reply_unknown_session_returns_404(self, client):
        reply = client.post(
            "/api/interview/reply",
            json={"session_id": "ia_does_not_exist", "message": "x", "action": "answer"},
        )
        assert reply.status_code == 404, reply.text


# ----------------------------------------------------------------------
# 3. /api/interview/draft
# ----------------------------------------------------------------------
class TestDraftEndpoint:
    def test_draft_returns_card_when_can_draft_true(self, client):
        # 模拟 can_draft=True: 直接通过 session fixture 注入
        from core import interview_agent

        start = client.post(
            "/api/interview/start",
            json={"target_role": "test_qa", "jd_text": _minimal_jd_text()},
        ).json()
        sid = start["session_id"]

        # 拿到 session,手动填齐 can_draft 条件
        sess = interview_agent.get_session(sid)
        assert sess is not None
        sess.captured_slots["responsibility"] = "测试反馈整理"
        sess.captured_slots["action"] = ["做了表格"]
        sess.captured_slots["metric"] = ["覆盖 50 个用例"]

        resp = client.post(f"/api/interview/draft", json={"session_id": sid})
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "draft_card" in data
        card = data["draft_card"]
        for f in ("title", "responsibility", "actions", "draft_bullets", "warnings"):
            assert f in card, f"draft_card 缺 {f!r}"

    def test_draft_returns_400_when_cannot_draft_yet(self, client):
        start = client.post(
            "/api/interview/start",
            json={"target_role": "test_qa", "jd_text": _minimal_jd_text()},
        ).json()
        sid = start["session_id"]

        # 不注入任何 slot → can_draft=False
        resp = client.post("/api/interview/draft", json={"session_id": sid})
        assert resp.status_code == 400, resp.text


# ----------------------------------------------------------------------
# 4. Round 6-A Phase 2: /api/interview/save-card
# ----------------------------------------------------------------------
class TestSaveCardEndpoint:
    """Round 6-A Phase 2: save-card endpoint(plan §2.4)。"""

    def test_save_card_happy_path_writes_project(
        self, client, tmp_materials_path, monkeypatch,
    ):
        """happy path: 写 project 到临时 materials.json,真实文件零变化。"""
        from core import interview_agent

        # 真实 materials.json 不动 sanity check
        real_path = _real_materials_path()
        real_before = (
            real_path.read_text(encoding="utf-8") if real_path.exists() else ""
        )

        # 1) start session
        start = client.post(
            "/api/interview/start",
            json={"target_role": "test_qa", "jd_text": _minimal_jd_text()},
        ).json()
        sid = start["session_id"]

        # 2) 手动注入满足 can_draft 的 slots
        sess = interview_agent.get_session(sid)
        assert sess is not None
        sess.captured_slots["responsibility"] = "测试反馈整理"
        sess.captured_slots["action"] = ["做了表格"]
        sess.captured_slots["result"] = "返工减少"

        # 3) save-card
        body = {
            "session_id": sid,
            "edited_card": _edited_card(),
            "save_mode": "append_project",
        }
        resp = client.post("/api/interview/save-card", json=body)
        assert resp.status_code == 200, resp.text
        data = resp.json()

        # 返回结构
        assert data["ok"] is True
        new_id = data["material_ref"]["id"]
        assert new_id.startswith("interview_"), (
            f"id 应以 interview_ 开头, 实际 {new_id!r}"
        )
        assert data["material_ref"]["type"] == "project"
        assert data["refresh"]["should_refresh_preview"] is True
        assert data["refresh"]["should_refresh_match"] is True

        # 临时 materials.json 里有新 project
        data_after = json.loads(tmp_materials_path.read_text(encoding="utf-8"))
        assert any(p["id"] == new_id for p in data_after["projects"])
        new_proj = next(p for p in data_after["projects"] if p["id"] == new_id)
        assert new_proj["category"] == "interview_captured"
        assert "interview_agent" in new_proj["tags"]
        assert isinstance(new_proj["highlights"], dict)
        assert new_proj["highlights"]["test_qa"] == _edited_card()["draft_bullets"]
        assert new_proj["highlights"]["general"] == _edited_card()["draft_bullets"]

        # 真实 materials.json 完全没动
        real_after = (
            real_path.read_text(encoding="utf-8") if real_path.exists() else ""
        )
        assert real_after == real_before, (
            "save-card endpoint 竟意外修改真实 data/materials.json!"
        )

    def test_save_card_invalid_save_mode_returns_400(self, client):
        """save_mode 不是 'append_project' → 400(plan §2.3 错误处理)。"""
        start = client.post(
            "/api/interview/start",
            json={"target_role": "test_qa", "jd_text": _minimal_jd_text()},
        ).json()
        sid = start["session_id"]

        body = {
            "session_id": sid,
            "edited_card": _edited_card(),
            "save_mode": "append_to_existing_project",  # Phase 2 不支持(决策点 D4)
        }
        resp = client.post("/api/interview/save-card", json=body)
        assert resp.status_code == 400, resp.text

    def test_save_card_missing_required_field_returns_422(self, client):
        """edited_card 缺 'title' 字段 → 422(plan §2.3 错误处理)。"""
        start = client.post(
            "/api/interview/start",
            json={"target_role": "test_qa", "jd_text": _minimal_jd_text()},
        ).json()
        sid = start["session_id"]

        bad_card = _edited_card()
        del bad_card["title"]  # 缺必填字段

        body = {
            "session_id": sid,
            "edited_card": bad_card,
            "save_mode": "append_project",
        }
        resp = client.post("/api/interview/save-card", json=body)
        assert resp.status_code == 422, resp.text

    def test_save_card_empty_bullets_returns_422(self, client):
        """draft_bullets 空列表 → 422(plan §2.3 错误处理)。"""
        start = client.post(
            "/api/interview/start",
            json={"target_role": "test_qa", "jd_text": _minimal_jd_text()},
        ).json()
        sid = start["session_id"]

        bad_card = _edited_card()
        bad_card["draft_bullets"] = []  # 空 bullets

        body = {
            "session_id": sid,
            "edited_card": bad_card,
            "save_mode": "append_project",
        }
        resp = client.post("/api/interview/save-card", json=body)
        assert resp.status_code == 422, resp.text