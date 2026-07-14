# R6-K LLM Resilience — Circuit Breaker + 降级 UI

> **状态**: 草稿待实施
> **作者**: Mavis
> **时间**: 2026-07-14
> **关联**: R6-H live eval v2 closeout (LLM 端点稳定性新 ground truth) + R6-H §5.3 决策表 + R6-H §6 不做清单

---

## 0. 一句话目标

解决 R6-H live v2 暴露的 **LLM 端点稳定性风险** — 32 分钟 LLM 端点卡 0 trace,chat panel 用户场景下用户会被卡 32 分钟。本 round 落 2 个改动:

1. **后端 circuit breaker** — LLM 端点连续 fail / hang → 自动切 rules 默认,60s 后试探
2. **前端降级 UI** — circuit open 时 chat panel 显示 "LLM 端点暂不可用, 已使用规则模式" chip, 倒计时距下次试探, 隐藏 enable_interview_llm toggle

**不改 production LLM 抽取 schema / retry / token / prompt**(R6-H §6 严格不做清单保持)。

---

## 1. 背景 (R6-H live v2 closeout 关联)

R6-H live eval v2 跑分 partial 33% 进度,后 32 分钟 LLM 端点卡 0 trace (具体记录在 `.harness/docs/round6-h-live-eval-v2-llm-stability.md` §1.1)。

**核心风险**:
- chat panel 用户 1 轮对话 30-36s (R6-H live v1 实测)
- 端点挂 32 min = 用户体验灾难
- LLM 端点稳定性 random (R6-H live v1 5.5 min 跑通 vs R6-H live v2 32 min 卡死)
- 协议层 (response_format) 已修, 端点可用性是新维度风险

**R6-H §5.3 决策表没列 "未通过 (LLM 服务稳定性)" 档**,R6-H live v2 closeout 报告 §7.2 新增此档位。本 round 实施对应修复。

---

## 2. 实施 1: 后端 Circuit Breaker

### 2.1 改动文件

- **新建** `backend/core/llm_circuit_breaker.py` (~120 行): circuit breaker state machine 纯 stdlib (无外部依赖)
- **改** `backend/core/interview_agent.py`: 在 `_call_llm_for_slot_extraction` 之前 + `_decide_interview_mode` 之后, 接入 circuit breaker
- **不改** `core/interview_prompts.py` / `core/interview_policy.py` / `core/interview_verifier.py` / `core/llm_rewriter.py` (R6-H §6 锁定)

### 2.2 Circuit Breaker 状态机

```
       [closed]  -- fail × 3 OR hang > 60s × 1 -->  [open]
          ^                                              │
          │                                              │ 60s 后
          │                                              ▼
       [half-open]  <-- probe --------------------  [open]
          │  success
          └──>  [closed]
          │  fail
          └──>  [open] (再等 60s)
```

- **closed (默认)**: LLM 正常调用, 失败计数 +1
- **open**: 跳过 LLM 调用, 强制 rules (mode_warning = "LLM 端点暂不可用 (circuit open), 已使用规则模式")
- **half-open**: 60s 后下一次 LLM 调用试探, 成功 → closed, 失败 → open (再 60s)
- **fail 触发**: network error / JSON parse error / schema error / HTTP 4xx/5xx (跟 R6-A Phase 4 fallback 触发条件一致)
- **hang 触发**: 单次 LLM 调用超过 60s (跟 R6-H timeout = 60s 一致)
- **fail 计数阈值**: 默认 3 次连续失败 → open (避免一次抖动就 open)
- **半开探测**: open 60s 后下一次 LLM 调用自动作为 probe

### 2.3 模块接口 (新文件 `core/llm_circuit_breaker.py`)

```python
# State constants
CIRCUIT_CLOSED: str = "closed"
CIRCUIT_OPEN: str = "open"
CIRCUIT_HALF_OPEN: str = "half_open"

# Thresholds (env-overridable for testing)
DEFAULT_FAIL_THRESHOLD: int = 3
DEFAULT_OPEN_SECONDS: float = 60.0
DEFAULT_HANG_SECONDS: float = 60.0

# Public API
class CircuitBreaker:
    """Thread-unsafe single-process circuit breaker (chat panel 是单用户, 不需要 lock)."""
    
    def __init__(self, fail_threshold=DEFAULT_FAIL_THRESHOLD,
                 open_seconds=DEFAULT_OPEN_SECONDS,
                 hang_seconds=DEFAULT_HANG_SECONDS): ...
    
    def state(self) -> str: ...  # CIRCUIT_CLOSED / OPEN / HALF_OPEN
    
    def allow_request(self) -> bool: ...  # True if should call LLM
    
    def record_success(self) -> None: ...  # close circuit
    
    def record_failure(self) -> None: ...  # increment fail count, may open
    
    def record_hang(self) -> None: ...  # immediately open
    
    def time_until_probe(self) -> float: ...  # seconds until next probe (0 if closed/half_open)
    
    def snapshot(self) -> dict: ...  # for /api/interview/start response (state + remaining_seconds)


# Module-level singleton (chat panel 单用户, 全局 1 个 instance 足够)
_CIRCUIT: CircuitBreaker = CircuitBreaker()

def get_circuit() -> CircuitBreaker: ...
def reset_circuit() -> None: ...  # for tests
```

### 2.4 interview_agent.py 接入

**在 `_call_llm_for_slot_extraction` 之前加 circuit check**:
```python
def _call_llm_for_slot_extraction(slot, user_message, *, turn_index, session, llm_api_key, llm_base_url, llm_model):
    circuit = get_circuit()
    if not circuit.allow_request():
        # circuit open → skip LLM, return None → 走 fallback rules
        return None
    try:
        result = _http_post_with_timeout(...)  # existing R6-A Phase 4 call
        circuit.record_success()
        return result
    except (URLError, TimeoutError, HTTPError, ValueError, KeyError) as e:
        circuit.record_failure()
        if isinstance(e, TimeoutError):
            circuit.record_hang()
        return None
```

**在 `_decide_interview_mode` 之后 / `_do_answer` 之前加 circuit 覆盖**:
```python
def _do_answer(session, user_message):
    # ... existing R6-A Phase 1+2+4 logic ...
    
    # R6-K: circuit breaker override
    circuit = get_circuit()
    if not circuit.allow_request() and session.interview_mode == "llm_assisted":
        session.interview_mode = "rules"  # 强制降级
        session.mode_warning = (
            f"LLM 端点暂不可用 (circuit {circuit.state()}, "
            f"距下次试探 {circuit.time_until_probe():.0f}s), "
            f"已使用规则模式"
        )
    
    # 继续走 _extract_slots (会读 session.interview_mode 决定 llm_enabled)
```

### 2.5 API 响应透传

`/api/interview/start` 响应 `StartResponse` 加 `circuit_state: str` + `circuit_remaining_seconds: float` 字段 (R6-B Phase 2 已加 `interview_mode` + `mode_warning`, 沿用同样 pattern)。

`/api/interview/reply` 响应 `ReplyResponse` 加同样 2 字段 (跟 `extraction_summary` / `question_plan` 同层)。

**字段透传让前端**:
- start: 第一次进入 chat panel 时显示降级状态
- reply: 每次对话后实时更新降级状态 (circuit 可能从 closed → open, 或从 open → half-open → closed)

### 2.6 R6-K 严格不做清单 (R6-H §6 保持)

- **不**改 `core/interview_prompts.py` (LLM prompt 内容)
- **不**改 `core/interview_llm.py` retry / schema / token 策略
- **不**改 `PROMPT_VERSIONS`
- **不**改 `INTERVIEW_POLICY_GAP_CRITICAL_SLOTS`
- **不**改 `INTERVIEW_LLM_NO_KEY_WARNING`
- **不**改 default `enable_interview_llm=False`
- **不**改 `core/interview_verifier.py` sentinel 常量
- **不**挂 pre-push hook
- **不**引入新 LLM 调用 (复用现有 R6-A Phase 4 `_call_llm_for_slot_extraction`)
- **不**引入新依赖 (纯 stdlib + dataclass + time)
- **不**改 `scripts/evaluate_interview_agent.py` (R6-G 锁定脱敏文案)

---

## 3. 实施 2: 前端降级 UI

### 3.1 改动文件

- **改** `frontend/src/api/index.ts`: 加 `CircuitState` type + `InterviewStartResponse.circuit_state` + `circuit_remaining_seconds` + `InterviewReplyResponse.circuit_state` + `circuit_remaining_seconds`
- **改** `frontend/src/components/InterviewAgentPanel.vue`: 加 `circuitState` + `circuitRemainingSeconds` ref + chip 显示 + 倒计时 + 隐藏 toggle
- **不改** `frontend/src/components/InterviewDraftCard.vue` / `frontend/src/App.vue` (隔离 spec §9)

### 3.2 chip 显示规则

| circuit_state | chip 颜色 | chip 文字 | toggle 显示 | 倒计时显示 |
|---|---|---|---|---|
| `closed` | (不显示) | (不显示) | 显示 (用户可手动启 LLM) | (不显示) |
| `open` | 紫红 (el-tag type="danger") | "LLM 端点暂不可用, 已使用规则模式" | **隐藏** (避免用户再启 LLM) | 显示 "距下次试探 Xs" |
| `half-open` | 黄 (el-tag type="warning") | "LLM 端点恢复中, 试探中..." | **隐藏** | (不显示) |

### 3.3 倒计时实现

- 用 `setInterval` 每秒更新 `circuitRemainingSeconds` 倒计时
- 倒计时归零时, 触发后端 `/api/interview/start` 重新调用, 让半开探测结果回流
- circuit_state 变化时, 后端 `/reply` 响应透传, 实时更新

### 3.4 隐私边界 (R6-B §12 + AGENTS.md)

- chip 文字 / 倒计时 / mode_warning 不含 user_message / API key / source_span 明文
- mode_warning 沿用 R6-B Phase 2 锁定 (含 "LLM_API_KEY" 字面量不出现, 通用描述 "LLM 端点")
- circuit_state 字段是 string 枚举 (closed/open/half_open), 不含敏感信息

---

## 4. R6-K 不做

- **不**改 production LLM 抽取 schema / retry / token
- **不**自动切 default `enable_interview_llm=True` (本 round 默认仍 False)
- **不**跑 R6-H live v3 验证 (LLM 端点稳定性 ground truth 已写入 R6-H live v2 closeout, 本 round focus 是改边界)
- **不**改 `core/llm_rewriter.py` (R5-E 锁定)
- **不**改 `scripts/evaluate_prompt_versions.py` / `evaluate_agent_workflow.py` (R5-D §12 #3 锁定)
- **不**扩 eval set (R6-J 锁定 20 条)
- **不**改 PROMPT_VERSIONS / 切 winner (R5-E 锁定)
- **不**做 retry 指数 backoff (留 R6-K+ 后续,本 round focus 是 circuit breaker + 降级 UI)
- **不**做端点挂时切回 rules 默认且前端 disabled toggle (留 (iv) 选项,本 round focus 1+2)

---

## 5. R6-K 验收门槛

- **后端**:
  - 3 个连续 fail → circuit open
  - 60s 后下一次 LLM 调用 → half-open probe
  - half-open probe 成功 → circuit closed
  - half-open probe 失败 → circuit open (再 60s)
  - single hang > 60s → circuit open 立即
  - circuit open 时 session.interview_mode 强制 "rules"
  - circuit open 时 mode_warning 含 "LLM 端点暂不可用"
- **前端**:
  - chip 在 open / half_open 状态显示, closed 状态不显示
  - open 状态显示倒计时, 60s 后自动重试
  - open / half_open 状态隐藏 enable_interview_llm toggle
- **隐私**:
  - chip 文字不含 user_message / API key / source_span
  - mode_warning 不含 "LLM_API_KEY" 字面量

---

## 6. R6-K 风险 + 缓解

| 风险 | 缓解 |
|---|---|
| circuit breaker state 跟 R5-A Phase 3 evidence 路径混用 | circuit breaker 是 LLM-only, 不影响 rules 路径 |
| circuit open 期间用户开启 LLM toggle | 前端 chip 隐藏 toggle (避免 user input 改 mode) |
| circuit state 全局单例跨测试污染 | `reset_circuit()` helper 给 test 调, 测试用 isolated CircuitBreaker 实例 |
| 60s 倒计时在 chat panel UI 跟其他 timer 冲突 | `setInterval` 局部 scope, 组件 unmount 时 clearInterval |
| circuit open 时 LLM 真实端点恢复但 chat panel 没回流 | `/reply` 每次响应都透传 circuit_state, 前端按响应更新 |

---

## 7. R6-K 实施步骤 (预计 2-3 hour)

### Phase 1 — 后端 circuit breaker (1 hour)

1. 写 `backend/core/llm_circuit_breaker.py` (~120 行)
2. 改 `backend/core/interview_agent.py`:
   - `_call_llm_for_slot_extraction` 加 circuit check
   - `_do_answer` 加 circuit 覆盖
   - `interview_mode` / `mode_warning` 字段写 circuit 状态
3. 改 `backend/api/interview.py`:
   - `StartResponse` / `ReplyResponse` / `DraftResponse` 加 `circuit_state` + `circuit_remaining_seconds`
4. 加 2 个新单测 (test_circuit_breaker + test_circuit_breaker_api)

### Phase 2 — 前端降级 UI (1 hour)

1. 改 `frontend/src/api/index.ts`:
   - `CircuitState` type
   - `InterviewStartResponse.circuit_state` + `circuit_remaining_seconds`
   - `InterviewReplyResponse.circuit_state` + `circuit_remaining_seconds`
2. 改 `frontend/src/components/InterviewAgentPanel.vue`:
   - `circuitState` + `circuitRemainingSeconds` ref
   - `onStart` / `onReply` 接收 circuit_state
   - chip 渲染 (按状态变颜色 / 文字)
   - 倒计时 (setInterval)
   - 隐藏 toggle (open / half_open 时)
3. 验证 `vue-tsc --noEmit` 0 error + `npm run build` 成功

### Phase 3 — 收尾 (30 min)

1. 跑主仓全量 `pytest tests/ -q` → 期望 959 + 4-6 R6-K 新 = 963-965 passed
2. 跑 `vue-tsc --noEmit` 0 error + `npm run build` 成功
3. 写 `.harness/docs/round6-k-closeout.md` 收尾报告
4. commit + 推 feat + 合 main + push main (pre-push hook 跑全量 verify)

---

## 8. R6-K 关联文档

- `.harness/docs/round6-h-live-eval-v2-llm-stability.md` — R6-H live v2 closeout (LLM 端点稳定性新 ground truth 起源)
- `.harness/docs/round6-h-live-eval-v2-decision-gate-spec.md` — R6-H 决策门禁 spec
- `.harness/docs/round6-h-live-eval-v2-decision-report.md` — R6-H 决策报告
- `.harness/docs/round6-j-decision-report.md` — R6-J 决策报告
- `.harness/docs/round6-j-eval-set-expansion-spec.md` — R6-J spec

---

(R6-K spec 落地, 2026-07-14, 实施 1+2 启动, owner: Mavis)
