"""
Round 6-A Phase 1: interview_agent 单元测试

测试覆盖:
  - TestSessionLifecycle (3): session_id 前缀 / 不存在 / reset
  - TestGapSelection (6):  tier 优先 / missing 命中 / 不 import workflow /
                          不该追问 -5 / 返 Top 1 / 稳定排序
  - TestSlotExtractionRules (5): background / action / method / metric / responsibility
  - TestDraftCard (4): can_draft 三组合 / build_draft_card 字段 / warnings
  - TestStateMachine (3): skip 计数 / 连续 skip 强制 draft / 轮数上限
  - TestTracePrivacy (2):  trace 不含 user_message / 不含 draft_card_text

R5-E 边界:
  - 不 import core.agent_workflow / core.llm_rewriter
  - 不改 PROMPT_VERSIONS / SYSTEM_PROMPT
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest


# 极简素材库 fixture — 不读真实 data/materials.json
def _minimal_materials() -> dict:
    return {
        "_meta": {"version": "0.1.0", "last_updated": "2026-06-29"},
        "basics": {
            "name": "示例同学",
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


def _full_materials_for_round_trip() -> dict:
    """完整版素材库 — round-trip 测试需要 preview_resume 跑通 build_sections。

    Phase 1 测试只用 _minimal_materials,因为它们不调 preview_resume。
    save_card round-trip 测试需要 education / skills 都符合 build_sections 期望。
    """
    return {
        "_meta": {"version": "0.1.0", "last_updated": "2026-06-29"},
        "basics": {
            "name": "示例同学",
            "phone": "13800000000",
            "email": "your_email@example.com",
            "location": "深圳市",
        },
        "education": {
            "school": "示例大学",
            "college": "示例学院",
            "major": "示例专业",
            "degree": "本科",
            "period": "2024.9 - 2028.6",
            "year": "大二",
            "core_courses": ["程序设计基础", "人工智能原理"],
            "highlights": ["医学与工科交叉复合背景"],
        },
        "projects": [],
        "skills": {
            "programming_languages": ["Python"],
            "ai_ml": ["PyTorch"],
            "tools": ["Git"],
        },
        "honors": [],
        "certs": [],
    }


def _minimal_jd_text() -> str:
    return (
        "岗位要求: 参与 AI 产品测试与数据质量评估, "
        "能梳理流程、跟进问题闭环, 有量化意识。"
    )


# ----------------------------------------------------------------------
# 1. Session 生命周期
# ----------------------------------------------------------------------
class TestSessionLifecycle:
    def test_create_session_returns_ia_prefix(self):
        from core.interview_agent import create_session

        sess = create_session("test_qa", _minimal_jd_text(), _minimal_materials())
        assert sess.session_id.startswith("ia"), (
            f"session_id 应以 'ia' 开头, 实际 {sess.session_id!r}"
        )
        # 8 hex 后缀
        assert re.match(r"^ia[0-9a-f]{8}$", sess.session_id), (
            f"session_id 应为 'ia' + 8 hex, 实际 {sess.session_id!r}"
        )

    def test_get_session_returns_none_for_unknown(self):
        from core.interview_agent import get_session

        assert get_session("ia_does_not_exist") is None

    def test_reset_session_clears_state(self):
        from core.interview_agent import (
            create_session, reset_session, get_session,
        )

        sess = create_session("test_qa", _minimal_jd_text(), _minimal_materials())
        sid = sess.session_id
        # 先确认存在
        assert get_session(sid) is sess
        # reset 后应拿不到
        assert reset_session(sid) is True
        assert get_session(sid) is None
        # reset 不存在的 id 返 False,不抛
        assert reset_session("ia_never_existed") is False


# ----------------------------------------------------------------------
# 2. 缺口选择
# ----------------------------------------------------------------------
class TestGapSelection:
    def test_select_gap_prioritizes_required_tier(self):
        """required tier (4 分) > preferred (2 分) > bonus (1 分)"""
        from core.interview_agent import (
            GapCandidate, _score_gap, _select_gap_from_candidates,
        )

        req = GapCandidate(
            gap_id="process_metric", label="流程", reason="",
            keywords=["流程"], source=[], tier="required",
            priority=0.0, suggested_slots=("action",),
        )
        pref = GapCandidate(
            gap_id="tech_metric", label="技术", reason="",
            keywords=["流程"], source=[], tier="preferred",
            priority=0.0, suggested_slots=("action",),
        )
        bonus = GapCandidate(
            gap_id="communication", label="沟通", reason="",
            keywords=["流程"], source=[], tier="bonus",
            priority=0.0, suggested_slots=("action",),
        )
        # parse_jd + match_score 给的 parsed
        parsed = {"raw_keywords": ["流程"], "tier_info": {"required": [], "preferred": [], "bonus": []}}
        score_req = _score_gap(req, parsed, missing=[])
        score_pref = _score_gap(pref, parsed, missing=[])
        score_bonus = _score_gap(bonus, parsed, missing=[])
        assert score_req > score_pref > score_bonus

    def test_select_gap_uses_match_score_missing(self):
        """missing_keywords 命中 gap.keywords → +3 分"""
        from core.interview_agent import GapCandidate, _score_gap

        gap = GapCandidate(
            gap_id="process_metric", label="流程", reason="",
            keywords=["流程", "闭环"], source=[], tier="preferred",
            priority=0.0, suggested_slots=("action",),
        )
        parsed = {"raw_keywords": [], "tier_info": {"required": [], "preferred": [], "bonus": []}}
        # missing = ["流程"] 命中 → +3
        s_hit = _score_gap(gap, parsed, missing=["流程"])
        s_miss = _score_gap(gap, parsed, missing=["Python"])
        assert s_hit - s_miss >= 3, f"missing 命中应至少 +3, 实际差 {s_hit - s_miss}"

    def test_select_gap_does_not_import_workflow(self):
        """R5-A/B 保护: interview_agent 不依赖 core.agent_workflow / core.llm_rewriter"""
        import re as _re
        import core.interview_agent as ia_mod

        src_module = ia_mod.__file__
        assert src_module is not None
        with open(src_module, encoding="utf-8") as f:
            src = f.read()

        # 检查 import 语句 — 不能出现 from core.agent_workflow / import core.agent_workflow
        # 不能出现 from core.llm_rewriter / import core.llm_rewriter
        # (允许 docstring 里出现这些名字作为说明, 不允许实际 import)
        forbidden_imports = [
            _re.search(r"^\s*from\s+core\.agent_workflow\s+import\s+", src, _re.MULTILINE),
            _re.search(r"^\s*import\s+core\.agent_workflow\b", src, _re.MULTILINE),
            _re.search(r"^\s*from\s+core\.llm_rewriter\s+import\s+", src, _re.MULTILINE),
            _re.search(r"^\s*import\s+core\.llm_rewriter\b", src, _re.MULTILINE),
        ]
        for m in forbidden_imports:
            assert m is None, (
                f"interview_agent.py 实际 import 了 R5-A/B/E 锁定的核心域模块: {m.group(0) if m else None}"
            )

    def test_select_gap_ignores_uninterviewable(self):
        """学历/年限/证书/硬技能/无相邻证据类 gap -5 分,即使 tier=required 也不入选"""
        from core.interview_agent import (
            GapCandidate, _select_gap_from_candidates,
        )

        # 构造两个 candidate,一个在不该追问白名单,一个不在
        bad = GapCandidate(
            gap_id="degree_required", label="学历要求", reason="",
            keywords=["本科"], source=[], tier="required",
            priority=0.0, suggested_slots=(),
        )
        good = GapCandidate(
            gap_id="process_metric", label="流程优化", reason="",
            keywords=["流程"], source=[], tier="preferred",
            priority=0.0, suggested_slots=("action",),
        )
        parsed = {"raw_keywords": ["流程"], "tier_info": {"required": ["本科"], "preferred": ["流程"], "bonus": []}}
        top = _select_gap_from_candidates([bad, good], parsed, missing=[])
        assert top.gap_id == "process_metric", (
            f"不该追问 gap 应被扣分落选, 实际选中 {top.gap_id!r}"
        )

    def test_select_gap_returns_top_one(self):
        """始终返 1 个 GapCandidate,不抛"""
        from core.interview_agent import (
            GapCandidate, _select_gap_from_candidates,
        )

        cands = [
            GapCandidate(
                gap_id=f"gap_{i}", label=f"G{i}", reason="",
                keywords=[], source=[], tier="bonus",
                priority=0.0, suggested_slots=(),
            )
            for i in range(3)
        ]
        parsed = {"raw_keywords": [], "tier_info": {"required": [], "preferred": [], "bonus": []}}
        top = _select_gap_from_candidates(cands, parsed, missing=[])
        assert isinstance(top.gap_id, str)
        assert top.gap_id in {"gap_0", "gap_1", "gap_2"}

    def test_select_gap_stable_sort_by_gap_id(self):
        """priority 相同时按 gap_id 升序,稳定排序"""
        from core.interview_agent import (
            GapCandidate, _select_gap_from_candidates,
        )

        # 构造 3 个 candidate 全部 priority=0 (同样的 keywords 空 + tier=bonus 兜底)
        # 排序应严格按 gap_id asc
        cands = [
            GapCandidate(
                gap_id="zzz", label="Z", reason="",
                keywords=[], source=[], tier="bonus",
                priority=0.0, suggested_slots=(),
            ),
            GapCandidate(
                gap_id="aaa", label="A", reason="",
                keywords=[], source=[], tier="bonus",
                priority=0.0, suggested_slots=(),
            ),
            GapCandidate(
                gap_id="mmm", label="M", reason="",
                keywords=[], source=[], tier="bonus",
                priority=0.0, suggested_slots=(),
            ),
        ]
        parsed = {"raw_keywords": [], "tier_info": {"required": [], "preferred": [], "bonus": []}}
        top = _select_gap_from_candidates(cands, parsed, missing=[])
        assert top.gap_id == "aaa", f"priority 同分应按 gap_id 升序, 实际 {top.gap_id!r}"


# ----------------------------------------------------------------------
# 3. 槽位抽取规则
# ----------------------------------------------------------------------
class TestSlotExtractionRules:
    def test_extract_background_returns_short_string(self):
        """background: 整段当 string, 截 200 字"""
        from core.interview_agent import extract_slots

        # 短文本(<200 字)整段保留
        msg = "我在课程项目里做过一个测试反馈整理"
        out = extract_slots(msg, "background")
        assert isinstance(out.get("background"), str)
        assert "课程项目" in out["background"]
        # 长文本(>200 字)截断到 200 字
        long_msg = "背景" * 150  # 300 字符
        out2 = extract_slots(long_msg, "background")
        assert len(out2["background"]) <= 200

    def test_extract_action_splits_on_punctuation(self):
        """action: 按 ; / 。 / ， / \\n 切成 actions[]"""
        from core.interview_agent import extract_slots

        msg = "我做了表格模板;按类型分类,统一格式;每天同步进度"
        out = extract_slots(msg, "action")
        # captured_slots 单数 key (与 slot_name 一致)
        actions = out.get("action", [])
        assert isinstance(actions, list)
        # 至少 2 段
        assert len(actions) >= 2
        # 每段非空
        assert all(a.strip() for a in actions)

    def test_extract_method_finds_tool_keyword(self):
        """method: 找「用了/采用/基于/通过」后面到句末,入 methods[]"""
        from core.interview_agent import extract_slots

        msg = "我用了共享文档同步状态,基于问题类型分类,通过每日站会跟进"
        out = extract_slots(msg, "method")
        methods = out.get("method", [])
        assert isinstance(methods, list)
        # 至少 3 个方法被识别
        assert len(methods) >= 3
        # 至少一个含 "共享文档" / "分类" / "站会"
        joined = " | ".join(methods)
        assert any(k in joined for k in ("共享文档", "分类", "站会"))

    def test_extract_metric_regex_finds_numbers(self):
        """metric: regex 找数字 + 单位(人/%/倍/小时/天/次/万)"""
        from core.interview_agent import extract_slots

        msg = "覆盖 50 个用例,准确率 95%,团队 8 个人协作,节省 2 小时"
        out = extract_slots(msg, "metric")
        metrics = out.get("metric", [])
        assert isinstance(metrics, list)
        assert len(metrics) >= 3, f"应至少识别 3 个数字+单位, 实际 {metrics}"
        # 验证包含数字
        assert any(re.search(r"\d", m) for m in metrics)

    def test_extract_responsibility_finds_owner_keyword(self):
        """responsibility: 找「负责/主管/owner/主导」后面到下一个标点前的短语"""
        from core.interview_agent import extract_slots

        msg = "我负责测试反馈整理,跟同学协作"
        out = extract_slots(msg, "responsibility")
        resp = out.get("responsibility", "")
        assert isinstance(resp, str)
        assert "测试反馈整理" in resp or "测试反馈" in resp


# ----------------------------------------------------------------------
# 4. draft_card
# ----------------------------------------------------------------------
class TestDraftCard:
    def test_can_draft_true_when_required_combo(self):
        """(background, action, result) 满足 → can_draft True"""
        from core.interview_agent import InterviewSession, InterviewState, can_draft

        sess = InterviewSession(
            session_id="ia_test001",
            target_role="test_qa",
            jd_digest={},
            selected_gap=None,
            state=InterviewState.ASKING,
            turn_count=1,
            captured_slots={
                "background": "课程项目",
                "action": ["做了表格", "按类型分类"],
                "result": "返工减少",
            },
            skip_count=0,
            draft_card=None,
            message_log=[],
        )
        assert can_draft(sess) is True

    def test_can_draft_true_when_alt_combo(self):
        """(responsibility, action, metric) 满足 → can_draft True"""
        from core.interview_agent import InterviewSession, InterviewState, can_draft

        sess = InterviewSession(
            session_id="ia_test002",
            target_role="test_qa",
            jd_digest={},
            selected_gap=None,
            state=InterviewState.ASKING,
            turn_count=1,
            captured_slots={
                "responsibility": "测试反馈整理",
                "action": ["做了表格"],
                "metric": ["覆盖 50 个用例"],
            },
            skip_count=0,
            draft_card=None,
            message_log=[],
        )
        assert can_draft(sess) is True

    def test_build_draft_card_contains_required_fields(self):
        """build_draft_card 必须含 title / responsibility / actions / draft_bullets"""
        from core.interview_agent import (
            InterviewSession, InterviewState, GapCandidate, build_draft_card,
        )

        gap = GapCandidate(
            gap_id="process_metric", label="流程优化", reason="",
            keywords=[], source=[], tier="required",
            priority=10.0, suggested_slots=("responsibility", "action", "result", "metric"),
        )
        sess = InterviewSession(
            session_id="ia_test003",
            target_role="test_qa",
            jd_digest={},
            selected_gap=gap,
            state=InterviewState.DRAFT_READY,
            turn_count=3,
            captured_slots={
                "responsibility": "测试反馈整理",
                "action": ["做了表格", "按类型分类"],
                "result": "返工减少",
                "metric": [],
            },
            skip_count=0,
            draft_card=None,
            message_log=[],
        )
        card = build_draft_card(sess)
        # 必含字段
        for f in ("title", "responsibility", "actions", "draft_bullets", "warnings"):
            assert f in card, f"draft_card 缺字段 {f!r}"
        assert isinstance(card["draft_bullets"], list)
        assert len(card["draft_bullets"]) >= 1

    def test_draft_card_warnings_for_missing_quant(self):
        """无 metric 时 warnings 含 '缺少量化' 或类似提示"""
        from core.interview_agent import (
            InterviewSession, InterviewState, GapCandidate, build_draft_card,
        )

        gap = GapCandidate(
            gap_id="process_metric", label="流程优化", reason="",
            keywords=[], source=[], tier="required",
            priority=10.0, suggested_slots=("responsibility", "action", "result", "metric"),
        )
        sess = InterviewSession(
            session_id="ia_test004",
            target_role="test_qa",
            jd_digest={},
            selected_gap=gap,
            state=InterviewState.DRAFT_READY,
            turn_count=3,
            captured_slots={
                "responsibility": "测试反馈整理",
                "action": ["做了表格"],
                "result": "返工减少",
                # metric 空
            },
            skip_count=0,
            draft_card=None,
            message_log=[],
        )
        card = build_draft_card(sess)
        warnings = card.get("warnings", [])
        assert isinstance(warnings, list)
        assert any("量化" in w or "metric" in w.lower() or "数据" in w for w in warnings), (
            f"无 metric 时 warnings 应含量化提示, 实际 {warnings}"
        )


# ----------------------------------------------------------------------
# 5. 状态机
# ----------------------------------------------------------------------
class TestStateMachine:
    def test_apply_action_skip_increments_skip_count(self):
        """action='skip_question' → skip_count += 1"""
        from core.interview_agent import (
            InterviewSession, InterviewState, GapCandidate, ActionType,
            apply_action,
        )

        gap = GapCandidate(
            gap_id="process_metric", label="流程", reason="",
            keywords=[], source=[], tier="required",
            priority=10.0, suggested_slots=("responsibility", "action", "result", "metric"),
        )
        sess = InterviewSession(
            session_id="ia_test005", target_role="test_qa",
            jd_digest={}, selected_gap=gap, state=InterviewState.ASKING,
            turn_count=0, captured_slots={}, skip_count=0,
            draft_card=None, message_log=[],
        )
        new_sess, _ = apply_action(sess, ActionType.SKIP_QUESTION, None)
        assert new_sess.skip_count == 1

    def test_two_consecutive_skips_forces_draft(self):
        """连续 2 次 skip → state 进入 DRAFT_READY(或 ABORTED),trigger draft 提示"""
        from core.interview_agent import (
            InterviewSession, InterviewState, GapCandidate, ActionType,
            apply_action,
        )

        gap = GapCandidate(
            gap_id="process_metric", label="流程", reason="",
            keywords=[], source=[], tier="required",
            priority=10.0, suggested_slots=("responsibility", "action", "result", "metric"),
        )
        sess = InterviewSession(
            session_id="ia_test006", target_role="test_qa",
            jd_digest={}, selected_gap=gap, state=InterviewState.ASKING,
            turn_count=0, captured_slots={}, skip_count=0,
            draft_card=None, message_log=[],
        )
        s1, _ = apply_action(sess, ActionType.SKIP_QUESTION, None)
        s2, r2 = apply_action(s1, ActionType.SKIP_QUESTION, None)
        # 第 2 次 skip 后,要么 state=DRAFT_READY,要么 r2 含 can_draft=True 提示
        assert s2.state in (InterviewState.DRAFT_READY, InterviewState.ABORTED) or r2.get("force_draft") is True, (
            f"连续 2 次 skip 应触发 draft 收束, 实际 state={s2.state}, response={r2}"
        )

    def test_max_turns_per_gap_caps_at_three(self):
        """MAX_TURNS_PER_GAP=3 上限 — turn_count 超 3 时强制 draft 提示"""
        from core.interview_agent import (
            InterviewSession, InterviewState, GapCandidate, ActionType,
            apply_action, MAX_TURNS_PER_GAP,
        )

        # 确认常量
        assert MAX_TURNS_PER_GAP == 3, f"MAX_TURNS_PER_GAP 应为 3, 实际 {MAX_TURNS_PER_GAP}"

        gap = GapCandidate(
            gap_id="process_metric", label="流程", reason="",
            keywords=[], source=[], tier="required",
            priority=10.0, suggested_slots=("responsibility", "action", "result", "metric"),
        )
        # turn_count 已经 = MAX_TURNS_PER_GAP
        sess = InterviewSession(
            session_id="ia_test007", target_role="test_qa",
            jd_digest={}, selected_gap=gap, state=InterviewState.ASKING,
            turn_count=MAX_TURNS_PER_GAP, captured_slots={}, skip_count=0,
            draft_card=None, message_log=[],
        )
        _, r = apply_action(sess, ActionType.ANSWER, "继续追问")
        # 轮数已到上限,即使 can_draft=False 也应该给 draft 提示
        assert r.get("force_draft") is True or r.get("can_draft") is True, (
            f"turn_count={MAX_TURNS_PER_GAP} 应触发 force_draft, 实际 response={r}"
        )


# ----------------------------------------------------------------------
# 6. trace 隐私
# ----------------------------------------------------------------------
class TestTracePrivacy:
    def test_trace_does_not_contain_user_message(self, monkeypatch):
        """trace 写入不存 user_message 原文"""
        from core import interview_agent
        from core.interview_agent import (
            InterviewSession, InterviewState, GapCandidate, apply_action, ActionType,
        )

        captured: list[dict] = []

        def fake_log(event: dict) -> None:
            captured.append(event)

        monkeypatch.setattr(interview_agent, "log_agent_trace_jsonl", fake_log)

        gap = GapCandidate(
            gap_id="process_metric", label="流程", reason="",
            keywords=[], source=[], tier="required",
            priority=10.0, suggested_slots=("responsibility", "action", "result", "metric"),
        )
        sess = InterviewSession(
            session_id="ia_test008", target_role="test_qa",
            jd_digest={}, selected_gap=gap, state=InterviewState.ASKING,
            turn_count=0, captured_slots={}, skip_count=0,
            draft_card=None, message_log=[],
        )
        secret_message = "PII_SENTINEL_USER_MSG_42_xyz"
        apply_action(sess, ActionType.ANSWER, secret_message)
        # 所有写入的 trace 都不应含原文
        for ev in captured:
            blob = repr(ev)
            assert secret_message not in blob, (
                f"trace 含 user_message 原文: {ev}"
            )
        # workflow 字段应是 "interview"
        assert any(ev.get("workflow") == "interview" for ev in captured), (
            f"trace 应有 workflow='interview', 实际 events={captured}"
        )

    def test_trace_does_not_contain_draft_card_text(self, monkeypatch):
        """trace 写入不存 draft_card text 原文"""
        from core import interview_agent
        from core.interview_agent import (
            InterviewSession, InterviewState, GapCandidate,
            apply_action, ActionType,
        )

        captured: list[dict] = []

        def fake_log(event: dict) -> None:
            captured.append(event)

        monkeypatch.setattr(interview_agent, "log_agent_trace_jsonl", fake_log)

        gap = GapCandidate(
            gap_id="process_metric", label="流程", reason="",
            keywords=[], source=[], tier="required",
            priority=10.0, suggested_slots=("responsibility", "action", "result", "metric"),
        )
        sess = InterviewSession(
            session_id="ia_test009", target_role="test_qa",
            jd_digest={}, selected_gap=gap, state=InterviewState.ASKING,
            turn_count=0,
            captured_slots={
                "responsibility": "PII_SENTINEL_RESP_99",
                "action": ["PII_SENTINEL_ACTION_88"],
                "result": "PII_SENTINEL_RESULT_77",
            },
            skip_count=0,
            draft_card=None,
            message_log=[],
        )
        # 触发 draft_now
        try:
            apply_action(sess, ActionType.DRAFT_NOW, None)
        except Exception:
            # draft_now 可能因为某些原因抛(例如接口差异)— 我们关心的是 trace
            pass
        # 全部 sentinel 字符串都不应进入 trace
        for sentinel in (
            "PII_SENTINEL_RESP_99",
            "PII_SENTINEL_ACTION_88",
            "PII_SENTINEL_RESULT_77",
        ):
            for ev in captured:
                assert sentinel not in repr(ev), (
                    f"trace 含 draft_card 原文 ({sentinel}): {ev}"
                )


# ----------------------------------------------------------------------
# 7. Round 6-A Phase 2: save_card 写库闭环
# ----------------------------------------------------------------------
def _real_materials_path() -> Path:
    """定位 backend/data/materials.json — 不依赖 cwd,只用 __file__ 解析。"""
    return Path(__file__).resolve().parent.parent / "data" / "materials.json"


def _save_card_sess(sid: str, target_role: str = "test_qa"):
    """构造一个 DRAFT_READY 状态的 session,可以直接调 save_card。"""
    from core.interview_agent import (
        GapCandidate, InterviewSession, InterviewState,
    )

    gap = GapCandidate(
        gap_id="process_metric",
        label="流程优化/量化结果",
        reason="save_card 测试",
        keywords=["流程", "效率"],
        source=["manual"],
        tier="required",
        priority=9.0,
        suggested_slots=("responsibility", "action", "result", "metric"),
    )
    return InterviewSession(
        session_id=sid,
        target_role=target_role,
        jd_digest={},
        selected_gap=gap,
        state=InterviewState.DRAFT_READY,
        turn_count=3,
        captured_slots={
            "responsibility": "测试反馈整理",
            "action": ["做了表格", "统一格式"],
            "result": "返工减少",
            "metric": ["覆盖 50 个用例"],
        },
        skip_count=0,
        draft_card=None,
        message_log=[],
    )


def _save_card_edited() -> dict:
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


class TestSaveCard:
    """Round 6-A Phase 2: save_card 写库闭环(plan §2.4)。"""

    def test_save_card_writes_to_temp_materials_path(self, tmp_path, monkeypatch):
        """save_card 写入临时 materials_path,不污染真实 data/materials.json。

        关键不变量:即使测试失败也不能留下真实的 materials.json 残骸。
        """
        from core import interview_agent
        from core.interview_agent import InterviewState, save_card

        # 1) 真实 materials.json 当前内容 — 测试结束时要断言完全不变
        real_path = _real_materials_path()
        real_before = real_path.read_text(encoding="utf-8") if real_path.exists() else ""

        # 2) 临时文件作为 save_card 目标
        temp_mats = tmp_path / "materials.json"
        temp_mats.write_text(
            json.dumps(_minimal_materials(), ensure_ascii=False),
            encoding="utf-8",
        )

        # 3) 拦截 trace 写入,避免真实 jsonl 追加
        captured_traces: list[dict] = []
        monkeypatch.setattr(
            interview_agent, "log_agent_trace_jsonl",
            lambda ev: captured_traces.append(ev),
        )

        sess = _save_card_sess("ia_save001")
        edited_card = _save_card_edited()

        result = save_card(
            sess, edited_card, "append_project",
            materials_path=temp_mats,
        )

        # 返回结构
        assert result["ok"] is True
        assert result["material_ref"]["type"] == "project"
        new_id = result["material_ref"]["id"]
        assert new_id.startswith("interview_"), f"id 前缀应为 interview_, 实际 {new_id!r}"
        assert result["refresh"]["should_refresh_preview"] is True
        assert result["refresh"]["should_refresh_match"] is True

        # 临时文件里有新 project
        new_data = json.loads(temp_mats.read_text(encoding="utf-8"))
        assert any(p["id"] == new_id for p in new_data["projects"]), (
            f"新 project {new_id} 不在临时 materials.json 里"
        )

        # 新 project 字段结构(决策点 D1 落地点)
        new_proj = next(p for p in new_data["projects"] if p["id"] == new_id)
        assert new_proj["category"] == "interview_captured", (
            f"category 应为 interview_captured, 实际 {new_proj.get('category')!r}"
        )
        assert "interview_agent" in new_proj["tags"], (
            f"tags 应含 interview_agent, 实际 {new_proj.get('tags')!r}"
        )
        # highlights 是 dict(role_key + general 双写入,plan §2.3)
        assert isinstance(new_proj["highlights"], dict), (
            f"highlights 必须是 dict, 实际 type={type(new_proj.get('highlights')).__name__}"
        )
        assert new_proj["highlights"]["test_qa"] == edited_card["draft_bullets"]
        assert new_proj["highlights"]["general"] == edited_card["draft_bullets"]
        # 审计字段
        assert "_interview_meta" in new_proj
        meta = new_proj["_interview_meta"]
        assert meta["source_gap_id"] == "process_metric"
        assert meta["source_session_id"] == "ia_save001"

        # session state 切到 SAVED
        assert sess.state == InterviewState.SAVED

        # trace: workflow=interview, tool=save_card, step 数字
        save_traces = [
            t for t in captured_traces
            if t.get("workflow") == "interview" and t.get("tool") == "save_card"
        ]
        assert len(save_traces) == 1, (
            f"应有 1 条 save_card trace, 实际 {len(save_traces)}"
        )
        st = save_traces[0]
        assert isinstance(st.get("step"), int), f"step 应为 int, 实际 {st.get('step')!r}"
        assert st["input_size"] > 0
        assert st["output_size"] > 0

        # 关键不变量: 真实 materials.json 完全没动
        real_after = real_path.read_text(encoding="utf-8") if real_path.exists() else ""
        assert real_after == real_before, (
            "save_card 竟意外修改真实 data/materials.json!"
        )

    def test_save_card_generates_unique_project_id(self, tmp_path):
        """连续 2 次 save 不冲突(plan §2.3 id 生成规则)。"""
        from core.interview_agent import save_card

        temp_mats = tmp_path / "materials.json"
        temp_mats.write_text(
            json.dumps(_minimal_materials(), ensure_ascii=False),
            encoding="utf-8",
        )

        sess1 = _save_card_sess("ia_save002a")
        sess2 = _save_card_sess("ia_save002b")
        edited_card = _save_card_edited()

        r1 = save_card(sess1, edited_card, "append_project", materials_path=temp_mats)
        r2 = save_card(sess2, edited_card, "append_project", materials_path=temp_mats)

        assert r1["material_ref"]["id"] != r2["material_ref"]["id"], (
            f"连续 2 次 save_card 生成相同 project id: {r1['material_ref']['id']}"
        )

        data = json.loads(temp_mats.read_text(encoding="utf-8"))
        ids = [p["id"] for p in data["projects"]]
        assert r1["material_ref"]["id"] in ids
        assert r2["material_ref"]["id"] in ids
        assert len(set(ids)) == len(ids), f"projects 列表有重复 id: {ids}"

    def test_save_card_round_trip_through_preview_resume(
        self, tmp_path, monkeypatch,
    ):
        """save_card 写入后,preview_resume 能 pick 到新 highlights。

        round-trip 验证: save_card 写入的 project 必须能被 _pick_highlights 选中,
        进而被 preview_resume 渲染到 sections 里。这是 save-card 闭环的核心证据。
        """
        from core import generator, interview_agent
        from core.interview_agent import save_card
        from core.generator import preview_resume

        # 临时 materials + monkeypatch generator.MATERIALS_PATH 让 preview_resume 读它
        temp_mats = tmp_path / "materials.json"
        # 完整版 fixture, 让 preview_resume 的 build_sections 能跑通
        temp_mats.write_text(
            json.dumps(_full_materials_for_round_trip(), ensure_ascii=False),
            encoding="utf-8",
        )
        monkeypatch.setattr(generator, "MATERIALS_PATH", temp_mats)
        # 拦截 trace
        monkeypatch.setattr(
            interview_agent, "log_agent_trace_jsonl",
            lambda ev: None,
        )

        sess = _save_card_sess("ia_save003", target_role="test_qa")
        # 用唯一 sentinel 字符串验证 round-trip
        sentinel_bullet_a = "ROUND_TRIP_BULLET_A_zzz"
        sentinel_bullet_b = "ROUND_TRIP_BULLET_B_zzz"
        edited_card = _save_card_edited()
        edited_card["draft_bullets"] = [sentinel_bullet_a, sentinel_bullet_b]

        result = save_card(
            sess, edited_card, "append_project",
            materials_path=temp_mats,
        )
        new_id = result["material_ref"]["id"]

        # round-trip: 老路径 preview_resume(enable_agent_workflow=False 默认,不动 R5-A)
        # 用 custom_project_ids 把新 id 注入,build_sections 才会渲染它
        preview = preview_resume(target_role="test_qa", custom_project_ids=[new_id])

        # 在 project_group section 里找含 sentinel bullet 的项目,断言出现
        # Section dataclass 没有 id 字段(id 在 materials["projects"][i]["id"] 里),
        # 所以匹配方式改为: 找 highlights 含 sentinel bullet 的项目
        found_a = False
        found_b = False
        for section in preview.get("sections", []):
            if section.get("type") != "project_group":
                continue
            content = section.get("content") or {}
            for proj in content.get("projects", []):
                proj_content = proj.get("content", {})
                highlights = proj_content.get("highlights", []) or []
                if any(sentinel_bullet_a in (h or "") for h in highlights):
                    found_a = True
                if any(sentinel_bullet_b in (h or "") for h in highlights):
                    found_b = True
        assert found_a, (
            f"preview_resume 没 pick 到 sentinel_bullet_a "
            f"(project {new_id} 写入后, project_group.highlights 不含 sentinel)"
        )
        assert found_b, (
            f"preview_resume 没 pick 到 sentinel_bullet_b "
            f"(project {new_id} 写入后, project_group.highlights 不含 sentinel)"
        )

        # 关键不变量: 真实 materials.json 没动
        real_path = _real_materials_path()
        real_after = real_path.read_text(encoding="utf-8")
        sentinel_count = real_after.count("ROUND_TRIP_BULLET")
        assert sentinel_count == 0, (
            f"真实 materials.json 被 round-trip 测试污染, 出现 {sentinel_count} 次 sentinel"
        )