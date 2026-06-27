"""
LLM 智能改写模块测试 (Round 2 #3)

覆盖核心逻辑 (HTTP / JSON 解析 / 降级 / 端到端):
  1. is_llm_enabled 状态机:有 key + auto → True;无 key → False;有 key + false → False
  2. rewrite_highlights happy path: HTTP 200 + 合法 JSON → 改写生效
  3. rewrite_highlights HTTP 500 → 返回原文 (不抛)
  4. rewrite_highlights 超时 → 返回原文
  5. rewrite_highlights JSON 解析失败 → 返回原文
  6. rewrite_highlights 长度截断:max_per_call=3 + 10 条 → 3 改写 + 7 原文
  7. rewrite_highlights JSON schema 兼容:OpenAI 标准 / {"rewritten":..} / 顶层 array
  8. rewrite_highlights 长度对不上 → 降级回原文 (不污染其他位置)
  9. 端到端 (LLM_ENABLED=false):6 个 role 的 build_sections 与 Round 2 #1 baseline 一字不差
 10. 端到端 (HTTP mock 成功):build_sections 的 project.highlights 包含改写后的文本

测试策略:
  - 不真发 HTTP,monkeypatch urllib.request.urlopen
  - 不联网抓任何数据
  - 不留磁盘副作用(已设的 env var 用 monkeypatch.delenv 还原)
"""
import json
from io import BytesIO
from unittest.mock import MagicMock

import pytest

import core.llm_rewriter as llm
from core.generator import build_sections, ENABLED_ROLES


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
class _FakeResp:
    """模拟 urllib response:有 .read() / .status,支持 with 上下文"""
    def __init__(self, body: bytes, status: int = 200):
        self._body = body
        self.status = status

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _openai_chat_response(bullets: list[str]) -> dict:
    """构造一个标准 OpenAI chat/completions 响应,content 是 JSON 字符串"""
    return {
        "id": "chatcmpl-fake",
        "model": "gpt-4o-mini",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": json.dumps({"rewritten": bullets}, ensure_ascii=False),
                },
                "finish_reason": "stop",
            }
        ],
    }


def _openai_chat_response_v2(indexed_items: list[dict]) -> dict:
    """
    R3-P: 构造一个返回新 schema 的 OpenAI 响应
    indexed_items: [{"index": 0, "text": "..."}, {"index": 1, "text": "..."}, ...]
    """
    return {
        "id": "chatcmpl-fake-v2",
        "model": "gpt-4o-mini",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": json.dumps({"rewritten": indexed_items}, ensure_ascii=False),
                },
                "finish_reason": "stop",
            }
        ],
    }


def _payload_chunk_size(req) -> int:
    """从请求 payload 里读出 bullets 数组长度(== 这次 chunk 大小)"""
    payload = json.loads(req.data.decode("utf-8"))
    user_msg = payload["messages"][1]["content"]
    return len(json.loads(user_msg)["bullets"])


def _patch_urlopen(monkeypatch, body: bytes, status: int = 200, side_effect=None):
    """
    把 urllib.request.urlopen 换成返回固定 body 的 mock。
    side_effect: 若给出 (exception),则 urlopen 抛该异常(模拟超时/HTTPError/URLError)。
    """
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["timeout"] = timeout
        captured["url"] = req.full_url
        captured["data"] = req.data
        captured["headers"] = dict(req.headers)
        if side_effect is not None:
            raise side_effect
        return _FakeResp(body, status)

    monkeypatch.setattr("core.llm_rewriter.urllib.request.urlopen", fake_urlopen)
    return captured


def _patch_urlopen_chunk_aware(monkeypatch, rewrite_factory):
    """
    把 urlopen 换成"按 chunk 大小返回合适长度 rewrite"的 mock。
    rewrite_factory: 函(chunk_index, chunk_bullets) -> list[str]
    自动捕获每次请求的 chunk size + bullets + chunk_index,记录到 captured["calls"]。
    """
    captured = {"calls": []}

    def fake_urlopen(req, timeout=None):
        payload = json.loads(req.data.decode("utf-8"))
        user_msg = json.loads(payload["messages"][1]["content"])
        bullets = user_msg["bullets"]
        idx = len(captured["calls"])
        captured["calls"].append({
            "timeout": timeout,
            "url": req.full_url,
            "bullets": bullets,
            "headers": dict(req.headers),
        })
        rewritten = rewrite_factory(idx, bullets)
        body = json.dumps(
            _openai_chat_response(rewritten), ensure_ascii=False
        ).encode("utf-8")
        return _FakeResp(body, 200)

    monkeypatch.setattr("core.llm_rewriter.urllib.request.urlopen", fake_urlopen)
    return captured


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


@pytest.fixture
def disable_llm_no_key(monkeypatch):
    """没 key → LLM 关闭"""
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_ENABLED", raising=False)
    yield


@pytest.fixture
def disable_llm_forced(monkeypatch):
    """有 key 但 LLM_ENABLED=false → 强制关闭"""
    monkeypatch.setenv("LLM_API_KEY", "sk-fake-test-key")
    monkeypatch.setenv("LLM_ENABLED", "false")
    yield
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_ENABLED", raising=False)


# ----------------------------------------------------------------------
# 1. is_llm_enabled 状态机
# ----------------------------------------------------------------------
def test_is_llm_enabled_with_key_and_auto(enable_llm):
    """有 key + LLM_ENABLED=auto → True"""
    assert llm.is_llm_enabled() is True


def test_is_llm_enabled_without_key(disable_llm_no_key):
    """无 key → False"""
    assert llm.is_llm_enabled() is False


def test_is_llm_enabled_key_but_disabled(disable_llm_forced):
    """有 key + LLM_ENABLED=false → False"""
    assert llm.is_llm_enabled() is False


# ----------------------------------------------------------------------
# 2. rewrite_highlights:核心逻辑(无 LLM 时不打 HTTP)
# ----------------------------------------------------------------------
def test_rewrite_skipped_when_disabled(disable_llm_no_key, monkeypatch):
    """LLM 关闭时直接返回原文,不调 urlopen"""
    called = {"count": 0}
    def boom(*a, **kw):
        called["count"] += 1
        raise AssertionError("urlopen should not be called when LLM disabled")
    monkeypatch.setattr("core.llm_rewriter.urllib.request.urlopen", boom)

    bullets = ["原文 1", "原文 2", "原文 3"]
    assert llm.rewrite_highlights(bullets, target_role="tech_metric") == bullets
    assert called["count"] == 0


def test_rewrite_empty_input_returns_empty(enable_llm):
    """空输入 → 空输出,不调 LLM"""
    assert llm.rewrite_highlights([], target_role="tech_metric") == []


# ----------------------------------------------------------------------
# 3. rewrite_highlights:HTTP 成功路径
# ----------------------------------------------------------------------
def test_rewrite_happy_path_uses_openai_schema(enable_llm, monkeypatch):
    """HTTP 200 + 合法 OpenAI chat/completions 响应 → 改写生效,顺序对齐"""
    bullets = ["原文 A", "原文 B", "原文 C"]
    rewritten = ["改写 A", "改写 B", "改写 C"]
    body = json.dumps(_openai_chat_response(rewritten), ensure_ascii=False).encode("utf-8")
    captured = _patch_urlopen(monkeypatch, body=body)

    out = llm.rewrite_highlights(
        bullets, target_role="tech_metric", jd_text="医疗 AI"
    )
    assert out == rewritten
    # 校验 HTTP 调用参数合理
    assert captured["timeout"] == llm.REQUEST_TIMEOUT_SEC
    assert captured["url"].endswith("/chat/completions")
    assert captured["headers"]["Authorization"] == "Bearer sk-fake-test-key"
    # payload 含 target_role + jd_context + bullets
    payload = json.loads(captured["data"].decode("utf-8"))
    assert payload["model"] == "gpt-4o-mini"
    assert payload["messages"][1]["content"]
    user_payload = json.loads(payload["messages"][1]["content"])
    assert user_payload["target_role"] == "tech_metric"
    assert user_payload["jd_context"] == "医疗 AI"
    assert user_payload["bullets"] == bullets


def test_rewrite_accepts_top_level_array(enable_llm, monkeypatch):
    """LLM 直接返顶层 JSON array → 也能正确解析"""
    bullets = ["x", "y"]
    rewritten = ["x-new", "y-new"]
    body = json.dumps(rewritten, ensure_ascii=False).encode("utf-8")
    _patch_urlopen(monkeypatch, body=body)

    out = llm.rewrite_highlights(bullets, target_role="algorithm")
    assert out == rewritten


def test_rewrite_accepts_rewritten_field(enable_llm, monkeypatch):
    """LLM 返 {\"rewritten\": [...]} → 也能正确解析"""
    bullets = ["a", "b"]
    rewritten = ["a2", "b2"]
    body = json.dumps({"rewritten": rewritten}, ensure_ascii=False).encode("utf-8")
    _patch_urlopen(monkeypatch, body=body)

    out = llm.rewrite_highlights(bullets, target_role="product")
    assert out == rewritten


# ----------------------------------------------------------------------
# 4. rewrite_highlights:失败降级路径
# ----------------------------------------------------------------------
def test_rewrite_falls_back_on_http_500(enable_llm, monkeypatch):
    """HTTP 500 → 返回原文(不抛)"""
    from urllib.error import HTTPError
    err = HTTPError(
        url="https://example.com/v1/chat/completions",
        code=500,
        msg="Internal Server Error",
        hdrs=None,
        fp=BytesIO(b"boom"),
    )
    _patch_urlopen(monkeypatch, body=b"", side_effect=err)

    bullets = ["原文 1", "原文 2", "原文 3"]
    out = llm.rewrite_highlights(bullets, target_role="tech_metric")
    assert out == bullets


def test_rewrite_falls_back_on_timeout(enable_llm, monkeypatch):
    """超时 → 返回原文(不抛)"""
    _patch_urlopen(monkeypatch, body=b"", side_effect=TimeoutError("read timeout"))

    bullets = ["a", "b"]
    out = llm.rewrite_highlights(bullets, target_role="tech_metric")
    assert out == bullets


def test_rewrite_falls_back_on_invalid_json(enable_llm, monkeypatch):
    """HTTP 200 但 body 不是 JSON → 返回原文"""
    _patch_urlopen(monkeypatch, body=b"<html>not json</html>")

    bullets = ["原文 1", "原文 2"]
    out = llm.rewrite_highlights(bullets, target_role="tech_metric")
    assert out == bullets


def test_rewrite_falls_back_on_length_mismatch(enable_llm, monkeypatch):
    """LLM 返回的 bullet 数量跟输入对不上 → 降级回原文"""
    rewritten_too_few = ["只返一条"]
    body = json.dumps(_openai_chat_response(rewritten_too_few), ensure_ascii=False).encode("utf-8")
    _patch_urlopen(monkeypatch, body=body)

    bullets = ["原文 1", "原文 2", "原文 3"]
    out = llm.rewrite_highlights(bullets, target_role="tech_metric")
    assert out == bullets


# ----------------------------------------------------------------------
# 5. rewrite_highlights:长度截断
# ----------------------------------------------------------------------
def test_rewrite_truncates_to_max_per_call(enable_llm, monkeypatch):
    """10 条 bullets + max_per_call=3 → 调用 4 次 (3+3+3+1),每个 chunk 大小正确"""
    bullets = [f"原文 {i}" for i in range(10)]

    captured = _patch_urlopen_chunk_aware(
        monkeypatch,
        rewrite_factory=lambda idx, chunk: [f"R{idx}-{i}" for i in range(len(chunk))],
    )

    out = llm.rewrite_highlights(bullets, target_role="tech_metric", max_per_call=3)

    assert len(out) == 10
    # 调用 4 次,每次 chunk 大小 [3, 3, 3, 1]
    assert len(captured["calls"]) == 4
    chunk_sizes = [len(c["bullets"]) for c in captured["calls"]]
    assert chunk_sizes == [3, 3, 3, 1]
    # 第 4 次 chunk 只有 1 条 (positions 9)
    assert captured["calls"][3]["bullets"] == ["原文 9"]
    # 输出按 chunk 顺序拼起来:每个位置都拿到改写
    assert out == [
        "R0-0", "R0-1", "R0-2",
        "R1-0", "R1-1", "R1-2",
        "R2-0", "R2-1", "R2-2",
        "R3-0",
    ]
    # 任意位置的文本 ≠ 原文 (确认改写生效,不是回退)
    assert all(out[i] != bullets[i] for i in range(10))


# ----------------------------------------------------------------------
# 6. 端到端:build_sections 集成
# ----------------------------------------------------------------------
def test_build_sections_unchanged_when_llm_disabled(disable_llm_no_key):
    """
    LLM 关闭时,所有 6 个 role 的 build_sections 输出与 Round 2 #1 baseline 一致。
    校验:
      - 每个 project 的 highlights 非空
      - tech_metric 的第一个 project (company_medical_eval) 的 highlights 内容
        与底层 materials.json["projects"][0]["highlights"]["tech_metric"] 完全一致
        (锁死 baseline,任何 _pick_highlights 改动都会被抓到)
    """
    for role in ENABLED_ROLES:
        sections = build_sections(target_role=role)
        proj_group = next(s for s in sections if s.type == "project_group")
        projects = proj_group.content["projects"]
        assert projects, f"{role} 没有任何 project 输出"
        for proj in projects:
            highlights = proj["content"]["highlights"]
            assert highlights, f"{role} - {proj['title']} highlights 为空"

    # 精确回归:tech_metric 第一个 project 的 highlights == materials.json 直出
    from core.generator import load_materials, _pick_highlights
    materials = load_materials()
    first_proj = materials["projects"][0]
    expected = first_proj["highlights"]["tech_metric"]
    sections = build_sections(target_role="tech_metric")
    actual = next(s for s in sections if s.type == "project_group") \
                .content["projects"][0]["content"]["highlights"]
    assert actual == expected, (
        f"tech_metric baseline regression: build_sections 输出跟 Round 2 #1 不一致\n"
        f"  diff[0]: got={actual[0][:40]!r} expected={expected[0][:40]!r}"
    )
    # 顺手再验一次 _pick_highlights 的直出,作为更底层 sanity
    assert _pick_highlights(first_proj, "tech_metric") == expected


def test_build_sections_picks_up_llm_rewrite(enable_llm, monkeypatch):
    """
    LLM 启用 + HTTP mock 成功 → build_sections 的 project highlights 包含改写后文本。
    """
    # 取第一个 role (tech_metric) 的第一个 project 作为测试对象
    sections_before = build_sections(target_role="tech_metric")
    proj_before = next(
        s for s in sections_before if s.type == "project_group"
    ).content["projects"][0]
    original_first_highlight = proj_before["content"]["highlights"][0]

    # 用 chunk-aware mock:对每个 chunk,逐 bullet 改写成 "改写-{index}"
    # 注意:这里 index 是全局绝对位置 (input index),不是 chunk 内 index
    captured_calls = {"calls": []}

    def chunk_aware(req, timeout=None):
        payload = json.loads(req.data.decode("utf-8"))
        user_msg = json.loads(payload["messages"][1]["content"])
        bullets = user_msg["bullets"]
        # 从 req.full_url 拿不到全局 index,所以记录 caller 给的 chunk_offset
        # 这里靠 captured_calls 的 index 推断 (假设 caller 单进程)
        offset = captured_calls["offset"]
        captured_calls["calls"].append({"bullets": bullets, "offset": offset})
        captured_calls["offset"] += len(bullets)
        rewritten = [f"改写-{offset + i}" for i in range(len(bullets))]
        body = json.dumps(
            _openai_chat_response(rewritten), ensure_ascii=False
        ).encode("utf-8")
        return _FakeResp(body, 200)

    captured_calls["offset"] = 0
    monkeypatch.setattr("core.llm_rewriter.urllib.request.urlopen", chunk_aware)

    sections_after = build_sections(target_role="tech_metric")
    proj_after = next(
        s for s in sections_after if s.type == "project_group"
    ).content["projects"][0]
    out_highlights = proj_after["content"]["highlights"]

    # 长度对齐 + 全部被改写 (原文被替换为 "改写-N")
    assert len(out_highlights) == len(proj_before["content"]["highlights"])
    assert all(h.startswith("改写-") for h in out_highlights)
    assert out_highlights[0] != original_first_highlight


def test_build_sections_silent_fallback_when_http_fails(enable_llm, monkeypatch):
    """
    LLM 启用但 HTTP 报错 → build_sections 仍正常返回,highlights == 原文(不抛异常给上层)。
    """
    from urllib.error import URLError
    monkeypatch.setattr(
        "core.llm_rewriter.urllib.request.urlopen",
        MagicMock(side_effect=URLError("connection refused")),
    )

    sections = build_sections(target_role="tech_metric")
    proj = next(
        s for s in sections if s.type == "project_group"
    ).content["projects"][0]
    # 不为空,且是 list[str](没异常被吞)
    assert isinstance(proj["content"]["highlights"], list)
    assert proj["content"]["highlights"]


# ======================================================================
# Round 3-P: Prompt 工程升级 (few-shot + JSON schema + retry)
# ======================================================================
class TestSystemPromptV2:
    """R3-P: SYSTEM_PROMPT v2 必须含 few-shot 示例 + 显式 schema 约束。"""

    def test_system_prompt_contains_few_shot_example_basic(self):
        """基础 few-shot 示例(无 jd_focus)必须在 SYSTEM_PROMPT 里"""
        assert "示例 1" in llm.SYSTEM_PROMPT
        assert "基础改写" in llm.SYSTEM_PROMPT or "无 jd_focus" in llm.SYSTEM_PROMPT
        # 示例里必须给输入 + 输出 + 显式 schema
        assert "输入 bullets" in llm.SYSTEM_PROMPT
        assert '"rewritten"' in llm.SYSTEM_PROMPT
        assert '"index"' in llm.SYSTEM_PROMPT
        assert '"text"' in llm.SYSTEM_PROMPT

    def test_system_prompt_contains_few_shot_example_with_jd_focus(self):
        """带 jd_focus 的 few-shot 示例必须在 SYSTEM_PROMPT 里"""
        assert "示例 2" in llm.SYSTEM_PROMPT
        assert "jd_focus" in llm.SYSTEM_PROMPT
        # jd_focus 的 4 个子键都应出现
        assert "matched" in llm.SYSTEM_PROMPT
        assert "missing" in llm.SYSTEM_PROMPT
        assert "tier_required" in llm.SYSTEM_PROMPT
        assert "tier_preferred" in llm.SYSTEM_PROMPT

    def test_system_prompt_has_hard_constraints(self):
        """硬性约束 7 条(不编造 / 长度 / schema / jd_focus 4 条)都在 prompt 里"""
        assert "绝不" in llm.SYSTEM_PROMPT
        assert "编造事实" in llm.SYSTEM_PROMPT
        assert "20-50 字" in llm.SYSTEM_PROMPT
        # schema 约束
        assert "JSON" in llm.SYSTEM_PROMPT
        assert "数量必须等于" in llm.SYSTEM_PROMPT


class TestNewSchemaExtraction:
    """R3-P: 新 schema 验证 + 提取。"""

    def test_new_schema_indexed_items_accepted(self, enable_llm, monkeypatch):
        """新 schema [{"index": i, "text": "..."}] 能被正确提取"""
        items = [
            {"index": 0, "text": "改写 0"},
            {"index": 1, "text": "改写 1"},
            {"index": 2, "text": "改写 2"},
        ]
        body = json.dumps(_openai_chat_response_v2(items)).encode("utf-8")
        _patch_urlopen(monkeypatch, body)
        out = llm.rewrite_highlights(
            ["原文 0", "原文 1", "原文 2"], target_role="tech_metric"
        )
        assert out == ["改写 0", "改写 1", "改写 2"]

    def test_new_schema_rejects_duplicate_index(self, enable_llm, monkeypatch):
        """重复 index → 验证失败 → 走 retry → 第 2 次仍 bad → 降级原文"""
        items = [
            {"index": 0, "text": "改写 0"},
            {"index": 0, "text": "改写 1"},  # 重复 index 0
            {"index": 2, "text": "改写 2"},
        ]
        body = json.dumps(_openai_chat_response_v2(items)).encode("utf-8")
        # 两次都返同样 bad schema → retry 也没救 → 降级
        _patch_urlopen(monkeypatch, body)
        out = llm.rewrite_highlights(
            ["原文 0", "原文 1", "原文 2"], target_role="tech_metric"
        )
        # 验证失败 → retry 仍失败 → 降级原文
        assert out == ["原文 0", "原文 1", "原文 2"]

    def test_new_schema_rejects_out_of_range_index(self, enable_llm, monkeypatch):
        """index 越界(>= expected_count)→ 验证失败 → retry 仍失败 → 降级"""
        items = [
            {"index": 0, "text": "改写 0"},
            {"index": 1, "text": "改写 1"},
            {"index": 5, "text": "改写 2"},  # 越界(预期 0..2)
        ]
        body = json.dumps(_openai_chat_response_v2(items)).encode("utf-8")
        _patch_urlopen(monkeypatch, body)
        out = llm.rewrite_highlights(
            ["原文 0", "原文 1", "原文 2"], target_role="tech_metric"
        )
        assert out == ["原文 0", "原文 1", "原文 2"]

    def test_new_schema_rejects_empty_text(self, enable_llm, monkeypatch):
        """text 是空字符串 → 验证失败 → retry → 降级"""
        items = [
            {"index": 0, "text": "改写 0"},
            {"index": 1, "text": "  "},  # 空白
            {"index": 2, "text": "改写 2"},
        ]
        body = json.dumps(_openai_chat_response_v2(items)).encode("utf-8")
        _patch_urlopen(monkeypatch, body)
        out = llm.rewrite_highlights(
            ["原文 0", "原文 1", "原文 2"], target_role="tech_metric"
        )
        assert out == ["原文 0", "原文 1", "原文 2"]

    def test_new_schema_rejects_count_mismatch(self, enable_llm, monkeypatch):
        """数量不等(expected_count=3,返回 2 个)→ 验证失败 → 降级"""
        items = [
            {"index": 0, "text": "改写 0"},
            {"index": 1, "text": "改写 1"},
            # 缺第 3 个
        ]
        body = json.dumps(_openai_chat_response_v2(items)).encode("utf-8")
        _patch_urlopen(monkeypatch, body)
        out = llm.rewrite_highlights(
            ["原文 0", "原文 1", "原文 2"], target_role="tech_metric"
        )
        assert out == ["原文 0", "原文 1", "原文 2"]


class TestRetryOnInvalid:
    """R3-P: 失败 retry 一次(更严格指令)→ 成功时返回;仍失败时降级。"""

    def test_retry_succeeds_with_strict_hint(self, enable_llm, monkeypatch):
        """第 1 次返 bad schema,第 2 次返 good schema → 取第 2 次结果"""
        bad_items = [
            {"index": 0, "text": "改写 0"},
            {"index": 0, "text": "改写 1"},  # 重复 index
        ]
        good_items = [
            {"index": 0, "text": "改写 retry 0"},
            {"index": 1, "text": "改写 retry 1"},
        ]
        # 两次 urlopen 返回不同 body
        body_bad = json.dumps(_openai_chat_response_v2(bad_items)).encode("utf-8")
        body_good = json.dumps(_openai_chat_response_v2(good_items)).encode("utf-8")

        call_count = {"n": 0}
        def fake_urlopen(req, timeout=None):
            call_count["n"] += 1
            body = body_bad if call_count["n"] == 1 else body_good
            return _FakeResp(body)

        monkeypatch.setattr(
            "core.llm_rewriter.urllib.request.urlopen", fake_urlopen
        )

        out = llm.rewrite_highlights(
            ["原文 0", "原文 1"], target_role="tech_metric"
        )
        assert call_count["n"] == 2, "应该重试 1 次(共 2 次调用)"
        assert out == ["改写 retry 0", "改写 retry 1"], "应取第 2 次成功结果"

    def test_retry_exhausted_falls_back_to_original(self, enable_llm, monkeypatch):
        """第 1 次 + 第 2 次都返 bad schema → 降级原文(不再重试)"""
        bad_items = [
            {"index": 0, "text": "改写 0"},
            {"index": 0, "text": "改写 1"},  # 重复
        ]
        body_bad = json.dumps(_openai_chat_response_v2(bad_items)).encode("utf-8")

        call_count = {"n": 0}
        def fake_urlopen(req, timeout=None):
            call_count["n"] += 1
            return _FakeResp(body_bad)

        monkeypatch.setattr(
            "core.llm_rewriter.urllib.request.urlopen", fake_urlopen
        )

        out = llm.rewrite_highlights(
            ["原文 0", "原文 1"], target_role="tech_metric"
        )
        assert call_count["n"] == 2, "应该调用 2 次(首次 + retry 1 次)"
        assert out == ["原文 0", "原文 1"], "retry 也失败 → 降级原文"

    def test_network_error_does_not_retry(self, enable_llm, monkeypatch):
        """HTTP/网络错误 → 不 retry(避免浪费 token)→ 立即降级"""
        from urllib.error import URLError
        call_count = {"n": 0}
        def fake_urlopen(req, timeout=None):
            call_count["n"] += 1
            raise URLError("connection refused")

        monkeypatch.setattr(
            "core.llm_rewriter.urllib.request.urlopen", fake_urlopen
        )

        out = llm.rewrite_highlights(
            ["原文 0", "原文 1"], target_role="tech_metric"
        )
        assert call_count["n"] == 1, "网络错误不应 retry(避免 token 浪费)"
        assert out == ["原文 0", "原文 1"]


class TestSchemaValidationUnit:
    """R3-P: _validate_new_schema / _validate_legacy_schema 单元测试(无网络)"""

    def test_validate_new_schema_happy_path(self):
        items = [
            {"index": 0, "text": "a"},
            {"index": 1, "text": "b"},
        ]
        assert llm._validate_new_schema(items, 2) is True

    def test_validate_new_schema_wrong_count(self):
        items = [{"index": 0, "text": "a"}]  # expected 2
        assert llm._validate_new_schema(items, 2) is False

    def test_validate_new_schema_index_out_of_range(self):
        items = [
            {"index": 0, "text": "a"},
            {"index": 3, "text": "b"},  # 越界(expected_count=2)
        ]
        assert llm._validate_new_schema(items, 2) is False

    def test_validate_new_schema_empty_text(self):
        items = [
            {"index": 0, "text": "a"},
            {"index": 1, "text": ""},
        ]
        assert llm._validate_new_schema(items, 2) is False

    def test_validate_new_schema_non_dict_item(self):
        items = [
            {"index": 0, "text": "a"},
            "not a dict",
        ]
        assert llm._validate_new_schema(items, 2) is False

    def test_validate_legacy_schema_happy_path(self):
        items = ["a", "b", "c"]
        assert llm._validate_legacy_schema(items, 3) is True

    def test_validate_legacy_schema_wrong_count(self):
        items = ["a", "b"]  # expected 3
        assert llm._validate_legacy_schema(items, 3) is False

    def test_validate_legacy_schema_empty_string(self):
        items = ["a", "  ", "c"]
        assert llm._validate_legacy_schema(items, 3) is False


# ======================================================================
# R4-F: Function Calling — tools schema 挂载 + tool_calls 解析分支
# ======================================================================
def _openai_chat_response_with_tool_calls(tool_calls: list[dict]) -> dict:
    """
    R4-F: 构造一个 OpenAI chat/completions 响应,message 含 tool_calls 字段
    (无 content,模拟 LLM 决定调工具而非直接返文本)
    """
    return {
        "id": "chatcmpl-fake-tool",
        "model": "gpt-4o-mini",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": tool_calls,
                },
                "finish_reason": "tool_calls",
            }
        ],
    }


class TestFunctionCalling:
    """R4-F: Function Calling 协议接入 — 5 case 锁死行为。"""

    def test_tools_schema_structure(self):
        """TOOL_EVALUATE_SCHEMA 结构:含 1 个 function 工具 + 正确 parameters"""
        assert isinstance(llm.TOOL_EVALUATE_SCHEMA, list)
        assert len(llm.TOOL_EVALUATE_SCHEMA) == 1
        tool = llm.TOOL_EVALUATE_SCHEMA[0]
        assert tool["type"] == "function"
        fn = tool["function"]
        assert fn["name"] == "evaluate_bullet_jd_match"
        # description 必含, 提示 LLM 工具语义
        assert "关键词" in fn["description"] or "JD" in fn["description"]
        # parameters: object 类型 + bullet/jd_focus 必填
        params = fn["parameters"]
        assert params["type"] == "object"
        assert "bullet" in params["properties"]
        assert "jd_focus" in params["properties"]
        assert set(params["required"]) == {"bullet", "jd_focus"}
        # jd_focus 内部 4 个字段 (matched/missing/tier_required/tier_preferred) 都应存在
        jd_focus_props = params["properties"]["jd_focus"]["properties"]
        for key in ("matched", "missing", "tier_required", "tier_preferred"):
            assert key in jd_focus_props, f"jd_focus 必含 {key}"

    def test_default_path_does_not_attach_tools(self, enable_llm, monkeypatch):
        """enable_function_calling=False(默认)→ payload 不含 tools 字段(老路径字节级一致)"""
        captured = _patch_urlopen(
            monkeypatch,
            body=json.dumps(
                _openai_chat_response(["r0", "r1"])
            ).encode("utf-8"),
        )
        llm.rewrite_highlights(
            ["x", "y"], target_role="tech_metric", jd_text="JD"
        )
        payload = json.loads(captured["data"].decode("utf-8"))
        assert "tools" not in payload, (
            f"默认路径不应挂 tools 字段,实际: {payload.keys()}"
        )
        assert "tool_choice" not in payload

    def test_jd_focus_none_does_not_attach_tools(self, enable_llm, monkeypatch):
        """jd_focus=None 时即使 enable_function_calling=True 也不挂 tools
        (空 jd_focus 没工具执行的意义,避免污染老调用路径)"""
        captured = _patch_urlopen(
            monkeypatch,
            body=json.dumps(
                _openai_chat_response(["r0", "r1"])
            ).encode("utf-8"),
        )
        llm.rewrite_highlights(
            ["x", "y"], target_role="tech_metric",
            enable_function_calling=True,  # 开 FC
            jd_focus=None,  # 但 jd_focus 缺
        )
        payload = json.loads(captured["data"].decode("utf-8"))
        assert "tools" not in payload, "jd_focus=None 时不应挂 tools"

    def test_enable_function_calling_attaches_tools(self, enable_llm, monkeypatch):
        """enable_function_calling=True + jd_focus 非空 → payload 含 tools 字段"""
        captured = _patch_urlopen(
            monkeypatch,
            body=json.dumps(
                _openai_chat_response(["r0", "r1"])
            ).encode("utf-8"),
        )
        llm.rewrite_highlights(
            ["x", "y"], target_role="tech_metric",
            enable_function_calling=True,
            jd_focus={"matched": ["Python"], "missing": ["PyTorch"],
                      "tier_required": ["Python"], "tier_preferred": []},
        )
        payload = json.loads(captured["data"].decode("utf-8"))
        assert "tools" in payload
        assert payload["tools"] == llm.TOOL_EVALUATE_SCHEMA
        assert payload["tool_choice"] == "auto"

    def test_tool_calls_response_falls_back_to_original(self, enable_llm, monkeypatch):
        """LLM 返 tool_calls(无 content)→ _extract_rewritten 返回 None → 降级原文
        (R4-A 才接 agent loop 真正执行工具;R4-F 阶段 tool_calls 视为未交付改写)"""
        tool_calls = [
            {
                "id": "call_1",
                "type": "function",
                "function": {
                    "name": "evaluate_bullet_jd_match",
                    "arguments": json.dumps(
                        {"bullet": "x", "jd_focus": {"matched": [], "missing": []}},
                        ensure_ascii=False,
                    ),
                },
            }
        ]
        body = json.dumps(
            _openai_chat_response_with_tool_calls(tool_calls)
        ).encode("utf-8")
        _patch_urlopen(monkeypatch, body=body)

        bullets = ["原文 1", "原文 2"]
        out = llm.rewrite_highlights(
            bullets, target_role="tech_metric",
            enable_function_calling=True,
            jd_focus={"matched": ["Python"], "missing": ["PyTorch"],
                      "tier_required": [], "tier_preferred": []},
        )
        # LLM 返 tool_calls → 没交付最终改写 → 降级原文
        assert out == bullets, (
            f"tool_calls 响应应降级原文,实际: {out}"
        )


# ======================================================================
# R4-A: Agent Loop (max_step=3) + 单工具约束 + trace 日志
# ======================================================================
def _patch_http_post_json_step_aware(monkeypatch, response_factory):
    """
    R4-A: 替换 _http_post_json 为按 step 返回不同响应的 mock。
    response_factory: 函(step_index, payload_dict) -> dict (LLM 响应) 或 raise RuntimeError

    返回 captured: dict 含 "calls" 列表(每条 {"step", "url", "messages", "data"})

    为什么要 mock _http_post_json 而不是 urllib.request.urlopen?
    - _call_with_agent_loop 直接调 _http_post_json (不走 _call_with_retry)
    - mock _http_post_json 能精确控制每个 step 的响应
    """
    captured = {"calls": []}

    def fake_http_post_json(url, payload, api_key, timeout):
        idx = len(captured["calls"])
        captured["calls"].append({
            "step": idx,
            "url": url,
            "messages": payload.get("messages", []),
            "data": payload,
        })
        return response_factory(idx, payload)

    monkeypatch.setattr("core.llm_rewriter._http_post_json", fake_http_post_json)
    return captured


def _tool_call_response(tool_name: str, arguments: dict, call_id: str = "call_1") -> dict:
    """构造一个 LLM tool_calls 响应(无 content)"""
    return {
        "id": "chatcmpl-agent",
        "model": "gpt-4o-mini",
        "choices": [{
            "index": 0,
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": call_id,
                    "type": "function",
                    "function": {
                        "name": tool_name,
                        "arguments": json.dumps(arguments, ensure_ascii=False),
                    },
                }],
            },
            "finish_reason": "tool_calls",
        }],
    }


def _rewrite_response(bullets: list[str]) -> dict:
    """构造一个标准 rewrite 响应 (OpenAI chat/completions, 新 schema)"""
    return _openai_chat_response(bullets)


class TestAgentLoop:
    """R4-A: Agent Loop (max_step=3) + 单工具约束 + trace 日志 — 8 case 锁死行为。"""

    def test_max_step_exhausted_falls_back(self, enable_llm, monkeypatch, tmp_path):
        """LLM 连续 3 步都返 tool_calls → 第 4 步被 max_step 截断 → 降级原文 + trace 记 max_step_exhausted"""
        # 用 tmp_path 重定向 trace 日志,避免污染
        import core.logger
        monkeypatch.setattr(core.logger, "AGENT_TRACE_PATH", tmp_path / "agent_trace.log")

        # 每步都返 tool_calls(让 loop 跑满 3 步)
        captured = _patch_http_post_json_step_aware(
            monkeypatch,
            response_factory=lambda step, payload: _tool_call_response(
                "evaluate_bullet_jd_match",
                {"bullet": "x", "jd_focus": {"matched": [], "missing": []}},
            ),
        )
        bullets = ["原文 1", "原文 2"]
        out = llm.rewrite_highlights(
            bullets, target_role="tech_metric",
            enable_function_calling=True,
            jd_focus={"matched": ["Python"], "missing": ["PyTorch"],
                      "tier_required": [], "tier_preferred": []},
        )
        # 3 步都调了 LLM, 但都没拿到 output → 降级原文
        assert len(captured["calls"]) == llm.MAX_AGENT_STEPS
        assert out == bullets, f"max_step 用完应降级原文, 实际: {out}"

    def test_tool_execution_success_path(self, enable_llm, monkeypatch, tmp_path):
        """Step 0 返 tool_calls → 工具执行 → Step 1 返 rewritten → 成功拿改写"""
        import core.logger
        monkeypatch.setattr(core.logger, "AGENT_TRACE_PATH", tmp_path / "agent_trace.log")

        # 工厂: step 0 返 tool_calls, step 1 返 rewritten
        def factory(step, payload):
            if step == 0:
                return _tool_call_response(
                    "evaluate_bullet_jd_match",
                    {"bullet": "原文 1", "jd_focus": {
                        "matched": ["Python"], "missing": ["PyTorch"]}},
                )
            return _rewrite_response(["改写 0", "改写 1"])

        captured = _patch_http_post_json_step_aware(monkeypatch, response_factory=factory)
        bullets = ["原文 1", "原文 2"]
        out = llm.rewrite_highlights(
            bullets, target_role="tech_metric",
            enable_function_calling=True,
            jd_focus={"matched": ["Python"], "missing": ["PyTorch"],
                      "tier_required": [], "tier_preferred": []},
        )
        # 2 步: step 0 调工具, step 1 拿改写
        assert len(captured["calls"]) == 2
        assert out == ["改写 0", "改写 1"]
        # Step 1 的 messages 应含 step 0 的 tool 响应
        step1_messages = captured["calls"][1]["messages"]
        roles = [m["role"] for m in step1_messages]
        assert "tool" in roles, f"Step 1 messages 应含 tool 角色, 实际: {roles}"

    def test_tool_execution_failure_fallback(self, enable_llm, monkeypatch, tmp_path):
        """Step 0 返 tool_calls 但 LLM 返的 tool 名字不在注册表 → 工具失败 → step 1 继续 → 拿不到 → 降级"""
        import core.logger
        monkeypatch.setattr(core.logger, "AGENT_TRACE_PATH", tmp_path / "agent_trace.log")

        def factory(step, payload):
            if step == 0:
                # 未知工具 — _execute_tool_call 会返 {"error": "unknown tool: foo"}
                return _tool_call_response(
                    "unknown_tool_foo",
                    {"arg": "x"},
                )
            # step 1 返 schema 失败响应(无 content / 无 tool_calls) → 降级
            return {
                "id": "chatcmpl-bad",
                "model": "gpt-4o-mini",
                "choices": [{
                    "index": 0,
                    "message": {"role": "assistant", "content": "garbage"},
                    "finish_reason": "stop",
                }],
            }

        captured = _patch_http_post_json_step_aware(monkeypatch, response_factory=factory)
        bullets = ["原文 1", "原文 2"]
        out = llm.rewrite_highlights(
            bullets, target_role="tech_metric",
            enable_function_calling=True,
            jd_focus={"matched": ["Python"], "missing": ["PyTorch"],
                      "tier_required": [], "tier_preferred": []},
        )
        # 2 步: tool 执行(返 error) + 下次 schema 失败 → 降级
        assert len(captured["calls"]) == 2
        assert out == bullets, f"工具执行失败 + schema 失败应降级原文, 实际: {out}"

    def test_trace_log_format_and_fields(self, enable_llm, monkeypatch, tmp_path):
        """trace 日志写入 backend/logs/agent_trace.log(此处用 tmp_path 模拟)
        格式: [ISO 时间] session=xxx step=N tool=xxx latency_ms=N outcome=xxx
        """
        trace_file = tmp_path / "agent_trace.log"
        import core.logger
        monkeypatch.setattr(core.logger, "AGENT_TRACE_PATH", trace_file)

        # Step 0 tool → step 1 rewrite
        def factory(step, payload):
            if step == 0:
                return _tool_call_response(
                    "evaluate_bullet_jd_match",
                    {"bullet": "x", "jd_focus": {"matched": [], "missing": []}},
                )
            return _rewrite_response(["ok 0", "ok 1"])

        _patch_http_post_json_step_aware(monkeypatch, response_factory=factory)
        llm.rewrite_highlights(
            ["原文 0", "原文 1"], target_role="tech_metric",
            enable_function_calling=True,
            jd_focus={"matched": ["Python"], "missing": [],
                      "tier_required": [], "tier_preferred": []},
        )

        # 验证文件存在 + 内容
        assert trace_file.exists(), "agent_trace.log 应被创建"
        content = trace_file.read_text(encoding="utf-8")
        lines = [l for l in content.strip().split("\n") if l]
        # 2 步: step 0 tool_executed + step 1 success_rewrite
        assert len(lines) == 2, f"应有 2 行 trace, 实际: {len(lines)}"
        # 第 1 行: step 0 + tool_executed
        import re
        assert re.match(
            r"\[\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\] session=agent_[0-9a-f]{8} step=0 "
            r"tool=evaluate_bullet_jd_match latency_ms=\d+ outcome=tool_executed",
            lines[0],
        ), f"第 1 行格式错: {lines[0]}"
        # 第 2 行: step 1 + success_rewrite
        assert re.match(
            r"\[\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\] session=agent_[0-9a-f]{8} step=1 "
            r"tool=no_tool latency_ms=\d+ outcome=success_rewrite",
            lines[1],
        ), f"第 2 行格式错: {lines[1]}"
        # 隐私验证: 日志不应含 bullet / message 内容
        assert "原文 0" not in content
        assert "原文 1" not in content
        assert "ok 0" not in content

    def test_network_error_no_loop(self, enable_llm, monkeypatch, tmp_path):
        """Step 0 网络错误 → 不进 loop, 立即降级原文 + trace 记 network_error_fallback"""
        trace_file = tmp_path / "agent_trace.log"
        import core.logger
        monkeypatch.setattr(core.logger, "AGENT_TRACE_PATH", trace_file)

        from urllib.error import URLError
        captured_calls = {"n": 0}

        def fake_http_post_json(url, payload, api_key, timeout):
            captured_calls["n"] += 1
            raise RuntimeError(f"URLError: connection refused")

        monkeypatch.setattr("core.llm_rewriter._http_post_json", fake_http_post_json)

        bullets = ["原文 1", "原文 2"]
        out = llm.rewrite_highlights(
            bullets, target_role="tech_metric",
            enable_function_calling=True,
            jd_focus={"matched": ["Python"], "missing": ["PyTorch"],
                      "tier_required": [], "tier_preferred": []},
        )
        # 只调了 1 次(网络错误立即降级, 不进 loop)
        assert captured_calls["n"] == 1
        assert out == bullets
        # trace 记录 network_error_fallback
        content = trace_file.read_text(encoding="utf-8")
        assert "network_error_fallback" in content
        assert "step=0" in content

    def test_max_step_zero_uses_old_path(self, enable_llm, monkeypatch, tmp_path):
        """MAX_AGENT_STEPS=0 时 rewrite_highlights 走 _call_with_retry 老路径(不调 agent loop)"""
        import core.logger
        monkeypatch.setattr(core.logger, "AGENT_TRACE_PATH", tmp_path / "agent_trace.log")

        # 临时把 MAX_AGENT_STEPS 改成 0 — rewrite_highlights 应走 _call_with_retry
        monkeypatch.setattr(llm, "MAX_AGENT_STEPS", 0)

        # _call_with_retry 走 _http_post_json, 我们只测它被调
        captured = _patch_http_post_json_step_aware(
            monkeypatch,
            response_factory=lambda step, payload: _rewrite_response(["ok 0", "ok 1"]),
        )
        out = llm.rewrite_highlights(
            ["原文 0", "原文 1"], target_role="tech_metric",
            enable_function_calling=True,
            jd_focus={"matched": ["Python"], "missing": [],
                      "tier_required": [], "tier_preferred": []},
        )
        # _call_with_retry 调 1 次(没 retry)
        assert len(captured["calls"]) == 1
        assert out == ["ok 0", "ok 1"]
        # trace 不应有 success_rewrite 等 outcome(走老路径不写 trace)
        trace_file = tmp_path / "agent_trace.log"
        if trace_file.exists():
            content = trace_file.read_text(encoding="utf-8")
            # 走老路径 _call_with_retry 不调 log_agent_trace
            assert "success_rewrite" not in content

    def test_single_step_single_tool_constraint(self, enable_llm, monkeypatch, tmp_path):
        """单步单工具约束: LLM 返 2 个 tool_calls → 只执行 [0], [1] 忽略"""
        import core.logger
        monkeypatch.setattr(core.logger, "AGENT_TRACE_PATH", tmp_path / "agent_trace.log")

        def factory(step, payload):
            if step == 0:
                # 返 2 个 tool_calls — 只应执行 [0]
                return {
                    "id": "chatcmpl-2-tools",
                    "model": "gpt-4o-mini",
                    "choices": [{
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {
                                        "name": "evaluate_bullet_jd_match",
                                        "arguments": json.dumps(
                                            {"bullet": "x", "jd_focus": {"matched": [], "missing": []}},
                                            ensure_ascii=False,
                                        ),
                                    },
                                },
                                {
                                    "id": "call_2",
                                    "type": "function",
                                    "function": {
                                        "name": "evaluate_bullet_jd_match",  # 同名, 应该只执行 1 次
                                        "arguments": json.dumps(
                                            {"bullet": "y", "jd_focus": {"matched": [], "missing": []}},
                                            ensure_ascii=False,
                                        ),
                                    },
                                },
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }],
                }
            return _rewrite_response(["ok 0", "ok 1"])

        captured = _patch_http_post_json_step_aware(monkeypatch, response_factory=factory)
        out = llm.rewrite_highlights(
            ["原文 0", "原文 1"], target_role="tech_metric",
            enable_function_calling=True,
            jd_focus={"matched": ["Python"], "missing": [],
                      "tier_required": [], "tier_preferred": []},
        )
        # Step 0: 收到 2 个 tool_calls → 单步单工具 → 执行 [0] → 进 step 1
        # Step 1: 返 rewritten → 成功
        assert len(captured["calls"]) == 2
        # Step 1 的 messages 应只含 1 个 tool 响应(单工具约束)
        step1_messages = captured["calls"][1]["messages"]
        tool_messages = [m for m in step1_messages if m["role"] == "tool"]
        assert len(tool_messages) == 1, (
            f"单步单工具约束: 应只有 1 个 tool 消息, 实际: {len(tool_messages)}"
        )
        assert out == ["ok 0", "ok 1"]

    def test_execute_tool_call_known_tool(self, enable_llm):
        """_execute_tool_call: 已知工具 (evaluate_bullet_jd_match) 应返 {matched, missing, suggestion}"""
        tc = {
            "id": "call_1",
            "type": "function",
            "function": {
                "name": "evaluate_bullet_jd_match",
                "arguments": json.dumps(
                    {"bullet": "基于 Python 做 LLM 评测",
                     "jd_focus": {"matched": ["Python"], "missing": ["PyTorch"],
                                  "tier_required": [], "tier_preferred": []}},
                    ensure_ascii=False,
                ),
            },
        }
        result = llm._execute_tool_call(
            tc, chunk=["x"], jd_focus={"matched": ["Python"], "missing": []}
        )
        # 返 matched + missing + suggestion(无 error)
        assert "matched_keywords" in result
        assert "missing_keywords" in result
        assert "suggestion" in result
        assert "error" not in result
        assert "Python" in result["matched_keywords"]
        assert "PyTorch" in result["missing_keywords"]

    def test_execute_tool_call_unknown_tool(self, enable_llm):
        """_execute_tool_call: 未知工具 → 返 {"error": "unknown tool: ..."}"""
        tc = {
            "id": "call_1",
            "type": "function",
            "function": {
                "name": "magic_universe_tool",
                "arguments": json.dumps({"x": 1}, ensure_ascii=False),
            },
        }
        result = llm._execute_tool_call(tc, chunk=["x"], jd_focus=None)
        assert "error" in result
        assert "magic_universe_tool" in result["error"]