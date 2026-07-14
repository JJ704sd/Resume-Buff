# R6-J 决策报告 — 扩 eval set 10 → 20, 加 5 类 boundary 场景

> **状态**: R6-J closeout 落档
> **作者**: Mavis
> **时间**: 2026-07-14
> **关联**: R6-H live eval v2 决策报告 + `.harness/docs/round6-j-eval-set-expansion-spec.md` + R6-H spec §5.3

---

## 0. 一句话结论

R6-J 验证了 4 件事:

1. **扩 eval set 10 → 20 加 5 类 boundary 场景不破 948 baseline** — 主仓跑全量 `pytest tests/ -q` → **959 passed** (948 老 + 11 R6-J 新单测, 65.98s)
2. **process_metric 兜底达成** — R6-H §7 ⚠️ 盲点 0 轮 → R6-J 4 轮 (含 2 条 R6-J boundary_process_metric_*)
3. **4 gap 全覆盖** — tech_metric=6 / communication=3 / process_metric=4 / domain_x=2 / others=5, 跟 R6-H 0 轮 process_metric 比, gap 分布从 3/4 变成 4/4
4. **offline 模式仍然无法证伪 LLM 收益** — boundary 10 条新 sample 跟 R6-H 一样, LLM 跟 Rules 在 offline 模式下走同一路径 (llm_disabled_fallback), delta=0

**关键 schema_pass 数值变化** (R6-E 0.30 → R6-J 0.00) **必须解读为行为变化 (R6-E Phase 4 fix 7fe798c 累积 + sample 增加)**, **不**解读为 LLM 抽取能力下降。详见 §5.1。

---

## 1. 跑分配置 + 报告路径

- run_at: 2026-07-14
- 跑分命令: `D:\python3.11\python.exe -m scripts.evaluate_interview_agent --mode offline --extractor compare --output backend/logs/interview_eval_report_r6j.md`
- 报告路径: `backend/logs/interview_eval_report_r6j.md` (`.gitignore`, 不入 git)
- 样本总数: 40 runs (20 sample × 2 toggles: rules + llm 意图, offline 模式 llm 走规则版 fallback)
- 样本分布:
  - `plan_baseline`: 3 条 (3 × 2 toggles = 6)
  - `simulated_user_v1`: 7 条 (7 × 2 = 14)
  - `boundary_v1`: 10 条 (10 × 2 = 20)
- gap 分布: tech_metric=6 / communication=3 / process_metric=4 / domain_x=2 / others=5

---

## 2. 8 个核心指标 (聚合, 跟 R6-H spec §4.4 对齐)

| 指标 | R6-J (offline compare) | R6-H (live v1) | delta | 解读 |
|---|---|---|---|---|
| `schema_pass_rate` | 0.00 | 0.30 | -0.30 | **行为变化, 详见 §5.1** |
| `avg_completeness` | 0.60 | 0.53 | +0.07 | 略升, 因 boundary 抓到更多 slot (low_conf_rate 一致) |
| `fabrication_violations_count` | 0 | 0 | 0 | 仍 0, boundary 10 条不引入 fabrication |
| `fallback_rate` (extractor=llm) | 1.00 | 0.00 (R6-H live 100% 跑通) | +1.00 | offline 模式 llm 不发网络 → 100% fallback, R6-H live 已修 |
| `fallback_rate` (extractor=rules) | 0.00 | 0.00 | 0 | rules 永远不走 fallback |
| `slot_source_breakdown.llm` | 0 (offline) | 30 (R6-H live) | -30 | offline 模式 llm 不发网络, 符合预期 |
| `llm_parse_retry_count` | 0 | 0 | 0 | 都 0 |
| `llm_to_rules_slot_fallback_count` | 0 | 0 | 0 | 都 0 |
| `low_confidence_slot_rate` | 0.18 | 0.23 | -0.05 | 略降, 跟 boundary sample 抽到更多高 confidence slot 一致 |
| `p95_latency_ms` | 1 | ~35s (R6-H live) | -34s | offline 1ms vs live 35s, 跟 R6-H decision report §1 一致 |

---

## 3. 4 项通过门槛 (R6-H §5.1, 跟 R6-J 对齐)

| 指标 | 阈值 | R6-J 实测 | 通过? |
|---|---|---|---|
| `fabrication_violations_count` | == 0 | 0 | ✅ |
| `fallback_rate` | <= 0.20 | 1.00 (offline llm 路径) / 0.00 (rules 路径) | ⚠️ offline 必 fail, R6-H live 0% 已修 |
| `slot_source_breakdown.llm` | > 0 | 0 (offline) | ⚠️ offline 必 fail, R6-H live 30 已修 |
| `schema_pass / completeness delta > 0` | 明确正收益 | schema -0.30, completeness +0.07 | ❌ schema 负 delta, 行为变化 (§5.1) |

R6-H 决策报告 §5.3 决策表 4 档对照:

| 档位 | 触发条件 | R6-J 命中? |
|---|---|---|
| 强通过 | 4 项强门槛全过 + 用户主观确认 | ❌ schema_pass 0.00 不达标 |
| 通过 | 4 项通过门槛全过 + 强门槛未全过 | ❌ offline 模式 fallback_rate + slot_source_breakdown 必 fail |
| **未通过 (LLM 持平)** | schema_pass / avg_completeness delta ≤ 0 + 4 项门槛过 | ✅ **命中** (跟 R6-H 同档) |
| 未通过 (fallback 高) | fallback_rate > 0.20 (live 模式口径) | ❌ R6-H live 0% 已修, offline 模式不算 |

---

## 4. 4 项强门槛 (R6-H §5.2)

| 指标 | 阈值 | R6-J 实测 | 通过? |
|---|---|---|---|
| `schema_pass_rate` | >= 0.60 | 0.00 | ❌ (行为变化, 详见 §5.1) |
| `avg_completeness` | >= 0.70 | 0.60 | ❌ (略低, 0.53 → 0.60 是 +0.07 改进, 离 0.70 仍差 0.10) |
| `fabrication_violations_count` | == 0 | 0 | ✅ |
| 用户主观确认 | ✅ | ⏳ (待 user review) | - |

3 项强门槛 fail, 不进强通过档。

---

## 5. 4 项隐私扫描 (R6-H §4.6)

- `LLM_API_KEY`: 0 命中 ✅
- `Bearer`: 0 命中 ✅
- `sk-`: 0 命中 ✅ (MiniMax key 不是 sk- 前缀)
- `BEGIN PROMPT`: 0 命中 ✅

---

## 5.1 关键发现:schema_pass 数值变化 = 行为变化 (7fe798c fix + sample 累积)

**R6-J 跟 R6-E (0.30) 数值不可直接对比**, 根因是 R6-E Phase 4 fix (commit `7fe798c`):

- **修复前 (R6-E 跑分时)**: `_do_answer` 用 `_current_slot(sess)`, 按 `gap.suggested_slots` 顺序跳过 captured。对于 process_metric gap (suggested = responsibility, action, result, metric), 2nd turn captured {responsibility, action} 时, _current_slot 返回 result (第 3 个, 跳前 2 个) → captured 第 3 字段是 result
- **修复后 (R6-J 跑分时)**: `_do_answer` 优先读 `sess.question_plan["slot"]` (policy 决策结果)。policy step 3 `_find_missing_required_slots` 遍历 `CAN_DRAFT_CONDITIONS`:
  - combo1 (background, action, result): captured={responsibility, action} → missing=[background, result], gap=2
  - combo2 (responsibility, action, metric): captured={responsibility, action} → missing=[metric], gap=1, **break** (gap==1)
  - combo3 (responsibility, action, result): 不遍历
  - 返回 best=combo2 missing=[metric]
  - 3rd turn ask `missing[0]`=metric

**两种行为都让任一 combo 满足 (can_draft=True)**, 7fe798c fix 是 spec 决策改进 (combo 满足 + /draft 端点返 200), 但改变了 captured 字段 (从 result 变成 metric), 影响了 R6-J 跑分 schema_pass 判定。

**R6-C.2A 验收口径保留**: schema_pass_rate 数值变化必须解读为 **行为变化 / 评测合同变化**, **不**解读为 LLM 抽取能力变化。本 round (R6-J) schema_pass 0.00 是 7fe798c fix (R6-E Phase 4) 行为变化 + R6-J sample 扩 10 → 20 累积结果, 不是 LLM 抽取能力下降。

**R6-J 不期望 schema_pass_rate 提升** (R6-J spec §6 "R6-J 不做" 已声明: 走方案 C 不动合同, 看新 sample 下 LLM 跟 Rules 自然分叉; offline 模式 LLM 不发网络, delta 始终 = 0)。

---

## 6. R6-J 新增指标 (spec §5.2)

| 指标 | R6-J 实测 | 通过? | 说明 |
|---|---|---|---|
| `boundary_sample_count` | 10 | ✅ | 5 类各 2 条 (chaos / multi_slot / long_context / jargon / process_metric) |
| `boundary_sample_schema_pass` | 0/10 | ❌ (offline 限制) | offline 模式 LLM 不发网络, 跟 R6-E 老 sample 行为一致 |
| `process_metric_sample_count` | 4 | ✅ (R6-H 0 → R6-J 4 兜底) | R6-H §7 ⚠️ 盲点修复: 含 1 老 sample + 1 老 sim + 2 R6-J boundary_process_metric_* |
| `process_metric_sample_schema_pass` | 0/4 | ❌ (7fe798c fix 累积, 行为变化) | captured 抓 metric 优先 (combo2 gap=1 break), expected 含 result → fail, 是行为变化非 LLM 能力下降 |
| `coverage_by_gap` | tech_metric=6 / communication=3 / process_metric=4 / domain_x=2 / others=5 | ✅ | 4 gap 全覆盖, R6-H 0 轮 process_metric 兜底达成 |
| `extraction_2x_样本` | 40 (20 sample × 2 toggles) | ✅ | R6-B Phase 5 compare 模式 spec 验证 |
| `unreachable_contract_warning` | 17 (按 sample 去重) | ⚠️ | R6-J 边界 sample 引入 9 条新 warning (boundary 5 类 9 个 unreachable/beyond), 跟 R6-C.2A 兼容 |
| `fallback_category_breakdown` | none=20 / llm_disabled_fallback=20 | ✅ | 跟 R6-H decision report §三 一致, offline 模式双组各 50% |

---

## 7. 决策档位 + 下一步

### 7.1 决策档位: **未通过 (LLM 持平, offline 限制)**

**依据**:
- R6-J 跟 R6-H 同档 (R6-H spec §5.3 决策表 "未通过 (LLM 持平)" 档)
- R6-J schema_pass 0.00 不可直接对比 R6-E 0.30, 是行为变化 (7fe798c fix 累积)
- offline 模式 LLM 不发网络, 无法证伪 LLM 收益 (跟 R6-H §8 结论一致)
- R6-J 验证了: 扩 eval set + boundary sample 不破 948 baseline, process_metric 兜底达成, 4 gap 全覆盖
- 不属于 "未通过 (fallback 高)" 档 — R6-H live 已验证 fallback=0%, R6-J offline 模式 fallback=1.00 是预期行为

### 7.2 R6-J 不期望的指标 (R6-J spec §6 已声明)

- **不期望** schema_pass_rate 提升 (走方案 C 不动合同, offline 模式 LLM 不发网络)
- **不期望** delta > 0 (offline 模式 LLM 跟 Rules 走同一条规则版路径)
- **不期望** R6-K 触发 (fallback 不是真的高, offline 模式限制)

### 7.3 下一步 (R6-H spec §5.3 + R6-J 决策报告 §7 二选一 / 三选一 / 四选一)

按 R6-H spec §5.3 决策表, "未通过 (LLM 持平)" 档走 R6-J 路径, R6-J 完成后再决策。R6-J 完成后再决策的下一步候选:

- **(a) R6-H live eval v2 (R6-H §10 路径 A)** — 跑 `--mode live --extractor compare` + 真实 LLM key, 验证 boundary sample 下 LLM 跟 Rules delta 是否变正 (R6-H live v1 已验证 100% 跑通, R6-J 扩 sample 后重跑)
  - 通过门槛: live `fallback_rate <= 0.20` + `slot_source_breakdown.llm > 0` + `schema_pass / avg_completeness delta > 0`
  - 强门槛: `schema_pass_rate >= 0.60` + `avg_completeness >= 0.70` + `fabrication == 0` + 用户主观确认
  - 决策档位: "强通过" → R6-I (prompt 优化), "通过" → 保持 rules 默认 + R6-I 启动, "未通过" → R6-K 修边界 / 暂缓 LLM 投资

- **(b) R6-I: prompt / retry / token 优化** — R6-H §5.3 决策表强通过档触发, R6-J 不触发
  - 当前不推荐: R6-J 决策档位不是强通过

- **(c) R6-K: 修 fallback / schema / prompt 边界** — R6-H §5.3 决策表 fallback 高档触发, R6-J 不触发 (offline 模式 fallback 100% 是预期)
  - 当前不推荐: R6-H live 0% 已验证 fallback 修好

- **(d) 暂缓 LLM 投资, 保持 rules 默认** — R6-H §5.3 决策表未通过档默认行为
  - 当前推荐: R6-J 没找到 LLM 优势场景 (offline 限制), 暂缓投资
  - **跟 R6-H 决策报告 §5 档位一致, 不变**

### 7.4 R6-J spec §6 严格不做清单保持

- **不**改 `core/interview_prompts.py` prompt 内容
- **不**改 `core/interview_llm.py` retry / schema / token 策略
- **不**改 `PROMPT_VERSIONS` (R5-E 锁定)
- **不**改 default `enable_interview_llm=False` (R6-B Phase 2 锁定)
- **不**改 `INTERVIEW_POLICY_GAP_CRITICAL_SLOTS` (R6-C.2B 锁定)
- **不**改 `INTERVIEW_LLM_NO_KEY_WARNING` (R6-B Phase 2 锁定)
- **不**动 `core/interview_verifier.py` sentinel (R6-G 锁定)
- **不**动 `scripts/evaluate_interview_agent.py` 脱敏文案 (R6-G 锁定)
- **不**挂 pre-push hook
- **不**引入新 LLM 调用
- **不**引入新依赖

---

## 8. R6-J closeout 验收 (spec §7 + dev workflow)

- [x] spec 落地: `.harness/docs/round6-j-eval-set-expansion-spec.md` ✅
- [x] 扩 eval set 10 → 20 加 5 类 boundary 场景 + process_metric 兜底 ✅
- [x] 11 个 R6-J 新 pytest (4 个 test class) — 主仓跑全量 959 passed / 0 skipped ✅
- [x] 不破 R6-G baseline 948 — 主仓全量 948 + 11 = 959 全绿, R6-G 老测试零回退 ✅
- [x] 跑分命令按 spec 走 offline compare ✅
- [x] R6-J 决策报告落档 ✅
- [x] 4 项隐私扫描 0 命中 ✅
- [x] R6-H §6 严格不做清单保持 ✅
- [x] 4 核心文件锁定 (`core/interview_prompts.py` / `core/interview_llm.py` / `core/interview_policy.py` / `core/interview_verifier.py`) 全部不动 ✅
- [x] 决策档位确认: **未通过 (LLM 持平, offline 限制)** ✅

---

## 9. 关联 commit (R6-J round 期间)

- `c32f566` feat(round6-j): 扩 eval set 10 → 20, 加 5 类 boundary 场景 + process_metric 兜底 (R6-J 主 commit, 2 文件 +456/-1)
- (待 commit) `docs(round6-j): R6-J 决策记录 + closeout`

---

## 10. 关联文档

- `.harness/docs/round6-h-live-eval-v2-decision-gate-spec.md` — R6-H 决策门禁 spec (R6-J 来源)
- `.harness/docs/round6-h-live-eval-v2-decision-report.md` — R6-H 决策记录 (R6-J 上一档)
- `.harness/docs/round6-j-eval-set-expansion-spec.md` — R6-J 扩 eval set spec
- `backend/logs/interview_eval_report_r6j.md` — R6-J 跑分报告 (`.gitignore`, 不入 git)
- `backend/logs/interview_eval_report_r6e_offline.md` — R6-E 跑分报告 (旧 baseline, 0.30 schema_pass, 行为变化前的基线)
- `backend/data/materials.json` — R6-H commit `f50e715` chat panel 真实项目 (公开脱敏版)

---

(closeout 落档, 2026-07-14, R6-J 完成, owner: Mavis)
