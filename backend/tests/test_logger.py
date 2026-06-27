"""
core/logger 模块测试

R4-A: log_agent_trace 函数 — 写 agent loop 推理链路 trace
  锁点:
    1. 文件创建: backend/logs/agent_trace.log(此处用 monkeypatch 替换路径)
    2. 格式: [ISO 时间] session=xxx step=N tool=xxx latency_ms=N outcome=xxx
    3. 字段完整性: 5 字段全在
    4. append 模式: 多次调用累积, 旧 log 不丢
    5. 隐私: 不写 message content / bullet 内容
"""
import re

import pytest

import core.logger
from core.logger import log_agent_trace


@pytest.fixture
def trace_file(tmp_path, monkeypatch):
    """重定向 agent_trace.log 到 tmp_path, 避免污染 backend/logs/"""
    p = tmp_path / "agent_trace.log"
    monkeypatch.setattr(core.logger, "AGENT_TRACE_PATH", p)
    return p


class TestLogAgentTrace:
    """R4-A: log_agent_trace 写入测试 — 3 case 锁死行为"""

    def test_creates_file_on_first_write(self, trace_file):
        """首次调用应创建文件"""
        assert not trace_file.exists()
        log_agent_trace(
            session_id="agent_abc12345",
            step=0,
            tool_name="evaluate_bullet_jd_match",
            latency_ms=150,
            outcome="tool_executed",
        )
        assert trace_file.exists()
        content = trace_file.read_text(encoding="utf-8")
        assert "session=agent_abc12345" in content
        assert "step=0" in content
        assert "tool=evaluate_bullet_jd_match" in content
        assert "latency_ms=150" in content
        assert "outcome=tool_executed" in content

    def test_format_matches_iso_timestamp_pattern(self, trace_file):
        """格式: [ISO 时间] session=xxx step=N tool=xxx latency_ms=N outcome=xxx"""
        log_agent_trace(
            session_id="agent_xyz",
            step=2,
            tool_name="no_tool",
            latency_ms=87,
            outcome="success_rewrite",
        )
        content = trace_file.read_text(encoding="utf-8").strip()
        # ISO 格式: 2026-06-27T18:00:00 (到秒)
        pattern = re.compile(
            r"^\[\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\] "
            r"session=agent_xyz step=2 tool=no_tool latency_ms=87 outcome=success_rewrite$"
        )
        assert pattern.match(content), f"格式不匹配: {content}"

    def test_append_mode_and_field_completeness(self, trace_file):
        """append 模式: 多次调用累积; 每行 5 字段全在"""
        # 写 3 行不同 step + outcome
        log_agent_trace("agent_a1", 0, "evaluate_bullet_jd_match", 100, "tool_executed")
        log_agent_trace("agent_a1", 1, "no_tool", 50, "schema_fail_fallback")
        log_agent_trace("agent_a1", 3, "no_tool", 0, "max_step_exhausted")

        lines = trace_file.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 3
        # 验证每行 5 字段都在
        for line in lines:
            for field in ("session=", "step=", "tool=", "latency_ms=", "outcome="):
                assert field in line, f"字段 {field} 缺失 in: {line}"
        # 验证每行 outcome 不同
        outcomes = [re.search(r"outcome=(\w+)", l).group(1) for l in lines]
        assert outcomes == ["tool_executed", "schema_fail_fallback", "max_step_exhausted"]
