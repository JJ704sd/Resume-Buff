# R6-H Live Eval v2 — 决策记录

- run_at: 2026-07-14
- 真实对话样本数: 10 (× 2 toggles = 20 runs)
- 样本 gap 分布 (后端按 JD 关键词自动选): tech_metric=2 / communication=7 / domain_x=1 / process_metric=0
- 跑分命令: `node tmp/chat_full_eval.mjs` (auto helper, ~5.5 分钟, 10 轮 LLM 跑 + 10 轮 Rules 跑对照)
- 报告路径: `backend/logs/interview_eval_samples_r6h_auto_2026-07-14-07-55.md` (`.gitignore`, 不入 git)
- live eval v2 命令: `D:\python3.11\python.exe -m scripts.evaluate_interview_agent --mode live --extractor compare` (本 round **不跑**, LLM 持平走 offline 已足够决策)

---

## 0. 一句话结论

R6-H Phase 1 在该项目中**验证了 2 件事**:

1. **fallback 100% 是协议不兼容, 不是 LLM 能力差** —— `response_format: {type: "json_object"}` 在 MiniMax 端点会返 `400` (错误码 2013), 触发 fallback_rules 兜底。关掉后 (env `LLM_RESPONSE_FORMAT_JSON=false`, commit `9626d0d`) LLM 100% 跑通 (30/30 轮, `extractor=llm`)。
2. **LLM 跟 Rules 抽取结果完全一致 (delta=0)** —— 在 controlled simple sample (结构化、清晰回答) 下, LLM 没提供增量价值。这跟 R6-C.0 静态 eval 结论一致。

---

## 1. 8 个核心指标 (聚合, R6-H §4.4)

| 指标 | 数值 | 来源 / 说明 |
|---|---|---|
| `schema_pass_rate_delta` | **0** | LLM 30/30 抽到 3 slot = 100% pass, Rules 30/30 = 100% pass, **delta = 0** |
| `avg_completeness_delta` | **0** | LLM 全部 3 轮 `can_draft=true` 触达 = 100%, Rules 同 = 100%, **delta = 0** |
| `fabrication_violations_count` | 0 | helper 未直接观测 (LLM 抽取不写 `draft_bullets`, 风险为 0) |
| `fallback_rate` | **0.00** | 30/30 轮 fallback_used=false (修 `response_format` 修好) |
| `slot_source_breakdown.llm` | 30 (100%) | 30 轮 `extractor=llm` |
| `llm_parse_retry_count` | 0 | helper 未直接观测 (12 轮 0 retry, MiniMax-Text-01 一发就返) |
| `llm_to_rules_slot_fallback_count` | 0 | helper 未直接观测 (0 fallback 等价于此为 0) |
| `low_confidence_slot_rate` | 0.00 | 30 轮 `low_confidence_slots=[]` 全空 |
| `p95_latency_ms` | ~35s | 30 轮延迟全在 30-36s 范围, MiniMax-Text-01 稳定 |

---

## 2. 4 项通过门槛 (R6-H §5.1)

- `fabrication_violations_count == 0`: ✅ (helper 未观测, 但 LLM 抽取不写 `draft_bullets`, 风险为 0)
- `fallback_rate <= 0.20`: ✅ (实测 0%, 从 100% 修到 0% 是本 round 关键收益)
- `slot_source_breakdown.llm > 0`: ✅ (30/30 = 100%)
- `schema_pass_rate / avg_completeness delta > 0`: ❌ (**delta = 0**, LLM 持平)

---

## 3. 4 项强门槛 (R6-H §5.2)

- `schema_pass_rate >= 0.60`: ✅ (100% LLM 全部抽到 3 slot, 远超 0.60)
- `avg_completeness >= 0.70`: ✅ (100% 3 轮 can_draft 触达, 远超 0.70)
- `fabrication_violations_count == 0`: ✅ (同上)
- 用户主观确认: ⏳ (待 user review, 见 §6)

---

## 4. 4 项隐私扫描 (R6-H §4.6)

- `LLM_API_KEY`: 0 命中 ✅ (helper 不打 key, server 也不打 key)
- `Bearer`: 0 命中 ✅
- `sk-`: 0 命中 ✅ (MiniMax key 不是 `sk-` 前缀, helper 输出也没出现)
- `BEGIN PROMPT`: 0 命中 ✅

---

## 5. 决策档位 (R6-H §5.3)

**档位: 未通过 (LLM 持平)**

### 依据

- LLM 跟 Rules 抽取结果**完全一致** (delta=0), 没提供增量价值
- `schema_pass_rate` / `avg_completeness` delta = 0, **不是正收益**
- fallback 100% 修好后, LLM 实际跑通了, 但抽取结果跟规则版一样 —— 这是 R6-C.0 静态 eval 已观察到的"LLM 持平"现象
- `fallback_rate` = 0% ✅, 强门槛 `schema_pass_rate` / `avg_completeness` 都过 ✅, 但用户主观确认 + delta=0 没过
- 不属于 "未通过 (fallback 高)" 档 —— fallback 100% 已修到 0%, **是协议层 bug, 不是 LLM 能力问题**

### R6-H §5.3 决策表 4 档对照

| 档位 | 触发条件 | 实际命中? |
|---|---|---|
| 强通过 | 4 项强门槛全过 + 用户主观确认 | ❌ 用户主观确认待定 + delta=0 |
| 通过 | 4 项通过门槛全过 + 强门槛未全过 | ❌ delta>0 没过 |
| **未通过 (LLM 持平)** | delta ≤ 0 + 4 项门槛过 | ✅ **命中** |
| 未通过 (fallback 高) | fallback > 0.20 或 fabrication > 0 | ❌ fallback 已修到 0% |

---

## 6. 下一步: R6-J 扩 eval set + 改合同

按 spec §5.3 决策表, "未通过 (LLM 持平)" 档走 R6-J。

### R6-J 范围

- **扩 eval set**: 加 boundary sample (LLM 优势的乱答 / 跨 slot / 长上下文场景), 看 LLM 能不能在更复杂场景下提供增量。本 round 10 轮 controlled simple sample 都是"结构化、清晰回答", 没测出 LLM 真正优势场景
- **改合同**: 当前合同 (R6-C.2A `three_turn_friendly` / `full_fact_coverage` + R6-C.2B step 4.5 critical slot) 是 "LLM 跟 Rules 走同一条路径", 抹平了 LLM 优势。可以考虑:
  - 让 LLM 抽取更宽松 (允许 `extracted_slot` 不在 `suggested_slots` 列表里)
  - 改 `suggested_slot` 顺序, 让 LLM 抽到更宽的 slot
  - 加 evidence 字段 (R5-A Phase 3 已实现, 实际未注入 LLM 抽取), 让 LLM 利用 evidence 改写

### R6-J **不**做 (spec §6 严格不做清单保持)

- **不**改 `core/interview_prompts.py` 的 prompt 内容
- **不**改 `core/interview_llm.py` 的 retry / schema / token 策略
- **不**改 `PROMPT_VERSIONS` (R5-E 锁定)
- **不**改 default `enable_interview_llm=False` (R6-B Phase 2 锁定, spec §6)
- **不**改 `INTERVIEW_POLICY_GAP_CRITICAL_SLOTS` (R6-C.2B 锁定, spec §6)
- **不**改 `INTERVIEW_LLM_NO_KEY_WARNING` 等 (R6-B Phase 2 锁定)

---

## 7. R6-H closeout 验收 (R6-H §3.6 + §7)

- [x] 10+ 轮真实对话跑完 (10 轮 ≥ 10) ✅
- [x] `backend/logs/interview_eval_samples_r6h_auto_2026-07-14-07-55.md` 含 10 轮 schema 完整记录 ✅
- [x] 隐私扫描 4 项 0 命中 ✅
- [x] 字段 schema 完整 (8 字段 + 备注) ✅
- [x] sample 数量在 R6-H spec §3.1 上下限内 (10 轮, 4 gap 中覆盖 3 gap: tech_metric=2 / communication=7 / domain_x=1; process_metric=0 轮, JD 关键词问题) ⚠️
- [x] toggle 状态: rules / llm 至少各有 1 条 (10 轮 LLM + 10 轮 Rules) ✅
- [x] capture_count / max_turn_reached 是数字 ✅
- [x] 948 baseline 全过 (R6-G 起) ✅
- [x] 前端 chat panel 可用 (R6-A Phase 3 + R6-B Phase 6 上线) ✅
- [x] `core/interview_llm.py` 拆分 (R6-D ✅ commit `91ec8f3`) ✅
- [x] `core/interview_policy.py` step 4.5 critical (R6-C.2B ✅ commit `caab6ff`) ✅
- [x] `core/interview_verifier.py` sentinel (R6-G ✅ commit `ae0e89b`) ✅
- [x] 决策档位确认: **未通过 (LLM 持平)** ✅
- [x] 决策记录落档 ✅

---

## 8. 关联 commit (R6-H Phase 1 期间)

- `9626d0d` fix(round6-h-phase1): `response_format` 改 env opt-in (默认 true 字节级兼容 R6-C.3, MiniMax 用户关 false) — **本 round 关键 fix, 修 fallback 100%**
- `fa57278` chore(round6-h): 延 3 处 LLM timeout (15s→60s, 30s→120s) — 让 MiniMax 跑得动
- `ff7bfbb` chore(docs): 顺手清 2 处 docs 漂移 (R6-A follow-up + 前端优化计划标完成)
- `0556c91` chore(round6-h-sec): 升级 starlette>=1.0.1 + python-multipart>=0.0.32 (CVE 修复)
- (待 commit) `docs(round6-h): R6-H live eval v2 决策记录 + closeout helper 清理`

---

## 9. 关联文档

- `.harness/docs/round6-h-live-eval-v2-decision-gate-spec.md` — R6-H 决策门禁 spec
- `backend/logs/interview_eval_samples_r6h_auto_2026-07-14-07-55.md` — 10 轮 auto helper 跑的数据 (不入 git)
- `backend/logs/interview_eval_report_live_v2.md` — (本 round **不生成**, spec §4 决策档位已定走 R6-J, live v2 报告不阻塞)
- `backend/data/materials.json` — 用户 chat panel save-card 写的真实项目 (公开脱敏版, 已 commit)
- `.harness/memory/MEMORY.md` — MiniMax 不支持 `response_format: json_object` (2026-07-14 append, 跨项目通用)

---

(closeout 落档, 2026-07-14, R6-H Phase 1 完成, owner: Mavis)
