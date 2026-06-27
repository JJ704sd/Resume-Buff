# Round 5-B — Agent 能力产品化与可信闭环 Spec

> 适用项目: 简历帮  
> 日期: 2026-06-27  
> 状态: Future spec / 未启动  
> 前置: R5-A Phase 1-4 代码与测试已在当前工作区出现,但 Phase 4 相关文件仍处于未提交状态  
> 目标: 在不改变本地单用户与隐私边界的前提下,把 R5-A 已落地的 Agent 后端能力整理成稳定 API 契约、真实工具数据流、可解释 UI 和更可靠评测闭环。

---

## 0. 现状审计摘要

本轮对照 `.harness/docs/agent-enhancement-spec.md` 检查后,当前项目整体已经实现 R5-A 的主体架构:

- `backend/core/agent_tools.py`: 集中式 `AGENT_TOOLS` 注册表 + `execute_agent_tool()` 统一入口,已含 `parse_jd` / `match_score` / `evaluate_bullet_jd_match` / `retrieve_evidence` / `rewrite_highlights`。
- `backend/core/agent_workflow.py`: 受控 Plan-and-Execute workflow,`build_task_graph()` 确定性产任务图,`enable_agent_workflow=True` 时可跑 preview/generate,并写 JSONL trace。
- `backend/core/logger.py`: `JSONL_TRACE_FIELDS` 11 字段 schema + `log_agent_trace_jsonl()`。
- `backend/core/evidence.py`: 轻量 RAG evidence snippets + lexical retrieval + prompt summary。
- `scripts/replay_agent_trace.py`: request/session 级 markdown replay。
- `scripts/evaluate_agent_workflow.py` + `backend/tests/test_agent_eval.py` + `AI岗位JD库_agent_eval报告.md`: Phase 4 eval 已在工作区出现。

同时存在 9 个需要下一轮处理的差距:

1. `agent-enhancement-spec.md` 顶部仍写 Phase 4 未启动,后文又写 Phase 4 已完成,文档状态自相矛盾。
2. 同一 spec 的推荐下一步仍建议从 Phase 1 + Phase 2 开始,已过期。
3. spec 提到 `agent_trace` 请求字段,但 API 模型没有该字段。
4. spec 提到 `agent_summary` 响应,但 preview 目前只在 workflow 路径返回 `evidence_summary`,没有 request_id / tools / fallback / latency 汇总。
5. 前端 API 类型和 UI 尚未暴露 `enable_agent_workflow` / `enable_function_calling` / `session_id` / `agent_summary` / `evidence_summary`。
6. `ToolSpec.input_schema` 目前主要是元数据,`execute_agent_tool()` 未主动做 schema 校验或上下文权限校验。
7. workflow 内 `has_external_resume = False` 固定,外部简历诊断尚未纳入 Agent 编排。
8. `evaluate_bullet_jd_match` 在 workflow 里仍是 representative 单步,不是逐 bullet 评估。
9. eval 脚本需要从 JSONL 反推工具调用,因为 preview 响应没有稳定 `request_id`。

---

## 1. 目标

Round 5-B 聚焦"把 Agent 能力变得可用、可解释、可信":

1. 建立稳定的 Agent API 契约:请求字段、响应字段、trace request_id、前端类型全部对齐。
2. 让工具注册表从"能调"升级为"可校验、可授权、可审计"。
3. 把外部简历诊断纳入 Agent workflow,形成 JD / 素材库 / 已有简历三方对比。
4. 提供默认收起的前端高级 Agent 面板,展示摘要而非原文。
5. 升级 eval 报告,从"能跑"变成"能真实衡量 fallback、工具链、延迟和证据约束"。

非目标:

- 不做自动投递、招聘网站爬取、HR 跟踪。
- 不新增账号系统、鉴权、公网部署、多用户隔离。
- 不引入向量数据库、embedding API、Redis 或长时任务队列。
- 不把完整 JD、完整简历、完整 bullet、真实联系方式写进日志、trace 或报告。
- 不默认开启 GUI 高级面板;前端展示保持高级/调试性质,默认收起。

---

## 2. Phase 1 — Agent API 契约与文档收口

### 2.1 后端响应新增 `agent_summary`

`preview_resume(enable_agent_workflow=True)` 返回:

```json
{
  "agent_summary": {
    "request_id": "rabcdef12",
    "workflow": "preview",
    "steps": 7,
    "tools_used": ["parse_jd", "match_score", "retrieve_evidence"],
    "fallback_used": false,
    "fallback_reason": null,
    "latency_ms": 18,
    "evidence_count": 4,
    "trace_available": true
  }
}
```

约束:

- `agent_summary` 不含 JD 原文、bullet 原文、evidence text 原文。
- `request_id` 必须与 JSONL trace 的 request_id 一致。
- `enable_agent_workflow=False` 时默认不返回 `agent_summary`,保持旧路径结构。
- `generate` 返回 FileResponse,不强行塞 JSON metadata;如需追踪,只在 trace 中记录 generate workflow。

### 2.2 API 请求字段整理

保留:

- `enable_agent_workflow: bool = False`
- `enable_function_calling: bool = False`
- `session_id: str | None = None`

不新增 `agent_trace` 字段。理由:

- 本地单用户场景下,只要 workflow 开启就写 trace;trace 写失败不影响主流程。
- 是否展示 trace 是前端高级面板的 UI 状态,不是后端行为开关。
- 避免出现"workflow 开了但 trace 关了,eval/replay 无 request_id"的不可解释状态。

### 2.3 文档收口

更新现有文档:

- `.harness/docs/agent-enhancement-spec.md`: 修正 Phase 4 状态,删除/改写过期的"下一步从 Phase 1 + Phase 2 开始"。
- `.harness/docs/ROADMAP.md`: 测试数、Phase 4 状态、后续候选同步为 R5-B。
- `AGENTS.md` / `README.md`: 只同步稳定事实,不重复大段 spec。

### 验收

- 新增 `TestAgentSummaryContract`: request_id 格式、tools_used、fallback 字段、隐私字段缺失。
- 新增 `TestPreviewAgentSummary`: `enable_agent_workflow=True` 时响应含 `agent_summary`,False 时旧路径不含。
- replay 脚本可用 preview 返回的 `request_id` 拉出同一次 workflow。

---

## 3. Phase 2 — 工具契约、权限与真实数据流

### 3.1 Schema 校验

实现轻量 schema validator,只覆盖当前 `ToolSpec.input_schema` 用到的子集:

- `type`: object / string / integer / number / boolean / array
- `required`
- `properties`
- `items`
- `minimum` / `maximum`

失败时:

- 不调用工具函数。
- 返回 `ToolResult(status="error", error_type=ToolErrorType.TOOL_ARGS_INVALID)`。
- `error_msg` 只写字段名和类型摘要,不写参数原文。

### 3.2 Context 权限校验

为 `execute_agent_tool(tool_name, args, context)` 启用 context:

```python
context = {
  "allow_jd_text": True,
  "allow_materials": True,
  "allow_external_resume": False,
  "max_pii_risk": "medium",
}
```

规则:

- 工具 permission 与 context 不匹配时返回 `privacy_violation` 或 `tool_not_allowed`。
- `parse_external_resume` / 外部简历相关工具默认需要 `allow_external_resume=True`。
- trace 仍只写工具名、状态、错误类型、长度。

### 3.3 真实工具数据流

减少"展示型工具调用":

- `rewrite_highlights` 工具 trace 要对应实际改写链路,不能只调用 representative bullet 作为占位。
- `evaluate_bullet_jd_match` 从 representative 单步升级为 per-project top bullets 批量评估,输出压缩后的 `bullet_evaluations`。
- `agent_summary.tools_used` 只统计实际影响本次 preview 的工具。

### 验收

- `TestToolSchemaValidation`: 缺 required、类型错、范围错均返回 `TOOL_ARGS_INVALID`。
- `TestToolPermissionContext`: materials/JD/external resume 权限不匹配时拒绝,且不泄露原文。
- `TestWorkflowEffectiveTools`: `tools_used` 与实际执行且影响输出的工具一致。
- 旧路径 `enable_agent_workflow=False` 字节级不变。

---

## 4. Phase 3 — 外部简历 Agent 诊断

### 4.1 新增 workflow 输入

`PreviewRequest` 增加:

```python
external_resume_text: str | None = None
```

前端已有 `ResumeUploader` 可产出外部简历全文;R5-B 只把这段文本透传到 preview,不在 generate 强制使用。

### 4.2 工具注册

新增工具:

- `parse_external_resume`: 输入外部简历文本或解析后的 paragraphs,输出关键词/段落摘要。
- `compare_resume_jd`: 输入 jd_profile、materials_score、external_resume_profile,输出 have/need/gap。

输出结构:

```json
{
  "external_resume_perspective": {
    "have_keywords": ["LLM", "Python"],
    "need_keywords": ["流程图", "原型"],
    "materials_can_cover": ["Python"],
    "resume_only_keywords": ["Docker"],
    "suggestions": ["补充 PM 维度素材:物流/原型/流程图"]
  }
}
```

### 4.3 隐私边界

- external resume 原文不写 JSONL trace。
- `agent_summary` 只写 have/need 数量,不写段落原文。
- eval 报告不输出 external resume 文本。

### 验收

- `TestExternalResumeWorkflow`: 有 external resume 时任务图包含 external resume 相关步骤。
- `TestExternalResumePrivacy`: trace 和 agent_summary 不含 external resume 原文。
- `TestResumePerspectiveConsistency`: 与现有 `match_score(..., external_resume_text=...)` 的 have/need 语义保持一致。

---

## 5. Phase 4 — 前端高级 Agent 面板

> 该 phase 属于 GUI 实施任务。遵循 ROADMAP 用户偏好:默认暂停,只有用户明确说"启动前端 Agent 面板"才实施。

### 5.1 TypeScript 契约

更新 `frontend/src/api/index.ts`:

- Preview request 参数支持 `enable_agent_workflow` / `enable_function_calling` / `session_id` / `external_resume_text`。
- `PreviewResponse` 增加可选 `agent_summary` / `evidence_summary` / `external_resume_perspective` 类型。

### 5.2 UI 行为

在预览页增加默认收起的高级面板:

- 显示 request_id 短串、工具数、是否 fallback、总耗时。
- 显示 evidence 数量与来源类型统计,不展示完整 evidence text。
- 显示外部简历 have/need 关键词数量和建议。
- 提供"复制 request_id"按钮,方便本地运行 replay 脚本。

### 验收

- `cd frontend && npx vue-tsc --noEmit` 0 error。
- `cd frontend && npm run build` 成功。
- 手测:不开 Agent 开关时 UI 与当前预览页一致;开启后高级面板出现摘要。

---

## 6. Phase 5 — Eval 报告升级

### 6.1 稳定 request_id

eval 脚本不再从 JSONL 反推最近 request:

- 直接读取 preview 返回的 `agent_summary.request_id`。
- 用 request_id 精确 replay。
- `tools_used` 来源优先使用 `agent_summary.tools_used`,JSONL 仅作为交叉验证。

### 6.2 真实 fallback 统计

区分:

- `llm_disabled_fallback`: 无 key,预期 fallback。
- `tool_error_fallback`: 工具失败导致 fallback。
- `schema_retry_fallback`: LLM schema retry 后仍失败。
- `workflow_abort_fallback`: required step 失败。

### 6.3 Mock LLM 与真实 LLM 双模式

默认无 key:

- 走 deterministic / mocked path。
- 不联网。
- 验证 schema、trace、工具链和隐私。

有 key:

- 记录真实 latency、fallback rate、schema pass rate。
- 报告明确标注模型、base_url 是否本地/远端,但不写 API key。

### 验收

- `TestEvalUsesAgentSummaryRequestId`
- `TestEvalFallbackCategories`
- `TestEvalNoRawTextInReport`
- eval 报告 8 节结构保留,新增"真实 LLM 可选基线"小节。

---

## 7. 实施顺序建议

推荐顺序:

1. Phase 1: 先做 API 契约和文档收口。没有 request_id / agent_summary,后面的 UI 和 eval 都会继续绕路。
2. Phase 2: 再做 schema/权限和真实工具数据流。它能把 Agent 从"可演示"推进到"可审计"。
3. Phase 3: 接外部简历诊断。后端已经有 R3-G 基础,增量可控。
4. Phase 5: 升级 eval 报告。此时 request_id 与 fallback 分类已经稳定。
5. Phase 4: 前端高级面板最后做,且等用户明确启动 GUI。

最小可交付切片:

- Phase 1 + Phase 2 的后端测试全部通过。
- 不做前端 UI,只补 TypeScript API 类型也可以先暂停。
- 不改默认行为,不开 `enable_agent_workflow` 时用户体验完全不变。

---

## 8. 验证矩阵

后端:

- `cd backend && D:\python3.11\python.exe -m pytest tests/ -v`
- 新增行为至少覆盖 agent_summary、schema validation、permission context、external resume privacy、eval request_id。

前端:

- `cd frontend && npx vue-tsc --noEmit`
- `cd frontend && npm run build`

脚本:

- `D:\python3.11\python.exe scripts/evaluate_agent_workflow.py`
- `D:\python3.11\python.exe scripts/replay_agent_trace.py --request-id <agent_summary.request_id>`

隐私:

- trace / replay / eval report 均不得包含完整 JD、完整简历、完整 bullet、姓名、手机号、邮箱。
- 只允许出现公开脱敏 placeholder。

---

## 9. 风险与回退

| 风险 | 影响 | 回退 |
|---|---|---|
| agent_summary 改响应结构影响前端 | 预览页类型不匹配 | 字段设为可选;默认 workflow 关闭不返回 |
| schema validator 过严 | 旧工具调用被拒绝 | 先以当前工具 schema 写回归测试,逐步收紧 |
| per-bullet evaluation 增加耗时 | preview latency 上升 | 只评估 top projects 的前 N 条,默认 N=3 |
| external_resume_text 误入日志 | PII 风险 | 新增隐私测试;trace 只记长度 |
| GUI 面板信息过多 | 主流程变吵 | 默认收起,只展示摘要和 request_id |

---

## 10. 完成定义

Round 5-B 完成时应满足:

- 当前 `agent-enhancement-spec.md` 状态与代码一致,不再出现 Phase 状态矛盾。
- preview workflow 返回稳定 `agent_summary`,且 request_id 能 replay。
- 工具输入 schema 和权限 context 有测试锁定。
- 外部简历能进入 Agent workflow,但不泄露原文。
- eval 报告不再靠脆弱 trace 反推,能精确关联 request_id。
- 默认关闭增强路径时,旧 preview/generate 行为保持不变。
