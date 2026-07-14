# 简历帮 - pytest 配置文件
# 让 tests/ 下的测试可以直接 import core / api 模块 (把 backend/ 当 root)
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


# R6-K: 跨 module 隔离 LLM 端点 circuit breaker 单例
# R6-K 在 core/llm_circuit_breaker.py 引入模块级单例, R6-C.3 等老测试不 reset
# 全量跑时某个 R6-K 测试触发 circuit open → 后续 module 跑时 _call_llm_for_slot_extraction
# 顶部 circuit check 返 None → urlopen 不被调 → trace 字段不写 → 老测试 fail
# autouse fixture 在每个 test 跑前 reset_circuit, 保证 isolation
@pytest.fixture(autouse=True)
def _r6k_reset_circuit_breaker():
    from core.llm_circuit_breaker import reset_circuit
    reset_circuit()
    yield
    # 不在 teardown reset, 让 R6-K test_circuit_open_forces_rules_mode_in_session 等
    # 显式断言 circuit state 的测试不被 teardown 干扰
