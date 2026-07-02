# Round 6-C Live Eval 结果归因 + 收尾落地记录

> 适用项目: 简历帮 / Resume-Buff  
> 日期: 2026-07-02(初稿 2026-07-01,收尾更新 2026-07-02)  
> 状态: **R6-C 全 4 个 round + R6-D 行为不变重构 已全部落地**(commit `ea43473` / `a1a9fc2` / `caab6ff` + `651ea4e` / `84dd086` / `91ec8f3`);**活跃基线 930 passed + 0 skipped**(R6-C.3 收尾后保持,R6-D 行为不变维持)  
> 依据: 当前本地仓库、`backend/logs/interview_eval_report_live.md`(R6-C.0 live)、`backend/logs/interview_eval_report_r6c3.md`(R6-C.3 复跑 offline)、`round6-c-live-eval-guide.md`、`round6-b-interview-agent-intelligence-spec.md`、`AGENTS.md`、`ROADMAP.md`  
> 隐私边界: 本文只摘录聚合指标、slot key、计数和文件级事实;不摘录 user_message、prompt、raw response、source_span、draft bullet 原文或 API key 类凭据。

---

## 0. 一句话结论

R6-C 的核心命题:**LLM 抽取收益是否值得默认开启**。本次 live eval 跑通了真实 LLM 调用链路,但**目前没有证据证明 `llm_assisted` 比 `rules` 更值得开放**:

- 质量指标未达门槛: `schema_pass_rate=0.30`, `avg_completeness=0.53`(R6-C.0 live 与 R6-C.1+ C.2A offline 同值,合同驱动)。
- LLM 相对 rules 的质量增益为 0: `schema_pass_rate delta=+0.00`, `avg_completeness delta=+0.00`(R6-C.0 live compare 数据)。
- 安全指标稳定: `fabrication_violations_count=0`。
- 当前报告仍基于内置脱敏 eval set,不是 guide §1 要求的"10+ 轮真实前端对话"产品收益验证。

但 R6-C.1 / C.2A / C.2B / C.3 + R6-D 把**评测合同可信度**和**LLM 抽取可观测性**两条短板补齐:评测合同明确写下来(schema warnings / product_goal / observability §4.5+4.6+4.7),LLM 模块边界拆分清楚(R6-D `core/interview_llm.py` 独立,行为不变)。**为下一轮基于真实 10+ 轮对话的 live eval v2 准备就绪**。

---

## 1. 起点事实核对(R6-C.0 live eval 时点)

### 1.1 Git 与文件状态

- 当前分支: `main`
- 最近提交(R6-C.0 live 时点): `3b8b9d1 docs(round6-c): summarize live eval result and next steps`
- R6-C.0 live 报告: `backend/logs/interview_eval_report_live.md`(2026-07-01 13:29:59 跑测)
- 目标文档本次更新原因: R6-C 4 个 round + R6-D 已落地,需要把"路线 A/B/C/D 提案"转成"实际改动 + 测试结果 + 指标分布"

### 1.2 代码与测试基线

- 后端测试目录实际为 `backend/tests/`,不是根目录 `tests/`。
- R6-C.0 起点活跃基线: `863 passed + 0 skipped`(R6-B Phase 5 收尾)。
- `backend/core/interview_agent.py` 在 R6-C.0 时为 **2074 行**;R6-D 后降至 **1499 行**(`core/interview_llm.py` 537 行新模块承接 LLM 抽取主链)。
- `scripts/evaluate_interview_agent.py` 当前内置 10 条样本;compare 后报告 20 行: rules 10 + llm 10。
- `MAX_TURNS_PER_GAP = 3`;eval harness 会跳过 `"整理成素材"` chip,其余 user messages 逐条走 `apply_action(... ANSWER ...)`。
- `schema_pass` 的实现只检查 `expected_slots` 的 key 是否在 `session.captured_slots` 中非空,**不检查 expected value 的文本匹配**。

### 1.3 LLM 抽取现状(R6-C.0 起点 vs R6-C.3 收尾)

| 维度 | R6-C.0(起点) | R6-C.3(收尾) | 落点 |
|---|---|---|---|
| 请求体 `response_format` | 缺失 | `{"type": "json_object"}` | R6-C.3 |
| `SLOT_EXTRACTION_SYSTEM_PROMPT` few-shot | 无 | 2 个短示例(string + list,脱敏) | R6-C.3 |
| `temperature` | `0.0` | `0.0`(字节级一致) | — |
| `InterviewSession` 3 可观测字段 | 无 | `slot_source_breakdown` / `llm_parse_retry_count` / `llm_to_rules_slot_fallback_count` | R6-C.3 |
| `extract_slots` 是否接 `session` | 否(unused) | 是(累计 3 字段) | R6-C.3 |
| LLM call 模块归属 | `core/interview_agent.py` 2184 行内 | `core/interview_llm.py` 537 行独立 | R6-D |
| LLM prompt 注册表 | `core/interview_prompts.py` 独立常量 | 不入 `PROMPT_VERSIONS`(决策点 D5,沿用 R6-A Phase 4) | — |

### 1.4 老路径字节级一致(R6-C.1 / C.2A / C.2B / C.3 / R6-D 共同约束)

- `enable_interview_llm=False` 默认 session 不走 LLM 抽取,3 个可观测字段保持 `0 / {} / {}`(R6-C.3 显式测试锁)。
- `_extract_slots_by_rules` 不写 LLM 可观测字段(R6-C.3 锁,避免老路径污染)。
- R6-D 拆分后 `core/interview_agent.py` 通过 `from core.interview_llm import ...` 重导出全部符号,测试 / scripts 仍可 `from core.interview_agent import _attach_llm_slot_meta` 调用。
- `core/interview_llm.py` 反向依赖禁止:`TYPE_CHECKING` 块以外不 import `core.interview_agent`(防循环依赖);任何位置不出现 `from core.llm_rewriter import ...`(R5-E 边界保持)。

---

## 2. R6-C.0 Live Eval 摘要(原文要点回顾)

运行报告: `backend/logs/interview_eval_report_live.md`  
跑测时间: 2026-07-01 13:29:59  
命令: `D:\python3.11\python.exe scripts/evaluate_interview_agent.py --mode live --extractor compare --output backend/logs/interview_eval_report_live.md`

### 2.1 LLM 元信息

| 字段 | 值 |
|---|---|
| requested mode | `live` |
| resolved mode | `live` |
| extractor | `compare` |
| llm_enabled | `True` |
| llm_model | `gpt-4o-mini` |
| llm_base_url_host | `api.openai.com` |

### 2.2 指标

| 指标 | 门槛 | 实测 | 判断 |
|---|---:|---:|---|
| `schema_pass_rate` | `>= 0.60` | `0.30` | 未达标 |
| `avg_completeness` | `>= 0.70` | `0.53` | 未达标 |
| `fabrication_violations_count` | `== 0` | `0` | 达标 |
| `fallback_rate` | `<= 0.20` | `0.00`(session 级) | 表面达标,但口径不足(R6-C.1 已声明) |
| `low_confidence_slot_rate` | 辅助观察 | `0.23` | 需关注 |
| `avg_latency_ms` | 辅助观察 | `496` | 仅参考 |
| `p95_latency_ms` | 辅助观察 | `1213` | 仅参考 |

### 2.3 Rules vs LLM-assisted

| 指标 | rules | llm | Delta(llm - rules) |
|---|---:|---:|---:|
| 样本数 | 10 | 10 | - |
| `schema_pass_rate` | 0.30 | 0.30 | +0.00 |
| `avg_completeness` | 0.53 | 0.53 | +0.00 |
| `fabrication_violations` | 0 | 0 | - |
| `fallback_rate`(session 级) | 0.00 | 0.00 | 0.00 |
| `avg_latency_ms` | 1 | 991 | +990ms |
| `p95_latency_ms` | 3 | 1377 | +1374ms |

结论: **LLM 路径目前只带来网络延迟,没有带来可观测质量收益**。

### 2.4 R6-C.0 报告模板 caveat(已被 R6-C.1 修)

R6-C.0 live report 的元信息和延迟显示它确实跑在 live 模式,但 `## 2.5` 表头和说明仍出现 `offline → 强制规则 fallback` 文案。R6-C.1(`ea43473`)已修正 live compare 下表头 stale wording: 按 `requested_mode` 动态化 — `live` → "live + 已配置 LLM 凭据 → 真实 LLM 抽取",`offline` → "offline → 强制规则 fallback"。

### 2.5 R6-C.0 fallback_rate caveat(已被 R6-C.1 + C.3 联合修)

`fallback_rate=0.00` 在 R6-C.0 不能解释为"LLM 每轮抽取都稳定成功",原因是当时 fallback 分类没有逐 slot 维度。R6-C.1 在报告 §二 加口径声明明确是 workflow / session 级聚合,**不是** slot 级 LLM 成功率;R6-C.3 新增 §4.7 `slot_source_breakdown` / `llm_parse_retry_count` / `llm_to_rules_slot_fallback_count` 三个可观测字段,逐样本 + 按 source + 按 extractor 拆分,真正可逐样本 / 逐轮判断 LLM 抽取质量(offline 跑实测 rules=60 / llm=0 / mixed=0 / retries=0 / fb=0,符合 offline 模式不发网络预期)。

---

## 3. Failure 模式归因(原文分析,R6-C.1+ C.2A 验证后细化)

### 3.1 强证据: 三轮上限 + policy 顺序让部分 expected slot 不可达(R6-C.1 contract warnings 量化)

R6-C.1 落地后报告 `## 4.5 Eval contract warnings` 自动产出 **6 条 unique warning**(按 sample 去重,compare 模式双组同跑不重复):

| sample | gap | slot | code |
|---|---|---|---|
| `sim_tech_metric_medical_eval` | `tech_metric` | `metric` | `unreachable_expected_slot` |
| `sim_tech_metric_ecg` | `tech_metric` | `method` | `beyond_three_turns_expected_slot` |
| `sim_tech_metric_ecg` | `tech_metric` | `metric` | `unreachable_expected_slot` |
| `sim_communication_volunteer` | `communication` | `responsibility` | `unreachable_expected_slot` |
| `sim_tech_metric_rubric_design` | `tech_metric` | `method` | `beyond_three_turns_expected_slot` |
| `sim_tech_metric_rubric_design` | `tech_metric` | `metric` | `unreachable_expected_slot` |

`code` 含义: `unreachable_expected_slot` = expected slot 不在该 gap 的 `GAP_SUGGESTED_SLOTS` 中;`beyond_three_turns_expected_slot` = expected slot 在 suggested 顺序中位置 ≥ `MAX_TURNS_PER_GAP`(=3),且不属于 near-limit 触达集合 `{metric, result}`,前 3 轮内很可能无法被问到。

### 3.2 中证据: LLM 介入点过晚(同原文)

LLM 只在回答某个 slot 后做字段抽取,不决定下一问问哪个 slot。因此它无法主动把 `tech_metric` 的第 4/5 个 slot 提前,也无法让 `communication` 去问不在 suggested slots 中的 `responsibility`。这也解释了为什么 LLM 和 rules 的 captured slot key 完全同形,质量 delta 为 0。

### 3.3 R6-C.2B 修复: policy gap-specific critical slot 补足

针对 R6-C.1 contract warning 6 条中 5 条 unreachable / beyond warning(`sim_tech_metric_medical_eval` 的 metric / `sim_tech_metric_ecg` 的 metric+method / `sim_tech_metric_rubric_design` 的 metric+method / `sim_communication_volunteer` 的 responsibility),R6-C.2B 通过 policy 内部优先级链新增 **step 4.5 (gap_critical_slot_priority)** 修复:

- 新增 `INTERVIEW_POLICY_GAP_CRITICAL_SLOTS` 常量 2 entries:`tech_metric: ("metric", "method")` + `communication: ("responsibility",)`,放在 policy 内部,不污染 `GAP_SUGGESTED_SLOTS`(后者是 LLM 抽取端的引导顺序,改它会污染 LLM 抽取链路)。
- 新增 `_find_missing_critical_slots(session)` 纯 dict lookup 返回未 captured 列表,配置顺序保留。
- 优先级位置: step 4.5 在 step 4 (low_confidence) 之后, step 5 (near_limit) 之前。
- 注意:R6-C.2B **不期望** `schema_pass_rate` 提升 — eval 走 `_extract_slots_iteratively` 路径(基于 `_current_slot` 按 gap.suggested_slots 顺序)不走 policy,改动只影响 `next_question` 路径(前端 chat panel UI)。

### 3.4 弱证据: rules 子串匹配与低置信度(同原文)

`low_confidence_slot_rate=0.23`,失败样本里常见 `background` / `responsibility` 低置信度。这里可能存在 rules fallback 关键词不足,但它不是首要根因。即使改善关键词,如果 eval 仍期望三轮内不可达的 slot,`schema_pass_rate` 仍会偏低。

---

## 4. 本阶段(R6-C.1+ C.2A+ C.2B+ C.3+ R6-D)实际改动清单

### 4.1 R6-C.1 — eval contract warnings + live compare wording fix(commit `ea43473`, 2026-07-01)

路线 A 实施:

- `scripts/evaluate_interview_agent.py` 新增 `_validate_eval_contract(sample)` 纯函数: 校验 `expected_slots` 是否在对应 gap 的 `GAP_SUGGESTED_SLOTS` 内 + 在 `MAX_TURNS_PER_GAP=3` 范围内可达;near_limit 触达集合 `{metric, result}` 跳过 beyond 检查。
- 2 个新 warning code 常量 `EVAL_CONTRACT_WARN_UNREACHABLE` / `EVAL_CONTRACT_WARN_BEYOND_3`。
- `write_report` 新增 `## 4.5 Eval contract warnings` 章节,按 sample 去重(compare 模式双组同跑不重复),只列 sample/gap/slot/code 4 字段不含 user_message。
- 修正 live compare 表头 stale wording(按 `requested_mode` 动态化: live → "live + 已配置 LLM 凭据 → 真实 LLM 抽取",offline → "offline → 强制规则 fallback")。
- §二 fallback_rate 口径声明明确为 workflow / session 级,不是 slot 级 LLM 成功率。
- **14 个 R6-C.1 pytest** = `tests/test_interview_eval.py` 增量: TestPhaseC1EvalContractValidation 7 + TestPhaseC1ReportContractSection 2 + TestPhaseC1ReportWording 3 + TestPhaseC1ReportPrivacy 2。
- baseline 863 → **877 全绿**(14 新增, 863 老测试零回退)。
- **不挂 pre-push hook / 不修改 `core/` / `evaluate_agent_workflow.py` / `evaluate_prompt_versions.py` / 任何前端**。

### 4.2 R6-C.2A — fix eval set contract(commit `a1a9fc2`, 2026-07-01)

路线 A 收尾,**不改 policy**:

- 10 条 eval sample 各加 `product_goal` (枚举 `three_turn_friendly` / `full_fact_coverage`) + `contract_note` (str, 合同决策说明) 2 个字段。
- `communication_club` (plan_baseline) 调整 `expected_slots`: 移除 `responsibility` (不在 `communication` suggested), 改为 `(action, method, result)` 表达 "3 轮内可生成素材" 目标。
- 7 条 simulated samples **不删 expected** (符合"完整项目事实覆盖"目标), 保留含 unreachable / beyond 的 slot, 在 `contract_note` 字段标记 "需后续 policy 调整"。
- `write_report` 新增 `## 4.6 Eval contract: product goal` 章节,按 sample 去重列表展示 product_goal / 合同说明。
- §八 结论追加 "schema_pass_rate 数值变化 = 评测合同变化" 口径声明。
- **验收口径** (R6-C.2A 强制): `schema_pass_rate` 数值变化必须解读为 **评测合同变化** (`expected_slots` 调整 / `product_goal` 标记), **不**解读为 LLM 抽取能力提升或下降。
- **禁止** 把 `expected_slots` 改成当前 captured slot keys (作弊) — 测试 `test_communication_club_removed_responsibility_slot` 锁死(`communication_club` 改后 expected `(action, method, result)` 含 result,captured 没,证明是合同驱动)。
- **`product_goal` 分工**: `plan_baseline` (3 条) 标 `three_turn_friendly` (3 轮内可生成素材, 调整后 0 warning), `simulated_user_v1` (7 条) 标 `full_fact_coverage` (完整项目事实覆盖, 保留 expected, 6 条 unique warning 跨 4 条 sample)。
- **12 个 R6-C.2A pytest** = `tests/test_interview_eval.py::TestPhaseC2EvalContract` 12 case。
- baseline 877 → **889 全绿** (12 新增, 877 老测试零回退)。
- **offline 实测** = `total=10 schema_pass_rate=0.30 avg_completeness=0.53 fabric_violations=0 low_confidence_slot_rate=0.23`(跟 R6-C.1 baseline 一致, 0.30 不变但内部 fail 原因变了 — 合同驱动)。
- **不挂 pre-push hook / 不修改** `core/` / `core/interview_agent.py` / `core/interview_prompts.py` / `core/interview_policy.py` / `core/interview_verifier.py` / 任何前端。

### 4.3 R6-C.2B — policy gap-specific critical slot 补足(commit `caab6ff` + merge `651ea4e`, 2026-07-01)

路线 B 收尾(R6-C.2A 路线 A 不改 policy,本轮路线 B 改 policy 让 critical slot 三轮内可达):

- **核心边界** — 只改 `backend/core/interview_policy.py` + `backend/tests/test_interview_policy.py` + `backend/tests/test_interview_agent.py` 3 个文件。
- **不修改** `core/interview_agent.py` 的 LLM 抽取逻辑 / `core/interview_prompts.py`(`GAP_SUGGESTED_SLOTS` 是 LLM 抽取端引导顺序, 改它会污染 LLM 抽取链路)。
- **改动内容**:
  - `INTERVIEW_POLICY_GAP_CRITICAL_SLOTS` 新常量 2 entries(`tech_metric: ("metric", "method")` + `communication: ("responsibility",)`)
  - `INTERVIEW_POLICY_REASON_GAP_CRITICAL_SLOT = "gap_critical_slot_priority"` 新 reason_code
  - `_find_missing_critical_slots(session)` 新 helper 纯 dict lookup 返未 captured 列表(配置顺序保留)
  - `plan_next_question` 新增 **step 4.5** 优先级位置: step 4 (low_confidence) 之后, step 5 (near_limit) 之前, 触发条件 = 当前 gap 在 `INTERVIEW_POLICY_GAP_CRITICAL_SLOTS` 有配置 + 有未 captured 的 critical slot。
- **20 个 R6-C.2B pytest** = `tests/test_interview_policy.py`(TestPhaseC2BCriticalSlot 16 case: 2 critical priority 路径 + 2 优先级位置 + 4 step 4.5 不触发边界 + 2 critical captured / gap not in registry + 2 配置稳定性 + 3 schema 稳定性 + 1 已有 reason_codes_are_unique 注册新 code = 16 净增) + `tests/test_interview_agent.py`(TestPhaseC2BCriticalSlotIntegration 4 case: tech_metric_prioritizes_metric / communication_prioritizes_responsibility / step_4_5_does_not_break_combo1_chain + step_4_5_writes_message_log_for_anti_repeat)。
- baseline 889 → **909 全绿**(20 新增, 889 老测试零回退)。
- **实测** = `D:\python3.11\python.exe -m pytest tests/test_interview_policy.py tests/test_interview_agent.py -q` → 115 passed;`scripts/evaluate_interview_agent.py --mode offline` 仍跑 `total=10 schema_pass_rate=0.30 avg_completeness=0.53`(R6-C.2B **不期望** schema_pass_rate 提升 — eval 走 `_extract_slots_iteratively` 路径不走 policy, 改动只影响 `next_question` 路径即前端 chat panel UI)。
- **不挂 pre-push hook / 不引入新依赖(纯 stdlib) / 不修改** `core/interview_agent.py` / `core/interview_prompts.py` / 任何 `scripts/` / frontend / eval set。
- **不写** `backend/logs/interview_eval_report_live.md` (沿用边界)。

### 4.4 R6-C.3 — LLM 抽取可观测性 + prompt few-shot 优化(commit `84dd086`, 2026-07-02)

R6-C.2 阶段收尾增量(不拆模块, 4 个目标一次性交付):

- **核心边界** — 改 3 个 backend 文件 + 2 个测试文件:`backend/core/interview_prompts.py` / `backend/core/interview_agent.py` / `scripts/evaluate_interview_agent.py` / `backend/tests/test_interview_agent.py` / `backend/tests/test_interview_eval.py`。
- **不修改** `core/interview_policy.py` (R6-C.2B 路线 B 锁定) / `core/interview_verifier.py` (R6-B Phase 4 锁定) / `core/llm_rewriter.py` / 任何 frontend。
- **4 个目标落地**:
  1. `_call_llm_for_slot_extraction` request body 加 `response_format={"type": "json_object"}` 字段(在 messages 后 / temperature 前, OpenAI-compatible 端点强约束 JSON 输出, 降低 JSON parse retry 概率);temperature 仍 0.0(spec §4.4 字节级一致)。
  2. `SLOT_EXTRACTION_SYSTEM_PROMPT` 加 2 个短 few-shot 示例(覆盖 string slot `responsibility` + list slot `action`, 例子用脱敏描述 "数据标注 / 看样例 / 判断标准 / 边界", **不**含 JD 原文, 遵守 spec §4.4 模板不含 JD 全文隐私边界)。
  3. `InterviewSession` 新增 3 个可观测性字段(全部含默认值, 老测试构造兼容):`slot_source_breakdown: dict[str, int]` (rules / llm / mixed 计数, 每轮 answer 后 +1, 老路径 rules-only, LLM 成功 +llm, fallback 算 rules) + `llm_parse_retry_count: int` (累计 JSON parse / schema retry 次数, 网络错不 retry 故不计入) + `llm_to_rules_slot_fallback_count: int` (LLM 失败 fallback 规则版累计次数, 网络 + JSON + schema 错都算)。
  4. `scripts/evaluate_interview_agent.py` 扩展可观测性 4 链路:`EvalRow` 加 3 字段 (defensive copy 过滤未知 key / 非 int / bool);`compute_metrics` 加 3 聚合 + by_source 拆分 + by_extractor 拆分(compare 模式);`write_report` 新增 `## 4.7、LLM 抽取可观测性 (R6-C.3)` 章节(全局聚合表 + 按 source 拆 + 按 extractor 拆 + 隐私边界声明);每行 sample 摘要加 `src=[rules=N/llm=M/mixed=K] retries=N fb_to_rules=N` 3 字段;§八 结论追加 R6-C.3 LLM 抽取可观测性 1 行;§七 隐私检查加 1 行 "LLM 抽取可观测性只含 slot key + 整数计数 + 比率, 不含原文 (R6-C.3 保护)";`VERSION` 常量更新为 "R6-C.3 (LLM 抽取可观测性 + prompt few-shot; rules/llm/compare 三模式)"。
- **隐私边界 (R6-C.3)** — 3 字段只含整数 / 短字符串("rules" / "llm" / "mixed" 三个字面量), **绝不**含 user_message / source_span / draft_card / API key / prompt 正文 / raw response;EvalRow 在 `_evaluate_one` 末尾 defensive copy + 只取已知 key + int 校验, 防 session 字段污染。
- **21 个 R6-C.3 pytest** = `tests/test_interview_agent.py`(TestPhaseC3LLMObservability 11) + `tests/test_interview_eval.py`(TestPhaseC3ObservabilityFields 5 + TestPhaseC3ObservabilityReport 5)。
- baseline 909 → **930 全绿** (21 新增, 909 老测试零回退; 85.78s 跑完)。
- **实测** = `D:\python3.11\python.exe -m pytest tests/ -q` → 930 passed in 85.78s;`D:\python3.11\python.exe -m pytest tests/test_interview_agent.py tests/test_interview_eval.py -q` → 146 passed in 2.22s;前端 `npx vue-tsc --noEmit` 0 error + `npm run build` 成功。
- **offline compare 复跑实测** (`D:\python3.11\python.exe scripts/evaluate_interview_agent.py --mode offline --extractor compare --output backend/logs/interview_eval_report_r6c3.md`):
  - `total=20 (rules=10 + llm 意图=10) rules schema_pass=0.30 llm schema_pass=0.30 llm fallback_rate=1.00`
  - §4.7 章节渲染: `slot_source_breakdown.rules=60 llm=0 mixed=0 llm_rate=0.0 retries=0 fb_to_rules=0`(60 = 30 rules × 2 组 compare,符合 offline 模式 LLM 不发网络预期)
  - §4.5 章节渲染: 6 条 unique warning(同 4.1 列表)
  - §4.6 章节渲染: 10 条 sample(product_goal 分工 3+7)
- **不挂 pre-push hook / 不引入新依赖(纯 stdlib + urllib + json + dataclass) / 不引入新 LLM 调用 / 不破坏** R5-E / R6-B / R6-C.1 / R6-C.2 任何边界。

### 4.5 R6-D — 机械拆分 LLM slot 抽取模块(commit `91ec8f3`, 2026-07-02)

R6-C.3 之后行为不变重构(spec §5.3 + plan §4.4):

- **核心边界** — 改 1 个 backend 文件 + 新建 1 个 backend 文件 + 新建 1 个 backend 测试文件 + 改 1 个 backend 测试文件 + 改 1 个 api 测试文件:
  - `backend/core/interview_agent.py`(从 2074 行减到 **1499 行**)
  - `backend/core/interview_llm.py`(新建, **537 行**,含 R6-A Phase 4 LLM slot 抽取 + R6-B Phase 1 slot_meta helper + R6-B Phase 2 mode 决策 + R6-C.3 可观测性 schema 全部符号)
  - `backend/tests/test_interview_agent.py`(从 ~2674 行减到 **1410 行**, 删 6 个 LLM class)
  - `backend/tests/test_interview_llm.py`(新建, **1090 行**,平移 6 个 LLM class 共 35 case)
  - `backend/tests/test_interview_api.py`(3 处 monkeypatch 路径改 `core.interview_llm` 命名空间)
- **不修改** `core/interview_policy.py` (R6-C.2B 路线 B 锁定) / `core/interview_verifier.py` (R6-B Phase 4 锁定) / `core/llm_rewriter.py` / `core/interview_prompts.py` / `scripts/` / 任何 frontend / `evaluate_*`。
- **搬运符号清单** (7 函数 + 3 helper + 5 常量 + 2 mode 常量 + 1 schema dict) — `_resolve_interview_llm_config` / `_validate_llm_extraction_payload` / `_call_llm_for_slot_extraction` / `_try_parse_llm_content` / `_extract_slots_via_llm` / `_attach_llm_slot_meta` / `_decide_interview_mode` / `_has_llm_api_key` / `_validate_confidence` / `_compute_source_span_hash` / `_make_slot_meta` + `_INTERVIEW_LLM_DEFAULT_BASE_URL` / `_INTERVIEW_LLM_DEFAULT_MODEL` / `INTERVIEW_LLM_NO_KEY_WARNING` / `INTERVIEW_MODE_RULES` / `INTERVIEW_MODE_LLM_ASSISTED` / `INTERVIEW_SLOT_META_MIN_CONFIDENCE` / `INTERVIEW_SLOT_META_MAX_CONFIDENCE` / `INTERVIEW_SLOT_META_RULES_CONFIDENCE_FALLBACK` / `INTERVIEW_SLOT_META_LLM_DEFAULT_CONFIDENCE` / `INTERVIEW_OBSERVABILITY_SCHEMA`。
- **重导出策略** — `interview_agent.py` 通过 `from core.interview_llm import ...` 把全部上述符号 import 进自己命名空间,保持向后兼容,测试和 scripts 仍可 `from core.interview_agent import _attach_llm_slot_meta`。
- **反向依赖禁止**:
  - `interview_llm.py` 不得 import `core.interview_agent`(仅 `TYPE_CHECKING` 块 import `InterviewSession` 类型注解, 防循环依赖)
  - `interview_llm.py` 不得 import `core.llm_rewriter` (R5-E 边界保持)
- **0 新 pytest** —— R6-D 不引入新测试, 全部是行为不变机械平移。
- baseline 909 → **930 全绿**(R6-C.3 baseline 零回退, 行为不变重构; R6-C.2B 老路径字节级一致, R6-B 4 phases 锁定的 4 个 file 边界全部保持)。
- **实测** = `D:\python3.11\python.exe -m pytest tests/ -q` → 930 passed in 87.45s;`D:\python3.11\python.exe -m pytest tests/test_interview_agent.py tests/test_interview_llm.py tests/test_interview_eval.py -q` → 146 passed in 2.95s。
- **不挂 pre-push hook / 不引入新依赖(纯 stdlib + TYPE_CHECKING) / 不引入新 LLM 调用 / 不改** LLM prompt 内容 / retry 策略 / schema 限制 / frontend。

---

## 5. 测试命令和结果汇总

### 5.1 跑测命令

```powershell
Set-Location -LiteralPath D:\简历帮
D:\python3.11\python.exe -m pytest backend/tests/ -q
```

### 5.2 基线变化(每 round 收尾时实测)

| 时点 | commit | baseline | 新增 | 累计 |
|---|---|---:|---:|---:|
| R6-B Phase 5 收尾 | `717e47c` | 863 | — | 863 |
| R6-C.1 收尾 | `ea43473` | 863 | +14 | **877** |
| R6-C.2A 收尾 | `a1a9fc2` | 877 | +12 | **889** |
| R6-C.2B 收尾 | `651ea4e` | 889 | +20 | **909** |
| R6-C.3 收尾 | `84dd086` | 909 | +21 | **930** |
| R6-D 收尾 | `91ec8f3` | 930 | +0(行为不变) | **930** |

### 5.3 当前活跃基线(2026-07-02 实测)

```powershell
D:\python3.11\python.exe -m pytest backend/tests/ -q
# => 930 passed in 122.31s (0:02:02)
```

分模块跑测:

| 命令 | 结果 |
|---|---|
| `pytest backend/tests/test_interview_policy.py -q` | 45 passed in 0.32s |
| `pytest backend/tests/test_interview_llm.py -q` | 33 passed in 0.31s |
| `pytest backend/tests/test_interview_agent.py backend/tests/test_interview_llm.py backend/tests/test_interview_eval.py -q` | 146 passed in 2.95s |
| `pytest backend/tests/ -q` | **930 passed in 122.31s** |

前端:

| 命令 | 结果 |
|---|---|
| `cd frontend && npx vue-tsc --noEmit` | 0 error |
| `cd frontend && npm run build` | 成功(`dist/index.html 0.48kB / css 369kB / js 1104kB`) |

### 5.4 offline compare 报告复现(R6-C.3 落地的可观测字段验证)

```powershell
D:\python3.11\python.exe scripts/evaluate_interview_agent.py --mode offline --extractor compare --output backend/logs/interview_eval_report_r6c3.md
# => [ok] eval compare done. total=20 (rules=10 + llm 意图=10) rules schema_pass=0.30 llm schema_pass=0.30 llm fallback_rate=1.00
# => [ok] report -> backend\logs\interview_eval_report_r6c3.md
```

报告章节验证:

| 章节 | 内容 |
|---|---|
| `## 0` LLM 元信息 | `llm_mode: offline`, `llm_enabled: False`, `llm_model: gpt-4o-mini`, `llm_base_url_host: api.openai.com`(host 截取,不含 path/query/secret) |
| `## 一` Eval set 概览 | 20 条样本(compare 双组 ×10) |
| `## 二` 全局聚合 | `schema_pass_rate=0.30`, `fallback_rate=0.50`(含 `fb_cat=llm_disabled_fallback` llm 意图组), `avg_completeness=0.53`, `fabric_violations=0`, `low_confidence_slot_rate=0.23` |
| `## 2.5` Rules vs LLM-assisted 对照 | rules schema_pass=0.30 / llm schema_pass=0.30(offline 双组完全相同) |
| `## 三` fallback_category 分布 | `none=10 / llm_disabled_fallback=10 / 其它 3 类=0` |
| `## 四` 每条样本摘要 | 20 行,每行 14 字段(含 `src=[rules=N/llm=M/mixed=K] retries=N fb_to_rules=N` R6-C.3 新增) |
| `## 4.5` Eval contract warnings | **6 条** unique warning,按 sample 去重(见 3.1 表) |
| `## 4.6` Eval contract: product goal | **10 条** sample(product_goal 分工 3 `three_turn_friendly` + 7 `full_fact_coverage`) |
| `## 4.7` LLM 抽取可观测性 | `slot_source_breakdown.rules=60 / llm=0 / mixed=0 / llm_rate=0.0`(60 = 30 rules × 2 组 compare);`llm_parse_retry_count_total=0`;`llm_to_rules_slot_fallback_count_total=0`(offline 模式 LLM 不发网络,符合预期) |
| `## 五` Fabrication guard | 0 violation |
| `## 六` 延迟分布 | min=3ms / median=5ms / mean=4ms / p95=5ms / max=6ms |
| `## 七` 隐私检查 | `_check_pii_safe` 自检通过 + 7 条边界声明(含 R6-C.3 LLM 抽取可观测性保护) |

---

## 6. 新的指标或 warnings 分布(R6-C.1+ C.2A+ C.2B+ C.3 落地后)

### 6.1 R6-C.1 Eval contract warnings 分布(§4.5)

按 sample 去重后 **6 条 unique warning**(compare 模式双组同跑不重复),分布如下:

| gap | sample 数 | warning 类型 | 数量 |
|---|---|---|---:|
| `tech_metric` | 3 | `unreachable_expected_slot` (metric) | 3 |
| `tech_metric` | 2 | `beyond_three_turns_expected_slot` (method) | 2 |
| `tech_metric` | 2 | `unreachable_expected_slot` (metric) | 2 |
| `communication` | 1 | `unreachable_expected_slot` (responsibility) | 1 |
| **总计** | 4 sample | — | **6** |

按 sample 计: `sim_tech_metric_medical_eval` / `sim_tech_metric_ecg` / `sim_tech_metric_rubric_design` / `sim_communication_volunteer` 各有 1-2 条 warning,其他 6 sample 合同已合规。

### 6.2 R6-C.2A product_goal 分布(§4.6)

10 条 sample 全标注 `product_goal`,分工如下:

| source | 数量 | product_goal | 合同状态 |
|---|---:|---|---|
| `plan_baseline` | 3 | `three_turn_friendly` | 全部 0 warning(其中 `communication_club` 已调 `expected_slots` 移除 responsibility) |
| `simulated_user_v1` | 7 | `full_fact_coverage` | 4 sample 含 warning,3 sample 合同已合规 |

按 sample 合同状态:

- **6 条 3 轮内合同已合规**(`process_metric_course` / `communication_club` / `tech_metric_data` / `sim_process_metric_open_source` / `sim_domain_x_data_label` / `sim_process_metric_eval_pipeline`): responsibility/action/result 等关键 slot 都在 suggested 0-2 位置或 near_limit 触达,3 轮内可达。
- **4 条保留 expected 不删, 标记需后续 policy 调整**(`sim_tech_metric_medical_eval` / `sim_tech_metric_ecg` / `sim_communication_volunteer` / `sim_tech_metric_rubric_design`): 含 metric / method / responsibility 等 unreachable 或 beyond slot,保留 expected 表达 "完整项目事实覆盖" 目标,在 `contract_note` 字段标记 "需后续 policy 调整"。

### 6.3 R6-C.3 LLM 抽取可观测性分布(§4.7, offline 跑实测)

`D:\python3.11\python.exe scripts/evaluate_interview_agent.py --mode offline --extractor compare` 跑出来的可观测性指标:

| 指标 | 全局 | 按 source `plan_baseline` | 按 source `simulated_user_v1` | 按 extractor `rules` | 按 extractor `llm` |
|---|---:|---:|---:|---:|---:|
| `slot_source_breakdown.rules` | 60 | 18 | 42 | 30 | 30 |
| `slot_source_breakdown.llm` | 0 | 0 | 0 | 0 | 0 |
| `slot_source_breakdown.mixed` | 0 | 0 | 0 | 0 | 0 |
| `llm_parse_retry_count` | 0 | 0 | 0 | 0 | 0 |
| `llm_to_rules_slot_fallback_count` | 0 | 0 | 0 | 0 | 0 |

判断: **offline 模式 LLM 不发网络,符合预期**;`llm=0 / retries=0 / fb=0` 是正确行为,不能解读为 "LLM 抽取不稳定"。真实 LLM 调用需在 live 模式 + 已配置 LLM 凭据时才会出现 llm>0。

### 6.4 R6-C.2B policy step 4.5 优先级位置

新增优先级 step 在原 8 步链(spec §6)中的位置:

| step | 描述 | reason_code | R6-C.2B 影响 |
|---:|---|---|---|
| 0 | no_gap_selected | `no_more` / 无 | 无 |
| 1 | skip_count >= MAX | `force_draft_skip_limit` | 无 |
| 2 | turn_count >= MAX | `force_draft_turn_limit` | 无 |
| 3 | 任一 CAN_DRAFT 未满 | `missing_required_before_draft` | 无 |
| 4 | confidence < 0.6 | `low_confidence_recheck` | 无 |
| **4.5** | **gap 在 CRITICAL 配置 + 未 captured 的 critical slot** | **`gap_critical_slot_priority`** | **新增,覆盖 6 条 warning 中的 5 条** |
| 5 | turn_count >= MAX-1 + 缺 metric | `near_limit_priority_result_metric` | 无 |
| 6 | suggested 顺序下一未 captured | `next_suggested_slot` | 无 |
| 7 | anti-repeat | `anti_repeat_switch_slot` | 无 |
| 8 | suggested 全 covered | `all_gap_slots_covered` | 无 |

---

## 7. R6-C.0 旧规划中不合理之处与本阶段实际修正对照

| 旧规划(R6-C.0) | 实际修正(R6-C.1+ C.2A+ C.2B+ C.3+ R6-D) | 落点 commit |
|---|---|---|
| "重写 expected_slots 让它对齐 captured 前三轮"风险过高 → 先新增 eval contract 检查 | 新增 `_validate_eval_contract` + `## 4.5` 章节输出 6 条 unique warning + `## 4.6` product_goal 标注 | `ea43473` / `a1a9fc2` |
| "fallback_rate 达标说明 LLM 稳定"不成立 → 后续要汇总 slot_source_breakdown / retries / fb | 新增 §4.7 三字段可观测 + per-sample `src=[rules=N/llm=M/mixed=K] retries=N fb_to_rules=N` | `84dd086` |
| "马上拆 `core/interview_llm.py`"时机仍不对 → 等 eval contract 修正后再开 | 在 R6-C.3 把可观测性 + prompt few-shot 落定后,R6-D 才做机械拆分(行为不变,显式约束) | `91ec8f3` |
| "优化 prompt 是 P1"需要降级 → 先修 eval contract 再改 prompt | R6-C.3 顺序: 1. eval contract(C.1/C.2A) → 2. policy 补足(C.2B) → 3. 可观测性 + prompt few-shot(C.3) | `84dd086` |
| 路线 D 触发条件 = "用户明确要求 / LLM 值得继续投资 / 文件膨胀 / 新功能需改 LLM 3 处以上" | 实际触发条件: R6-C.3 落地后 LLM 模块边界清晰且可观测性就绪, 文件膨胀到 2074 行, 满足"文件膨胀"条件 | `91ec8f3` |

---

## 8. 当前边界(本阶段 R6-C.1+ C.2A+ C.2B+ C.3+ R6-D 后)

### 8.1 默认行为(R6-C.1+ C.2A+ C.2B+ C.3+ R6-D 后)

- `enable_interview_llm=False` 默认 session 仍走 rules-only 抽取,LLM 模块可观测字段保持 0 / {} / {}。
- `INTERVIEW_POLICY_GAP_CRITICAL_SLOTS` 已注册,前端 chat panel 用户实际对话时,`plan_next_question` 会优先追问 critical slot。
- eval compare 报告 §4.5 + §4.6 + §4.7 自动产出,用户/开发者跑 offline 可立即看到 contract warning + product_goal + LLM 抽取可观测性。
- `core/interview_llm.py` 独立模块,测试 / scripts 仍可 `from core.interview_agent import ...` 调用全部符号(重导出策略)。

### 8.2 当前不做

- **不**默认开启智能抽取 toggle(`enable_interview_llm=False` 仍是默认)。
- **不**提交 `backend/logs/interview_eval_report_live.md`(沿用 R6-C.0 边界)。
- **不**把本次静态 eval set 的结果当作真实用户 10+ 轮产品收益结论(simulated_user_v1 ≠ 真实使用反馈)。
- **不**把 expected slots 直接改成 captured slots 来抬分(R6-C.2A `test_communication_club_removed_responsibility_slot` 锁死)。
- **不**在 R6-D 重构里混入新行为(纯机械拆分, R6-C.3 baseline 零回退)。
- **不**改 `core/interview_policy.py`(R6-C.2B 路线 B 锁定) / `core/interview_verifier.py`(R6-B Phase 4 锁定) / `core/llm_rewriter.py`。
- **不**在 R6-D 里扩 `PROMPT_VERSIONS` 把 `SLOT_EXTRACTION_SYSTEM_PROMPT` 入注册表(决策点 D5 保持,R6-D 收尾后 next round 候选)。

### 8.3 文件级事实(本阶段改动的文件清单)

| 文件 | 状态 | 改动摘要 |
|---|---|---|
| `scripts/evaluate_interview_agent.py` | 改 | R6-C.1 14 行 + R6-C.2A 12 行 + R6-C.3 21 行(三阶段增量,~600 行) |
| `backend/core/interview_agent.py` | 改 | R6-C.3 18 行(3 个可观测字段 + extract_slots 接 session)+ R6-D -575 行(LLM 模块物理分离) |
| `backend/core/interview_llm.py` | 新建 | R6-D 537 行(LLM 抽取主链 + slot_meta helper + mode 决策 + observability schema) |
| `backend/core/interview_policy.py` | 改 | R6-C.2B ~80 行(step 4.5 + GAP_CRITICAL_SLOTS + 1 reason_code + 1 helper) |
| `backend/core/interview_prompts.py` | 改 | R6-C.3 ~40 行(2 个 few-shot 示例加 SLOT_EXTRACTION_SYSTEM_PROMPT) |
| `backend/tests/test_interview_agent.py` | 改 | R6-C.2B +11 + R6-C.3 +11 + R6-D -1264(LLM class 全部平移到 test_interview_llm) |
| `backend/tests/test_interview_llm.py` | 新建 | R6-D 1090 行(平移 6 个 LLM class 共 35 case) |
| `backend/tests/test_interview_policy.py` | 改 | R6-C.2B 新增 TestPhaseC2BCriticalSlot 16 case |
| `backend/tests/test_interview_eval.py` | 改 | R6-C.1 +14 + R6-C.2A +12 + R6-C.3 +10 |
| `backend/tests/test_interview_api.py` | 改 | R6-D 3 处 monkeypatch 路径改 `core.interview_llm` 命名空间 |
| `AGENTS.md` | 改 | R6-C.1/C.2A/C.2B/C.3 + R6-D 5 段锁死段落 + 活跃基线 863→930 |
| `.harness/docs/ROADMAP.md` | 改 | 见本文 §9 待办 |

---

## 9. 后续文档维护(本阶段同步 TODO)

- ✅ **已完成**: `round6-c-live-eval-result-and-next-steps.md`(本文)同步 R6-C.1+ C.2A+ C.2B+ C.3+ R6-D 实际改动 + 测试命令结果 + 新的指标分布 + R6-D 拆分落地。
- ✅ **已完成**: `AGENTS.md` 测试基线段落同步 863 → 877 → 889 → 909 → 930(R6-C.3 收尾)+ R6-D 行为不变维持 930(R6-C.3 起活跃基线)。
- ✅ **已完成**: `AGENTS.md` 新增 R6-C.1 / C.2A / C.2B / C.3 / R6-D 5 段锁死段落(详见 §10 ROADMAP 同步条目)。
- ⏸️ **ROADMAP 同步**(本 round 收尾时): 顶部快照段更新 R6-C + R6-D entry, P1 段加 R6-C 条目, 活跃基线 863→930, 历史快照列表更新。
- ⏸️ **下一轮候选(等用户明确启动)**:
  - R6-D+: LLM prompt 优化(根据真实对话数据迭代 few-shot + temperature 微调, 接入真实 LLM key 后跑 live compare v2)。
  - R6-D+: retry 策略升级(指数 backoff / multi-sample / best-of-N)。
  - R6-D+: token 成本控制(prompt 压缩 / 缓存命中检测)。
  - R6-D+: 扩 `PROMPT_VERSIONS` 把 `SLOT_EXTRACTION_SYSTEM_PROMPT` 入注册表(决策点 D5 突破, 需先收集 live v2 数据)。
  - R6-D+: 接入真实 LLM key 后跑 live eval v2(需用户在 chat panel 跑 10+ 轮真实对话, 满足 plan §5.1 启动条件)。

---

## 10. 参考

- `.harness/docs/round6-c-live-eval-guide.md`
- `.harness/docs/round6-b-interview-agent-intelligence-spec.md`
- `.harness/docs/ROADMAP.md`(本 round 收尾同步)
- `AGENTS.md`(R6-C.1 / C.2A / C.2B / C.3 / R6-D 5 段锁死段落 + 活跃基线 930)
- `scripts/evaluate_interview_agent.py`(R6-C.1 + C.2A + C.3 增量 + compare 三模式)
- `backend/core/interview_agent.py`(R6-C.3 18 行 + R6-D -575 行)
- `backend/core/interview_llm.py`(R6-D 新建 537 行)
- `backend/core/interview_policy.py`(R6-C.2B 80 行)
- `backend/core/interview_prompts.py`(R6-C.3 40 行)
- `backend/tests/test_interview_eval.py`(R6-C.1 +14 + C.2A +12 + C.3 +10)
- `backend/tests/test_interview_policy.py`(R6-C.2B 16 case)
- `backend/tests/test_interview_llm.py`(R6-D 新建 35 case)
- `backend/logs/interview_eval_report_live.md`(R6-C.0 live,本地日志,不入库)
- `backend/logs/interview_eval_report_r6c3.md`(R6-C.3 offline 复跑,本地日志,不入库)