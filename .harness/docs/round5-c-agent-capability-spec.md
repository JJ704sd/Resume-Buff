# Round 5-C — Agent 真实闭环与可解释化 Spec

> 适用项目: 简历帮
> 日期: 2026-06-28
> 状态: ✅ **已完成 (R5-C Phase 1-5 全部落地,baseline 487→544 pytest 全绿)**
> 当前基线: GitHub `main` = `09a2704dd7f54170d83be35e788c945dcae4ed6c`(R5-B Phase 2A merge);本地 `c6ead64`(R5-C Phase 2 merge)+ R5-C Phase 1/3/5 未 commit 改动
> 前置: R5-A Phase 1-4 + closeout 已完成 ✅;R5-B Phase 2A 工具 schema/context/effective tools 已完成 ✅
> 后端测试: **544 passed + 0 skipped**(487 R5-B Phase 2A baseline + 17 R5-C Phase 2 + 10 R5-C Phase 3 + 15 R5-C Phase 5 + ~15 R5-C Phase 1 from test_agent_eval.py)
> 目标: 把已经可审计的 Agent 后端能力推进到"可评测、可解释、可被前端安全消费"的真实闭环 ✅

---

## 0. 背景

R5-B Phase 2A 已经解决“工具能不能被安全调用”的问题:

- `core/tool_schema.py` 已有轻量 JSON schema validator。
- `execute_agent_tool()` 已有 context 权限边界。
- `ToolSpec.metadata["affects_preview"]` 已定义有效工具语义。
- `agent_summary.tools_used` 只列成功且真正影响 preview 的工具。

现在剩下的高价值问题不是继续扩 allowlist,而是让 Agent 链路对用户和评测都更可信:

1. eval 能精确关联一次 workflow,不用猜最后一条 trace。
2. 外部简历从“JD 评分辅助输入”升级为 Agent workflow 的真实输入。
3. bullet 评估从 representative 单步升级为可解释的批量诊断。
4. 前端能展示安全摘要,但不暴露原文和 PII。

---

## 1. 非目标

- 不做自动投递、招聘网站爬取、HR 跟踪。
- 不新增账号、鉴权、公网部署、多用户隔离。
- 不引入向量数据库、embedding API、Redis、后台队列。
- 不把完整 JD、完整简历、完整 bullet、真实姓名、手机号、邮箱写入 trace、eval report 或前端 Agent 面板。
- 不默认开启 Agent workflow;默认路径继续保持 `enable_agent_workflow=False` 字节级稳定。

---

## 2. Phase 1 — Eval request_id 精确关联与 fallback taxonomy

### 2.1 目标

修复 `scripts/evaluate_agent_workflow.py` 当前从 JSONL 最后一条事件反推 request_id 前缀的脆弱逻辑。eval 应直接读取:

```python
request_id = preview.get("agent_summary", {}).get("request_id")
tools_used = preview.get("agent_summary", {}).get("tools_used", [])
fallback_used = preview.get("agent_summary", {}).get("fallback_used", False)
```

JSONL replay 只作为交叉验证,不作为主数据源。

### 2.2 fallback 分类

新增 eval 内部字段 `fallback_category`,至少区分:

| 类别 | 含义 | 来源 |
|---|---|---|
| `none` | 无 fallback | `agent_summary.fallback_used=False` |
| `llm_disabled_fallback` | 无 LLM key,改写走原文 | `is_llm_enabled() == False` 且 FC/AW 路径需要 LLM |
| `tool_error_fallback` | 工具失败但 workflow 继续或降级 | JSONL / `agent_summary.fallback_reason` |
| `schema_retry_fallback` | LLM schema retry 后仍失败 | `llm_rewriter` 现有 schema failure 路径 |
| `workflow_abort_fallback` | required step 或 workflow 主体失败 | `fallback_reason` |

不要求 Phase 1 一次性让所有类别都能由真实路径触发;但报告结构和测试要锁住分类语义。

### 2.3 测试

新增或更新:

- `TestEvalUsesAgentSummaryRequestId`
- `TestEvalToolsUsedPrefersAgentSummary`
- `TestEvalFallbackCategoryNone`
- `TestEvalFallbackCategoryLlmDisabled`
- `TestEvalReportNoRawRequestIdLeak`

### 2.4 验收

- `scripts/evaluate_agent_workflow.py` 不再读取“最后一条 step=0 trace”来推断主 request。
- 报告仍保持 8 节结构,新增 fallback taxonomy 摘要。
- 报告不输出完整 request_id;展示短串即可。
- 后端全量 pytest 通过。

---

## 3. Phase 2 — 外部简历进入 Agent workflow

### 3.1 API 输入

`PreviewRequest` 增加:

```python
external_resume_text: str | None = None
```

规则:

- 只在 preview 链路使用;generate 不强制消费外部简历。
- `enable_external_resume` 可保留向后兼容,但新逻辑应以 `external_resume_text` 非空作为 `has_external_resume` 的真实依据。
- API 不落盘 external resume 文本。

### 3.2 新工具

在 `core/agent_tools.py` 注册两个工具:

| 工具 | permission | pii_risk | affects_preview | 输出 |
|---|---|---:|---:|---|
| `parse_external_resume` | `read_external_resume` | high | false | 压缩后的关键词/profile,不含段落原文 |
| `compare_resume_jd` | `read_jd_and_external_resume` | high | false | have/need/gap/suggestions 摘要 |

建议输出:

```json
{
  "external_resume_perspective": {
    "have_keywords": ["LLM", "Python"],
    "need_keywords": ["原型", "流程图"],
    "materials_can_cover": ["Python"],
    "resume_only_keywords": ["Docker"],
    "suggestions": ["补充 PM 维度素材: 物流 / 原型 / 流程图"],
    "counts": {
      "have": 2,
      "need": 2,
      "materials_can_cover": 1,
      "resume_only": 1
    }
  }
}
```

### 3.3 Workflow 任务图

当 `external_resume_text` 非空:

```text
parse_user_intent
-> parse_jd / match_score / retrieve_evidence
-> retrieve_materials
-> parse_external_resume
-> compare_resume_jd
-> evaluate_bullet_jd_match?
-> rewrite_highlights
-> aggregate_preview
```

注意:

- `parse_external_resume` 和 `compare_resume_jd` 初期不标 `affects_preview=True`,先作为诊断信息输出。
- 如果后续要让外部简历影响素材排序或改写,必须单独升版并补 baseline 测试。

### 3.4 隐私边界

- `ToolResult` 不存 external resume 原文。
- JSONL trace 只写 `input_size/output_size`。
- `agent_summary` 只写工具名、状态、fallback、耗时。
- `external_resume_perspective` 不返回段落原文,只返回关键词和数量。

### 3.5 测试

- `TestExternalResumeWorkflowUsesText`
- `TestParseExternalResumeToolPrivacy`
- `TestCompareResumeJdOutputSchema`
- `TestExternalResumeTraceNoRawText`
- `TestExternalResumeOldPathUnchanged`

---

## 4. Phase 3 — per-bullet 真实评估数据流

### 4.1 目标

把当前 representative 单条 bullet 评估升级为确定性批量评估,让 Agent 能解释“哪些项目/亮点最贴 JD,哪些缺口需要补素材”。

### 4.2 候选选择

从 `build_sections()` 的候选项目中选:

- top projects: 默认 3 个。
- each project top bullets: 默认 3 条。
- 无 JD 时不执行。
- 无 bullets 时跳过,不报错。

### 4.3 输出结构

返回压缩结果,不返回完整 bullet 文本:

```json
{
  "bullet_evaluations": [
    {
      "project_id": "llm_eval_platform",
      "bullet_index": 0,
      "matched_keywords": ["LLM", "评测"],
      "missing_keywords": ["流程图"],
      "matched_count": 2,
      "missing_count": 1,
      "suggestion": "补流程设计或原型素材"
    }
  ]
}
```

### 4.4 affects_preview 语义

Phase 3 初始建议:

- `evaluate_bullet_jd_match` 仍保持 `affects_preview=False`,因为它先作为诊断输出。
- 当后续明确把 `bullet_evaluations` 用于排序、筛选或 prompt 约束时,再改为 `affects_preview=True`。

### 4.5 测试

- `TestBulletEvaluationSelectsTopProjects`
- `TestBulletEvaluationNoRawBulletInTrace`
- `TestBulletEvaluationOutputSchema`
- `TestBulletEvaluationSkippedWithoutJd`
- `TestAffectsPreviewStillFalseUntilConsumed`

---

## 5. Phase 4 — 前端高级 Agent 面板

> GUI 任务默认等用户明确启动。若启动,只做默认收起的高级面板,不改变主流程。

### 5.1 TypeScript 契约

更新 `frontend/src/api/index.ts`:

```ts
export interface AgentSummary {
  request_id: string
  steps_executed: number
  tools_used: string[]
  fallback_used: boolean
  fallback_reason?: string | null
  latency_ms: number
}

export interface EvidenceSummary {
  source_type: string
  source_id: string
  matched_keywords: string[]
  confidence: number
}

export interface ExternalResumePerspective {
  have_keywords: string[]
  need_keywords: string[]
  materials_can_cover: string[]
  resume_only_keywords: string[]
  suggestions: string[]
  counts: {
    have: number
    need: number
    materials_can_cover: number
    resume_only: number
  }
}
```

`PreviewResponse` 增加可选字段:

```ts
agent_summary?: AgentSummary
evidence_summary?: EvidenceSummary[] | null
external_resume_perspective?: ExternalResumePerspective | null
bullet_evaluations?: BulletEvaluation[] | null
```

### 5.2 preview/generate 参数

`resumeApi.preview()` 支持:

- `enable_agent_workflow`
- `enable_function_calling`
- `session_id`
- `external_resume_text`

`resumeApi.generate()` 可先只支持 `enable_agent_workflow` / `enable_function_calling` / `session_id`,不默认传 external resume。

### 5.3 UI 行为

在预览页增加默认收起面板:

- request_id 短串 + 复制按钮。
- tools_used 数量和名称。
- fallback 状态和耗时。
- evidence 来源类型统计,不展示完整 evidence text。
- 外部简历 have/need/gap 计数和建议。
- bullet 评估摘要,不展示完整原 bullet。

### 5.4 验收

- `cd frontend && npx vue-tsc --noEmit`
- `cd frontend && npm run build`
- 不开启 Agent workflow 时 UI 与当前预览页一致。
- 开启 Agent workflow 后,面板仅展示摘要,不展示 JD/简历/bullet 原文。

---

## 6. Phase 5 — 文档与回放闭环

### 6.1 文档更新

更新:

- `.harness/docs/ROADMAP.md`: 当前快照从 441 改为 487,并加入 R5-C 入口。
- `README.md`: 能力表只保留用户可见稳定事实,不要重复大段 spec。
- `AGENTS.md`: 只补 durable lock points,不要把完整 spec 复制进去。

### 6.2 replay 增强

保持 `scripts/replay_agent_trace.py` 的隐私约束不变,可新增:

- 根据 request_id 输出 fallback category 摘要。
- 根据 tools_used 与 trace 交叉验证是否一致。
- 仍不输出原文。

### 6.3 验收

- replay 输出字段仍只来自 trace schema / agent_summary 摘要。
- 文档中不出现“Phase 2A 仍未启动”之类过期描述。

---

## 7. 推荐实施顺序

1. **Phase 1 eval request_id**
   最小、风险低,立刻提升评测可信度。

2. **Phase 2 external resume workflow**
   复用已有 R3-G 能力,补上 Agent 工具链和隐私边界。

3. **Phase 3 per-bullet evaluation**
   把工具调用从 demo 变成真实诊断数据。

4. **Phase 4 frontend panel**
   等后端输出稳定后再做 UI,避免前端绑定不稳定字段。

5. **Phase 5 docs/replay**
   每个 phase 收尾时增量更新,最终统一校准。

---

## 8. 验证矩阵

后端:

```powershell
cd backend
D:\python3.11\python.exe -m pytest tests/ -v
```

前端:

```powershell
cd frontend
npx vue-tsc --noEmit
npm run build
```

脚本:

```powershell
D:\python3.11\python.exe scripts/evaluate_agent_workflow.py
D:\python3.11\python.exe scripts/replay_agent_trace.py --request-id <request_id>
```

隐私检查:

- trace / replay / eval report / frontend panel 不含完整 JD。
- trace / replay / eval report / frontend panel 不含完整外部简历。
- trace / replay / eval report / frontend panel 不含完整 bullet。
- 只允许公开脱敏 placeholder。

---

## 9. 完成定义

Round 5-C 完成时应满足:

- eval 能直接用 `agent_summary.request_id` 精确关联 trace。
- eval report 能区分 fallback 类别。
- 外部简历文本能进入 Agent workflow,但不泄露原文。
- per-bullet 评估输出可解释摘要,不输出完整 bullet。
- 前端能默认收起地展示 Agent 摘要,不改变旧路径体验。
- `enable_agent_workflow=False` 时 preview/generate 旧路径保持字节级稳定。
- 后端 pytest、前端类型检查、前端构建全部通过。
