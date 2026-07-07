# Round 6-H: Live Eval v2 决策门禁 Spec

> 适用项目: 简历帮 / Resume-Buff  
> 本地仓库: `D:\简历帮`  
> 起草日期: 2026-07-03  
> 当前 active baseline: **948 passed** (R6-G 落地后, 2026-07-03)  
> 状态: **draft spec**  
> 任务来源: R6-F closeout 报告 `.harness/docs/round6-f-project-review-bug-audit-report.md` §7 (c) "R6-H LLM 真实收益验证(待用户启动)" + R6-E spec §10 Phase 4-6

---

## 0. 一句话结论

R6-H 是**决策门禁 round**, 严格不做 prompt / retry / token 优化。基于用户在前端 `InterviewAgentPanel` 跑的 10+ 轮真实对话样本, 跑 `evaluate_interview_agent.py --mode live --extractor compare`, 按通过门槛 / 强门槛 / 决策表决定 LLM slot 抽取是否值得继续投资。

---

## 1. 背景与目标

### 1.1 第一性原理

R6-C.0 live compare 已证明 LLM 在静态 eval set 上相对 rules 的 `schema_pass_rate` / `avg_completeness` delta = 0, 即在**受控样本**上 LLM 没有明显优势。继续堆功能前, 必须用**真实前端对话样本**做产品面验证, 确认 LLM 抽取在用户实际使用中是否提供明确价值。

这是项目价值问题, 不是技术问题:**本项目的价值是"把真实经历安全、可追溯、低摩擦地变成可复用简历素材", 不是"更多智能"。** LLM 抽取如果在真实使用中没明确收益, 就保持 rules 默认, 把精力放在扩 eval set / 改真实样本合同 / 修边界 bug 上。

### 1.2 R6-H 范围

R6-H = 数据采集 + 跑分 + 决策 三步, 严格不涉及:

- LLM prompt 内容修改
- retry 策略升级
- token 成本控制
- schema 限制调整
- 默认行为变更 (`enable_interview_llm=False` 仍默认)
- 前端 UI 改造(除接收决策结果展示外)
- `PROMPT_VERSIONS` 注册表改动
- `core/interview_prompts.py` / `core/interview_llm.py` / `core/interview_policy.py` / `core/interview_verifier.py` 4 个核心文件

### 1.3 与历史 round 的边界

- **R6-A Phase 4** (2026-06-30): LLM slot extraction 上线但仅 `live + key 启用` 时触发
- **R6-C.3** (2026-07-02): LLM 抽取可观测性 `slot_source_breakdown` / `llm_parse_retry_count` / `llm_to_rules_slot_fallback_count` 3 字段就位
- **R6-D** (2026-07-02): LLM 模块拆分 `core/interview_llm.py` 独立 (行为不变机械重构)
- **R6-E closeout** (2026-07-03): GitHub 同步 + 文档一致性 + Phase 4 bug fix (`_do_answer` slot 优先读 `question_plan` 决策) — commit `7fe798c`
- **R6-F closeout** (2026-07-03): 项目回顾 + bug 审核, 0 P0 / 0 P1, 5 P2 + 1 P3 全部 owner 决策落地, 3 review-needed 延后 R6-G — commit `a3f48b1`
- **R6-G** (2026-07-03): 3 review-needed 落地 (verifier sentinel + envelope hygiene + stderr 脱敏), +12 pytest, 936 → 948 baseline — commit `ae0e89b`
- **R6-H** (2026-07-03 起): live eval v2 决策门禁 — **本轮**

---

## 2. 前置条件

| 条件 | 状态 | 验证方式 |
|---|---|---|
| R6-F closeout 落地 | ✅ commit `a3f48b1` | `git log --oneline -5` |
| R6-G 落地 | ✅ commit `ae0e89b` | `git log --oneline -2` |
| 948 baseline 全过 | ✅ 实测 116.93s | `D:\python3.11\python.exe -m pytest tests/ -q` |
| 用户已配置 LLM key | ⚠️ 用户自报, owner **不打印/校验** key 值 / env var 名 | 用户自报 |
| 前端 `InterviewAgentPanel` 可用 | ✅ R6-A Phase 3 上线, R6-B Phase 6 增强 (confidence_notes / verification / needsSaveConfirm 3 面板) | `npm run build` 成功 |
| 真实对话数据未采集 | ⚠️ 等用户在 chat panel 跑 10+ 轮 | 启动 R6-H Phase 1 时核对 |
| `core/interview_llm.py` 模块拆分完成 | ✅ R6-D 锁定 | `git log --oneline --all` 含 `91ec8f3` |
| `core/interview_prompts.SLOT_EXTRACTION_SYSTEM_PROMPT` + few-shot 就位 | ✅ R6-C.3 锁定 | `git log --oneline` 含 `84dd086` |
| `core/interview_policy.py` step 4.5 critical slot | ✅ R6-C.2B 锁定 | `git log --oneline` 含 `caab6ff` |

**任一条件不满足** → 不开 R6-H Phase 2 (live compare), 先补前置。

---

## 3. Phase 1 — 真实对话数据采集

### 3.1 目标

用户在前端 `InterviewAgentPanel` 跑 **至少 10 轮真实对话**, 覆盖:

- 2 轮 `tech_metric`
- 2 轮 `communication`
- 2 轮 `process_metric`
- 2 轮 `domain_x`
- 2 轮 用户自由选择(可选其他 gap 或重复, 不强求)

每轮 = 一次完整的 start → reply 序列(可到 `/draft` 或 `/save-card` 中止, 也可在 3 轮内未触达 draft 中止)。

### 3.2 工具

- 智能抽取 toggle 可开可关; **默认仍 rules**
- 允许对照(同一对话 toggle 开/关各跑一次, 留作 R6-H live compare 的双轨数据)
- 不强制: 不要求 10 轮都开 LLM toggle, 也不要求 10 轮都关
- 跑对话时可观察前端 `modeTagInfo` 三态 (warning / success / info) 确认 toggle 状态

### 3.3 隐私边界 (本阶段最关键)

**绝不**保存 / 打印 / 提交 下列内容到任何位置:

- 完整 `user_message` 原文
- 完整 `draft_bullets` 原文
- `session_id` 完整值(只存前 4 字符, R5-C Phase 1 隐私约定)
- LLM raw response
- prompt 模板正文
- API key 值 / env var 名 (`LLM_API_KEY`) / Bearer 头 / key 前缀 (`sk-`)

### 3.4 样本记录 schema

只保存以下字段, 写到 `backend/logs/interview_eval_samples_r6h.md` (本地, 不入 git):

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `sample_id` | str | ✅ | 用户自命名 (e.g. `tech_metric_medical_eval`) |
| `gap` | enum | ✅ | `tech_metric` / `communication` / `process_metric` / `domain_x` / `other` |
| `expected_slot_keys` | list[str] | ✅ | 用户预期 LLM 抽取的 slot key 列表 (e.g. `["responsibility", "action", "result"]`) |
| `product_goal` | enum | ✅ | `three_turn_friendly` / `full_fact_coverage` (R6-C.2A 口径) |
| `toggle` | enum | ✅ | `rules` / `llm` (跑对话时智能抽取 toggle 状态) |
| `capture_count` | int | ✅ | 实际 captured slot 数 (0-3) |
| `max_turn_reached` | int | ✅ | 实际跑了几轮 (1-3) |
| `notes` | str | ⚪ | 人工备注, e.g. "用户答 3 轮就触达 result 槽" |

**`product_goal` 沿用 R6-C.2A 口径**:
- `three_turn_friendly`: 3 轮内可生成素材
- `full_fact_coverage`: 完整项目事实覆盖(允许 3 轮外, 不强求 3 轮内可生成)

### 3.5 不入库的字段

- 完整 `user_message` 原文
- 完整 `draft_bullets` 原文
- 完整 `session_id` (只用前 4 字符)
- LLM raw response
- prompt 模板正文
- API key / env var / Bearer / key 前缀

### 3.6 验收

- [ ] 10+ 轮真实对话跑完
- [ ] `backend/logs/interview_eval_samples_r6h.md` 含 10+ 条 schema 完整记录
- [ ] 隐私扫描: 抽样 10 段 user_message 原文, grep 该文件不出现
- [ ] 字段 schema 完整, 无 "其他" 字段污染
- [ ] sample 数量在 4 gap × 2 轮 + 2 自由 上下限内

---

## 4. Phase 2 — live eval v2 跑分

### 4.1 目标

基于 Phase 1 的 10+ 真实对话样本, 跑 `evaluate_interview_agent.py --mode live --extractor compare`, 产出 v2 报告。

### 4.2 命令

```powershell
cd D:\简历帮
D:\python3.11\python.exe -m scripts.evaluate_interview_agent `
  --mode live `
  --extractor compare `
  --output backend/logs/interview_eval_report_live_v2.md
```

### 4.3 输入要求

- LLM key 在 env (`LLM_API_KEY`, **owner 不打印/校验**)
- `LLM_BASE_URL` 可选, 默认走 `core.llm_rewriter.DEFAULT_BASE_URL` 同源默认值
- `LLM_MODEL` 可选, 默认走 `core.llm_rewriter.DEFAULT_MODEL` 同源默认值
- 真实对话样本已采集(Phase 1 完成)

### 4.4 核心指标 (8 个, R6-E spec §10 + R6-F 报告 §7 整合)

```text
schema_pass_rate_delta               = llm - rules            (要求 > 0)
avg_completeness_delta               = llm - rules            (要求 > 0)
fabrication_violations_count         (要求 == 0)
fallback_rate                        (要求 <= 0.20)
slot_source_breakdown.llm            (要求 > 0)
llm_parse_retry_count                (累计, 监控用)
llm_to_rules_slot_fallback_count     (累计, 监控用)
low_confidence_slot_rate             (累计, 监控用)
p95_latency_ms                       (累计, 监控用)
```

### 4.5 报告路径

`backend/logs/interview_eval_report_live_v2.md` (`.gitignore`, **不入 git**)

### 4.6 报告隐私扫描 (R6-G 落地后 4 项必过)

报告渲染后必须通过 4 项扫描:

1. `Select-String -LiteralPath backend\logs\interview_eval_report_live_v2.md -Pattern "LLM_API_KEY" -SimpleMatch` — 0 命中
2. `Select-String -LiteralPath backend\logs\interview_eval_report_live_v2.md -Pattern "Bearer" -SimpleMatch` — 0 命中
3. `Select-String -LiteralPath backend\logs\interview_eval_report_live_v2.md -Pattern "sk-" -SimpleMatch` — 0 命中
4. `Select-String -LiteralPath backend\logs\interview_eval_report_live_v2.md -Pattern "BEGIN PROMPT" -SimpleMatch` — 0 命中

### 4.7 不做

- **不**提交 `backend/logs/interview_eval_report_live_v2.md` 到 git
- **不**把报告内容(除聚合指标)粘贴到 `.harness/docs/` 任何文件
- **不**在 stdout / stderr 打印 key 值 / env var 名
- **不**在 R6-H 跑分时同步跑 prompt / retry / token 优化实验(留 R6-I)
- **不**在跑分时改任何 `core/` / `scripts/` 文件

---

## 5. Phase 3 — 决策门禁

### 5.1 通过门槛 (4 项, 全部满足 = 通过)

| 指标 | 阈值 | 不满足后果 |
|---|---|---|
| `fabrication_violations_count` | == 0 | 一票否决, 任何编造 = 暂停 LLM 投资 |
| `fallback_rate` | <= 0.20 | fallback 高 → 暂停, 修 fallback / schema / prompt 边界 |
| `slot_source_breakdown.llm` | > 0 | 0 = LLM 实际没跑通 → 查 env / 排查 |
| `schema_pass_rate` / `avg_completeness` delta | 明确正收益 (> 0) | 持平 / 负收益 → LLM 没价值, 保持 rules |

### 5.2 强门槛 (4 项, 全部满足 = 强通过)

| 指标 | 阈值 |
|---|---|
| `schema_pass_rate` | >= 0.60 |
| `avg_completeness` | >= 0.70 |
| `fabrication_violations_count` | == 0 |
| 用户主观确认 | 追问更省力 + 无明显误抽取 |

强门槛全过 + 用户主观确认 = **强通过**, 默认可考虑开 `enable_interview_llm=True`。

### 5.3 决策表 (4 档)

| 档位 | 触发条件 | 下一步 |
|---|---|---|
| **强通过** | 4 项强门槛全过 + 用户主观确认 | **R6-I**: prompt / retry / token 优化启动 |
| **通过** | 4 项通过门槛全过 + 强门槛未全过 | **R6-J**: 扩 eval set / 改真实样本合同, R6-H 重跑 |
| **未通过 (LLM 持平)** | schema_pass_rate / avg_completeness delta ≤ 0 + 4 项门槛过 | **R6-J**: 扩 eval set / 改合同, R6-H 重跑前先扩 |
| **未通过 (fallback 高)** | fallback_rate > 0.20 或 slot_source_breakdown.llm = 0 或 fabrication > 0 | **R6-K**: 修 fallback / schema / prompt 边界, 不继续投资 LLM 抽取 |

### 5.4 决策记录文档

无论哪一档, 都要写决策记录到 `.harness/docs/round6-h-live-eval-v2-decision-report.md` (新文件, **入 git**):

```markdown
## R6-H Decision

- run_at: <ISO date>
- 真实对话样本数: N
- 样本 gap 分布: tech_metric=N / communication=N / process_metric=N / domain_x=N / other=N
- 跑分命令: <命令>
- 报告路径: backend/logs/interview_eval_report_live_v2.md (.gitignore, 不入 git)

### 8 个核心指标 (聚合)

- schema_pass_rate_delta: +X.XX
- avg_completeness_delta: +X.XX
- fabrication_violations_count: 0
- fallback_rate: 0.XX
- slot_source_breakdown.llm: N
- llm_parse_retry_count: N
- llm_to_rules_slot_fallback_count: N
- low_confidence_slot_rate: 0.XX
- p95_latency_ms: N

### 4 项通过门槛

- fabrication_violations_count == 0: ✅ / ❌
- fallback_rate <= 0.20: ✅ / ❌
- slot_source_breakdown.llm > 0: ✅ / ❌
- schema_pass / completeness 明确正收益: ✅ / ❌

### 4 项强门槛

- schema_pass_rate >= 0.60: ✅ / ❌
- avg_completeness >= 0.70: ✅ / ❌
- fabrication_violations_count == 0: ✅ / ❌
- 用户主观确认: ✅ / ❌

### 4 项隐私扫描

- LLM_API_KEY: 0 命中 ✅
- Bearer: 0 命中 ✅
- sk-: 0 命中 ✅
- BEGIN PROMPT: 0 命中 ✅

### 决策档位 + 下一步

- 档位: 强通过 / 通过 / 未通过 (LLM 持平) / 未通过 (fallback 高)
- 下一步: R6-I / R6-J / R6-K / 暂缓
- 决策依据: <一段中文解释为什么是这个档位, 引证具体指标>
```

原始 v2 报告**不**写进决策记录, 路径只在 closeout 文档里标"本地 .gitignore, 不入 git"。

---

## 6. 不做清单 (R6-H 严格不)

- **不**改 `core/interview_prompts.py` 的 prompt 内容
- **不**改 `core/interview_llm.py` 的 retry / schema / token 策略
- **不**改 `PROMPT_VERSIONS` (R5-E 锁定, 决策点 D5 保留)
- **不**改 default `enable_interview_llm=False` (R6-B Phase 2 锁定)
- **不**改 `INTERVIEW_POLICY_GAP_CRITICAL_SLOTS` (R6-C.2B 锁定)
- **不**改 `INTERVIEW_LLM_NO_KEY_WARNING` 等 (R6-B Phase 2 锁定)
- **不**动 `core/interview_verifier.py` 的 sentinel 常量 (R6-G 锁定)
- **不**动 `scripts/evaluate_interview_agent.py` 的脱敏文案 (R6-G 锁定)
- **不**挂 pre-push hook (R5-D spec §12 #3 默认手动脚本沿用)
- **不**引入新 LLM 调用
- **不**引入新依赖 (纯 stdlib + 既有依赖)
- **不**提交 live report 原始日志 (`backend/logs/interview_eval_report_live_v2.md` .gitignore)
- **不**提交真实对话原文
- **不**提交 `user_message` / `draft_bullets` / API key / Bearer / env var 名
- **不**开账号 / 鉴权 / 云端 / 多用户
- **不**做自由聊天 / 模拟面试 / 自动投递 (R6-B spec §13 非目标)

---

## 7. 验收标准

R6-H 完成时必须满足:

- [ ] 用户跑完 10+ 轮真实对话
- [ ] `backend/logs/interview_eval_samples_r6h.md` 含 10+ 条 schema 完整记录, 隐私扫描通过
- [ ] live eval v2 报告生成在 `backend/logs/interview_eval_report_live_v2.md` (不入 git)
- [ ] 报告 4 项隐私扫描 0 命中
- [ ] 决策记录 `.harness/docs/round6-h-live-eval-v2-decision-report.md` 入 git, 含 8 个核心指标 + 4 档决策 + 下一步
- [ ] `AGENTS.md` 加 R6-H entry (commit message 含 948 baseline + 决策档位 + 下一步)
- [ ] `README.md` / `ROADMAP.md` / `MEMORY.md` 三方同步 (baseline + 决策档位 + 下一步)
- [ ] 全量 pytest 仍 948 passed (R6-H 不改 backend 代码, baseline 不变)
- [ ] 前端 `vue-tsc --noEmit` 0 error + `npm run build` 成功
- [ ] `git status` 无意外业务代码变更(仅 docs + decision report)

---

## 8. 给执行 agent 的提示词

```text
你在 D:\简历帮 工作。请执行 R6-H: Live Eval v2 决策门禁。

先读 AGENTS.md 和 .harness/docs/round6-h-live-eval-v2-decision-gate-spec.md (本 spec)。

目标:
1. 核对前置条件: 948 baseline 全过 / 用户已配 LLM key / 前端可用
2. 提示用户跑 10+ 轮真实对话 (4 gap × 2 轮 + 2 自由)
3. 引导用户按 schema 填 backend/logs/interview_eval_samples_r6h.md (不入 git)
4. 跑 D:\python3.11\python.exe -m scripts.evaluate_interview_agent --mode live --extractor compare --output backend/logs/interview_eval_report_live_v2.md
5. 按 §5 决策表 4 档评分, 写决策记录到 .harness/docs/round6-h-live-eval-v2-decision-report.md
6. 同步 README/ROADMAP/MEMORY/AGENTS 4 份文档 (baseline + 决策档位 + 下一步)
7. 不提交 live report / samples / 真实对话原文
8. 不打印 key / env var / Bearer / raw response
9. 不改 backend/core/ / backend/api/ / frontend/src/ / scripts/

验收命令:
git -C D:\简历帮 log --oneline -3
cd D:\简历帮\backend
D:\python3.11\python.exe -m pytest tests/ -q
cd D:\简历帮\frontend
npx vue-tsc --noEmit
npm run build
cd D:\简历帮
D:\python3.11\python.exe -m scripts.evaluate_interview_agent --mode live --extractor compare --output backend/logs/interview_eval_report_live_v2.md
Select-String -LiteralPath backend\logs\interview_eval_report_live_v2.md -Pattern "LLM_API_KEY|BEGIN PROMPT|source_span|Bearer|sk-" -SimpleMatch
```

---

## 9. 收尾记录模板

```markdown
## R6-H Closeout

- run_at: 2026-07-XX
- baseline_before: 948 passed
- baseline_after: 948 passed (R6-H 不改 backend)
- 真实对话样本数: N
- 样本 gap 分布: tech_metric=N / communication=N / process_metric=N / domain_x=N / other=N
- 跑分命令: D:\python3.11\python.exe -m scripts.evaluate_interview_agent --mode live --extractor compare --output backend/logs/interview_eval_report_live_v2.md
- 报告路径: backend/logs/interview_eval_report_live_v2.md (本地 .gitignore, 不入 git)

### 8 个核心指标 (聚合)

- schema_pass_rate_delta
- avg_completeness_delta
- fabrication_violations_count
- fallback_rate
- slot_source_breakdown.llm
- llm_parse_retry_count
- llm_to_rules_slot_fallback_count
- low_confidence_slot_rate
- p95_latency_ms

### 决策

- 通过门槛 4 项: ✅/❌ (fabrication=0 / fallback≤0.20 / llm>0 / 正收益)
- 强门槛 4 项: ✅/❌ (schema_pass≥0.60 / completeness≥0.70 / fabrication=0 / 用户主观确认)
- 隐私扫描 4 项: ✅/❌ (LLM_API_KEY / Bearer / sk- / BEGIN PROMPT)
- 决策档位: 强通过 / 通过 / 未通过 (LLM 持平) / 未通过 (fallback 高)
- 下一步: R6-I / R6-J / R6-K / 暂缓
- 决策依据: <一段中文>

### 文档同步

- AGENTS.md: 加 R6-H entry (commit message 含 948 baseline + 决策档位 + 下一步)
- README.md: 后端测试基线 + 文档一致性 + 决策档位
- ROADMAP.md: 阶段状态 + 决策档位
- MEMORY.md: 里程碑 entry
```

---

## 附录 A: 关联文档

- `.harness/docs/round6-e-github-sync-live-eval-v2-spec.md` §10 Phase 4-6 (真实数据采集 + 跑分 + 决策) — **直接来源**
- `.harness/docs/round6-f-project-review-bug-audit-report.md` §7 (c) — **R6-H 任务来源**
- `.harness/docs/round6-c-live-eval-result-and-next-steps.md` — R6-C.0 live 摘要 + R6-C.1+ C.2A+ C.2B+ C.3+ R6-D 改动清单
- `.harness/docs/round6-c-live-eval-guide.md` — R6-C live eval 操作指南
- `backend/core/interview_llm.py` — R6-D 拆分的 LLM 模块 (R6-G hygiene 清理)
- `backend/core/interview_agent.py` — R6-E Phase 4 slot 对齐 bug fix
- `backend/core/interview_policy.py` — R6-C.2B 路线 B 锁定 (step 4.5 critical slot)
- `backend/core/interview_verifier.py` — R6-B Phase 4 + R6-G verifier sentinel
- `scripts/evaluate_interview_agent.py` — R6-C.3 + R6-D + R6-G 报告生成 + stderr 脱敏
- `frontend/src/components/InterviewAgentPanel.vue` — R6-B Phase 6 + R6-F UI chip fix

## 附录 B: R6-H 决策门禁流程图

```text
[Phase 1: 用户跑 10+ 轮真实对话] → samples (本地 .gitignore)
                  ↓
[Phase 2: live eval v2 跑分] → v2 报告 (本地 .gitignore, 不入 git)
                  ↓
   ┌─────────────────────────────┐
   │  4 项通过门槛 全过?           │
   │  (fabrication=0 /            │
   │   fallback≤0.20 /            │
   │   llm>0 / 正收益)            │
   └─────────────────────────────┘
              ↓yes            ↓no
   ┌────────────────┐    ┌────────────────────────┐
   │  4 强门槛 全过? │    │ fabrication>0 /        │
   └────────────────┘    │ fallback>0.20 /        │
       ↓yes  ↓no         │ llm=0                  │
   ┌────────┐ ┌──────┐    └────────────────────────┘
   │ 用户主观 │ │ R6-J │            ↓
   │  确认?  │ │ (扩  │    ┌──────────────────────┐
   └──┬──┬──┘ │ eval │    │ 未通过 (fallback 高)  │
   yes│  │no   │ set) │    └──────────────────────┘
   ┌──┘  └────┐└──────┘            ↓
   ↓          ↓               ┌────────┐
┌──────┐  ┌──────┐            │ R6-K   │
│ 强通过 │  │ 通过 │            │ (修边界)│
└──────┘  └──────┘            └────────┘
   ↓          ↓
  R6-I       R6-J
  (启动      (扩 eval
  优化)      set 重跑)
```

**特别路径**: `schema_pass / completeness delta ≤ 0` 但其他 3 项过 → 走"未通过 (LLM 持平)"档 → R6-J (扩 eval set, 改合同, R6-H 重跑前先扩)。

---

## 10. Phase 2 跑分准备 spec 计划 (2026-07-06 落档)

> 本章为 Phase 2 跑分的**准备期 spec 落档**, 不执行 live 跑分 (key 未配 + 真实样本 0/10 当前不可执行), 不改动任何业务代码。路径 A 已获用户拍板为后续 round 实施方向, 但本计划只落档设计, 不写代码。

### 10.1 准备期核心发现 (基于现状核实)

探查现有 `scripts/evaluate_interview_agent.py` 与 `backend/logs/interview_eval_samples_r6h.md` 后发现**关键缺口**:

- 脚本 `--mode live --extractor compare` 当前只跑内置 `EVAL_SET_ALL` (10 条脱敏模拟样本, 含 `user_messages`), **没有加载 R6-H 真实对话样本的入口**;
- R6-H 第一性原理要求"用真实用户对话验证", 但真实样本按 §3.3 / §3.4 隐私边界**只存 8 个统计字段 (sample_id / gap / expected_slot_keys / product_goal / toggle / capture_count / max_turn_reached / notes), 不含 `user_messages` 原文**;
- 脚本 `_evaluate_one` 算 `schema_pass_rate` / `avg_completeness` / `fabrication_guard` 必须喂 `user_messages` 给 `extract_slots` → 真实统计样本**无法直接进现有跑分路径**;
- 即: spec §4.2 字面命令跑的是"模拟集 live 对照", 不是"真实样本验证"。两者数据模型对不上, 必须桥接。

### 10.2 桥接路径决策 (用户 2026-07-06 拍板: 路径 A)

| 路径 | 内容 | 验证价值 | 代码改动 | 决策 |
|---|---|---|---|---|
| **A (已选)** | 前端/后端用户手动跑对话时, 把真实 session 的 `user_messages` 抽离落盘到本地 gitignored JSON (脱敏: `session_id` 前 4 字符、不存 `draft_card` 原文、不存 API key), 给脚本加 `--real-sessions <path>` 加载这批真实 session 跑 live compare | 真实验证, R6-H 第一性原理正解 | 需小改 `scripts/` + 加轻量落盘机制 | ✅ 后续 round 实施 |
| B (弃) | 复用 `_run_real_sessions.py` 思路, 真实 API + 真实 LLM, 但 `user_messages` 仍来自 `EVAL_SET_ALL` | 仅链路 smoke, 不算真实样本验证 (R6-C.0 已做过) | 不改代码 | ❌ |

**路径 A 实施边界 (后续 round, 本计划不落地)**:
- 落盘 JSON 路径 `backend/logs/interview_real_sessions_r6h.json` (`.gitignore`, 不入 git);
- 脱敏: 每条 `{session_short_id: 前4字符, gap, user_messages: [...], toggle, expected_slot_keys}`; **绝不**存 `draft_bullets` 原文 / 完整 `session_id` / API key / Bearer / `sk-` / prompt 正文;
- 前端/后端落盘机制须遵守 R6-H spec §6 不做清单: 不引入新依赖、不改 `core/interview_prompts.py` / `core/interview_llm.py` / `core/interview_policy.py` / `core/interview_verifier.py` 4 个核心文件;
- 脚本加 `--real-sessions <path>` CLI 分支, 加载真实 session 替代 `EVAL_SET_ALL` 走 `_evaluate_one` 同一套指标/报告/隐私扫描逻辑;
- 实施前需另起 plan 经用户授权 (本计划仅文档)。

### 10.3 前置核对清单 (Phase 2 入口检查表)

| 项 | 状态 | 验证方式 |
|---|---|---|
| 948 baseline 全过 | ✅ | `D:\python3.11\python.exe -m pytest tests/ -q` (R6-G 锁) |
| 前端 `npm run build` 成功 | ✅ | `cd frontend && npm run build` |
| `core/interview_llm.py` 模块拆分 (R6-D) | ✅ | `git log` 含 `91ec8f3` |
| `core/interview_policy.py` step 4.5 critical slot (R6-C.2B) | ✅ | `git log` 含 `caab6ff` |
| `core/interview_verifier.py` sentinel (R6-G) | ✅ | `git log` 含 `ae0e89b` |
| LLM key (`LLM_API_KEY`) 已配 | ⚠️ **当前未配** → live compare 不可执行; rules 对照 (offline compare) 仍可跑 | 用户自报, owner 不打印/校验 |
| 真实对话样本回填进度 | ⚠️ **0/10 待填** (`interview_eval_samples_r6h.md` §6 入口判断) | 读 samples md 计数 |

**任一 ⚠️ 项未解除 → 不开 Phase 2 live compare**, 先走 §10.4 准备期验证 (rules 对照) + 等用户补前置。

### 10.4 准备期可立即跑的验证 (rules 对照, 不等同真实样本验证)

```powershell
cd D:\简历帮
D:\python3.11\python.exe -m scripts.evaluate_interview_agent `
  --mode offline `
  --extractor compare `
  --output backend/logs/interview_eval_report_r6h_prep.md
```

用途: 验证脚本/报告链路健康 + `slot_source_breakdown` / `llm_parse_retry_count` / `llm_to_rules_slot_fallback_count` 3 字段渲染正常, **不作为 R6-H 真实样本验证结论**。

### 10.5 报告隐私扫描命令 (Phase 2 跑分后执行, 4 项 0 命中)

```powershell
cd D:\简历帮
Select-String -LiteralPath backend\logs\interview_eval_report_live_v2.md -Pattern "LLM_API_KEY" -SimpleMatch   # 0 命中
Select-String -LiteralPath backend\logs\interview_eval_report_live_v2.md -Pattern "Bearer" -SimpleMatch        # 0 命中
Select-String -LiteralPath backend\logs\interview_eval_report_live_v2.md -Pattern "sk-" -SimpleMatch            # 0 命中
Select-String -LiteralPath backend\logs\interview_eval_report_live_v2.md -Pattern "BEGIN PROMPT" -SimpleMatch   # 0 命中
```

### 10.6 阻塞项与待办 (标注)

| 阻塞/待办 | 责任方 | 当前状态 | 解除条件 |
|---|---|---|---|
| 真实样本回填 (10+ 轮) | 用户 | ⚠️ 0/10, 前端手动跑过几轮但不足 10 轮 | 用户在 `InterviewAgentPanel` 跑满 10+ 轮并按 §3.4 schema 填 samples md |
| LLM key 配置 | 用户 | ⚠️ 未配 (`LLM_API_KEY` 空) | 用户设 env `LLM_API_KEY` (非空即启用) |
| 路径 A 桥接实施授权 | 用户决策 | ✅ 已拍板方向, ⏸ 未实施 | 另起 plan 授权小改 `scripts/` + 加落盘机制 |
| Phase 2 live compare 可执行 | — | ❌ 当前不可执行 | 上 3 项全部解除后 |

### 10.7 验收脚本清单汇总

1. **现在可跑** (准备期 rules 对照): §10.4 offline compare 命令 → 验证链路健康;
2. **待 key + 真实样本** (Phase 2 本体): §4.2 live compare 命令 + §10.5 四条隐私扫描 + §5 决策表评分;
3. **配套 (路径 A 实施后)**: `--real-sessions <path>` 加载真实 session 跑 live compare, 同 §4.2 指标与 §10.5 扫描。

---

(spec 完, 2026-07-03 起草; §10 追加 2026-07-06)
