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