# R6-J 扩 eval set + 改合同 — Spec

> **状态**: 草稿待 user 确认
> **作者**: Mavis
> **时间**: 2026-07-14
> **关联**: R6-H live eval v2 决策报告(档位:未通过 LLM 持平)+ R6-H spec §5.3 + §6 不做清单

---

## 0. 一句话目标

把 `scripts/evaluate_interview_agent.py` 的 eval set 从 10 条扩到 **20-25 条**,加 LLM 真正能展现优势的场景(乱答/跨 slot/长上下文/process_metric 兜底),看 LLM 跟 Rules 的 delta 能不能从 0 变正。

**不改 production 代码**(`core/interview_agent.py` / `core/interview_llm.py` / `core/interview_policy.py` / `core/interview_verifier.py` / `core/interview_prompts.py` 全部不动)。

---

## 1. R6-H 实测 + 决策档位回顾

详见 `.harness/docs/round6-h-live-eval-v2-decision-report.md`。关键事实:

- 10 轮 sample 全部是 **structured simple** (3 句话清楚回答一个 slot)
- LLM 跟 Rules 抽到**完全一样**的 slot (delta = 0)
- sample gap 分布: tech_metric=2 / communication=7 / domain_x=1 / **process_metric=0** ⚠️
- 通过门槛:`delta > 0` ❌ 没过 → 走"未通过 (LLM 持平)"档 → R6-J

R6-H §5.3 决策表已规定:R6-J = 扩 eval set / 改真实样本合同, **R6-H 重跑前先扩**。

---

## 2. R6-J 三大目标

### 2.1 目标 1 — 扩 eval set (主要工作量)

从 10 条扩到 **20-25 条**,加 5 类 LLM 优势场景:

| # | 场景类别 | 典型 sample | LLM 优势点 |
|---|---|---|---|
| 1 | **乱答 / 口语化** | "嗯... 我想想... 啊就是, 我主要吧, 就是搞那个, 数据标注那块儿" | 规则按关键词命中率低, LLM 能从散句重组 |
| 2 | **跨 slot 单回答** | "我在 xx 项目里用了聚类, 然后是 5 个人一起做的, 用了 2 周" | 规则按 suggested 顺序只能问一个 slot, LLM 单回答能抽到 action + method + result |
| 3 | **长上下文 100+ 字** | 3-4 句长段落描述一个项目 | 规则按关键词位置, 容易抓错 slot, LLM 长上下文能定位 |
| 4 | **行业 jargon** | "做了 few-shot prompt, SFT 蒸馏, DPO 对齐" | 规则未必能命中, LLM 认识术语 |
| 5 | **process_metric 兜底** | "我设计了评估 rubric, 跟 3 个标注员对答案, Kappa 0.72" | **R6-H §7 ⚠️ 盲点**, 至少 3-4 条 |

每类 2-3 条,总量 = 10 老 + 10-15 新 = **20-25 条**。

### 2.2 目标 2 — 改合同(轻量,可选)

考虑 2 选 1, **默认不改**,先看新 eval set 跑下来 delta 变没变正:

- **方案 A: 加 LLM-only bonus 分** — 新增 `llm_bonus` 字段在 metrics 里,LLM 抽到 suggested 外的 slot 算加分
- **方案 B: 调 suggested_slot 顺序** — 让 LLM 抽到更宽的 slot 集合
- **方案 C: 不动合同** — R6-H 没改合同, R6-J 也先不改,看新 sample 下 LLM 跟 Rules 自然分叉

**建议走 C** — 不动合同,先验证 hypothesis(LLM 在 boundary sample 下能展现实力)。如果 C 跑下来 delta 还 0,再走 A(加 LLM bonus)或 B(调顺序)。

### 2.3 目标 3 — process_metric 覆盖度兜底(必要)

R6-H §7 ⚠️ 标记 process_metric 0 轮覆盖,根因是 JD 关键词让后端选 gap 时 communication 分数更高。R6-J 直接在 eval set 显式包含:

- 3-4 条 process_metric 样本 (test_qa / data_annot role)
- 显式 `gap_id="process_metric"`,绕过后端自动选 gap 的问题
- 评估:process_metric 场景下 LLM 跟 Rules 的 delta

---

## 3. 不做清单 (R6-H §6 严格保持)

R6-J 跟 R6-H 一样,严格不做:

- **不**改 `core/interview_prompts.py` prompt 内容
- **不**改 `core/interview_llm.py` retry / schema / token 策略
- **不**改 `PROMPT_VERSIONS` (R5-E 锁定)
- **不**改 default `enable_interview_llm=False` (R6-B Phase 2 锁定)
- **不**改 `INTERVIEW_POLICY_GAP_CRITICAL_SLOTS` (R6-C.2B 锁定)
- **不**改 `INTERVIEW_LLM_NO_KEY_WARNING` 等 (R6-B Phase 2 锁定)
- **不**动 `core/interview_verifier.py` sentinel 常量 (R6-G 锁定)
- **不**动 `scripts/evaluate_interview_agent.py` 脱敏文案 (R6-G 锁定)
- **不**挂 pre-push hook
- **不**引入新 LLM 调用
- **不**引入新依赖 (纯 stdlib + 既有依赖)
- **不**改 production API (`/api/interview/*` 任何 endpoint)

R6-J 改动范围只限:
- `scripts/evaluate_interview_agent.py` — 新增 10-15 条 eval sample
- `backend/tests/test_interview_eval.py` — 加新 sample 的单元测试
- 新建 `.harness/docs/round6-j-decision-report.md` — 跑完写决策记录

---

## 4. R6-J 实施步骤 (预计 1 round)

### Phase 0 — 准备 (本 round 内)

1. 写 R6-J spec(本文件)
2. user 确认范围 (扩多少条 / 改不改合同 / 哪些 gap 必覆盖)
3. 切到 worktree 分支 `feat/round6-j-eval-expansion`

### Phase 1 — 扩 eval set (核心)

1. 在 `scripts/evaluate_interview_agent.py` 加 10-15 条 sample,分 5 类:
   - boundary_chaos (2-3 条): 乱答/口语化/错别字
   - boundary_multi_slot (2-3 条): 单回答含多 slot
   - boundary_long_context (2-3 条): 100+ 字长段落
   - boundary_jargon (2-3 条): 行业术语 (SFT/DPO/few-shot 等)
   - process_metric_boost (3-4 条): 显式 process_metric gap
2. 全部加 `product_goal` / `contract_note` 字段对齐 R6-C.2A 合同
3. 跑 `--mode offline --extractor rules` 验证新 sample 不破老测试
4. 加 `tests/test_interview_eval.py` 单元测试覆盖新 sample

### Phase 2 — 重跑 (复用 R6-H 跑分命令)

1. 跑 `D:\python3.11\python.exe -m scripts.evaluate_interview_agent --mode offline --extractor compare --output backend/logs/interview_eval_report_r6j.md`
2. 对比 R6-H baseline (10 条) 跟 R6-J 新 baseline (20-25 条):
   - **关键 delta**:`schema_pass_rate` / `avg_completeness` / `fabrication` / `fallback` / `low_confidence_slot_rate` / `p95_latency_ms` 6 指标
   - **核心问题**:boundary sample 下, LLM 跟 Rules 的 delta 是否变正?
   - **process_metric 子集 delta**:这一类是不是 LLM 真的优势场景?

### Phase 3 — 决策记录

1. 写 `.harness/docs/round6-j-decision-report.md` 对齐 R6-H 决策报告 schema (8 指标 + 4 通过门槛 + 4 强门槛 + 4 隐私扫描 + 决策档位)
2. 决策档位判定:
   - **强通过** → LLM 默认开 (考虑 R6-I 启动 prompt 优化)
   - **通过** → LLM 仍默认关, prompt 优化启动
   - **未通过 (LLM 持平)** → R6-J hypothesis 失败, 回退到 rules 默认, 暂缓 LLM 投资
   - **未通过 (fallback 高)** → R6-K 修 fallback 边界
3. 落档 + commit + push

---

## 5. R6-J 验收门槛 (跟 R6-H 一致, 复用 §5.1 + §5.2)

**通过门槛 4 项**:

| 指标 | 阈值 |
|---|---|
| `fabrication_violations_count` | == 0 |
| `fallback_rate` | <= 0.20 |
| `slot_source_breakdown.llm` | > 0 |
| `schema_pass_rate` / `avg_completeness` delta | **明确正收益 (> 0)** — R6-H = 0 是核心痛点 |

**强门槛 4 项**:

| 指标 | 阈值 |
|---|---|
| `schema_pass_rate` | >= 0.60 |
| `avg_completeness` | >= 0.70 |
| `fabrication_violations_count` | == 0 |
| 用户主观确认 | ✅ (chat panel 真实对话验证) |

**新增 R6-J 子指标**:

| 指标 | 说明 |
|---|---|
| `boundary_sample_delta` | boundary 5 类 sample 的 LLM vs Rules delta (新指标) |
| `process_metric_delta` | process_metric 4 条 sample 的 LLM vs Rules delta (新指标) |
| `coverage_by_gap` | 4 gap 都有覆盖,无 0 轮 (兜底 R6-H §7 ⚠️) |

---

## 6. R6-J 不做 (spec 边界)

- **不**自动切默认 `enable_interview_llm=True` (等 R6-J 决策档位 + R6-I prompt 优化完成后由 user 决策)
- **不**改 front-end (`enable_interview_llm` toggle 默认 False 保持)
- **不**改 production LLM 抽取 schema (R6-C.3 锁定)
- **不**跑 live eval v2 (offline 模式足够决策, 避免 token 浪费)
- **不**扩 eval set 到 50+ 条 (R6-J 走 20-25 条够 hypothesis 验证, 不堆量)
- **不**改 sample 格式 (保持 R6-C.2A product_goal / contract_note 字段)

---

## 7. R6-J 风险 + 缓解

| 风险 | 缓解 |
|---|---|
| 扩 sample 引入 PII 泄漏 | 复用 R6-G 脱敏文案标准, 公开版 demo 素材, 跑 `_check_pii_safe` 二次扫 |
| eval set 30+ 条跑得太慢 (>5 min) | 控制在 20-25 条, 跟 R6-H 跑分耗时对齐 |
| LLM 在 boundary 下 fallback 反而升高 | 这是合法发现, 决策档位走"未通过 (fallback 高)" → R6-K 启动 |
| process_metric 0 轮兜底后 LLM 仍 0 增量 | process_metric 子指标 `process_metric_delta=0` 也是合法结论, 写进决策报告 |
| boundary sample 跟真实 chat panel 脱节 | user 跑 chat panel 真实对话 5-10 轮验证, 比 offline 更有信号 |

---

## 8. R6-J 时间线

- **Phase 0 (本 round 0.5h)**: 写 spec + user 确认
- **Phase 1 (1 round 2-3h)**: 扩 10-15 条 sample + 单测 + 跑通
- **Phase 2 (0.5h)**: 重跑 compare 模式
- **Phase 3 (0.5h)**: 写决策报告 + commit + push
- **总计**: 1 round 半天

---

## 9. R6-J 不直接做的事 + 留给后续 round

- **R6-I**: prompt / retry / token 优化 (R6-H §5.3 决策表强通过档触发, R6-J 不触发)
- **R6-K**: 修 fallback / schema / prompt 边界 (fallback 高档触发)
- **R6-L+**: 前端 chat panel 真实对话 10+ 轮 (R6-J 通过门槛后 user 启动)

---

## 10. user 确认范围 checklist (本 round 末)

- [ ] 扩多少条: 20 / 25 / 其他?
- [ ] 5 类 boundary 场景必含哪些?
- [ ] process_metric 兜底 3-4 条够不够?
- [ ] 改合同走 A / B / C 哪个?
- [ ] 跑法: offline compare 模式 (建议) / live compare 模式?
- [ ] 决策报告写到 `.harness/docs/round6-j-decision-report.md` 对齐 R6-H 模板

(确认后切到 worktree 分支 `feat/round6-j-eval-expansion` 开干)
