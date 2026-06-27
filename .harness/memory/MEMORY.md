# 简历帮 — 团队共享记忆

> 跨 round 沉淀的项目级事实，orchestrator / developer / tester 都可读写。
> 私人化的偏好 / 个人数据**不放这里**，放个人 agent memory。

## 项目里程碑

- **2026-06-24**：Round 1 MVP 完成（commit `b2e5dbf`）— 4 项目 + 7 技能组 + 3 荣誉 + 1 证书，基础 docx 生成 + 强制预览
- **2026-06-24**：PII scrub + private backup 隔离（commit `cca78a3`）
- **2026-06-24**：README 隐私/部署边界声明（commit `4e3f1e9`）
- **2026-06-25**：Round 2 #1 — 启用全部 6 个 role 方向（commit `14fc0eb`）
- **2026-06-25**：README 当前能力表同步（commit `0467b29`）
- **2026-06-25**：Round 3-A 完成 — JD 加权 score + tier 分组（required/preferred/bonus）+ 业务阈值 banner（高≥80 / 中 60-79 / 低<60），**72 个 pytest 用例全绿**（53 jd_parser + 3 api_jd + 16 llm_rewriter）
- **2026-06-26**：Round 3-G（外部简历实时读取 + JD 评分联动）**cancelled** — 用户选完 scope 后主动叫停；worker 仍落地完整 MVP（**1467 行新增**），按 2026-06-26 hygiene 决策 **commit 到 `feat/r3g-resume-upload` 分支保留**（不 merge 不 push）。**2026-06-27 重启完成**：见下方 R3-G 完成条目（3 commit 落地 181 passed），走"功能移植"而非 git cherry-pick
- **2026-06-26**：清理 `backend/output/` 6 个含真实 PII 的产物（陈佳豪 docx ×3 + audit_test + test_audit + preview_audit.json）— A 任务收尾
- **2026-06-26**：Round 3-J 完成 — 简历模板库（5 套排版 `classic` / `single_column` / `two_column` / `minimal` / `technical`），**88 个 pytest 用例全绿**（53 jd_parser + 3 api_jd + 16 llm_rewriter + **16 generator_layouts**），前端 radio 选模板 + 后端 `_LAYOUT_DISPATCH` 渲染分发 + 日志记 template
- **2026-06-26**：Round 3-E 完成 — pre-push hook（`scripts/verify.ps1` 全量 pytest + vue-tsc + build + `scripts/hooks/pre-push` 自动挡 push + `scripts/install-hooks.ps1` 一键 setup），用 `git config core.hooksPath scripts/hooks` 把 hook 目录指向仓库内可版本控制位置，Windows only（PowerShell 5.1），跳过用 `git push --no-verify`
- **2026-06-26**：Round 3-I 完成 — JD-driven generation（让评分卡的"准"真正落到生成结果里）。**新 `core/jd_ranker.py` 纯规则排序**（命中数倒序 + tie 维持原顺序，3 函数 `rank_projects` / `rank_highlights` / `rank_skill_groups`）；`generator.py` / `preview_resume` / `generate_resume_docx` 加可选 `jd_context` / `jd_text` 关键字参数（默认 None → 字节级一致）；`llm_rewriter.py` system prompt 加 matched 识别 + missing 不编造 + tier 引导（jd_focus=None 时 user message schema 完全不变）；`api/resume.py` PreviewRequest / GenerateRequest 加 jd_text 字段 + 422 校验（>50k 字符）；前端 `App.vue` 加 jdAware 复选框 + section 命中关键词角标。**113 个 pytest 全绿**（88 baseline + 25 新增），6 role 字节级 baseline hash 在 test 里固化锁死 jd_context=None 路径。**coder 在 wrap-up 阶段被 15min cap kill 但实施 100% 完成 + commit 已就位**；owner 接手 merge + 文档同步（coder 在 deliverable.md 标好 merge commit message 模板）
- **2026-06-26**：R3-I 收尾 archive — commit `775e8be chore(round3#i): archive R3-I 设计文档 + v4 JD 库 + scripts`（8 files / 4384 行）。R3-I 期间/前后留下的工作产物入库：`.harness/docs/round3-i-plan.md`（设计文档）+ `AI岗位JD库_v4_intern.json`（v4 主库 82 份 JD）+ 2 份 md 报告（4 级实习筛选 + 黄金标的 match 实测）+ 4 个 scripts（`audit_workspace.py` 工程审计 / `build_v4.py` v4 入库 / `score_intern_match.py` 4 级打标 / `match_golden_targets.py` 黄金实测）。**bugfix**：`build_v4.py` 原引用已 trash 的 `AI岗位JD库_v3_intern.json`，改为从 v4 文件自包含读取 + idempotent 注释，再跑 `v3: 82 → v4: 82 (新增 0)` 验证通过
- **2026-06-26**：Round 3.5 完成 — 阈值调优（基于 8 份 ground truth 验证 `_classify_recommendation` 阈值 80/60）。**新增 `tests/test_threshold_tuning.py` 11 用例**（3 阈值常量锁死 + 6 ground truth 验证 + 2 meta-level 评估集/scale 校验），2 份 match_score 漏匹配 bug 已知 skip。**124 个 pytest 全绿**（113 baseline + 11 新增），2 skipped。新增 `scripts/label_samples.py`（AI 推断 label，按 `role_id_hint` 跑对应 role，60→10 次 match_score）+ `scripts/score_thresholds.py`（confusion matrix 报告）+ `AI岗位JD库_v4_intern_阈值调优报告.md`。`_meta.label_scale` 加第 4 项 `公告型`（公告型 JD 不参与阈值评估）。`jd_samples.json` 10 份（4 百运网 + 6 主库挑选），label 分布：推荐投 6 / 建议补充 2 / 公告型 2 / 别投 0。**当前阈值 80/60 准确率 6/8 = 75%（非 score=0 子集 100%）**；误判 2 份是 match_score 漏匹配 bug（`baiyun_2026_product` / `baiyun_2026_qa` score=0 但 label=建议补充/推荐投），归 R3.5+ 修
- **2026-06-27**：Round 3.5+ 完成 — 修 match_score 漏匹配 bug（commit `2889dd9`）。**实际根因有 2 个独立 bug**（R3.5 推测只是 1 个）：
  1. `_build_candidate_pool` 只查 role_skill_keys 对应 items → 跨 role 经验不计入池 → baiyun_qa 误判
  2. `KEYWORD_GROUPS` 缺 "AI" surface → 中英 JD 里高频 "AI" 字面识别不到 → baiyun_product 误判（parse_jd 命中 0 关键词，score 走全 unknown 兜底归零）
  **修法**：
  1. `_build_candidate_pool` 加 `include_borrowed=True` 参数（默认开）：池 = role 范围（强匹配）+ 全素材库扫描（borrowed）
  2. `match_score` 透传 `include_borrowed`，coverage 仍按 role 范围不变（保留"用户在当前 role 展示什么"语义），score/matched_keywords 反映 borrowed 命中
  3. `KEYWORD_GROUPS['skills']` 加 `("AI", "LLM", 0.5)`：跟 "大模型"/"LLM" 语义等价
  4. 抽出 `_scan_items_into_pool` 工具函数，role + borrowed 池扫描逻辑复用
  **回归测试**：`tests/test_jd_parser.py::TestMatchScoreBugfixR35Plus` 3 个用例锁死修复：
  - baiyun_qa 修后 score>0 + matched 含 Python/LLM
  - baiyun_product 修后 score>0 + matched 含 LLM（"AI" surface 生效）
  - include_borrowed=False 时严格 role 范围保留（旧行为可恢复，防回潮）
  un-skip `baiyun_2026_qa`（修后 score=100，ground truth label '推荐投' 一致 ✓）；保留 `baiyun_2026_product` skip（修后 score=100，但 ground truth label='建议补充' 期望 '中'，原 label 基于 score=0 反推，KEYWORD_GROUPS 暂无 PM 维度关键词，match_score 不能反映"补 PM 维度"语义，待 user 复核 label）。**128 个 pytest 全绿**（125 baseline + 3 R3.5+ bugfix），1 skipped。**8 份 eval 实跑准确率 7/8 = 88%**（R3.5 时 6/8 = 75%，+13pp），仅 baiyun_product 1 份待 label 复核。`AI岗位JD库_v4_黄金标的match报告.md` 重跑：3 份黄金 × 6 role 分数无变化（公告型 JD 不受 R3.5+ 影响）。**未修（留给 user / R3.5.1）**：`scripts/score_thresholds.py` 仍读 jd_samples.json frozen top_score，R3.5+ 修复要等 R3.5.1 改实跑模式才能在阈值调优报告里看到。设计文档落档 `.harness/docs/round3-5plus-plan.md`
- **2026-06-27**：Round 3.5+ (b) 完成 — 加 PM 维度 surface（commit `ed57e25`）。**上下文**：R3.5+ 修后 baiyun_product score=100 vs label='建议补充' (期望'中') 仍 gap；user 选 (b) 方案：加 PM 维度 surface，让 match_score 精确告诉 user 缺什么。**修法**：`KEYWORD_GROUPS['domains']` 加 4 个 PM 维度 surface（0.5 加分）：物流 / 工业工程 / 原型 / 流程图。**效果**：baiyun_2026_product 实跑 score=33, matched=['LLM'], missing=['原型', '工业工程', '流程图', '物流']；suggestions 精确给"补 PM 维度素材"指引（提到 物流/工业工程/原型）。**8 份 eval live 准确率保持 7/8 = 88%**（R3.5+ 同），baiyun_product 仍 skip（修后 score='低' vs label='中' 仍 gap，根因是 user 素材库实际缺 PM 经验，不是算法问题）。**3 个回归测试**：`tests/test_jd_parser.py::TestMatchScorePMDimensions` 锁死 baiyun_product missing 含 PM 维度 4 项 + suggestions 提到 PM 关键词 + KEYWORD_GROUPS 字典级断言（防 surface 被删回潮）。match_golden_targets 18 次匹配：黄金标的分数无变化（公告型/技术型 JD 不受 PM surface 影响）。**131 个 pytest 全绿**（128 baseline + 3 R3.5+ bugfix + 3 R3.5+ (b) pm_dimensions），1 skipped。**下一步**：baiyun_product 严格阈值校验留待 user 补 PM 素材 (or 改 label='低') 后再 un-skip；R3.5.1 仍待启动（`score_thresholds.py` 改实跑 + 扩 ground truth 样本）
- **2026-06-27**：Round 3.5.1 完成 — `score_thresholds.py` 改实跑 match_score（commit `44bd370`）。**背景**：R3.5 写的 score_thresholds.py 读 jd_samples.json 里的 frozen top_score（R3.5 时 AI 推断写死的 score），R3.5+ / R3.5+ (b) 修 match_score 后，frozen top_score 跟实跑结果不一致，报告失去参考价值。**修法**：`scripts/score_thresholds.py` 移除 `s['top_score']` 读取，改跑 `match_score(s['text'], s['role_id_hint'], materials)` 拿 score / coverage；role 沿用 role_id_hint（user 标定的期望 role），不再 6 role 取最高（简化，跟 R3.5 top_role 不直接可比但阈值评估本身不依赖 6 role 扫描）；sys.path 注入 backend/ 让 scripts/ 下脚本能 import core.*（跟 match_golden_targets.py 同样处理）；报告 markdown 顶部加 "R3.5.1 (实跑模式)" 标识 + "R3.5.1 vs R3.5 差异说明" 段。**效果**：**8 份 eval 实跑准确率 R3.5.1 时点 7/8 = 88% → R3.6.2 baiyun_product label 第三次复核改 '别投' 后变 8/8 = 100%**（R3.5 frozen 6/8 = 75%，+13pp/+25pp）；提升核心是 baiyun_2026_qa 从 frozen 0 → 实跑 100（修后 '高' 跟 label '推荐投' 一致）；报告含详细 coverage（skills/tools/domains 三维），比 R3.5 报告信息量更丰富；baiyun_2026_product 在 R3.6.2 后实跑 33 '低' 跟 label '别投' 一致（低对应别投阈值档）。**5 个回归测试**：`tests/test_score_thresholds.py::TestScoreThresholdsLive` 锁死（脚本能跑通 / 输出含 R3.5.1 标识 / 准确率 ≥ 6/8 baseline / 篡改 frozen 字段后实跑分数不变核心防回潮 / 报告 markdown 含标识）。**136 个 pytest 全绿**（131 baseline + 5 R3.5.1 score_thresholds_live），1 skipped。**未修**：baiyun_2026_product 严格阈值校验留待 user 补 PM 素材 (or 改 label='低') 后再 un-skip；frozen top_score / top_role / top_coverage 字段保留在 jd_samples.json 作为 R3.5 时点历史 snapshot，不删除以保留 ground truth。**R3.5.1 后续候选**：(1) 扩 ground truth 样本（至少补 2-3 份 "别投" 类别补齐 label 分布）；(2) 调优阈值（实跑准确率 R3.6.2 后 100%，远高于 85%，当前不调）
- **2026-06-27**：Round 3-G 完成 — 外部简历上传 + 简历视角评分（commits `b15dec5` + `d81c71e` + `c3b2807`）。**重启背景**：2026-06-26 cancelled 的 R3-G MVP 在 `feat/r3g-resume-upload` worktree `eb7e841` 保留 1467 行；user 2026-06-27 重启，明确"功能移植"而非 git cherry-pick（eb7e841 base 是 R3-I 之前的旧 base，但 worker 提前把改动"剥离"成纯新增 4 文件 + 修改 5 文件格式）。**实施路径**：(1) `git show eb7e841:<file>` 提取纯新增文件 → `python -c "subprocess.check_output + open('wb')"` 写到 worktree 避开 PowerShell `>` UTF-16 BOM 编码坑；(2) 5 个修改文件按当前 main 的实现手动合并（api/jd.py MatchRequest 加 external_resume_text + jd_parser.py match_score 加第 4 关键字参数 + api/resume.py POST /parse-external endpoint）；(3) Step 1 占位 `_build_resume_perspective` 返回 None，Step 2 实装归一化简历 + 扫 required keywords surface 命中 + need 扣 borrowed pool 去重（避免 false negative）；(4) Step 3 前端集成 `api/index.ts` 加 `ParsedResume` / `ResumePerspective` 类型 + `resumeApi.parseExternal(file)` + `jdApi.match(text, role, external_resume_text?)` + `App.vue` 加 `<ResumeUploader>` + externalResumeText ref + onScoreJd 透传 + 评分结果区加 have/need 卡片。**核心算法（`_build_resume_perspective`）**：归一化简历文本 + 对每个 required keyword 在 `KEYWORD_GROUPS` 找所有 surface（LLM → ["LLM", "大模型", "大语言模型", "AI"]）→ 任一 surface 在简历里出现 → have；否则 need_candidate；need = need_candidate - borrowed pool 命中（match_score 已算过的"素材库能补"集合，避免重复 false negative）。**测试**：从 worktree `eb7e841` 移植 `test_parse_external.py` 30 + `test_jd_match_ext.py` 14 个用例，跟 R3.5+ borrowed pool / R3.5+ (b) PM dimensions 全部兼容无重叠冲突。**181 个 pytest 全绿 + 0 skipped**（137 R3.6.2 baseline + 44 R3-G 移植）；**端到端冒烟**：上传 .txt 简历（218 字符/10 段）→ score=95 / recommendation='高' / have=10 关键词（Docker/Git/LLM/Linux/NLP/Prompt/PyTorch/Python/Transformer/评测）/ need=0（简历覆盖所有 JD 要求）；不传 / 空字符串 → `resume_perspective: None`（前端 v-if 隐藏）。**设计文档落档** `.harness/docs/round3-g-plan.md`（4 步走 plan）。**worktree 处理**：`feat/r3g-resume-upload` 分支不再需要，已 merge 全部 commit 到 main；worktree 与分支均已清理（`git worktree list` 与 `git branch -a` 在 2026-06-27 R4 closeout 阶段确认无残留；R3-G 分支同 R4 一样由 GitHub PR merge 自动删除，无需手动 `git branch -D` / `git push origin --delete`）
- **2026-06-27**：Round 4 Agent MVP 完成 — Function Calling + Agent Loop + Session 记忆（commits `a4c9156` + `ac90e13` + `c5ec652` + `ba536df`,PR #1 merge `8e2ce91`）。**背景**：用户对照 AI Agent R&D JD 识别出 4 个结构性缺口（Function Calling / Agent Loop / Session 记忆 / 可观测 trace）；MVP 优先打前 3 个 + trace 并入 R4-A，R4-C Chat UI 留 P2。**ROI 决策**（JD 信号 × 改动成本）：必做 R4-F + R4-A + R4-M，不做 R4-X（MCP 协议 ~400 行 SDK 风险大）/ R4-V（完整回放留 P2）。**实施 4 commit**：R4-F `llm_rewriter.py` 加 `TOOL_EVALUATE_SCHEMA` OpenAI tools schema + `evaluate_bullet_jd_match(bullet, jd_focus)` 工具函数（从 match_score 内部抽 surface 扫描逻辑导出）+ `rewrite_highlights` 加 `enable_function_calling: bool = False` 默认关（旧路径字节级一致）+ `_extract_rewritten` 加 tool_calls 解析分支 + Preview/Generate Request 透传（8 case 锁）→ R4-A `_call_with_agent_loop()` ReAct-style mini loop（`MAX_AGENT_STEPS=3` 硬上限 + 单步单工具 + 网络错误不入 loop）+ `logger.log_agent_trace()` 写 `logs/agent_trace.log` 跟 `generation.log` 分离（12 case 锁）→ R4-M `core/session.py` `_SESSIONS: dict[str, deque(maxlen=10)]` + 4 API（create / get / append / clear）+ `rewrite_highlights` 加 `session_id` 参数 + 隐私隔离（session 内容不写日志只写 id+步数）（11 case 锁）→ integration commit `rewrite_highlights` → `generator.build_sections` → `api/resume.py` 整链 session_id 透传（`session_id=None` 旧路径字节级一致）。**283 个 pytest 全绿 + 0 skipped**（252 R3-P baseline + 8 R4-F + 12 R4-A + 11 R4-M）。**踩坑**：(1) R4-M worker 第一轮 commit `81dd80c` stat 只 2 文件但 message 描述 5 文件 — classic "commit message 撒谎"，owner 看 `git show --stat` 发现 stat 与 message 不符，立即拦下；(2) cherry-pick R4-M 后 2 个 `TestSessionIntegration` fail（`rewrite_highlights` 没接 `session_id` 参数）— owner 手工补完剩下 4 文件改动 + 验证全绿；(3) `_call_with_agent_loop` 内部"解析失败"与"工具执行失败"要分别走不同降级路径，不能混在一起（解析失败重试原文 / 工具失败返回错误 message 让 LLM 重试）。**已写 AGENTS.md 锁点**：R4-F (Function Calling 协议接入) / R4-A (Agent Loop + 单工具约束 + trace 日志) / R4-M (Session 记忆 + 隐私隔离) / R4-M integration (session_id 整链透传)。**R4-C Chat UI 留 P2**（用户偏好 GUI 暂停）。**设计文档** `.harness/docs/round4-agent-mvp-plan.md`（237 行 ROI 决策 + 3 步实施 + 验收清单 + 风险回退）。**wrap-up 已闭环**：`feat/round4-agent-mvp` 分支由 GitHub PR #1 merge 时自动删除（`Automatically delete head branches` 默认行为），无需手动 `git branch -D` / `git push origin --delete`；closeout commit `60a18b8 docs(round4): ...` 已 `git push origin main` 成功，`git ls-remote --heads origin` 在 2026-06-27 R4 closeout 阶段确认只剩 main，远程 + 本地均无残留分支

- **2026-06-27**：Round 5-A Agent 增强 — 3 phase 全部落地（commits `1679a22` + `7c5af05` + `380906f`,PR #2 merge `66cf5ff`）。**背景**：R4 MVP 优先打 AI Agent R&D JD 结构性缺口；R5-A 在 R4 基础上补"可观测 + 可规划 + 可调用 + 可评测"工作流,设计文档 `.harness/docs/agent-enhancement-spec.md` 拆 4 phase,Phase 4 (Agent eval 报告) 需真实 LLM key 等用户明确启动再开。**实施 3 commit 顺序落地**：
  1. **`1679a22` Phase 1 — Agent 编排层 + 工具注册表**：`core/agent_workflow.py` 受控 Plan-and-Execute(`build_task_graph(has_jd, enable_function_calling, has_external_resume)` 确定性产任务图 LLM 不参与规划 + step 序号连续 + `AgentStep` frozen=True; `run_agent_workflow()` 失败时降级到 `build_sections` / `render_docx` 旧路径); `core/agent_tools.py` AGENT_TOOLS 4 个核心工具(`parse_jd` / `match_score` / `evaluate_bullet_jd_match` / `rewrite_highlights`) + 统一 `execute_agent_tool(tool_name, args, context)` 入口(未知工具 → `TOOL_NOT_ALLOWED` 不抛 / TypeError → `TOOL_ARGS_INVALID` / 其他异常 → `TOOL_RUNTIME_ERROR`); `ToolResult` dataclass **不存 args / input 原文** 隐私边界(`TestPrivacyGuarantee::test_tool_result_has_no_args_or_input_attrs` 锁); `PreviewRequest.enable_agent_workflow` / `GenerateRequest.enable_agent_workflow` 字段默认 False 字节级一致;**283 → 320 +20 pytest**(6 TestBuildTaskGraph + 2 TestAgentStepSchema + 6 TestRunAgentWorkflow + 3 TestBackwardCompatibility + 3 TestPrivacyGuarantee)
  2. **`7c5af05` Phase 2 — 结构化 JSONL trace + 会话回放**：`core/logger.py` `JSONL_TRACE_FIELDS` 11 字段稳定 schema(ts / request_id / session_id / workflow / step / tool / latency_ms / status / error_type / input_size / output_size) + `log_agent_trace_jsonl(event)` 写 `backend/logs/agent_trace.jsonl` + `_estimate_input_size` / `_estimate_output_size` 用 `json.dumps(...).encode("utf-8")` 算 bytes 不存原文 + 写入失败 IO/磁盘满/编码错 logger 内部 try/except 静默降级不影响主流程(spec §6.3) + `generate_request_id()` 模块级函数生成短 uuid 前缀 "r"; `core/agent_workflow.py` 每个 step 含本地步骤(intent / retrieve / aggregate / parse_external_resume)写一条 trace `status="skipped"`; `scripts/replay_agent_trace.py` argparse CLI 支持 `--request-id` / `--session-id` / `--path` 输出 markdown 摘要只渲染 7 列 step/tool/latency_ms/status/error_type/input_size/output_size 不输出原文; 旧 R4-A `log_agent_trace` / `agent_trace.log` 签名/格式/路径完全不动兼容共存;**320 → 352 +32 pytest**;**安全审查无 P0/P1 阻塞**(JSONL 不存原文 PII / 写入失败不阻断 / replay 不输出敏感内容)
  3. **`380906f` Phase 3 — 轻量 RAG evidence**：`core/evidence.py` 新增 420 行:`EvidenceSnippet` frozen dataclass 5 字段(source_type/source_id/text/matched_keywords/confidence) + `build_evidence_snippets(materials, role)` 切 projects/skills/honors/certs 4 类 snippets role 缺时 fallback general + `retrieve_evidence(jd_keywords, role, materials, top_k=8, min_confidence=0.0)` 复用 `KEYWORD_GROUPS` surface/normalized 做 lexical retrieval + 排序稳定 `(-confidence, source_type, source_id)` + 0 命中 snippet 过滤(不返噪声) + `_summarize_evidence_for_prompt` 单条 80 字符截断 + 总 2000 字符上限 + `(N more)` 截断标记 + `evidence_to_dict_list` frozen dataclass 转 JSON 友好 dict list(tuple→list, round 3 位小数); `core/agent_tools.py` 注册 `retrieve_evidence` 工具(`ToolSpec.pii_risk=medium` 跟 match_score 同级, callable 包 lambda 走 `evidence_to_dict_list`); `core/agent_workflow.py` has_jd=True 时任务图插入 `retrieve_evidence` step(match_score 之后, retrieve_materials 之前; `step.required=False, fallback="use_default"`) + 显式 evidence 透传时工具调用 `status="skipped"` 跳过执行 + `enable_agent_workflow=True` 时 preview 返回值新增 `evidence_summary` 字段(dict list, 供前端高级信息区); `core/llm_rewriter.py` `rewrite_highlights` 加 `evidence` kwarg(None 字节级一致) + `_build_request_payload` 加 `evidence_summary` kwarg + `SYSTEM_PROMPT` 加第 8 条硬性约束"只能基于 evidence 中存在的事实改写" + `EVIDENCE_CONSTRAINT_SUFFIX` 单独常量后缀(evidence 非空时追加); `core/generator.py` `build_sections` / `preview_resume` / `generate_resume_docx` 加 `evidence` kwarg 透传(零修改上层行为, None 旧路径字节级一致);**352 → 416 +62 pytest**(45 `test_evidence.py`: 9 TestBuildEvidenceSnippets + 5 TestKeywordHit + 6 TestComputeConfidence + 9 TestRetrieveEvidence + 4 TestSummarizeEvidenceForPrompt + 3 TestEvidenceToDictList + 4 TestAgentToolsIntegration + 4 TestMatchScoreRegression + 1 TestKeyWordGroupsReuse + 9 `test_agent_workflow.py` TestEvidencePhase3 + 8 `test_llm_rewriter.py` TestEvidenceIntegration);**零向量数据库 / 零 embedding API / 零新依赖**(spec §5.3);**安全审查无 P0/P1 阻塞**(trace 不含 evidence text 原文只记 bytes / evidence_summary 不含 PII materials 已脱敏 / 无新增外部网络调用 / write fail 静默降级不影响主流程)
- **踩坑**:
  1. Phase 1 隐私边界:`ToolResult` dataclass 不存 args / input 原文看似简单,但要明确"传进去的字段都不能留"(包括 input text / jd_text / external_resume_text 等敏感字段),不能只看 args — args 里嵌套的 dict 也要清。测试 `TestPrivacyGuarantee::test_tool_result_has_no_args_or_input_attrs` 锁死整个 ToolResult.__dict__ 不含 args/input 键
  2. Phase 2 trace 字段计算:`_estimate_input_size` / `_estimate_output_size` 用 `json.dumps(...).encode("utf-8")` 而非 `len(str(obj))`,后者会把 unicode 字符算 1 char 但 UTF-8 中文 3 bytes,导致 size 估算偏低。统一用 bytes 长度避免误判
  3. Phase 2 旧路径兼容:`log_agent_trace` 跟 `log_agent_trace_jsonl` 签名完全不同(`(session_id, step, tool_name, latency_ms, outcome)` vs `(event)` 11 字段 dict),两个函数都保留,R4-A 老调用代码不动,新代码只走 JSONL 路径。R5-A Phase 2 收尾时明确两个 trace 文件并存(`agent_trace.log` + `agent_trace.jsonl`),replay 脚本只读 JSONL
  4. Phase 3 evidence 任务图插入位置很关键:`match_score` 之后, `retrieve_materials` 之前 — 顺序不能颠倒(evidence 依赖 match_score 算出的 jd_keywords 透传到 retrieve_evidence)。`TestEvidencePhase3::test_task_graph_has_evidence_step_when_jd_present` 锁死 names.index 顺序
  5. Phase 3 `evidence=None` 字节级一致是 R5-A Phase 3 的硬约束(老 352 测试零回退),实现路径上 `_build_request_payload` 在 evidence_summary 为 None 时不写字段 + system prompt 不追加 `EVIDENCE_CONSTRAINT_SUFFIX` 后缀,这两条缺一不可。`TestEvidenceIntegration::test_evidence_none_payload_byte_identical_to_baseline` 锁死整条 payload 字节级一致
  6. Phase 3 `_summarize_evidence_for_prompt` 单条 80 字符截断 + 总 2000 字符上限是为了避免 evidence 注入 LLM context 后超 token 上限;截断标记 `(N more)` 提示 LLM 还有更多 evidence 但当前 summary 已截断。`(N more)` 写在 summary 末尾而不是开头,避免 LLM 先看截断提示跳过看 evidence
- **效果**：**416 passed + 0 skipped**(283 R4 baseline + 20 Phase 1 + 32 Phase 2 + 62 Phase 3);**R5-A 整体增量 +133 pytest**,三轮迭代零回退,字节级一致;`evidence_summary` 是新字段仅 `enable_agent_workflow=True` 时返回,默认 False 不污染老路径;`agent_trace.jsonl` 跟 `agent_trace.log` 并存,R4-A 老格式用户数据兼容;**默认 disable 全部新能力**(enable_agent_workflow=False + evidence=None + enable_function_calling=False + session_id=None),**零行为变更**,等用户明确启用才走新路径
- **已写 AGENTS.md 锁点**:R5-A Phase 1 (Agent 编排层 + 工具注册) / Phase 2 (结构化 JSONL trace + 会话回放) / Phase 3 (轻量 RAG evidence)
- **Phase 4 (Agent eval 报告) 留待**:需真实 LLM key 才能产出 schema pass rate / fallback rate 等指标,等用户明确启动再开

## 技术栈定型

- 后端：Python + FastAPI + python-docx + pymupdf + **pytest（2026-06-25 推翻先前"不引入"决策，见改动记录）**
- 前端：Vue 3 + TypeScript + Vite + Element Plus + axios
- 不引入：ESLint / Prettier / Vitest（**用户偏好**：保持栈精简，避免配置膨胀）
- 不加：账号系统 / 鉴权 / 公网部署（**用户偏好**：本地单用户）

## 角色清单（稳定）

| id | 显示名 | 风格 |
|---|---|---|
| `tech_metric` | 大模型技术度量 | 评测严谨 / 方法论导向 |
| `product` | AI 产品经理 | 用户视角 / 场景驱动 |
| `algorithm` | 医疗 AI 算法 | 模型复现 / 架构对比 |
| `data_annot` | 大模型数据标注 | 准确率导向 / SOP 严谨 |
| `test_qa` | AI 测试 / QA | 指标体系 / Badcase 归因 |
| `general` | 日常实习(通用) | 全面展示 / 不偏科 |

## 核心域约定（`core/generator.py`）

- **fallback 链**：`test_qa → tech_metric → general`（role 没匹配到项目时的兜底）
- `ROLE_CONFIG` 是核心配置，**改前必读全文 + README 顶部**
- `ENABLED_ROLES` 是当前启用的 role 列表
- `preview_resume()` 不写文件 / 不写日志（只浏览）
- `generate_resume_docx()` 写 `output/` + `logs/`

## 用户偏好（跨 round 适用）

- **中文优先**：所有用户可见文案 + 中文注释 + 中文错误信息
- **每轮独立验证 + 清理冗余测试**（用户明确要求，2026-06-23）
- **GUI 实施任务默认暂停**（2026-06-23，等需要时再启动）
- **长期 P3 任务**（opengate 真 MC / 多病例扩增 / GPU 加速 / 云端部署 / 多端同步）等用户明确指令
- **不主动 git push**，commit 由用户决定何时推

## 待办（按优先级）

| 优先级 | 项 | 状态 |
|---|---|---|
| P1 | Round 2 #2：JD 解析 / 匹配度评分 | ✅ 完成（R3-A 落地） |
| P1 | Round 2 #3：LLM 智能改写项目描述 | ✅ 完成（`core/llm_rewriter.py`，无 key 静默降级） |
| P1 | Round 3-A：JD 加权 score / tier / 业务阈值 banner | ✅ 完成（72 测试全绿，2026-06-25） |
| P2 | Round 3.5：阈值调优（基于 8 份 ground truth 验证，80/60 锁死 + 11 回归测试） | ✅ 完成（124 pytest 全绿 / 2 skipped match_score bug 待 R3.5+，2026-06-26） |
| P2 | Round 3-G：外部简历实时读取 + JD 评分联动 | ⏸️ Cancelled（2026-06-26；**MVP 1467 行 commit 在 `feat/r3g-resume-upload` 分支保留**） |
| P2 | Round 3-J：简历模板库（默认/单栏/双栏/简洁/技术） | ✅ 完成（5 套排版 + 16 测试，2026-06-26） |
| P2 | Round 3-E：CI 验证（pre-push hook） | ✅ 完成（2026-06-26） |
| P2 | Round 3-K：求职信（规则版，基于素材库 + role + JD） | ⏸️ 2026-06-26 暂缓：用户认为求职信在国内使用频率低，等真有人明确说"我要写求职信"再开 |
| P2 | Round 3-M：简历导出多格式（docx → pdf / md / html） | 待启动 |
| P2 | Round 4 Agent MVP：Function Calling + Agent Loop + Session 记忆 | ✅ 完成（PR #1 merge `8e2ce91`,283 pytest 全绿,2026-06-27） |
| P2 | Round 4-C：Agent Chat UI 组件 | ⏸️ 留 P2（用户偏好 GUI 暂停,设计文档够用） |
| P3 | 云端部署 / 多端同步 | 暂停（等用户明确启动） |

## 已知陷阱

- `App.vue` 的 `defaultActive` 是手写 list（如 `['education', 'project_group', 'skills']`），加新 section type 时记得同步
- `ROLE_DISPLAY` 在 `backend/api/resume.py` 顶部，与 `ROLE_CONFIG` 分离 — 加新 role 时**两处都要改**
- `materials.json._meta.source_files` 是历史简历文件名（脱敏版用了占位符），改 schema 时记得保持这个字段
- 前端 `axios` 报错信息走 `e?.response?.data?.detail ?? e?.message ?? '未知错误'` — 后端 HTTPException 的 `detail` 会原样展示，不要在那里塞 PII
- `backend/output/` 容易堆积含真实姓名的 docx / json — 每次跑完生成记得用 mavis-trash 清 PII 文件（参考 2026-06-26 A 任务）
- **R3-G**：PowerShell `git show commit:path > path` 会写 UTF-16 with BOM → pytest 报 "source code string cannot contain null bytes"（6959 个 null bytes）。**修法**：用 `python -c "import subprocess; data = subprocess.check_output(['git', 'show', 'commit:path']); open('path', 'wb').write(data)"` 走 Python 二进制管道
- **R3-G**：PowerShell `git commit -m` body 里 `**xx**:` 或 `xx 改动:` (行尾 `:`) 会被 shell 当 pathspec 解析吞字段，commit 失败但 `git add` 已 staged。**修法**：用 `git commit -F tmp_msg.txt` 走临时文件传多行 message，避开引号 + `-m` 拼接坑
- **R3-G**：`parse_resume_bytes(filename, raw_bytes) -> dict` 返回 `{filename, size_bytes, paragraphs: list, page_count?, note?}` dict 不是 list。`POST /parse-external` endpoint 必须 `text = "\n".join(p["text"] for p in parsed["paragraphs"])` 才能拼出全文，不能直接 `parsed` 整个传给前端
- **R3-G**：`_build_resume_perspective` 返回 None vs empty dict 区分语义 — `external_resume_text` 为空/None 时返回 None（前端 v-if 不展示），非空但 JD 0 关键词时返回 `{have_keywords: [], need_keywords: [], have_count: 0, need_count: 0}`（前端展示"简历覆盖所有"空状态）
- **R3-G**：need 扣 borrowed pool 是 R3.5+ 设计的核心去重 — 必须等 `match_score` 算出 pool 后才调 `_build_resume_perspective`，不能独立算，否则 "简历里没写但素材库能补" 的关键词会算 need（false negative）
- **R3-G**：移植 R3-G worktree 测试到当前 main 时，**必须**重新写断言而不是照搬 — R3.5+ borrowed pool 设计 + R3.5+ (b) PM dimensions 让 "Transformer/LLM/物流/工业工程" 等关键词被去重，第一版断言 assertIn 'Transformer', need 必 fail
- **R3-G**：功能移植 vs git cherry-pick — eb7e841 base 是 R3-I 之前的旧 base，但 eb7e841 自身只 +1467/-5（worker 提前"剥离"成纯新增 4 + 修改 5 的结构）；走 `git show :file` 提取 + 手动合并 5 个修改文件，比 cherry-pick 处理 ~30 文件冲突快很多
- **R3-G bug hunt (2026-06-27)**：写"简历里有某关键词"的测试时，**断言的关键词必须先在 JD 文本里"出现"**，否则不进 have/need（基本逻辑正确但容易踩坑）。例子：测试 emoji 归一化时，断言 `assert "LLM" in rp["have_keywords"]` 失败，因为 JD 文本只写 "需要 Python / PyTorch / Docker 经验"，LLM 不在 JD 要求里所以不进 have。**修法**：先在 JD 里列全要测的关键词，再写断言；不要靠"简历里出现 = 必然进 have"反推。**预防**：写测试时按 JD 文本 `parse_jd().skills ∪ tools ∪ domains` 列出 expected have 集合，比手工记忆更可靠
- **R3-G bug hunt (2026-06-27)**：写回归测试前先**核对现有测试覆盖**，避免 100% 重叠冗余。11 个 bug hunt 用例分析后只新增 2 个（emoji/特殊字符归一化 + `.exe` UnsupportedFormatError），9 个已被覆盖（gbk / 损坏 docx / 损坏 pdf / 超大 / external None/空/空白 / synonym_alias / need 扣 borrowed pool / JD 0 关键词 / 中文标点）。**冗余检测清单**：写新测试前先 grep 现有 test_*.py 看同函数/同 case 关键词是否已被覆盖（特别是核心算法已 lock 的实现）

## 改动记录（重要决策）

- **2026-06-24**：决定不引入 pytest — Round 1 以手测为主，pytest 配置成本高于价值
- **2026-06-24**：决定 frontend 不加 ESLint — Vite 默认够用，配 ESLint 收益小
- **2026-06-24**：决定 `materials.json` 公开脱敏 + 真实数据走 `_private_backup.json`（`.gitignore`）
- **2026-06-25**：决定 frontend 用 Element Plus 而不是自研组件 — 节省 UI 工作量
- **2026-06-25**：决定强制两段式（preview → generate）— 防止用户投错简历
- **2026-06-25**：**推翻"不引入 pytest"决策** — R3-A 加权 score / tier 涉及边界多（72 个测试），手测无法覆盖，引入 pytest（53 jd_parser + 3 api_jd + 16 llm_rewriter），仅后端，前端不引入 Vitest
- **2026-06-26**：R3-G scope 选定（"解析 + JD 评分联动"）后用户主动 cancel — 验证"GUI 实施任务默认暂停"偏好依然有效，后续 round 必须用户明确指令才启动
- **2026-06-26**：R3-J 决定 5 套排版（`classic` / `single_column` / `two_column` / `minimal` / `technical`）由 `LAYOUT_CONFIG` dict 统一驱动视觉差异（颜色/字号/行距/margin/header 对齐/skills 前缀/项目底纹/双栏 table），4 个 layout 复用 `_render_classic` 仅改 layout_cfg，`two_column` 走 table 结构差异 — 避免重复渲染逻辑，便于以后加新模板只需加一行 config
- **2026-06-26**：Hygiene 决策 — R3-G cancelled 后**保留分支而非 trash 代码**（用户偏好"commit 由用户决定何时推"≠"禁止 commit"；1467 行 MVP 含 pytest 覆盖有重启价值，留作未来 round 备料）；`feat/r3j-templates` 已 merge 后直接删；`scripts/` 目录本次核实时**不存在**，无需加 .gitignore（防过度约束）
- **2026-06-26**：R3-E 决定用 `core.hooksPath scripts/hooks` 把 hook 目录指向仓库内可版本控制位置 + PowerShell only（不写 .sh 减小维护面）+ 不在 verify 里跑 npm install（慢 + 网络不稳）—— 立工具链门槛，每个 round 自动受益
- **2026-06-26**：R3-I archive 阶段发现 `scripts/build_v4.py` 死引用 — 原代码 `SRC = Path(r"D:\简历帮\AI岗位JD库_v3_intern.json")` 读已 trash 的 v3 文件，将来任何时候再跑都会 `FileNotFoundError`。修复方案：把 SRC 改成 `DST`（即 v4 文件自包含），加幂等注释说明 v3 历史版本已 trash，将来扩 v5 直接在 `NEW_JDS` 末尾追加新 JD；验证 `v3: 82 → v4: 82 (新增 0)` 通过。**教训**：每次 archive commit 前要跑一次 `git grep "<已删除的资源>"` 扫死引用，commit message body 写清修复路径（触发条件 / 改的文件 / 回归验证），不靠"测试通过"就以为 OK
- **2026-06-26**：MEMORY 描述修正 — R3-E 收尾时记"`scripts/` 目录本次核实时**不存在**"，但 R3-I archive 实际把 `scripts/audit_workspace.py` + 3 个 v4 库脚本（build_v4 / score_intern_match / match_golden_targets）一并入库；现在 `scripts/` 是 R3-K / 投递阶段的活目录（有 v4 扩库 + 打标 + match_score 实测 + 工程审计 4 类脚本），不再是"不存在"。`.gitignore` 不需要新增 — 仓库根的 `scripts/` 始终 tracked
- **2026-06-26**：R3.5 决策 — **不调阈值**。基于 8 份 ground truth（排除 2 份公告型）跑 confusion matrix，当前 80/60 准确率 75%（6/8），**扣分全是 match_score 漏匹配 bug**（`baiyun_2026_product` / `baiyun_2026_qa` score=0 但 label=建议补充/推荐投），**非 score=0 子集 100%**。**调阈值没用**：降 mid（60→50）score=0 仍"低"；降 high（80→70）score=67 会变"高"引入 false positive。唯一修法是修 match_score，归 R3.5+。**接受 75% 准确率**，加 `tests/test_threshold_tuning.py` 锁死阈值（3 边界常量 + 6 ground truth + 2 meta），2 bug 已知 skip，文档化后等 R3.5+ 修 match_score 后再跑 Phase 3.5 看是否要调阈值。**教训**：阈值调优前必须区分"阈值不准"vs"上游算法漏匹配"——混淆会导致永远调不出好阈值（降阈值救不了 score=0，降阈值救不了 false positive，方向错）
- **2026-06-26**：R3.5 label 标注策略 — **AI 推断 + user 复核**，不是 user 手工标。10 份 JD label 由 `scripts/label_samples.py` 基于 `role_id_hint` 跑对应 role（不是全 6 role 找最高分，避免 product JD 被 tech_metric 100 分抢）推断 + `label_note` 含 `top_score / coverage / 命中 / 缺失关键词`，用户快速复核 4 份可疑（公告型 2 份从"推荐投"/"别投"改"公告型"、product/qa 2 份 false negative 改"建议补充"/"推荐投"）。**label_scale 加第 4 项 `公告型`**（公告型 JD 不参与阈值评估，因为 match_score 不适用）。`jd_samples.json` 本地 `.gitignore` 不入库，ground truth 永远跟用户素材库版本走；测试 `jd_samples.json` 不存在时 pytest skip 不破 CI
- **2026-06-27**：R3-G 重启决策 — **功能移植**而非 git cherry-pick。`feat/r3g-resume-upload` worktree `eb7e841` 是 1467 行 MVP（2026-06-26 cancelled 后保留），但 base 是 R3-I 之前的旧 base（与当前 main 脱节 30+ commits）。**不走 cherry-pick 原因**：手动合并冲突成本高 + 容易引入 main 已经修过的 bug（如 R3.5+ borrowed pool 漏匹配）；**走功能移植**：用 `git show eb7e841:<file>` 提取 4 个纯新增文件 + 5 个修改文件按当前 main 实现手动合并 + 写新测试。**4 步走**：Step 1 后端端点 + 透传字段（占位 `_build_resume_perspective`）→ Step 2 实装核心逻辑 + 移植 R3-G 测试 → Step 3 前端集成 → Step 4 文档同步。**关键经验**：(1) 占位函数让 Step 1 独立可验证 (137 passed)；(2) Step 2 直接复用 main 已算好的 `pool` 不重算（need 扣 pool 去重逻辑完美适配 R3.5+ borrowed pool 设计）；(3) 移植 44 个测试无冗余（30 + 14 不重叠）；(4) Step 3 避开 `**xx**:` pathspec 坑 + 上传简历路径
- **2026-06-27**：R3-G `resume_perspective` 设计 — **同义词 alias 算法 + 借调池去重**。**算法**：(1) 归一化简历文本（小写 + 去标点）；(2) 对每个 required keyword 找 `KEYWORD_GROUPS` 所有 surface（例：LLM → ["LLM", "大模型", "大语言模型", "AI"]）；(3) 任一 surface 在归一化简历里出现 → have；否则 → need_candidate；(4) need = need_candidate - borrowed pool 命中（`match_score` 已经算过的"素材库能补"集合，避免重复 false negative）。**优势**：跟 R3.5+ borrowed pool + R3.5+ (b) PM dimensions 完美兼容，不破坏现有 match_score 算法。**返回 None vs empty dict 区分语义**：外部简历文本为空时返回 None（前端 v-if 隐藏 + 不影响原有评分展示），非空但 JD 0 关键词时返回空 dict（前端展示"简历覆盖所有"空状态）
- **2026-06-26**：R3.5 push 前 bugfix — `scripts/label_samples.py` 非 idempotent，二次跑会重置 user 复核的 4 份 label。**修复 commit `1bac68e fix(round3#5): label_samples.py idempotent + --force flag`**：(1) 加 `--force` 命令行 flag（默认 False）；(2) 只对 `label=None` 的样本推断 label，保留 user 复核；(3) 删除冗余 print 行（每条 sample 只打一次）。验证：124 pytest 全绿 / 2 skipped，二次跑每份都标 `[保留]`。**教训**：写"写文件"脚本时第一件事是 idempotent — 增量更新（不动已有值）vs 全量覆盖（重写所有值）必须显式选，否则破坏用户手工修改
