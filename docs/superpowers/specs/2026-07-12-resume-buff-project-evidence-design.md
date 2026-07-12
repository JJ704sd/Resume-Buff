# Resume-Buff 项目经历证据与面试版块设计

## 1. 目标

将 Resume-Buff 从简历上的“素材库 + 简历生成器”扩展为一套可被面试官追问、也能用源码证明的 AI 应用项目叙事：

- 上层：4 条可直接放入简历的项目 bullet，突出 AI 应用 / Agent 能力。
- 下层：每条 bullet 绑定功能、源码锚点、数据流、可量化证据、面试追问和回答骨架。
- 边界：只写当前代码和仓库记录已经支持的能力，不把实验脚本、规划项或未验证的线上能力包装成已上线能力。

项目定位建议：

> Resume-Buff 是一个本地单用户的 JD 驱动 AI 简历与面试证据系统：用户维护结构化素材库，系统按岗位和 JD 生成可预览、可下载的简历，并通过证据检索和多轮追问补齐项目事实。

## 2. 简历上层：推荐 4 条 bullet

### 2.1 结构化素材与统一生成

设计项目 / 技能 / 荣誉 / 证书等结构化素材库，按岗位角色选择项目和 role-specific highlights；由同一套 `sections` 数据同时驱动前端预览与 `.docx` 生成，支持多模板、JD 感知排序和无 key 时的原文降级，避免“预览内容”和“下载文件”不一致。

证据锚点：`backend/core/generator.py:344` 的 `build_sections`、`backend/core/generator.py:1037` 的 `render_docx`、`backend/core/generator.py:1080` 的 `preview_resume`、`backend/core/generator.py:1186` 的 `generate_resume_docx`。

### 2.2 JD 解析、匹配与项目重排

实现规则驱动的 JD 解析与 0–100 匹配评分：按 skills / tools / domains 三类关键词做加权 coverage，输出命中项、缺失项、投递建议和 required / preferred / bonus 分层；匹配结果进一步用于项目、项目亮点和技能组排序，并支持外部简历的 have / need 对比。

证据锚点：`backend/core/jd_parser.py:581` 的 `match_score`、`backend/core/jd_parser.py:709` 的 `_build_resume_perspective`、`backend/core/generator.py:426` 的项目重排、`frontend/src/App.vue:782` 的评分卡展示。

### 2.3 证据检索与受控 Agent workflow

把素材库中的项目亮点、技能、荣誉和证书切成不可变 evidence snippets，按 JD 关键词命中、置信度和稳定排序检索 top-k；再通过固定的 Plan-and-Execute 任务图串联 JD 解析、匹配、证据检索、bullet 评估和改写。工具执行统一经过 allowlist、JSON schema、权限和 PII 风险校验，异常时回退普通生成路径，trace 只记录步骤、状态、耗时和输入输出长度。

证据锚点：`backend/core/evidence.py:38` 的 `EvidenceSnippet`、`backend/core/evidence.py:275` 的 `retrieve_evidence`、`backend/core/agent_workflow.py:166` 的 `build_task_graph`、`backend/core/agent_workflow.py:359` 的 `run_agent_workflow`、`backend/core/agent_tools.py:384` 的 `execute_agent_tool`。

### 2.4 JD 驱动的面试追问与事实核验

实现独立的面试 Agent API：从 JD 缺口选择追问主题，围绕 background / responsibility / action / method / result / metric 等槽位进行多轮问答；策略层按“可生成条件、低置信度、关键槽位、轮数上限和防重复”决定下一问，生成可编辑 draft card，核验每条 bullet 是否有槽位或量化数据来源，用户确认后再以新项目写回素材库。

证据锚点：`backend/api/interview.py:237`、`backend/api/interview.py:279`、`backend/api/interview.py:326`、`backend/api/interview.py:382` 四个端点；`backend/core/interview_policy.py:406` 的 `plan_next_question`；`backend/core/interview_agent.py:1283` 的 `build_draft_card`；`backend/core/interview_verifier.py:263` 的 `verify_draft_card`。

## 3. 证据下层：功能—实现—面试展开矩阵

| 版块 | 用户可见功能 | 直接实现证据 | 面试可展开点 |
|---|---|---|---|
| 素材库 | 维护一份结构化事实源，按 role 取不同 highlights | `api/materials.py` 的 GET / PUT；`generator.py:288` 的 fallback 链 | 为什么不用直接维护多份简历；如何避免事实漂移 |
| 生成链路 | 预览、确认、下载 `.docx` | `build_sections` → `preview_resume` / `generate_resume_docx` | 如何保证 preview / download 一致；模板和 sections 如何解耦 |
| JD 匹配 | 评分、coverage、命中 / 缺失关键词、建议 | `jd_parser.py:581` 的加权 score 与三维 coverage | 权重怎么设计；borrowed pool 如何缓解 false negative |
| Evidence | 从项目和技能中返回与 JD 相关的 top-k 事实片段 | `EvidenceSnippet` + `retrieve_evidence` | 为什么先规则检索；稳定排序和置信度如何保证可复现 |
| Agent | 固定任务图、工具注册、权限、trace、fallback | `build_task_graph` + `execute_agent_tool` + JSONL trace | 为什么不是让 LLM 自由规划；工具失败如何分关键 / 非关键 |
| 面试追问 | 选缺口、逐槽位追问、重述、跳过、切换 gap | `/api/interview/start` / `reply` | 状态机有哪些状态；question plan 如何成为唯一决策源 |
| 草稿核验 | 检查 bullet 是否有事实来源、量化来源和低置信度风险 | `verify_draft_card` | verifier 不调用 LLM 的原因；如何避免“0 个 unsupported”误导 |
| LLM 可靠性 | 有 key 才启用，无 key / 网络错 / schema 错均可回退 | `interview_llm.py:234`、`:367`、`:441` | 网络错误为什么不重试；JSON/schema retry 与 rules fallback 的边界 |
| 质量与隐私 | 测试、类型检查、构建、离线评测、敏感信息不落 trace | `AGENTS.md` 记录 948 passed + 0 skipped；`agent_workflow.py:383` 的 trace 约束 | 如何验证 fallback、PII、API 契约和端到端闭环 |

## 4. 一条完整数据流的面试讲法

```text
结构化素材库 + JD
        ↓
parse_jd / match_score
        ↓
命中关键词、缺失项、岗位缺口
        ↓
retrieve_evidence(top-k)
        ↓
固定 Agent task graph
        ↓
受 evidence 约束的 bullet 改写 / sections 构造
        ↓
前端预览 → 人工 review → DOCX 下载

另一条补素材闭环：

JD 缺口 → 面试 Agent 选 gap → 多轮槽位抽取
        ↓
draft_card → verifier / confidence notes
        ↓
用户编辑确认 → save_card → 写回 materials.json
```

讲解时应强调：LLM 是可选增强层，规则路径是默认基线；任务图本身由确定性代码生成，LLM 不负责决定关键步骤顺序。

## 5. 面试官高频追问与回答骨架

### Q1：为什么不直接把 JD 和简历扔给 LLM？

回答骨架：先把问题拆成确定性部分和不确定性部分。JD 关键词、岗位匹配、项目排序和素材事实检索用规则保证可解释、可复现；LLM 只做可选改写或槽位抽取。没有 key、网络失败或返回 schema 错误时仍能走 rules，核心生成链不会被外部模型阻断。

### Q2：0–100 匹配分是怎么算出来的？

回答骨架：先把 JD 归一化为 skills / tools / domains，再在素材库候选池中找命中项；同一关键词按最高权重计入，分组 coverage 是命中权重除以总权重，整体 score 是跨组去重后的加权命中率。候选池默认允许借用其他 role 的素材，避免只按当前岗位标签造成 false negative，同时保留 `include_borrowed=False` 的严格模式。

### Q3：Evidence 检索如何减少幻觉？

回答骨架：先把素材切成 `EvidenceSnippet`，只把与 JD 关键词命中的 top-k 片段和来源标识交给改写链；没有命中就返回空 evidence，让上层走无 evidence 分支。它是事实约束和可追溯输入，不声称能单独证明 LLM 永不幻觉；最终仍需要用户 review。

### Q4：你的 Agent 和普通 workflow 有什么区别？

回答骨架：这里的 Agent 不是自由发挥的自治体，而是受控编排层。任务图由 `build_task_graph` 确定性生成，工具只能从 allowlist 调用，参数先过 schema，再过权限和 PII 风险校验；每步产出结构化结果和脱敏 trace。这样保留了 Agent 的工具组合能力，同时把失败边界和审计成本控制住。

### Q5：面试 Agent 如何保证三轮内问到关键事实？

回答骨架：`plan_next_question` 按优先级处理：可生成条件缺口、低置信度复核、gap-specific critical slot、接近上限时的 result / metric、普通 suggested slot 和 anti-repeat。`question_plan.slot` 是问答和抽取共享的决策源，避免 UI 问 result、后端却把回答写进 method 的错位。

### Q6：LLM 抽取失败时具体怎么降级？

回答骨架：没有 key 时 session 直接进入 rules 模式；网络 / HTTP 错误不做 retry；返回内容无法解析或 schema 不合法时最多做解析 / schema retry，再回退规则抽取。session 记录 `slot_source_breakdown`、retry 次数和 fallback 次数，便于评估真实收益，而不是只看最终结果。

### Q7：为什么 verifier 不直接用 LLM？

回答骨架：verifier 处在保存前的风险门禁位置，需要稳定、低成本、可复现，所以用正则和槽位来源做确定性检查：量化数字是否来自 captured slots、bullet 是否能对应 action / responsibility / result / method / metric、是否涉及低置信度槽位。它给 warning，不把 unsupported claim 当成绝对阻断，最终仍由用户确认。

### Q8：这个项目的工程质量证据是什么？

回答骨架：仓库当前记录的后端基线是 948 passed、0 skipped；测试覆盖 JD 评分、evidence、Agent 工具和 workflow、面试状态机、LLM schema / retry / fallback、verifier、API 和隐私边界；前端另有 `vue-tsc` 与 Vite build 门禁。真正线上模型评测则作为手动 live eval，不混进默认启动流程。

## 6. 不宜过度承诺的说法

- 不写“全自动生成可信简历”：当前明确保留人工 review，LLM 是可选增强。
- 不写“自主 Agent 自动规划”：当前任务图是确定性 Plan-and-Execute，LLM 不参与规划。
- 不写“生产级多用户系统”：项目是本地单用户工具，`/api/materials` 无鉴权，不应直接暴露公网。
- 不写“LLM 已证明有效”：仓库默认 rules，live eval 需要配置 key 并手动运行；离线 compare 只能证明评测链路和 fallback 行为。
- 不把素材库中的医疗评测、ECG、开源复现经历混同为 Resume-Buff 自身功能；它们是被 Resume-Buff 管理和生成的用户项目素材。

## 7. 验收标准

1. 上层 4 条 bullet 能在一页简历中独立阅读，并且每条都能指向至少一个源码模块。
2. 下层矩阵能回答“功能是什么、代码在哪、为什么这样设计、失败怎么办、如何测试”。
3. 面试回答不把规则能力、LLM 能力、实验脚本和当前默认路径混为一谈。
4. 所有数字优先采用仓库已有记录；若未在本轮重新执行测试，表述为“仓库记录基线”，不伪装成即时实测。
