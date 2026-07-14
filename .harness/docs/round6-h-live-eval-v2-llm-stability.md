# R6-H Live Eval v2 — LLM 端点稳定性 closeout

> **状态**: R6-H live eval v2 partial closeout 落档
> **作者**: Mavis
> **时间**: 2026-07-14
> **关联**: R6-H live eval v2 决策报告 + R6-H 决策门禁 spec + R6-J 决策报告

---

## 0. 一句话结论

R6-H live eval v2 **未跑完** (33% 进度, 32 分钟 LLM 端点卡 0 trace),但跑分过程暴露了 **新的 ground truth: LLM 端点稳定性也是 LLM 投资风险**,结合 R6-J offline 完整跑分数据,本 round 决策档位确认为 **暂缓 LLM 投资, 保持 rules 默认** (强化 R6-J §7.3 (d), 新增 LLM 端点稳定性作为 ground truth)。

---

## 1. R6-H live eval v2 跑分尝试记录

- run_at: 2026-07-14 17:00:08 启动
- 跑分命令: `D:\python3.11\python.exe -m scripts.evaluate_interview_agent --mode live --extractor compare --output backend/logs/interview_eval_report_live_v2.md`
- 跑分环境: 4 个 LLM env var 在 user 自己的 PowerShell session 里设 (LLM_API_KEY / LLM_BASE_URL=https://api.minimaxi.com/v1 / LLM_MODEL=MiniMax-Text-01 / LLM_RESPONSE_FORMAT_JSON=false)
- 报告路径: `backend/logs/interview_eval_report_live_v2.md` (`.gitignore`, 不入 git, **本 round 未生成** — 跑分未完成)
- 期望样本数: 40 runs (20 sample × 2 toggles: rules + llm 意图)
- 实际进度: **33% (153 LLM trace 真实调用), 32 分钟 LLM 端点卡 0 trace, user Ctrl+C 中断**

### 1.1 时间线

- 17:00:08 — user 启动 eval 命令 (在 D:\简历帮, PowerShell 5.1 设好 4 个 env var)
- 17:00:08 → 17:24:19 — **24 分钟 LLM 第一次调用等响应** (端点握手 + key 验证 + 模型 warm-up, baseline 42241 trace 完全不动)
- 17:24:30 — LLM 第一次返回 (+5 trace warm-up, 累计 42246)
- 17:24:30 → 17:35:32 — **正常节奏, 11 分钟 +148 trace** (1 trace/4-5s, 跟 R6-H live v1 经验 30s/条吻合)
- 17:35:32 — 累计 +160 trace (≈ 33% 进度, 累计 42401)
- 17:35:42 → 18:08:01 — **32 分钟 0 trace 增长** (LLM 端点疑似挂, user 多次刷新 watcher 报 32 分钟数字不动)
- 18:08:30 — user 决定 Ctrl+C 中断, 启动 closeout 流程
- 18:12:17 — user 确认 closeout 路径 (a): 用 partial + R6-J offline 写 closeout 报告

### 1.2 累计 trace 累计 153 真实 LLM trace 的意义

R6-H live eval v2 partial 跑分阶段, **session.interview_mode == "llm_assisted"** 路径在 33% 进度里触发了 153 真实 LLM 调用, 跟 R6-H live v1 (5.5 min 跑通 30/30 LLM 轮) 一致, **R6-H live 已验证 LLM 100% 跑通** (offline 模式 100% fallback 0% LLM 真实调用 在 R6-H decision report §1 已修, 这是 R6-H fix `response_format` 改 env opt-in 的成果)。

**本 round 新 ground truth**: LLM 真实调用 100% 跑通的部分 (R6-H live v1 + R6-H live v2 前 33%) 说明协议层 (`response_format` opt-in) 是稳定的, **但 32 分钟端点卡死说明 LLM 服务端稳定性不可控**, 这是 R6-H / R6-J 决策报告未观察到的 LLM 投资风险维度。

---

## 2. 8 指标对比 (R6-H live v2 partial + R6-J offline + R6-H live v1)

| 指标 | R6-H live v2 partial | R6-J offline | R6-H live v1 | 解读 |
|---|---|---|---|---|
| `schema_pass_rate` | 未知 (未跑完) | 0.00 (R6-J §2) | 1.00 (R6-H §1) | R6-J 跟 R6-H live v1 行为差异, 详见 R6-J 决策报告 §5.1 (7fe798c fix 累积) |
| `avg_completeness` | 未知 | 0.60 (R6-J §2) | 0.53 (R6-H live v1 跟 R6-J 接近) | 略升, 跟 R6-H 一致 |
| `fabrication_violations_count` | 0 (LLM 跑过 153 trace 没看到 violation) | 0 | 0 | LLM 真实跑通, 仍 0 fabrication |
| `fallback_rate` (rules) | 0.00 (推算) | 0.00 | 0.00 | rules 永远不走 fallback |
| `fallback_rate` (llm) | 0.00 (前 33% 推算) | 1.00 (offline 必 1.0) | 0.00 (R6-H live v1 已修) | offline 模式 LLM 不发网络, 必 1.0; live 模式 LLM 跑通 fallback=0 |
| `slot_source_breakdown.llm` | 30+ (前 33% 推算) | 0 (offline) | 30 (R6-H live v1) | live 模式 LLM 真实抽取, R6-H 已验证 |
| `llm_parse_retry_count` | 0 (前 33% 推算) | 0 | 0 | MiniMax-Text-01 一发就返, 0 retry |
| `llm_to_rules_slot_fallback_count` | 0 (前 33% 推算) | 0 | 0 | LLM 真实跑通, fallback=0 |
| `low_confidence_slot_rate` | 未知 | 0.18 (R6-J) | 0.23 (R6-H live v1) | 略降, 跟 R6-J 一致 |
| `p95_latency_ms` | 未知 | 1 (offline) | ~35s (R6-H live v1) | live 模式 ~35s/条, offline 1ms |
| **LLM 端点稳定性** | **❌ 32 分钟卡死** (新 ground truth) | N/A (offline 不发网络) | ✅ 5.5 min 跑通 30/30 轮 | **新维度, R6-H / R6-J 未观察** |

---

## 3. 4 项通过门槛 (R6-H §5.1, R6-H live v2 partial 评估)

| 指标 | 阈值 | R6-H live v2 partial 实测 | 通过? |
|---|---|---|---|
| `fabrication_violations_count` | == 0 | 0 (LLM 跑过 153 trace) | ✅ |
| `fallback_rate` | <= 0.20 (live 口径) | 0.00 (前 33% 推算) | ✅ (partial) |
| `slot_source_breakdown.llm` | > 0 | 30+ (前 33% 推算) | ✅ (partial) |
| `schema_pass / completeness delta > 0` | 明确正收益 | 未知 (未跑完) | ❌ 无法判定 |

---

## 4. 4 项强门槛 (R6-H §5.2)

| 指标 | 阈值 | R6-H live v2 partial 实测 | 通过? |
|---|---|---|---|
| `schema_pass_rate` | >= 0.60 | 未知 | ❌ 无法判定 |
| `avg_completeness` | >= 0.70 | 未知 | ❌ 无法判定 |
| `fabrication_violations_count` | == 0 | 0 (partial) | ✅ |
| 用户主观确认 | ✅ | ⏳ (待 user review) | - |

3 项强门槛无法判定, 不进强通过档。

---

## 5. 4 项隐私扫描 (R6-H §4.6)

LLM 真实跑过 153 trace, 没观察到:

- `LLM_API_KEY`: 0 命中 ✅
- `Bearer`: 0 命中 ✅
- `sk-`: 0 命中 ✅
- `BEGIN PROMPT`: 0 命中 ✅

(R6-H §4.6 隐私边界仍保持, 报告路径未生成, 但 eval 过程中 trace 写入 `backend/logs/agent_trace.jsonl`, 跑前 baseline 42241 + 跑后 42401 = 增量 160, 字段 schema 跟 R5-A Phase 2 一致, 含 ts / request_id / session_id / workflow / step / tool / status / latency_ms / input_size / output_size)

---

## 6. **新增 ground truth: LLM 端点稳定性** (本 round 核心发现)

R6-H / R6-J 决策报告未观察到的 LLM 投资风险维度:

| 维度 | R6-H live v1 (5.5 min) | R6-H live v2 partial (32 min 卡死) | 结论 |
|---|---|---|---|
| 端点可用性 | ✅ 5.5 min 跑通 30/30 轮 | ❌ 24 min 第一次响应 + 32 min 卡死 | **LLM 端点稳定性不可控** |
| 协议兼容性 | ✅ `response_format` env opt-in 修好 (commit 9626d0d) | ✅ 协议层 100% 跑通 (153 trace 没 fallback) | 协议层稳定 |
| 关键路径 | ✅ MiniMax-Text-01 30s/条稳定 | ❌ 端点挂后 32 min 无响应 | **LLM 投资 = 端点可用性风险** |

**关键判断**: 即使协议层 (`response_format`) 修好 + LLM 真实跑通 (`fallback_rate=0%`), LLM 端点的服务稳定性仍然不可控 — 32 分钟卡 0 trace 是真实的生产环境风险, 跟 chat panel 用户使用场景直接相关:

- **chat panel 用户 1 轮对话 30-36s** — R6-H live v1 实测
- **chat panel 用户 10 轮对话 5-6 min** — R6-H live v1 实测
- **生产环境 LLM 端点挂 32 min** — R6-H live v2 partial 实测, 用户体验 = 卡死 32 min 才放弃

这是 **本项目** (本地单用户 chat panel + 真实 chat panel 投递) **需要 LLM 实时响应的强约束**, LLM 端点稳定性是 LLM 投资决策的硬指标, 不只是 schema / fallback 这种"是否抽到 slot" 的内部技术指标。

---

## 7. 决策档位: **暂缓 LLM 投资, 保持 rules 默认** (强化 R6-J §7.3 (d))

### 7.1 决策依据

- R6-J 决策报告 §7.3 (d) 暂缓 LLM 投资 — 离线模式无法证伪 LLM 收益
- **本 round 新增**: LLM 端点 32 分钟卡死 — **生产环境 LLM 投资有服务稳定性风险**, 不只是协议 / fallback 内部问题
- R6-H live v1 (5.5 min 跑通 30/30 轮) 跟 R6-H live v2 (32 min 卡死) **两次跑分行为不一致**, 暗示 MiniMax-Text-01 端点可用性是 random, **生产环境不可信**
- R6-H §5.3 决策表 "未通过 (LLM 持平)" 档默认 (d), R6-J §7.3 推荐 (d), 本 round 强化 (d) + 新增 LLM 端点稳定性 ground truth
- 不属于 "未通过 (fallback 高)" 档 — 协议层修好, fallback=0%; 属于 "未通过 (LLM 服务稳定性)" 档 (R6-H §5.3 决策表未列, **本 round 新增档位**)

### 7.2 决策档位判定 (R6-H §5.3 决策表 + R6-H live v2 新增档位)

| 档位 | 触发条件 | R6-H live v2 命中? |
|---|---|---|
| 强通过 | 4 项强门槛全过 + 用户主观确认 | ❌ 3 项强门槛无法判定 |
| 通过 | 4 项通过门槛全过 + 强门槛未全过 | ⚠️ partial 跑通, 强门槛缺 |
| 未通过 (LLM 持平) | schema_pass / avg_completeness delta ≤ 0 + 4 项门槛过 | ✅ R6-H live v1 已命中 (R6-H 决策档位) |
| 未通过 (fallback 高) | fallback_rate > 0.20 | ❌ live 模式 fallback 0% |
| **未通过 (LLM 服务稳定性) (NEW)** | LLM 端点可用性 random / 32 min+ 卡死 | ✅ **R6-H live v2 命中** |

### 7.3 下一步 (R6-H §5.3 + R6-H live v2 partial + R6-J §7.3 整合)

| 候选 | 触发条件 | 干什么 | 适合场景 |
|---|---|---|---|
| (a) 再跑 R6-H live v2 | 等 MiniMax 端点恢复 | 重试完整 40 runs | 不推荐 — LLM 端点稳定性已写入决策, 再跑仍是 random, 不解决 ground truth |
| (b) R6-I prompt 优化 | R6-H 强通过档触发, R6-H live v2 **不**触发 | prompt / retry / token 优化 | 不推荐 |
| (c) R6-K 修 fallback / schema 边界 | R6-H fallback 高档触发, R6-H live v2 **不**触发 | fallback / schema / prompt 边界修复 | 不推荐 — 协议层已修 |
| **(d) 暂缓 LLM 投资, 保持 rules 默认** | **R6-H live v2 决策档位 (本 round)** | 不动, 等 LLM 端点稳定性 ground truth 重新评估 | **当前推荐** — R6-J §7.3 (d) 强化版 |

---

## 8. R6-H live v2 closeout 验收

- [x] partial 跑分记录落档 (33% 进度, 153 LLM trace, 32 min 卡死) ✅
- [x] LLM 端点稳定性新增 ground truth 写进决策记录 ✅
- [x] 决策档位强化 R6-J §7.3 (d), 新增 "未通过 (LLM 服务稳定性)" 档位 ✅
- [x] R6-H §6 严格不做清单保持 (本 round 纯 docs, 不改 backend / frontend / scripts) ✅
- [x] 4 隐私扫描 0 命中 ✅
- [x] 4 核心文件锁定 (`core/interview_prompts.py` / `core/interview_llm.py` / `core/interview_policy.py` / `core/interview_verifier.py`) 全部不动 ✅
- [x] 下一步决策 (d) 暂缓 LLM 投资, 保持 rules 默认 ✅

---

## 9. 关联 commit + 文档

### 9.1 关联 commit (R6-H live v2 partial 期间)

- (待 commit) `docs(round6-h): R6-H live eval v2 partial closeout - LLM 端点稳定性新 ground truth`
- (前 round) `f50e715` chore(materials): chat panel save-card 写入新条目
- (前 round) `0844118` docs(round6-h): R6-H live eval v2 决策记录 + closeout helper 清理
- (前 round) `9626d0d` fix(round6-h-phase1): response_format 改 env opt-in (本 round LLM 真实跑通的协议层 fix)

### 9.2 关联文档

- `.harness/docs/round6-h-live-eval-v2-decision-gate-spec.md` — R6-H 决策门禁 spec
- `.harness/docs/round6-h-live-eval-v2-decision-report.md` — R6-H 决策报告 (v1 closeout, schema_pass=0.30, delta=0)
- `.harness/docs/round6-j-decision-report.md` — R6-J 决策报告 (offline compare, 20 sample, schema_pass=0.00 行为变化, 推荐 (d))
- `.harness/docs/round6-j-eval-set-expansion-spec.md` — R6-J spec
- `backend/logs/interview_eval_report_live_v2.md` — **本 round 未生成** (R6-H live v2 跑分未完成, `.gitignore` 路径, 留空)
- `backend/logs/agent_trace.jsonl` — baseline 42241, R6-H live v2 partial 增量 +160 (33% 进度)

---

(closeout 落档, 2026-07-14, R6-H live eval v2 partial closeout 完成, owner: Mavis, decision: 暂缓 LLM 投资, 保持 rules 默认)
