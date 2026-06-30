# Round 6-C — Interview Agent Live Eval 收益验证操作指南

> 适用项目: 简历帮 / Resume-Buff  
> 日期: 2026-06-30  
> 状态: 操作文档, 未运行 live eval  
> 范围: R6-B 后的人工收益验证流程;不改业务代码、不自动入库 live report

---

## 0. 目标

R6-C 的目标是验证 R6-B 已上线的 `llm_assisted` 智能抽取路径是否比 `rules` 规则路径更值得开放给用户。

本指南只说明如何在满足前置条件后手动运行 live compare eval、检查隐私边界、判断指标是否达标,以及如何决定下一步。不运行 live eval,不读取或输出真实 API key,不把报告自动入库。

---

## 1. 前置条件

必须同时满足:

- 当前代码基线为 R6-B Phase 0+1+2+3+4+5+6 已完成。
- 用户已在本地配置 LLM key,并确认 live 模式可以访问 OpenAI-compatible `/chat/completions`。
- 用户已在前端 Interview Agent 面板完成 10+ 轮真实对话,对话内容能代表真实投递场景。
- 用户接受 live eval 会发起真实 LLM 网络请求。
- `backend/logs/` 仍在 `.gitignore` 中,live report 默认只留本地。

说明:10+ 轮真实对话是产品收益判断的前置观察,用于确认真实使用中确实需要智能抽取;评测脚本本身仍按 `scripts/evaluate_interview_agent.py` 的 eval harness 生成聚合报告。最终决策应同时看真实使用体感和 live compare 指标。

运行前不要做这些事:

- 不要把真实 API key 写进文档、命令、commit message 或报告。
- 不要把 live report 自动 commit。
- 不要把真实 `backend/data/materials.json`、`backend/data/_private_backup.json` 或 `backend/logs/*` 混入提交。
- 不要修改 `backend/`、`frontend/`、`scripts/` 业务代码来适配本次操作。

---

## 2. 运行命令

在仓库根目录执行:

```powershell
Set-Location -LiteralPath D:\简历帮
D:\python3.11\python.exe scripts/evaluate_interview_agent.py --mode live --extractor compare --output backend/logs/interview_eval_report_live.md
```

预期行为:

- `--mode live` 会在有 LLM 配置时真实调用 LLM。
- `--extractor compare` 会对同一批 eval 样本跑 `rules` 和 `llm` 两组。
- 报告写入 `backend/logs/interview_eval_report_live.md`。
- stdout 只应输出聚合指标和报告路径,不应输出用户原文、prompt、raw response、source_span 或 API key。

如果脚本提示 live 模式缺少 LLM 配置,停止本轮验证。不要在对话或文档里粘贴 key;只在本地环境变量或本地 `.env` 中处理。

---

## 3. 隐私检查

live report 入库前必须人工审查。默认策略是:报告先只留在 `backend/logs/`,审查通过后再决定是否摘录指标到文档;不要直接提交完整 live report。

### 3.1 自动文本扫描

先跑基础扫描:

```powershell
Set-Location -LiteralPath D:\简历帮
Select-String -LiteralPath backend\logs\interview_eval_report_live.md -Pattern "LLM_API_KEY","BEGIN PROMPT","source_span","Bearer","sk-","raw response","user_message" -SimpleMatch
```

期望:无匹配。

再用用户自己从真实对话中挑出的 3-5 个短句哨兵做扫描。哨兵应来自真实 `user_message` 原文,例如一句独特项目描述或数字表述:

```powershell
Select-String -LiteralPath backend\logs\interview_eval_report_live.md -Pattern "短句哨兵1","短句哨兵2","短句哨兵3" -SimpleMatch
```

期望:无匹配。

### 3.2 人工审查清单

打开 `backend/logs/interview_eval_report_live.md`,逐节确认:

- report 不含 `user_message` 原文。
- report 不含 LLM prompt 正文。
- report 不含 raw response。
- report 不含 `source_span` 明文。
- report 不含 API key、key 前缀、Bearer header、env var 名或内部 base URL path/query。
- report 不含完整 draft bullets 原文或真实个人敏感信息。
- report 只包含聚合指标、fallback 分类、样本名、source 名、计数和比率。

任一项不满足时:

- 停止入库。
- 记录为隐私阻断问题。
- 先修 eval 报告脱敏边界,再重新运行 live eval。

---

## 4. 指标阈值

优先看 compare 报告里的 `llm` / `llm_assisted` 分组,并与 `rules` baseline 对照。

| 指标 | 达标阈值 | 判断方式 |
|---|---:|---|
| `schema_pass_rate` | `>= 0.60` | LLM 路径是否能稳定填齐 expected slots |
| `avg_completeness` | `>= 0.70` | draft_card 六类字段完整度是否足够 |
| `fabrication_violations_count` | `== 0` | 是否保持零编造硬事实 |
| `fallback_rate` | `<= 0.20` | live LLM 路径是否大部分没有回退规则版 |

辅助观察:

- `schema_pass_rate` 和 `avg_completeness` 至少不应低于 rules baseline。
- `fallback_rate > 0.20` 时,先排查 LLM 配置、网络、schema 解析和 fallback 分类。
- `fabrication_violations_count > 0` 是硬阻断,即使其他指标高也不能开放智能抽取。
- `low_confidence_slot_rate` 偏高时,说明抽取能工作但保存前人工确认压力仍大。

---

## 5. 后续决策

### 5.1 指标达标

条件:

- `schema_pass_rate >= 0.60`
- `avg_completeness >= 0.70`
- `fabrication_violations_count == 0`
- `fallback_rate <= 0.20`
- 隐私检查通过

决策:

- 可以考虑逐步开放智能抽取。
- 仍保持前端 toggle 默认关闭,先作为实验功能给用户手动开启。
- 文档只摘录聚合指标和结论,不提交完整 live report。

### 5.2 指标不达标

常见情况:

- `schema_pass_rate < 0.60`
- `avg_completeness < 0.70`
- `fallback_rate > 0.20`
- LLM 相比 rules 没有提升

决策:

- 暂不扩大智能抽取入口。
- 优先优化 slot extraction prompt 或 rules fallback。
- 如果是 schema / JSON 失败多,先优化 LLM 输出约束和解析兜底。
- 如果是漏抽关键 slot 多,先对照失败样本修 prompt 或补规则抽取。
- 修完后重新跑 live compare,不要用单次失败报告直接 rollout。

### 5.3 文件维护压力变大

触发条件:

- `backend/core/interview_agent.py` 继续膨胀到难以审阅或测试。
- LLM call、slot extraction、fallback、slot_meta 逻辑互相缠绕。
- live eval 显示 LLM 路径值得继续投资,但当前文件边界拖慢迭代。

决策:

- 另开机械拆分 `core/interview_llm.py` 的重构 round。
- 重构原则是行为不变、测试先行、只搬 LLM slot extraction 相关逻辑。
- 不在 live eval 验证 round 中混入重构。

---

## 6. 建议记录模板

如果隐私审查通过,可在后续文档中只记录如下摘要:

```markdown
## R6-C live eval 摘要

- 运行日期:
- 命令: `D:\python3.11\python.exe scripts/evaluate_interview_agent.py --mode live --extractor compare --output backend/logs/interview_eval_report_live.md`
- 样本数:
- rules schema_pass_rate:
- llm schema_pass_rate:
- llm avg_completeness:
- llm fabrication_violations_count:
- llm fallback_rate:
- 隐私检查: 通过 / 不通过
- 结论: 达标开放 / 不达标优化 / 先做机械拆分
```

不要摘录:

- 用户回答原文。
- LLM prompt。
- raw response。
- source_span。
- API key 或环境变量名。
- 完整 draft bullet 原文。

---

## 7. 本轮边界

R6-C live eval 操作指南不做:

- 不运行 live eval。
- 不读取或输出真实 API key。
- 不把 live report 自动入库。
- 不改 `backend/`、`frontend/`、`scripts/` 业务代码。
- 不开放智能抽取默认开启。
- 不重构 `core/interview_agent.py`。
- 不提交 `backend/logs/interview_eval_report_live.md`。
