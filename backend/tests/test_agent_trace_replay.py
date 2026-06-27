"""
R5-A Phase 2: scripts/replay_agent_trace.py 测试

锁点(10 case):
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