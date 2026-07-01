# Round 6-C Live Eval 结果归因与下一步规划

> 适用项目: 简历帮 / Resume-Buff  
> 日期: 2026-07-01  
> 状态: 决策记录 + 后续规划;不修改 backend / frontend / scripts 业务代码  
> 依据: 当前本地仓库、`backend/logs/interview_eval_report_live.md`、`round6-c-live-eval-guide.md`、`round6-b-interview-agent-intelligence-spec.md`、`ROADMAP.md`  
> 隐私边界: 本文只摘录聚合指标、slot key、计数和文件级事实;不摘录 user_message、prompt、raw response、source_span、draft bullet 原文或 API key 类凭据。

---

## 0. 一句话结论

本次 `--mode live --extractor compare` 跑通了真实 LLM 调用链路,但**不能证明 `llm_assisted` 已经比 `rules` 更值得开放**:

- 质量指标未达门槛: `schema_pass_rate=0.30`, `avg_completeness=0.53`。
- LLM 相对 rules 的质量增益为 0: `schema_pass_rate delta=+0.00`, `avg_completeness delta=+0.00`。
- 安全指标较好: `fabrication_violations_count=0`。
- 当前报告仍基于内置脱敏 eval set,不是 guide §1 要求的“10+ 轮真实前端对话”产品收益验证。

下一步不应直接“调 prompt”或“拆 `core/interview_llm.py`”。从第一性原理看,应先修正 eval contract 和报告口径,确认指标到底在衡量什么;再决定是否优化 LLM 抽取或重构模块边界。

---

## 1. 当前仓库事实核对

### 1.1 Git 与文件状态

- 当前分支: `main`
- 最近提交: `c4dc539 docs(round6-c): add live eval 操作指南`
- 目标文档当前是未跟踪文件: `.harness/docs/round6-c-live-eval-result-and-next-steps.md`
- 另有无关未跟踪目录: `.planning/面试讲解/`;本文档不触碰。

### 1.2 代码与测试基线

- 后端测试目录实际为 `backend/tests/`,不是根目录 `tests/`。
- 活跃基线仍按 AGENTS / ROADMAP: `863 passed + 0 skipped`。
- `backend/core/interview_agent.py` 当前本地行数为 **2074 行**,不是旧文档中的 1771 行。
- `scripts/evaluate_interview_agent.py` 当前内置 10 条样本;compare 后报告 20 行: rules 10 + llm 10。
- `MAX_TURNS_PER_GAP = 3`;eval harness 会跳过 `"整理成素材"` chip,其余 user messages 逐条走 `apply_action(... ANSWER ...)`。
- `schema_pass` 的实现只检查 `expected_slots` 的 key 是否在 `session.captured_slots` 中非空,**不检查 expected value 的文本匹配**。

### 1.3 LLM 抽取现状

- `SLOT_EXTRACTION_SYSTEM_PROMPT` 已要求“严格只输出 JSON”,并标注 string/list 类型。
- `_call_llm_for_slot_extraction` 已设置 `temperature: 0.0`。
- 当前请求体没有 `response_format={"type": "json_object"}`。
- LLM 只参与 `extract_slots` 阶段,不参与 `plan_next_question` / slot 选择;slot 顺序由 deterministic policy 决定。
- `_extract_slots_via_llm` 失败会返回 `None`,上层 fallback 到 `_extract_slots_by_rules`。

---

## 2. Live Eval 摘要

运行报告: `backend/logs/interview_eval_report_live.md`  
跑测时间: 2026-07-01 13:29:59  
命令来源: `round6-c-live-eval-guide.md` §2

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
| `fallback_rate` | `<= 0.20` | `0.00` | 表面达标,但口径不足 |
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
| `fallback_rate` | 0.00 | 0.00 | 0.00 |
| `avg_latency_ms` | 1 | 991 | +990ms |
| `p95_latency_ms` | 3 | 1377 | +1374ms |

结论: LLM 路径目前只带来网络延迟,没有带来可观测质量收益。

### 2.4 报告模板 caveat

live report 的元信息和延迟显示它确实跑在 live 模式,但 `## 2.5` 表头和说明仍出现 `offline → 强制规则 fallback` 文案。这是报告模板的陈旧措辞,不是本次运行实际模式。后续应优先修正,否则读者会误以为这份 report 是 offline compare。

### 2.5 fallback_rate caveat

`fallback_rate=0.00` 不能解释为“LLM 每轮抽取都稳定成功”。当前 eval row 的 `fallback_category` 由 extractor mode、session actual mode、error_type 分类;它没有逐 slot 记录“LLM 解析失败后是否 fallback 到 rules”。因此:

- `fb_cat=none` 只能说明 session 处于 `llm_assisted` 且没有 workflow 级 abort。
- 它不能区分“LLM 成功抽取”和“LLM 返回 None 后本轮规则兜底成功”。
- 如果后续要判断 LLM 真实收益,需要新增 per-row 或 per-slot 的 extraction source 汇总,但报告仍只能写 slot key / 计数,不能写原文。

---

## 3. Failure 模式归因

### 3.1 强证据: 三轮上限 + policy 顺序让部分 expected slot 不可达

`MAX_TURNS_PER_GAP=3`,而部分 gap 的 suggested slots 超过 3 个:

| gap | suggested slots | 前 3 轮通常覆盖 | 常见未覆盖 |
|---|---|---|---|
| `process_metric` | responsibility, action, result, metric | responsibility/action/result | metric |
| `tech_metric` | background, responsibility, action, method, result | background/responsibility/action | method/result |
| `communication` | background, action, method, result | background/action/method | result |
| `domain_x` | responsibility, action, method, difficulty, result | responsibility/action/method | difficulty/result |

这解释了 report 中的主要失败:

- `tech_metric` 4/4 fail: expected 常含 `method` / `metric` / `result`,但前三问多集中在 `background` / `responsibility` / `action`。
- `communication` 2/2 fail: expected 含 `responsibility` 或 `result`;其中 `responsibility` 不在该 gap 的 suggested slots 中,`result` 是第 4 位。
- `domain_x` 1/1 fail: captured 为 `responsibility/action/method`,若 expected 含 `metric` 或 `result`,三轮内很可能不可达。

这不是简单的“LLM 抽取不行”,而是 eval 合同没有说清楚: `expected_slots` 到底应该代表“用户答案里的业务真值”,还是“在当前 policy 和三轮上限内应被问到并抽到的 slot”。

### 3.2 中证据: LLM 介入点过晚

LLM 只在回答某个 slot 后做字段抽取,不决定下一问问哪个 slot。因此它无法主动把 `tech_metric` 的第 4/5 个 slot 提前,也无法让 `communication` 去问不在 suggested slots 中的 `responsibility`。

这解释了为什么 LLM 和 rules 的 captured slot key 完全同形,质量 delta 为 0。

### 3.3 弱证据: rules 子串匹配与低置信度

`low_confidence_slot_rate=0.23`,失败样本里常见 `background` / `responsibility` 低置信度。这里可能存在 rules fallback 关键词不足,但它不是首要根因。即使改善关键词,如果 eval 仍期望三轮内不可达的 slot,`schema_pass_rate` 仍会偏低。

---

## 4. 旧规划中不合理之处与修正

### 4.1 “重写 expected_slots 让它对齐 captured 前三轮”风险过高

旧稿建议把 expected 改成 `{background, responsibility, action}` 这类更容易通过的组合。这样确实可能抬高 `schema_pass_rate`,但它会把 eval 变成“迎合当前实现”,而不是衡量产品需要。

修正: 先新增 eval contract 检查,明确每条样本的 `expected_slots` 是否可达:

- expected slot 必须属于该 gap 的 suggested slots,否则标记为 `unreachable_expected_slot`。
- expected slot 如果排在 `MAX_TURNS_PER_GAP` 之后,必须有明确原因,例如 policy 的 near-limit metric 逻辑会提前问它。
- report 需要输出 `eval_contract_warnings_count`,用于提醒“本次指标是否可作为产品门槛”。

### 4.2 “fallback_rate 达标说明 LLM 稳定”不成立

当前 fallback 分类没有逐 slot 维度,不能证明 LLM 抽取没有发生本轮规则兜底。后续如果要评估 LLM 真实价值,应在不泄漏原文的前提下汇总:

- `slot_source_breakdown`: rules / llm / mixed 的计数。
- `llm_parse_retry_count`: JSON/schema retry 次数。
- `llm_to_rules_slot_fallback_count`: LLM 抽取失败后 slot 级 fallback 次数。

### 4.3 “马上拆 `core/interview_llm.py`”时机仍不对

当前文件已 2074 行,机械拆分的客观压力比旧稿更强。但 live eval 的结论是“LLM 暂无质量收益”,不是“LLM 值得继续大规模投资”。现在拆模块会产生迁移成本,却不能直接回答产品问题。

修正: 只有当 eval contract 修正后仍确认 LLM 路径值得继续迭代,或者用户明确要求维护性拆分时,才单独开 R6-D mechanical split round。

### 4.4 “优化 prompt 是 P1”需要降级

Prompt 可优化,但不是第一步。当前 prompt 已有 JSON 文本约束、类型约束和 `temperature=0.0`;缺的是 `response_format`、few-shot、slot-source/fallback 可观测性。若不先修 eval contract,改 prompt 后仍可能只是在不可达 expected 上打转。

---

## 5. 推荐后续路线

### 路线 A: R6-C.1 修 eval contract 与报告口径

优先级: 最高  
工作量: 1-2 小时  
目标: 让指标先可信,再谈优化。

建议改动:

- `scripts/evaluate_interview_agent.py`
  - 增加 `_validate_eval_contract(sample)` helper。
  - report 增加 eval contract warnings 章节。
  - 修正 live compare 下 `llm 意图(offline → 强制规则 fallback)` 的陈旧表头和说明。
  - `fallback_rate` 说明改为 workflow/session 级 fallback,避免暗示 slot 级 LLM 成功。
- `backend/tests/test_interview_eval.py`
  - 增加 expected slot 不在 suggested slots 时产生 warning 的测试。
  - 增加 expected slot 超出三轮可达范围时产生 warning 的测试。
  - 增加 live report 表头不出现 offline stale wording 的测试。
  - 增加报告不泄漏 user_message / prompt / source_span 的回归测试。

验收:

- `D:\python3.11\python.exe -m pytest backend/tests/test_interview_eval.py -q`
- 必要时跑 `D:\python3.11\python.exe -m pytest backend/tests/ -q`
- 重新生成一份 live 或 offline compare 报告,确认指标旁边能看到 contract warning。

停止条件:

- 如果 warnings 解释了大多数 schema_fail,先不要动 LLM prompt。
- 如果 warnings 很少但 schema_pass 仍低,进入路线 B。

### 路线 B: R6-C.2 修样本或 policy,而不是“改软 expected”

优先级: 第二  
工作量: 1-3 小时  
目标: 让 eval set 衡量真实产品目标。

二选一:

- 如果目标是“3 轮内生成可保存素材”,则 expected 应只包含三轮内应该问到的关键 slot,并在样本注释里说明为什么这些 slot 足够 draft。
- 如果目标是“覆盖项目完整事实”,则样本应提供足够轮次,或 policy 应在接近上限时更早问 `result` / `metric` / gap-specific critical slot。

不建议:

- 不要单纯把 expected 改成当前 captured 的前三个 key。
- 不要用一次指标上升宣称 LLM 能力提升。

### 路线 C: R6-C.3 LLM 抽取可观测性 + prompt 小改

优先级: 第三  
工作量: 2-4 小时  
目标: 在指标可信后判断 LLM 是否真的贡献了抽取能力。

建议改动:

- 请求体增加 OpenAI-compatible `response_format={"type": "json_object"}`。
- prompt 增加 1-2 个短 few-shot,覆盖 string slot 和 list slot。
- 保持 `temperature=0.0`。
- 增加 slot 级 source 计数,报告只写 key/计数,不写原文。
- 若 LLM 输出非 dict、类型错、空 payload,记录 schema retry / fallback 计数。

验收:

- 863 pytest 全绿。
- live compare 中 LLM 组相对 rules 至少有一个质量指标明确提升,例如 `schema_pass_rate delta >= +0.05` 或 `avg_completeness delta >= +0.05`。
- `fabrication_violations_count` 仍为 0。
- 隐私扫描无命中。

### 路线 D: R6-D 机械拆分 `core/interview_llm.py`

优先级: 条件触发  
工作量: 1-2 小时  
目标: 降低维护成本,行为不变。

触发条件满足任一条即可开:

- 用户明确要求拆分。
- eval contract 修正后确认 LLM 值得继续投入,且后续要连续改 LLM call / prompt / fallback。
- `interview_agent.py` 继续膨胀并明显拖慢 review / 测试维护。
- 新增功能需要同时改 LLM 路径 3 处以上。

拆分原则:

- 机械搬迁,行为不变。
- 不改 API contract。
- 不新增依赖。
- 不 import `core.llm_rewriter`。
- 不把 policy / verifier / save-card 搬进 LLM 模块。
- 先写 `backend/tests/test_interview_llm.py`,再搬函数。

候选搬迁函数:

- `_resolve_interview_llm_config`
- `_call_llm_for_slot_extraction`
- `_try_parse_llm_content`
- `_validate_llm_extraction_payload`
- `_extract_slots_via_llm`
- `_attach_llm_slot_meta`
- `_decide_interview_mode`

---

## 6. 当前不做

- 不默认开启智能抽取 toggle。
- 不提交 `backend/logs/interview_eval_report_live.md`。
- 不把本次静态 eval set 的结果当作真实用户 10+ 轮产品收益结论。
- 不把 expected slots 直接改成 captured slots 来抬分。
- 不在 R6-C 收尾文档里混入代码修改。
- 不在没有收益证据前做大范围 LLM 架构改造。

---

## 7. 后续文档维护

需要更新本文档的时机:

- R6-C.1 修完 eval contract 后,补充 contract warning 的实测分布。
- R6-C.2 修样本或 policy 后,补充新的 schema/completeness 结果。
- R6-C.3 跑完 LLM prompt / observability 后,补充 LLM vs rules delta。
- 真正基于 10+ 轮前端真实对话跑 live eval 后,新增“产品收益结论”小节。
- 如果开 R6-D 拆分,把本文 §5 路线 D 转成独立 spec。

---

## 8. 参考

- `.harness/docs/round6-c-live-eval-guide.md`
- `.harness/docs/round6-b-interview-agent-intelligence-spec.md`
- `.harness/docs/ROADMAP.md`
- `scripts/evaluate_interview_agent.py`
- `backend/core/interview_agent.py`
- `backend/core/interview_policy.py`
- `backend/core/interview_prompts.py`
- `backend/tests/test_interview_eval.py`
- `backend/logs/interview_eval_report_live.md` (本地日志,不入库)
