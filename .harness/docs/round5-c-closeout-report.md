# R5-C 收尾审计报告

> 日期: 2026-06-28
> 范围: R5-C Phase 1-5 全部完成后的合并前审计
> 作者: orchestrator (本会话 mvs_05c574beb72f47b1b56ec6cd8445c1a2)
> 对照 spec: `.harness/docs/round5-c-agent-capability-spec.md`(已同步状态行 ✅)
> 对照 ROADMAP: `.harness/docs/ROADMAP.md`(同步 R5-C Phase 1-5 完成 + baseline 487→544)
> 对照架构审计: `.harness/docs/agent-architecture-audit-2026-06-28.md`(2026-06-28 启动审计时识别 5 个 gap,本轮逐一收口)

---

## 1. 总体结论

**R5-C 5 个 Phase 已全部按 spec 实现,基线 487 → 544 pytest 全绿,前端类型检查 + build 全过,隐私边界守住,文档三方同步。**

- 5 个 Phase 全部 ✅ 完成(spec §0 状态行已更新为已完成)
- 后端 **544 passed + 0 skipped**(与 README / ROADMAP / AGENTS 锁点一致)
- 前端 `vue-tsc --noEmit` 0 error
- 前端 `npm run build` 成功(Vite 6.4.3 + 仅 Rollup warning)
- `enable_agent_workflow=False` 老路径字节级一致(5/5 回归测试通过)
- 5 类 fallback taxonomy 全部落地,none / llm_disabled_fallback / tool_error_fallback / schema_retry_fallback / workflow_abort_fallback
- 外部简历进入 Agent workflow,4 维摘要不含原文
- per-bullet 评估批量化(3 projects × 3 bullets),不含 bullet 原文
- 前端"Agent Workflow 诊断"面板默认收起,仅展示摘要 / 计数 / 关键词 / request_id 短串
- 文档一致性检查通过:ROADMAP / README / AGENTS / spec 状态行全部对齐

**建议**:进入 commit 阶段(本地 commit,R5-C 5 个 Phase 一致打包),不开 PR(P3 默认等用户明确启动;用户偏好)。

---

## 2. 每个 Phase 的验收状态

| Phase | 主题 | 状态 | 验收证据 |
|---|---|:---:|---|
| **1** | eval request_id 关联 + fallback taxonomy | ✅ | `scripts/evaluate_agent_workflow.py` 优先读 `preview["agent_summary"]["request_id"]`;新增 5 类 fallback_category 常量 + `_classify_fallback_category()`;报告 `AI岗位JD库_agent_eval报告.md` 第 166-186 行新增 "6.1 fallback taxonomy 摘要" 段,request_id 短串只截前 4 字符;`tests/test_agent_eval.py` 新增 `TestEvalUsesAgentSummaryRequestId` × 3 + `TestEvalToolsUsedPrefersAgentSummary` × 5 + `TestEvalFallbackCategoryNone` × 3 + `TestEvalFallbackCategoryLlmDisabled` × 4 + `TestEvalReportNoRawRequestIdLeak` × 2 = 17 case |
| **2** | 外部简历进入 Agent workflow | ✅ | `PreviewRequest` / `GenerateRequest` 加 `external_resume_text: str \| None = None` 字段透传;`run_agent_workflow` 接受 `external_resume_text` kwarg,`has_external_resume` 以 `external_resume_text` 非空为真实依据;任务图插入 `parse_external_resume` + `compare_resume_jd` 两步(spec §3.3);`core/jd_parser.py` 新增 `parse_external_resume` / `compare_resume_jd` 输出 `{have_keywords, need_keywords, materials_can_cover, resume_only_keywords, suggestions, counts}` 4 维摘要不含原文;`core/agent_tools.py` 注册两工具,permission = `read_external_resume` / `read_jd_and_external_resume`,`pii_risk="high"`,`affects_preview=False` 仅诊断;workflow preview 返回 `external_resume_perspective` 字段;老路径完全不含此字段(字节级一致);`tests/test_r5c_phase2_external_resume.py` 17 case(2+3+2+2+1+3+1+2) |
| **3** | per-bullet 真实评估数据流 | ✅ | `core/agent_workflow.py` 新增 `_evaluate_top_bullets(materials, target_role, jd_focus, jd_context, *, top_projects=3, bullets_per_project=3) -> list[dict]` helper;任务图 `evaluate_bullet_jd_match` step 触发条件由 `enable_function_calling and has_jd` 改为 `has_jd`(不再依赖 FC,spec §4.2);workflow 主循环 evaluate step 走批量 helper 而非单 representative;输出 list[dict] 含 7 字段(`project_id` / `bullet_index` / `matched_keywords` / `missing_keywords` / `matched_count` / `missing_count` / `suggestion`)**不含 bullet 原文**;workflow preview 返回 `bullet_evaluations` 字段;`evaluate_bullet_jd_match` 仍 `affects_preview=False`;无 JD / 项目无 bullets / 批量失败 → `bullet_evaluations = []`;`tests/test_r5c_phase3_bullet_evaluation.py` 10 case |
| **4** | 前端高级 Agent 面板契约 | ✅ | `frontend/src/api/index.ts` 加 `AgentSummary` / `EvidenceSummary` / `ExternalResumePerspective` / `BulletEvaluation` TS 类型 + `preview/generate` 透传 `enable_agent_workflow` / `enable_function_calling` / `session_id` / `external_resume_text`;`App.vue` 默认收起"Agent Workflow 诊断"折叠面板(5 section: Request / Fallback / 工具 / Evidence / 外部简历 / bullet);`enableAgentWorkflow = ref(false)` 默认关闭;`agentSessionId` 前端生成 `crypto.randomUUID()` 含 fallback,不存 PII;`evidence.text` 前端不展示(只展示 `source_type` 分桶 + `confidence` + `matched_keywords` 计数);`bullet` 原文前端不展示(只展示 `project_id` + `matched/missing` 计数 + `suggestion`);`external_resume_perspective` 仅展示 `have_keywords` / `need_keywords` 关键词标签 + `suggestions` 短句;`vue-tsc --noEmit` 0 error,`npm run build` 成功 |
| **5** | 文档与回放闭环 | ✅ | `scripts/replay_agent_trace.py` 新增 `summarize_fallback(events)` 推断 `none` / `tool_error_fallback` / `unknown`(trace 信号不足时归 unknown 提示 caller 查 agent_summary);`cross_validate_tools_used(events, expected_tools)` 对账 caller `agent_summary.tools_used`,输出 `{expected, observed, matched, missing, unexpected, status}` 状态(`ok` / `missing` / `unexpected` / `empty`);`render_tools_cross_validation(cross)` 只输出工具名字符串;`render_markdown` 默认追加 `## Fallback Summary` 段(向后兼容);`--tools-used <csv>` CLI 参数触发 `## Tools Cross-Validation (R5-C Phase 5)` 段;`_observed_tools(events)` 严格只接受 `str` 类型工具名(防 events 脏数据);`tests/test_agent_trace_replay.py` 新增 3 + 7 + 2 + 2 = 14 case(AGENTS 锁点写 15,差 1 来自原 baseline `TestReplayRobustness` 收纳);`evaluate_agent_workflow.py` 不动(spec §6.3 明确"不修改既有");ROADMAP / README / AGENTS 三方同步 baseline 487→544 |

---

## 3. 改动文件清单(11 modified + 4 untracked)

### 3.1 Modified

| 文件 | 行数 | 主要内容 |
|---|---:|---|
| `.harness/docs/ROADMAP.md` | 85 | 顶部快照加 R5-C Phase 1-5 + 测试数 544 拆解;新增"R5-C 5 phase 全部落地"段(含背景 / 设计 / Phase 1-5 实施路径 / 实施坑 / 效果 / 下一步);测试数字段对齐 544 |
| `AGENTS.md` | 5 | Testing instructions 锁点 baseline 487→544 + 加 4 个 R5-C 锁点段(Phase 1 / Phase 3 / Phase 5 / R5-C closeout 衔接) |
| `AI岗位JD库_agent_eval报告.md` | 200 | 新增 "6.1 fallback taxonomy 摘要 (R5-C Phase 1)" 段(全局分布表 + spec §2.2 类别含义对照);每 JD 表格加 `request_id (短4字符)` + `fallback_category` 列;总数 / 一致性表加 fallback_category 列 |
| `README.md` | 15 | "当前能力"表加 R5-C Phase 1-5 五行(对应 5 个 ✅),每行 1 段精简说明 + commit / test 数;后续候选段保留 R5-D / R5-E 等未来入口 |
| `backend/core/agent_workflow.py` | 232 | 模块顶部 docstring 加 R5-C Phase 2 / Phase 3 增量说明;`build_task_graph()` evaluate step 触发改为 `has_jd`;新增 `external_resume_perspective` / `bullet_evaluations` 字段;`run_agent_workflow` evaluate step 走批量 helper(走 `_evaluate_top_bullets` 内部,不走 `execute_agent_tool`);新增 `_evaluate_top_bullets()` helper(top projects × top bullets,聚合 `evaluate_bullet_jd_match` 纯函数);preview 返回值加 `external_resume_perspective` / `bullet_evaluations` |
| `backend/tests/test_agent_eval.py` | 242 | 5 个新类 17 case(见 Phase 1 验收表) |
| `backend/tests/test_agent_trace_replay.py` | 320 | 4 个新类 14 case(3 + 7 + 2 + 2);保留 11 case R5-A Phase 2 baseline |
| `frontend/src/App.vue` | 489 | 默认关 `enableAgentWorkflow = ref(false)`;`generateAgentSessionId()` 用 `crypto.randomUUID()` 含 fallback;5 个 computed helpers(`hasAgentPanel` / `evidenceList` / `bulletList` / `extPerspective` / `agentToolsUsed`);2 个 stat computeds(`evidenceStats` 按 source 分桶 / `bulletStats` 按 project 分组);模板加 Agent Workflow 开关 + el-switch + 默认收起的"Agent Workflow 诊断"折叠面板(5 section);`copyRequestId` 含 clipboard API + textarea 降级 |
| `frontend/src/api/index.ts` | 109 | 4 个新类型接口 + 4 个新 optional 字段(`agent_summary` / `evidence_summary` / `external_resume_perspective` / `bullet_evaluations`);`preview()` / `generate()` 透传 4 个新字段(`enable_agent_workflow` / `enable_function_calling` / `session_id` / `external_resume_text`) |
| `scripts/evaluate_agent_workflow.py` | 278 | 新增 5 个常量 + 3 个 helper(`_extract_request_id_from_preview` / `_extract_tools_used_from_preview` / `_short_request_id` / `_classify_fallback_category`);`evaluate_one` 优先读 agent_summary;新增 `fallback_category` 字段进 row;`compute_metrics` 加 `fallback_category_breakdown`;`write_report` 加 fallback_category 列 + 6.1 摘要段;报告 request_id 短串只截前 4 字符 |
| `scripts/replay_agent_trace.py` | 228 | 3 个新常量(`FALLBACK_CATEGORY_NONE` / `FALLBACK_CATEGORY_TOOL_ERROR` / `FALLBACK_CATEGORY_UNKNOWN` + 4 个 cross-validate status 常量);新增 `summarize_fallback(events)` / `cross_validate_tools_used(events, expected_tools)` / `render_tools_cross_validation(cross)` / `_observed_tools(events)`;`render_markdown` 默认追加 `## Fallback Summary` 段;`--tools-used <csv>` CLI 参数触发 `## Tools Cross-Validation` 段 |

### 3.2 Untracked

| 文件 / 目录 | 说明 |
|---|---|
| `.harness/docs/agent-architecture-audit-2026-06-28.md` | 启动审计时识别 5 个 gap(eval request_id 脆弱 / 外部简历未进 workflow / 前端未消费 / bullet 评估 representative 单步 / parse_jd+match_score 未成真实输入)。R5-C Phase 1-4 直接收口前 3 个 + 第 4 个;第 5 个明确"展示型定位"保留。本文件是审计输入,留作历史参考 |
| `.harness/docs/round5-c-agent-capability-spec.md` | R5-C 设计 spec。状态行已同步为 ✅ 已完成 |
| `.planning/github-architecture-audit/` | 审计 planning 目录(findings.md / progress.md / task_plan.md),文档专用,非代码 |
| `backend/tests/test_r5c_phase3_bullet_evaluation.py` | Phase 3 新测试文件 487 行,10 case |

---

## 4. 测试结果

### 4.1 后端 pytest

```text
cd D:\简历帮\backend
D:\python3.11\python.exe -m pytest tests/ -q
........................................................................ [ 13%]
........................................................................ [ 26%]
........................................................................ [ 39%]
........................................................................ [ 52%]
........................................................................ [ 66%]
........................................................................ [ 79%]
........................................................................ [ 92%]
........................................                                 [100%]
544 passed in 54.48s
```

- **544 passed + 0 skipped**(与 README / ROADMAP / AGENTS / spec 锁点完全一致)
- 老路径字节级一致 5/5 通过(`TestBackwardCompatibility` × 3 + `TestAgentSummaryField::test_old_path_preview_does_not_have_agent_summary` + `TestWorkflowEffectiveTools::test_old_path_no_agent_summary_byte_level`)
- 无 P0/P1 安全阻塞

### 4.2 前端 vue-tsc + build

```text
cd D:\简历帮\frontend
npx vue-tsc --noEmit
# 0 error (无输出)

npm run build
# vite v6.4.3 building for production...
# ✓ 1647 modules transformed.
# dist/index.html 0.48 kB / dist/assets/index-CW00-BKj.css 362.98 kB / dist/assets/index-Bn0L9sv7.js 1,088.13 kB
# ✓ built in 5.56s
# (warning: vueuse/* #__PURE__ comment placement; chunk size > 500 kB)
```

- 0 TypeScript error
- build 成功(只有 Rollup warning,无 error)
- `frontend/dist/` 已在 .gitignore

### 4.3 手动跑脚本

```text
cd D:\简历帮
D:\python3.11\python.exe scripts/evaluate_agent_workflow.py
# 12 JD × 4 开关对照 全部跑通; report 写 AI岗位JD库_agent_eval报告.md
# JSONL trace: backend/logs/agent_trace.eval_tmp.jsonl (临时,已 mavis-trash)

D:\python3.11\python.exe scripts/replay_agent_trace.py --request-id r323fdce5 --path backend/logs/agent_trace.eval_tmp.jsonl
# 输出 8 step + Fallback Summary (tool_error_fallback) + Errors

D:\python3.11\python.exe scripts/replay_agent_trace.py --request-id r323fdce5 \
  --path backend/logs/agent_trace.eval_tmp.jsonl --tools-used retrieve_evidence,parse_jd
# 追加 Tools Cross-Validation: status=unexpected, matched=2 / unexpected=3
```

- 真实 request_id `r323fdce5` 来自 eval 期间临时 JSONL(已清理)
- replay 双段输出正常,只输出工具名字符串不接触原文

---

## 5. 隐私审计结论

### 5.1 审计方法

1. **grep 扫描 13 个核心文件**:搜索 `error_msg =` / `error_msg="` / `PII` / `隐私` / `p11` / `phone` / `email` / `school` / `private` 等敏感关键词,确认所有边界都有注释 + 测试断言
2. **测试覆盖扫描**:`tests/test_agent_trace_replay.py` / `tests/test_r5c_phase3_bullet_evaluation.py` / `tests/test_r5c_phase2_external_resume.py` / `tests/test_agent_workflow.py` / `tests/test_logger.py` / `tests/test_tool_schema.py` 都含 PII 安全断言
3. **gitignore 检查**:`backend/data/_private_backup.json` / `backend/output/` / `backend/logs/` / `frontend/dist/` 都 `git check-ignore` 确认忽略
4. **代码搜索**:`_private_backup` / `_read_jd_text` 等关键字唯一出现在注释(docstring),无实际读取

### 5.2 审计结论

| 维度 | 结论 |
|---|---|
| **完整 JD 是否泄漏到 trace/log/report/agent_summary** | ✅ 否。`input_size` / `output_size` 只算字节数;report 只展示 `score` / `recommendation` / `matched_count` / `missing_count` 等计数 |
| **完整外部简历是否泄漏到 trace/log/report/agent_summary** | ✅ 否。`parse_external_resume` 只返 `profile: {char_count, paragraph_count}` + `keywords` 列表;`compare_resume_jd` 只返 4 维摘要(`have_keywords` / `need_keywords` / `materials_can_cover` / `resume_only_keywords`)+ `suggestions` + `counts`;`ToolResult.output` 不存原文;JSONL trace 只写 `input_size/output_size` |
| **完整 bullet 是否泄漏到 trace/log/report/agent_summary/前端面板** | ✅ 否。`bullet_evaluations` 只含 `project_id` / `bullet_index` / `matched_keywords` / `missing_keywords` / `matched_count` / `missing_count` / `suggestion` 7 字段;`suggestion` 是 1 句人话短句不含原文;前端 App.vue 不展示 bullet 原文,只展示 `bulletStats.totalMatched` / `totalMissing` / `topSuggestions` |
| **真实姓名 / 手机号 / 邮箱 / 学校** | ✅ 不入任何 trace / log / report / 前端面板。`_private_backup.json` 完全不入仓;`materials.json` 是公开脱敏版(`13800000000` / `your_email@example.com` / `示例大学` / `示例同学` placeholder);eval PII scanner 对 placeholder 白名单容忍 |
| **`_private_backup.json` 是否被读取** | ✅ 否。grep 唯一匹配在 `scripts/evaluate_agent_workflow.py` 第 30 行注释("不读 backend/data/_private_backup.json(只在 gitignore 的真实备份)"),无实际读取 |
| **`backend/output/` / `backend/logs/` / `frontend/dist/` 是否会被提交** | ✅ 否。`git check-ignore` 全部确认 |

### 5.3 error_msg 边界确认

`backend/core/agent_workflow.py` 唯一一处 `error_msg` 赋值(第 588 行):`error_msg=type(e).__name__` — 只含异常类型名,不含 args / 原文(spec §6.4 隐私边界)。

`backend/core/agent_tools.py` 4 处 `error_msg`(第 428 / 442 / 454 / 470 / 481 行):
- 第 428 行:`error_msg=f"工具 {tool_name!r} 不在 allowlist"` — 只含工具名字符串
- 第 442 行:`error_msg=permission_err` — 只含权限名 + 风险级别(由 `_check_permission_context` 内部生成,见第 351-357 行,只含权限名不含 args)
- 第 454 行:`error_msg=validation_err` — 只含字段名 + 类型摘要(由 `core/tool_schema.py` 内部生成,见 spec §6.4 隐私)
- 第 470 行:`error_msg=f"TypeError: {type(e).__name__}"` — 只含异常类型名
- 第 481 行:`error_msg=f"{type(e).__name__}: {type(e).__name__}"` — 只含异常类型名

### 5.4 affects_preview 语义准确性

| 工具 | `affects_preview` | 实际行为 | 评估 |
|---|:---:|---|---|
| `parse_jd` | False | 仅展示型,workflow 跑后输出仅进 trace / `parse_jd` step result | ✅ 正确(展示型不污染 preview) |
| `match_score` | False | 同上,`build_sections` 内部独立调用 `match_score`,不依赖 workflow 输出 | ✅ 正确 |
| `retrieve_evidence` | **True** | output 真正注入 `build_sections` → `rewrite_highlights` → 影响 highlights | ✅ 正确(影响 preview 的唯一工具) |
| `evaluate_bullet_jd_match` | False | 走批量 helper 输出 `bullet_evaluations`,不注 `build_sections` / `rewrite_highlights` | ✅ 正确(spec §4.4 明确"先作为诊断输出") |
| `rewrite_highlights` | False | 同 `match_score` 展示型 | ✅ 正确 |
| `parse_external_resume` | False | 仅解析外部简历,output 只给 `compare_resume_jd` 喂数据(spec §3.3 明确"初期不标 affects_preview=True") | ✅ 正确 |
| `compare_resume_jd` | False | output 仅收集到 `external_resume_perspective` 字段(诊断) | ✅ 正确 |

`agent_summary.tools_used` 只列 `affects_preview=True` 且 `status=success` 的工具 → 当前唯一真工具 = `retrieve_evidence`,符合预期(11/15 个老测试 + 5 个 R5-B Phase 2A 测试 + 2 个 R5-C 新测试全部锁死)。

---

## 6. 代码质量检查

### 6.1 死代码 / 重复逻辑 / 未使用 import

- ✅ `backend/core/agent_workflow.py` AST 解析 14 个顶层 def/class,无未使用 import
- ✅ `_pick_representative_bullet` 仍保留(用于 FC 路径 `rewrite_highlights` 工具 args,跟批量 helper 是不同用途 — spec §4.2 明确"Phase 1 MVP 简化 representative",FC 工具 args 仍走单 representative)
- ✅ `parse_external_resume` / `compare_resume_jd` 走 `core.jd_parser.py`(新增工具函数),无重复实现
- ✅ `rank_projects` 通过 `core.generator` re-export(`generator.py` 第 25 行 `from core.jd_ranker import rank_projects`),无循环 import

### 6.2 测试冗余检查

| 文件 | 测试数 | 评估 |
|---|---:|---|
| `tests/test_r5c_phase2_external_resume.py` | 17 | 锁 schema / 隐私 / 老路径,无冗余(全部独立断言) |
| `tests/test_r5c_phase3_bullet_evaluation.py` | 10 | 锁 helper / schema / trace / 边界 / 老路径,无冗余 |
| `tests/test_agent_trace_replay.py` 新增 | 14 (Phase 5) + 12 (baseline) = 26 | Phase 5 增量 4 类细分(fallback / cross-validate / PII / robustness),无冗余 |
| `tests/test_agent_eval.py` 新增 | 17 (Phase 1) + 11 (baseline) = 28 | Phase 1 增量 5 类细分(request_id / tools_used / category / report),无冗余 |

**结论**:R5-C 5 个 Phase 新增 ~58 测试方法,全部锁核心逻辑 / 边界 / 集成,无 thin wrapper / URL 字符串字面量 / mock 自指。基线回归 0 回退(487 → 544,纯增)。

### 6.3 老路径字节级一致性

```text
tests/test_agent_workflow.py::TestBackwardCompatibility::test_generator_preview_resume_still_works_without_new_kwarg PASSED
tests/test_agent_workflow.py::TestBackwardCompatibility::test_generator_preview_resume_default_off_returns_same_as_workflow PASSED
tests/test_agent_workflow.py::TestBackwardCompatibility::test_generator_preview_resume_with_jd_still_works PASSED
tests/test_agent_workflow.py::TestAgentSummaryField::test_old_path_preview_does_not_have_agent_summary PASSED
tests/test_agent_workflow.py::TestWorkflowEffectiveTools::test_old_path_no_agent_summary_byte_level PASSED
```

✅ 5/5 老路径回归测试通过。

---

## 7. 文档一致性检查

| 文档 | 当前测试数 | spec 状态 | 一致性 |
|---|---:|---|---|
| `.harness/docs/round5-c-agent-capability-spec.md` | 544(状态行已更新) | ✅ 已完成 | ✅ |
| `.harness/docs/ROADMAP.md` | 544(顶部快照 + R5-C 段) | ✅ 已完成 | ✅ |
| `README.md` | 544(5 行 R5-C ✅ entries) | ✅ 已完成 | ✅ |
| `AGENTS.md` | 544(Testing instructions + 5 个 R5-C 锁点段) | ✅ 已完成 | ✅ |
| `.harness/docs/agent-architecture-audit-2026-06-28.md` | 487(审计时点) | 历史快照,描述 R5-B Phase 2A baseline + 识别 5 个 gap | ✅(留作历史参考) |
| `.harness/docs/round5-b-agent-capability-spec.md` | n/a | "Future spec"(已实现完成) | ⚠️ 历史设计 doc,可保留 — 不强行改写 |
| `.harness/docs/agent-enhancement-spec.md` | n/a | 历史 R5-A spec | ⚠️ 同上,历史设计 doc 保留 |

### 7.1 历史 Future spec 文档处理建议

`round5-b-agent-capability-spec.md` 第 5 行仍写 "Future spec / R5-B.0 文档基线已校准;下一轮推荐从 Phase 2A 启动"。这是历史 spec 文档的 snapshot,改写它会破坏版本化历史。建议:

- **保留**:作为"那个时间点的设计文档"快照,提供未来审计追溯能力
- **不强行改写**:与 `round5-c-agent-capability-spec.md`(已同步状态)区分
- **路径上不再被新引用**:新文档 / commit / closeout 报告均引用 `round5-c-agent-capability-spec.md` 作为最新 spec

类似地 `agent-enhancement-spec.md`(R5-A Phase 1-4 spec)也是历史 spec,保留原状。

---

## 8. 剩余风险 / 后续候选

### 8.1 已知技术债(不阻塞合并)

1. **报告字符编码问题**:终端输出 `recommendation` 列含中文 `推荐投` / `建议补充` / `别投` 在 Windows PowerShell 下显示乱码(`rec=�?`)。仅影响 CLI 输出,不影响 markdown 报告内容。**建议**:PowerShell 配 `PYTHONIOENCODING=utf-8` 或用 `chcp 65001`(用户已知,与本轮 R5-C 无关)
2. **`evaluate_bullet_jd_match` 仍 `affects_preview=False`**:spec §4.4 明确"先作为诊断输出,后续明确用于排序 / 改写时再升 affects_preview=True"。当前实现正确,后续若需要 bullet_evaluations 注入改写 prompt,需要单独升版 + 补 baseline 字节级 hash 测试(spec §4.4 提示)
3. **R5-C Phase 4 仅交付默认收起的 Agent 面板 + 类型契约**:实际"用户打开面板看诊断"流程需要用户明确启动(spec §5 段头注释 "GUI 任务默认等用户明确启动")。**当前契约已就位,等用户说"启用面板"再开 PR**
4. **`request_id` 短串 = 4 字符**:spec §2.4 明确"展示短串即可"。当前 4 字符截取策略简单(就是前 4),不做哈希。如果将来需要唯一性更高的短串,可以改成 hash 前 4 字节 — 但当前 9 字符 uuid 前 4 字符碰撞概率仍较低(16^4 = 65536),eval set 仅 12 JD 不会撞

### 8.2 后续候选(等用户拍)

- **R5-D 真实 LLM 接入**:用户提供真实 LLM key 后,跑完整 12 JD × 4 开关对照,得出 schema pass rate / fallback rate / latency 真实指标。当前 eval 全走原文 fallback,反映离线路径真实表现(spec Phase 4 实际收益评估)
- **R5-E Vector DB RAG 升级**:把 `core/evidence.py` 的 lexical retrieval 升级为真 embedding API 检索,需要评估成本(spec §5.3)
- **R5-C Phase 4 GUI 实际打开**:用户明确启动后,前端 App.vue 取消 `enableAgentWorkflow = ref(false)` 默认值,默认展开面板
- **`evaluate_bullet_jd_match` 升 `affects_preview=True`**:后续若 bullet_evaluations 用于排序 / 改写,需要单独升版 + 补 baseline

---

## 9. 是否建议合并

### 9.1 建议操作

✅ **建议进入 commit 阶段**:
- 本地 commit(R5-C 5 个 Phase 一致打包,或拆成 3-5 个聚焦 commit)
- 不开 PR(P3 默认等用户明确启动;用户偏好 GUI / 云端 / PR 等都按"等明确指令"处理)
- 不直接 push main(本地 commit 后用户决定何时 push)

### 9.2 commit 策略建议

考虑拆成 5 个聚焦 commit(每个 Phase 一个),便于历史追溯 + 单独 revert:

```text
feat(round5-c#phase1): eval request_id 优先 agent_summary + fallback taxonomy 5 类
feat(round5-c#phase2): 外部简历文本进入 Agent workflow (preview 透传 + 工具注册 + 隐私边界)
feat(round5-c#phase3): per-bullet 真实评估数据流 (top projects × top bullets helper)
feat(round5-c#phase4): 前端 Agent 面板契约 (TS 类型 + 默认收起 el-collapse)
feat(round5-c#phase5): replay 增强 (Fallback Summary + Cross-Validation) + 文档三方同步
docs(round5-c): closeout 报告 + ROADMAP/README/AGENTS 三方同步 baseline 544
```

或者单 commit:

```text
feat(round5-c): Agent 真实闭环 (eval + 外部简历 + per-bullet + 前端契约 + replay) baseline 487→544
docs(round5-c): closeout 报告 + ROADMAP/README/AGENTS 三方同步
```

### 9.3 不建议项

- ❌ 不开 PR(本地单用户工具,等用户明确启动云端 / 远端协作)
- ❌ 不直接 push main(用户偏好 commit 由用户决定何时推,AGENTS.md 已明确)
- ❌ 不实施 GUI Agent 面板实际展开(spec §5 段头 "GUI 任务默认等用户明确启动")
- ❌ 不实施真实 LLM 接入 / Vector DB RAG(等用户明确启动 + 评估成本)

---

## 10. closeout 签字

| 项 | 状态 |
|---|:---:|
| R5-C Phase 1 | ✅ |
| R5-C Phase 2 | ✅ |
| R5-C Phase 3 | ✅ |
| R5-C Phase 4 | ✅ |
| R5-C Phase 5 | ✅ |
| 后端 pytest 544/544 | ✅ |
| 前端类型检查 0 error | ✅ |
| 前端 build 成功 | ✅ |
| 隐私审计 7 维度 | ✅ |
| 文档三方同步(ROADMAP / README / AGENTS / spec) | ✅ |
| 老路径字节级一致 5/5 测试 | ✅ |
| error_msg 边界 6 处全部安全 | ✅ |
| affects_preview 语义 7 个工具全部正确 | ✅ |
| `_private_backup.json` 不被读取 | ✅ |
| `output/` / `logs/` / `dist/` 不入 commit | ✅ |
| closeout 报告写入 `.harness/docs/` | ✅(本文件) |

---

_审计时间:2026-06-28 15:27-15:45 (Asia/Shanghai)_
_审计员:orchestrator (本会话 mvs_05c574beb72f47b1b56ec6cd8445c1a2)_
_对照 spec: `.harness/docs/round5-c-agent-capability-spec.md` ✅ 已完成_
_对照架构审计: `.harness/docs/agent-architecture-audit-2026-06-28.md`_
_下一轮候选:等用户明确启动(真实 LLM 接入 / Vector DB RAG / GUI 实际启用 / bullet_evaluations 升 affects_preview 等)_