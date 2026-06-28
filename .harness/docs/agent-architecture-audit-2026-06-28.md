# Agent 架构实现审计报告

> 日期: 2026-06-28
> 对照仓库: `https://github.com/JJ704sd/Resume-Buff`
> GitHub default branch: `main`
> 审计快照: `09a2704dd7f54170d83be35e788c945dcae4ed6c`
> 范围: 架构文档、Agent 后端、工具契约、trace/eval、外部简历链路、前端暴露面、测试基线

---

## 1. 结论摘要

当前本地项目与 GitHub `main` 完全对齐:本地 `HEAD`、`origin/main`、GitHub `HEAD` 均为 `09a2704dd7f54170d83be35e788c945dcae4ed6c`。

整体判断:

- `.harness/docs/architecture.md` 描述的 Vue SPA -> FastAPI -> backend core/data/output/logs 架构已按文档实现。
- `.harness/docs/agent-enhancement-spec.md` 中 R5-A Phase 1-4 + closeout 的主体能力已实现。
- R5-B Phase 2A 也已实现,代码和测试已经超过 `.harness/docs/round5-b-agent-capability-spec.md` 的旧 future 状态。
- 后端 Agent 能力已经具备:受控 workflow、工具注册表、schema 校验、权限 context、JSONL trace、RAG evidence、eval 脚本、隐私边界。
- 主要未完成项集中在产品闭环:eval 仍未直接用 `agent_summary.request_id`;外部简历尚未进入 Agent workflow;前端仍未暴露 Agent summary/evidence/trace 高级面板;`evaluate_bullet_jd_match` 仍是 representative 单步。

验证结果:

```text
cd backend && D:\python3.11\python.exe -m pytest tests/ -q
487 passed, 1 warning in 54.93s
```

唯一 warning 来自 replay CLI 测试中的 Windows 子进程 UTF-8 解码线程,未导致测试失败。

---

## 2. 文档与实现对照

| 文档要求 / 阶段 | 实现状态 | 证据 | 审计结论 |
|---|---:|---|---|
| 基础架构:Vue 3 SPA + FastAPI + backend core/data/output/logs | 已实现 | `frontend/src/App.vue`, `frontend/src/api/index.ts`, `backend/main.py`, `backend/api/*`, `backend/core/*` | 与 `architecture.md` 一致 |
| 6 role + 多模板 + JD-driven preview/generate | 已实现 | `backend/core/generator.py`, `backend/tests/test_generator_*` | 与 ROADMAP / README 一致 |
| R3-G 外部简历上传 + JD match 简历视角 | 已实现 | `backend/api/resume.py:/parse-external`, `backend/core/resume_parser.py`, `backend/core/jd_parser.py::match_score(external_resume_text=...)`, `frontend/src/components/ResumeUploader.vue` | 只在 JD 评分链路完整,尚未进入 Agent workflow |
| R4 Function Calling / Agent Loop / Session | 已实现 | `backend/core/llm_rewriter.py`, `backend/core/session.py`, `backend/core/logger.py::log_agent_trace` | 与 R4 MVP 文档一致 |
| R5-A Phase 1 Agent workflow + tool registry | 已实现 | `backend/core/agent_workflow.py`, `backend/core/agent_tools.py`, `backend/tests/test_agent_workflow.py` | 与 `agent-enhancement-spec.md` 一致 |
| R5-A Phase 2 JSONL trace + replay | 已实现 | `backend/core/logger.py::JSONL_TRACE_FIELDS`, `scripts/replay_agent_trace.py`, `backend/tests/test_agent_trace_replay.py` | 与 `agent-enhancement-spec.md` 一致 |
| R5-A Phase 3 轻量 RAG evidence | 已实现 | `backend/core/evidence.py`, `retrieve_evidence` tool, `backend/tests/test_evidence.py` | 与 `agent-enhancement-spec.md` 一致 |
| R5-A Phase 4 eval 报告 | 已实现 | `scripts/evaluate_agent_workflow.py`, `backend/tests/test_agent_eval.py`, `AI岗位JD库_agent_eval报告.md` | 已能跑 12 JD x 4 组开关 |
| R5-A closeout agent_summary / external flag / required args / target_role bugfix | 已实现 | `PreviewRequest.enable_external_resume`, `agent_summary`, `_validate_required_args`, `match_score` schema `target_role` | 与 AGENTS.md 锁点一致 |
| R5-B Phase 2A schema/context/effective tools | 已实现 | `backend/core/tool_schema.py`, `_check_permission_context`, `affects_preview`, `TestToolPermissionContext`, `TestWorkflowEffectiveTools` | 代码已经超过旧 R5-B spec 的 future 状态 |
| 前端 Agent 类型 / 高级面板 | 未实现 | `frontend/src/api/index.ts` 的 `PreviewResponse` 未含 `agent_summary/evidence_summary`;preview/generate 未传 Agent flags | 与旧 R5-B spec 的 Phase 4 未完成状态一致 |

---

## 3. 现状能力判断

### 3.1 已经可靠落地的能力

1. **受控 Agent workflow**
   `build_task_graph()` 根据 `has_jd`、`enable_function_calling`、`has_external_resume` 确定性产任务图,LLM 不参与规划,符合本地单用户工具的稳定性要求。

2. **工具契约与隐私边界**
   `ToolResult` 不存 args/input 原文;`execute_agent_tool()` 先做 allowlist、context 权限,再做 schema 校验,最后调用工具。权限失败返回 `PRIVACY_VIOLATION`,错误信息只含权限名/字段名/类型名。

3. **轻量 schema validator**
   `core/tool_schema.py` 已覆盖 object/string/integer/number/boolean/array、required、properties、items、minimum、maximum,且不引入第三方依赖。

4. **JSONL trace 与 replay**
   trace 固定 11 字段,只记录长度、工具、状态、错误分类;replay 只渲染 markdown 摘要,不输出原文。

5. **RAG evidence 作为唯一当前有效工具链输出**
   `retrieve_evidence` 的结果注入 `build_sections -> rewrite_highlights`,因此 `affects_preview=True`;`agent_summary.tools_used` 只列成功且真正影响 preview 的工具。

6. **测试锁定足够强**
   后端 487 个测试覆盖从 JD scoring、layout、LLM schema、session、trace、evidence、workflow 到 R5-B Phase 2A 的权限/schema/effective tools。

### 3.2 文档漂移

存在一处明显文档漂移:

- `.harness/docs/round5-b-agent-capability-spec.md` 仍写着“下一轮推荐从 Phase 2A 启动”和 `441 passed` 基线。
- `AGENTS.md`、`README.md` 和代码实际状态已经是 R5-B Phase 2A 完成,`487 passed`。

建议保留旧 R5-B spec 作为历史设计文档,新增下一轮 `round5-c-agent-capability-spec.md` 作为未来入口,避免继续改写已执行过的 spec。

---

## 4. 主要缺口

### Gap A: eval request_id 关联仍脆弱

`scripts/evaluate_agent_workflow.py` 当前会读取 JSONL trace 最后一条事件,取 request_id 前 4 字符,再从 JSONL 中反查工具调用。这与 R5-B spec 中“直接读取 `preview["agent_summary"]["request_id"]`”的方向不一致。

风险:

- 同一临时 trace 中连续多次 workflow 时,前缀匹配存在碰撞和误归因风险。
- `fallback_used` 当前主要由 exception 推断,不能区分 `llm_disabled_fallback`、`tool_error_fallback`、`schema_retry_fallback` 等类别。

### Gap B: 外部简历还没进入 Agent workflow

已有能力:

- `/api/resume/parse-external` 能解析 docx/pdf/txt。
- `/api/jd/match` 可传 `external_resume_text`,返回 `resume_perspective`。

未完成:

- `PreviewRequest` / `GenerateRequest` 只有 `enable_external_resume`,没有 `external_resume_text`。
- `build_task_graph(has_external_resume=True)` 只加 `parse_external_resume` 占位 step,`tool=None`。
- `AGENT_TOOLS` 还没有 `parse_external_resume` / `compare_resume_jd`。

### Gap C: 前端尚未消费 Agent 后端能力

`frontend/src/api/index.ts` 当前:

- `PreviewResponse` 未声明 `agent_summary` / `evidence_summary`。
- `resumeApi.preview()` / `resumeApi.generate()` 不支持 `enable_agent_workflow`、`enable_function_calling`、`session_id`、`external_resume_text`。
- `App.vue` 有外部简历上传和 JD match have/need 卡片,但没有 Agent workflow 开关、高级面板、request_id 复制、evidence summary 展示。

### Gap D: bullet 评估仍是 representative 单步

`evaluate_bullet_jd_match` 在 workflow 中仍用 `_pick_representative_bullet()` 选一条代表 bullet。它可证明工具调用路径存在,但还不能代表真实简历生成质量。

下一阶段应改成 top projects x top bullets 的确定性批量评估,输出压缩后的 `bullet_evaluations`,再决定是否影响 preview。

### Gap E: parse_jd / match_score 仍未成为真实数据流输入

当前 workflow 会调用 `parse_jd` 和 `match_score`,但主输出仍由 `build_sections()` 内部解析 JD 和排序。也就是说这些工具是可观测/展示型,不是 preview 的真实输入。

这不是当前实现 bug,因为 R5-B Phase 2A 已通过 `affects_preview=False` 把语义说清楚。但如果要让 Agent 能力更像“真实任务链”,下一阶段需要逐步把工具输出变成 aggregator 的输入,或者明确保留展示型定位。

---

## 5. 下一步建议

建议下一轮不要继续叫 R5-B Phase 2A。当前更合适的入口是:

1. **Round 5-C Phase 1: Eval request_id + fallback taxonomy**
   先修最小闭环,让评测能稳定指向一次 workflow。

2. **Round 5-C Phase 2: 外部简历进入 Agent workflow**
   复用 R3-G 解析和 have/need 语义,但进入 Agent 工具链和隐私测试。

3. **Round 5-C Phase 3: per-bullet 真实评估数据流**
   把 representative 单步升级为确定性批量评估。

4. **Round 5-C Phase 4: 前端高级 Agent 面板**
   默认收起,只展示摘要、request_id、工具状态、evidence 数量、外部简历 gap,不展示原文。

对应 future spec 已新增到:

```text
.harness/docs/round5-c-agent-capability-spec.md
```

---

## 6. 审计结论

项目当前架构不是“文档写了但没做”,而是“核心后端已经做到 R5-B Phase 2A,部分旧 future spec 没跟上”。

现在最值得投入的不是继续加工具外壳,而是把已有 Agent 后端能力变成三条闭环:

- eval 能精准回放并解释失败;
- 外部简历能作为 Agent 输入参与诊断;
- 前端能以安全摘要方式让用户看见 Agent 为什么这样改。
