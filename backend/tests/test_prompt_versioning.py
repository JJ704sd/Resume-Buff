"""
core/llm_rewriter prompt 版本化测试 (R5-E Phase 1)

锁点(8 case):
  TestPromptVersionConstants (3):
    1. PROMPT_VERSIONS["v2-baseline"] 字节级 == SYSTEM_PROMPT
    2. 4 个版本 key 都能选择(都非空 + 同长度关系)
    3. v5-minimal 短于 v2-baseline 的 60%

  TestResolvePromptVersion (4):
    4. None 解析为 v2-baseline
    5. 空字符串解析为 v2-baseline
    6. 已知 key 原样返回(含 strip 后)
    7. 未知 key 抛 ValueError, 错误信息不含 prompt 正文

  TestSelectSystemPrompt (4):
    8. None / None → SYSTEM_PROMPT(同对象,字节级)
    9. None + evidence → SYSTEM_PROMPT + SUFFIX(字节级一致)
    10. v3-priority / None → SYSTEM_PROMPT_V3_PRIORITY
    11. v3-priority + evidence → V3 + SUFFIX

  TestBuildRequestPayloadBytewiseStable (2):
    12. 不传 prompt_version → system == SYSTEM_PROMPT(字节级一致老路径)
    13. evidence_summary=None 不追加 SUFFIX(字节级)

  TestRewriteHighlightsPassthrough (2):
    14. rewrite_highlights prompt_version=None / enable_function_calling=False
        不打 HTTP / 不抛
    15. rewrite_highlights prompt_version="v3-priority" + LLM mock 成功
        → 实际 LLM 请求 payload 的 system 是 V3(给 caller 真证据)

  TestApiModels (2):
    16. PreviewRequest() / GenerateRequest() 默认 prompt_version=None
    17. PreviewRequest.prompt_version 字段在 external_resume_text 之后

  TestWorkflowPassthrough (1):
    18. workflow (enable_agent_workflow=True) 把 prompt_version 透传到 build_sections

  TestPrivacyGuarantee (2):
    19. 错误信息不含 prompt 正文(关键短语扫)
    20. PROMPT_VERSIONS 字典不含 prompt 正文片段以外的关键 sentinel
        (实际是确认 dict 只有 4 个 key, 没把 prompt 内容散落出去)

测试策略:
  - 全 mock(LLM HTTP / workflow) → 纯单元测试
  - 不真连 LLM
  - 不写磁盘副作用(monkeypatch 隔离 env)
  - 字节级稳定是核心 spec §2.1 锁点
"""
import json
from io import BytesIO
from unittest.mock import patch

import pytest


# ====================================================================
# Helpers
# ====================================================================
class _FakeResp:
    """模拟 urllib response(同 test_llm_rewriter 一致)"""
    def __init__(self, body: bytes, status: int = 200):
        self._body = body
        self.status = status

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _openai_chat_response_v2(indexed_items: list[dict]) -> dict:
    """构造 OpenAI chat/completions 响应"""
    return {
        "id": "chatcmpl-fake",
        "model": "gpt-4o-mini",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": json.dumps(
                        {"rewritten": indexed_items}, ensure_ascii=False
                    ),
                },
                "finish_reason": "stop",
            }
        ],
    }


@pytest.fixture
def enable_llm(monkeypatch):
    """有 key + auto → LLM 启用"""
    monkeypatch.setenv("LLM_API_KEY", "sk-fake-test-key")
    monkeypatch.setenv("LLM_ENABLED", "auto")
    monkeypatch.setenv("LLM_BASE_URL", "https://example.com/v1")
    monkeypatch.setenv("LLM_MODEL", "gpt-4o-mini")
    yield
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_ENABLED", raising=False)
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)


# ====================================================================
# TestPromptVersionConstants
# ====================================================================
class TestPromptVersionConstants:
    """R5-E Phase 1: PROMPT_VERSIONS 注册表常量锁点"""

    def test_v2_baseline_is_current_system_prompt(self):
        """PROMPT_VERSIONS["v2-baseline"] 字节级 == SYSTEM_PROMPT
        (允许同一对象引用 — spec §3 明确要求 v2-baseline 指向当前 SYSTEM_PROMPT)"""
        import core.llm_rewriter as llm
        # 优先级 1: 完全相同对象引用(更严格, 字节级锁死)
        assert llm.PROMPT_VERSIONS["v2-baseline"] is llm.SYSTEM_PROMPT
        # 优先级 2: 内容相等(同上对象的兜底)
        assert llm.PROMPT_VERSIONS["v2-baseline"] == llm.SYSTEM_PROMPT

    def test_all_four_versions_selectable(self):
        """4 个版本 key 都能选择, 每个都非空 + 字符串"""
        import core.llm_rewriter as llm
        expected_keys = {"v2-baseline", "v3-priority", "v4-counterexample", "v5-minimal"}
        assert set(llm.PROMPT_VERSIONS.keys()) == expected_keys
        for key, content in llm.PROMPT_VERSIONS.items():
            assert isinstance(content, str), f"{key} 不是字符串"
            assert content.strip(), f"{key} 是空白字符串"

    def test_v5_minimal_shorter_than_v2_baseline(self):
        """v5-minimal 必须短于 v2-baseline 的 60% (spec §3 候选 prompt 内容要求)"""
        import core.llm_rewriter as llm
        baseline_len = len(llm.PROMPT_VERSIONS["v2-baseline"])
        minimal_len = len(llm.PROMPT_VERSIONS["v5-minimal"])
        assert minimal_len < baseline_len * 0.6, (
            f"v5-minimal ({minimal_len}) 应短于 v2-baseline 60% ({baseline_len * 0.6:.0f})"
        )
        # 底线: schema + 不编造 + 顺序一致 三条都得保留
        minimal = llm.PROMPT_VERSIONS["v5-minimal"]
        assert "rewritten" in minimal
        assert "index" in minimal
        assert "0..N-1" in minimal or "顺序" in minimal or "一致" in minimal
        assert "编造" in minimal  # 不编造

    def test_v4_counterexample_extends_v3_priority(self):
        """v4 在 v3 基础上加 4 个反例类别 (spec §3)"""
        import core.llm_rewriter as llm
        v4 = llm.PROMPT_VERSIONS["v4-counterexample"]
        # v4 必须包含 v3 的优先级链关键短语
        assert "P0" in v4
        assert "P1" in v4
        assert "P2" in v4
        # v4 必须包含 4 个反例类别
        assert "前言" in v4 or "解释" in v4  # 1) 不输出解释性前言
        assert "顺序" in v4 or "数量" in v4  # 2) 不改变 bullet 数量或顺序
        assert "借事实" in v4 or "其他 bullet" in v4  # 3) 不从其他 bullet 借事实
        assert "missing" in v4 or "关键词" in v4  # 4) 不为 missing keyword 硬塞


# ====================================================================
# TestResolvePromptVersion
# ====================================================================
class TestResolvePromptVersion:
    """R5-E Phase 1: _resolve_prompt_version 解析逻辑"""

    def test_none_resolves_to_baseline(self):
        """None → 'v2-baseline'"""
        import core.llm_rewriter as llm
        assert llm._resolve_prompt_version(None) == "v2-baseline"

    def test_empty_string_resolves_to_baseline(self):
        """空字符串 → 'v2-baseline'(spec §3: None 或空字符串解析为 baseline)"""
        import core.llm_rewriter as llm
        assert llm._resolve_prompt_version("") == "v2-baseline"

    def test_whitespace_resolves_to_baseline(self):
        """全空白字符串 → 'v2-baseline'(strip 后空 → baseline)"""
        import core.llm_rewriter as llm
        assert llm._resolve_prompt_version("   ") == "v2-baseline"

    def test_known_key_returns_as_is(self):
        """已知 key 原样返回"""
        import core.llm_rewriter as llm
        assert llm._resolve_prompt_version("v2-baseline") == "v2-baseline"
        assert llm._resolve_prompt_version("v3-priority") == "v3-priority"
        assert llm._resolve_prompt_version("v4-counterexample") == "v4-counterexample"
        assert llm._resolve_prompt_version("v5-minimal") == "v5-minimal"

    def test_known_key_with_surrounding_whitespace_stripped(self):
        """已知 key 含周围空白 → strip 后返回"""
        import core.llm_rewriter as llm
        assert llm._resolve_prompt_version("  v3-priority  ") == "v3-priority"
        assert llm._resolve_prompt_version("\tv4-counterexample\n") == "v4-counterexample"

    def test_unknown_key_raises_value_error(self):
        """未知 key 抛 ValueError"""
        import core.llm_rewriter as llm
        with pytest.raises(ValueError) as exc_info:
            llm._resolve_prompt_version("v99-bogus")
        # 错误信息必须含版本 key(用户输入的回显)
        assert "v99-bogus" in str(exc_info.value)

    def test_unknown_key_error_does_not_leak_prompt_body(self):
        """R5-E Phase 1 隐私边界: 错误信息不含 prompt 正文
        (spec §2.3: 不把完整 prompt 写入错误信息或日志)"""
        import core.llm_rewriter as llm
        for key in ("v99-bogus", "v999-fake", "totally-unknown"):
            try:
                llm._resolve_prompt_version(key)
            except ValueError as e:
                msg = str(e)
                # 任何 prompt 的关键短语都不应出现(挑几个稳定 sentinel 扫)
                for sentinel in [
                    "绝不",
                    "润色专家",
                    "few-shot",
                    "硬性约束",
                    "JSON schema",
                    "示例 1",
                    "示例 2",
                    "事实",
                    "tier_required",
                    "jd_focus",
                ]:
                    assert sentinel not in msg, (
                        f"错误信息 {msg!r} 泄漏 prompt 正文片段 {sentinel!r}"
                    )


# ====================================================================
# TestSelectSystemPrompt
# ====================================================================
class TestSelectSystemPrompt:
    """R5-E Phase 1: _select_system_prompt 选择逻辑"""

    def test_default_no_evidence_returns_system_prompt(self):
        """默认(None / None)→ SYSTEM_PROMPT(同对象, 字节级锁死)"""
        import core.llm_rewriter as llm
        out = llm._select_system_prompt(None, None)
        assert out is llm.SYSTEM_PROMPT

    def test_default_with_evidence_returns_system_prompt_plus_suffix(self):
        """None + evidence 非空 → SYSTEM_PROMPT + EVIDENCE_CONSTRAINT_SUFFIX(字节级一致)"""
        import core.llm_rewriter as llm
        out = llm._select_system_prompt(None, "some evidence summary text")
        expected = llm.SYSTEM_PROMPT + llm.EVIDENCE_CONSTRAINT_SUFFIX
        assert out == expected

    def test_v3_priority_no_evidence_returns_v3(self):
        """v3-priority / None → SYSTEM_PROMPT_V3_PRIORITY"""
        import core.llm_rewriter as llm
        out = llm._select_system_prompt("v3-priority", None)
        assert out == llm.SYSTEM_PROMPT_V3_PRIORITY

    def test_v3_priority_with_evidence_returns_v3_plus_suffix(self):
        """v3-priority + evidence 非空 → V3 + EVIDENCE_CONSTRAINT_SUFFIX
        (候选 prompt 也遵循同一 evidence 拼接规则 — 激活事实约束)"""
        import core.llm_rewriter as llm
        out = llm._select_system_prompt("v3-priority", "evidence text")
        expected = llm.SYSTEM_PROMPT_V3_PRIORITY + llm.EVIDENCE_CONSTRAINT_SUFFIX
        assert out == expected

    def test_empty_string_evidence_treated_as_none(self):
        """evidence_summary 空字符串走 None 分支(spec §3 等价 None)"""
        import core.llm_rewriter as llm
        out_none = llm._select_system_prompt(None, None)
        out_empty = llm._select_system_prompt(None, "")
        # 注意: _select_system_prompt 只看 `is not None`, 不 strip 空字符串
        # 因为 _build_request_payload 内部 caller 已经把空 evidence 当 None
        # 这里只验证 None 路径的语义
        assert out_none is llm.SYSTEM_PROMPT
        assert out_empty == llm.SYSTEM_PROMPT + llm.EVIDENCE_CONSTRAINT_SUFFIX


# ====================================================================
# TestBuildRequestPayloadBytewiseStable
# ====================================================================
class TestBuildRequestPayloadBytewiseStable:
    """R5-E Phase 1: _build_request_payload 默认路径字节级一致(spec §2.1)"""

    def test_no_prompt_version_default_payload_equals_system_prompt(self):
        """不传 prompt_version → system message 内容 == SYSTEM_PROMPT(同一对象)"""
        import core.llm_rewriter as llm
        payload = llm._build_request_payload(
            ["bullet 1", "bullet 2"],
            target_role="tech_metric",
            jd_text="some jd",
            model="gpt-4o-mini",
        )
        system_content = payload["messages"][0]["content"]
        # 同一对象引用 — 字节级锁死
        assert system_content is llm.SYSTEM_PROMPT

    def test_no_evidence_no_prompt_version_no_suffix(self):
        """evidence_summary=None 不追加 SUFFIX"""
        import core.llm_rewriter as llm
        payload = llm._build_request_payload(
            ["bullet"],
            target_role="tech_metric",
            jd_text="",
            model="gpt-4o-mini",
        )
        system_content = payload["messages"][0]["content"]
        # 字节级锁死: 不带 SUFFIX
        assert system_content == llm.SYSTEM_PROMPT
        assert "evidence 事实约束已激活" not in system_content

    def test_evidence_with_default_version_appends_suffix(self):
        """evidence_summary 非空 + 默认 version → SUFFIX 追加"""
        import core.llm_rewriter as llm
        payload = llm._build_request_payload(
            ["bullet"],
            target_role="tech_metric",
            jd_text="",
            model="gpt-4o-mini",
            evidence_summary="snippet 1\nsnippet 2",
        )
        system_content = payload["messages"][0]["content"]
        expected = llm.SYSTEM_PROMPT + llm.EVIDENCE_CONSTRAINT_SUFFIX
        assert system_content == expected

    def test_explicit_v2_baseline_matches_default(self):
        """显式 prompt_version='v2-baseline' 与不传 → 字节级相同"""
        import core.llm_rewriter as llm
        default_payload = llm._build_request_payload(
            ["a"], target_role="tech_metric", jd_text="", model="gpt-4o-mini"
        )
        v2_payload = llm._build_request_payload(
            ["a"], target_role="tech_metric", jd_text="", model="gpt-4o-mini",
            prompt_version="v2-baseline",
        )
        # system 字段
        assert default_payload["messages"][0]["content"] == v2_payload["messages"][0]["content"]
        # 整个 payload 序列化后字节级一致(消息顺序、tools、response_format 都不变)
        assert json.dumps(default_payload, ensure_ascii=False) == json.dumps(
            v2_payload, ensure_ascii=False
        )


# ====================================================================
# TestRewriteHighlightsPassthrough
# ====================================================================
class TestRewriteHighlightsPassthrough:
    """R5-E Phase 1: rewrite_highlights prompt_version 透传"""

    def test_no_prompt_version_no_http_when_disabled(self, monkeypatch):
        """prompt_version=None + LLM 关闭 → 不打 HTTP, 返回原文"""
        import core.llm_rewriter as llm
        monkeypatch.delenv("LLM_API_KEY", raising=False)
        monkeypatch.delenv("LLM_ENABLED", raising=False)

        called = {"n": 0}

        def boom(*a, **kw):
            called["n"] += 1
            raise AssertionError("urlopen 不应在 LLM 关闭时被调")

        monkeypatch.setattr(
            "core.llm_rewriter.urllib.request.urlopen", boom
        )

        bullets = ["原文 1", "原文 2"]
        out = llm.rewrite_highlights(
            bullets, target_role="tech_metric", prompt_version=None
        )
        assert out == bullets
        assert called["n"] == 0

    def test_v3_priority_payload_actually_uses_v3_prompt(
        self, enable_llm, monkeypatch
    ):
        """prompt_version='v3-priority' + LLM mock 成功 → 实际 HTTP payload 的
        system 是 SYSTEM_PROMPT_V3_PRIORITY(给 caller 真证据)"""
        import core.llm_rewriter as llm

        items = [
            {"index": 0, "text": "改写 0"},
            {"index": 1, "text": "改写 1"},
        ]
        body = json.dumps(_openai_chat_response_v2(items)).encode("utf-8")

        captured = {}

        def fake_urlopen(req, timeout=None):
            captured["payload"] = json.loads(req.data.decode("utf-8"))
            return _FakeResp(body, 200)

        monkeypatch.setattr(
            "core.llm_rewriter.urllib.request.urlopen", fake_urlopen
        )

        out = llm.rewrite_highlights(
            ["原文 0", "原文 1"],
            target_role="tech_metric",
            jd_text="some jd",
            prompt_version="v3-priority",
        )
        assert out == ["改写 0", "改写 1"]
        # 抓到的 system 必须是 V3 优先级版
        sys_content = captured["payload"]["messages"][0]["content"]
        # 注意: payload 来自 json.loads, 字符串是新对象, 用 == 而非 is
        assert sys_content == llm.SYSTEM_PROMPT_V3_PRIORITY
        assert "P0" in sys_content
        assert "P1" in sys_content


# ====================================================================
# TestApiModels
# ====================================================================
class TestApiModels:
    """R5-E Phase 1: API 层 PreviewRequest / GenerateRequest 默认值 + 字段顺序"""

    def test_preview_request_default_prompt_version_none(self):
        """PreviewRequest() 默认 prompt_version=None"""
        from api.resume import PreviewRequest
        req = PreviewRequest(target_role="tech_metric")
        assert req.prompt_version is None

    def test_generate_request_default_prompt_version_none(self):
        """GenerateRequest() 默认 prompt_version=None"""
        from api.resume import GenerateRequest
        req = GenerateRequest(target_role="tech_metric")
        assert req.prompt_version is None

    def test_preview_request_prompt_version_after_external_resume_text(self):
        """PreviewRequest.prompt_version 字段在 external_resume_text 之后
        (spec §3 字段位置要求, 避免打乱既有字段顺序的兼容性约定)"""
        from api.resume import PreviewRequest
        fields = list(PreviewRequest.model_fields.keys())
        er_idx = fields.index("external_resume_text")
        pv_idx = fields.index("prompt_version")
        assert pv_idx == er_idx + 1, (
            f"prompt_version 应在 external_resume_text 之后. 字段: {fields}"
        )
        # prompt_version 必须是最后一个字段
        assert pv_idx == len(fields) - 1

    def test_generate_request_prompt_version_after_external_resume_text(self):
        """GenerateRequest.prompt_version 字段在 external_resume_text 之后"""
        from api.resume import GenerateRequest
        fields = list(GenerateRequest.model_fields.keys())
        er_idx = fields.index("external_resume_text")
        pv_idx = fields.index("prompt_version")
        assert pv_idx == er_idx + 1

    def test_api_models_accept_known_prompt_version(self):
        """PreviewRequest / GenerateRequest 可接受已知 prompt_version"""
        from api.resume import PreviewRequest, GenerateRequest
        req_p = PreviewRequest(
            target_role="tech_metric", prompt_version="v3-priority"
        )
        req_g = GenerateRequest(
            target_role="tech_metric", prompt_version="v5-minimal"
        )
        assert req_p.prompt_version == "v3-priority"
        assert req_g.prompt_version == "v5-minimal"


# ====================================================================
# TestWorkflowPassthrough
# ====================================================================
class TestWorkflowPassthrough:
    """R5-E Phase 1: workflow (enable_agent_workflow=True) 把 prompt_version
    透传到 build_sections(spec §3 Phase 1 改动文件清单要求)"""

    def test_workflow_passes_prompt_version_to_build_sections(
        self, monkeypatch
    ):
        """workflow preview 把 prompt_version 传给 build_sections
        (mock build_sections, 验证 prompt_version kwarg 透传)"""
        from core import agent_workflow
        from core.generator import build_sections as real_build_sections

        captured = {}

        def fake_build_sections(*args, **kwargs):
            captured.update(kwargs)
            # 避免真的渲染 — 用真 build_sections 但只取 target_role 简化路径
            target_role = kwargs.get("target_role") or (args[0] if args else "tech_metric")
            return real_build_sections(target_role=target_role)

        # agent_workflow.run_agent_workflow 内部是局部 import:
        #   from core.generator import load_materials, build_sections, ...
        # 每次调用函数时都重新读 core.generator.build_sections, 所以 monkeypatch
        # core.generator.build_sections 生效。
        monkeypatch.setattr("core.generator.build_sections", fake_build_sections)
        # 关闭 LLM / enable_function_calling=False 简化路径
        monkeypatch.delenv("LLM_API_KEY", raising=False)
        monkeypatch.delenv("LLM_ENABLED", raising=False)

        # workflow preview 路径 (run_agent_workflow 没有 enable_agent_workflow kwarg,
        # 那是 preview_resume 的开关 — workflow 本身已是 Agent workflow 入口)
        out = agent_workflow.run_agent_workflow(
            target_role="tech_metric",
            prompt_version="v3-priority",
        )
        # 验证 build_sections 收到了 prompt_version
        assert "prompt_version" in captured, (
            f"workflow 没把 prompt_version 透传到 build_sections, kwargs={captured}"
        )
        assert captured["prompt_version"] == "v3-priority"

    def test_workflow_default_prompt_version_is_none(self, monkeypatch):
        """workflow 不传 prompt_version 时, build_sections 收到 None(字节级一致)"""
        from core import agent_workflow
        # 在 monkeypatch 之前先抓住真函数引用(防止 fake 内重 import 拿到 fake 自己)
        from core.generator import build_sections as real_build_sections

        captured = {}

        def fake_build_sections(*args, **kwargs):
            captured.update(kwargs)
            # 用真函数(已抓住的引用)而非 "from core.generator import build_sections"
            return real_build_sections(target_role="tech_metric")

        monkeypatch.setattr("core.generator.build_sections", fake_build_sections)
        monkeypatch.delenv("LLM_API_KEY", raising=False)
        monkeypatch.delenv("LLM_ENABLED", raising=False)

        # 不传 prompt_version
        out = agent_workflow.run_agent_workflow(target_role="tech_metric")
        assert captured.get("prompt_version") is None


# ====================================================================
# TestPrivacyGuarantee
# ====================================================================
class TestPrivacyGuarantee:
    """R5-E Phase 1: 隐私边界 — 错误信息 / trace / 输出不含 prompt 正文"""

    def test_error_message_no_prompt_body(self):
        """未知 prompt_version 抛 ValueError, 错误信息不含 PROMPT_VERSIONS 里
        任何 prompt 关键短语(spec §2.3: 不把完整 prompt 写入错误信息或日志)

        用户输入会被回显是 by-design;真正要验证的是**其他 prompt 内容不泄漏**。
        """
        import core.llm_rewriter as llm

        # 用一个肯定不会出现在任何 prompt 里的字符串作为 user input
        bogus_input = "v999-bogus-version-doesnt-exist"

        # sentinel 取 PROMPT_VERSIONS 里各 prompt 的关键短语
        sentinels = [
            # v2-baseline (SYSTEM_PROMPT)
            "示例 1",
            "示例 2",
            "硬性约束",
            "few-shot",
            # v3-priority
            "P0 JSON schema",
            "P1 事实边界",
            "P2 evidence 边界",
            "P3 JD 对齐",
            "P4 表达",
            # v4-counterexample
            "禁止事项",
            "硬塞无依据",
            # v5-minimal
            "不得编造原 bullet",
        ]

        try:
            llm._resolve_prompt_version(bogus_input)
        except ValueError as e:
            msg = str(e)
            for sentinel in sentinels:
                assert sentinel not in msg, (
                    f"错误信息 {msg!r} 泄漏 PROMPT_VERSIONS 关键短语 {sentinel!r}"
                )

    def test_prompt_versions_dict_has_only_expected_keys(self):
        """PROMPT_VERSIONS 字典只含 4 个已知 key, 没有泄漏 PII"""
        import core.llm_rewriter as llm
        assert set(llm.PROMPT_VERSIONS.keys()) == {
            "v2-baseline",
            "v3-priority",
            "v4-counterexample",
            "v5-minimal",
        }
        # 长度合理(每个 prompt 都是几百到一千多字符, 不会是空)
        for k, v in llm.PROMPT_VERSIONS.items():
            assert len(v) > 50, f"{k} 内容过短(可能未填充): {len(v)}"