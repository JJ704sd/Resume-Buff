"""R6-K: LLM 端点 circuit breaker 单测.

来源: .harness/docs/round6-k-llm-resilience-spec.md §2
覆盖 CircuitBreaker class 状态机 + 模块级单例.

R6-K 严格不做清单保持:
  - 不改 core/interview_prompts.py / core/interview_llm.py retry/schema/token
  - 不改 PROMPT_VERSIONS
  - 不引入新 LLM 调用
  - 不引入新依赖
"""
from __future__ import annotations

import time

import pytest

from core.llm_circuit_breaker import (
    CIRCUIT_CLOSED,
    CIRCUIT_HALF_OPEN,
    CIRCUIT_OPEN,
    CircuitBreaker,
    get_circuit,
    reset_circuit,
)


# ======================================================================
# CircuitBreaker class 状态机
# ======================================================================
class TestCircuitBreakerStateMachine:
    """R6-K §2.2 状态机: closed → open → half_open → closed/open."""

    def test_initial_state_is_closed(self):
        """新 CircuitBreaker 默认 closed."""
        cb = CircuitBreaker()
        assert cb.state() == CIRCUIT_CLOSED
        assert cb.allow_request() is True
        assert cb.time_until_probe() == 0.0

    def test_single_hang_immediately_opens_circuit(self):
        """单次 hang (TimeoutError) 立即 open, 不等累计阈值."""
        cb = CircuitBreaker(fail_threshold=3, open_seconds=60.0)
        cb.record_hang()
        assert cb.state() == CIRCUIT_OPEN
        assert cb.allow_request() is False
        # 倒计时约 60s (允许 ±1s 测试 jitter)
        remaining = cb.time_until_probe()
        assert 59.0 <= remaining <= 61.0

    def test_three_consecutive_failures_open_circuit(self):
        """3 次连续 failure (低于阈值) → open. 1-2 次不 open."""
        cb = CircuitBreaker(fail_threshold=3, open_seconds=60.0)
        cb.record_failure()
        assert cb.state() == CIRCUIT_CLOSED
        cb.record_failure()
        assert cb.state() == CIRCUIT_CLOSED
        cb.record_failure()
        assert cb.state() == CIRCUIT_OPEN

    def test_success_resets_failure_count(self):
        """中间一次 success 重置 fail_count, 后续 3 次 failure 才 open."""
        cb = CircuitBreaker(fail_threshold=3, open_seconds=60.0)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()  # 重置
        cb.record_failure()
        cb.record_failure()
        # 此时 fail_count=2 (中间重置过), 不应 open
        assert cb.state() == CIRCUIT_CLOSED

    def test_open_to_half_open_after_timeout(self):
        """open 60s 后下一次 state() 调自动转 half_open."""
        cb = CircuitBreaker(fail_threshold=3, open_seconds=0.1)
        cb.record_hang()
        assert cb.state() == CIRCUIT_OPEN
        time.sleep(0.15)  # 等过 open_seconds
        # state() 内部自动检查时间, 返回 half_open
        assert cb.state() == CIRCUIT_HALF_OPEN
        # half_open 状态允许请求 (probe 机会)
        assert cb.allow_request() is True
        # 但 time_until_probe 仍 0 (half_open 状态)
        assert cb.time_until_probe() == 0.0

    def test_half_open_success_closes_circuit(self):
        """half_open probe 成功 → closed."""
        cb = CircuitBreaker(fail_threshold=3, open_seconds=0.1)
        cb.record_hang()
        time.sleep(0.15)
        assert cb.state() == CIRCUIT_HALF_OPEN
        cb.record_success()
        assert cb.state() == CIRCUIT_CLOSED
        assert cb.allow_request() is True

    def test_half_open_failure_returns_to_open(self):
        """half_open probe 失败 → open (再 60s)."""
        # 用 60s 默认 open_seconds (跟生产一致), 但用 fail_threshold=3 减少 setup 开销
        cb = CircuitBreaker(fail_threshold=3, open_seconds=60.0)
        # 手动设置 _opened_at 为 100s 前 (模拟 60s+ 已过)
        cb._state = CIRCUIT_OPEN
        cb._opened_at = time.time() - 100.0
        # state() 内部会转 half_open (因为已过 60s)
        assert cb.state() == CIRCUIT_HALF_OPEN
        # probe 失败 → open (新 _opened_at = time.time())
        cb.record_failure()
        assert cb.state() == CIRCUIT_OPEN
        # 立即 time_until_probe 应该 ≈ 60s (新打开的周期)
        remaining = cb.time_until_probe()
        assert 59.0 <= remaining <= 61.0

    def test_snapshot_format(self):
        """snapshot() 返 {circuit_state, circuit_remaining_seconds} 给 API 透传."""
        cb = CircuitBreaker()
        snap = cb.snapshot()
        assert "circuit_state" in snap
        assert "circuit_remaining_seconds" in snap
        assert snap["circuit_state"] == CIRCUIT_CLOSED
        assert snap["circuit_remaining_seconds"] == 0.0

        cb.record_hang()
        snap = cb.snapshot()
        assert snap["circuit_state"] == CIRCUIT_OPEN
        assert 59.0 <= snap["circuit_remaining_seconds"] <= 61.0


# ======================================================================
# 模块级单例
# ======================================================================
class TestModuleLevelSingleton:
    """模块级 _CIRCUIT 单例, 测试用 reset_circuit() 隔离."""

    def setup_method(self):
        """每个 case 前重置单例 (避免测试间污染)."""
        reset_circuit()

    def test_get_circuit_returns_singleton(self):
        """多次 get_circuit() 返同一 instance."""
        c1 = get_circuit()
        c2 = get_circuit()
        assert c1 is c2

    def test_reset_circuit_returns_to_closed(self):
        """reset_circuit() 把单例重置为 closed (用于测试隔离)."""
        cb = get_circuit()
        cb.record_hang()
        assert cb.state() == CIRCUIT_OPEN
        reset_circuit()
        assert get_circuit().state() == CIRCUIT_CLOSED
        assert get_circuit().allow_request() is True
