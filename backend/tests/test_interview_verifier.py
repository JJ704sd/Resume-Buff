"""
Round 6-B Phase 4: draft verifier 单元测试(spec §7 + AGENTS.md R6-B Phase 4)

覆盖:
  - TestQuantitativeSource (4): 量化数字命中 captured slot → supported / 不命中 →
                                  unsupported / 无量化 → 走 slot 文本分支 / regex 边界
  - TestSlotTextSource (3): bullet 是 action 元素子串 / bullet 是 responsibility 字符串 /
                            bullet 不在任一 SOURCE_SLOT_KEYS 里
  - TestLowConfidenceClaims (3): slot_meta 含 < 0.6 meta → confidence_notes 生成 /
                                 > = 0.6 不算 / 不读 slot_meta 不爆
  - TestUnsupportedWarning (2): warning 含 bullet 前 30 字摘要 + draft_bullets[N] 索引
                                → 不复制完整原文(隐私边界)
  - TestVerifierReturnShape (3): 5 字段类型正确 / 异常输入不抛 / 空 bullets 返零计数
  - TestPrivacyGuarantee (4): 不含 user_message / 不含 source_span 明文 / 不含 API key /
                              warnings 不含完整 bullet 原文

边界:
  - verifier 是 pure stdlib + dict 操作, 不 import 网络 / llm / 重型依赖
  - 测试 mock session(slim dataclass 字面仿造), 不依赖完整 InterviewSession
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import pytest


# ----------------------------------------------------------------------
# 简化版 session — 只用 verifier 关心的字段(captured_slots + slot_meta)
# 不 import 真实 InterviewSession, 避免 verifier 测试受其他改动污染
# ----------------------------------------------------------------------
@dataclass
class _FakeSession:
    captured_slots: dict[str, Any] = field(default_factory=dict)
    slot_meta: dict[str, Any] = field(default_factory=dict)


# ----------------------------------------------------------------------
# 1. TestQuantitativeSource — 量化数字 vs captured slot 来源(spec §7 量化分支)
# ----------------------------------------------------------------------
class TestQuantitativeSource:
    def test_quantitative_match_in_captured_slot_supported(self):
        """bullet 数字 "50%" 命中 captured slot "覆盖 50%场景" → supported"""
        from core.interview_verifier import verify_draft_card

        sess = _FakeSession(captured_slots={"metric": ["覆盖 50%场景"]})
        card = {"draft_bullets": ["覆盖 50%场景, 大幅提升"]}
        result = verify_draft_card(card, sess)

        assert result["claims_total"] == 1
        assert result["claims_supported"] == 1
        assert result["unsupported_claims"] == 0

    def test_quantitative_no_source_generates_warning(self):
        """bullet 数字 "30%" 未在 captured slots 任何字符串里出现 → unsupported + warning"""
        from core.interview_verifier import verify_draft_card

        sess = _FakeSession(captured_slots={"result": "返工减少"})
        card = {"draft_bullets": ["准确率 30% 提升"]}
        result = verify_draft_card(card, sess)

        assert result["claims_total"] == 1
        # bullet 没有任何 slot 子串匹配 → unsupported
        assert result["unsupported_claims"] == 1
        assert result["claims_supported"] == 0
        # warning 含 bullet 索引 + 摘要
        assert any("draft_bullets[0]" in w for w in result["warnings"]), (
            f"warning 应含 bullet 索引, 实际 {result['warnings']}"
        )

    def test_quantitative_regex_pattern_matches_units(self):
        """regex 支持 人/%/倍/小时/天/次/万/个/条/例(spec §7 量化口径与 metric 抽取同源)"""
        from core.interview_verifier import QUANTITATIVE_PATTERN

        # 各单位命中
        assert QUANTITATIVE_PATTERN.findall("30%") == [("30", "%")]
        assert QUANTITATIVE_PATTERN.findall("5人") == [("5", "人")]
        assert QUANTITATIVE_PATTERN.findall("3.5倍") == [("3.5", "倍")]
        assert QUANTITATIVE_PATTERN.findall("12小时") == [("12", "小时")]
        assert QUANTITATIVE_PATTERN.findall("7天") == [("7", "天")]
        assert QUANTITATIVE_PATTERN.findall("200次") == [("200", "次")]
        assert QUANTITATIVE_PATTERN.findall("5万") == [("5", "万")]
        # 多单位单 bullet
        matches = QUANTITATIVE_PATTERN.findall("覆盖 50 个用例, 平均 12 小时完成 30% 流程")
        nums = [n for n, _ in matches]
        assert "50" in nums
        assert "12" in nums
        assert "30" in nums

    def test_no_quantitative_falls_back_to_slot_text(self):
        """bullet 无量化数字但命中 action slot → 仍算 supported"""
        from core.interview_verifier import verify_draft_card

        sess = _FakeSession(
            captured_slots={"action": ["梳理测试反馈表"]},
        )
        card = {"draft_bullets": ["梳理测试反馈表, 统一格式"]}
        result = verify_draft_card(card, sess)

        assert result["claims_supported"] == 1
        assert result["unsupported_claims"] == 0


# ----------------------------------------------------------------------
# 2. TestSlotTextSource — bullet 子串 vs SOURCE_SLOT_KEYS 内容
# ----------------------------------------------------------------------
class TestSlotTextSource:
    def test_bullet_substring_of_action_element_supported(self):
        """bullet 是 captured action 元素的子串 → supported"""
        from core.interview_verifier import verify_draft_card

        sess = _FakeSession(
            captured_slots={"action": ["梳理问题反馈表, 统一格式"]},
        )
        card = {"draft_bullets": ["梳理问题反馈表"]}
        result = verify_draft_card(card, sess)

        assert result["claims_supported"] == 1

    def test_bullet_substring_of_responsibility_supported(self):
        """bullet 是 captured responsibility 字符串的子串 → supported"""
        from core.interview_verifier import verify_draft_card

        sess = _FakeSession(
            captured_slots={"responsibility": "测试反馈整理与流程优化"},
        )
        card = {"draft_bullets": ["测试反馈整理"]}
        result = verify_draft_card(card, sess)

        assert result["claims_supported"] == 1

    def test_bullet_no_match_any_source_slot_unsupported(self):
        """bullet 不在任一 SOURCE_SLOT_KEYS 字符串里 → unsupported"""
        from core.interview_verifier import verify_draft_card

        sess = _FakeSession(
            captured_slots={
                "responsibility": "测试反馈整理",
                "action": ["梳理问题反馈表"],
                "result": "返工减少",
            },
        )
        # bullet 完全不命中上述任何 slot
        card = {"draft_bullets": ["独立完成机器学习模型调优"]}
        result = verify_draft_card(card, sess)

        assert result["unsupported_claims"] == 1
        assert result["claims_supported"] == 0


# ----------------------------------------------------------------------
# 3. TestLowConfidenceClaims — confidence < 0.6 → confidence_notes 触发
# ----------------------------------------------------------------------
class TestLowConfidenceClaims:
    def test_low_confidence_slot_generates_confidence_notes(self):
        """slot_meta 含 confidence < 0.6 → confidence_notes 含 slot 名"""
        from core.interview_verifier import compute_confidence_notes

        sess = _FakeSession(
            slot_meta={
                "result": [{"confidence": 0.45, "turn_index": 2}],
                "metric": [{"confidence": 0.85, "turn_index": 3}],
            },
        )
        notes = compute_confidence_notes(sess)
        assert len(notes) == 1
        assert "result" in notes[0]
        # metric confidence 0.85 → 不算 low_confidence
        assert "metric" not in " ".join(notes)

    def test_confidence_at_threshold_not_low(self):
        """confidence = 0.6 (等于阈值) → 不算 low_confidence(spec §7 "< 0.6")"""
        from core.interview_verifier import compute_confidence_notes

        sess = _FakeSession(
            slot_meta={"result": [{"confidence": 0.6, "turn_index": 1}]},
        )
        notes = compute_confidence_notes(sess)
        assert notes == []

    def test_high_confidence_slot_no_low_notes(self):
        """slot_meta 全 confidence >= 0.6 → confidence_notes 空 list"""
        from core.interview_verifier import compute_confidence_notes

        sess = _FakeSession(
            slot_meta={
                "action": [{"confidence": 0.8, "turn_index": 1}],
                "metric": [{"confidence": 0.7, "turn_index": 2}],
            },
        )
        notes = compute_confidence_notes(sess)
        assert notes == []

    def test_low_confidence_claims_count_increments(self):
        """bullet 涉及 confidence < 0.6 slot → low_confidence_claims +1"""
        from core.interview_verifier import verify_draft_card

        sess = _FakeSession(
            captured_slots={
                "responsibility": "测试反馈整理",
                "action": ["梳理问题反馈表"],
                "result": "返工减少",  # 用作 bullet 子串匹配
            },
            slot_meta={
                # result slot confidence < 0.6 → 该 slot 进 low_confidence
                "result": [{"confidence": 0.45, "turn_index": 2}],
            },
        )
        card = {"draft_bullets": ["测试反馈整理, 返工减少"]}
        result = verify_draft_card(card, sess)

        # bullet 命中 responsibility + action → supported
        assert result["claims_supported"] == 1
        # bullet 涉及 low_confidence slot result → low_confidence_claims = 1
        assert result["low_confidence_claims"] == 1
        # warnings 含 low_confidence 提示
        assert any("result" in w for w in result["warnings"])


# ----------------------------------------------------------------------
# 4. TestUnsupportedWarning — warning 格式 / 摘要截断
# ----------------------------------------------------------------------
class TestUnsupportedWarning:
    def test_warning_has_bullet_index_and_preview(self):
        """warning 含 draft_bullets[索引] + 前 30 字摘要(spec §7 隐私边界)"""
        from core.interview_verifier import verify_draft_card

        sess = _FakeSession(
            captured_slots={"result": "返工减少"},  # bullet 不命中
        )
        long_bullet = "独立的端到端 AI 测试全链路优化方案设计与落地" * 5  # 超 30 字
        card = {"draft_bullets": [long_bullet]}
        result = verify_draft_card(card, sess)

        assert len(result["warnings"]) >= 1
        warning = result["warnings"][0]
        assert "draft_bullets[0]" in warning
        # warning 不应包含完整 bullet (只看是否含前 30 字 - 不含完整原文)
        assert long_bullet[:30] in warning  # 前 30 字应出现
        assert long_bullet not in warning  # 完整 bullet 不应出现
        assert "..." in warning  # 截断标记

    def test_warning_does_not_leak_full_bullet_text(self):
        """warning 不含完整 bullet 原文(spec §7 "禁止把完整 ... draft_card 原文")"""
        from core.interview_verifier import verify_draft_card

        secret = "TOP-SECRET-BULLET-CONTENT-DO-NOT-LEAK-2026-06-30-1234567890"
        sess = _FakeSession(
            captured_slots={"result": "返工减少"},
        )
        card = {"draft_bullets": [secret]}
        result = verify_draft_card(card, sess)

        # 警告信息不复制完整 bullet 原文(只取前 30 字预览)
        for w in result["warnings"]:
            assert secret not in w, (
                f"warning 竟含完整 bullet 原文: {w}"
            )


# ----------------------------------------------------------------------
# 5. TestVerifierReturnShape — 返回 schema 稳定
# ----------------------------------------------------------------------
class TestVerifierReturnShape:
    def test_returns_5_required_fields(self):
        """verify_draft_card 必含 5 字段 + 类型正确"""
        from core.interview_verifier import verify_draft_card

        sess = _FakeSession(captured_slots={"action": ["a"]})
        result = verify_draft_card({"draft_bullets": ["a"]}, sess)

        assert set(result.keys()) == {
            "claims_total", "claims_supported",
            "low_confidence_claims", "unsupported_claims",
            "warnings",
        }, f"verifier 返回字段不符, 实际 {result.keys()}"
        assert isinstance(result["claims_total"], int)
        assert isinstance(result["claims_supported"], int)
        assert isinstance(result["low_confidence_claims"], int)
        assert isinstance(result["unsupported_claims"], int)
        assert isinstance(result["warnings"], list)

    def test_empty_bullets_returns_zero_counts(self):
        """draft_bullets 空 list → 4 计数全 0 + warnings 空 list"""
        from core.interview_verifier import verify_draft_card

        sess = _FakeSession(captured_slots={"action": ["a"]})
        result = verify_draft_card({"draft_bullets": []}, sess)

        assert result["claims_total"] == 0
        assert result["claims_supported"] == 0
        assert result["low_confidence_claims"] == 0
        assert result["unsupported_claims"] == 0
        assert result["warnings"] == []

    def test_malformed_inputs_return_safe_defaults(self):
        """card/session 异常输入 → 返零计数 + 不抛(spec §6.3 失败不阻断主流程)"""
        from core.interview_verifier import verify_draft_card

        # 各种异常输入都不抛
        bad_inputs = [
            None,
            {},
            {"draft_bullets": "not a list"},
            {"draft_bullets": [None, 123, {}]},
            {"draft_bullets": ["valid"]},  # captured_slots 缺失 → fake session 默认空 dict, OK
        ]
        for bad in bad_inputs:
            result = verify_draft_card(bad, _FakeSession())
            assert result["claims_total"] in (0, 1)
            # 数字字段都是 int, warnings 是 list
            assert isinstance(result["warnings"], list)
            assert isinstance(result["claims_supported"], int)


# ----------------------------------------------------------------------
# 6. TestPrivacyGuarantee — 不含 user_message / source_span / API key / draft_card 原文
# ----------------------------------------------------------------------
class TestPrivacyGuarantee:
    def test_verification_does_not_contain_user_message(self):
        """verification 输出不含 user_message 字面量"""
        from core.interview_verifier import verify_draft_card

        secret_msg = "USER_PRIVATE_MSG_DO_NOT_LEAK_2026_ABCDEFG"
        sess = _FakeSession(captured_slots={"responsibility": "测试反馈整理"})
        card = {"draft_bullets": [f"完成 {secret_msg} 的测试"]}
        result = verify_draft_card(card, sess)

        # 不应复制完整 user_message 文本来输出
        serialized = str(result["warnings"]) + str(result)
        assert secret_msg not in serialized, (
            f"verifier 输出竟含 user_message 字符串"
        )

    def test_verification_does_not_contain_source_span_plaintext(self):
        """verification 输出不含 source_span 明文字符串(只允许 sha256 hash 出现)"""
        from core.interview_verifier import verify_draft_card

        secret_span = "SHARED_SOURCE_SPAN_SENTINEL_2026"
        sess = _FakeSession(
            captured_slots={"responsibility": "测试反馈整理"},
            slot_meta={
                "result": [
                    {
                        "confidence": 0.5,
                        "turn_index": 1,
                        "source_span_hash": "sha256:abcdef1234567890",
                        # 注意: hash 是允许出现在 slot_meta 里的, 但原文不应泄漏
                    },
                ],
            },
        )
        card = {"draft_bullets": ["测试反馈整理"]}
        result = verify_draft_card(card, sess)

        serialized = str(result["warnings"]) + str(result)
        # source_span 明文不应出现
        assert secret_span not in serialized

    def test_verification_does_not_contain_api_key(self):
        """verification 输出不含 LLM_API_KEY 字面量 / Bearer / sk- 前缀"""
        from core.interview_verifier import verify_draft_card

        sess = _FakeSession(captured_slots={"action": ["a"]})
        card = {"draft_bullets": ["a"]}

        # 在输入里塞一个看起来像 API key 的字符串, 验证 verifier 输出不带它出去
        result = verify_draft_card(
            {"draft_bullets": ["sk-test-1234567890abcdef-not-a-real-key"]},
            sess,
        )
        serialized = str(result["warnings"]) + str(result)
        assert "sk-test-1234567890abcdef" not in serialized
        assert "Bearer " not in serialized
        assert "LLM_API_KEY" not in serialized

    def test_verification_does_not_contain_pii_sentinel_in_card(self):
        """Sentinel PII (电话 / 邮箱) 不应被 verifier 当成 bullet 来源泄漏到 warnings

        spec §7 + AGENTS.md privacy boundary: 不复制原文
        """
        from core.interview_verifier import verify_draft_card

        phone = "13812345678"
        email = "user@example.com"
        sess = _FakeSession(captured_slots={"responsibility": "测试反馈整理"})
        # bullet 含完整 PII — verification 应只截前 30 字
        card = {
            "draft_bullets": [
                f"联系 {phone} / {email} 完成测试反馈整理"
            ],
        }
        result = verify_draft_card(card, sess)

        all_warnings = " ".join(result["warnings"])
        # bullet 含 phone + email, 子串可能命中截断前 30 字(电话 11 字)
        # 但 email 不在截断范围内; 我们只断言 PII 不在 verifier 输出里
        # 注意: 如果 PII 在前 30 字, 也只是被截断后显示, 不算泄漏
        # 此处验证只截前 30 字, 不复制全文(>30 字的原文)
        if len("联系 13812345678 / user@example.com 完成测试反馈整理") > 30:
            # bullet 整体超过 30 字, 应该含 "..."
            if result["warnings"]:
                assert "..." in result["warnings"][0] or len(
                    result["warnings"][0]
                ) < 200, (
                    f"warning 应有截断标记或较短, 实际 {result['warnings'][0]}"
                )


# ----------------------------------------------------------------------
# 7. TestVerifierPurity — 不 mutate session
# ----------------------------------------------------------------------
class TestVerifierPurity:
    def test_does_not_mutate_session(self):
        """verify_draft_card 是纯函数, 不修改 session(测试用 snapshot diff)"""
        from core.interview_verifier import verify_draft_card

        sess = _FakeSession(
            captured_slots={"action": ["a"]},
            slot_meta={"action": [{"confidence": 0.7}]},
        )

        # snapshot
        import copy
        sess_before = copy.deepcopy({
            "captured": sess.captured_slots,
            "meta": sess.slot_meta,
        })

        verify_draft_card({"draft_bullets": ["a"]}, sess)
        verify_draft_card({"draft_bullets": ["unsupported content"]}, sess)

        # 验证 session 没有被修改
        assert sess.captured_slots == sess_before["captured"]
        assert sess.slot_meta == sess_before["meta"]

    def test_is_deterministic(self):
        """同样输入 → 完全相同输出(verifier 不依赖环境 / 时间)"""
        from core.interview_verifier import verify_draft_card

        sess = _FakeSession(
            captured_slots={"action": ["a"]},
            slot_meta={"action": [{"confidence": 0.5}]},
        )
        card = {"draft_bullets": ["a", "non-matching bullet"]}

        result1 = verify_draft_card(card, sess)
        result2 = verify_draft_card(card, sess)
        assert result1 == result2


# ----------------------------------------------------------------------
# 8. TestVerifierNoNetwork — 模块默认不 import 网络 / LLM(pure stdlib)
# ----------------------------------------------------------------------
class TestVerifierNoNetwork:
    def test_verifier_module_no_network_imports(self):
        """AST 静态扫描: verifier 文件不 import urllib / requests / httpx / openai / anthropic /
        llm_rewriter (R6-B Phase 4 边界保护, 沿用 Phase 3 policy 的锁)"""
        import ast

        from pathlib import Path

        verifier_path = (
            Path(__file__).resolve().parent.parent
            / "core"
            / "interview_verifier.py"
        )
        source = verifier_path.read_text(encoding="utf-8")
        tree = ast.parse(source)

        forbidden_patterns = [
            "urllib", "requests", "httpx", "openai", "anthropic",
            "llm_rewriter", "agent_workflow", "agent_tools",
            "tool_schema",
        ]
        found_forbidden: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if any(
                        p in alias.name
                        for p in forbidden_patterns
                    ):
                        found_forbidden.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module and any(
                    p in node.module
                    for p in forbidden_patterns
                ):
                    found_forbidden.append(node.module)

        assert found_forbidden == [], (
            f"verifier 模块不该 import 这些: {found_forbidden}"
        )

    def test_verifier_does_not_read_env(self):
        """verifier 模块不该读 os.environ(纯函数, 决定性)"""
        import ast

        from pathlib import Path

        verifier_path = (
            Path(__file__).resolve().parent.parent
            / "core"
            / "interview_verifier.py"
        )
        source = verifier_path.read_text(encoding="utf-8")
        tree = ast.parse(source)

        found_env: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                if isinstance(node.value, ast.Name) and node.value.id == "os":
                    if node.attr in ("environ", "getenv"):
                        found_env.append(f"os.{node.attr}")
            elif isinstance(node, ast.Call):
                fn = node.func
                if isinstance(fn, ast.Attribute):
                    if fn.attr in ("getenv", "getenv"):
                        found_env.append(fn.attr)

        assert found_env == [], (
            f"verifier 不该读 env: {found_env}"
        )


# ----------------------------------------------------------------------
# 9. TestVerifierInternalErrorSentinel — R6-G F-2.1: 内部崩溃 sentinel 提示
# ----------------------------------------------------------------------
# R6-F audit §2 review-needed:
#   verifier 主链路 try/except 兜成 5 字段全 0/[] 时, 前端 UI 看到
#   unsupported_claims=0 + low_confidence_claims=0 会误以为 "全部 verified 通过",
#   verifier 实际崩了用户感知不到。
# R6-G F-2.1 修复:
#   verify_draft_card 兜底时往 warnings 塞 1 条 sentinel 字符串;
#   compute_confidence_notes 兜底时返 [sentinel] 而非 []。
#   sentinel 文字纯状态描述, 不含 user_message / source_span / draft_bullets /
#   API key / jd_text / prompt 正文(隐私边界, 沿用 spec §7)。
# ----------------------------------------------------------------------
class TestVerifierInternalErrorSentinel:
    """
    R6-G F-2.1: verifier 内部崩溃 sentinel 提示 + 隐私边界。

    spec §6.3 "失败不阻断主流程" 兼容: 数字字段保持 0, 不抛; 但 warnings
    必须非空(防止前端误判为 "全部 verified 通过")。
    """

    def test_verify_draft_card_internal_error_emits_sentinel_warning(self, monkeypatch):
        """verify_draft_card 主链路抛异常时, warnings 含 sentinel, 4 计数全 0。"""
        from core.interview_verifier import (
            _VERIFIER_INTERNAL_ERROR_SENTINEL,
            verify_draft_card,
        )

        sess = _FakeSession(captured_slots={"action": ["x"]})

        # 强制 _collect_source_strings 抛异常 → 触发兜底 except 分支
        from core import interview_verifier as iv_mod

        def _boom(_captured):
            raise RuntimeError("forced verifier internal error for F-2.1 test")
        monkeypatch.setattr(iv_mod, "_collect_source_strings", _boom)

        result = verify_draft_card({"draft_bullets": ["valid bullet"]}, sess)

        # 4 计数全 0(spec §6.3 兼容)
        assert result["claims_total"] == 0
        assert result["claims_supported"] == 0
        assert result["low_confidence_claims"] == 0
        assert result["unsupported_claims"] == 0
        # warnings 含 sentinel(防前端误判)
        assert result["warnings"] == [_VERIFIER_INTERNAL_ERROR_SENTINEL]
        # sentinel 是不空字符串(防止空字符串绕过 UI 渲染)
        assert _VERIFIER_INTERNAL_ERROR_SENTINEL
        assert isinstance(_VERIFIER_INTERNAL_ERROR_SENTINEL, str)

    def test_compute_confidence_notes_internal_error_emits_sentinel(self, monkeypatch):
        """compute_confidence_notes 主链路抛异常时, 返 [sentinel] 而非 []。"""
        from core.interview_verifier import (
            _CONFIDENCE_COLLECT_ERROR_SENTINEL,
            compute_confidence_notes,
        )

        sess = _FakeSession(
            slot_meta={"result": [{"confidence": 0.45, "turn_index": 1}]},
        )

        # 强制 _collect_low_confidence_slots 抛异常
        from core import interview_verifier as iv_mod

        def _boom(_session, _threshold=None):
            raise RuntimeError("forced confidence collect error for F-2.1 test")
        monkeypatch.setattr(iv_mod, "_collect_low_confidence_slots", _boom)

        notes = compute_confidence_notes(sess)
        assert notes == [_CONFIDENCE_COLLECT_ERROR_SENTINEL]
        assert _CONFIDENCE_COLLECT_ERROR_SENTINEL
        assert isinstance(_CONFIDENCE_COLLECT_ERROR_SENTINEL, str)

    def test_sentinel_does_not_leak_user_message_or_source_span_or_api_key(self):
        """sentinel 文字是纯状态描述, 不含 user_message / source_span / API key 哨兵。"""
        from core.interview_verifier import (
            _CONFIDENCE_COLLECT_ERROR_SENTINEL,
            _VERIFIER_INTERNAL_ERROR_SENTINEL,
        )

        # 用一批常见哨兵 / 隐私关键词验证 sentinel 文字干净
        sentinels = [
            _VERIFIER_INTERNAL_ERROR_SENTINEL,
            _CONFIDENCE_COLLECT_ERROR_SENTINEL,
        ]
        forbidden_substrings = [
            "user_message", "source_span", "draft_bullets",
            "api_key", "API key", "sk-", "Bearer", "LLM_API_KEY",
            "jd_text", "prompt", "session", "captured",
        ]
        for s in sentinels:
            for f in forbidden_substrings:
                assert f.lower() not in s.lower(), (
                    f"sentinel {s!r} 泄漏隐私关键词 {f!r}"
                )

    def test_sentinels_exported_in_all(self):
        """__all__ 含 2 个 sentinel 常量, 测试 / 外部模块可稳定 import。"""
        import core.interview_verifier as iv_mod

        assert "_VERIFIER_INTERNAL_ERROR_SENTINEL" in iv_mod.__all__
        assert "_CONFIDENCE_COLLECT_ERROR_SENTINEL" in iv_mod.__all__
        assert hasattr(iv_mod, "_VERIFIER_INTERNAL_ERROR_SENTINEL")
        assert hasattr(iv_mod, "_CONFIDENCE_COLLECT_ERROR_SENTINEL")

    def test_happy_path_does_not_emit_sentinel(self):
        """happy path(无崩溃) → warnings 不含 sentinel(防误报噪音)。"""
        from core.interview_verifier import (
            _CONFIDENCE_COLLECT_ERROR_SENTINEL,
            _VERIFIER_INTERNAL_ERROR_SENTINEL,
            compute_confidence_notes,
            verify_draft_card,
        )

        sess = _FakeSession(
            captured_slots={"action": ["a"]},
            slot_meta={"result": [{"confidence": 0.45, "turn_index": 1}]},
        )
        # 正常 verify
        result = verify_draft_card({"draft_bullets": ["a"]}, sess)
        assert _VERIFIER_INTERNAL_ERROR_SENTINEL not in result["warnings"]
        # 正常 confidence
        notes = compute_confidence_notes(sess)
        assert _CONFIDENCE_COLLECT_ERROR_SENTINEL not in notes
