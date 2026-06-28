"""
R5-A Phase 2: scripts/replay_agent_trace.py 测试
R5-C Phase 5: 加 fallback category 渲染 + tools_used 交叉验证测试

锁点:
  R5-A Phase 2 baseline (10 case):
    TestReplayFilter (3 case):
      1.  filter_by_request_id          — 单次 workflow 全部 step
      2.  filter_by_session_id          — 多 workflow 同 session
      3.  no_id_returns_empty            — 不传 id → 空列表(spec: 必须显式选)

    TestReplayMarkdown (3 case):
      4.  markdown_contains_required_metadata  — request_id/workflow/session_id/steps/total_latency
      5.  markdown_table_columns_correct         — 7 列: step/tool/latency_ms/status/error_type/input_size/output_size
      6.  markdown_does_not_leak_raw_content    — 不含 PII / 原文敏感字段

    TestReplayScript (3 case):
      7.  cli_with_request_id_outputs_markdown  — subprocess 跑 --request-id
      8.  cli_with_session_id_outputs_markdown  — subprocess 跑 --session-id
      9.  cli_without_id_exits_nonzero          — 不传 id 报错退出

    TestReplayRobustness (1 case):
      10. corrupt_jsonl_line_is_skipped          — 坏行不阻断

  R5-C Phase 5 增量 (5 case):
    TestReplayFallbackSummary (2 case):
      11. fallback_summary_none_when_no_errors         — 无 error step → category=none
      12. fallback_summary_tool_error_when_status_error — 有 status=error → category=tool_error_fallback

    TestReplayToolsCrossValidation (3 case):
      13. cross_validate_ok_when_all_matched            — expected 全部在 trace → status=ok
      14. cross_validate_missing_when_expected_absent    — expected 含 trace 没有的 → status=missing
      15. cross_validate_unexpected_when_trace_extra     — trace 比 expected 多 → status=unexpected
      + 默认不传 --tools-used 时不输出 Cross-Validation 段(由 cli_with_request_id_outputs_markdown 间接锁)

    TestReplayPiiSafety (2 case):
      16. fallback_summary_does_not_leak_raw_content    — 即使 event 含敏感 dict 字段, fallback summary 不泄漏
      17. cross_validate_does_not_leak_raw_content      — 交叉验证段不含原文 / dict body

    TestReplayRobustnessR5C (1 case):
      18. cross_validate_handles_malformed_events       — events 含 None tool / 空 status 时 cross-validate 不抛

测试策略:
  - 用 tmp_path 写 mock JSONL, 直接 import replay 内部函数(filter_events / render_markdown)
  - subprocess 测试走 --path 传 tmp_path
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest


# 让 import 能找到 scripts/
SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent / "scripts"
REPLAY_SCRIPT = SCRIPTS_DIR / "replay_agent_trace.py"


# =========================================================================
# Fixtures
# =========================================================================
def _make_event(
    *, request_id="r11111111", session_id="s22222222", workflow="preview",
    step=0, tool="parse_jd", latency_ms=18, status="success",
    error_type=None, input_size=1024, output_size=512, ts="2026-06-27T19:00:00",
) -> dict:
    return {
        "ts": ts,
        "request_id": request_id,
        "session_id": session_id,
        "workflow": workflow,
        "step": step,
        "tool": tool,
        "latency_ms": latency_ms,
        "status": status,
        "error_type": error_type,
        "input_size": input_size,
        "output_size": output_size,
    }


@pytest.fixture
def sample_jsonl(tmp_path):
    """构造 mock JSONL: 2 个 request_id 各 3 条 + 1 个其他 request"""
    p = tmp_path / "trace.jsonl"
    events = []
    # request 1: 3 steps
    for i in range(3):
        events.append(_make_event(
            request_id="r11111111", session_id="s22222222",
            workflow="preview", step=i,
            tool=["parse_jd", "match_score", "rewrite_highlights"][i],
            latency_ms=10 + i, status="success",
            input_size=1000 + i, output_size=500 + i,
            ts=f"2026-06-27T19:00:0{i}",
        ))
    # request 2: 3 steps(同 session)
    for i in range(3):
        events.append(_make_event(
            request_id="r33333333", session_id="s22222222",
            workflow="generate", step=i,
            tool=["parse_jd", "match_score", "rewrite_highlights"][i],
            latency_ms=20 + i, status="success",
            input_size=2000 + i, output_size=600 + i,
            ts=f"2026-06-27T19:01:0{i}",
        ))
    # 第三个 request(无关)
    events.append(_make_event(
        request_id="r99999999", session_id="", workflow="preview",
        step=0, tool="parse_jd", latency_ms=5, status="success",
        ts="2026-06-27T19:02:00",
    ))
    p.write_text(
        "\n".join(json.dumps(e, ensure_ascii=False) for e in events) + "\n",
        encoding="utf-8",
    )
    return p


@pytest.fixture
def replay_module():
    """import replay_agent_trace 模块"""
    sys.path.insert(0, str(SCRIPTS_DIR))
    try:
        import replay_agent_trace as mod
        return mod
    finally:
        sys.path.pop(0)


# =========================================================================
# TestReplayFilter
# =========================================================================
class TestReplayFilter:
    """replay 按 request_id / session_id 过滤"""

    def test_filter_by_request_id_returns_only_matching_events(self, sample_jsonl, replay_module):
        """按 request_id 过滤 → 只返同 workflow 的 steps"""
        events = list(replay_module._read_jsonl(sample_jsonl))
        result = replay_module.filter_events(events, request_id="r11111111", session_id=None)
        assert len(result) == 3, f"应返 3 条, 实际 {len(result)}"
        assert all(e["request_id"] == "r11111111" for e in result)

    def test_filter_by_session_id_returns_all_workflows(self, sample_jsonl, replay_module):
        """按 session_id 过滤 → 跨多次 workflow 全部 steps"""
        events = list(replay_module._read_jsonl(sample_jsonl))
        result = replay_module.filter_events(events, request_id=None, session_id="s22222222")
        # 2 个 request 各 3 steps, 共 6 条
        assert len(result) == 6, f"应返 6 条, 实际 {len(result)}"
        rids = {e["request_id"] for e in result}
        assert rids == {"r11111111", "r33333333"}

    def test_no_id_returns_empty_list(self, sample_jsonl, replay_module):
        """不传 request_id 也不传 session_id → 返空列表(spec: 必须显式选)"""
        events = list(replay_module._read_jsonl(sample_jsonl))
        result = replay_module.filter_events(events, request_id=None, session_id=None)
        assert result == []


# =========================================================================
# TestReplayMarkdown
# =========================================================================
class TestReplayMarkdown:
    """markdown 摘要渲染"""

    def test_markdown_contains_required_metadata(self, replay_module):
        """markdown 顶部必须有 request_id / workflow / session_id / steps / total_latency_ms"""
        events = [
            _make_event(
                request_id="r11111111", session_id="s22222222",
                workflow="preview", step=0, tool="parse_jd", latency_ms=18,
                input_size=1024, output_size=512,
            ),
            _make_event(
                request_id="r11111111", session_id="s22222222",
                workflow="preview", step=1, tool="match_score", latency_ms=20,
                input_size=500, output_size=300,
            ),
        ]
        md = replay_module.render_markdown(events)
        assert "request_id:" in md
        assert "workflow:" in md
        assert "session_id:" in md
        assert "steps:" in md
        assert "total_latency_ms:" in md
        assert "38" in md  # 18 + 20

    def test_markdown_table_has_correct_columns(self, replay_module):
        """markdown 表格含 7 列: step/tool/latency_ms/status/error_type/input_size/output_size"""
        events = [_make_event(step=0, tool="parse_jd")]
        md = replay_module.render_markdown(events)
        for col in ("step", "tool", "latency_ms", "status", "error_type", "input_size", "output_size"):
            assert col in md, f"表格缺列 {col}"
        # 表格头格式校验
        assert "| step | tool | latency_ms | status | error_type | input_size | output_size |" in md

    def test_markdown_does_not_leak_raw_sensitive_content(self, replay_module):
        """markdown 不输出原始字段 dict body / 任何 jd_text / bullet 原文"""
        events = [
            _make_event(
                request_id="r11111111", step=0, tool="parse_jd",
                latency_ms=18, status="success", input_size=1024, output_size=512,
            ),
        ]
        # 即使 event 含敏感 dict 字段, 渲染函数也不输出
        events[0]["jd_text"] = "敏感 JD 描述"
        events[0]["bullet"] = "敏感 bullet 描述"
        events[0]["email"] = "user@example.com"

        md = replay_module.render_markdown(events)
        assert "敏感 JD 描述" not in md
        assert "敏感 bullet 描述" not in md
        assert "user@example.com" not in md
        # 但 input_size 这种字段值允许出现在表格里(只是数字)
        assert "1024" in md


# =========================================================================
# TestReplayScript (subprocess)
# =========================================================================
class TestReplayScript:
    """命令行入口测试"""

    def _run_replay(self, *args, jsonl_path=None):
        """辅助: 用 --path 指向 tmp_path 跑 replay"""
        cmd = [
            sys.executable,
            str(REPLAY_SCRIPT),
            *args,
        ]
        if jsonl_path is not None:
            cmd.extend(["--path", str(jsonl_path)])
        result = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8",
        )
        return result

    def test_cli_with_request_id_outputs_markdown(self, sample_jsonl):
        """cli --request-id r11111111 → 输出 markdown 摘要"""
        result = self._run_replay("--request-id", "r11111111", jsonl_path=sample_jsonl)
        assert result.returncode == 0, f"exit 非 0: {result.stderr}"
        out = result.stdout
        assert "# Agent Trace Replay" in out
        assert "r11111111" in out
        assert "parse_jd" in out
        assert "match_score" in out

    def test_cli_with_session_id_outputs_markdown(self, sample_jsonl):
        """cli --session-id s22222222 → 输出跨 workflow 摘要"""
        result = self._run_replay("--session-id", "s22222222", jsonl_path=sample_jsonl)
        assert result.returncode == 0, f"exit 非 0: {result.stderr}"
        out = result.stdout
        assert "r11111111" in out
        assert "r33333333" in out

    def test_cli_without_id_exits_nonzero(self, sample_jsonl):
        """cli 不传 id → 报错退出(非 0)"""
        result = self._run_replay(jsonl_path=sample_jsonl)
        assert result.returncode != 0, "应报错退出"


# =========================================================================
# TestReplayRobustness
# =========================================================================
class TestReplayRobustness:
    """坏行 / 文件不存在 — 不抛"""

    def test_corrupt_jsonl_line_is_skipped(self, tmp_path, replay_module):
        """坏行(json 解析失败)静默跳过, 不阻断"""
        p = tmp_path / "corrupt.jsonl"
        p.write_text(
            json.dumps(_make_event()) + "\n"  # 1 行 good
            "这不是 JSON 这行是垃圾\n"  # 坏行
            + json.dumps(_make_event(step=1)) + "\n",  # 1 行 good
            encoding="utf-8",
        )
        events = list(replay_module._read_jsonl(p))
        assert len(events) == 2, f"坏行被跳过, 应剩 2 条, 实际 {len(events)}"

    def test_missing_jsonl_file_returns_empty(self, tmp_path, replay_module):
        """文件不存在 → 返空 events, 不抛"""
        p = tmp_path / "no_such_file.jsonl"
        events = list(replay_module._read_jsonl(p))
        assert events == []


# =========================================================================
# R5-C Phase 5: fallback category 摘要
# =========================================================================
class TestReplayFallbackSummary:
    """R5-C Phase 5: summarize_fallback() + markdown Fallback Summary 段"""

    def test_fallback_summary_none_when_no_errors(self, replay_module):
        """events 全 success / skipped → category=none, error_count=0"""
        events = [
            _make_event(step=0, tool=None, status="skipped"),
            _make_event(step=1, tool="parse_jd", status="success"),
            _make_event(step=2, tool="match_score", status="success"),
        ]
        fb = replay_module.summarize_fallback(events)
        assert fb["category"] == replay_module.FALLBACK_CATEGORY_NONE
        assert fb["error_count"] == 0
        assert fb["tool_errors"] == []

    def test_fallback_summary_tool_error_when_status_error(self, replay_module):
        """有 status=error → category=tool_error_fallback + tool_errors 含 step/tool/error_type"""
        events = [
            _make_event(step=1, tool="parse_jd", status="success"),
            _make_event(
                step=2, tool="match_score", status="error",
                error_type="TOOL_ARGS_INVALID",
            ),
            _make_event(
                step=3, tool="rewrite_highlights", status="error",
                error_type="LLM_DISABLED",
            ),
        ]
        fb = replay_module.summarize_fallback(events)
        assert fb["category"] == replay_module.FALLBACK_CATEGORY_TOOL_ERROR
        assert fb["error_count"] == 2
        assert len(fb["tool_errors"]) == 2
        # 每条 tool_error 只含 step/tool/error_type,不含原文
        for e in fb["tool_errors"]:
            assert set(e.keys()) == {"step", "tool", "error_type"}
        assert fb["tool_errors"][0]["step"] == 2
        assert fb["tool_errors"][0]["tool"] == "match_score"
        assert fb["tool_errors"][0]["error_type"] == "TOOL_ARGS_INVALID"

    def test_markdown_contains_fallback_summary_section(self, replay_module):
        """render_markdown 输出必含 '## Fallback Summary' 段 + category 行"""
        events = [_make_event(step=1, tool="parse_jd", status="success")]
        md = replay_module.render_markdown(events)
        assert "## Fallback Summary" in md
        assert "- category:" in md
        assert "`none`" in md
        assert "- error_steps:" in md
        assert "- tool_errors:" in md


# =========================================================================
# R5-C Phase 5: tools_used 交叉验证
# =========================================================================
class TestReplayToolsCrossValidation:
    """R5-C Phase 5: cross_validate_tools_used() + render_tools_cross_validation()"""

    def test_cross_validate_ok_when_all_matched(self, replay_module):
        """expected 完全覆盖 trace observed → status=ok, missing/unexpected 都空"""
        events = [
            _make_event(step=1, tool="parse_jd", status="success"),
            _make_event(step=2, tool="retrieve_evidence", status="success"),
        ]
        cross = replay_module.cross_validate_tools_used(
            events, ["parse_jd", "retrieve_evidence"],
        )
        assert cross["status"] == replay_module.CROSS_VALIDATE_OK
        assert sorted(cross["matched"]) == ["parse_jd", "retrieve_evidence"]
        assert cross["missing"] == []
        assert cross["unexpected"] == []
        # observed 顺序按调用顺序(去重)
        assert cross["observed"] == ["parse_jd", "retrieve_evidence"]

    def test_cross_validate_missing_when_expected_absent(self, replay_module):
        """expected 含 trace 没出现过的工具 → status=missing"""
        events = [
            _make_event(step=1, tool="parse_jd", status="success"),
            _make_event(step=2, tool="match_score", status="success"),
        ]
        cross = replay_module.cross_validate_tools_used(
            events, ["parse_jd", "rewrite_highlights"],
        )
        assert cross["status"] == replay_module.CROSS_VALIDATE_MISSING
        assert cross["matched"] == ["parse_jd"]
        assert cross["missing"] == ["rewrite_highlights"]
        # observed 里出现的 match_score 是 unexpected
        assert "match_score" in cross["unexpected"]

    def test_cross_validate_unexpected_when_trace_extra(self, replay_module):
        """trace 比 expected 多工具 → status=unexpected(没 missing)"""
        events = [
            _make_event(step=1, tool="parse_jd", status="success"),
            _make_event(step=2, tool="retrieve_evidence", status="success"),
            _make_event(step=3, tool="match_score", status="success"),
        ]
        # expected 只列 retrieve_evidence → trace 里有 parse_jd / match_score 是 unexpected
        cross = replay_module.cross_validate_tools_used(events, ["retrieve_evidence"])
        assert cross["status"] == replay_module.CROSS_VALIDATE_UNEXPECTED
        assert cross["matched"] == ["retrieve_evidence"]
        assert cross["missing"] == []
        assert sorted(cross["unexpected"]) == ["match_score", "parse_jd"]

    def test_cross_validate_empty_when_no_expected(self, replay_module):
        """expected=None 或 [] → status=empty, 不输出 Cross-Validation 段"""
        events = [_make_event(step=1, tool="parse_jd")]
        cross = replay_module.cross_validate_tools_used(events, None)
        assert cross["status"] == replay_module.CROSS_VALIDATE_EMPTY
        # render 返空 list
        rendered = replay_module.render_tools_cross_validation(cross)
        assert rendered == []

        cross2 = replay_module.cross_validate_tools_used(events, [])
        assert cross2["status"] == replay_module.CROSS_VALIDATE_EMPTY

    def test_render_tools_cross_validation_only_outputs_safe_fields(self, replay_module):
        """render_tools_cross_validation 输出只含工具名字符串, 不含原文"""
        events = [_make_event(step=1, tool="parse_jd")]
        events[0]["jd_text"] = "敏感 JD 描述"
        events[0]["bullet"] = "敏感 bullet 描述"
        events[0]["email"] = "user@example.com"

        cross = replay_module.cross_validate_tools_used(events, ["parse_jd"])
        rendered = "\n".join(replay_module.render_tools_cross_validation(cross))
        assert "## Tools Cross-Validation" in rendered
        assert "`parse_jd`" in rendered
        assert "敏感 JD 描述" not in rendered
        assert "敏感 bullet 描述" not in rendered
        assert "user@example.com" not in rendered

    def test_cli_with_tools_used_outputs_cross_validation(self, sample_jsonl):
        """cli 传 --tools-used 触发 Cross-Validation 段"""
        cmd = [
            sys.executable,
            str(REPLAY_SCRIPT),
            "--request-id", "r11111111",
            "--path", str(sample_jsonl),
            "--tools-used", "parse_jd,retrieve_evidence",
        ]
        result = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8",
        )
        assert result.returncode == 0, f"exit 非 0: {result.stderr}"
        out = result.stdout
        assert "## Tools Cross-Validation (R5-C Phase 5)" in out
        assert "- status:" in out
        # sample_jsonl fixture 里 parse_jd / match_score / rewrite_highlights 出现
        # expected 是 parse_jd / retrieve_evidence → match_score / rewrite_highlights 是 unexpected
        # (retrieve_expected 是 missing)
        assert "missing" in out.lower()
        assert "unexpected" in out.lower()

    def test_cli_without_tools_used_hides_cross_validation(self, sample_jsonl):
        """cli 不传 --tools-used → 不输出 Cross-Validation 段(spec §6.2 默认不显示)"""
        cmd = [
            sys.executable,
            str(REPLAY_SCRIPT),
            "--request-id", "r11111111",
            "--path", str(sample_jsonl),
        ]
        result = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8",
        )
        assert result.returncode == 0
        assert "## Tools Cross-Validation" not in result.stdout
        # 但 Fallback Summary 默认总是输出
        assert "## Fallback Summary" in result.stdout


# =========================================================================
# R5-C Phase 5: PII 安全 (replay 任何新增段都不能泄漏原文)
# =========================================================================
class TestReplayPiiSafetyR5C:
    """R5-C Phase 5: 新增 fallback summary + cross-validation 段也不输出原文"""

    def test_fallback_summary_does_not_leak_raw_content(self, replay_module):
        """fallback summary 段不含 jd_text / bullet / email / PII"""
        events = [
            _make_event(
                step=1, tool="match_score", status="error",
                error_type="TOOL_ARGS_INVALID",
            ),
        ]
        # 注入敏感字段
        events[0]["jd_text"] = "JD 全文含敏感关键词"
        events[0]["bullet"] = "bullet 原文"
        events[0]["email"] = "user@example.com"
        events[0]["input"] = {"text": "敏感输入"}

        md = replay_module.render_markdown(events)
        # Fallback Summary 段必含 category + error_steps + tool_errors 但不含原文
        assert "## Fallback Summary" in md
        assert "JD 全文含敏感关键词" not in md
        assert "bullet 原文" not in md
        assert "user@example.com" not in md
        assert "敏感输入" not in md
        # 但 schema 字段(input_size / output_size 这些数字)允许出现
        assert "1024" in md  # input_size from fixture

    def test_full_render_with_both_features_keeps_pii_safe(self, replay_module):
        """render_markdown + render_tools_cross_validation 联动时, 全段都不含 PII"""
        events = [
            _make_event(step=1, tool="parse_jd", status="success"),
            _make_event(
                step=2, tool="match_score", status="error",
                error_type="TOOL_ARGS_INVALID",
            ),
        ]
        events[0]["jd_text"] = "敏感 JD"
        events[1]["args"] = {"role": "tech_metric", "text": "敏感参数"}

        md = replay_module.render_markdown(events)
        cross = replay_module.cross_validate_tools_used(events, ["parse_jd"])
        cross_md = "\n".join(replay_module.render_tools_cross_validation(cross))
        full = md + "\n" + cross_md

        # 任何原文都不应出现
        for forbidden in ("敏感 JD", "敏感参数", "tech_metric"):
            assert forbidden not in full, f"PII 泄漏: {forbidden}"


# =========================================================================
# R5-C Phase 5: cross_validate 容错
# =========================================================================
class TestReplayRobustnessR5C:
    """R5-C Phase 5: cross_validate 在 malformed events 上不抛"""

    def test_cross_validate_handles_malformed_events(self, replay_module):
        """events 里含 None tool / 空 tool / 非 str tool 时 cross-validate 不抛, 且不污染 observed"""
        events = [
            {"request_id": "r1", "step": 0, "tool": None, "status": "skipped"},  # 本地步骤 → 跳过
            {"request_id": "r1", "step": 1, "tool": "", "status": "success"},    # 空 tool → 跳过
            {"request_id": "r1", "step": 2, "tool": "parse_jd", "status": "success"},
            {"request_id": "r1", "step": 3, "tool": 12345, "status": "success"},  # 非 str → 跳过
            {"request_id": "r1", "step": 4, "tool": ["list"], "status": "success"},  # list → 跳过
            {"request_id": "r1", "step": 5},  # 缺字段 → 跳过
        ]
        cross = replay_module.cross_validate_tools_used(events, ["parse_jd"])
        # 不抛
        assert cross["status"] == replay_module.CROSS_VALIDATE_OK
        # observed 只含 str 类型工具名
        assert cross["observed"] == ["parse_jd"]
        assert "" not in cross["observed"]
        assert "12345" not in cross["observed"]
        assert "None" not in cross["observed"]

    def test_summarize_fallback_handles_malformed_events(self, replay_module):
        """events 缺 status / error_type 字段时 summarize_fallback 不抛"""
        events = [
            {"request_id": "r1", "step": 0},  # 缺 status / error_type
            {"request_id": "r1", "step": 1, "status": "success"},
        ]
        fb = replay_module.summarize_fallback(events)
        # 无 status=error → category=none
        assert fb["category"] == replay_module.FALLBACK_CATEGORY_NONE
        assert fb["error_count"] == 0
        assert fb["tool_errors"] == []