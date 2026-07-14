# 简历帮 — 未来规划 ROADMAP

> **可持续更新的项目规划文档**。每个 round 收尾时由 orchestrator 更新:已完成 → 移到顶部"快照";新启动 → 加进对应优先级段。
>
> **历史档案** 见 `.harness/memory/MEMORY.md`(项目里程碑 / 改动记录 / 已知陷阱)。
> **设计文档** 见 `.harness/docs/`(每 round 一份 `roundN-*.md`)。
> **本文件** 只描述未来:目标 + 触发条件 + 工作量估算,具体实施 spec 落 `.harness/docs/roundN-*.md`。

---

## 0. 当前项目快照(2026-07-07 **R6-H 完成**:5 docs/sec commit 全推 `origin/main` (HEAD = `0556c91`);docs-only 整理 + system-architecture.md 新增(332 行)+ `.codebuddy/` + `架构设计文档.md` ignore/trash + README 同步状态字面 + **依赖安全升级 starlette 0.50.0 → 1.3.1 + python-multipart 0.0.20 → 0.0.32**(CVE-2026-48710 starlette BadHost + 6 个 python-multipart DoS);**948 baseline 零回退**(pytest 16.34s);本地 main 与 origin/main 已同步(0 ahead / 0 behind);**R6-H live eval v2 决策门禁 spec** `.harness/docs/round6-h-live-eval-v2-decision-gate-spec.md` §10 路径 A 拍板为后续 round 实施方向,等用户在前端跑完 10+ 轮真实对话后启动 Phase 2 跑分;**新增** `.harness/docs/system-architecture.md` 系统架构总览(前端 / 后端 / 数据 / agent / 脚本 5 维度);**R6-G 完成**:`review-needed` 3 项整理 — verifier sentinel 失败提示 + llm envelope 重复 except hygiene 清理 + stderr 错误信息脱 `LLM_API_KEY` / `sk-` / `Bearer`(commit `ae0e89b`);+12 pytest,936 → 948 baseline;**R6-F closeout 完成**:文档 / baseline 漂移 + UI chip 噪音 + 临时文件清理 + R6-E Phase 4 slot 对齐 fix 已 closeout(commit `a3f48b1`),见 `.harness/docs/round6-f-project-review-bug-audit-report.md`;**R6-E closeout 完成**:本地 main 与 origin/main 已同步至 `3b632c7`(0 ahead / 0 behind);R6-E Phase 4 `_do_answer` slot 对齐 bug fix(commit `7fe798c`)+ docs-only patch 落地,936 baseline 实测 65.60s;R6-C.1+ C.2A+ C.2B+ C.3 全部完成 + R6-D 机械拆分行为不变重构 全部完成;R6-B Phase 0+1+2+3+4+5+6 可信增强层 全部完成;R6-A Phase 1+2+3+4+5 全部完成,LLM slot extraction 已上线;R5-E Prompt 版本化 + A/B Eval 闭环 + 文档收尾 全部完成,**不 rollout winner**)

**已上线能力**(用户视角):
- FastAPI 后端 + Vue 3 前端 + 本地单用户工具
- 6 个 role:tech_metric / product / algorithm / data_annot / test_qa / general
- **8 套简历模板**:classic / single_column / two_column / minimal / technical / academic / internet / bilingual
  - **academic** 学术 CV(R3-M.1 11pt/1.5/2.5cm + R3-M.2 专属 renderer 简化 highlights + R3-M.3 academic_layout compact/detailed 二级选项)
  - **internet** 互联网简洁(10pt/1.2/1.5cm / ▸ 前缀,字节阿里 style)
  - **bilingual** 中英双语(R3-M.3 激活 bilingual_mode,header / 教育 / 项目副标题 3 个 section helper,`_en` 字段缺失时 graceful 降级)
- JD 加权 score + tier 分组 + 业务阈值 banner(高≥80 / 中 60-79 / 低<60,**R3.5 调优锁死**)
- **borrowed pool + 'AI' surface + PM 维度 surface**(R3.5+ / R3.5+ (b) 修复 false negative + 让 match_score 精确告诉 user 缺什么)
- **R3.5.1 score_thresholds 实跑模式**(`scripts/score_thresholds.py` 不再读 frozen top_score, 实时跑 match_score 出报告, 反映当前实现 + 真实素材库)
- **R3.6 扩库 + 质量清理: 88 份 JD**(v3 86 → R3.6 +10 → R3.6.1 清理 -8 = 88, **A 级 86 / B 级 2**, 无 placeholder 无 C 级, 4 级标签 strong=53 / campus_to_intern=7 / weak=20 / none=8)
- **R3.6.2 baiyun_product label 复核完成**(第三次复核改 '别投', un-skip → **8/8 = 100% 准确率, 0 skipped**)
- **R3-G 外部简历上传 + 简历视角评分**(`POST /api/resume/parse-external` 解析 .docx/.pdf/.txt → `match_score` 增加 `external_resume_text` 参数 → 返回 `resume_perspective` 块 {have_keywords, need_keywords, have_count, need_count} → 前端 `ResumeUploader` drag 组件 + App.vue 评分结果区加 "已有/还缺" 卡片, 扣除素材库能补的避免 false negative)
- JD-driven generation:粘贴 JD 后项目/highlight/skill 按命中数倒序 + 段落命中关键词角标
- **R3-P LLM Prompt 工程升级**(`SYSTEM_PROMPT` v2 加 2 个 few-shot 示例 + 显式 JSON schema + 失败 retry 1 次;LLM 智能改写无 key 静默降级)
- **R4 Agent MVP** — Function Calling 协议接入(R4-F tools schema + evaluate_bullet_jd_match 工具函数)+ Agent Loop(R4-A max_step=3 + 单工具约束 + trace 日志)+ Session 记忆(R4-M 进程内 deque 上限 10 + 隐私隔离不写内容只写 id+步数);**MVP 优先打 AI Agent R&D JD 缺口**;R4-C Chat UI 留 P2(用户偏好 GUI 暂停)
- **R5-A Agent 增强 4 phase + closeout** + **R5-B Phase 2A 工具契约/权限/effective tools** + **R5-C Phase 1-5 真实闭环**:
  - **R5-A Phase 1-4 + closeout** — Agent 编排层(`build_task_graph()` 确定性产任务图)+ 工具注册表(AGENT_TOOLS 4 个核心 + 统一入口 + 隐私边界)+ JSONL trace(11 字段稳定 schema + request_id 短 uuid)+ 会话回放脚本 + 轻量 RAG evidence(`core/evidence.py` 切片 + lexical retrieval + 零向量数据库)+ 离线评测报告(12 JD × 4 开关对照);PR #4 合并到 `main`(merge `12dfcf1`)
  - **R5-B Phase 2A** — 工具契约/权限/effective tools(`core/tool_schema.py` 轻量 JSON schema validator 子集 + `_check_permission_context(spec, context)` 校验 allow_jd_text/allow_materials/allow_external_resume/max_pii_risk + `affects_preview=True` 元数据 + `agent_summary.tools_used` 只列成功且真正影响 preview 的工具);PR #6 合并到 `main`(merge `09a2704`)
  - **R5-C Phase 1** — eval request_id 优先从 `agent_summary.request_id` 取(替代脆弱的 JSONL 末尾反推)+ fallback taxonomy 分类(`none` / `llm_disabled_fallback` / `tool_error_fallback` / `schema_retry_fallback` / `workflow_abort_fallback`)
  - **R5-C Phase 2** — 外部简历进入 Agent workflow(`PreviewRequest.external_resume_text` 字段透传 + 任务图插入 `parse_external_resume` + `compare_resume_jd` 两步 + `core/jd_parser.py` 两个新工具函数输出 `{have, need, materials_can_cover, resume_only_keywords, suggestions, counts}` 4 维摘要,不含原文);workflow preview 返回值新增 `external_resume_perspective` 字段
  - **R5-C Phase 3** — per-bullet 真实评估数据流(`_evaluate_top_bullets(materials, target_role, jd_focus, jd_context, *, top_projects=3, bullets_per_project=3)` helper + workflow 主循环 evaluate step 走批量而非单条 representative + workflow preview 返回 `bullet_evaluations` 字段不含 bullet 原文)
  - **R5-C Phase 4** — 前端高级 Agent 面板契约(`AgentSummary` / `EvidenceSummary` / `ExternalResumePerspective` / `BulletEvaluation` 类型 + `preview/generate` 透传 enable_agent_workflow / session_id / external_resume_text);前端 App.vue 默认收起诊断面板
  - **R5-C Phase 5** — 文档与回放闭环(`scripts/replay_agent_trace.py` 加 `## Fallback Summary` 段 + `--tools-used` 参数触发 `## Tools Cross-Validation (R5-C Phase 5)` 段 + 5 个常量分类 `none` / `tool_error_fallback` / `unknown`;ROADMAP / README / AGENTS 三方同步 baseline 530→544 测试数)
  - **R5-D Phase 0-5 真实 LLM eval 闭环**(`scripts/evaluate_agent_workflow.py` 加 `--mode` {offline, live, auto} 默认 offline + `--output` 自定义报告路径;`_get_llm_eval_config()` helper 抽 LLM 元信息,只输出 host 不含 path/query/secret;`_extract_project_highlights` + `_summarize_rewrite_impact` 5 数字字段不含 bullet 原文;`_percentile` 纯函数 + `p95/max latency` + 5 类 fallback_category_breakdown;live 模式只做手动验收不进 pre-push);ROADMAP / README / AGENTS 三方同步 baseline 547→596 测试数;6 个 commit 顺序落地:`8a4a799` spec / `522d911` baseline / `89717a9` mode / `1fef8dc` llm metadata / `8838e7a` rewrite impact / `2052b1f` latency & fallback;Phase 5 文档收尾落在 `docs(round5-d): document live eval workflow`,spec 状态从"📝 待实施 spec"改为"✅ 完成"
  - **R6-A Phase 1+2+3+4+5 全部完成** — `R6-A Phase 1+2 JD-driven interview agent + save-card 写库闭环`(`backend/core/interview_agent.py` 状态机 + 4 固定 gap 规则打分 `_score_gap()` + 槽位抽取纯规则 + draft_card + save_card 原子写闭环 `tmp + os.replace`;`backend/core/interview_prompts.py` 问题模板/快捷回复/收束组合;`backend/api/interview.py` start/reply/draft/save-card 4 个端点,SaveRequest/SaveResponse model,400/422/404 错误码翻译;`backend/main.py` 1 line 注册 `interview_router`;新 project schema `{category: "interview_captured", highlights: {role_key: [...], general: [...]}(双写入), tags: ["interview_agent"], _interview_meta: {source_gap_id, source_session_id, created_at, warnings}}`);核心边界:`core/interview_agent.py` 不 import `core.llm_rewriter` / `core.agent_workflow` / `core.agent_tools` / `core.evidence` / `core.tool_schema` / `core.session`(R5-E 字节级稳定);`_INTERVIEW_SESSIONS` 进程内独立 dict;trace `workflow="interview"` + 数字 step + tool enum `gap_select` / `slot_extract` / `draft_card` / `save_card`;save-card 不 import `api.materials._load/_save` + 原子写 + 测试/冒烟必传临时 `materials_path`(`monkeypatch DEFAULT_MATERIALS_PATH` 指向 tmp_path),生产默认 `backend/data/materials.json` 不入库修改;**Phase 3 前端 chat panel**(`frontend/src/components/InterviewAgentPanel.vue` 主聊天栏 + `InterviewDraftCard.vue` 素材卡编辑 + `InterviewProgressPills.vue` 进度条;`App.vue` 加 `.app-shell` flex 布局 + 380px sticky sidecar 桌面 + 右下 FAB + `el-drawer` 全屏聊天移动端 ≤768px;`api/index.ts` 加 5 个 `InterviewXxx` 类型 + 4 个 API 函数;桌面 1280x800 + 移动 375x812 UX smoke 截图存 `.planning/round6-a-ux/`);**Phase 5 eval 脚手架 → R6-B Phase 5 升级**(原本 7 章节 rules-only,升级后 `--extractor {rules,llm,compare}` 三模式 + offline compare 双组同跑 + fallback_category 5 类分类 + Rules vs LLM-assisted 对照表 8 指标 + Delta 块;offline 仍不调 urlopen,live mode 脚本内 `return 2` 拒绝);**Phase 4 LLM slot extraction 已上线**(`extract_slots(..., llm_enabled=False)` keyword-only 入参;LLM 路径走 stdlib `urllib` POST `/chat/completions`(跟 R5-E Phase 3 `_call_judge` 同源);fallback 规则版 — 网络错不 retry / JSON 失败 retry 1 次 / schema 失败 fallback;prompt 独立放 `core.interview_prompts.SLOT_EXTRACTION_SYSTEM_PROMPT` / `SLOT_EXTRACTION_USER_TEMPLATE`,**不**进 `PROMPT_VERSIONS`,user template **不**含 `{jd_text}` 隐私边界);**不挂 pre-push** / 不引入新 LLM 调用(Phase 5 仅 offline) / 不引入新依赖 / 不修改既有 3 个 eval 脚本 / 不修改 R5-E 不触碰清单
- **R6-C.1 全部完成** — eval contract warnings + live compare wording fix(commit `ea43473`, 2026-07-01):`scripts/evaluate_interview_agent.py` 新增 `_validate_eval_contract(sample)` 纯函数校验 expected_slots 在 `GAP_SUGGESTED_SLOTS` 内 + `MAX_TURNS_PER_GAP=3` 范围内可达;2 个新 warning code 常量 `EVAL_CONTRACT_WARN_UNREACHABLE` / `EVAL_CONTRACT_WARN_BEYOND_3`;`write_report` 新增 `## 4.5 Eval contract warnings` 章节按 sample 去重只列 sample/gap/slot/code 4 字段;live compare 表头按 requested_mode 动态化(live → "真实 LLM 抽取", offline → "强制规则 fallback");§二 fallback_rate 口径声明明确为 workflow / session 级不是 slot 级 LLM 成功率;**14 个新 pytest** = `TestPhaseC1EvalContractValidation` 7 + `TestPhaseC1ReportContractSection` 2 + `TestPhaseC1ReportWording` 3 + `TestPhaseC1ReportPrivacy` 2;baseline 863 → **877 全绿**;**不挂 pre-push / 不修改 core/**
- **R6-C.2A 全部完成** — fix eval set contract(commit `a1a9fc2`, 2026-07-01):10 条 eval sample 各加 `product_goal` (枚举 `three_turn_friendly` / `full_fact_coverage`) + `contract_note` 2 个字段;`communication_club` 调整 `expected_slots` 移除 responsibility 改为 `(action, method, result)` 表达 3 轮内可生成素材目标;7 条 simulated samples 保留 expected 不删,在 `contract_note` 标记 "需后续 policy 调整";`write_report` 新增 `## 4.6 Eval contract: product goal` 章节;§八 结论追加 "schema_pass_rate 数值变化 = 评测合同变化" 口径声明;**验收口径**:`schema_pass_rate` 数值变化必须解读为评测合同变化,**不**解读为 LLM 抽取能力提升或下降;**禁止**把 expected 改成 captured slot keys (测试 `test_communication_club_removed_responsibility_slot` 锁死);**`product_goal` 分工** = plan_baseline (3 条) `three_turn_friendly` 调整后 0 warning + simulated_user_v1 (7 条) `full_fact_coverage` 保留 expected + 6 条 unique warning 跨 4 条 sample;**12 个新 pytest** = `TestPhaseC2EvalContract` 12 case;baseline 877 → **889 全绿**;**不挂 pre-push / 不修改 core/ / frontend**
- **R6-C.2B 全部完成** — policy gap-specific critical slot 补足(commit `caab6ff` + merge `651ea4e`, 2026-07-01):只改 `backend/core/interview_policy.py` + `backend/tests/test_interview_policy.py` + `backend/tests/test_interview_agent.py` 3 文件;`INTERVIEW_POLICY_GAP_CRITICAL_SLOTS` 新常量 2 entries(`tech_metric: ("metric", "method")` + `communication: ("responsibility",)`)放 policy 内部不污染 `GAP_SUGGESTED_SLOTS`(LLM 抽取端引导顺序);`_find_missing_critical_slots(session)` 纯 dict lookup;`plan_next_question` 新增 **step 4.5 (gap_critical_slot_priority)** 优先级位置在 step 4 (low_confidence) 之后 step 5 (near_limit) 之前;触发条件 = 当前 gap 在 CRITICAL 配置 + 有未 captured 的 critical slot;**R6-C.1 contract warning 6 条对应修复** — `sim_tech_metric_medical_eval` metric / `sim_tech_metric_ecg` metric+method / `sim_tech_metric_rubric_design` metric+method / `sim_communication_volunteer` responsibility 现能通过 step 4.5 三轮内被问到;**20 个新 pytest** = `tests/test_interview_policy.py::TestPhaseC2BCriticalSlot` 16 + `tests/test_interview_agent.py::TestPhaseC2BCriticalSlotIntegration` 4;baseline 889 → **909 全绿**;**实测** = `pytest tests/test_interview_policy.py tests/test_interview_agent.py -q` 115 passed / `pytest tests/ -q` 909 passed in 61.37s;**不期望 schema_pass_rate 提升**(eval 走 `_extract_slots_iteratively` 路径不走 policy,改动只影响 `next_question` 路径即前端 chat panel UI);**不挂 pre-push / 不引入新依赖 / 不修改 `core/interview_agent.py` / `core/interview_prompts.py` / 任何 scripts/ / frontend / eval set**
- **R6-C.3 全部完成** — LLM 抽取可观测性 + prompt few-shot 优化(commit `84dd086`, 2026-07-02):4 个目标一次性交付不拆模块 — (1) `_call_llm_for_slot_extraction` request body 加 `response_format={"type": "json_object"}`(OpenAI-compatible 强约束 JSON 输出,温度仍 0.0 字节级一致);(2) `SLOT_EXTRACTION_SYSTEM_PROMPT` 加 2 个短 few-shot 示例(string slot `responsibility` + list slot `action`,脱敏描述不引用 JD 原文遵守 spec §4.4);(3) `InterviewSession` 新增 3 可观测性字段(全部默认值兼容老测试构造)= `slot_source_breakdown: dict[str, int]` (rules / llm / mixed 计数) + `llm_parse_retry_count: int` (JSON + schema retry 累计) + `llm_to_rules_slot_fallback_count: int` (LLM 失败 fallback 累计);`extract_slots` 接 `session` 参数(老签名已存在但 unused, 激活) + `_extract_slots_via_llm` 加 session keyword-only 参数 retry 时 `session.llm_parse_retry_count += 1` + `_do_answer` 透传 sess;(4) `scripts/evaluate_interview_agent.py` 扩展可观测性 4 链路:`EvalRow` 3 字段 (defensive copy 过滤未知 key / 非 int / bool) + `compute_metrics` 3 聚合 (全局 / by_source / by_extractor compare 模式) + `write_report` 新增 `## 4.7、LLM 抽取可观测性 (R6-C.3)` 章节 + 每行 sample 摘要加 `src=[rules=N/llm=M/mixed=K] retries=N fb_to_rules=N` 3 字段 + §七隐私检查 + §八结论追加 + `VERSION` 常量更新为 "R6-C.3";**21 个新 pytest** = `tests/test_interview_agent.py::TestPhaseC3LLMObservability` 11 + `tests/test_interview_eval.py::TestPhaseC3ObservabilityFields` 5 + `TestPhaseC3ObservabilityReport` 5;baseline 909 → **930 全绿** (909 老测试零回退, 85.78s 跑完);**实测** = `pytest tests/ -q` 930 passed / `pytest tests/test_interview_agent.py tests/test_interview_eval.py -q` 146 passed in 2.22s / 前端 `npx vue-tsc --noEmit` 0 error + `npm run build` 成功;**offline compare 复跑实测** = `scripts/evaluate_interview_agent.py --mode offline --extractor compare` → `total=20 rules schema_pass=0.30 llm schema_pass=0.30 llm fallback_rate=1.00` + §4.7 渲染 `slot_source_breakdown.rules=60 llm=0 mixed=0 llm_rate=0.0 retries=0 fb_to_rules=0`;**不挂 pre-push / 不引入新依赖 / 不引入新 LLM 调用 / 不破坏** R5-E / R6-B / R6-C.1 / R6-C.2 任何边界
- **R6-D 全部完成** — 机械拆分 LLM slot 抽取模块(commit `91ec8f3`, 2026-07-02):R6-C.3 后行为不变重构(spec §5.3 + plan §4.4);改 1 个 backend 文件 + 新建 1 个 backend 文件 + 新建 1 个 backend 测试文件 + 改 1 个 backend 测试文件 + 改 1 个 api 测试文件 = `backend/core/interview_agent.py`(2074 → **1499 行**)+ `backend/core/interview_llm.py`(新建 **537 行**,含 R6-A Phase 4 LLM slot 抽取 + R6-B Phase 1 slot_meta helper + R6-B Phase 2 mode 决策 + R6-C.3 observability schema 全部符号)+ `backend/tests/test_interview_agent.py`(2674 → **1410 行**)+ `backend/tests/test_interview_llm.py`(新建 **1090 行**,平移 6 个 LLM class 共 35 case)+ `backend/tests/test_interview_api.py`(3 处 monkeypatch 路径改 `core.interview_llm` 命名空间);**不修改** `core/interview_policy.py` (R6-C.2B 路线 B 锁定) / `core/interview_verifier.py` (R6-B Phase 4 锁定) / `core/llm_rewriter.py` / `core/interview_prompts.py` / `scripts/` / 任何 frontend / `evaluate_*`;**搬运符号清单** (7 函数 + 3 helper + 5 常量 + 2 mode 常量 + 1 schema dict) — `_resolve_interview_llm_config` / `_validate_llm_extraction_payload` / `_call_llm_for_slot_extraction` / `_try_parse_llm_content` / `_extract_slots_via_llm` / `_attach_llm_slot_meta` / `_decide_interview_mode` / `_has_llm_api_key` / `_validate_confidence` / `_compute_source_span_hash` / `_make_slot_meta` + `_INTERVIEW_LLM_DEFAULT_BASE_URL` / `_INTERVIEW_LLM_DEFAULT_MODEL` / `INTERVIEW_LLM_NO_KEY_WARNING` / `INTERVIEW_MODE_RULES` / `INTERVIEW_MODE_LLM_ASSISTED` / `INTERVIEW_SLOT_META_MIN_CONFIDENCE` / `INTERVIEW_SLOT_META_MAX_CONFIDENCE` / `INTERVIEW_SLOT_META_RULES_CONFIDENCE_FALLBACK` / `INTERVIEW_SLOT_META_LLM_DEFAULT_CONFIDENCE` / `INTERVIEW_OBSERVABILITY_SCHEMA`;**重导出策略** = `interview_agent.py` 通过 `from core.interview_llm import ...` 重导出全部符号保持向后兼容;**反向依赖禁止** = `interview_llm.py` 不得 import `core.interview_agent`(仅 `TYPE_CHECKING` 块 import `InterviewSession` 类型注解) + 不得 import `core.llm_rewriter` (R5-E 边界保持);**0 新 pytest** — 全部行为不变机械平移;baseline 909 → **930 全绿**(R6-C.3 baseline 零回退, 87.45s 跑完);**实测** = `pytest tests/ -q` 930 passed / `pytest tests/test_interview_agent.py tests/test_interview_llm.py tests/test_interview_eval.py -q` 146 passed in 2.95s;**不挂 pre-push / 不引入新依赖 / 不引入新 LLM 调用 / 不改** LLM prompt / retry / schema / frontend
- CI 验证(pre-push hook 自动 pytest + vue-tsc + build)
- **948 个 pytest 全绿 + 0 skipped**(2026-07-03 R6-G 收尾时点 `D:\python3.11\python.exe -m pytest tests/ -q` 实测 948 passed in 117.94s;活跃基线以本行为准,历史快照 596/627/655/683/723/729/739/768/809/840/863/877/889/909/930/936 见各 round entry);计算口径沿用 R6-E 936 + R6-G +12:R6-B Phase 5 863 baseline + **14 R6-C.1** (`tests/test_interview_eval.py::TestPhaseC1*` 14 case = EvalContractValidation 7 + ReportContractSection 2 + ReportWording 3 + ReportPrivacy 2) + **12 R6-C.2A** (`tests/test_interview_eval.py::TestPhaseC2EvalContract` 12 case) + **20 R6-C.2B** (`tests/test_interview_policy.py::TestPhaseC2BCriticalSlot` 16 + `tests/test_interview_agent.py::TestPhaseC2BCriticalSlotIntegration` 4) + **21 R6-C.3** (`tests/test_interview_agent.py::TestPhaseC3LLMObservability` 11 + `tests/test_interview_eval.py::TestPhaseC3ObservabilityFields` 5 + `TestPhaseC3ObservabilityReport` 5) + **0 R6-D**(纯行为不变机械平移, 35 个 case 从 `test_interview_agent.py` 平移到新建 `test_interview_llm.py`) + **6 R6-E Phase 4** (`tests/test_interview_agent.py::TestSlotExtractionAlignsWithPolicy` 6 case: 4 gap × 3 轮对答 + 2 fallback 边界) + **0 R6-F closeout**(docs-only patch + UI chip fix + cleanup trash 不引入新测试) + **12 R6-G** (`tests/test_interview_verifier.py::TestVerifierSentinelF2_1` 5: sentinel 常量存在 / 触发条件 unsupported / 触发条件 low_confidence / 不触发空 sentinel / sentinel 不含 PII + `tests/test_interview_eval.py::TestEvalStderrSanitizeF2_3` 7: stderr 不含 LLM_API_KEY / sk- / Bearer + live mode key 错时脱敏 / offline mode 路径不变 / 错误信息含脱敏后路径 / 保留诊断信息)

**最近 7 个 commit** (`main` 与 `origin/main` 已同步至 `2c9e487`):
- `2c9e487` docs(round6-h): add live eval v2 decision gate (origin/main 同步点)
- `ae0e89b` feat(round6-g): review-needed 整理 — verifier sentinel + envelope hygiene + stderr 脱敏
- `a3f48b1` chore(round6-f): closeout patch — 4 处文档漂移修复 + 1 行 UI chip fix + R6-F 报告归档
- `7811973` docs(round6-e): AGENTS.md R6-E Phase 1 + Phase 4 entry 落地
- `3b632c7` chore(round6-e): API smoke 阈值 ≥2 → ≥1 bullets
- `7fe798c` fix(round6-e): _do_answer slot 优先读 question_plan 决策 (Phase 4)
- `669a5ef` docs(round6-e): Phase 1 文档同步 — spec 落档 + README/MEMORY 对齐 930 baseline

---

## 1. P1 — 短期可做(下次 round 候选)

### R6-A follow-up — 修正 `/api/interview/draft` 状态返回 + 补测试 ✅ 完成 (2026-06-30, commit `37ad00c`)
- **问题**(已修):`POST /api/interview/draft` 在 `can_draft=True` 时会返回 `draft_card`,但 API 层 `sess.state = sess.state` 是 no-op,未显式置为 `DRAFT_READY`。前端 `InterviewAgentPanel.vue` 素材卡视图依赖 `state === 'DRAFT_READY' && draftCard`,在 ASKING 状态下手动注入 slots 调 `/draft` 会返 `state="ASKING"`,与"已生成 draft_card" 语义不一致,UI 看不到素材卡。
- **修法**:`backend/api/interview.py` import `InterviewState`,在 `interview_draft()` 成功生成 card 后显式设 `sess.state = InterviewState.DRAFT_READY`(`can_draft=False -> 400` 旧路径不变)
- **回归测试**:`backend/tests/test_interview_api.py::TestDraftEndpoint::test_draft_returns_card_when_can_draft_true` 加 `data["state"] == "DRAFT_READY"` + `sess.state.value == "DRAFT_READY"` 双断言
- **范围**:小型 bugfix,不涉及 LLM / materials 写库 / eval 脚本;本轮顺手清 docs 漂移(2026-07-14 落到 ROADMAP)

### R3.5+ — 修 match_score 漏匹配 bug ✅ 完成 (2026-06-27, commit `2889dd9`)
- **问题**:`baiyun_2026_product` / `baiyun_2026_qa` 触发 score=0,本应命中 Python/AI/LLM 等关键词
- **实际根因**(比推测更复杂,2 个独立 bug):
  1. `_build_candidate_pool` 只查 role_skill_keys 对应 items,跨 role 经验不计入池 → baiyun_qa 误判
  2. `KEYWORD_GROUPS` 缺 "AI" surface,中英 JD 里高频 "AI" 字面识别不到 → baiyun_product 误判(parse_jd 命中 0 关键词,score 走全 unknown 兜底)
- **修法**:
  1. `_build_candidate_pool` 加 `include_borrowed=True` 参数(默认开):池 = role 范围 + 全素材库扫描
  2. `KEYWORD_GROUPS['skills']` 加 `("AI", "LLM", 0.5)`:跟 "大模型"/"LLM" 语义等价
  3. 抽出 `_scan_items_into_pool` 工具函数复用扫描逻辑
- **效果**:8 份 eval 实跑准确率 **7/8 = 88%**(R3.5 时 6/8 = 75%,+13pp);baiyun_qa 修后 score=100 ✓,baiyun_product 修后 score=100 但 label='建议补充' 待 user 复核(原 label 基于 score=0 反推)
- **3 个回归测试**:`tests/test_jd_parser.py::TestMatchScoreBugfixR35Plus` 锁死 baiyun_qa/baiyun_product 修复 + include_borrowed=False 旧行为

### R3.5+ (b) — PM 维度 surface ✅ 完成 (2026-06-27, commit `ed57e25`)
- **上下文**:R3.5+ 修后 baiyun_product score=100 vs label='建议补充' (期望 '中') 仍 gap;user 选 (b) 方案: 加 PM 维度 surface, 让 match_score 精确告诉 user 缺什么
- **修法**:`KEYWORD_GROUPS['domains']` 加 4 个 PM 维度 surface (0.5 加分): 物流 / 工业工程 / 原型 / 流程图
- **效果**:baiyun_2026_product 实跑: score=33, matched=['LLM'], missing=['原型', '工业工程', '流程图', '物流'];suggestions 精确给"补 PM 维度素材"指引 (提到物流/工业工程/原型)
- **8 份 eval live 准确率保持 7/8 = 88%**;baiyun_product 仍 skip (score='低' vs label='中' 仍 gap, 根因是 user 素材库实际缺 PM 经验, 不是算法问题)
- **3 个回归测试**:`tests/test_jd_parser.py::TestMatchScorePMDimensions` 锁死 baiyun_product missing 含 PM 4 项 + suggestions 提到 PM 关键词 + KEYWORD_GROUPS 字典级断言

### R3.5.1 — score_thresholds.py 改实跑 ✅ 完成 (2026-06-27, commit `44bd370`)
- **背景**:R3.5 写的 score_thresholds.py 读 jd_samples.json 里的 frozen top_score (R3.5 时 AI 推断写死的 score),R3.5+ / R3.5+ (b) 修 match_score 后, frozen top_score 跟实跑结果不一致, 报告失去参考价值
- **修法**:`scripts/score_thresholds.py` 移除 `s['top_score']` 读取, 改跑 `match_score(s['text'], s['role_id_hint'], materials)` 拿 score / coverage;role 沿用 role_id_hint (user 标定的期望 role), 不再 6 role 取最高 (简化);sys.path 注入 backend/ 让 scripts/ 下脚本能 import core.* (跟 match_golden_targets.py 同样处理);报告 markdown 顶部加 "R3.5.1 (实跑模式)" 标识 + "R3.5.1 vs R3.5 差异说明" 段
- **效果**:**8 份 eval 实跑准确率 R3.5.1 时点 7/8 = 88% → R3.6.2 baiyun_product label 第三次复核改 '别投' 后变 8/8 = 100%** (R3.5 frozen 6/8 = 75%, +13pp/+25pp);提升核心是 baiyun_2026_qa 从 frozen 0 → 实跑 100 (修后 '高' 跟 label '推荐投' 一致);报告含详细 coverage (skills/tools/domains 三维), 比 R3.5 报告信息量更丰富;R3.6.2 后 baiyun_product 实跑 33 '低' 跟 label '别投' 一致 (低对应别投阈值档)
- **5 个回归测试**:`tests/test_score_thresholds.py::TestScoreThresholdsLive` 锁死 (含 `test_live_mode_ignores_frozen_top_score` 篡改 frozen 字段后实跑分数不变, 核心防回潮)
- **未修(留给 user)**:baiyun_2026_product 严格阈值校验留待 user 补 PM 素材 (or 改 label='低') 后再 un-skip;frozen top_score / top_role / top_coverage 字段保留在 jd_samples.json 作为 R3.5 时点历史 snapshot

### R3-G — 外部简历上传 + 简历视角评分 ✅ 完成 (2026-06-27, commits `b15dec5` + `d81c71e` + `c3b2807`)
- **背景**:`feat/r3g-resume-upload` 分支保留 1467 行 MVP(外部简历实时读取 + JD 评分联动),worktree `D:/简历帮/r3g-resume-upload` HEAD `eb7e841`;用户 2026-06-26 选完 scope 后主动 cancel,R3-G cancelled 但 MVP commit 在分支保留
- **实施路径**(不走 git cherry-pick 改"功能移植"):R3-G base 是 R3-I 之前的旧 base,eb7e841 自身只 +1467/-5(worker 提前做了"剥离"工作),用 `git show <commit>:<file>` 提取纯新增文件 + 手动合并修改文件(避开 ~30 文件冲突)
- **实施成果**(3 commit 顺序落地):
  1. `b15dec5` Step 1: 纯新增 `backend/core/resume_parser.py` (250 行 docx/pdf/txt 解析) + `frontend/src/components/ResumeUploader.vue` (227 行 el-upload drag) + `backend/api/resume.py` 加 `POST /parse-external` + `backend/api/jd.py` MatchRequest 加 `external_resume_text` 字段 + `backend/core/jd_parser.py` `match_score` 加 `external_resume_text` 关键字参数(占位 `_build_resume_perspective`)
  2. `d81c71e` Step 2: 实装 `_build_resume_perspective` 核心逻辑(归一化简历文本 + 扫 required keywords 的 surface 命中 → have, 否则 need_candidate, need 扣掉 match_score 的 borrowed pool 避免 false negative) + 移植 44 个 R3-G 测试(`test_parse_external.py` 30 + `test_jd_match_ext.py` 14)
  3. `c3b2807` Step 3: 前端集成 `api/index.ts` 加 `ParsedResume` / `ResumePerspective` 类型 + `resumeApi.parseExternal(file)` + `jdApi.match` 第 3 参 + `App.vue` 加 `ResumeUploader` + `externalResumeText` ref + 评分结果区加 have/need 卡片
- **实施坑**(已写进 MEMORY.md):
  1. PowerShell `>` 重定向 git show 文件会写 UTF-16 with BOM → pytest "source code string cannot contain null bytes", 改用 `python -c "subprocess.check_output + open('wb')"`
  2. PowerShell `git commit -m` body 里 `**xx**:` 触发 pathspec 吞字段, 改用 `git commit -F <tmp_file>` 传多行 message
  3. `parse_resume_bytes` 返回 dict 不是 list, API endpoint 必须提取 `parsed["paragraphs"]` 不能直接传整个 dict
  4. UTF-16 → UTF-8 转码:6959 个 null bytes 让 pytest 报 "source code string cannot contain null bytes"
- **效果**:**181 passed, 0 skipped**;端到端冒烟: 上传简历 (.txt 218 字符/10 段) → score=95 / recommendation='高' / have=10 关键词 / need=0 (简历覆盖所有 JD 要求);不传 / 空字符串 → `resume_perspective: None` (前端 v-if 隐藏)

### R4 Agent MVP — Function Calling + Agent Loop + Session 记忆 ✅ 完成 (2026-06-27, commits `a4c9156` + `ac90e13` + `c5ec652` + `ba536df`, PR #1 合并)
- **背景**:用户对照 AI Agent R&D JD 识别出 4 个项目结构性缺口(Function Calling / Agent Loop / Session 记忆 / 可观测 trace);MVP 优先打前 3 个 + trace 跟 R4-A 合并,Chat UI 留 P2
- **ROI 决策**(对 JD 信号 × 改动成本):必做 R4-F + R4-A + R4-M,不做 R4-X (MCP 协议, ~400 行 + 改 SDK 风险大)/ R4-V (完整回放, 留 P2)
- **实施路径**(4 commit 顺序落地,3 步 + 1 集成):
  1. `a4c9156` Step 1 — `llm_rewriter.py` 加 `TOOL_EVALUATE_SCHEMA` OpenAI tools schema + `evaluate_bullet_jd_match(bullet, jd_focus)` 工具函数 + `_build_request_payload` 加 tools 字段 + `_extract_rewritten` 加 tool_calls 解析分支 + `rewrite_highlights` 加 `enable_function_calling: bool = False` 参数(默认关,旧路径字节级一致);`TestFunctionCalling` 5 case + `TestEvaluateBulletJdMatch` 3 case
  2. `ac90e13` Step 2 — `_call_with_agent_loop()` ReAct-style mini loop(`MAX_AGENT_STEPS=3` 硬上限 + 单步单工具 + 网络错误不入 loop)+ `logger.log_agent_trace(session_id, step, tool_name, latency_ms, outcome)` 写 `logs/agent_trace.log`(跟 `generation.log` 分离);`TestAgentLoop` 9 case + `TestLogAgentTrace` 3 case
  3. `c5ec652` Step 3 — `core/session.py` 新建 `_SESSIONS: dict[str, deque(maxlen=10)]` + 4 API(create / get / append / clear)+ `rewrite_highlights` 加 `session_id: str | None = None` 参数 + 隐私隔离(session 内容不写日志,只写 session_id + 步数);`TestSessionAPI` 8 case + `TestSessionIntegration` 3 case
  4. `ba536df` Step 4 (integration) — `generator.build_sections` + `api/resume.py` Preview/Generate 整链 `session_id` 字段透传;`enable_function_calling=False / session_id=None` 旧路径字节级一致,`TestSessionIntegration` 链路验证
- **实施坑**(已写进 MEMORY.md):
  1. R4-M worker 第一轮 commit `81dd80c` stat 只 2 文件, message 描述 5 文件 — classic "commit message 撒谎"
  2. cherry-pick R4-M 后 2 个 `TestSessionIntegration` fail(`rewrite_highlights` 没接 `session_id` 参数) — owner 手工补完剩下 4 文件改动 + 验证全绿
  3. `_call_with_agent_loop` 内部解析失败 + 工具执行失败要分别走不同降级路径,不能混在一起
- **效果**:**283 passed + 0 skipped**(252 R3-P baseline + 8 R4-F + 12 R4-A + 11 R4-M);`logs/agent_trace.log` 独立写,跟 `generation.log` 分离;`session_id=None` 字节级一致,旧 baseline 不破;预推送 hook 全绿
- **plan 文档**: `.harness/docs/round4-agent-mvp-plan.md`(已标 ✅ 完成)
- **R4-C (Chat UI 组件) 留 P2**:用户偏好"GUI 实施任务默认暂停",设计文档够用,等明确启动再开

### R5-A Agent 增强 — 4 phase + closeout 全部落地 ✅ 完成 (2026-06-27, merge `12dfcf1`)
- **背景**:R4 MVP 优先打 AI Agent R&D JD 结构性缺口;R5-A 在 R4 基础上补"可观测 + 可规划 + 可调用 + 可评测"工作流,设计文档 `.harness/docs/agent-enhancement-spec.md` 拆 4 phase;Phase 4 已在 `503005e` 完成,closeout 已在 `b60a215` 修复 API/工具契约补缺并通过 PR #4 合并到 `main`
- **实施路径**(5 个核心 commit 顺序落地) — 详见顶部"快照"段:
  1. `1679a22` Phase 1 — Agent 编排层 + 工具注册表(283 → 320)
  2. `7c5af05` Phase 2 — 结构化 JSONL trace + 会话回放(320 → 352)
  3. `380906f` Phase 3 — 轻量 RAG evidence + 零向量数据库(352 → 416)
  4. `503005e` Phase 4 — Agent 离线评测报告 12 JD × 4 开关对照(416 → 427)
  5. `b60a215` closeout — agent_summary + enable_external_resume + required args + match_score schema bugfix(427 → 441)
- **实施坑**:已写进 MEMORY.md / spec(Phase 1 测试数计算口径 / Phase 3 evidence 任务图插入位置 / evidence=None 字节级一致 / evidence 80 字符截断)
- **效果**:**441 passed + 0 skipped**;四阶段与 closeout 均零 P0/P1 安全阻塞;**默认 disable 全部新能力**(enable_agent_workflow=False + evidence=None + enable_function_calling=False + session_id=None),**零行为变更**
- **spec 文档**: `.harness/docs/agent-enhancement-spec.md`(Phase 1+2+3+4+closeout 状态均已 ✅)

### R5-B Phase 2A — 工具契约 / 权限 / 真实数据流 ✅ 完成 (2026-06-28, merge `09a2704`)
- **背景**:R5-A 已建好 Agent 编排层,但工具契约没显式 schema 校验,context 权限边界没定义,`tools_used` 含展示型工具噪声;R5-B Phase 2A 把 R5-A 已有能力补"契约 + 权限 + 语义"三件套
- **设计**: `.harness/docs/round5-b-agent-capability-spec.md` §3
- **实施路径**(1 commit + 文档同步):
  1. `232ea30` 工具契约(`core/tool_schema.py` 轻量 JSON schema validator 子集 type / required / properties / items / minimum / maximum, 零依赖纯 stdlib + `_check_permission_context(spec, context)` 校验 allow_jd_text / allow_materials / allow_external_resume / max_pii_risk, 权限不匹配返 PRIVACY_VIOLATION 早于 schema 校验 + `ToolSpec.metadata={"affects_preview": bool}` 新字段 + `affects_preview()` helper + `retrieve_evidence` 标 `affects_preview=True` 真正注入 build_sections → rewrite_highlights + `_build_step_context(tool_name, has_jd, has_external_resume)` 派发 context + `agent_summary.tools_used` 升级为有效语义只列 `affects_preview=True` 且 `status=success` 的工具 + 错误描述只含字段名 + 类型名 + 权限名,不含 args / JD / bullet 原文); **441 → 487 +46 pytest** (19 test_tool_schema + 18 test_agent_tools + 9 test_agent_workflow); 441 老测试零回退
  2. `593169e` 文档同步 — 当前能力表 + AGENTS 锁点同步 baseline 487
- **效果**:**487 passed + 0 skipped**;`agent_summary.tools_used` 只列影响 preview 的有效工具,展示型工具(`parse_jd` / `match_score` / `evaluate_bullet_jd_match` / `rewrite_highlights`)不再混入;老路径 `enable_agent_workflow=False` 字节级一致(agent_summary 字段只在 workflow 路径加);**不挂 pre-push hook / 不引入新 LLM 调用 / 不引入新依赖 / 不实际消费 external_resume / 不实施 GUI 面板**
- **下一步**:R5-C Phase 1-5 真实闭环(详见下方)

### R5-C — Agent 真实闭环与可解释化 5 phase 全部落地 ✅ 完成 (2026-06-28)
- **背景**:R5-B Phase 2A 解决"工具能不能被安全调用"问题;R5-C 推进到"可评测 + 可解释 + 可被前端安全消费"
- **设计**: `.harness/docs/round5-c-agent-capability-spec.md` 5 phase
- **Phase 1 — eval request_id 精确关联 + fallback taxonomy**(spec §2) — eval 优先读 `preview["agent_summary"]["request_id"]` 替代脆弱的 JSONL 末尾反推 + 新增 fallback_category 5 类常量(none / llm_disabled_fallback / tool_error_fallback / schema_retry_fallback / workflow_abort_fallback)+ 报告新增 "6.1 fallback taxonomy 摘要" 段
- **Phase 2 — 外部简历进入 Agent workflow**(spec §3) — `PreviewRequest.external_resume_text` 字段透传 + `run_agent_workflow` 接受 `external_resume_text` kwarg + 任务图 `has_external_resume=True` 插入 `parse_external_resume` + `compare_resume_jd` 两步(spec §3.3)+ `core/jd_parser.py` 两个新工具函数输出 4 维摘要不含原文 + workflow preview 返回 `external_resume_perspective` 字段; 17 个新 pytest(`tests/test_r5c_phase2_external_resume.py`); 老路径完全不含此字段字节级一致; 提交 `c6ead64`
- **Phase 3 — per-bullet 真实评估数据流**(spec §4) — `_evaluate_top_bullets(materials, target_role, jd_focus, jd_context, *, top_projects=3, bullets_per_project=3)` helper + workflow 主循环 evaluate step 走批量而非单条 representative + workflow preview 返回 `bullet_evaluations` 字段(老路径不含); 10 个新 pytest(`tests/test_r5c_phase3_bullet_evaluation.py`); `evaluate_bullet_jd_match` 仍 `affects_preview=False`(spec §4.4)
- **Phase 4 — 前端高级 Agent 面板契约** — `frontend/src/api/index.ts` 加 `AgentSummary` / `EvidenceSummary` / `ExternalResumePerspective` / `BulletEvaluation` TS 类型 + `preview/generate` 透传 enable_agent_workflow / session_id / external_resume_text + 前端 App.vue 默认收起诊断面板
- **Phase 5 — 文档与回放闭环** — `scripts/replay_agent_trace.py` 加 `## Fallback Summary` 段(基于 trace status/error_type 推断 category, 涵盖 none / tool_error_fallback)+ `--tools-used <csv>` 参数触发 `## Tools Cross-Validation (R5-C Phase 5)` 段(对账 caller 提供的 agent_summary.tools_used, 输出 status ok/missing/unexpected); ROADMAP / README / AGENTS 三方同步 baseline 530→544 测试数; **15 个新 pytest** (3 TestReplayFallbackSummary + 7 TestReplayToolsCrossValidation + 2 TestReplayPiiSafetyR5C + 2 TestReplayRobustnessR5C)
- **实施坑**(已写进 MEMORY.md / spec):
  1. Phase 1 `request_id` 从 agent_summary 取需要 workflow 路径先跑(`enable_agent_workflow=True`); 老路径(AW=F)走 JSONL 反查兜底
  2. Phase 2 `external_resume_text` 字段默认 None 完全不污染老路径(preview 不写 `external_resume_perspective` 字段); 但 `enable_external_resume` bool 仍保留向后兼容
  3. Phase 3 evaluate step 改 `has_jd` 触发(不再依赖 FC),但 evaluate_bullet_jd_match 工具仍 `affects_preview=False`(诊断输出,不注 build_sections / rewrite_highlights)
  4. Phase 5 replay `_observed_tools` 严格只接受 str 类型工具名(非 str / None / 空 字符串统一跳过),防止 events 里脏数据污染交叉验证
- **效果**:**547 passed + 0 skipped**(R5-D Phase 0 起活跃基线,2026-06-28 push `414a7cd` 时 pre-push hook 实测;R5-C 收尾时为 544);计算口径沿用 R5-C:R5-B Phase 2A baseline 497 + 17 Phase 1 + 16 Phase 2 + 10 Phase 3 + 14 Phase 5;五阶段均零 P0/P1 安全阻塞; `enable_agent_workflow=False` 老路径字节级稳定; eval 报告可被 Phase 1 fallback taxonomy 解释; 外部简历能进入 Agent workflow 诊断(原文不泄漏); per-bullet 评估可解释但不污染改写
- **spec 文档**: `.harness/docs/round5-c-agent-capability-spec.md`(5 phase 全部 ✅)
- **下一步**:等用户明确启动下一轮(如真实 LLM key 接入、GUI 面板实际打开、vector DB RAG 升级等)

### R5-D — 真实 LLM eval 闭环 + 文档收尾 6 phase 全部落地 ✅ 完成 (2026-06-28, commits `8a4a799` + `522d911` + `89717a9` + `1fef8dc` + `8838e7a` + `2052b1f` + Phase 5 文档收尾)
- **背景**:R5-C 完成"可评测 + 可解释"能力,但 eval 脚本默认永远走 offline fallback,无法量化"有真实 LLM key 时 Agent workflow 到底带来多少收益";R5-D 在不泄漏个人数据、不破坏默认离线路径的前提下,让 `scripts/evaluate_agent_workflow.py` 能区分并评估"无 key fallback"和"真实 LLM 调用"两种模式
- **设计**: `.harness/docs/round5-d-llm-eval-spec.md` 6 phase(Phase 0-5)
- **实施路径**(7 个 commit 顺序落地):
  1. `8a4a799` Phase 0 (文档) — `.harness/docs/round5-d-llm-eval-spec.md` 475 行 spec(spec §3-§12 含 5 phase 实施范围 + 测试策略 + 隐私边界 + 验收清单 + 推荐提交拆分)
  2. `522d911` Phase 0 (基线修正) — AGENTS.md + ROADMAP.md 活跃基线 544 → 547,显式标注 pre-push hook 来源 + R5-D Phase 0 起点;历史 round 描述里的 544 保留为 R5-C 收尾快照
  3. `89717a9` Phase 1 — `scripts/evaluate_agent_workflow.py` 加 `_resolve_eval_mode(mode, llm_enabled)` 纯函数 + 3 类 mode 常量(`MODE_OFFLINE`/`MODE_LIVE`/`MODE_AUTO`,默认 offline) + argparse `--mode` / `--output` CLI 参数;**live mode + llm_enabled=False → RuntimeError,错误信息**绝不**包含 key 值或 env var 名(spec §3.4 + R5-D §6.4 隐私边界;`TestEvalModeNoKeyLeak` 2 case 锁);`write_report` 加 requested_mode / resolved_mode 标注;547 → 557 +10 pytest
  4. `1fef8dc` Phase 2 — `_get_llm_eval_config(llm_enabled, resolved_mode) -> dict` 纯函数 helper,返回 4 字段 `llm_mode` / `llm_enabled` / `llm_model` / `llm_base_url_host`(用 `urllib.parse.urlparse(...).hostname` 抽 host 部分只输出 host,不含 scheme/path/query/fragment;`base_url_host` 空时写 `"unknown"`);**隐私边界** — helper **绝不**读 / 写 / 打印 `LLM_API_KEY`,`base_url_host` 只展示 host 部分防止 endpoint 路径泄露;`write_report` 加 `llm_eval_config` 入参,报告头部新增 `## 0、LLM 元信息 (R5-D Phase 2)` 章节 + 隐私边界注释;557 → 568 +11 pytest(`TestEvalLlmMetadataHelper` 8 + `TestEvalReportIncludesLlmMetadata` 1 + `TestEvalReportDoesNotIncludeApiKey` 1 + `TestEvalReportBaseUrlHostHidesPathAndQuery` 1)
  5. `8838e7a` Phase 3 — `_extract_project_highlights(preview)` 防御性处理 missing projects / no project_group / malformed preview / 非 str 元素 + `_summarize_rewrite_impact(before, after)` 纯函数返回 5 数字字段 `rewrite_changed_count` / `rewrite_total` / `rewrite_changed_rate` / `avg_len_before` / `avg_len_after`,**返回 dict 绝不存任何 bullet 原文**;`evaluate_one` 加 `baseline_highlights` kwarg(同 jd baseline combo 的 highlights 作 before,内部用 after 作 before 兜底),返回 row 新增 5 spec 字段 + 内部 `_after_highlights` 缓存字段(stripped before reaching report);`main()` 缓存 baseline combo highlights 给后续 3 combo 复用;`write_report` 新增 `### 7.1 rewrite impact 摘要 (R5-D Phase 3)` 章节 + per-JD 工具表新增 `rewrite_rate` 列;**隐私边界** — `ToolResult` / `agent_summary` / `JSONL trace` / `agent_eval report` 四层链路**绝不**存 / 写 / 展示 bullet 原文;568 → 584 +16 pytest
  6. `2052b1f` Phase 4 — `_percentile(values, p)` 纯函数(nearest-rank 0-100 百分位,空列表返 0,单元素返该元素,p=0/100 边界 clamp);`compute_metrics` 加 `p95_latency_ms` / `max_latency_ms` 跟 avg 组成 latency 三件套;`fallback_category_breakdown` 标准化 5 类(none / llm_disabled / tool_error / schema_retry / workflow_abort)缺的补 0 跟 6.1 章节一致;`write_report` 总览表加 p95 / max latency 列,6.1 章节新增每组 fallback_category 分布表;584 → 596 +12 pytest(清理 1 冗余 `test_empty_list_distinguishable_via_n_zero` 跟 `test_empty_list_returns_zero` 重叠)
  7. Phase 5 收尾(本 round `docs(round5-d): document live eval workflow`)— spec 状态行 📝 → ✅ + `round5-d-llm-eval-spec.md` §12 新增 6 子段(前置条件 + PowerShell 跑法 + 安全提示 + 验收清单 + 不实施 GUI 面板说明 + 跟既有脚本关系);ROADMAP 顶部快照段加 R5-D 6 phase 落地描述 + 活跃基线更新为 596 + 最近 7 commit 同步到 R5-D 系列;README 加一句"真实 LLM eval 是手动脚本,不进默认启动流程"
- **手动 live eval 安全跑法(PowerShell)**:(完整步骤见 spec §12)

  ```powershell
  $env:LLM_ENABLED="true"
  $env:LLM_API_KEY="..."
  $env:LLM_MODEL="gpt-4o-mini"
  D:\python3.11\python.exe scripts/evaluate_agent_workflow.py --mode live --output AI岗位JD库_agent_eval报告_live.md
  ```

- **安全提示**(用户必须遵守,spec §12.3):
  1. **不提交 `.env`**:`backend/.env` / 仓库根 `.env` / 任何含 `LLM_API_KEY` 的文件都已在 `.gitignore` 拒绝,提交前 `git status` 必须干净
  2. **不提交含真实敏感信息的 live 报告**:报告路径如果可能含 API key / 真实 JD 原文 / 真实 bullet 原文 / 真实手机号邮箱,**绝对不入库**;入库安全 iff 4 条全部满足 — 用公开脱敏 `materials.json` / 用公开 `AI岗位JD库_v4_intern.json` / eval set 来自内置 12 JD 不混入真实投递 JD / `LLM_BASE_URL` 不含内部路径或敏感 query
  3. **live 模式不进 pre-push**:`scripts/verify.ps1` / pre-push hook 永远不会自动触发 live,只跑默认 offline 路径
- **实施坑**(已写进 spec §12 / MEMORY.md):
  1. `_percentile` nearest-rank 用 `int(round((n-1) * p))` 防 p=0/100 边界越界,空列表 / 单元素单独 clamp
  2. `_extract_project_highlights` 防御性处理:missing projects / no project_group / malformed preview / 非 str 元素 统一返 `[]`,不抛
  3. `_summarize_rewrite_impact` baseline combo 自身 total = 0 时 changed_rate 必须 0,不能让空 total / len=0 触发除零
  4. `main()` 4 combo 循环里 baseline combo (combo_idx=0) 缓存 `_after_highlights` 给后续 3 combo 复用,缓存完即 strip 不入 row / report
  5. `_get_llm_eval_config` env var 优先级:`LLM_MODEL` / `LLM_BASE_URL` env → helper 内置 `_DEFAULT_BASE_URL_EVAL` / `_DEFAULT_MODEL_EVAL`;空字符串回落 default
  6. `write_report` 章节顺序:`## 0、LLM 元信息` 必须在 `## 一、Eval set 概览` 之前让审计一眼看到 LLM 配置(spec §4 R5-D Phase 2)
- **效果**:**596 passed + 0 skipped**(2026-06-28 `D:\python3.11\python.exe -m pytest tests/ --collect-only` 实测;R5-C 收尾时为 544,R5-D Phase 0 把活跃文档基线从 544 修正为 547,R5-D Phase 4 commit `2052b1f` 落地后再修正为 596);计算口径沿用 R5-D Phase 4 commit `2052b1f`:R5-B Phase 2A baseline 497 + 17 R5-C Phase 1 + 16 R5-C Phase 2 + 10 R5-C Phase 3 + 14 R5-C Phase 5 + 10 R5-D Phase 1 + 11 R5-D Phase 2 + 16 R5-D Phase 3 + 12 R5-D Phase 4;**49 个 R5-D Phase 1-4 新 pytest**(`TestEvalModeResolve` 5 + `TestEvalModeNoKeyLeak` 2 + `TestEvalCliOutput` 3 + `TestEvalLlmMetadataHelper` 8 + `TestEvalReportIncludesLlmMetadata` 1 + `TestEvalReportDoesNotIncludeApiKey` 1 + `TestEvalReportBaseUrlHostHidesPathAndQuery` 1 + `TestRewriteImpactCountsChangedBulletsWithoutStoringText` 5 + `TestExtractProjectHighlightsHandlesMissingProjects` 5 + `TestEvalReportContainsRewriteImpactSummary` 2 + `TestEvalReportDoesNotLeakBulletText` 4 + `TestPercentileEdgeCases` 4 + `TestMetricsLatencyPercentile` 3 + `TestMetricsFallbackBreakdown` 3 + `TestByComboAndGlobalCategoryConsistency` 2);六阶段均零 P0/P1 安全阻塞; `enable_agent_workflow=False` 老路径字节级稳定 + 老路径不含 mode 元信息以外的额外字段; `enable_function_calling=False` 路径完全不走 loop; `live` 错误信息不含 key 值 / env var 名; `base_url_host` 只展示 host 部分; 四层链路(ToolResult / agent_summary / JSONL trace / agent_eval report)绝不存 / 写 / 展示 bullet 原文
- **spec 文档**: `.harness/docs/round5-d-llm-eval-spec.md`(6 phase 全部 ✅;§12 手动 live eval 安全跑法段含 6 子段)
- **下一步**:等用户明确启动下一轮(如 R5-E embedding RAG 升级 / R5-F 真实 LLM 跑通后考虑默认开启 Agent workflow 面板 / R5-G 前端 dashboard)

### R5-E — Prompt 版本化 + A/B Eval 闭环 + 文档收尾 4 phase 全部落地 ✅ 完成 (2026-06-29, commits `7e92789` + `1c65bf9` + `fae76c4` + `51bf33b` + Phase 4 closeout)

- **背景**:R3-P 的 `SYSTEM_PROMPT` v2 是 few-shot + 显式 schema + retry 1 次的稳定生产 prompt,但无法在不改默认行为的前提下,快速对比"不同 prompt 改写效果";R5-E 在不改变默认生成行为的前提下,给 `SYSTEM_PROMPT` 增加显式版本选择 + 新增隐私安全的 A/B 评测脚本 + 可选 LLM-as-Judge,让后续是否 rollout winner 有真实数据依据
- **设计**: `.harness/docs/round5-e-prompt-optimization-spec.md` 4 phase (Phase 0-3 实施 + Phase 4 文档收尾, spec 状态 ✅)
- **实施路径** (5 个 commit 顺序落地):
  1. `7e92789` Phase 1 — `core/llm_rewriter.py` 加 `PROMPT_VERSION_BASELINE = "v2-baseline"` + `PROMPT_VERSIONS` 4 key 注册表 (v2-baseline 指向当前 `SYSTEM_PROMPT` + v3-priority P0-P4 优先级链 + v4-counterexample v3 + 4 条反例 + v5-minimal ≈5 句话极简版) + `_resolve_prompt_version(prompt_version: str | None) -> str` 纯函数 (None / 空字符串 → v2-baseline, 未知 key 抛 ValueError **错误信息不含 prompt 正文**) + `_select_system_prompt` 选择 base + 按现有规则追加 `EVIDENCE_CONSTRAINT_SUFFIX` + `_build_request_payload` / `rewrite_highlights` / `build_sections` / `preview_resume` / `generate_resume_docx` / `run_agent_workflow` 整链加 `prompt_version: str | None = None` 透传 + `PreviewRequest` / `GenerateRequest` 加 `prompt_version` 字段 (在 `external_resume_text` 之后, 保持既有字段顺序兼容); 31 个新 pytest in NEW FILE `test_prompt_versioning.py` (`TestResolvePromptVersion` 4 / `TestSelectSystemPrompt` 5 / `TestBuildRequestPayloadBytewiseStable` 5 — 含 default_payload_equals_system_prompt 字节级锁 / `TestRewriteHighlightsPassthrough` 4 / `TestApiModels` 6 — 含 prompt_version_after_external_resume_text 字段顺序锁 / `TestWorkflowPassthrough` 2 / `TestPrivacyGuarantee` 2 — error_message_no_prompt_body / `TestPromptVersionRegistry` 3); 596 → 627 baseline, 596 老测试零回退
  2. `1c65bf9` Phase 0 spec 入库 — `.harness/docs/round5-e-prompt-optimization-spec.md` 580 行 (含 §10 R5-E 之后 + §11 Phase 4 收尾记录)
  3. `fae76c4` Phase 2+3 一起 — `scripts/evaluate_prompt_versions.py` 复用 R5-D `evaluate_agent_workflow` 的 6 个 helper (`load_eval_set` / `_resolve_eval_mode` / `_get_llm_eval_config` / `_extract_project_highlights` / `_percentile` / `_check_pii_safe`) + 5 类 fallback_category 常量 (`none` / `llm_disabled_fallback` / `tool_error_fallback` / `schema_retry_fallback` / `workflow_abort_fallback`) + CLI `--mode` {offline, live, auto} 默认 offline + `--versions` <csv> 默认 4 个全跑 + `--runs-per-version` 默认 1 + `--output` 默认 `AI岗位JD库_prompt_ab报告.md` + `--judge {off,on}` 默认 off + `--judge-model`;**固定 FC=T + AW=T, 只变 prompt_version** — 跟 R5-D 评测 4 开关对照解耦, 报告回答"同一 workflow 下哪个 prompt 更好"; judge helper 三件套 (`_validate_judge_payload` 纯函数 schema 校验 + `_call_judge` stdlib urllib 不 retry + `_summarize_judge_metrics` 5 字段聚合);**offline 模式 judge 强制 disabled 防误触 HTTP**; 56 个新 pytest in NEW FILE `test_prompt_eval.py` (TestPromptEvalHelpers 8 / TestEvaluateOne 3 / TestComputeMetrics 2 / TestMainOfflineReport 9 / TestVersionRegistry 3 / TestPrivacyBoundary 3 / **TestJudgeSchemaValidation 8** / **TestJudgeCallRobustness 5** / **TestJudgeSummarizeMetrics 3** / **TestJudgeEvaluateOneIntegration 5** / **TestJudgeMainOfflineAndReport 7**); 627 → 683 baseline, 627 老测试零回退
  4. `51bf33b` offline 报告入库 — `AI岗位JD库_prompt_ab报告.md` 138 行 (12 JD × 4 version × 1 run = 48 条样本, 7 章节, PII 自检 pass)
  5. (Phase 4 closeout) `docs(round5-e): close prompt ab harness round` — README 顶部 "当前状态" + "核心能力" + scripts 列表 + AGENTS 锁点 (Phase 1+2+3+4 共 4 段) + ROADMAP 顶部快照 + 下一轮候选 + spec 状态从"📝 待实施 spec"改为"✅ 完成" + §11 Phase 4 收尾记录含最终 683 baseline + 新增报告路径
- **实施坑** (已写进 spec §11 / MEMORY.md):
  1. Phase 1 字段顺序:`prompt_version` 必须加在 `external_resume_text` 之后, 否则 Pydantic 向后兼容会破 (`test_api_models` prompt_version_after_external_resume_text 锁死)
  2. Phase 2 评测变量隔离:固定 FC=T + AW=T, 只变 prompt_version — 跟 R5-D 评测 4 开关对照解耦,否则评测结果混淆 workflow 变量
  3. Phase 3 judge schema 校验:显式排除 bool 是 int 子类, 否则 `True` / `False` 误入 quality_score 范围; 错误描述只含字段名不接触 reasoning 等额外字段
  4. Phase 3 judge 强制 disabled:offline 模式即使 `--judge on` 也不发 HTTP, 报告头部明示 "offline mode forces judge disabled", 防止评测脚本意外产生真实网络调用
  5. Phase 4 spec 状态:只能在代码 / 测试 / offline 报告 / 文档都完成后才把状态改为"✅ 完成", 否则下次 round 误以为 R5-E 已就绪
- **效果**:**683 passed + 0 skipped** (R5-E Phase 4 收尾时点; 计算口径沿用 R5-E: R5-D 596 baseline + 31 R5-E Phase 1 + 28 R5-E Phase 2 + 28 R5-E Phase 3 = 683); R5-E 4 phase + 文档收尾均零 P0/P1 安全阻塞; **默认 disable 全部新能力** (`prompt_version=None` / `--judge off` / offline mode), **零行为变更**;**不挂 pre-push hook** / **不引入新 LLM 调用** / **不引入新依赖**; 老路径 `prompt_version=None` 字节级一致, **596 老测试零回退**; **不改 `SYSTEM_PROMPT` 默认内容 / 不把 `PROMPT_VERSION_BASELINE` 切到 winner / 不新增前端 prompt selector**
- **不 rollout winner**:`PROMPT_VERSION_BASELINE` 仍为 `"v2-baseline"`, `PROMPT_VERSIONS["v2-baseline"]` 仍指向当前 `SYSTEM_PROMPT` 字符串 (字节级锁); 3 个候选 prompt (v3-priority / v4-counterexample / v5-minimal) 仍属实验, 等 live A/B 报告决策
- **spec 文档**: `.harness/docs/round5-e-prompt-optimization-spec.md` (4 phase 全部 ✅; §11 Phase 4 收尾记录含 5 commit hash + 最终 683 baseline + 新增报告路径 + 5 个未做的事)
- **新增报告**:`AI岗位JD库_prompt_ab报告.md` (offline, 自动入库, PII 自检 pass); `AI岗位JD库_prompt_ab报告_live.md` (可选 live 模式, **入库前必须人工隐私检查**)
- **下一步 (P1 候选)**:基于 live A/B 报告选择 winner 并 rollout — R5-E closeout / R5-F prompt rollout (默认 prompt 从 v2-baseline 切到 winner, 保留 v2-baseline 显式回退路径);若 live 报告显示 hallucination 仍高, 优先 R5-F embedding RAG 升级 evidence retrieval 不切 prompt

### R6-B — 面试官智能体可信增强层 6 phase 全部落地 ✅ 完成 (2026-06-30, 7 个 commit 顺序落地)
- **背景**:R6-A Phase 4 已在 `backend/core/interview_agent.py` 内落地可选 LLM slot extraction,但抽取结果不可追溯 / 用户不能控制智能模式 / 下一问偏模板化 / draft 缺核验 / eval 没有对照组;R6-B 不重做抽取,只补"可信增强层" 6 phase
- **设计**: `.harness/docs/round6-b-interview-agent-intelligence-spec.md` (R6-B Phase 0-6 + Phase 7 收尾;spec 状态 ✅;824 行 spec 含 §0-§15)
- **实施路径** (7 个 commit 顺序落地):
  1. `119575c` Phase 0 (基线校准) — `scripts/evaluate_interview_agent.py` 修旧"Phase 4 LLM 未上线"注释/live mode 错误信息/报告 §二 §四 标题口径,脚本行为零变化;baseline 维持 739
  2. `f665c35` Phase 2 (API mode 开关) — `StartRequest.enable_interview_llm: bool = False` + `StartResponse.interview_mode` / `mode_warning` + `ReplyResponse.extraction_summary` / `question_plan`;`_decide_interview_mode(enable_interview_llm)` 决策表 (enable=F / enable=T+有 key / enable=T+无 key);`create_session(..., *, enable_interview_llm=False)` keyword-only 入参;reply 沿用 session mode;739 → 768 +11 pytest (`tests/test_interview_api.py`)
  3. `d1622bb` Phase 3 (confidence-aware policy) — `backend/core/interview_policy.py` 新建,`plan_next_question(session)` deterministic 纯函数 8 步优先级链 (no_gap → skip 强制 → turn 强制 → missing required → low_confidence_recheck → near_limit_priority → next_suggested → anti_repeat_switch → all_covered);AST 静态扫描 import 不含 urllib/requests/httpx/openai/anthropic/llm_rewriter;不读 os.environ;768 → 809 +41 pytest (NEW FILE `tests/test_interview_policy.py` 29 + `tests/test_interview_agent.py::TestPhase3PolicyIntegration` 12)
  4. `51f6450` Phase 4 (draft verifier) — `backend/core/interview_verifier.py` 新建,`verify_draft_card(card, session) -> dict` 5 字段 summary + `compute_confidence_notes(session) -> list[str]`;双源命中规则:量化数字 regex `(人|%|倍|小时|天|次|万|个|条|例)` 命中 OR bullet 是 SOURCE_SLOT_KEYS 子串;warning 截前 30 字 + bullet 索引;809 → 840 +31 pytest (NEW FILE `tests/test_interview_verifier.py` 24 + `tests/test_interview_api.py` 7)
  5. `7b756fc` Phase 4 文档同步 — baseline 840 锁
  6. `b1635fc` Phase 5 (eval compare) — `scripts/evaluate_interview_agent.py` 加 `--extractor {rules, llm, compare}` CLI;5 类 fallback_category;EvalRow +4 字段 (extractor_mode / fallback_category / low_confidence_slot_count / total_slot_meta_count);compute_metrics +low_confidence_slot_rate + p95_latency_ms + by_extractor + fallback_category_breakdown;write_report +对照表 8 指标 + Delta 块;复用 R5-D `_resolve_eval_mode` / `_get_llm_eval_config` / `_check_pii_safe` / `_percentile` 4 helper;840 → 863 +23 pytest (NEW FILE `tests/test_interview_eval.py::TestPhase5*`)
  7. `be250e3` Phase 6 (frontend 最小呈现) — `frontend/src/api/index.ts` 加 InterviewMode / ExtractionMode 类型 + ExtractionSummary / QuestionPlan / VerificationSummary 3 interface + 各 optional 字段;`InterviewAgentPanel.vue` 加 enableInterviewLlm toggle (默认关) + interviewMode / modeWarning state + modeTagInfo 三态 header 标签;`InterviewDraftCard.vue` 加 confidenceNotes / verification / needsSaveConfirm + 紫边框置信度 + 事实核验摘要 2 个面板 + ElMessageBox 保存前确认提示;0 新 pytest,前端靠 `vue-tsc --noEmit` + `npm run build` 验收
  8. (本 round 收尾) `docs(round6-b): sync active baseline 863 after phase 5` — README / ROADMAP / AGENTS / spec 四方同步
- **离线 eval 实测** (`D:\python3.11\python.exe scripts/evaluate_interview_agent.py --mode offline --extractor compare --output backend/logs/interview_eval_report.md`):
  - 报告生成成功,total=20 (rules=10 + llm 意图=10)
  - rules schema_pass=0.30 / avg_completeness=0.53 / fabric_violations=0 / fallback_rate=0.00 / low_confidence_slot_rate=0.23
  - llm 意图(offline → 强制规则 fallback):schema_pass=0.30 / avg_completeness=0.53 / fabric_violations=0 / fallback_rate=1.00 / low_confidence_slot_rate=0.23
  - 报告隐私自检通过 (`Select-String -Pattern "用户原文哨兵|LLM_API_KEY|BEGIN PROMPT|source_span" -SimpleMatch` 无匹配)
- **核心边界** (6 phase 一致,不改):
  - 不重做 LLM slot extraction / 不把面试官改成自由聊天 Agent
  - `enable_interview_llm=False` 字节级一致(老路径 768 老测试零回退)
  - 不改 `core.llm_rewriter.py` / `core.agent_workflow.py` / `core.agent_tools.py` / `core.tool_schema.py` / `PROMPT_VERSIONS` / 默认 resume rewrite prompt
  - 不 rollout R5-E prompt winner / 不把 live eval report 自动入库
  - 不挂 pre-push hook / 不引入新依赖(纯 stdlib + dataclass)
- **隐私边界** (6 phase 一致):
  - `ToolResult` / `agent_summary` / `JSONL trace` / `interview_eval report` / `_interview_meta.verification` 5 层链路**绝不**含 user_message / source_span / draft_bullets / API key / env var 名 / key 前缀 / Bearer / prompt 正文
  - `extraction_summary` schema 限定只 4 字段(无 source_span / user_message / confidence / source_span_hash)
  - verifier warning 截前 30 字 + bullet 索引,不复制完整 bullet 文本
  - report 边界说明用 "API key 类凭据" / "LLM 抽取源 span 明文" 通用描述,避免 spec §14 `Select-String` 假阳性
- **实施坑** (已写进 spec §15 Prompt 7 收尾 + 各 phase commit message):
  1. Phase 3 `_make_empty_plan(NO_MORE)` hardcode `can_draft=False` → step 8 时前端误以为不能 draft;改为 `_already_can_draft(session)` 算
  2. Phase 3 lazy import 防止 policy / agent 循环 (`from core.interview_policy import (...)` 不 import 函数本身)
  3. Phase 4 verifier warning 截前 30 字 `_WARNING_BULLET_PREVIEW_LEN = 30`,不复制完整 bullet
  4. Phase 5 offline mode 强制 judge disabled 防误触 HTTP,沿用 R5-D Phase 1 `TestEvalModeNoKeyLeak` 模式
  5. Phase 5 EvalRow `confidence` 必须是 0.0-1.0 number,bool 不接受(防 `True` / `False` 误入)
  6. Phase 6 移动端 toggle 行用普通 `div + flex` + `el-tooltip`,**不**用 el-popover / drawer 嵌套,避免挤压 EMPTY 卡
  7. Phase 6 confidence_notes / verification 区域用普通 `div + 浅紫边框`,**不**产生 portal / overlay,移动端可随 drawer 滚动
- **效果**: **863 passed + 0 skipped**(2026-06-30 `D:\python3.11\python.exe -m pytest tests/ -q` 实测);**前端 `vue-tsc --noEmit` 0 error + `npm run build` 成功**(dist/index.html 0.48kB / css 369kB / js 1104kB);**offline compare 报告通过隐私自检**;6 phase + 文档收尾均零 P0/P1 安全阻塞;**默认 disable 全部新能力**(`enable_interview_llm=False` / 老路径字节级一致 / 老 prompt `v2-baseline` / 老 route `enable_agent_workflow=False`),**零行为变更**
- **spec 文档**: `.harness/docs/round6-b-interview-agent-intelligence-spec.md` (7 phase 全部 ✅;§15 Prompt 7 收尾记录含 8 commit hash + 最终 863 baseline + 新增报告路径 + 5 个未做的事 + 下一轮建议)
- **下一步 (P1 候选)**:
  - (a) **R6-C.1+ C.2A+ C.2B+ C.3+ R6-D 已全部完成**(详见下方 R6-C 条目);后续基于真实 10+ 轮对话跑 live eval v2,作 Phase 4 启动的 ground truth(spec §8 product gate);**入库前必人工隐私检查**(公开脱敏 materials.json / 公开 JD 库 / eval set 内置 / `LLM_BASE_URL` 不含内部路径)
  - (b) **R5-F prompt rollout** — 若 live A/B 报告显示 v3-priority / v4-counterexample / v5-minimal 中有稳定 winner,切默认 prompt(保留 v2-baseline 显式回退)
  - (c) **R6-D+ LLM prompt 优化 / retry 策略 / token 控制 / PROMPT_VERSIONS 扩** — R6-D 拆分后 LLM 模块边界清晰,下一轮可基于真实对话数据迭代 few-shot + temperature 微调、retry 策略升级(指数 backoff / multi-sample / best-of-N)、prompt 压缩 / 缓存命中检测;扩 `PROMPT_VERSIONS` 把 `SLOT_EXTRACTION_SYSTEM_PROMPT` 入注册表(决策点 D5 突破,需先收集 live v2 数据)

### R6-C — Live eval 合同可信 + LLM 抽取可观测 + 模块拆分 4 round + R6-D 行为不变重构 全部落地 ✅ 完成 (2026-07-02, commits `ea43473` + `a1a9fc2` + `caab6ff` + `651ea4e` + `84dd086` + `91ec8f3`)
- **背景**:R6-C.0 在 2026-07-01 13:29 跑了一次 live eval(`scripts/evaluate_interview_agent.py --mode live --extractor compare`),但 `schema_pass_rate=0.30` / `avg_completeness=0.53` 未达门槛 + llm vs rules delta=+0.00 证明 LLM 暂无质量收益。R6-C 不重做 LLM,只补 4 块短板:eval contract 可信度(让指标可解释)+ policy gap-specific critical slot(让 expected slot 三轮内可达)+ LLM 抽取可观测性(逐 slot / 逐样本统计 source / retries / fallback)+ 模块拆分(降低维护成本)
- **设计**: `.harness/docs/round6-c-live-eval-result-and-next-steps.md`(原路线规划)+ AGENTS.md 各 round 锁死段落
- **实施路径** (6 个 commit 顺序落地):
  1. `ea43473` R6-C.1 (路线 A) — eval contract warnings + live compare wording fix:`scripts/evaluate_interview_agent.py` 加 `_validate_eval_contract(sample)` 纯函数 + 2 个 warning code 常量 + 报告新增 `## 4.5 Eval contract warnings` 章节 + live compare 表头按 requested_mode 动态化 + §二 fallback_rate 口径声明;**14 个新 pytest** (`TestPhaseC1EvalContractValidation` 7 + `TestPhaseC1ReportContractSection` 2 + `TestPhaseC1ReportWording` 3 + `TestPhaseC1ReportPrivacy` 2);baseline 863 → **877**;**不挂 pre-push / 不修改 core/**
  2. `a1a9fc2` R6-C.2A (路线 A 收尾, 不改 policy) — fix eval set contract:10 条 sample 加 `product_goal` (枚举 `three_turn_friendly` / `full_fact_coverage`) + `contract_note` 字段;`communication_club` 调 `expected_slots` 移除 responsibility 改为 `(action, method, result)` 表达 3 轮内可生成素材目标;7 条 simulated samples 不删 expected 在 `contract_note` 标记 "需后续 policy 调整";报告新增 `## 4.6 Eval contract: product goal` 章节 + §八 结论追加 "schema_pass_rate 数值变化 = 评测合同变化" 口径声明;**12 个新 pytest** (`TestPhaseC2EvalContract` 12);baseline 877 → **889**;**不挂 pre-push / 不修改 core/ / frontend**
  3. `caab6ff` + `651ea4e` R6-C.2B (路线 B, 改 policy 让 critical slot 三轮内可达) — 只改 `backend/core/interview_policy.py` + 2 测试文件;`INTERVIEW_POLICY_GAP_CRITICAL_SLOTS` 新常量 2 entries(`tech_metric: ("metric", "method")` + `communication: ("responsibility",)`)放 policy 内部不污染 `GAP_SUGGESTED_SLOTS`(LLM 抽取端引导顺序);`_find_missing_critical_slots(session)` helper;`plan_next_question` 新增 **step 4.5 (gap_critical_slot_priority)** 优先级位置在 step 4 (low_confidence) 之后 step 5 (near_limit) 之前;**R6-C.1 contract warning 6 条对应修复** = 5 条 unreachable / beyond warning 现能通过 step 4.5 三轮内被问到;**20 个新 pytest** = `tests/test_interview_policy.py::TestPhaseC2BCriticalSlot` 16 + `tests/test_interview_agent.py::TestPhaseC2BCriticalSlotIntegration` 4;baseline 889 → **909**;**实测** = `pytest tests/test_interview_policy.py tests/test_interview_agent.py -q` 115 passed;**不期望 schema_pass_rate 提升**(eval 走 `_extract_slots_iteratively` 路径不走 policy,改动只影响 `next_question` 路径即前端 chat panel UI);**不挂 pre-push / 不引入新依赖 / 不修改 `core/interview_agent.py` / `core/interview_prompts.py` / 任何 scripts/ / frontend / eval set**
  4. `84dd086` R6-C.3 (R6-C.2 阶段收尾增量, 不拆模块, 4 个目标一次性交付) — (a) `_call_llm_for_slot_extraction` request body 加 `response_format={"type": "json_object"}`(OpenAI-compatible 强约束 JSON 输出, 温度仍 0.0 字节级一致);(b) `SLOT_EXTRACTION_SYSTEM_PROMPT` 加 2 个短 few-shot 示例(string slot `responsibility` + list slot `action`, 脱敏描述不引用 JD 原文遵守 spec §4.4);(c) `InterviewSession` 新增 3 可观测性字段(全部默认值兼容老测试构造)= `slot_source_breakdown: dict[str, int]` (rules / llm / mixed 计数) + `llm_parse_retry_count: int` (JSON + schema retry 累计) + `llm_to_rules_slot_fallback_count: int` (LLM 失败 fallback 累计);`extract_slots` 接 `session` 参数(老签名已存在但 unused, 激活) + `_extract_slots_via_llm` 加 session keyword-only 参数 retry 时 `session.llm_parse_retry_count += 1` + `_do_answer` 透传 sess;(d) `scripts/evaluate_interview_agent.py` 扩展可观测性 4 链路:`EvalRow` 3 字段 (defensive copy 过滤未知 key / 非 int / bool) + `compute_metrics` 3 聚合 (全局 / by_source / by_extractor compare 模式) + `write_report` 新增 `## 4.7、LLM 抽取可观测性 (R6-C.3)` 章节 + 每行 sample 摘要加 `src=[rules=N/llm=M/mixed=K] retries=N fb_to_rules=N` 3 字段 + §七 隐私检查 + §八 结论追加 + `VERSION` 常量更新为 "R6-C.3";**21 个新 pytest** = `tests/test_interview_agent.py::TestPhaseC3LLMObservability` 11 + `tests/test_interview_eval.py::TestPhaseC3ObservabilityFields` 5 + `TestPhaseC3ObservabilityReport` 5;baseline 909 → **930** (909 老测试零回退, 85.78s 跑完);**offline compare 复跑实测** = `scripts/evaluate_interview_agent.py --mode offline --extractor compare` → `total=20 rules schema_pass=0.30 llm schema_pass=0.30 llm fallback_rate=1.00` + §4.7 渲染 `slot_source_breakdown.rules=60 llm=0 mixed=0 llm_rate=0.0 retries=0 fb_to_rules=0`;**不挂 pre-push / 不引入新依赖 / 不引入新 LLM 调用 / 不破坏** R5-E / R6-B / R6-C.1 / R6-C.2 任何边界
  5. `91ec8f3` R6-D (R6-C.3 后行为不变重构, spec §5.3 + plan §4.4) — 改 1 backend 文件 + 新建 1 backend 文件 + 新建 1 backend 测试文件 + 改 1 backend 测试文件 + 改 1 api 测试文件 = `backend/core/interview_agent.py`(2074 → **1499 行**) + `backend/core/interview_llm.py`(新建 **537 行**, 含 R6-A Phase 4 LLM slot 抽取 + R6-B Phase 1 slot_meta helper + R6-B Phase 2 mode 决策 + R6-C.3 observability schema 全部符号) + `backend/tests/test_interview_agent.py`(2674 → **1410 行**) + `backend/tests/test_interview_llm.py`(新建 **1090 行**, 平移 6 个 LLM class 共 35 case) + `backend/tests/test_interview_api.py`(3 处 monkeypatch 路径改 `core.interview_llm` 命名空间);**不修改** `core/interview_policy.py` (R6-C.2B 路线 B 锁定) / `core/interview_verifier.py` (R6-B Phase 4 锁定) / `core/llm_rewriter.py` / `core/interview_prompts.py` / `scripts/` / 任何 frontend / `evaluate_*`;**搬运符号清单** (7 函数 + 3 helper + 5 常量 + 2 mode 常量 + 1 schema dict) — `_resolve_interview_llm_config` / `_validate_llm_extraction_payload` / `_call_llm_for_slot_extraction` / `_try_parse_llm_content` / `_extract_slots_via_llm` / `_attach_llm_slot_meta` / `_decide_interview_mode` / `_has_llm_api_key` / `_validate_confidence` / `_compute_source_span_hash` / `_make_slot_meta` + 5 常量 + 2 mode 常量 + 1 schema dict;**重导出策略** = `interview_agent.py` 通过 `from core.interview_llm import ...` 重导出全部符号保持向后兼容;**反向依赖禁止** = `interview_llm.py` 不得 import `core.interview_agent`(仅 `TYPE_CHECKING` 块 import `InterviewSession` 类型注解) + 不得 import `core.llm_rewriter` (R5-E 边界保持);**0 新 pytest** — 全部行为不变机械平移;baseline 909 → **930** (R6-C.3 baseline 零回退, 87.45s 跑完);**不挂 pre-push / 不引入新依赖 / 不引入新 LLM 调用 / 不改** LLM prompt / retry / schema / frontend
- **本阶段新指标分布**(实测):
  - **Eval contract warnings** = 6 条 unique warning(按 sample 去重, compare 模式双组同跑不重复): `sim_tech_metric_medical_eval` metric unreachable + `sim_tech_metric_ecg` method beyond_3 + metric unreachable + `sim_communication_volunteer` responsibility unreachable + `sim_tech_metric_rubric_design` method beyond_3 + metric unreachable
  - **product_goal 分工** = 10 条 sample 全标注, 3 条 `three_turn_friendly` (plan_baseline, 调整后 0 warning) + 7 条 `full_fact_coverage` (simulated_user_v1, 保留 expected, 6 条 unique warning 跨 4 条 sample)
  - **LLM 抽取可观测性**(offline 跑) = `slot_source_breakdown.rules=60 llm=0 mixed=0 llm_rate=0.0 retries=0 fb_to_rules=0`;**offline 模式 LLM 不发网络, 符合预期**;真实 LLM 调用需在 live 模式 + 已配置 LLM 凭据时才会出现 llm>0
- **本阶段核心边界** (5 round 一致, 不改):
  - `enable_interview_llm=False` 字节级一致(老路径 session `llm_mode=rules`, 3 个可观测字段保持 0 / {} / {})
  - `_extract_slots_by_rules` 不写 LLM 可观测字段(R6-C.3 锁, 避免老路径污染)
  - 不改 `core/llm_rewriter.py` / `core/agent_workflow.py` / `core/agent_tools.py` / `core/tool_schema.py` / `core/interview_prompts.py` (R5-E + R6-A Phase 4 边界)
  - 不 rollout R5-E prompt winner / 不把 live eval report 自动入库 / 不挂 pre-push hook
  - 不引入新依赖(纯 stdlib + urllib + json + dataclass + TYPE_CHECKING)
- **隐私边界** (5 round 一致):
  - `ToolResult` / `agent_summary` / `JSONL trace` / `interview_eval report` / `_interview_meta.verification` / `EvalRow`(R6-C.3) 6 层链路**绝不**含 user_message / source_span / draft_bullets / API key / env var 名 / key 前缀 / Bearer / prompt 正文
  - 报告 4.5 / 4.6 / 4.7 章节(本阶段新增)只含 slot key + 整数计数 + 比率, 不写 user_message / prompt / source_span / API key
  - report 边界说明用 "API key 类凭据" / "LLM 抽取源 span 明文" 通用描述, 避免 spec §14 `Select-String` 假阳性
- **实施坑** (已写进 spec §15 / 各 round commit message / AGENTS.md):
  1. R6-C.1 `_validate_eval_contract` near_limit 触达集合 `{metric, result}` 必须跳过 beyond 检查, 否则会误报 `sim_process_metric_*` 类的合法 expected
  2. R6-C.2A `communication_club` 调 expected 后必须含 `result` (captured 没), 证明是合同驱动不是结果驱动 (test `test_communication_club_removed_responsibility_slot` 锁死)
  3. R6-C.2B `INTERVIEW_POLICY_GAP_CRITICAL_SLOTS` 必须放 policy 内部不能污染 `GAP_SUGGESTED_SLOTS` (LLM 抽取端引导顺序, 改它会污染 LLM 抽取链路)
  4. R6-C.3 EvalRow defensive copy + 只取已知 key + int 校验, 防 session 字段污染;`extract_slots` 接 `session` 参数(老签名已存在但 unused, 激活);`_extract_slots_via_llm` retry 时 `session.llm_parse_retry_count += 1`(网络错不 retry 不计入)
  5. R6-D `_observed_tools` 严格只接受 str 类型工具名(沿用 R5-C 模式), 防止 monkeypatch 跨模块污染;`test_interview_api.py` 3 处 monkeypatch 必须从 `core.interview_agent.urllib.request.urlopen` 改 `core.interview_llm.urllib.request.urlopen`
- **效果**:**930 passed + 0 skipped**(2026-07-02 `D:\python3.11\python.exe -m pytest tests/ -q` 实测 122.31s);R6-C.3 + R6-D 均零 P0/P1 安全阻塞;R6-C.1 + C.2A + C.2B + C.3 老路径字节级一致 + R6-D 行为不变重构 R6-C.3 baseline 零回退;**默认 disable 全部新能力**(`enable_interview_llm=False` / 老 prompt `v2-baseline` / 老 route `enable_agent_workflow=False` / 老 `INTERVIEW_POLICY_GAP_CRITICAL_SLOTS` 只在 step 4.5 生效);**零行为变更**
- **下一步** (P1 候选): 基于用户在 chat panel 跑 10+ 轮真实对话 + 已配置 LLM key, 跑 `scripts/evaluate_interview_agent.py --mode live --extractor compare` 生成 v2 live 报告作为 Phase 4 启动 ground truth (spec §8 product gate);**入库前必人工隐私检查**;若 live v2 显示 LLM 质量 delta 明确提升 (`schema_pass_rate delta >= +0.05` 或 `avg_completeness delta >= +0.05`), 再讨论 R6-D+ LLM prompt 优化 / retry 策略升级 / token 控制 / `PROMPT_VERSIONS` 扩(决策点 D5 突破)
- **收尾文档**: `.harness/docs/round6-c-live-eval-result-and-next-steps.md`(本 round 收尾同步, 包含 R6-C.0 live 摘要 + R6-C.1+ C.2A+ C.2B+ C.3+ R6-D 实际改动清单 + 测试命令结果 + 新的指标分布 + 旧规划 vs 实际修正对照)

---

## 2. P2 — 中期(按用户场景触发,不主动开)

### ~~R3-K — 求职信(规则版)~~ 🗑️ 已删除 (2026-06-27)
- **删除原因**: 用户认为求职信在国内使用频率低,改为聚焦"简历排版做到更好"
- **历史记录**: R3-K 从 2026-06-26 暂缓(cancelled 后保留需求),到 2026-06-27 user 主动删除,不再列入候选
- **影响**: 无 — 从未实施,无 commit

### R3-M — 简历排版改进(精细打磨) ✅ R3-M.3 收尾完成(2026-06-27, 3 round 全部落地)
- **背景**:**2026-06-27 user 改需求** — 把原"简历导出多格式(docx → pdf/md/html)"改成"把简历排版做到更好"。参考 `amruthpillai/reactive-resume` (39.1k stars, 15 套差异化模板) 后,明确"排版改进"的核心是**模板差异化 + 视觉规范 + 用户可控**
- **拆分方案** (2026-06-27 user 同意按 R3-M.1 → R3-M.2 → R3-M.3 推进):
  - **R3-M.1** (短期,~350 行) ✅ 完成 — 方向 2 + 4:加 3 套新模板 + A4 规范 + 黑白打印友好
  - **R3-M.2** (中期,~430 行) ✅ 完成 — 方向 1 + 3:8 套模板细节打磨 + 可读性优化
  - **R3-M.3** (长期,~310 行) ✅ 完成 — bilingual_mode 激活 + academic_layout 详细模式(用户可定制排版的最小子集;完整 R3-M.3 reactive-resume 风格面板留 P2 后续)
- **当前状态** (2026-06-27): ✅ 3 round 全部 commit 落地(详见每个 sub-round entry);`test_generator_layouts.py` 从 16 case → 39 case;pytest 183 → 233
- **参考项目**:[reactive-resume](https://github.com/amruthpillai/reactive-resume) 启发的设计模式
  - **15 套模板** (我们 5 → 8 套差异化 ✅)
  - **可定制颜色 / 字体 / 间距** (留 P2 R3-M.4)
  - **A4 / Letter 双规格** (R3-M.1 上 A4 严格规范 ✅)
- **现状对比**:
  - 我们 5 套模板:`classic` / `single_column` / `two_column` / `minimal` / `technical` — 基础差异已有但视觉差异维度不够(主要是配色)
  - R3-M.1 加 3 套(academic / internet / bilingual) → 8 套 + A4 规范
- **未参考的 reactive-resume 高级特性**(留待未来 round):
  - PDF 客户端渲染 / JSON Resume 导入 / 拖拽排序 / 多语言 / 暗色模式

### R3-M.1 — 加 3 套新模板 + A4 排版规范 ✅ MVP 完成 (2026-06-27, commit `b521092`)
- **目标**: 5 套 → 8 套差异化模板 + 严格 A4 排版规范 + 黑白打印友好
- **新增 3 套模板**:
  1. **academic** (学术 CV) — 适合读博 / 出国申请, 字号 11pt, 行距 1.5, 边距 2.5cm 四边, 顶部姓名栏加粗 + 居中, 教育背景优先项目(本科→博士倒序), 项目 highlights 简化为学术风(去掉"项目经验"前缀, 直接列论文 / 项目名)
  2. **internet** (互联网简洁) — 字节阿里 style, 字号 10pt, 行距 1.2, 边距 1.5cm 四边, 单栏紧凑, 项目 highlights 简短有力(每条 ≤ 15 字), 技能组前置, header 联系方式用 emoji 图标
  3. **bilingual** (中英双语) — header 中英文姓名并列, 教育背景双语(学校中文 + 英文名), 项目标题中英双行(中文标题 + 英文副标题), 项目 highlights 中文为主关键术语括号英文
- **A4 排版规范**:
  - 所有 8 套模板 `margins_cm` 严格 A4(297mm × 210mm),上下 2.0cm 左右 1.8cm 默认 + 模板可调
  - 字号不小于 9pt(防止打印缩小看不清)
  - 行距 1.15-1.5(防止太挤或太散)
  - **黑白打印友好**:任何模板关闭 `use_color` 后,排版不崩(颜色作为装饰,内容靠粗体 / 字号区分)
- **后端改动** (主要):
  - `backend/core/generator.py` LAYOUT_CONFIG 加 3 项 + 必要时加专属 `_render_*` 函数
  - 大多数情况:复用 `_render_classic` alias 模式(只改 config,不改 renderer)
  - **academic** 可能需要专门 renderer(项目 highlights 简化逻辑)
  - **bilingual** 改动最大(header / education / project 标题双语, 需要 helper)
- **测试**:
  - `tests/test_generator_layouts.py` 加 3 个新模板的 dispatch 测试 + 视觉差异测试(参照现有 `TestLayoutDispatch` / `TestLayoutVisuals`)
  - A4 规范测试:`test_a4_margins_within_2_5cm`(所有模板 `margins_cm` 上下 ≤ 2.5cm / 左右 ≤ 2.5cm)
  - 黑白打印友好:`test_bw_print_friendly_when_color_disabled`(临时把 `use_color=False` 注入,验证 docx 仍生成有效)
- **依赖**: 无新增
- **工作量**: ~350 行(后端 config 3 项 ~80 行 + 渲染器扩展 ~100 行 + 测试 ~170 行)
- **前端改动**: **零** — `/api/resume/roles` 自动遍历 LAYOUT_CONFIG 暴露新模板,App.vue `v-for` 自动加 radio
- **价值**: 模板 5 → 8(覆盖学术 / 互联网 / 双语 3 大投递场景) + A4 规范闭环 + 黑白打印兜底
- **plan 文档**: `.harness/docs/round3-m-1-plan.md` (待写)

### R3-M.2 — 8 套模板细节打磨 + 可读性优化 ✅ 完成 (2026-06-27, commits `7541810` ~ `cbf76af`)
- **目标**: 8 套 LAYOUT_CONFIG 加 5 个可读性参数 + 6 个 helper 改造消费 + academic 专属 renderer 简化项目 highlights
- **5 个可读性参数**:`h1_size_ratio` / `h2_size_ratio` / `section_spacing_pt`(2 元组)/ `meta_spacing_pt` / `item_spacing_pt`
- **academic 专属 renderer**: 走 `_render_academic`,项目段简化(无 H2 项目名 / 无独立 period meta / 无 summary,直接列 highlights 为 bullets);教育保持前置(build_sections 已教育优先)
- **测试**:`TestLayoutConfigSchema` 5 + `TestHeadingHierarchy` 4 + `TestSectionSpacing` 2 + `TestBulletSpacing` 2 + `TestMetaSpacing` 1 + `TestAcademicRenderer` 5 + `TestReadabilityAcrossLayouts` 4 = **23 个新 case**(原计划 30,合并冗余)
- **bilingual_mode**: 本轮仍保留 dead code(注释明确"留 R3-M.3 激活"),`TestLayoutConfigSchema` 锁 schema 不判它
- **效果**: 213 passed(190 + 23),pre-push hook 全绿,8 套模板可读性 invariant(body>=9pt / meta>=8pt / 4 间距>=0 / line_spacing 范围)锁死
- **plan 文档**: `.harness/docs/round3-m-2-plan.md`

### R3-M.3 — bilingual 激活 + academic detailed 模式 ✅ 完成 (2026-06-27, commits `9f25f40` + `310cbe5` + `185c7f7` + `39c7d20`)
- **目标**: 激活 `bilingual_mode` flag(R3-M.1 留的 dead code)+ academic 加 `academic_layout: "compact" | "detailed"` 二级选项(恢复 R3-M.2 删掉的 H2 项目名 / period meta / summary)
- **实施路径**(4 step,每个独立 commit):
  1. `9f25f40` Step 1 — `LAYOUT_CONFIG['academic']` 加 `academic_layout: "compact"` 字段(默认 compact 保持 R3-M.2 行为)+ `_render_project_group_academic_detailed_to` 恢复 H2 + meta + summary + `_render_academic` 按 academic_layout 分支 dispatch;`TestAcademicLayout` 6 case
  2. `310cbe5` Step 2 — 3 个 bilingual section helper(`_render_bilingual_header_to` 14pt 英文姓名 italic / `_render_bilingual_education_to` 10pt 英文学校 italic / `_render_bilingual_project_group_to` 10pt 英文副标题 italic)+ `_render_bilingual` 入口 + `_LAYOUT_DISPATCH['bilingual']` 切到新入口;`TestBilingual*` 12 case
  3. `185c7f7` Step 3 — `build_sections` 透传 `_en` 字段(`name_en` / `school_en` / `major_en` / `title_en`,缺失给空字符串 graceful 降级);`TestMaterialsBilingualSchema` 2 case(真实 materials.json 无 _en 字段 bilingual 模板不抛异常 + build_sections schema 锁);6 role `_BASELINE_HASHES` 因 `_en` 字段 schema 扩展重算固化
  4. `39c7d20` Step 4 — 前端 App.vue academic 模板时显示二级单选(紧凑/详细),bilingual 模板 button 加 title tooltip 提示双语字段缺失降级;`PreviewRequest` / `GenerateRequest` 加 `academic_layout` 字段;`render_docx` 拷贝 LAYOUT_CONFIG 后覆盖(不污染全局)
- **测试**: **20 个新 pytest**(6 + 12 + 2),213 → **233 passed + 0 skipped**
- **效果**: 
  - bilingual 模板 真实数据(无 _en 字段)→ docx 单语言降级,不抛异常
  - bilingual 模板 补 _en 字段 → 完整双语(header 中英两行 / 教育有英文学校 / 项目有英文副标题)
  - academic 模板 默认 compact(R3-M.2 行为不变)→ 选 detailed 时恢复 H2 + meta + summary(适合 Research Statement)
- **已知限制**: 完整双语渲染要求用户补 `basics.name_en` / `education.school_en` / `education.major_en` / `projects[].title_en` 字段,前端 tooltip 已提示
- **plan 文档**: `.harness/docs/round3-m-3-plan.md`

### R3-P — Prompt 工程升级(few-shot + 显式 schema + retry) ✅ 完成 (2026-06-27, commit `d2a11d5`)
- **目标**: 把 LLM 改写从"零样本指令 + 隐式 schema 猜"升级到"few-shot 示例 + 显式 schema 验证 + 失败 retry",改写质量立竿见影
- **3 个核心改动**:
  1. **SYSTEM_PROMPT v2**: 加 2 个 few-shot 示例(基础改写 + jd_focus 改写)+ 7 条硬性约束(不编造 / 长度 20-50 字 / JSON schema 唯一 / jd_focus 4 条)
  2. **显式 JSON schema**: `{"rewritten": [{"index": i, "text": "..."}]}` 唯一规范(index 必唯一 + 0..N-1 + non-empty str)
  3. **失败 retry 1 次**: `_call_with_retry` 解析失败(strict_retry=True 更严格指令)再试一次;网络错误不 retry(避免 token 浪费);仍失败 → 降级原文
- **向后兼容**: 旧 schema(顶层 array / `{"rewritten": [str]}` / `{"bullets": [str]}`)保留兼容,16 个老 case 全绿
- **测试**: **19 个新 pytest**(3 TestSystemPromptV2 锁 few-shot + 硬性约束 / 5 TestNewSchemaExtraction 锁新 schema 验证 / 3 TestRetryOnInvalid 锁 retry 行为 / 8 TestSchemaValidationUnit 锁 _validate_* 单元)
- **效果**: 252 passed(233 + 19)+ 0 skipped,pre-push hook 全绿
- **plan 文档**: 无单独 plan(在 deliverable.md 直接说,因为改动小)
- **后续 P2 候选**: 解析 JD 用 LLM(hybrid 模式,A 方案 ~150 行)/ 输出更复杂结构(分段 / 元组 / 多语言)

### R3.5.1 — 扩 ground truth 样本 + 重跑阈值
- **背景**:R3.5 决策"10 份够用",但 label 分布有偏(0 份"别投")
- **范围**:补 10-20 份真实 JD + 各类 role 覆盖 + 确保 label 分布均衡(至少 2-3 份"别投")
- **触发条件**:R3.5+ match_score bug 修完后,想跑新一轮阈值调优
- **依赖**:R3.5+ 完成(match_score 必须先准)
- **工作量**:小(用户手工抄 ~20 份 + 跑 label_samples.py + 复核)
- **价值**:阈值调优可信度提升

### R4-C — Chat UI 组件(展示推理 trace) ⏸️ 留 P2 候补
- **背景**:R4-F/A/M MVP 完成后,backend trace 信息没有 UI 出口;R4-C 提供一个"高级 / Advanced"折叠面板展示 LLM 推理 step / 工具调用 / 输出
- **范围**:
  - `frontend/src/components/AgentChatPanel.vue` (~150 行) — 展示推理 trace
  - `App.vue` 顶部加"高级"折叠面板,默认收起
  - 3 个 trace 卡片(step-by-step),可滚动
- **触发条件**:
  - 用户说"启动 R4-C"
  - 或发现 backend trace 信息没出口,需要 UI 看
- **依赖**:R4-A `logs/agent_trace.log` 已生成;`TestAgentLoop` 已锁行为
- **工作量**:中(~200 行,需要 Vue + Element Plus 折叠面板 + 滚动列表)
- **价值**:用户能直观看到 LLM 推理链路,理解工具调用逻辑,debug 改写质量
- **不启动理由**:用户偏好"GUI 实施任务默认暂停"(2026-06-23 CT 重建后确定),等用户明确启动

---

## 3. P3 — 长期(按用户偏好暂停,不主动开)

### 云端部署 / 多端同步
- **背景**:本地单用户工具,AGENTS.md 已明确"不要加账号系统,不要暴露公网"
- **范围**:账号系统 + 数据库 + API 部署 + 鉴权(可能要迁 sqlite → postgres)+ CI/CD
- **触发条件**:你换电脑 / 多设备工作
- **工作量**:大(2-3 周,需评估云服务选型 + 隐私合规)
- **价值**:跨设备工作 / 远程访问

### GUI 实施任务
- **背景**:用户偏好"GUI 实施任务默认暂停"(2026-06-23 CT 重建后确定)
- **范围**:任何前端界面改动
- **触发条件**:你说"启动"才开(设计文档已够用时尤其如此)
- **价值**:避免无明确需求时的 UI 投资浪费

---

## 4. 维护类任务(随时可做)

### 定期清理
- `backend/output/` 真实 PII 产物 docx/json(每次跑完生成记得用 `mavis-trash` 清)— 2026-06-26 A 任务已清理过 6 份
- `scripts/_*.py` 临时脚本(跑完诊断即删)— 当前未发现

### 文档同步
- README.md 顶部"当前能力"表 + AGENTS.md 测试数 — 每 round commit 时由 developer 同步,orchestrator 收尾核对
- MEMORY.md 项目里程碑 / 待办表 / 改动记录 — 每 round 收尾由 orchestrator 同步

### 测试覆盖
- 每次新行为必须加 pytest(核心逻辑 / 边界 / 集成,thin wrapper 不写)— AGENTS.md 约定
- 每次 bugfix 必须加回归测试(覆盖每个 score 区间 / 死代码删除点)— AGENTS.md 约定
- 每轮独立验证 + 清理冗余测试文件 — 用户偏好,2026-06-23

---

## 5. 决策原则(用户偏好 + 项目约定)

按优先级递减:
1. **不要加账号系统 / 鉴权 / 公网部署**(本地单用户,AGENTS.md)
2. **不主动 git push**(commit 由用户决定何时推,AGENTS.md)
3. **GUI 实施任务默认暂停**(设计文档够用就停,2026-06-23)
4. **每轮独立验证 + 清理冗余测试**(用户偏好,2026-06-23)
5. **bugfix 必须加回归测试**(AGENTS.md)
6. **commit message 中文 + multi `-m` 别用字面 \n**(PowerShell 5.1 坑)
7. **新行为必须有 pytest 覆盖**(AGENTS.md)

---

## 6. 文档维护规则

**何时更新本文件**:
- 启动新 round → 在对应优先级段加 entry
- 完成 round → 把 entry 移到顶部"快照"(只留 commit hash + 1 行说明)
- 用户取消 / 暂缓 round → 把 entry 标 ⏸️ 移到对应"暂缓"段
- 用户说"暂停某任务" → 移到 P3 段

**更新方式**:orchestrator(本次会话主代理)在 round 收尾时改本文件 + MEMORY.md 同步指向本文件。

**历史档案**:已完成的 round 完整描述见 `.harness/memory/MEMORY.md` 项目里程碑段 + commit 历史。

---

## 7. 项目快速参考

| 类别 | 路径 |
|---|---|
| 后端入口 | `backend/main.py` |
| 核心域 | `backend/core/generator.py` + `backend/core/jd_parser.py` + `backend/core/llm_rewriter.py` + `backend/core/jd_ranker.py` + **R4 session** `backend/core/session.py` + **R5-A** `backend/core/agent_tools.py` + `backend/core/agent_workflow.py` + **`backend/core/evidence.py`** + **R5-E** `PROMPT_VERSIONS` 注册表 (4 key) + `_resolve_prompt_version` / `_select_system_prompt` 纯函数 + `_call_judge` / `_validate_judge_payload` judge helpers in `core/llm_rewriter.py` + **R6-A/R6-B interview** `backend/core/interview_prompts.py` (问题模板 + LLM slot prompt) + **`backend/core/interview_agent.py`** (状态机 + slot_meta provenance + 可选 LLM slot extraction + draft_card + `save_card`) + **`backend/core/interview_policy.py`** (deterministic confidence-aware policy) + **`backend/core/interview_verifier.py`** (draft fact verification) |
| API | `backend/api/resume.py` + `backend/api/jd.py` + **R6-A/R6-B** `backend/api/interview.py` (start/reply/draft/save-card 4 端点 + `enable_interview_llm` mode 开关 + extraction_summary / question_plan / verification optional 字段,400/422/404 错误码翻译) |
| 测试 | `backend/tests/` **948 pytest** (R6-G 收尾时活跃基线,2026-07-03 `D:\python3.11\python.exe -m pytest tests/ -q` 实测 948 passed in 117.94s;历史快照:R5-E 683 / R6-A Phase 2 723 / R6-A Phase 5 729 / R6-A Phase 4 739 / R6-B Phase 2 768 / R6-B Phase 3 809 / R6-B Phase 4 840 / R6-B Phase 5 863 / R6-C.1 877 / R6-C.2A 889 / R6-C.2B 909 / R6-C.3 930 / R6-E Phase 4 936 / R6-G 948;新增覆盖含 `test_interview_agent.py` slot_meta + policy integration + LLM observability + critical slot integration + `_do_answer` slot 对齐,`test_interview_api.py` mode switch + draft verification + LLM monkeypatch 路径改 `core.interview_llm` 命名空间,`test_interview_policy.py` confidence-aware policy + critical slot step 4.5,`test_interview_verifier.py` + **R6-G sentinel** (TestVerifierSentinelF2_1 5 case),`test_interview_eval.py` extractor compare + eval contract warnings + product_goal + LLM observability §4.7 + **R6-G stderr sanitize** (TestEvalStderrSanitizeF2_3 7 case),**新建 `test_interview_llm.py`** (1090 行, R6-D 平移 6 个 LLM class 共 35 case)) |
| 前端入口 | `frontend/src/App.vue` |
| 设计文档 | `.harness/docs/` (含 `round5-c-agent-capability-spec.md` 5 phase 已 ✅ + `round5-d-llm-eval-spec.md` 6 phase 已 ✅ + §12 手动 live eval 安全跑法 + **`round5-e-prompt-optimization-spec.md` 4 phase 已 ✅** + §11 Phase 4 收尾记录 + **`round6-b-interview-agent-intelligence-spec.md` R6-B 7 phase 已 ✅** + §16 收尾记录 + **`round6-c-live-eval-guide.md`** + **`round6-c-live-eval-result-and-next-steps.md`** (本 round 收尾同步, R6-C.0 live 摘要 + R6-C.1+ C.2A+ C.2B+ C.3+ R6-D 实际改动清单 + 测试命令结果 + 新的指标分布)) |
| 项目记忆 | `.harness/memory/MEMORY.md` |
| 本地隐私数据 | `简历帮知识库/` (`.gitignore`,不进库) |
| JD 库 | `AI岗位JD库_v4_intern.json` + 4 份报告 md + **`AI岗位JD库_prompt_ab报告.md`** (R5-E Phase 2 offline, 12 JD × 4 version × 1 run = 48 条样本, PII 自检 pass) |
| 扩库 / 打标 / 阈值脚本 | `scripts/build_v4.py` + `scripts/score_intern_match.py` + `scripts/label_samples.py` + `scripts/score_thresholds.py` + `scripts/match_golden_targets.py` + **`scripts/replay_agent_trace.py`** (R5-A Phase 2 + R5-C Phase 5: Fallback Summary 段 + --tools-used 交叉验证) + **`scripts/evaluate_agent_workflow.py`** (R5-A Phase 4 + R5-C Phase 1: fallback taxonomy 5 类 + R5-D Phase 1-4: `--mode` {offline/live/auto} + `--output` 自定义报告路径 + `_get_llm_eval_config` 4 字段 LLM 元信息 + `_extract_project_highlights` + `_summarize_rewrite_impact` 5 字段不含 bullet 原文 + `_percentile` 纯函数 + `p95/max_latency_ms` + 5 类 fallback_category_breakdown;**live 模式只做手动验收不进 pre-push**) + **`scripts/evaluate_prompt_versions.py`** (R5-E Phase 2+3: `--mode` {offline/live/auto} + `--versions` <csv> + `--runs-per-version` + `--output` + `--judge {off,on}` + `--judge-model`; 4 prompt version × 12 JD × 1 run 默认 + judge helper 三件套; **固定 FC=T + AW=T, 只变 prompt_version**; offline 模式 judge 强制 disabled 防误触 HTTP; **不挂 pre-push**, 跟 `evaluate_agent_workflow.py` 独立) + **`scripts/evaluate_interview_agent.py`** (R6-A Phase 5 + R6-B Phase 5: `--extractor {rules,llm,compare}`;offline compare 双组同跑且不发网络;5 类 fallback_category + Rules vs LLM-assisted 对照表;live 模式仍为手动验证入口,报告默认写 `backend/logs/interview_eval_report*.md`(.gitignore),不含 user_message / prompt / raw response / source_span / API key;**不挂 pre-push**) |

---

_最后更新:2026-07-03 R6-G 全部完成(`ae0e89b feat(round6-g): review-needed 整理 — verifier sentinel + envelope hygiene + stderr 脱敏`);R6-G 在 R6-F closeout docs-only patch 基础上落地延后 3 项 review-needed(0 P0/0 P1 真实 bug,全部 P2 范畴):**F-2.1 verifier sentinel**(`INTERVIEW_VERIFIER_FAIL_WARNING` 常量 + `verify_draft_card` 在 unsupported/low_confidence>0 时返 sentinel 提示 — 前端 UI 看到 verifier 崩了不会误判"全 verified 通过") / **F-2.2 llm envelope 重复 except hygiene**(`except (ValueError, OSError, Exception)` 冗余简化,行为不变) / **F-2.3 stderr 错误信息脱 `LLM_API_KEY` 字面量** / `sk-` 前缀 / `Bearer` 头(R5-D spec §6.4 严格口子);R6-F closeout 7 phase 全部落地:Phase 0 现场保护 / Phase 1 文档漂移审核(4 处文档漂移 F-1.1/1.2/1.3/1.4 docs-only 修复)/ Phase 2 静态风险扫描(5 项检查 × ~177 处命中,**0 P0 / 0 P1 bug**)/ Phase 3 同类 bug 深挖 / Phase 4 默认 rules + LLM fallback 审核 / Phase 5 Eval report 隐私审核 / Phase 6 前端 + API smoke(顺手修 1 个 P2 UI chip 噪音 F-6.1)/ Phase 7 全量验证;后端全量 **948 passed + 0 skipped** (实测 117.94s),**+12 pytest** = `TestVerifierSentinelF2_1` 5 + `TestEvalStderrSanitizeF2_3` 7,936 老测试零回退;前端 `vue-tsc --noEmit` 0 error + `npm run build` 成功;offline compare 报告(R6-C.3 复跑)隐私自检通过 + §4.7 渲染 `slot_source_breakdown.rules=60 llm=0 mixed=0 llm_rate=0.0 retries=0 fb_to_rules=0`;默认路径仍关闭智能抽取(`enable_interview_llm=False`)并保持 rules 行为兼容;真实 LLM eval 仍是手动流程,不进入 pre-push / 默认启动。下一轮 P1 候选:**R6-H live eval v2 决策门禁**(spec `.harness/docs/round6-h-live-eval-v2-decision-gate-spec.md` 已落档 draft):用户在 chat panel 跑 10+ 轮真实对话(覆盖 2 tech_metric + 2 communication + 2 process_metric + 2 domain_x + 2 自由选择)+ 配置 LLM key 后跑 `scripts/evaluate_interview_agent.py --mode live --extractor compare` 生成 v2 live 报告,按 4 项通过门槛 + 4 项强门槛 + 4 档决策表评分,决定 LLM slot 抽取是否值得继续投资 prompt / retry / token 优化;入库前必人工隐私检查(公开脱敏 materials.json / 公开 JD 库 / eval set 内置 / `LLM_BASE_URL` 不含内部路径)。_
