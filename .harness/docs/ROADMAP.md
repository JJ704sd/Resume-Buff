# 简历帮 — 未来规划 ROADMAP

> **可持续更新的项目规划文档**。每个 round 收尾时由 orchestrator 更新:已完成 → 移到顶部"快照";新启动 → 加进对应优先级段。
>
> **历史档案** 见 `.harness/memory/MEMORY.md`(项目里程碑 / 改动记录 / 已知陷阱)。
> **设计文档** 见 `.harness/docs/`(每 round 一份 `roundN-*.md`)。
> **本文件** 只描述未来:目标 + 触发条件 + 工作量估算,具体实施 spec 落 `.harness/docs/roundN-*.md`。

---

## 0. 当前项目快照(2026-06-27 R5-A closeout 收尾)

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
- **R5-A Agent 增强 4 phase + closeout**(对应 `.harness/docs/agent-enhancement-spec.md`):
  - **Phase 1** — Agent 编排层(`core/agent_workflow.py` 受控 Plan-and-Execute + `build_task_graph()` 确定性产任务图 LLM 不参与规划 + `run_agent_workflow()` 失败降级到旧路径)+ 工具注册表(`core/agent_tools.py` AGENT_TOOLS 4 个核心工具 + 统一 `execute_agent_tool()` 入口 + 隐私边界 `ToolResult` 不存 args/input 原文);`enable_agent_workflow` 字段默认 False,字节级一致
  - **Phase 2** — 结构化 JSONL trace(`core/logger.py` `log_agent_trace_jsonl` 写 `backend/logs/agent_trace.jsonl` + 11 字段稳定 schema + `request_id` 短 uuid 前缀 "r" + input_size/output_size 只算 bytes 不存原文 + 写入失败静默降级不影响主流程)+ 会话回放(`scripts/replay_agent_trace.py` argparse CLI 支持 `--request-id`/`--session-id`/`--path` 输出 markdown 摘要不输出原文敏感字段);旧 R4-A `agent_trace.log` 完全不动兼容共存
  - **Phase 3** — 轻量 RAG evidence(`core/evidence.py` 新增 `EvidenceSnippet` frozen dataclass + `build_evidence_snippets` 切 projects/skills/honors/certs 4 类 snippets + `retrieve_evidence` 复用 `KEYWORD_GROUPS` surface/normalized 做 lexical retrieval + 排序稳定 `(-confidence, source_type, source_id)` + 0 命中 snippet 过滤 + `_summarize_evidence_for_prompt` 单条 80 字符截断 + 总 2000 字符上限);**零向量数据库 / 零 embedding API / 零新依赖**(`SPEC §5.3`);`enable_agent_workflow=True` 时任务图插入 retrieve_evidence step(match_score 之后 retrieve_materials 之前),失败 `use_default` 降级不阻断主流程,evidence 透传到 `rewrite_highlights` + `SYSTEM_PROMPT` 加第 8 条硬性约束"只能基于 evidence 中存在的事实改写";evidence=None 字节级一致
  - **Phase 4** — Agent 离线评测报告(scripts/evaluate_agent_workflow.py 跑固定 eval set 12 JD = jd_samples 8 份非公告型 + v4_strong 4 份 × 4 组开关对照 (FC × AW 笛卡尔积);输出 AI岗位JD库_agent_eval报告.md 含 8 节;不挂 pre-push hook (SPEC §12 #3 默认手动脚本);不修改既有 match_score / score_thresholds.py / match_golden_targets.py / replay_agent_trace.py;无 LLM key 时全部走原文 fallback;PII 用 placeholder 白名单
  - **R5-A closeout** — 补齐 `agent_summary` / `enable_external_resume` 透传 / required args validation / `match_score.target_role` 工具 schema bugfix;PR #4 已合并到 `main`(merge `12dfcf1`)
- CI 验证(pre-push hook 自动 pytest + vue-tsc + build)
- **441 个 pytest 全绿 + 0 skipped**(283 R4 baseline + **20 R5-A Phase 1: 6 TestBuildTaskGraph + 2 TestAgentStepSchema + 6 TestRunAgentWorkflow + 3 TestBackwardCompatibility + 3 TestPrivacyGuarantee** + **32 R5-A Phase 2: 4 TestLogAgentTraceJsonlSchema + 3 TestLogAgentTraceJsonlTypes + 2 TestLogAgentTraceJsonlPrivacy + 3 TestLogAgentTraceJsonlRobustness + 9 TestWorkflowJsonlTrace + 3 TestReplayFilter + 3 TestReplayMarkdown + 3 TestReplayScript + 2 TestReplayRobustness** + **62 R5-A Phase 3: 9 TestBuildEvidenceSnippets + 5 TestKeywordHit + 6 TestComputeConfidence + 9 TestRetrieveEvidence + 4 TestSummarizeEvidenceForPrompt + 3 TestEvidenceToDictList + 4 TestAgentToolsIntegration + 4 TestMatchScoreRegression + 1 TestKeyWordGroupsReuse + 9 TestEvidencePhase3 + 8 TestEvidenceIntegration** + **11 R5-A Phase 4: 3 TestEvalSetLoading + 4 TestSingleEvaluation + 2 TestPiiScanner + 2 TestPrivacyGuarantee** + **14 R5-A closeout: 3 TestEnableExternalResumePassthrough + 7 TestAgentSummaryField + 4 TestAgentToolArgsValidation**)

**最近 7 个 commit** (`main` / `origin/main` 当前基线):
- `12dfcf1` Merge pull request #4 from JJ704sd/feat/round5-a-agent-phase1
- `ce57802` docs(round5-a closeout): closeout 文档同步 + 测试数 427 -> 441
- `b60a215` fix(round5-a closeout): agent_summary + enable_external_resume + tool args validation + match_score schema bugfix
- `9caf7bd` Merge pull request #3 from JJ704sd/feat/round5-a-agent-phase1
- `0c6b057` docs(round5-b): future spec + 架构审计文档
- `503005e` feat(round5-a phase4): Agent 离线评测报告 + 12 JD x 4 组开关对照
- `9eca73a` docs(round5-a phase3): 测试数 352 -> 416 + R5-A Phase 3 当前能力表 + ROADMAP/MEMORY 同步

---

## 1. P1 — 短期可做(下次 round 候选)

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
- **实施路径**(5 个核心 commit 顺序落地):
  1. `1679a22` **Phase 1** — Agent 编排层(`core/agent_workflow.py` 受控 Plan-and-Execute: `build_task_graph(has_jd, enable_function_calling, has_external_resume)` 确定性产任务图 LLM 不参与规划 + step 序号连续 + `AgentStep` frozen=True; `run_agent_workflow()` 失败时降级到 `build_sections` / `render_docx` 旧路径)+ 工具注册表(`core/agent_tools.py` AGENT_TOOLS 4 个核心工具 `parse_jd` / `match_score` / `evaluate_bullet_jd_match` / `rewrite_highlights` + 统一 `execute_agent_tool(tool_name, args, context)` 入口; 未知工具 → `TOOL_NOT_ALLOWED` 不抛 / TypeError → `TOOL_ARGS_INVALID` / 其他异常 → `TOOL_RUNTIME_ERROR`; `ToolResult` dataclass **不存 args / input 原文** 隐私边界); `PreviewRequest.enable_agent_workflow` / `GenerateRequest.enable_agent_workflow` 字段默认 False 字节级一致; **283 → 320 +20 pytest** (6 TestBuildTaskGraph + 2 TestAgentStepSchema + 6 TestRunAgentWorkflow + 3 TestBackwardCompatibility + 3 TestPrivacyGuarantee)
  2. `7c5af05` **Phase 2** — 结构化 JSONL trace(`core/logger.py` `JSONL_TRACE_FIELDS` 11 字段稳定 schema ts / request_id / session_id / workflow / step / tool / latency_ms / status / error_type / input_size / output_size; `log_agent_trace_jsonl(event)` 写 `backend/logs/agent_trace.jsonl`; `_estimate_input_size` / `_estimate_output_size` 用 `json.dumps(...).encode("utf-8")` 算 bytes 不存原文; 写入失败 IO / 磁盘满 / 编码错 logger 内部 try/except 静默降级不影响主流程; `generate_request_id()` 模块级函数生成短 uuid 前缀 "r") + 会话回放(`scripts/replay_agent_trace.py` argparse CLI `--request-id` / `--session-id` / `--path` 输出 markdown 摘要只渲染 7 列 step/tool/latency_ms/status/error_type/input_size/output_size 不输出原文); 每个 step 含本地步骤(intent / retrieve / aggregate / parse_external_resume)写一条 trace `status="skipped"`; 旧 R4-A `log_agent_trace` / `agent_trace.log` 签名/格式/路径完全不动兼容共存; **320 → 352 +32 pytest** (4 + 3 + 2 + 3 + 9 + 3 + 3 + 3 + 2); **安全审查无 P0/P1 阻塞** (JSONL 不存原文 PII / 写入失败不阻断 / replay 不输出敏感内容)
  3. `380906f` **Phase 3** — 轻量 RAG evidence(`core/evidence.py` 新增 420 行: `EvidenceSnippet` frozen dataclass 5 字段 source_type/source_id/text/matched_keywords/confidence; `build_evidence_snippets(materials, role)` 切 projects/skills/honors/certs 4 类 snippets role 缺时 fallback general; `retrieve_evidence(jd_keywords, role, materials, top_k=8, min_confidence=0.0)` 复用 `KEYWORD_GROUPS` surface/normalized 做 lexical retrieval + 排序稳定 `(-confidence, source_type, source_id)` + 0 命中 snippet 过滤; `_summarize_evidence_for_prompt` 单条 80 字符截断 + 总 2000 字符上限 + `(N more)` 截断标记; `evidence_to_dict_list` frozen dataclass 转 JSON 友好 dict list tuple→list round 3 位小数); `core/agent_tools.py` 注册 `retrieve_evidence` 工具(`ToolSpec.pii_risk=medium` 跟 match_score 同级; callable 包 lambda 走 `evidence_to_dict_list`); `core/agent_workflow.py` has_jd 时任务图插入 `retrieve_evidence` step(match_score 之后 retrieve_materials 之前; `step.required=False, fallback="use_default"`) + 显式 evidence 透传时 step.status="skipped" 跳过执行 + `enable_agent_workflow=True` 时 preview 返回值新增 `evidence_summary` 字段(dict list 供前端高级信息区); `core/llm_rewriter.py` `rewrite_highlights` 加 `evidence` kwarg(None 字节级一致) + `_build_request_payload` 加 `evidence_summary` kwarg + `SYSTEM_PROMPT` 加第 8 条硬性约束"只能基于 evidence 中存在的事实改写" + `EVIDENCE_CONSTRAINT_SUFFIX` 单独常量后缀; `core/generator.py` `build_sections` / `preview_resume` / `generate_resume_docx` 加 `evidence` kwarg 透传(零修改上层行为, None 旧路径字节级一致); **352 → 416 +62 pytest** (45 `test_evidence.py`: 9 TestBuildEvidenceSnippets + 5 TestKeywordHit + 6 TestComputeConfidence + 9 TestRetrieveEvidence + 4 TestSummarizeEvidenceForPrompt + 3 TestEvidenceToDictList + 4 TestAgentToolsIntegration + 4 TestMatchScoreRegression + 1 TestKeyWordGroupsReuse + 9 `test_agent_workflow.py` TestEvidencePhase3 + 8 `test_llm_rewriter.py` TestEvidenceIntegration); **零向量数据库 / 零 embedding API / 零新依赖** (spec §5.3); **安全审查无 P0/P1 阻塞** (trace 不含 evidence text 原文只记 bytes / evidence_summary 不含 PII materials 已脱敏 / 无新增外部网络调用 / write fail 静默降级不影响主流程)
  4. `503005e` **Phase 4** — Agent 离线评测报告(`scripts/evaluate_agent_workflow.py` 跑固定 eval set 12 JD × 4 组开关对照,输出 `AI岗位JD库_agent_eval报告.md`;无 LLM key 时原文 fallback 不报错,有真实 LLM key 时产出 schema pass / fallback / latency 指标;`backend/tests/test_agent_eval.py` +11 case;**416 → 427 pytest 全绿**;不挂 pre-push hook)
  5. `b60a215` **closeout** — 根据 `.planning/agent-architecture-audit/findings.md` 修复 `agent_summary` 响应、`enable_external_resume` 整链透传、required args validation 和 `match_score.target_role` 工具 schema bugfix;**427 → 441 pytest 全绿**;PR #4 merge `12dfcf1`
- **实施坑**(已写进 MEMORY.md / spec):
  1. Phase 1 测试数计算口径:R4 baseline 283 → Phase 1 320 (+37, 不是 +20 单纯加 Phase 1 测试; 累计计算包含基础测试调整) → Phase 2 352 (+32) → Phase 3 416 (+62),**实际测试增量需扣除测试文件内 fixture / helper 等带来的间接调整**
  2. Phase 3 evidence 任务图插入位置很关键:`match_score` 之后, `retrieve_materials` 之前 — 顺序不能颠倒(evidence 依赖 match_score 算出的 jd_keywords 透传)
  3. `evidence=None` 字节级一致是 R5-A Phase 3 的硬约束(老 352 测试零回退),实现路径上 `_build_request_payload` 在 evidence_summary 为 None 时不写字段 + system prompt 不追加 `EVIDENCE_CONSTRAINT_SUFFIX` 后缀,这两条缺一不可
  4. `_summarize_evidence_for_prompt` 单条 80 字符截断 + 总 2000 字符上限是为了避免 evidence 注入 LLM context 后超 token 上限;截断标记 `(N more)` 提示 LLM 还有更多 evidence 但当前 summary 已截断
- **效果**:**441 passed + 0 skipped**(含 R5-A Phase 4 +11、closeout +14);四阶段与 closeout 均零 P0/P1 安全阻塞;`agent_summary` / `evidence_summary` 都仅在 `enable_agent_workflow=True` 路径提供,默认 False 不污染老路径;`agent_trace.jsonl` 跟 `agent_trace.log` 并存,R4-A 老格式用户数据兼容;**默认 disable 全部新能力**(enable_agent_workflow=False + evidence=None + enable_function_calling=False + session_id=None),**零行为变更**,等用户明确启用才走新路径
- **spec 文档**: `.harness/docs/agent-enhancement-spec.md`(Phase 1+2+3+4+closeout 状态均已 ✅),`.harness/docs/round5-b-agent-capability-spec.md` 为下一轮入口
- **下一步**:Round 5-B 推荐先做 Phase 2A 工具 schema/context/effective tools,再做 eval request_id 关联;GUI 高级面板继续等用户明确启动

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
| 核心域 | `backend/core/generator.py` + `backend/core/jd_parser.py` + `backend/core/llm_rewriter.py` + `backend/core/jd_ranker.py` + **R4 session** `backend/core/session.py` + **R5-A** `backend/core/agent_tools.py` + `backend/core/agent_workflow.py` + **`backend/core/evidence.py`** |
| API | `backend/api/resume.py` + `backend/api/jd.py` |
| 测试 | `backend/tests/` **416 pytest** (283 R4 baseline + 20 R5-A Phase 1 + 32 R5-A Phase 2 + 62 R5-A Phase 3) |
| 前端入口 | `frontend/src/App.vue` |
| 设计文档 | `.harness/docs/` (含 `agent-enhancement-spec.md` R5-A spec) |
| 项目记忆 | `.harness/memory/MEMORY.md` |
| 本地隐私数据 | `简历帮知识库/` (`.gitignore`,不进库) |
| JD 库 | `AI岗位JD库_v4_intern.json` + 4 份报告 md |
| 扩库 / 打标 / 阈值脚本 | `scripts/build_v4.py` + `scripts/score_intern_match.py` + `scripts/label_samples.py` + `scripts/score_thresholds.py` + `scripts/match_golden_targets.py` + **`scripts/replay_agent_trace.py`** (R5-A Phase 2 会话回放 CLI) |

---

_最后更新:2026-06-27 R5-B.0 文档基线校准;R5-A Phase 1-4 + closeout 已通过 PR #4 合并到 main(merge `12dfcf1`,427 → 441 全绿含 14 closeout 新 pytest),由 orchestrator 维护;下一轮推荐启动 Round 5-B Phase 2A 工具契约/权限/真实数据流_
