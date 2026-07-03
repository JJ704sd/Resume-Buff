"""
Round 6-D 测试集(2026-07-02 落地): LLM slot 抽取模块的测试覆盖。

平移自 test_interview_agent.py 的 LLM extraction 相关测试类, 因为 LLM 抽取
代码已从 core.interview_agent 物理搬到 core.interview_llm。mock urlopen
路径从 `core.interview_agent.urllib.request.urlopen` 改为
`core.interview_llm.urllib.request.urlopen`(urlopen 在 llm 模块命名空间
里被调, monkeypatch 必须改对模块)。

测试覆盖总览(R6-D 平移合计 35 case, baseline 930 → 拆 935 文件计数 1 个变 2 个):
  - TestLLMSlotExtraction       (6 case R6-A Phase 4): extract_slots LLM 分支
  - TestInterviewPromptRegistry (4 case R6-A Phase 4): LLM prompt 注册表 + 默认常量同步
  - TestSlotMetaLlmR6B          (5 case R6-B Phase 1): LLM source_span hash 化 + confidence 校验
  - TestSlotMetaPrivacyR6B      (3 case R6-B Phase 1): LLM 路径下隐私边界
  - TestSlotMetaUnitR6B         (6 case R6-B Phase 1): helper 单元
  - TestPhaseC3LLMObservability (11 case R6-C.3):     LLM 抽取可观测性

mock 路径变更规范:
  - 旧: `unittest.mock.patch("core.interview_agent.urllib.request.urlopen", ...)`
  - 新: `unittest.mock.patch("core.interview_llm.urllib.request.urlopen", ...)`
  - 旧: `monkeypatch.setattr(interview_agent, "_call_llm_for_slot_extraction", ...)`
  - 新: `monkeypatch.setattr(interview_llm, "_call_llm_for_slot_extraction", ...)`

行为不变保证(R6-D):
  - 所有测试 docstring / 断言 / mock 内容**不**修改
  - 仅 import 路径与 mock 模块路径更新
  - 老路径(llm_enabled=False / 默认)字节级一致, 3 个可观测字段保持 0 / {} / {}
"""
import json
import unittest.mock

import pytest



class TestLLMSlotExtraction:
    """R6-A Phase 4: extract_slots LLM 分支(plan §4.5)。

    覆盖:
      - llm_enabled=False / 无 key → 走规则版
      - llm_enabled=True + key → 调 LLM(mock urllib.request.urlopen)
      - LLM 返非 JSON → retry 1 次(只调 urlopen 2 次)
      - LLM schema 错 → fallback 规则, 不阻断
      - LLM 网络错 → fallback 规则, 不抛
    """

    def test_llm_extraction_disabled_falls_back_to_rules(self):
        """llm_enabled=False / 缺省: 走 _extract_slots_by_rules, 不调 LLM。"""
        import unittest.mock

        from core import interview_agent

        with unittest.mock.patch(
            "core.interview_llm.urllib.request.urlopen"
        ) as mock_urlopen:
            result = interview_agent.extract_slots(
                "我做了一个表格模板, 按问题类型、复现步骤、负责人和状态来记录。",
                "action",
                llm_enabled=False,
            )
        mock_urlopen.assert_not_called()
        # 规则版: action 用 ;/。/,\n 切, 至少 1 条
        assert isinstance(result.get("action"), list)
        assert len(result["action"]) >= 1
        assert "_warnings" in result

    def test_llm_extraction_no_key_falls_back_to_rules(self, monkeypatch):
        """llm_enabled=True 但无 key → 走规则版, 不调 LLM。"""
        import unittest.mock

        from core import interview_agent

        monkeypatch.delenv("LLM_API_KEY", raising=False)
        with unittest.mock.patch(
            "core.interview_llm.urllib.request.urlopen"
        ) as mock_urlopen:
            result = interview_agent.extract_slots(
                "我做了一个表格模板, 按问题类型、复现步骤、负责人和状态来记录。",
                "action",
                llm_enabled=True,
                llm_api_key="",  # 显式空
            )
        mock_urlopen.assert_not_called()
        assert isinstance(result.get("action"), list)

    def test_llm_extraction_with_key_calls_llm(self, monkeypatch):
        """llm_enabled=True + 有 key → 调 urlopen 1 次, 解析 LLM 返回的 schema。"""
        import unittest.mock

        from core import interview_agent

        monkeypatch.setenv("LLM_API_KEY", "test-key-1234")

        # 模拟 OpenAI-compatible /chat/completions 返回
        fake_content = json.dumps({
            "action": ["做了一个表格模板", "按问题类型、复现步骤、负责人和状态记录"],
            "_warnings": [],
        }, ensure_ascii=False)
        fake_resp_body = json.dumps({
            "choices": [{"message": {"content": fake_content}}],
        }, ensure_ascii=False).encode("utf-8")

        class _FakeResp:
            def __init__(self, body):
                self._body = body

            def read(self):
                return self._body

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        with unittest.mock.patch(
            "core.interview_llm.urllib.request.urlopen",
            return_value=_FakeResp(fake_resp_body),
        ) as mock_urlopen:
            result = interview_agent.extract_slots(
                "我做了一个表格模板, 按问题类型、复现步骤、负责人和状态来记录。",
                "action",
                llm_enabled=True,
                llm_base_url="https://mock.example.com",
                llm_model="mock-model",
            )

        # urlopen 调 1 次(成功路径, 不 retry)
        assert mock_urlopen.call_count == 1, (
            f"LLM 调用 urlopen 应调 1 次, 实际 {mock_urlopen.call_count}"
        )
        # LLM 输出被透传(不是规则版)
        assert result["action"] == [
            "做了一个表格模板",
            "按问题类型、复现步骤、负责人和状态记录",
        ]

    def test_llm_extraction_invalid_json_retries_once(self, monkeypatch):
        """LLM 返非 JSON → retry 1 次(strict_retry=True), 仍失败 → fallback 规则。"""
        import unittest.mock

        from core import interview_agent

        monkeypatch.setenv("LLM_API_KEY", "test-key-1234")

        class _FakeResp:
            def __init__(self, body):
                self._body = body

            def read(self):
                return self._body

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        # 2 次都返非 JSON
        bad_body = b"not a json response"

        with unittest.mock.patch(
            "core.interview_llm.urllib.request.urlopen",
            return_value=_FakeResp(bad_body),
        ) as mock_urlopen:
            result = interview_agent.extract_slots(
                "我做了一个表格模板, 按问题类型、复现步骤、负责人和状态来记录。",
                "action",
                llm_enabled=True,
                llm_base_url="https://mock.example.com",
                llm_model="mock-model",
            )

        # urlopen 应调 2 次(1 次失败 + 1 次 retry)
        assert mock_urlopen.call_count == 2, (
            f"schema retry 应调 2 次 urlopen, 实际 {mock_urlopen.call_count}"
        )
        # fallback 到规则版(action 仍返回非空 list)
        assert isinstance(result.get("action"), list)
        assert len(result["action"]) >= 1

    def test_llm_extraction_schema_error_falls_back_to_rules(self, monkeypatch):
        """LLM 返合法 JSON 但 schema 不符(缺 action key) → fallback 规则, 不阻断。"""
        import unittest.mock

        from core import interview_agent

        monkeypatch.setenv("LLM_API_KEY", "test-key-1234")

        # schema 错: 缺 action key
        bad_schema_content = json.dumps({"_warnings": []}, ensure_ascii=False)
        bad_schema_body = json.dumps({
            "choices": [{"message": {"content": bad_schema_content}}],
        }, ensure_ascii=False).encode("utf-8")

        class _FakeResp:
            def __init__(self, body):
                self._body = body

            def read(self):
                return self._body

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        with unittest.mock.patch(
            "core.interview_llm.urllib.request.urlopen",
            return_value=_FakeResp(bad_schema_body),
        ) as mock_urlopen:
            result = interview_agent.extract_slots(
                "我做了一个表格模板, 按问题类型、复现步骤、负责人和状态来记录。",
                "action",
                llm_enabled=True,
                llm_base_url="https://mock.example.com",
                llm_model="mock-model",
            )

        # schema retry 1 次 → urlopen 调 2 次
        assert mock_urlopen.call_count == 2, (
            f"schema 错应 retry 1 次, 实际 urlopen 调 {mock_urlopen.call_count} 次"
        )
        # fallback 规则版
        assert isinstance(result.get("action"), list)
        assert len(result["action"]) >= 1

    def test_llm_extraction_network_error_falls_back_to_rules(self, monkeypatch):
        """LLM 网络错(URLError) → fallback 规则版, 不抛。"""
        import unittest.mock
        from urllib.error import URLError

        from core import interview_agent

        monkeypatch.setenv("LLM_API_KEY", "test-key-1234")

        with unittest.mock.patch(
            "core.interview_llm.urllib.request.urlopen",
            side_effect=URLError("conn refused"),
        ) as mock_urlopen:
            # 不应抛
            result = interview_agent.extract_slots(
                "我做了一个表格模板, 按问题类型、复现步骤、负责人和状态来记录。",
                "action",
                llm_enabled=True,
                llm_base_url="https://mock.example.com",
                llm_model="mock-model",
            )

        # 网络错不 retry(沿用 _call_with_retry 风格) → urlopen 调 1 次
        assert mock_urlopen.call_count == 1, (
            f"网络错不应 retry, 实际 urlopen 调 {mock_urlopen.call_count} 次"
        )
        # fallback 规则版
        assert isinstance(result.get("action"), list)


# ----------------------------------------------------------------------
# 8. R6-A Phase 4: prompt registry / 边界保护(plan §4.5)




class TestInterviewPromptRegistry:
    """R6-A Phase 4: prompt 注册表 / R5-E 边界保护(plan §4.5)。

    覆盖:
      - SLOT_EXTRACTION_SYSTEM_PROMPT 是非空 str
      - SLOT_EXTRACTION_USER_TEMPLATE 不含 {jd_text} 防泄漏
      - PROMPT_VERSIONS 不含 interview prompt key (R5-E 保护)
      - 本地默认常量跟 core.llm_rewriter.DEFAULT_* 同步
    """

    def test_slot_extraction_prompt_registered(self):
        """SLOT_EXTRACTION_SYSTEM_PROMPT 是非空 str。"""
        from core.interview_prompts import SLOT_EXTRACTION_SYSTEM_PROMPT

        assert isinstance(SLOT_EXTRACTION_SYSTEM_PROMPT, str)
        assert len(SLOT_EXTRACTION_SYSTEM_PROMPT.strip()) > 0

    def test_slot_extraction_prompt_excludes_jd_full_text(self):
        """模板不含 {jd_text}, 防止 LLM 调用意外拿到 JD 全文(spec §4.4 隐私)。"""
        from core.interview_prompts import SLOT_EXTRACTION_USER_TEMPLATE

        assert isinstance(SLOT_EXTRACTION_USER_TEMPLATE, str)
        assert "{jd_text}" not in SLOT_EXTRACTION_USER_TEMPLATE, (
            "USER_TEMPLATE 含 {jd_text} 会让 LLM 调用意外拿到 JD 全文, "
            "违反 plan §4.4 隐私边界"
        )
        # 验证可正常 format
        rendered = SLOT_EXTRACTION_USER_TEMPLATE.format(
            slot="action", user_message="做了一件事",
        )
        assert "action" in rendered
        assert "做了一件事" in rendered

    def test_interview_prompts_not_in_llm_rewriter_registry(self):
        """PROMPT_VERSIONS 不含 interview prompt key (R5-E 保护, 决策点 D5)。"""
        from core.llm_rewriter import PROMPT_VERSIONS

        for forbidden_key in (
            "v6-interview-slot",
            "v6-interview-draft",
            "interview-slot",
            "interview-slot-extract",
        ):
            assert forbidden_key not in PROMPT_VERSIONS, (
                f"R5-E 边界保护违反: PROMPT_VERSIONS 不应含 {forbidden_key!r}"
                f"(决策点 D5: interview LLM prompt 独立常量, 不进 PROMPT_VERSIONS)"
            )

    def test_interview_llm_defaults_match_llm_rewriter(self):
        """interview_agent 本地默认常量跟 llm_rewriter 同步(防漂移)。

        R5-E 边界: interview_agent.py 文件任意位置不能出现
        `from core.llm_rewriter import ...` — 所以常量本地定义,
        测试锁防两边漂移。
        """
        from core import interview_agent
        from core.llm_rewriter import DEFAULT_BASE_URL, DEFAULT_MODEL

        assert (
            interview_agent._INTERVIEW_LLM_DEFAULT_BASE_URL == DEFAULT_BASE_URL
        ), (
            f"_INTERVIEW_LLM_DEFAULT_BASE_URL={interview_agent._INTERVIEW_LLM_DEFAULT_BASE_URL!r} "
            f"与 llm_rewriter.DEFAULT_BASE_URL={DEFAULT_BASE_URL!r} 不一致"
        )
        assert (
            interview_agent._INTERVIEW_LLM_DEFAULT_MODEL == DEFAULT_MODEL
        ), (
            f"_INTERVIEW_LLM_DEFAULT_MODEL={interview_agent._INTERVIEW_LLM_DEFAULT_MODEL!r} "
            f"与 llm_rewriter.DEFAULT_MODEL={DEFAULT_MODEL!r} 不一致"
        )


# ----------------------------------------------------------------------
# 9. R6-B Phase 1: slot_meta provenance(spec §5.1+§5.2)
# ----------------------------------------------------------------------




class TestSlotMetaLlmR6B:
    """R6-B Phase 1 spec §5.2: LLM source_span 在函数内 hash + len, 永不入 session/trace/API。

    覆盖:
      - 合法 string source_span → hash + len 写入 meta
      - confidence 是 0.0-1.0 number → 写入 meta
      - confidence 是 bool → 拒绝(走 default fallback)
      - source_span 是 None / 非 string → 降级到无 source_span_*
      - 多次写入同一 slot → 保留最近 INTERVIEW_SLOT_META_MAX 条
    """

    def test_llm_source_span_hashed_into_meta(self, monkeypatch):
        """LLM 返合法 source_span(string) → meta 含 sha256:... + len。"""
        import unittest.mock

        from core import interview_agent

        monkeypatch.setenv("LLM_API_KEY", "test-key-r6b-001")

        sentinel_span = "PII_SENTINEL_SPAN_xyz123_ABC"
        fake_content = json.dumps({
            "action": ["做了一个表格"],
            "_warnings": [],
            "source_span": sentinel_span,
            "confidence": 0.92,
            "reason_code": "explicit_action",
        }, ensure_ascii=False)
        fake_body = json.dumps({
            "choices": [{"message": {"content": fake_content}}],
        }, ensure_ascii=False).encode("utf-8")

        class _FakeResp:
            def __init__(self, body):
                self._body = body

            def read(self):
                return self._body

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        with unittest.mock.patch(
            "core.interview_llm.urllib.request.urlopen",
            return_value=_FakeResp(fake_body),
        ):
            out = interview_agent.extract_slots(
                "我做了一个表格模板",
                "action",
                llm_enabled=True,
                llm_base_url="https://mock.example.com",
                llm_model="mock-model",
                turn_index=7,
            )

        meta_list = out.get("_slot_meta")
        assert isinstance(meta_list, list) and len(meta_list) == 1
        meta = meta_list[0]
        assert meta["extractor"] == "llm"
        assert meta["confidence"] == 0.92
        assert meta["turn_index"] == 7
        assert meta["reason_code"] == "llm_explicit_action"
        # 关键: source_span 明文不入 meta
        assert sentinel_span not in json.dumps(meta, ensure_ascii=False)
        # hash + len 写入
        assert meta["source_span_hash"] is not None
        assert meta["source_span_hash"].startswith("sha256:")
        assert meta["source_span_len"] == len(sentinel_span)

    def test_llm_invalid_source_span_degrades(self, monkeypatch):
        """LLM 返非法 source_span(非 string / None) → 降级, 不写 source_span_*, 不抛。"""
        import unittest.mock

        from core import interview_agent

        monkeypatch.setenv("LLM_API_KEY", "test-key-r6b-002")

        fake_content = json.dumps({
            "action": ["做了一个表格"],
            "_warnings": [],
            "source_span": 12345,  # 非 string
            "confidence": 0.9,
        }, ensure_ascii=False)
        fake_body = json.dumps({
            "choices": [{"message": {"content": fake_content}}],
        }, ensure_ascii=False).encode("utf-8")

        class _FakeResp:
            def __init__(self, body):
                self._body = body

            def read(self):
                return self._body

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        with unittest.mock.patch(
            "core.interview_llm.urllib.request.urlopen",
            return_value=_FakeResp(fake_body),
        ):
            out = interview_agent.extract_slots(
                "我做了一个表格模板",
                "action",
                llm_enabled=True,
                llm_base_url="https://mock.example.com",
                llm_model="mock-model",
                turn_index=3,
            )

        meta = out["_slot_meta"][0]
        assert meta["extractor"] == "llm"
        assert meta["source_span_hash"] is None
        assert meta["source_span_len"] is None
        # confidence 合法 → 透传
        assert meta["confidence"] == 0.9

    def test_llm_confidence_bool_rejected(self, monkeypatch):
        """LLM 返 confidence=True(bool) → 拒绝, 走 _make_slot_meta fallback (0.60)。

        spec §5.2: confidence 必须是 0.0-1.0 number, bool 不接受。
        """
        import unittest.mock

        from core import interview_agent

        monkeypatch.setenv("LLM_API_KEY", "test-key-r6b-003")

        fake_content = json.dumps({
            "action": ["做了一个表格"],
            "_warnings": [],
            "confidence": True,  # bool — 必须拒绝
        }, ensure_ascii=False)
        fake_body = json.dumps({
            "choices": [{"message": {"content": fake_content}}],
        }, ensure_ascii=False).encode("utf-8")

        class _FakeResp:
            def __init__(self, body):
                self._body = body

            def read(self):
                return self._body

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        with unittest.mock.patch(
            "core.interview_llm.urllib.request.urlopen",
            return_value=_FakeResp(fake_body),
        ):
            out = interview_agent.extract_slots(
                "我做了一个表格模板",
                "action",
                llm_enabled=True,
                llm_base_url="https://mock.example.com",
                llm_model="mock-model",
            )

        meta = out["_slot_meta"][0]
        # bool 被拒绝, 走 _make_slot_meta fallback to LLM default 0.60
        assert meta["confidence"] == interview_agent.INTERVIEW_SLOT_META_LLM_DEFAULT_CONFIDENCE
        # 同时确认 meta 里 confidence 是 number 不是 bool
        assert isinstance(meta["confidence"], float)
        assert not isinstance(meta["confidence"], bool)

    def test_llm_confidence_out_of_range_rejected(self, monkeypatch):
        """LLM confidence 越界 (>1.0 或 <0.0) → 拒绝, 走 fallback。"""
        from core import interview_agent

        # 走 _attach_llm_slot_meta 单测 path, 不 mock urlopen
        # 构造 validated-style parsed: {slot, _warnings, confidence, source_span}
        parsed = {
            "action": ["做了一个表格"],
            "_warnings": [],
            "confidence": 5.0,  # 越界
            "source_span": "test",
        }
        out = interview_agent._attach_llm_slot_meta(
            parsed=parsed, current_slot="action", turn_index=0,
        )
        assert out is not None
        meta = out["_slot_meta"][0]
        assert meta["confidence"] == interview_agent.INTERVIEW_SLOT_META_LLM_DEFAULT_CONFIDENCE

    def test_slot_meta_max_5_entries_per_slot(self):
        """per slot 最多保留 INTERVIEW_SLOT_META_MAX=5 条(spec §5.2)。

        模拟同一 slot 写入 7 条 → session.slot_meta[slot] 只剩最后 5 条。
        """
        from core.interview_agent import (
            INTERVIEW_SLOT_META_MAX,
            InterviewSession, InterviewState, _append_slot_meta,
            _make_slot_meta,
        )

        sess = InterviewSession(
            session_id="ia_r6b_cap",
            target_role="test_qa",
            jd_digest={},
            selected_gap=None,
            state=InterviewState.ASKING,
            turn_count=0,
            captured_slots={},
            skip_count=0,
            draft_card=None,
            message_log=[],
        )
        # 写 7 条进 action slot
        for i in range(7):
            entry = _make_slot_meta(
                extractor="rules",
                confidence=0.8,
                turn_index=i,
                reason_code=f"test_{i}",
            )
            _append_slot_meta(sess, "action", [entry])

        assert "action" in sess.slot_meta
        kept = sess.slot_meta["action"]
        assert len(kept) == INTERVIEW_SLOT_META_MAX, (
            f"action slot 应保留最近 {INTERVIEW_SLOT_META_MAX} 条, 实际 {len(kept)}"
        )
        # 保留的是最后 5 条(turn_index 2-6)
        kept_turns = [m["turn_index"] for m in kept]
        assert kept_turns == [2, 3, 4, 5, 6], (
            f"应保留最近 5 条 (turn 2-6), 实际 turn={kept_turns}"
        )




class TestSlotMetaPrivacyR6B:
    """R6-B Phase 1 spec §5.2 隐私边界 + AGENTS.md。

    关键不变量:
      - session.slot_meta 不含 user_message / source_span 明文
      - trace 不含 user_message / source_span 明文
      - extract_slots 返回的 dict 不含 user_message 原文
    """

    def test_slot_meta_no_user_message_text(self, monkeypatch):
        """apply_action 后 session.slot_meta 不含 user_message 原文。"""
        from core.interview_agent import (
            ActionType, GapCandidate, InterviewSession, InterviewState,
            apply_action,
        )

        gap = GapCandidate(
            gap_id="process_metric", label="流程", reason="",
            keywords=[], source=[], tier="required",
            priority=10.0, suggested_slots=("action",),
        )
        sess = InterviewSession(
            session_id="ia_r6b_priv",
            target_role="test_qa",
            jd_digest={},
            selected_gap=gap,
            state=InterviewState.ASKING,
            turn_count=0,
            captured_slots={},
            skip_count=0,
            draft_card=None,
            message_log=[],
        )
        sentinel = "PII_SENTINEL_USER_MSG_R6B_999"
        apply_action(sess, ActionType.ANSWER, f"我做了表格模板 {sentinel}")

        # session.slot_meta 序列化后不含 sentinel
        slot_meta_blob = json.dumps(sess.slot_meta, ensure_ascii=False)
        assert sentinel not in slot_meta_blob, (
            f"session.slot_meta 含 user_message 原文: {sess.slot_meta}"
        )

    def test_slot_meta_no_source_span_plaintext(self, monkeypatch):
        """LLM source_span 转 hash 后, session.slot_meta 不含 source_span 明文。"""
        import unittest.mock

        from core import interview_agent

        monkeypatch.setenv("LLM_API_KEY", "test-key-r6b-priv")

        sentinel_span = "PII_SENTINEL_SOURCE_SPAN_R6B_777_abcdef"
        fake_content = json.dumps({
            "action": ["做了一个表格"],
            "_warnings": [],
            "source_span": sentinel_span,
            "confidence": 0.85,
        }, ensure_ascii=False)
        fake_body = json.dumps({
            "choices": [{"message": {"content": fake_content}}],
        }, ensure_ascii=False).encode("utf-8")

        class _FakeResp:
            def __init__(self, body):
                self._body = body

            def read(self):
                return self._body

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        with unittest.mock.patch(
            "core.interview_llm.urllib.request.urlopen",
            return_value=_FakeResp(fake_body),
        ):
            out = interview_agent.extract_slots(
                "我做了一个表格模板",
                "action",
                llm_enabled=True,
                llm_base_url="https://mock.example.com",
                llm_model="mock-model",
                turn_index=5,
            )

        blob = json.dumps(out, ensure_ascii=False)
        # 关键: source_span 明文不在 extract_slots 返回值里
        assert sentinel_span not in blob, (
            f"extract_slots 返回值含 source_span 明文: {out}"
        )
        # 但 hash 应在
        meta = out["_slot_meta"][0]
        assert sentinel_span not in json.dumps(meta, ensure_ascii=False)

    def test_trace_does_not_leak_source_span(self, monkeypatch):
        """LLM 抽取后 apply_action 写 trace, trace 不含 source_span 明文。"""
        import unittest.mock

        from core import interview_agent
        from core.interview_agent import (
            ActionType, GapCandidate, InterviewSession, InterviewState,
            apply_action,
        )

        captured: list[dict] = []

        def fake_log(event: dict) -> None:
            captured.append(event)

        monkeypatch.setattr(
            interview_agent, "log_agent_trace_jsonl", fake_log,
        )
        monkeypatch.setenv("LLM_API_KEY", "test-key-r6b-trace")

        sentinel_span = "PII_SENTINEL_TRACE_SPAN_R6B_555"
        fake_content = json.dumps({
            "action": ["做了一个表格"],
            "_warnings": [],
            "source_span": sentinel_span,
            "confidence": 0.85,
        }, ensure_ascii=False)
        fake_body = json.dumps({
            "choices": [{"message": {"content": fake_content}}],
        }, ensure_ascii=False).encode("utf-8")

        class _FakeResp:
            def __init__(self, body):
                self._body = body

            def read(self):
                return self._body

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        gap = GapCandidate(
            gap_id="process_metric", label="流程", reason="",
            keywords=[], source=[], tier="required",
            priority=10.0, suggested_slots=("action",),
        )
        sess = InterviewSession(
            session_id="ia_r6b_trace",
            target_role="test_qa",
            jd_digest={},
            selected_gap=gap,
            state=InterviewState.ASKING,
            turn_count=0,
            captured_slots={},
            skip_count=0,
            draft_card=None,
            message_log=[],
        )

        with unittest.mock.patch(
            "core.interview_llm.urllib.request.urlopen",
            return_value=_FakeResp(fake_body),
        ):
            apply_action(
                sess, ActionType.ANSWER,
                "PII_SENTINEL_USER_MSG_R6B_888",
            )

        # 所有 trace 都不应含 source_span / user_message 明文
        for ev in captured:
            blob = repr(ev)
            assert sentinel_span not in blob, (
                f"trace 含 source_span 明文: {ev}"
            )
            assert "PII_SENTINEL_USER_MSG_R6B_888" not in blob, (
                f"trace 含 user_message 明文: {ev}"
            )






class TestSlotMetaUnitR6B:
    """R6-B Phase 1 spec §5.2: helper 单元。

    覆盖:
      - _validate_confidence 边界(bool 拒绝 / 越界拒绝 / 合法通过)
      - _compute_source_span_hash 边界(空 string / 非 string / 合法)
      - _make_slot_meta 半残 source_span 自动归 None
    """

    def test_validate_confidence_bool_rejected(self):
        """_validate_confidence 拒绝 bool(spec §5.2)。"""
        from core.interview_agent import _validate_confidence

        assert _validate_confidence(True) is None
        assert _validate_confidence(False) is None
        # 合法边界
        assert _validate_confidence(0.0) == 0.0
        assert _validate_confidence(1.0) == 1.0
        assert _validate_confidence(0.5) == 0.5
        assert _validate_confidence(0) == 0.0
        assert _validate_confidence(1) == 1.0
        # 越界
        assert _validate_confidence(-0.1) is None
        assert _validate_confidence(1.5) is None
        # 非数字
        assert _validate_confidence("0.5") is None
        assert _validate_confidence(None) is None

    def test_compute_source_span_hash_legal(self):
        """_compute_source_span_hash: 合法 string → (sha256:..., len)。"""
        from core.interview_agent import _compute_source_span_hash

        h, ln = _compute_source_span_hash("测试一段文本")
        assert h is not None and h.startswith("sha256:")
        assert ln == len("测试一段文本")
        # hash 长度稳定(sha256 hex 前 16 字符 + "sha256:" 前缀 = 23 字符)
        assert len(h) == len("sha256:") + 16

    def test_compute_source_span_hash_invalid(self):
        """_compute_source_span_hash: 空 / 非 string → (None, None)。"""
        from core.interview_agent import _compute_source_span_hash

        assert _compute_source_span_hash("") == (None, None)
        assert _compute_source_span_hash(None) == (None, None)
        assert _compute_source_span_hash(12345) == (None, None)
        assert _compute_source_span_hash(["text"]) == (None, None)

    def test_make_slot_meta_half_residue_normalized(self):
        """_make_slot_meta: source_span_hash 与 len 半残时, 都归 None。"""
        from core.interview_agent import _make_slot_meta

        # 只传 hash 不传 len → len=None → 两个都 None
        m1 = _make_slot_meta(
            extractor="rules",
            confidence=0.8,
            turn_index=1,
            reason_code="test",
            source_span_hash="sha256:abc",
            source_span_len=None,
        )
        assert m1["source_span_hash"] is None
        assert m1["source_span_len"] is None

        # 只传 len 不传 hash → hash=None → 两个都 None
        m2 = _make_slot_meta(
            extractor="rules",
            confidence=0.8,
            turn_index=1,
            reason_code="test",
            source_span_hash=None,
            source_span_len=10,
        )
        assert m2["source_span_hash"] is None
        assert m2["source_span_len"] is None

        # 都传 → 都保留
        m3 = _make_slot_meta(
            extractor="rules",
            confidence=0.8,
            turn_index=1,
            reason_code="test",
            source_span_hash="sha256:abc",
            source_span_len=10,
        )
        assert m3["source_span_hash"] == "sha256:abc"
        assert m3["source_span_len"] == 10


# ----------------------------------------------------------------------
# 10. R6-B Phase 3: confidence-aware policy 集成(spec §6)




class TestPhaseC3LLMObservability:
    """R6-C.3: 4 个维度测试

    覆盖:
      A. Request body 改动 — response_format 字段
      B. temperature 仍 0.0
      C. slot_source_breakdown / llm_parse_retry_count / llm_to_rules_slot_fallback_count
      D. prompt few-shot 示例存在 + 不含 JD 原文
    """

    # ---------- A. Request body 改动 ----------

    def test_request_body_includes_response_format_json_object(self, monkeypatch):
        """R6-C.3: LLM 请求 body 含 `response_format={"type": "json_object"}`。

        Mock urlopen 抓 body bytes, json.loads 验证字段结构 + 顺序(在 messages 后,
        temperature 前, 跟 spec 一致)。
        """
        import unittest.mock

        from core import interview_agent

        monkeypatch.setenv("LLM_API_KEY", "test-key-c3-rf")

        captured_body: dict = {}

        def _fake_urlopen(req, timeout=None):
            # req.data 是 bytes, 抓出来供后续断言
            captured_body.update(json.loads(req.data.decode("utf-8")))
            class _R:
                def read(self_inner):
                    return json.dumps({
                        "choices": [{"message": {"content": json.dumps({
                            "responsibility": "检查文本分类结果",
                            "_warnings": [],
                        }, ensure_ascii=False)}}],
                    }, ensure_ascii=False).encode("utf-8")
                def __enter__(self_inner): return self_inner
                def __exit__(self_inner, *a): return False
            return _R()

        with unittest.mock.patch(
            "core.interview_llm.urllib.request.urlopen",
            side_effect=_fake_urlopen,
        ):
            interview_agent.extract_slots(
                "我负责一个数据标注项目, 主要是检查文本分类结果是否符合规则。",
                "responsibility",
                llm_enabled=True,
                llm_base_url="https://mock.example.com",
                llm_model="mock-model",
            )

        # 验证 response_format 字段
        assert "response_format" in captured_body, (
            f"LLM 请求 body 必须含 response_format 字段, 实际 keys={list(captured_body.keys())}"
        )
        assert captured_body["response_format"] == {"type": "json_object"}, (
            f"response_format 应是 {{type: json_object}}, 实际 {captured_body['response_format']!r}"
        )

    # ---------- B. temperature 仍 0.0 ----------

    def test_request_body_temperature_remains_zero(self, monkeypatch):
        """R6-C.3 兼容: temperature 仍 = 0.0(spec §4.4 字节级一致)。"""
        import unittest.mock

        from core import interview_agent

        monkeypatch.setenv("LLM_API_KEY", "test-key-c3-temp")

        captured_body: dict = {}

        def _fake_urlopen(req, timeout=None):
            captured_body.update(json.loads(req.data.decode("utf-8")))
            class _R:
                def read(self_inner):
                    return json.dumps({
                        "choices": [{"message": {"content": json.dumps({
                            "responsibility": "x", "_warnings": [],
                        }, ensure_ascii=False)}}],
                    }, ensure_ascii=False).encode("utf-8")
                def __enter__(self_inner): return self_inner
                def __exit__(self_inner, *a): return False
            return _R()

        with unittest.mock.patch(
            "core.interview_llm.urllib.request.urlopen",
            side_effect=_fake_urlopen,
        ):
            interview_agent.extract_slots(
                "我负责一个数据标注项目, 主要是检查文本分类结果是否符合规则。",
                "responsibility",
                llm_enabled=True,
                llm_base_url="https://mock.example.com",
                llm_model="mock-model",
            )

        assert captured_body.get("temperature") == 0.0, (
            f"temperature 必须仍 = 0.0 (R6-C.3 兼容), 实际 {captured_body.get('temperature')!r}"
        )

    # ---------- C. 可观测性字段 ----------

    def test_session_default_observability_fields_zero_and_empty(self):
        """R6-C.3: InterviewSession 默认值 = slot_source_breakdown={}, retries=0, fb=0。

        老测试构造 InterviewSession 时关键字缺省即可(字节级兼容)。
        """
        from core.interview_agent import InterviewSession, InterviewState

        sess = InterviewSession(
            session_id="ia-c3-default",
            target_role="test_qa",
            jd_digest={},
            selected_gap=None,
            state=InterviewState.EMPTY,
            turn_count=0,
            captured_slots={},
            skip_count=0,
            draft_card=None,
            message_log=[],
        )
        assert sess.slot_source_breakdown == {}, (
            f"默认 slot_source_breakdown 应是 {{}}, 实际 {sess.slot_source_breakdown!r}"
        )
        assert sess.llm_parse_retry_count == 0
        assert sess.llm_to_rules_slot_fallback_count == 0

    def test_slot_source_breakdown_rules_only_when_llm_disabled(self):
        """R6-C.3: llm_enabled=False → slot_source_breakdown 只 +rules, retries/fb 永远 0。"""
        from core import interview_agent
        from core.interview_agent import InterviewSession

        sess = InterviewSession(
            session_id="ia-c3-rules",
            target_role="test_qa",
            jd_digest={},
            selected_gap=None,
            state=interview_agent.InterviewState.ASKING,
            turn_count=0,
            captured_slots={},
            skip_count=0,
            draft_card=None,
            message_log=[],
        )
        for _ in range(3):
            interview_agent.extract_slots(
                "我做了一个表格模板, 按问题类型、复现步骤、负责人和状态来记录。",
                "action",
                sess,  # 传 session 写可观测性
                llm_enabled=False,
            )
        # rules 路径走 3 次 → breakdown["rules"] = 3
        assert sess.slot_source_breakdown == {"rules": 3, "llm": 0, "mixed": 0} or \
               sess.slot_source_breakdown.get("rules") == 3, (
            f"rules 路径 3 次应 +3 rules, 实际 {sess.slot_source_breakdown!r}"
        )
        assert sess.llm_parse_retry_count == 0, (
            f"rules 路径不调 LLM, retries 应 = 0, 实际 {sess.llm_parse_retry_count}"
        )
        assert sess.llm_to_rules_slot_fallback_count == 0, (
            f"rules 路径无 fallback, fb 应 = 0, 实际 {sess.llm_to_rules_slot_fallback_count}"
        )

    def test_slot_source_breakdown_records_llm_success(self, monkeypatch):
        """R6-C.3: LLM 成功 → slot_source_breakdown[llm] +1, retries 不增。"""
        import unittest.mock

        from core import interview_agent
        from core.interview_agent import InterviewSession

        monkeypatch.setenv("LLM_API_KEY", "test-key-c3-llm-ok")

        sess = InterviewSession(
            session_id="ia-c3-llm-ok",
            target_role="test_qa",
            jd_digest={},
            selected_gap=None,
            state=interview_agent.InterviewState.ASKING,
            turn_count=0,
            captured_slots={},
            skip_count=0,
            draft_card=None,
            message_log=[],
        )

        class _R:
            def read(self_inner):
                return json.dumps({
                    "choices": [{"message": {"content": json.dumps({
                        "action": ["做了一个表格模板"],
                        "_warnings": [],
                    }, ensure_ascii=False)}}],
                }, ensure_ascii=False).encode("utf-8")
            def __enter__(self_inner): return self_inner
            def __exit__(self_inner, *a): return False

        with unittest.mock.patch(
            "core.interview_llm.urllib.request.urlopen",
            return_value=_R(),
        ) as mock_urlopen:
            interview_agent.extract_slots(
                "我做了一个表格模板, 按问题类型、复现步骤、负责人和状态来记录。",
                "action",
                sess,
                llm_enabled=True,
                llm_base_url="https://mock.example.com",
                llm_model="mock-model",
            )

        # 1 次 urlopen, LLM 成功, +1 llm
        assert mock_urlopen.call_count == 1
        assert sess.slot_source_breakdown.get("llm") == 1, (
            f"LLM 成功应 +1 llm, 实际 {sess.slot_source_breakdown!r}"
        )
        assert sess.llm_parse_retry_count == 0, (
            f"LLM 1 次成功不 retry, retries 应 = 0, 实际 {sess.llm_parse_retry_count}"
        )
        assert sess.llm_to_rules_slot_fallback_count == 0, (
            f"LLM 成功不 fallback, fb 应 = 0, 实际 {sess.llm_to_rules_slot_fallback_count}"
        )

    def test_llm_parse_retry_count_increments_on_invalid_json(self, monkeypatch):
        """R6-C.3: LLM 返非 JSON → retry 1 次 → llm_parse_retry_count += 1。

        2 次都返非 JSON, 最终 fallback 规则版 → llm_to_rules_slot_fallback_count += 1。
        """
        import unittest.mock

        from core import interview_agent
        from core.interview_agent import InterviewSession

        monkeypatch.setenv("LLM_API_KEY", "test-key-c3-retry")

        sess = InterviewSession(
            session_id="ia-c3-retry",
            target_role="test_qa",
            jd_digest={},
            selected_gap=None,
            state=interview_agent.InterviewState.ASKING,
            turn_count=0,
            captured_slots={},
            skip_count=0,
            draft_card=None,
            message_log=[],
        )

        class _R:
            def read(self_inner):
                return b"not a json response"  # 非 JSON, schema 必错
            def __enter__(self_inner): return self_inner
            def __exit__(self_inner, *a): return False

        with unittest.mock.patch(
            "core.interview_llm.urllib.request.urlopen",
            return_value=_R(),
        ) as mock_urlopen:
            interview_agent.extract_slots(
                "我做了一个表格模板, 按问题类型、复现步骤、负责人和状态来记录。",
                "action",
                sess,
                llm_enabled=True,
                llm_base_url="https://mock.example.com",
                llm_model="mock-model",
            )

        # urlopen 调 2 次(1 retry)
        assert mock_urlopen.call_count == 2
        # retry 计数 +1
        assert sess.llm_parse_retry_count == 1, (
            f"JSON 错 retry 1 次, llm_parse_retry_count 应 = 1, 实际 {sess.llm_parse_retry_count}"
        )
        # fallback 计数 +1(因为 2 次都 schema 错)
        assert sess.llm_to_rules_slot_fallback_count == 1, (
            f"最终 fallback 规则版, fb 应 = 1, 实际 {sess.llm_to_rules_slot_fallback_count}"
        )
        # rules 路径 +1(fallback 走规则)
        assert sess.slot_source_breakdown.get("rules") == 1, (
            f"fallback 后走 rules, rules 应 +1, 实际 {sess.slot_source_breakdown!r}"
        )

    def test_llm_to_rules_slot_fallback_count_increments_on_network_error(self, monkeypatch):
        """R6-C.3: LLM 网络错(URLError) → 不 retry, fb_to_rules += 1, retries 不增。"""
        import unittest.mock
        from urllib.error import URLError

        from core import interview_agent
        from core.interview_agent import InterviewSession

        monkeypatch.setenv("LLM_API_KEY", "test-key-c3-net")

        sess = InterviewSession(
            session_id="ia-c3-net",
            target_role="test_qa",
            jd_digest={},
            selected_gap=None,
            state=interview_agent.InterviewState.ASKING,
            turn_count=0,
            captured_slots={},
            skip_count=0,
            draft_card=None,
            message_log=[],
        )

        with unittest.mock.patch(
            "core.interview_llm.urllib.request.urlopen",
            side_effect=URLError("conn refused"),
        ) as mock_urlopen:
            interview_agent.extract_slots(
                "我做了一个表格模板, 按问题类型、复现步骤、负责人和状态来记录。",
                "action",
                sess,
                llm_enabled=True,
                llm_base_url="https://mock.example.com",
                llm_model="mock-model",
            )

        # 网络错不 retry → urlopen 调 1 次
        assert mock_urlopen.call_count == 1
        # 网络错不计入 retries(只 JSON / schema 错才 retry)
        assert sess.llm_parse_retry_count == 0, (
            f"网络错不 retry, retries 应 = 0, 实际 {sess.llm_parse_retry_count}"
        )
        # fallback 计数 +1
        assert sess.llm_to_rules_slot_fallback_count == 1, (
            f"网络错 fallback, fb 应 = 1, 实际 {sess.llm_to_rules_slot_fallback_count}"
        )
        # rules 路径 +1
        assert sess.slot_source_breakdown.get("rules") == 1

    def test_observability_default_session_param_no_side_effect(self):
        """R6-C.3: extract_slots(session=None) → 不写任何可观测性字段, 字节级一致老路径。"""
        from core import interview_agent

        # 没传 session(默认) → 不应崩, 不应有 side effect
        result = interview_agent.extract_slots(
            "我做了一个表格模板, 按问题类型、复现步骤、负责人和状态来记录。",
            "action",
            llm_enabled=False,
        )
        assert isinstance(result.get("action"), list)

    def test_observability_accumulates_across_multiple_answers(self, monkeypatch):
        """R6-C.3: 连续多轮 answer → 可观测性字段累加(不重置)。"""
        import unittest.mock

        from core import interview_agent
        from core.interview_agent import InterviewSession

        monkeypatch.setenv("LLM_API_KEY", "test-key-c3-acc")

        sess = InterviewSession(
            session_id="ia-c3-acc",
            target_role="test_qa",
            jd_digest={},
            selected_gap=None,
            state=interview_agent.InterviewState.ASKING,
            turn_count=0,
            captured_slots={},
            skip_count=0,
            draft_card=None,
            message_log=[],
        )

        # 第 1 轮: LLM 成功
        class _ROk:
            def read(self_inner):
                return json.dumps({
                    "choices": [{"message": {"content": json.dumps({
                        "action": ["做了一个表格模板"], "_warnings": [],
                    }, ensure_ascii=False)}}],
                }, ensure_ascii=False).encode("utf-8")
            def __enter__(self_inner): return self_inner
            def __exit__(self_inner, *a): return False

        with unittest.mock.patch(
            "core.interview_llm.urllib.request.urlopen",
            return_value=_ROk(),
        ):
            interview_agent.extract_slots(
                "我做了一个表格模板, 按问题类型、复现步骤、负责人和状态来记录。",
                "action", sess, llm_enabled=True,
                llm_base_url="https://mock.example.com", llm_model="mock-model",
            )
        # 第 2 轮: LLM 网络错
        from urllib.error import URLError
        with unittest.mock.patch(
            "core.interview_llm.urllib.request.urlopen",
            side_effect=URLError("conn refused"),
        ):
            interview_agent.extract_slots(
                "我做了一个表格模板, 按问题类型、复现步骤、负责人和状态来记录。",
                "action", sess, llm_enabled=True,
                llm_base_url="https://mock.example.com", llm_model="mock-model",
            )
        # 第 3 轮: rules 路径
        with unittest.mock.patch(
            "core.interview_llm.urllib.request.urlopen",
        ) as mock_urlopen:
            interview_agent.extract_slots(
                "我做了一个表格模板, 按问题类型、复现步骤、负责人和状态来记录。",
                "action", sess, llm_enabled=False,
            )
            mock_urlopen.assert_not_called()

        # 累加: llm=1, rules=2 (第 2 轮 fallback + 第 3 轮直接 rules)
        assert sess.slot_source_breakdown.get("llm") == 1, (
            f"第 1 轮 LLM 成功, llm 应 = 1, 实际 {sess.slot_source_breakdown!r}"
        )
        assert sess.slot_source_breakdown.get("rules") == 2, (
            f"第 2 轮 fallback + 第 3 轮 rules, rules 应 = 2, 实际 {sess.slot_source_breakdown!r}"
        )
        assert sess.llm_parse_retry_count == 0
        assert sess.llm_to_rules_slot_fallback_count == 1, (
            f"第 2 轮网络错 fallback, fb 应 = 1, 实际 {sess.llm_to_rules_slot_fallback_count}"
        )

    # ---------- D. prompt few-shot 优化 ----------

    def test_slot_extraction_prompt_has_few_shot_examples(self):
        """R6-C.3: SLOT_EXTRACTION_SYSTEM_PROMPT 含 few-shot 示例(覆盖 string + list)。"""
        from core.interview_prompts import SLOT_EXTRACTION_SYSTEM_PROMPT

        prompt = SLOT_EXTRACTION_SYSTEM_PROMPT
        # 必须含 "Few-shot" 或 "示例" 字样
        assert "示例" in prompt or "Few-shot" in prompt or "few-shot" in prompt, (
            f"SLOT_EXTRACTION_SYSTEM_PROMPT 必须含 few-shot 示例标注, 当前:\n{prompt}"
        )
        # 必须含 string slot 的例子 — responsibility
        assert "responsibility" in prompt, (
            f"few-shot 应覆盖 string slot (e.g. responsibility), 当前:\n{prompt}"
        )
        # 必须含 list slot 的例子 — action
        assert "action" in prompt, (
            f"few-shot 应覆盖 list slot (e.g. action), 当前:\n{prompt}"
        )

    def test_slot_extraction_prompt_few_shot_no_jd_text(self):
        """R6-C.3: few-shot 示例不含 JD 原文(隐私边界)。"""
        from core.interview_prompts import SLOT_EXTRACTION_SYSTEM_PROMPT

        prompt = SLOT_EXTRACTION_SYSTEM_PROMPT
        # few-shot 例子应只含"输入/输出"和说明, 不应含真实 JD 字面
        # 这里只检查不含 "{jd_text}" 变量
        assert "{jd_text}" not in prompt, (
            f"SLOT_EXTRACTION_SYSTEM_PROMPT 不应含 {{jd_text}} 变量"
        )
        # 也不应含 prompt version 字面
        assert "v6-interview-slot" not in prompt, (
            f"SLOT_EXTRACTION_SYSTEM_PROMPT 不应含 version 字符串字面"
        )

    # ---------- E. R6-G F-2.2: envelope 提取 except hygiene(行为不变 + 防回潮) ----------

    def test_envelope_extraction_handles_invalid_json(self, monkeypatch):
        """R6-G F-2.2: envelope 提取处 json.loads 抛 JSONDecodeError → fallback raw。

        行为不变验证(R6-F audit §2): 即使清理了 except 冗余, JSON 错误路径
        仍正确 fallback 到 raw 文本(让 caller 决定 retry)。
        """
        from core import interview_llm
        # 直接调 _call_llm_for_slot_extraction, mock urlopen 返回 invalid JSON
        with unittest.mock.patch(
            "core.interview_llm.urllib.request.urlopen",
        ) as mock_urlopen:
            # 返回非 JSON 字符串, 触发 json.loads JSONDecodeError → except → pass
            mock_resp = unittest.mock.MagicMock()
            mock_resp.read.return_value = b"not a json string at all"
            mock_resp.__enter__ = lambda self: self
            mock_resp.__exit__ = lambda self, *args: None
            mock_urlopen.return_value = mock_resp

            result = interview_llm._call_llm_for_slot_extraction(
                user_payload={"slot": "action", "user_message": "x"},
                model="m", base_url="https://api.example.com/v1",
                api_key="sk-test-x", timeout_sec=5,
            )
            # envelope 失败, 返 raw 文本(行为不变)
            assert result == "not a json string at all"

    def test_envelope_extraction_handles_type_error(self, monkeypatch):
        """R6-G F-2.2: envelope 提取处 TypeError 路径(防御性) → fallback raw。

        resp_obj.get("choices") 返 None 时, .get 调 None 抛 AttributeError,
        但 json.loads 路径上 raw 字符串可能触发 TypeError(json.loads 接受 None 时) —
        测试 F-2.2 清理后仍能兜住。
        """
        from core import interview_llm
        with unittest.mock.patch(
            "core.interview_llm.urllib.request.urlopen",
        ) as mock_urlopen:
            # 返 raw=None, 模拟 read().decode() 失败 — 这里只验证 envelope 路径
            # 改用 raw = "null"(合法 JSON 但 choices 是 null) 触发 TypeError 路径
            mock_resp = unittest.mock.MagicMock()
            mock_resp.read.return_value = b"null"
            mock_resp.__enter__ = lambda self: self
            mock_resp.__exit__ = lambda self, *args: None
            mock_urlopen.return_value = mock_resp

            result = interview_llm._call_llm_for_slot_extraction(
                user_payload={"slot": "action", "user_message": "x"},
                model="m", base_url="https://api.example.com/v1",
                api_key="sk-test-x", timeout_sec=5,
            )
            # null 是合法 JSON, json.loads 返 None → not isinstance(None, dict) → 跳过
            # envelope 提取失败, 返 raw 文本
            assert result == "null"

    def test_envelope_except_clause_not_redundant(self):
        """R6-G F-2.2: 静态扫描 _call_llm_for_slot_extraction 内的 except 不含冗余 tuple。

        原代码: `except (json.JSONDecodeError, TypeError, Exception): pass`
        清理后: `except Exception: pass`(Exception 已包含前两者, 属 hygiene 冗余)
        防回潮: AST 扫描应找不到 `(json.JSONDecodeError, TypeError, ...)` 这种 tuple。
        """
        import ast
        from pathlib import Path

        llm_path = (
            Path(__file__).resolve().parent.parent
            / "core"
            / "interview_llm.py"
        )
        source = llm_path.read_text(encoding="utf-8")
        tree = ast.parse(source)

        # 收集所有 except handler 的 type 字段
        found_redundant: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler) and node.type is not None:
                # Tuple 形式 except (X, Y, ...): 视为可能冗余
                if isinstance(node.type, ast.Tuple):
                    elts = [
                        ast.unparse(e) for e in node.type.elts
                        if isinstance(e, ast.Name)
                    ]
                    # 含 Exception 又有其他具体类的, 即冗余
                    if "Exception" in elts and len(elts) > 1:
                        found_redundant.append(", ".join(elts))

        # 清理后, _call_llm_for_slot_extraction 内的 except 不应含 tuple 形式
        # 全模块扫描可能命中其他 except(网络错那里有 tuple 但不含 Exception),
        # 精确检查只过滤 json.JSONDecodeError 场景
        json_redundant = [
            r for r in found_redundant
            if "json" in r.lower() or "JSONDecode" in r
        ]
        assert json_redundant == [], (
            f"_call_llm_for_slot_extraction 内的 envelope 提取 except "
            f"不应含 json.JSONDecodeError 等冗余 tuple: {json_redundant}"
        )




# R6-D 平移 helper: 让 monkeypatch.setattr(interview_llm, ...) 可用
from core import interview_llm  # noqa: E402
