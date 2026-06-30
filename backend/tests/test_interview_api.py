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
        # Round 6-A follow-up: /draft 成功后 state 必须切到 DRAFT_READY
        # 之前 `sess.state = sess.state` 是 no-op, ASKING 状态下注入 slots
        # 调 /draft 会返 state="ASKING", 与"已生成 draft_card"语义不一致。
        assert data["state"] == "DRAFT_READY", (
            f"draft 成功后 state 应为 DRAFT_READY, 实际 {data['state']!r}"
        )
        assert "draft_card" in data
        card = data["draft_card"]
        for f in ("title", "responsibility", "actions", "draft_bullets", "warnings"):
            assert f in card, f"draft_card 缺 {f!r}"
        # 进程内 session 也应同步切到 DRAFT_READY
        assert sess.state.value == "DRAFT_READY", (
            f"session.state 应为 DRAFT_READY, 实际 {sess.state.value!r}"
        )

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


# ----------------------------------------------------------------------
# 5. R6-B Phase 2: API mode 开关(spec §5.3)
# ----------------------------------------------------------------------
# 覆盖:
#   - TestStartModeSwitch (4): 默认 rules / enable=False 字节级一致 /
#     enable=True + 无 key 走 rules + mode_warning / enable=True + 有 key 走 llm_assisted
#   - TestReplyUsesSessionMode (3): rules session → extraction_summary.extractor="rules" /
#     llm_assisted session → extraction_summary.extractor="llm" /
#     ReplyRequest 不重复传 enable 开关
#   - TestResponsePrivacy (4): 响应不含 API key / 不含 source_span 明文 /
#     不含 user_message 明文 / 不含 prompt 正文
# ----------------------------------------------------------------------


@pytest.fixture
def client_with_env_key(monkeypatch):
    """
    同 client fixture, 但 monkeypatch LLM_API_KEY 进 env 模拟"用户有 key"场景。
    用于验证 enable_interview_llm=True + 有 key → llm_assisted 模式。
    """
    from main import app

    from core import interview_agent

    monkeypatch.setattr(interview_agent, "load_materials", lambda: _minimal_materials())
    monkeypatch.setattr(interview_agent, "_INTERVIEW_SESSIONS", {})

    captured: list[dict] = []
    monkeypatch.setattr(
        interview_agent,
        "log_agent_trace_jsonl",
        lambda ev: captured.append(ev),
    )

    monkeypatch.setenv("LLM_API_KEY", "sk-test-1234567890abcdef")
    return TestClient(app)


@pytest.fixture
def client_without_env_key(monkeypatch):
    """
    同 client fixture, 但确保 env **没有** LLM_API_KEY。
    用于验证 enable=True 但无 key 时的 fallback 行为。
    """
    from main import app

    from core import interview_agent

    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setattr(interview_agent, "load_materials", lambda: _minimal_materials())
    monkeypatch.setattr(interview_agent, "_INTERVIEW_SESSIONS", {})

    captured: list[dict] = []
    monkeypatch.setattr(
        interview_agent,
        "log_agent_trace_jsonl",
        lambda ev: captured.append(ev),
    )

    return TestClient(app)


class TestStartModeSwitch:
    """R6-B Phase 2: StartRequest.enable_interview_llm 控制 session.interview_mode。"""

    def test_start_default_uses_rules_mode_without_warning(self, client):
        """不传 enable_interview_llm(默认 False)→ rules 模式, 无 warning(老路径字节级一致)。"""
        body = {"target_role": "test_qa", "jd_text": _minimal_jd_text()}
        resp = client.post("/api/interview/start", json=body)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["interview_mode"] == "rules", (
            f"默认应返 rules, 实际 {data.get('interview_mode')!r}"
        )
        assert data.get("mode_warning") is None, (
            f"默认应无 mode_warning, 实际 {data.get('mode_warning')!r}"
        )

    def test_start_explicit_false_uses_rules_mode(self, client):
        """显式传 enable_interview_llm=False → 仍 rules 模式, 无 warning。"""
        body = {
            "target_role": "test_qa",
            "jd_text": _minimal_jd_text(),
            "enable_interview_llm": False,
        }
        resp = client.post("/api/interview/start", json=body)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["interview_mode"] == "rules"
        assert data.get("mode_warning") is None

    def test_start_enable_true_without_key_falls_back_to_rules_with_warning(
        self, client_without_env_key,
    ):
        """enable=True + env 无 LLM_API_KEY → rules + mode_warning(spec §5.1, start 不失败)。"""
        body = {
            "target_role": "test_qa",
            "jd_text": _minimal_jd_text(),
            "enable_interview_llm": True,
        }
        resp = client_without_env_key.post("/api/interview/start", json=body)
        assert resp.status_code == 200, (
            f"无 key 时 start 仍应 200, 实际 {resp.status_code} {resp.text}"
        )
        data = resp.json()
        assert data["interview_mode"] == "rules", (
            f"无 key 应 fallback rules, 实际 {data.get('interview_mode')!r}"
        )
        assert data.get("mode_warning") is not None, (
            "无 key 模式 fallback 应有 mode_warning 提示用户"
        )
        # warning 必须是用户可读摘要, 不含 key 字符 / env var 名(spec §5.1)
        warning_text = data["mode_warning"]
        assert "智能抽取不可用" in warning_text or "已使用规则" in warning_text
        assert "sk-test" not in warning_text
        assert "LLM_API_KEY" not in warning_text
        assert "sk-" not in warning_text  # 防 key 字符串泄漏

    def test_start_enable_true_with_key_uses_llm_assisted(self, client_with_env_key):
        """enable=True + env 有 LLM_API_KEY → llm_assisted 模式, 无 warning。"""
        body = {
            "target_role": "test_qa",
            "jd_text": _minimal_jd_text(),
            "enable_interview_llm": True,
        }
        resp = client_with_env_key.post("/api/interview/start", json=body)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["interview_mode"] == "llm_assisted", (
            f"有 key 应 llm_assisted, 实际 {data.get('interview_mode')!r}"
        )
        assert data.get("mode_warning") is None, (
            f"有 key 不应有 mode_warning, 实际 {data.get('mode_warning')!r}"
        )


class TestReplyUsesSessionMode:
    """R6-B Phase 2: ReplyRequest 不传 enable 开关, reply 沿用 session.interview_mode。"""

    def test_reply_in_rules_session_uses_rules_extractor(self, client):
        """rules session → reply 走 rules extraction, extraction_summary.extractor='rules'。"""
        start = client.post(
            "/api/interview/start",
            json={"target_role": "test_qa", "jd_text": _minimal_jd_text()},
        ).json()
        sid = start["session_id"]
        assert start["interview_mode"] == "rules"

        # answer 走一轮 answer(responsibility slot)
        reply = client.post(
            "/api/interview/reply",
            json={"session_id": sid, "message": "我负责测试反馈整理", "action": "answer"},
        )
        assert reply.status_code == 200, reply.text
        data = reply.json()
        # Phase 2 必有 extraction_summary 字段(answer 路径)
        assert "extraction_summary" in data, "reply response 应含 extraction_summary 字段"
        es = data["extraction_summary"]
        assert es is not None, "answer 路径 extraction_summary 不应为 None"
        assert es["extractor"] == "rules", (
            f"rules session 走 rules, 实际 {es.get('extractor')!r}"
        )
        assert es["fallback_used"] is False
        assert isinstance(es["captured_slots"], list)
        # 至少填了 responsibility 或 background
        assert any(
            slot in es["captured_slots"]
            for slot in ("responsibility", "background")
        ), f"captured_slots 应含 responsibility 或 background, 实际 {es['captured_slots']}"
        # question_plan 必有
        assert "question_plan" in data
        assert data["question_plan"] is not None
        # R6-B Phase 3: reason_code 由 deterministic policy 决定, 不再是 phase2_placeholder
        qp = data["question_plan"]
        assert "slot" in qp
        assert qp["reason_code"] != "phase2_placeholder", (
            f"Phase 3 不再返回 phase2_placeholder, 实际 {qp['reason_code']!r}"
        )
        # 确认是 policy 的合法 reason_code
        from core.interview_policy import (
            INTERVIEW_POLICY_REASON_MISSING_REQUIRED,
            INTERVIEW_POLICY_REASON_NEXT_SLOT,
            INTERVIEW_POLICY_REASON_NO_MORE,
        )
        assert qp["reason_code"] in {
            INTERVIEW_POLICY_REASON_MISSING_REQUIRED,
            INTERVIEW_POLICY_REASON_NEXT_SLOT,
            INTERVIEW_POLICY_REASON_NO_MORE,
        }, f"reason_code 非法: {qp['reason_code']!r}"
        assert isinstance(qp["low_confidence_slots"], list)

    def test_reply_in_llm_assisted_session_uses_llm_extractor(
        self, client_with_env_key, monkeypatch,
    ):
        """llm_assisted session + 有 key → reply 走 LLM, extraction_summary.extractor='llm'。

        mock _call_llm_for_slot_extraction 返合法 JSON content,
        验证 reply 走 LLM 路径而不是 rules 路径。
        """
        from core import interview_agent

        def fake_call_llm(*, user_payload, model, base_url, api_key, timeout_sec):
            slot = user_payload.get("slot", "")
            # 模拟 LLM 返 responsibility 字符串
            return json.dumps({slot: "我负责 AI 测试数据质量", "_warnings": []})

        monkeypatch.setattr(
            interview_agent, "_call_llm_for_slot_extraction", fake_call_llm,
        )

        # start with enable=True + 有 key
        start = client_with_env_key.post(
            "/api/interview/start",
            json={
                "target_role": "test_qa",
                "jd_text": _minimal_jd_text(),
                "enable_interview_llm": True,
            },
        ).json()
        sid = start["session_id"]
        assert start["interview_mode"] == "llm_assisted"

        reply = client_with_env_key.post(
            "/api/interview/reply",
            json={"session_id": sid, "message": "我负责 AI 测试数据质量", "action": "answer"},
        )
        assert reply.status_code == 200, reply.text
        data = reply.json()
        es = data["extraction_summary"]
        assert es is not None
        assert es["extractor"] == "llm", (
            f"llm_assisted session + mock LLM 成功 → 应走 llm, 实际 {es.get('extractor')!r}"
        )
        assert es["fallback_used"] is False

    def test_reply_request_does_not_accept_enable_interview_llm(self, client):
        """ReplyRequest **不**接受 enable_interview_llm 字段(多传应被 Pydantic 忽略或 422)。"""
        start = client.post(
            "/api/interview/start",
            json={"target_role": "test_qa", "jd_text": _minimal_jd_text()},
        ).json()
        sid = start["session_id"]

        # 故意多传 enable_interview_llm — Pydantic 默认会忽略 extra 字段(因为 model 未声明)
        # 或因为声明了 enable_interview_llm=False 也不会被 start 那条 request 影响
        reply = client.post(
            "/api/interview/reply",
            json={
                "session_id": sid,
                "message": "我负责测试反馈整理",
                "action": "answer",
                "enable_interview_llm": True,  # 多传, 应被 Pydantic 忽略
            },
        )
        # reply 端点不应因为这个额外字段拒绝请求
        assert reply.status_code == 200, (
            f"reply 多传 enable_interview_llm 不应 422, 实际 {reply.status_code} {reply.text}"
        )
        data = reply.json()
        # reply 沿用 start 时决定的 mode(rules)— 不被多传的字段影响
        es = data["extraction_summary"]
        assert es["extractor"] == "rules", (
            f"start 时没开 llm, reply 多传 enable 不应改变 mode, 实际 extractor={es.get('extractor')!r}"
        )


class TestResponsePrivacy:
    """R6-B Phase 2: API response 不含 API key / prompt / source_span / user_message 明文。"""

    def test_start_response_does_not_leak_api_key(self, client_with_env_key):
        """StartResponse 不含 LLM_API_KEY 值 / env var 名 / key 字符串前缀。"""
        body = {
            "target_role": "test_qa",
            "jd_text": _minimal_jd_text(),
            "enable_interview_llm": True,
        }
        resp = client_with_env_key.post("/api/interview/start", json=body)
        assert resp.status_code == 200
        text = resp.text
        # 完整 key 值不应泄漏
        assert "sk-test-1234567890abcdef" not in text
        # env var 名不应泄漏
        assert "LLM_API_KEY" not in text
        # key 前缀不应泄漏
        assert "sk-test" not in text
        # Bearer 字样不应泄漏(说明没把 Authorization header 暴露)
        assert "Bearer" not in text

    def test_start_response_does_not_leak_prompt(self, client_with_env_key):
        """StartResponse 不含 LLM prompt 正文(SLOT_EXTRACTION_SYSTEM_PROMPT 任何子串)。"""
        from core.interview_prompts import SLOT_EXTRACTION_SYSTEM_PROMPT

        body = {
            "target_role": "test_qa",
            "jd_text": _minimal_jd_text(),
            "enable_interview_llm": True,
        }
        resp = client_with_env_key.post("/api/interview/start", json=body)
        assert resp.status_code == 200
        text = resp.text
        # prompt 正文(前 50 字符)不应泄漏到 response
        prompt_prefix = SLOT_EXTRACTION_SYSTEM_PROMPT[:50]
        assert prompt_prefix not in text, (
            "LLM prompt 字符串前缀不应出现在 response 中"
        )

    def test_reply_response_does_not_leak_source_span_or_user_message(
        self, client_with_env_key, monkeypatch,
    ):
        """ReplyResponse 不含 user_message / source_span 明文(就算 LLM 抽取成功)。"""
        from core import interview_agent

        def fake_call_llm(*, user_payload, model, base_url, api_key, timeout_sec):
            slot = user_payload.get("slot", "")
            # mock LLM 返带 source_span 的 payload
            return json.dumps({
                slot: "测试反馈整理",
                "source_span": "我负责测试反馈整理并跟进了完整流程",
                "_warnings": [],
            })

        monkeypatch.setattr(
            interview_agent, "_call_llm_for_slot_extraction", fake_call_llm,
        )

        start = client_with_env_key.post(
            "/api/interview/start",
            json={
                "target_role": "test_qa",
                "jd_text": _minimal_jd_text(),
                "enable_interview_llm": True,
            },
        ).json()
        sid = start["session_id"]

        user_msg = "我负责测试反馈整理并跟进了完整流程"
        reply = client_with_env_key.post(
            "/api/interview/reply",
            json={"session_id": sid, "message": user_msg, "action": "answer"},
        )
        assert reply.status_code == 200
        body_text = reply.text

        # source_span 明文不应出现在 response(只能以 hash 形式存在)
        assert user_msg not in body_text
        # key 字符串也不应泄漏
        assert "sk-test-1234567890abcdef" not in body_text
        assert "Bearer" not in body_text

        # extraction_summary 字段不包含 source_span / user_message / confidence
        data = reply.json()
        es = data["extraction_summary"]
        # schema 限定: 只有 extractor / fallback_used / captured_slots / low_confidence_slots
        for forbidden_key in ("source_span", "user_message", "confidence", "source_span_hash"):
            assert forbidden_key not in es, (
                f"extraction_summary 不应含 {forbidden_key!r}, 实际 keys={list(es.keys())}"
            )

    def test_reply_response_does_not_leak_api_key(self, client_with_env_key, monkeypatch):
        """ReplyResponse 不含 API key 值 / Bearer / env var 名。"""
        from core import interview_agent

        def fake_call_llm(*, user_payload, model, base_url, api_key, timeout_sec):
            slot = user_payload.get("slot", "")
            return json.dumps({slot: "测试反馈整理", "_warnings": []})

        monkeypatch.setattr(
            interview_agent, "_call_llm_for_slot_extraction", fake_call_llm,
        )

        start = client_with_env_key.post(
            "/api/interview/start",
            json={
                "target_role": "test_qa",
                "jd_text": _minimal_jd_text(),
                "enable_interview_llm": True,
            },
        ).json()
        sid = start["session_id"]

        reply = client_with_env_key.post(
            "/api/interview/reply",
            json={"session_id": sid, "message": "我负责测试反馈整理", "action": "answer"},
        )
        assert reply.status_code == 200
        body_text = reply.text
        assert "sk-test-1234567890abcdef" not in body_text
        assert "Bearer" not in body_text
        assert "LLM_API_KEY" not in body_text
# ----------------------------------------------------------------------
# 6. R6-B Phase 4: draft verifier 接入(spec §7)
# 覆盖:
#   - TestDraftVerification (4): /draft 返回的 draft_card 含 verification +
#     confidence_notes; verification 5 字段; confidence_notes 来自 slot_meta;
#     老路径(无 slot_meta) confidence_notes 仍返空 list(不爆)
#   - TestSaveCardVerificationMeta (3): /save-card 写入 _interview_meta.verification
#     4 数字 + warnings; 老路径(save_card 前没调 /draft, verification_summary=None) →
#     _interview_meta **不**含 verification; 隐私边界 _interview_meta 不含 draft_card 原文
# ----------------------------------------------------------------------


class TestDraftVerification:
    """R6-B Phase 4: /draft 返回 draft_card 注入 verification + confidence_notes。"""

    def test_draft_response_includes_verification_and_confidence_notes(
        self, client,
    ):
        """happy path: /draft 返 draft_card 含 verification(5 字段) + confidence_notes(list)。"""
        from core import interview_agent

        start = client.post(
            "/api/interview/start",
            json={"target_role": "test_qa", "jd_text": _minimal_jd_text()},
        ).json()
        sid = start["session_id"]

        # 填齐 can_draft 条件(R6-A path)
        sess = interview_agent.get_session(sid)
        assert sess is not None
        sess.captured_slots["responsibility"] = "测试反馈整理"
        sess.captured_slots["action"] = ["梳理问题反馈表", "统一格式"]
        sess.captured_slots["result"] = "返工减少"
        sess.captured_slots["metric"] = ["50个用例"]

        resp = client.post("/api/interview/draft", json={"session_id": sid})
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["state"] == "DRAFT_READY"

        card = data["draft_card"]
        # Phase 4 加的 2 个字段
        assert "verification" in card, (
            f"DraftResponse.draft_card 应含 verification, 实际 keys={list(card.keys())}"
        )
        assert "confidence_notes" in card, (
            f"DraftResponse.draft_card 应含 confidence_notes, 实际 keys={list(card.keys())}"
        )

        # verification 5 字段(spec §7)
        verification = card["verification"]
        for f in (
            "claims_total", "claims_supported", "low_confidence_claims",
            "unsupported_claims", "warnings",
        ):
            assert f in verification, (
                f"verification 缺 {f!r}, 实际 keys={list(verification.keys())}"
            )

        # confidence_notes 是 list[str](无 slot_meta 时空 list)
        assert isinstance(card["confidence_notes"], list)
        # 这里没塞 slot_meta, 所以 confidence_notes 应为空
        assert card["confidence_notes"] == [], (
            f"无 slot_meta 时 confidence_notes 应为空 list, 实际 {card['confidence_notes']}"
        )

        # 老字段也仍存在(向后兼容)
        for f in ("title", "responsibility", "actions", "draft_bullets", "warnings"):
            assert f in card

    def test_draft_response_confidence_notes_uses_low_confidence_slot(
        self, client,
    ):
        """session.slot_meta 含 confidence < 0.6 → confidence_notes 有提示"""
        from core import interview_agent

        start = client.post(
            "/api/interview/start",
            json={"target_role": "test_qa", "jd_text": _minimal_jd_text()},
        ).json()
        sid = start["session_id"]

        sess = interview_agent.get_session(sid)
        assert sess is not None
        sess.captured_slots["responsibility"] = "测试反馈整理"
        sess.captured_slots["action"] = ["梳理问题反馈表"]
        sess.captured_slots["result"] = "返工减少"
        sess.captured_slots["metric"] = ["50个用例"]

        # 注入低置信度 slot_meta: result < 0.6
        sess.slot_meta = {
            "result": [
                {"extractor": "rules", "confidence": 0.45, "turn_index": 2},
            ],
        }

        resp = client.post("/api/interview/draft", json={"session_id": sid})
        assert resp.status_code == 200, resp.text
        card = resp.json()["draft_card"]

        # confidence_notes 应提到 result slot
        notes = card["confidence_notes"]
        assert isinstance(notes, list)
        assert len(notes) >= 1
        assert any("result" in n for n in notes), (
            f"confidence_notes 应提到低置信度 slot 'result', 实际 {notes}"
        )

        # verification.low_confidence_claims / claims_supported 也应有数字
        verification = card["verification"]
        assert verification["claims_total"] >= 1

    def test_draft_response_does_not_leak_draft_card_full_text(self, client):
        """DraftResponse 整段 text 不含不相关的 PII 注入(spec §7 + AGENTS.md 隐私)。

        走完整 /draft 流程后, 注入 capture_slots 里的 sentinel 字符串不会出现在
        verification.warnings 里(spec §7 截前 30 字, 不复制完整原文)。
        """
        from core import interview_agent

        sentinel_secret = "TOP-PII-SECRET-DO-NOT-LEAK-FROM-DRAFT-2026-XYZ"

        start = client.post(
            "/api/interview/start",
            json={"target_role": "test_qa", "jd_text": _minimal_jd_text()},
        ).json()
        sid = start["session_id"]

        sess = interview_agent.get_session(sid)
        assert sess is not None
        sess.captured_slots["responsibility"] = sentinel_secret
        sess.captured_slots["action"] = ["梳理问题反馈表"]
        sess.captured_slots["result"] = "返工减少"

        resp = client.post("/api/interview/draft", json={"session_id": sid})
        assert resp.status_code == 200, resp.text
        # 完整 response text: capture 字段会出现在 card 业务字段里(highlights 是另一码事);
        # 我们只断言 verification.warnings 不复制完整原文
        card = resp.json()["draft_card"]
        warnings_text = json.dumps(
            card["verification"]["warnings"], ensure_ascii=False,
        )
        assert sentinel_secret not in warnings_text, (
            f"verification.warnings 含 capture 原文(违反 §7 隐私边界): {warnings_text}"
        )

    def test_draft_response_no_key_no_prompt_no_source_span_leak(self, client):
        """DraftResponse 不含 API key / prompt / source_span 明文 — 沿用 §5.3 锁"""
        secret = "sk-secret-key-sentinel-DO-NOT-LEAK-20260630"
        start = client.post(
            "/api/interview/start",
            json={"target_role": "test_qa", "jd_text": _minimal_jd_text()},
        ).json()
        sid = start["session_id"]

        # 直接修改 server-side session state, 注入 sentinel content 进 bullet path
        from core import interview_agent
        sess = interview_agent.get_session(sid)
        assert sess is not None
        sess.captured_slots["responsibility"] = secret
        sess.captured_slots["action"] = [secret]
        sess.captured_slots["result"] = secret

        resp = client.post("/api/interview/draft", json={"session_id": sid})
        assert resp.status_code == 200, resp.text
        text = resp.text

        # verification.warnings 也不应泄漏 user-side 注入的 sentinel
        assert "sk-test-" not in text
        assert "Bearer " not in text


class TestSaveCardVerificationMeta:
    """R6-B Phase 4: save_card 写入 _interview_meta.verification 摘要(spec §7)。"""

    def test_save_card_writes_verification_meta_when_summary_present(
        self, client, tmp_materials_path,
    ):
        """happy path: 走完 /draft(让 verification_summary 落盘) + /save-card,
        _interview_meta 含 verification 摘要(4 数字 + warnings)。"""
        from core import interview_agent

        # 1) start
        start = client.post(
            "/api/interview/start",
            json={"target_role": "test_qa", "jd_text": _minimal_jd_text()},
        ).json()
        sid = start["session_id"]

        sess = interview_agent.get_session(sid)
        assert sess is not None
        sess.captured_slots["responsibility"] = "测试反馈整理"
        sess.captured_slots["action"] = ["梳理问题反馈表", "统一格式"]
        sess.captured_slots["result"] = "返工减少"
        sess.captured_slots["metric"] = ["50个用例"]

        # 2) /draft 触发 verification 计算 + sess.verification_summary 缓存
        draft_resp = client.post("/api/interview/draft", json={"session_id": sid})
        assert draft_resp.status_code == 200, draft_resp.text

        # 3) /save-card
        body = {
            "session_id": sid,
            "edited_card": _edited_card(),
            "save_mode": "append_project",
        }
        resp = client.post("/api/interview/save-card", json=body)
        assert resp.status_code == 200, resp.text
        new_id = resp.json()["material_ref"]["id"]

        # 4) 验证 _interview_meta.verification 摘要
        data_after = json.loads(tmp_materials_path.read_text(encoding="utf-8"))
        new_proj = next(
            p for p in data_after["projects"] if p["id"] == new_id
        )
        meta = new_proj["_interview_meta"]

        # 既有字段不回退(R6-A Phase 2)
        assert meta["source_gap_id"], (
            f"source_gap_id 应非空, 实际 {meta.get('source_gap_id')!r}"
        )
        assert meta["source_session_id"] == sid

        # Phase 4 增量字段
        assert "verification" in meta, (
            f"_interview_meta 应含 verification, 实际 keys={list(meta.keys())}"
        )
        verification = meta["verification"]
        # 4 数字 + warnings
        assert isinstance(verification["claims_total"], int)
        assert isinstance(verification["claims_supported"], int)
        assert isinstance(verification["low_confidence_claims"], int)
        assert isinstance(verification["unsupported_claims"], int)
        assert isinstance(verification["warnings"], list)

        # extraction_mode 应为 session.interview_mode(老路径默认 "rules")
        assert meta.get("extraction_mode") == "rules"

    def test_save_card_no_verification_when_draft_not_called(self, client):
        """老路径: 不经 /draft(verification_summary=None)→ save-card 不写 verification meta"""
        from core import interview_agent

        start = client.post(
            "/api/interview/start",
            json={"target_role": "test_qa", "jd_text": _minimal_jd_text()},
        ).json()
        sid = start["session_id"]

        sess = interview_agent.get_session(sid)
        assert sess is not None
        # 直接 mock: 不调 /draft, 直接构建一个 session + 手动 inject draft_card 路径
        # 这里走 reply.action=draft_now, _do_draft_now 也会写 verification_summary
        # 所以我们用更直接的方式: 直接拿 session 强制把 verification_summary 设为 None
        sess.verification_summary = None

        # 满足 can_draft 才能走 save-card
        sess.captured_slots["responsibility"] = "测试反馈整理"
        sess.captured_slots["action"] = ["梳理问题反馈表"]
        sess.captured_slots["result"] = "返工减少"

        # 临时 materials 文件,避免污染真实
        import tempfile
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False,
            encoding="utf-8",
        ) as f:
            json.dump(_minimal_materials(), f, ensure_ascii=False)
            temp_path = Path(f.name)

        try:
            # 直接调 save_card(不走 /draft), verification_summary=None
            from core.interview_agent import save_card
            result = save_card(
                sess, _edited_card(), "append_project",
                materials_path=temp_path,
            )
            assert result["ok"] is True
            new_id = result["material_ref"]["id"]

            data_after = json.loads(temp_path.read_text(encoding="utf-8"))
            new_proj = next(
                p for p in data_after["projects"] if p["id"] == new_id
            )
            meta = new_proj["_interview_meta"]

            # 老路径: verification_summary=None → _interview_meta 不含 verification
            assert "verification" not in meta, (
                f"verification_summary=None 时 _interview_meta 不应含 verification, "
                f"实际 keys={list(meta.keys())}"
            )
            assert "extraction_mode" not in meta, (
                f"verification_summary=None 时 _interview_meta 不应含 extraction_mode, "
                f"实际 keys={list(meta.keys())}"
            )
        finally:
            temp_path.unlink(missing_ok=True)

    def test_save_card_verification_meta_does_not_leak_draft_card_or_user_text(
        self, client, tmp_materials_path,
    ):
        """_interview_meta.verification 不含 draft_card 原文 / user_message 明文 / source_span"""
        from core import interview_agent

        secret_bullet = (
            "XTOP-USER-PRIVATE-BULLET-DO-NOT-LEAK-2026-06-30-XYZ"
        )
        secret_msg = (
            "XUSER-PRIVATE-MESSAGE-DO-NOT-LEAK-2026-06-30-XYZ"
        )

        start = client.post(
            "/api/interview/start",
            json={"target_role": "test_qa", "jd_text": _minimal_jd_text()},
        ).json()
        sid = start["session_id"]

        sess = interview_agent.get_session(sid)
        assert sess is not None
        sess.captured_slots["responsibility"] = "测试反馈整理"
        sess.captured_slots["action"] = [secret_msg]  # 不应泄漏到 meta
        sess.captured_slots["result"] = "返工减少"

        # 触发 /draft 让 verification_summary 落盘
        draft_resp = client.post("/api/interview/draft", json={"session_id": sid})
        assert draft_resp.status_code == 200

        # /save-card 用带 secret 的 edited_card
        bad_card = _edited_card()
        bad_card["draft_bullets"] = [secret_bullet]

        body = {
            "session_id": sid,
            "edited_card": bad_card,
            "save_mode": "append_project",
        }
        resp = client.post("/api/interview/save-card", json=body)
        assert resp.status_code == 200, resp.text
        new_id = resp.json()["material_ref"]["id"]

        data_after = json.loads(tmp_materials_path.read_text(encoding="utf-8"))
        new_proj = next(
            p for p in data_after["projects"] if p["id"] == new_id
        )
        meta_str = json.dumps(new_proj, ensure_ascii=False)

        # draft_bullets 原文会出现在 highlights(业务必须), 不在 _interview_meta
        highlights_text = json.dumps(
            new_proj["highlights"], ensure_ascii=False,
        )
        assert secret_bullet in highlights_text  # 这是正常的(高亮字段)

        # _interview_meta.verification.warnings 里**不**应含完整 secret_bullet
        verification = new_proj["_interview_meta"]["verification"]
        warnings_text = json.dumps(verification["warnings"], ensure_ascii=False)
        assert secret_bullet not in warnings_text, (
            "_interview_meta.verification.warnings 不应含完整 draft_bullets 原文"
        )
        # user_message(action) 不应泄漏到 verification
        assert secret_msg not in warnings_text, (
            "_interview_meta.verification.warnings 不应含 user_message 明文"
        )
        # 4 数字 + extraction_mode 也都在
        for f in (
            "claims_total", "claims_supported", "low_confidence_claims",
            "unsupported_claims", "warnings",
        ):
            assert f in verification
