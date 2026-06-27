"""
core/logger 模块测试

R4-A: log_agent_trace 函数 — 写 agent loop 推理链路 trace
  锁点:
    1. 文件创建: backend/logs/agent_trace.log(此处用 monkeypatch 替换路径)
    2. 格式: [ISO 时间] session=xxx step=N tool=xxx latency_ms=N outcome=xxx
    3. 字段完整性: 5 字段全在
    4. append 模式: 多次调用累积, 旧 log 不丢
    5. 隐私: 不写 message content / bullet 内容

R5-A Phase 2: log_agent_trace_jsonl 函数 — 结构化 JSONL trace
  锁点(新 9 case):
    1.  文件创建 + JSONL 一行一个 JSON
    2.  字段完整性(11 字段稳定 schema)
    3.  append 模式
    4.  ts 自动补齐
    5.  tool=None 时序列化为 null(本地步骤)
    6.  error_type=None 时序列化为 null(成功)
    7.  输入非 dict 时静默忽略
    8.  写入失败(OSError)时静默降级不抛
    9.  不写完整 JD / bullet / 邮箱 / 电话(隐私边界)
"""
import json
import re

import pytest

import core.logger
from core.logger import log_agent_trace, log_agent_trace_jsonl, JSONL_TRACE_FIELDS


# =========================================================================
# R4-A fixtures + 测试(保留)
# =========================================================================
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


# =========================================================================
# R5-A Phase 2 fixtures + 测试
# =========================================================================
@pytest.fixture
def jsonl_trace_file(tmp_path, monkeypatch):
    """重定向 agent_trace.jsonl 到 tmp_path, 避免污染 backend/logs/"""
    p = tmp_path / "agent_trace.jsonl"
    monkeypatch.setattr(core.logger, "AGENT_TRACE_JSONL_PATH", p)
    return p


class TestLogAgentTraceJsonlSchema:
    """R5-A Phase 2: JSONL trace schema 锁定(11 字段固定)— 4 case"""

    def test_jsonl_fields_constant_has_11_required_fields(self):
        """JSONL_TRACE_FIELDS 必须含 spec §7.1 + Phase 2 任务的 11 字段"""
        expected = {
            "ts", "request_id", "session_id", "workflow", "step", "tool",
            "latency_ms", "status", "error_type", "input_size", "output_size",
        }
        actual = set(JSONL_TRACE_FIELDS)
        assert expected <= actual, f"JSONL schema 缺字段: {expected - actual}, 实际: {actual}"

    def test_creates_jsonl_file_with_one_event_per_line(self, jsonl_trace_file):
        """首次写入 → 文件创建; 多次写入 → 严格每行一个 JSON"""
        for i in range(3):
            log_agent_trace_jsonl({
                "request_id": "r" + "a" * 8,
                "step": i,
                "tool": "parse_jd",
                "status": "success",
                "latency_ms": 10 * i,
            })
        assert jsonl_trace_file.exists()
        lines = jsonl_trace_file.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 3, f"应为 3 行, 实际 {len(lines)}"
        for line in lines:
            event = json.loads(line)  # 必须能 parse 成 JSON
            assert isinstance(event, dict)

    def test_event_has_all_required_fields_with_defaults(self, jsonl_trace_file):
        """写一条最简 event → 11 字段都存在,缺字段自动填默认值"""
        log_agent_trace_jsonl({"step": 0})  # 只传 step
        event = json.loads(jsonl_trace_file.read_text(encoding="utf-8").strip())
        for field in JSONL_TRACE_FIELDS:
            assert field in event, f"event 缺字段 {field}, 实际 keys: {set(event.keys())}"
        # 默认值校验
        assert event["step"] == 0
        assert event["latency_ms"] == 0
        assert event["input_size"] == 0
        assert event["output_size"] == 0
        assert event["ts"]  # 自动补
        assert event["request_id"] == ""
        assert event["session_id"] == ""
        assert event["workflow"] == ""

    def test_append_mode_accumulates_events(self, jsonl_trace_file):
        """append 模式: 多次写累积, 旧内容不丢"""
        for i in range(5):
            log_agent_trace_jsonl({"request_id": f"r{i:08d}", "step": i})
        lines = jsonl_trace_file.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 5
        rids = [json.loads(l)["request_id"] for l in lines]
        assert rids == [f"r{i:08d}" for i in range(5)]


class TestLogAgentTraceJsonlTypes:
    """R5-A Phase 2: 字段类型 + None 处理 — 3 case"""

    def test_ts_auto_filled_if_missing(self, jsonl_trace_file):
        """缺 ts 字段 → 自动用当前 ISO 时间填充(到秒)"""
        log_agent_trace_jsonl({"step": 0, "request_id": "r12345678"})
        event = json.loads(jsonl_trace_file.read_text(encoding="utf-8").strip())
        assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$", event["ts"]), \
            f"ts 不是 ISO 格式: {event['ts']}"

    def test_tool_none_serializes_as_null(self, jsonl_trace_file):
        """tool=None(本地步骤)→ JSONL 中序列化为 null,不是字符串 'None'"""
        log_agent_trace_jsonl({
            "step": 0, "tool": None,
            "status": "skipped", "request_id": "r11111111",
        })
        event = json.loads(jsonl_trace_file.read_text(encoding="utf-8").strip())
        assert event["tool"] is None, f"tool=None 应序列化为 null, 实际: {event['tool']!r}"

    def test_error_type_none_for_success(self, jsonl_trace_file):
        """status=success → error_type=None(JSONL 序列化为 null)"""
        log_agent_trace_jsonl({
            "step": 0, "tool": "parse_jd", "status": "success",
            "request_id": "r22222222",
        })
        event = json.loads(jsonl_trace_file.read_text(encoding="utf-8").strip())
        assert event["error_type"] is None


class TestLogAgentTraceJsonlPrivacy:
    """R5-A Phase 2: 隐私边界 — trace 不写完整 JD / bullet / PII — 2 case"""

    def test_event_with_pii_strings_only_stores_provided_fields(self, jsonl_trace_file):
        """即使调用方误传 PII 字符串(event dict 含这些字段),
        也只写 JSONL schema 规定的 11 字段,不入原文敏感字段到磁盘。

        注意:这是 logger 层的"最后一道防线" — 上层应避免传 PII。
        测试验证即使传了 PII 字段,JSONL 也只写 11 个固定字段,
        不会把 'jd_text' / 'bullet' / 'email' 等意外序列化进文件。
        """
        log_agent_trace_jsonl({
            "step": 0,
            "request_id": "r33333333",
            # 误传的 PII 字段(不在 JSONL_TRACE_FIELDS)
            "jd_text": "完整 JD 描述: 字节跳动 大模型评测实习...",
            "bullet": "完整的 bullet 描述",
            "email": "user@example.com",
            "phone": "13800138000",
        })
        event = json.loads(jsonl_trace_file.read_text(encoding="utf-8").strip())
        # JSONL 只含 11 个 schema 字段,绝不含 PII 字段
        forbidden_fields = {"jd_text", "bullet", "email", "phone", "raw", "content"}
        leaked = forbidden_fields & set(event.keys())
        assert not leaked, f"JSONL 误入 PII 字段: {leaked}"

    def test_long_jd_text_only_counts_in_input_size_not_stored(self, jsonl_trace_file):
        """验证: 调用方把 JD 长度作为 input_size, 原文不入 event dict。
        logger 层不强制长度计算, 但只把 11 schema 字段写出。
        """
        long_jd = "测试 JD 内容" * 100  # 长文本
        log_agent_trace_jsonl({
            "step": 0,
            "tool": "parse_jd",
            "status": "success",
            "request_id": "r44444444",
            "input_size": len(long_jd.encode("utf-8")),  # 只传长度
            # 不传 jd_text
        })
        content = jsonl_trace_file.read_text(encoding="utf-8")
        assert "测试 JD 内容" not in content, "JSONL 不应包含 JD 原文"
        assert "input_size" in content
        event = json.loads(content.strip())
        assert event["input_size"] == len(long_jd.encode("utf-8"))


class TestLogAgentTraceJsonlRobustness:
    """R5-A Phase 2: 鲁棒性 — 异常输入 / IO 失败 — 3 case"""

    def test_non_dict_event_is_silently_ignored(self, jsonl_trace_file):
        """event 不是 dict → 静默忽略, 不抛"""
        log_agent_trace_jsonl("not a dict")  # type: ignore[arg-type]
        log_agent_trace_jsonl(None)  # type: ignore[arg-type]
        log_agent_trace_jsonl(123)  # type: ignore[arg-type]
        # 文件不存在(没成功写过 dict)
        assert not jsonl_trace_file.exists()

    def test_write_failure_does_not_raise(self, monkeypatch, tmp_path):
        """写入失败(模拟 OSError)→ 静默降级, 不抛"""
        broken_path = tmp_path / "broken_dir" / "agent_trace.jsonl"
        monkeypatch.setattr(core.logger, "AGENT_TRACE_JSONL_PATH", broken_path)

        # 不应抛
        log_agent_trace_jsonl({
            "step": 0, "request_id": "r55555555", "status": "success",
        })

    def test_old_log_agent_trace_still_works(self, trace_file, jsonl_trace_file):
        """同时调 R4-A 旧函数 + R5-A Phase 2 新函数, 两个文件都正常写"""
        log_agent_trace("agent_compat", 0, "evaluate_bullet_jd_match", 100, "tool_executed")
        log_agent_trace_jsonl({
            "step": 0, "request_id": "r66666666", "tool": "evaluate_bullet_jd_match",
            "latency_ms": 100, "status": "success",
        })

        # 旧 log 仍按 R4-A 格式
        old_content = trace_file.read_text(encoding="utf-8")
        assert "session=agent_compat" in old_content
        assert "outcome=tool_executed" in old_content

        # 新 jsonl 按 R5-A Phase 2 schema
        new_event = json.loads(jsonl_trace_file.read_text(encoding="utf-8").strip())
        assert new_event["request_id"] == "r66666666"
        assert new_event["tool"] == "evaluate_bullet_jd_match"
