"""R6-K: LLM 端点 circuit breaker.

R6-H live eval v2 closeout 暴露 LLM 端点稳定性风险 (32 分钟 LLM 端点卡 0 trace,
chat panel 用户场景下用户会被卡 32 分钟)。本模块提供轻量级 circuit breaker
状态机, 集成到 LLM slot 抽取路径, 端点连续 fail / 单次 hang → 自动切 rules
默认, 60s 后 probe 重连。

设计原则:
  - 纯 stdlib (dataclass + time), 无外部依赖
  - 模块级单例 (chat panel 是单用户, 不需要 lock)
  - 不 mutate 任何 session / module-level state
  - 状态机: closed → open → half_open → closed/open
  - 线程安全: 假定 chat panel 单进程单线程 (uvicorn 异步仍串行调用 LLM)
  - 隐私: 不写 trace / 日志 / API key / user_message

跟 R6-K spec §2.2 / §2.3 严格对齐。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field


# ----------------------------------------------------------------------
# State constants
# ----------------------------------------------------------------------
CIRCUIT_CLOSED: str = "closed"
CIRCUIT_OPEN: str = "open"
CIRCUIT_HALF_OPEN: str = "half_open"


# ----------------------------------------------------------------------
# Thresholds (env-overridable by test fixtures; 生产用默认)
# ----------------------------------------------------------------------
DEFAULT_FAIL_THRESHOLD: int = 3
DEFAULT_OPEN_SECONDS: float = 60.0


@dataclass
class CircuitBreaker:
    """单进程 circuit breaker 状态机.

    State transitions:
      closed → open:    record_failure × fail_threshold 累计, 或 record_hang 立即
      open → half_open: 60s 后下一次 allow_request() 自动转 half_open
      half_open → closed: record_success (probe 成功)
      half_open → open:   record_failure / record_hang (probe 失败, 再 60s)
    """

    fail_threshold: int = DEFAULT_FAIL_THRESHOLD
    open_seconds: float = DEFAULT_OPEN_SECONDS
    # Internal state
    _state: str = field(default=CIRCUIT_CLOSED, init=False)
    _fail_count: int = field(default=0, init=False)
    _opened_at: float = field(default=0.0, init=False)

    def state(self) -> str:
        """当前状态 (考虑 open 60s 后是否应转 half_open)."""
        if self._state == CIRCUIT_OPEN and (time.time() - self._opened_at) >= self.open_seconds:
            self._state = CIRCUIT_HALF_OPEN
        return self._state

    def allow_request(self) -> bool:
        """是否允许下一次 LLM 调用. half_open 状态算 1 次 probe 机会."""
        current = self.state()
        return current in (CIRCUIT_CLOSED, CIRCUIT_HALF_OPEN)

    def record_success(self) -> None:
        """LLM 调用成功. closed / half_open 都会重置到 closed."""
        self._state = CIRCUIT_CLOSED
        self._fail_count = 0
        self._opened_at = 0.0

    def record_failure(self) -> None:
        """LLM 调用失败 (HTTP 4xx/5xx / URLError / envelope parse 等).
        closed 状态累计 fail_count, 达到 fail_threshold → open.
        half_open 状态立即转 open (probe 失败)."""
        if self.state() == CIRCUIT_HALF_OPEN:
            self._open_now()
            return
        self._fail_count += 1
        if self._fail_count >= self.fail_threshold:
            self._open_now()

    def record_hang(self) -> None:
        """LLM 调用 hang (单次 timeout). 立即 open, 不等累计."""
        self._open_now()

    def time_until_probe(self) -> float:
        """距下次 half_open probe 的剩余秒数. closed / half_open 返回 0."""
        if self._state != CIRCUIT_OPEN:
            return 0.0
        elapsed = time.time() - self._opened_at
        remaining = self.open_seconds - elapsed
        return max(0.0, remaining)

    def snapshot(self) -> dict:
        """供 API 响应透传的状态快照. 字段: state + remaining_seconds."""
        return {
            "circuit_state": self.state(),
            "circuit_remaining_seconds": self.time_until_probe(),
        }

    def _open_now(self) -> None:
        self._state = CIRCUIT_OPEN
        self._opened_at = time.time()
        self._fail_count = 0


# ----------------------------------------------------------------------
# 模块级单例
# ----------------------------------------------------------------------
_CIRCUIT: CircuitBreaker = CircuitBreaker()


def get_circuit() -> CircuitBreaker:
    """获取全局 circuit breaker 单例. 测试用 reset_circuit() 重置."""
    return _CIRCUIT


def reset_circuit() -> None:
    """重置单例到 closed 状态. 仅测试用 (生产代码不应调)."""
    global _CIRCUIT
    _CIRCUIT = CircuitBreaker()


__all__ = [
    "CIRCUIT_CLOSED",
    "CIRCUIT_OPEN",
    "CIRCUIT_HALF_OPEN",
    "DEFAULT_FAIL_THRESHOLD",
    "DEFAULT_OPEN_SECONDS",
    "CircuitBreaker",
    "get_circuit",
    "reset_circuit",
]
