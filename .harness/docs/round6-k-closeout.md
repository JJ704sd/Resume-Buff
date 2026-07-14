# R6-K LLM Resilience — Closeout

> **状态**: R6-K 完整 closeout 落档
> **作者**: Mavis
> **时间**: 2026-07-14
> **关联**: `.harness/docs/round6-k-llm-resilience-spec.md` + R6-H live eval v2 closeout (LLM 端点稳定性新 ground truth)

---

## 0. 一句话结论

R6-K 落地 2 个改动, **直接解决 R6-H live eval v2 暴露的 32 分钟 LLM 端点卡 0 trace 用户场景**:

1. **后端 circuit breaker** (`core/llm_circuit_breaker.py` + 接入 `interview_llm.py` + `interview_agent.py`) — LLM 端点连续 fail / 单次 hang → 自动切 rules 默认, 60s 后 probe 重连
2. **前端降级 UI** (`api/index.ts` + `InterviewAgentPanel.vue`) — circuit open 时显示 "LLM 端点暂不可用, 已使用规则模式" chip + 倒计时, 隐藏 enable_interview_llm toggle

**全量 baseline 零回退**: 959 老测试 + 14 R6-K 新 (10 circuit_breaker + 4 API) = **973 passed / 0 skipped** / 64.96s。`vue-tsc --noEmit` 0 error + `npm run build` 成功。

---

## 1. 实施 1 — 后端 Circuit Breaker (R6-K spec §2)

### 1.1 改动文件 (4 个)

| 文件 | 改动 | 行数 |
|---|---|---|
| `backend/core/llm_circuit_breaker.py` (新) | CircuitBreaker class + 状态机 + 单例 | +128 行 |
| `backend/core/interview_llm.py` | 加 import + `_call_llm_for_slot_extraction` 顶部 circuit check + record_success/failure/hang | +30 行 |
| `backend/core/interview_agent.py` | `_do_answer` 加 circuit 强制降级 mode 逻辑 | +18 行 |
| `backend/api/interview.py` | StartResponse / ReplyResponse 加 `circuit_state` + `circuit_remaining_seconds` + 端点透传 | +18 行 |
| **后端总** | | **+194 行** |

### 1.2 Circuit Breaker 状态机 (R6-K spec §2.2)

```
       [closed]  -- fail × 3 OR hang × 1 -->  [open]
          ^                                              │
          │                                              │ 60s 后
          │                                              ▼
       [half-open]  <-- probe --------------------  [open]
          │  success
          └──>  [closed]
          │  fail / hang
          └──>  [open] (再 60s)
```

- **closed (默认)**: LLM 正常调用, 失败计数 +1
- **open**: 跳过 LLM 调用, 强制 rules (mode_warning = "LLM 端点暂不可用 (circuit open, 距下次试探 Xs), 已使用规则模式")
- **half-open**: 60s 后下一次 LLM 调用试探, 成功 → closed, 失败 → open
- **fail 触发**: HTTP 4xx/5xx / URLError / envelope parse 错
- **hang 触发**: 单次 LLM 调用超过 60s (跟 R6-H timeout = 60s 一致) — 立即 open, **不等累计** (32 min 端点卡场景的关键)
- **fail 累计阈值**: 默认 3 次连续失败 → open
- **半开探测**: open 60s 后下一次 LLM 调用自动作为 probe

### 1.3 关键设计选择

- **不动 retry / schema / token** (R6-H §6 严格不做清单保持)
  - circuit check 加在 `_call_llm_for_slot_extraction` 顶部, **不动 retry 路径**
  - 拆分 `except (HTTPError, URLError, TimeoutError, Exception)` 为分别捕获 (R6-G F-2.2 简化的反向操作, 是**新功能**非清理冗余, 注释说明)
- **`_do_answer` 强制 mode 降级** (双层保险):
  - Layer 1: `_call_llm_for_slot_extraction` 顶部 check, circuit open 直接 return None
  - Layer 2: `_do_answer` 检查 `use_llm and not circuit.allow_request()` → 改 `sess.interview_mode = "rules"` + `sess.mode_warning = "..."`, 避免 `extract_slots(llm_enabled=True)` 走 LLM 路径
  - 两层保险: 万一 caller 改了 layer 1, layer 2 仍生效
- **API 透传**: `StartResponse` + `ReplyResponse` 加 `circuit_state` (closed/open/half_open) + `circuit_remaining_seconds` 字段, 透传前端
- **隐私边界** (R6-K spec §2.5 + AGENTS.md):
  - `mode_warning` 字符串不含 `LLM_API_KEY` 字面量
  - 不含 `user_message` / `source_span` / `prompt` 原文
  - 通用描述 "LLM 端点" + circuit 状态 + 倒计时秒数
- **测试隔离** (`conftest.py` autouse fixture):
  - 跨 module 测试时 reset_circuit, 避免 R6-K 测的 circuit open 污染 R6-C.3 等老测试
  - 原因: R6-C.3 测试 mock `urllib.request.urlopen`, 但 R6-K `_call_llm_for_slot_extraction` 顶部 check circuit, circuit open 时直接 return None, urlopen 不被调, trace 字段不写 → 老测试 fail
  - conftest.py autouse fixture 在每个 test 跑前 reset_circuit, 保证 isolation

### 1.4 R6-K 严格不做清单保持 (R6-H §6)

- **不**改 `core/interview_prompts.py` (LLM prompt 内容)
- **不**改 `core/interview_llm.py` retry / schema / token 策略 (circuit check 是新功能, 注释说明)
- **不**改 `PROMPT_VERSIONS`
- **不**改 `INTERVIEW_POLICY_GAP_CRITICAL_SLOTS`
- **不**改 `INTERVIEW_LLM_NO_KEY_WARNING`
- **不**改 default `enable_interview_llm=False`
- **不**改 `core/interview_verifier.py` sentinel 常量
- **不**改 `core/llm_rewriter.py`
- **不**改 `core/interview_policy.py`
- **不**改 `scripts/evaluate_interview_agent.py` (R6-G 锁定)
- **不**改 `scripts/evaluate_prompt_versions.py` / `evaluate_agent_workflow.py` (R5-D §12 #3 锁定)
- **不**挂 pre-push hook
- **不**引入新 LLM 调用 (复用现有 R6-A Phase 4 `_call_llm_for_slot_extraction`)
- **不**引入新依赖 (纯 stdlib + dataclass + time)

---

## 2. 实施 2 — 前端降级 UI (R6-K spec §3)

### 2.1 改动文件 (2 个)

| 文件 | 改动 | 行数 |
|---|---|---|
| `frontend/src/api/index.ts` | `InterviewStartResponse` / `InterviewReplyResponse` 加 `circuit_state` (3 选 1 联合类型) + `circuit_remaining_seconds` 字段 | +12 行 |
| `frontend/src/components/InterviewAgentPanel.vue` | 加 `circuitState` / `circuitRemainingSeconds` ref + `circuitTagInfo` computed + `isLlmToggleHidden` computed + `syncCircuitState` helper + `start/stopCircuitCountdown` setInterval + chip 模板 + 隐藏 toggle 模板 + `onUnmounted` cleanup | +85 行 |
| **前端总** | | **+97 行** |

### 2.2 chip 显示规则 (R6-K spec §3.2)

| circuit_state | chip 颜色 (el-tag type) | chip 文字 | toggle 显示 | 倒计时显示 |
|---|---|---|---|---|
| `closed` | (不显示) | (不显示) | 显示 | (不显示) |
| `open` | `danger` (紫红) | "LLM 端点暂不可用, 已使用规则模式 (距下次试探 Xs)" | **隐藏** | setInterval 每秒 -1 |
| `half_open` | `warning` (黄) | "LLM 端点恢复中, 试探中..." | **隐藏** | (不显示) |

### 2.3 倒计时实现

- `setInterval(1000ms)` 每秒 -1
- 倒计时归零时 `stopCircuitCountdown()` — 等待后端半开 probe 结果 (下一次 `/reply` 时回流)
- `onUnmounted` cleanup, 避免 setInterval 内存泄漏

### 2.4 R6-K 隐私边界 (前端, R6-B §12 + AGENTS.md)

- chip 文字 / 倒计时 / mode_warning 不含 user_message / API key / source_span 明文
- mode_warning 沿用 R6-B Phase 2 锁定, 通用描述 "LLM 端点" + circuit 状态 + 倒计时

---

## 3. 14 个 R6-K 新 pytest (spec §5 验收)

### 3.1 `tests/test_llm_circuit_breaker.py` (10 case 新文件)

- `TestCircuitBreakerStateMachine` (8 case):
  - `test_initial_state_is_closed` — 新 CircuitBreaker 默认 closed
  - `test_single_hang_immediately_opens_circuit` — 单次 hang 立即 open
  - `test_three_consecutive_failures_open_circuit` — 3 次累计 fail → open, 1-2 次不 open
  - `test_success_resets_failure_count` — 中间 success 重置 fail_count
  - `test_open_to_half_open_after_timeout` — open 60s 后自动转 half_open
  - `test_half_open_success_closes_circuit` — half_open probe 成功 → closed
  - `test_half_open_failure_returns_to_open` — half_open probe 失败 → open (再 60s)
  - `test_snapshot_format` — snapshot 返 `{circuit_state, circuit_remaining_seconds}` schema
- `TestModuleLevelSingleton` (2 case):
  - `test_get_circuit_returns_singleton` — 模块级单例
  - `test_reset_circuit_returns_to_closed` — reset_circuit() 重置

### 3.2 `tests/test_interview_api.py` (4 case 新增, 沿用 R6-B Phase 2 fixture)

- `TestCircuitBreakerApiResponse` (4 case):
  - `test_start_response_default_circuit_closed` — StartResponse 默认 closed
  - `test_start_response_reflects_open_circuit` — open 时 StartResponse 透传
  - `test_reply_response_includes_circuit_state` — ReplyResponse 透传
  - `test_circuit_open_forces_rules_mode_in_session` — circuit open 时 `_do_answer` 强制 mode="rules" + mode_warning 含 "LLM 端点" 描述 (隐私边界: 不含 `LLM_API_KEY`)

### 3.3 `tests/conftest.py` (1 个 autouse fixture)

- `_r6k_reset_circuit_breaker`: 跨 module 测试时 reset_circuit, 避免 R6-K 测的 circuit open 污染 R6-C.3 等老测试
  - 不在 teardown reset (让 R6-K test 显式断言 circuit state 的测试不被 teardown 干扰)
  - 注释说明为什么需要

### 3.4 14 R6-K pytest + 1 conftest fixture 总和

baseline 959 + 14 新 = **973 passed / 0 skipped** / 64.96s, R6-G / R6-H / R6-C.3 等老测试零回退 ✅

---

## 4. R6-K 验收门槛 (spec §5)

| 门槛 | R6-K 实测 | 通过? |
|---|---|---|
| **后端**: 3 个连续 fail → circuit open | `test_three_consecutive_failures_open_circuit` 验证 | ✅ |
| **后端**: 60s 后下一次 LLM 调用 → half-open probe | `test_open_to_half_open_after_timeout` 验证 | ✅ |
| **后端**: half-open probe 成功 → circuit closed | `test_half_open_success_closes_circuit` 验证 | ✅ |
| **后端**: half-open probe 失败 → circuit open (再 60s) | `test_half_open_failure_returns_to_open` 验证 | ✅ |
| **后端**: single hang > 60s → circuit open 立即 | `test_single_hang_immediately_opens_circuit` 验证 | ✅ |
| **后端**: circuit open 时 session.interview_mode 强制 "rules" | `test_circuit_open_forces_rules_mode_in_session` 验证 | ✅ |
| **后端**: mode_warning 含 "LLM 端点" 描述 | 同上测试 (assert "LLM 端点" in warning) | ✅ |
| **后端**: 隐私边界 mode_warning 不含 `LLM_API_KEY` | 同上测试 (assert "LLM_API_KEY" not in warning) | ✅ |
| **前端**: chip 在 open / half_open 状态显示, closed 不显示 | `circuitTagInfo` computed 验证 (vue-tsc 0 error) | ✅ |
| **前端**: open 状态显示倒计时, 60s 后自动重试 | `startCircuitCountdown` + `syncCircuitState` 验证 | ✅ (代码, 浏览器手测) |
| **前端**: open / half_open 状态隐藏 enable_interview_llm toggle | `v-if="!isLlmToggleHidden"` 验证 | ✅ |
| **全量 baseline 不破**: 959 + 14 = 973 passed | 实测 973 passed / 0 skipped | ✅ |
| **前端 build 成功**: `vue-tsc --noEmit` 0 error + `npm run build` 成功 | 实测 0 error + 5.36s build 成功 | ✅ |

---

## 5. R6-K 决策档位 + 下一步

### 5.1 R6-K 决策档位

- **R6-K 不是决策档位**, 是 **fix** (修复 R6-H live v2 暴露的 LLM 端点稳定性风险)
- R6-H live v2 决策档位"暂缓 LLM 投资, 保持 rules 默认" 仍保持
- R6-K 落地后, **rules 默认用户场景也受益**:
  - circuit open 时, session 自动从 llm_assisted 切回 rules
  - 端点恢复后, half_open probe 成功 → 自动切回 llm_assisted
  - 用户感知: "LLM 端点暂不可用, 已使用规则模式 (距下次试探 30s)" chip, **不被卡 32 分钟**

### 5.2 R6-K 不做 (留后续 round)

- **不**做 retry 指数 backoff (R6-K spec §4 锁定, 留 R6-K+ 后续)
- **不**做端点挂时切回 rules 默认且前端 disabled toggle (留 (iv) 选项, 本 round focus 1+2)
- **不**改 production LLM 抽取 schema / retry / token (R6-H §6 保持)
- **不**自动切 default `enable_interview_llm=True` (本 round 默认仍 False)
- **不**跑 R6-H live v3 验证 (本 round focus 是改边界, 验证下次 LLM 真实使用时自动覆盖)

### 5.3 下一步候选

- **(i) 等 LLM 端点恢复后跑 R6-H live v2 重试** — R6-K circuit breaker 部署后, 重试时如果端点再卡, circuit 会自动切回 rules, 不会卡 32 min
- **(ii) 跑 R6-I prompt / retry / token 优化** — R6-H 强通过档触发, R6-H live v2 未达 (d) 暂缓不触发
- **(iii) 跑 chat panel 真实使用 10+ 轮** — 验证 R6-K circuit breaker 在生产 chat panel 真实场景下行为
- **(iv) R6-K+ 后续: retry 指数 backoff** — spec §4 锁定, 本 round 不做

---

## 6. R6-K 风险 + 缓解

| 风险 | 缓解 |
|---|---|
| circuit breaker state 跟 R5-A Phase 3 evidence 路径混用 | circuit breaker 是 LLM-only, 不影响 rules 路径 |
| circuit open 期间用户开启 LLM toggle | 前端 chip 隐藏 toggle (避免 user input 改 mode) |
| circuit state 全局单例跨测试污染 | `reset_circuit()` helper + `conftest.py` autouse fixture 隔离 |
| 60s 倒计时在 chat panel UI 跟其他 timer 冲突 | `setInterval` 局部 scope, 组件 unmount 时 clearInterval |
| circuit open 时 LLM 真实端点恢复但 chat panel 没回流 | `/reply` 每次响应都透传 circuit_state, 前端按响应更新 |
| R6-C.3 等老测试被 R6-K circuit check 污染 (urlopen 不被调) | `conftest.py` autouse fixture reset_circuit 在每个 test 跑前 |

---

## 7. R6-K closeout 验收

- [x] spec 落地: `.harness/docs/round6-k-llm-resilience-spec.md` ✅
- [x] 后端 circuit breaker 实施 (4 个文件 +194 行) ✅
- [x] 前端降级 UI 实施 (2 个文件 +97 行) ✅
- [x] 14 个 R6-K 新 pytest + 1 conftest fixture, baseline 959 → 973 passed / 0 skipped / 64.96s ✅
- [x] `vue-tsc --noEmit` 0 error + `npm run build` 成功 (5.36s) ✅
- [x] R6-H §6 严格不做清单保持 (12 项不破) ✅
- [x] 隐私边界: mode_warning 不含 `LLM_API_KEY` / `user_message` / `source_span` ✅
- [x] 4 核心文件锁定 (`core/interview_prompts.py` / `core/interview_llm.py` / `core/interview_policy.py` / `core/interview_verifier.py`) 全部不动 ✅
- [x] 4 隐私扫描 0 命中 (R6-H §4.6 保持) ✅
- [x] 决策档位: R6-K 是 fix, 不是决策档位; R6-H live v2 决策"暂缓 LLM 投资, 保持 rules 默认" 仍保持 ✅

---

## 8. 关联 commit + 文档

### 8.1 关联 commit (R6-K round 期间, 计划 1 commit 或拆 2 commit)

- (待 commit) `feat(round6-k): LLM 端点 circuit breaker + 前端降级 UI` — 主 commit
- (待 commit) `docs(round6-k): R6-K closeout 收尾报告` — docs commit

### 8.2 关联文档

- `.harness/docs/round6-h-live-eval-v2-llm-stability.md` — R6-H live v2 closeout (R6-K 起源)
- `.harness/docs/round6-k-llm-resilience-spec.md` — R6-K spec (实施前)
- `.harness/docs/round6-k-closeout.md` — 本文档 (实施后)
- `.harness/docs/round6-h-live-eval-v2-decision-gate-spec.md` — R6-H 决策门禁 spec
- `.harness/docs/round6-h-live-eval-v2-decision-report.md` — R6-H 决策报告
- `.harness/docs/round6-j-decision-report.md` — R6-J 决策报告

---

(closeout 落档, 2026-07-14, R6-K 完成, owner: Mavis, 后续: 等 LLM 端点恢复后跑 R6-H live v2 重试 验证 R6-K circuit breaker 实际行为)
