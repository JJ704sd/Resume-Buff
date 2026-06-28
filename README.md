# 简历帮 (JianLiBang)

> 个人简历助手 — 一份素材库,一键生成多份针对性简历。

> 🔒 **隐私状态(公开仓库版)**:`backend/data/materials.json` 已是**脱敏示例版**(姓名/手机/邮箱/学校/公司已替换为占位符,技术亮点保留作 demo)。本地真实数据在 `backend/data/_private_backup.json`(被 `.gitignore` 忽略,不入库)。
> - clone 后想用自己的数据:`cp backend/data/_private_backup.json backend/data/materials.json`,然后编辑内容
>
> ⚠️ **部署边界**:本工具**仅设计为本地单用户使用** — `PUT /api/materials` 无鉴权,不能直接暴露公网。多人协作 / 多端同步 / 云端部署属长期 P3 任务,**默认不做**,等用户明确启动再开。

## 这是什么 / 不是什么

### ✅ 简历帮**做**的事
- 把分散在 10+ 份原简历里的**事实**去重合并,沉淀为结构化**素材库**(`backend/data/materials.json`)
- 根据**目标岗位方向**,从素材库挑选 facts + 调整措辞,生成定制版 `.docx` 简历
- 生成前**强制预览**(人工确认),人 review 每个模块内容后再下载,避免投错

### ❌ 简历帮**不做**的事
- ❌ **不**自动投递(不会去 BOSS / 拉勾 / 牛客上代投)
- ❌ **不**追踪 HR 进度、面试状态
- ❌ **不**做模拟面试、八股训练
- ❌ **不**爬取招聘网站,不联网抓 JD(用户粘贴 JD 进来即可)
- ❌ **不**做账号/多用户系统(本地单用户工具)
- ❌ **不**替代人做最终决策(预览后必须人点确认才下载)

> 边界画在「素材库管理 + 简历文件生成」,再往外就是越权。

---

## Round 4 Agent MVP 当前能力(2026-06-27)

| 功能 | 状态 |
|---|---|
| 素材库(4 项目 + 7 技能组 + 3 荣誉 + 1 证书) | ✅ |
| 6 个岗位方向(度量/产品/算法/标注/测试/通用) | ✅ |
| 生成预览(按模块)+ fallback 链(test_qa → tech_metric → general) | ✅ |
| 本地日志 `backend/logs/generation.log` | ✅ |
| JD 解析(关键词 + 经验 + 学历 + **tier 分组**) + 加权 0-100 匹配度评分 + **业务阈值 banner (高≥80 / 中 60-79 / 低<60)** | ✅ Round 2 #2 + R3-A |
| LLM 智能改写项目描述(无 key 静默降级,OpenAI 兼容 HTTP) | ✅ Round 2 #3 |
| **R3-P Prompt 工程升级**(`SYSTEM_PROMPT` v2 加 2 个 few-shot 示例(基础 + jd_focus)+ 显式 JSON schema `{rewritten: [{index, text}]}` 唯一规范 + 失败 retry 1 次(更严格指令) + 旧 schema 保留兼容;`TestSystemPromptV2` 3 + `TestNewSchemaExtraction` 5 + `TestRetryOnInvalid` 3 + `TestSchemaValidationUnit` 8 = 19 case 锁死;`is_llm_enabled` 静默降级,无 key 走原文不抛) | ✅ Round 3-P |
| **简历模板库**(5 套排版:`classic` / `single_column` / `two_column` / `minimal` / `technical`,前端 radio 切换 + 后端 layout dispatcher + docx 视觉差异) | ✅ Round 3 J |
| **CI 验证(pre-push hook 自动 pytest + vue-tsc + build)** | ✅ Round 3 E |
| **JD-driven 生成**(粘贴 JD 后:项目/highlight/skill 按命中数倒序 + 前端每 section 命中关键词角标 + LLM 改写 prompt 注入 matched/missing 关键词 + 不传 JD 时字节级一致) | ✅ Round 3 I |
| **R3.5 阈值调优**(基于 8 份 ground truth 验证,80/60 阈值锁死 + 11 回归测试防回潮) | ✅ Round 3.5 |
| **R3.5+ 修 match_score 漏匹配 bug**(borrowed pool 跨 role 经验自动纳入 + `KEYWORD_GROUPS` 加 'AI' surface;3 个 bugfix 回归测试;baiyun_qa 修后 score=100 ✓,baiyun_product 修后 score=100 但 label 待 user 复核) | ✅ Round 3.5+ |
| **R3.5+ (b) PM 维度 surface**(`KEYWORD_GROUPS['domains']` 加 物流/工业工程/原型/流程图 4 个 surface;baiyun_product 修后 score=33 + missing/suggestions 精确给"补 PM 维度"指引;3 个 pm_dimensions 回归测试) | ✅ Round 3.5+ (b) |
| **R3.5.1 score_thresholds 实跑模式**(`scripts/score_thresholds.py` 改实跑 `match_score(text, role_id_hint, materials)`, 不读 jd_samples.json frozen top_score;8 份 eval 实跑准确率 R3.5.1 时点 7/8 = 88% → **R3.6.2 baiyun_product label 第三次复核改 '别投' 后变 8/8 = 100%**;5 个 score_thresholds_live 回归测试含篡改 frozen 字段验证实跑模式锁死) | ✅ Round 3.5.1 |
| **R3-G 外部简历上传 + 简历视角评分**(`POST /api/resume/parse-external` 解析 .docx/.pdf/.txt + `match_score` 增加 `external_resume_text` 参数 + 返回 `resume_perspective` 块 {have/need_keywords, have/need_count} + 前端 `<ResumeUploader>` el-upload drag + App.vue 评分结果区加 have/need 卡片 + 扣除素材库能补的避免 false negative) | ✅ Round 3-G |
| **学术 CV 模板**(academic, 11pt / 1.5 行距 / 2.5cm 边距, 适合读博 / 出国申请) | ✅ Round 3-M.1 |
| **互联网简洁模板**(internet, 10pt / 1.2 行距 / 1.5cm 边距 / ▸ 前缀, 字节阿里 style) | ✅ Round 3-M.1 |
| **中英双语模板**(bilingual, 中英 header / 教育 / 项目副标题, 适合外企 / 海外岗位) | ✅ Round 3-M.1 |
| **R3-M.2 模板可读性参数化**(`LAYOUT_CONFIG` 8 套加 h1_size_ratio / h2_size_ratio / section_spacing_pt / meta_spacing_pt / item_spacing_pt 5 个参数 + 6 个 helper 改造消费;academic 专属 `_render_academic` 简化项目 highlights(无 H2 项目名 / 无独立 period meta / 无 summary)+ 教育保持前置;模板差异化:academic 1.15/段宽 / internet H2=1.0/段紧凑 / bilingual 1.18+item=2;`TestReadabilityAcrossLayouts` 锁 body>=9pt / meta>=8pt / 4 间距>=0 / line_spacing [1.15, 1.5];bilingual_mode flag 保留 dead code 留 R3-M.3 激活双语 header / 教育 / 项目副标题) | ✅ Round 3-M.2 |
| **R3-M.3 bilingual 激活 + academic detailed**(`_LAYOUT_DISPATCH['bilingual']` 切到 `_render_bilingual` + 3 个 bilingual section helper(`_render_bilingual_header_to` / `_render_bilingual_education_to` / `_render_bilingual_project_group_to`);`_en` 字段(`basics.name_en` / `education.school_en` / `education.major_en` / `projects[].title_en`)build_sections 透传,缺失时 graceful 降级到单语言(中文);academic 加 `academic_layout: 'compact' \| 'detailed'` 二级选项,detailed 走 `_render_project_group_academic_detailed_to` 恢复 H2 项目名 + period meta + summary(适合 Research Statement);前端 App.vue academic 模板时显示二级单选(紧凑/详细),bilingual 模板 button 加 title tooltip 提示双语字段缺失降级;`PreviewRequest` / `GenerateRequest` 加 `academic_layout` 字段;`TestAcademicLayout` 6 + `TestBilingual*` 12 + `TestMaterialsBilingualSchema` 2 = **20 个新 pytest**;`render_docx` 拷贝 LAYOUT_CONFIG 后覆盖 `academic_layout` 不污染全局 schema;6 role `_BASELINE_HASHES` 因 `_en` 字段 schema 扩展重算固化) | ✅ Round 3-M.3 |
| **R4-F Function Calling 协议接入**(`llm_rewriter.py` 加 `TOOL_EVALUATE_SCHEMA` OpenAI function calling schema,`evaluate_bullet_jd_match(bullet, jd_focus)` 从 `match_score` 内部抽 surface 扫描逻辑导出;`rewrite_highlights` 加 `enable_function_calling: bool = False` 参数(默认关,旧路径字节级一致);`jd_focus is not None` 时挂 `tools` 字段,空时走老路径不开新边界;`PreviewRequest` / `GenerateRequest` 加同名字段透传;`TestFunctionCalling` 5 case 锁 tools 字段结构 / 默认不挂 / jd_focus=None 不挂 / 启用挂载 / tool_calls 解析失败降级原文 + `TestEvaluateBulletJdMatch` 3 case 锁新工具函数 surface 命中 + missing 列表) | ✅ Round 4-F |
| **R4-A Agent Loop(max_step=3 + 单工具约束 + trace 日志)**(`_call_with_agent_loop()` ReAct-style mini loop 包装 `_call_with_retry`,`MAX_AGENT_STEPS=3` 硬上限防死循环 + 单步单工具防 token 爆 + 网络错误不进入 loop(直接降级不浪费 token);`enable_function_calling=False` 时完全不走 loop(字节级一致,旧测试不破);`logger.log_agent_trace(session_id, step, tool_name, latency_ms, outcome)` 写 `logs/agent_trace.log` 跟 `generation.log` 分离;`TestAgentLoop` 9 case 锁 max_step 上限 / 工具成功路径 / 工具失败回退 / 连续 3 步仍无 output 降级 / trace 格式 / 网络错误不入 loop / max_step=0 走老路径 / 单步单工具约束 / execute_tool_call known+unknown 工具 + `TestLogAgentTrace` 3 case 锁 trace 写入格式 + 文件创建 + 字段完整性) | ✅ Round 4-A |
| **R4-M Session 记忆(进程内 deque 上限 10 + 隐私隔离)**(`core/session.py` 新建 `_SESSIONS: dict[str, deque(maxlen=10)]` + 4 API(create_session / get_messages / append_message / clear_session);`rewrite_highlights` 加 `session_id: str | None = None` 参数,挂上后从 session 拉历史 messages 拼到 LLM messages 头部;`PreviewRequest` / `GenerateRequest` 加 `session_id` 字段透传;**隐私隔离** — `session_id` 由前端生成(不存 PII),后端不写 session 内容到日志(只写 session_id + 步数);MVP 不持久化(进程退出即丢),不做 TTL;`TestSessionAPI` 8 case 锁 create/append/get/clear/上限 10 FIFO/不存在 session_id 静默忽略/空 session_id 静默忽略/唯一性 + `TestSessionIntegration` 3 case 锁 session_id 拼接到 LLM messages / session=None 不拼接 / 多轮同 session 累积) | ✅ Round 4-M |
| **R4-M integration: session_id 透传整链**(`rewrite_highlights` 接收 `session_id` 后从 `session.get_messages()` 拉历史拼到 LLM messages 头部,`generator.build_sections` 透传 `session_id` 给 generator,`api/resume.py` Preview/Generate Request 加字段后 endpoint 透传到 core 层;旧路径(`session_id=None`)字节级一致,`TestSessionIntegration` + `TestSessionAPI` 全绿) | ✅ Round 4-M integration |
| **R5-A Phase 1 Agent 编排层 + 工具注册表**(`core/agent_tools.py` AGENT_TOOLS 4 个核心 + 统一 `execute_agent_tool()` 入口(allowlist/错误分类/隐私边界);`core/agent_workflow.py` `build_task_graph()` 确定性产任务图(LLM 不参与规划)+ `run_agent_workflow()` 失败时降级旧路径;`PreviewRequest.enable_agent_workflow` / `GenerateRequest.enable_agent_workflow` 字段,默认 False 字节级一致;`AgentStep` 不存原文 PII;`ToolResult` 不存 args/input 原文;`generator.preview_resume/generate_resume_docx` 加 `enable_agent_workflow` kwarg 默认 False;`enable_agent_workflow=False` 字节级一致,283 老测试零回退;TestBuildTaskGraph 6 + TestAgentStepSchema 2 + TestRunAgentWorkflow 6 + TestBackwardCompatibility 3 + TestPrivacyGuarantee 3 = 20 新 pytest) | ✅ Round 5-A Phase 1 |
| **R5-A Phase 2 结构化 JSONL trace + 会话回放**(`core/logger.py` 加 `log_agent_trace_jsonl(event)` 写 `backend/logs/agent_trace.jsonl`,11 字段稳定 schema(ts / request_id / session_id / workflow / step / tool / latency_ms / status / error_type / input_size / output_size),input_size/output_size 只算 bytes 不存原文;`core/agent_workflow.py` 每次 workflow 生成 request_id(短 uuid,前缀 "r"),每个 step 含本地步骤写一条 JSONL trace,`status=skipped` 表示本地步骤;写入失败(IO/磁盘满/编码错)→ 静默降级不影响 preview/generate 主流程(spec §6.3);`scripts/replay_agent_trace.py` argparse CLI 支持 `--request-id` / `--session-id` / `--path`,输出 markdown 摘要不输出原文敏感字段;旧 R4-A `log_agent_trace` + `agent_trace.log` 完全不动兼容共存;`TestLogAgentTraceJsonlSchema` 4 + `TestLogAgentTraceJsonlTypes` 3 + `TestLogAgentTraceJsonlPrivacy` 2 + `TestLogAgentTraceJsonlRobustness` 3 + `TestWorkflowJsonlTrace` 9 + `TestReplayFilter` 3 + `TestReplayMarkdown` 3 + `TestReplayScript` 3 + `TestReplayRobustness` 2 = **32 新 pytest**,320 → 352 全绿) | ✅ Round 5-A Phase 2 |
| **R5-A Phase 3 轻量 RAG evidence**(`core/evidence.py` 新增 `EvidenceSnippet` frozen dataclass + `build_evidence_snippets(materials)` 从 projects/skills/honors/certs 4 类切 snippets + `retrieve_evidence(jd_keywords, role, materials, top_k=8)` 复用 `KEYWORD_GROUPS` surface/normalized 做 lexical matching + `_summarize_evidence_for_prompt` 把 snippets 压成 80 字符/条 + 2000 字符总上限的 LLM 友好 summary;排序稳定 `(-confidence, source_type, source_id)`;**零向量数据库 / 零 embedding API**(spec §5.3);`core/agent_tools.py` 注册 `retrieve_evidence` 工具(`ToolSpec.pii_risk=medium` 跟 match_score 同级);`core/agent_workflow.py` has_jd 时任务图插入 `retrieve_evidence` step(match_score 之后, retrieve_materials 之前),evidence 失败走 `use_default` 降级不阻断主流程,evidence 透传给 `build_sections` → `rewrite_highlights`;`core/llm_rewriter.py` 加 `evidence` kwarg + `_build_request_payload` 加 `evidence_summary` kwarg + `SYSTEM_PROMPT` 加第 8 条硬性约束"只能基于 evidence 中存在的事实改写",evidence=None 时 payload 字节级一致(老测试零回退);`PreviewRequest.enable_agent_workflow=True` 时 preview 返回值加 `evidence_summary` 字段(供前端高级信息区),trace 只记 evidence 数量 + 长度不记原文;`TestBuildEvidenceSnippets` 9 + `TestKeywordHit` 5 + `TestComputeConfidence` 6 + `TestRetrieveEvidence` 9 + `TestSummarizeEvidenceForPrompt` 4 + `TestEvidenceToDictList` 3 + `TestAgentToolsIntegration` 4 + `TestMatchScoreRegression` 4 + `TestKeyWordGroupsReuse` 1 = **45 个 test_evidence 新 pytest** + `TestEvidencePhase3` 9 个 test_agent_workflow 集成 + `TestEvidenceIntegration` 8 个 test_llm_rewriter evidence payload = **62 新 pytest**,352 → 416 全绿;**安全审查无 P0/P1 阻塞** — trace 不含 evidence text 原文 / evidence_summary 不含 PII(材料已脱敏)/ 无新增外部网络调用) | ✅ Round 5-A Phase 3 |
| **R5-B Phase 2A 工具契约 / 权限 / 真实数据流**(`core/tool_schema.py` 新增轻量 JSON schema validator 子集 — type / required / properties / items / minimum / maximum,零依赖纯 stdlib;`core/agent_tools.py` 升级 `_validate_required_args` → 委托 `validate_schema`,新增 `_check_permission_context(spec, context)` 校验 `allow_jd_text` / `allow_materials` / `allow_external_resume` / `max_pii_risk`,权限不匹配返 PRIVACY_VIOLATION(早于 schema 校验);`ToolSpec.metadata={"affects_preview": bool}` 新增字段 + `affects_preview()` helper;`retrieve_evidence` 标 `affects_preview=True`(output 真正注入 build_sections → rewrite_highlights);`core/agent_workflow.py` 新增 `_build_step_context(tool_name, has_jd, has_external_resume)`,任务图每个工具步骤派发 context;`agent_summary.tools_used` 升级为有效语义 — 只列 `affects_preview=True` 且 `status=success` 的工具(展示型工具 `parse_jd` / `match_score` / `evaluate_bullet_jd_match` / `rewrite_highlights` 不列);错误描述只含字段名 + 类型名 + 权限名,不含 args / JD / bullet 原文(spec §6.4 隐私);`TestSchemaRequired` 3 + `TestSchemaType` 5 + `TestSchemaRange` 2 + `TestSchemaArray` 3 + `TestSchemaNoSchema` 2 + `TestSchemaPrivacy` 1 + `TestSchemaIntegration` 3 = **19 个 test_tool_schema 新 pytest** + `TestToolPermissionContext` 8 + `TestAffectsPreview` 6 + `TestExecuteAgentToolSchemaIntegration` 4 = **18 个 test_agent_tools 新 pytest** + `TestWorkflowEffectiveTools` 5 + `TestWorkflowContextDispatch` 4 = **9 个 test_agent_workflow 新 pytest** = **46 个新 pytest** (441 → 487 全绿),441 老测试零回退;**不挂 pre-push hook**(spec §12 #3 默认手动脚本);**不破坏老路径**(enable_agent_workflow=False 字节级一致 — `agent_summary` 字段只在 workflow 路径加);**不引入新 LLM 调用 / 不引入新依赖**(纯 stdlib + dataclass) | ✅ Round 5-B Phase 2A |

---

## 8 要素 × Round 3-A 落地表

| 要素 | Round 1 → Round 3-A 增量 |
|---|---|
| **1. 任务边界** | 本 README 顶部"做/不做"清单;`ENABLED_ROLES` 写死,**Round 2 启用 6 个 role**(度量/产品/算法/标注/测试/通用) |
| **2. 上下文** | Round 1 用"素材库 + role 模板";**Round 2 加 JD 文本解析**(skill/tool/domain/experience/education 5 维度)+ LLM 改写上下文(target_role + jd_context) |
| **3. 工具** | python-docx(写 docx) + pymupdf(读 docx/pdf) + FastAPI + Vue 3 + Element Plus + **OpenAI 兼容 HTTP(urllib stdlib,无第三方包)** + jieba-ready(预留 Round 3) |
| **4. 权限** | 本地单用户;素材库和输出目录按 user 权限隔离(不需要账号系统) |
| **5. 人工确认** | 强制两段式:`POST /preview` → 渲染 → `POST /generate`;**Round 2 加 JD 评分卡预览**(0-100 分 + 三维覆盖率 + 命中/缺失关键词);**R3-A 加业务阈值 banner**(高≥80 / 中 60-79 / 低<60,与 scoreColor/scoreTag 阈值一致) |
| **6. 评测** | Round 1 仅"事实覆盖自检";**当前 283 个 pytest 用例**(181 R3-G baseline + 1 emoji/特殊字符归一化 + 1 .exe UnsupportedFormatError + **7 R3-M.1 MVP:3 个 `test_layout_generates_valid_docx` 参数化 + 4 个 visuals `test_academic_larger_font_size` / `test_internet_smaller_font_size` / `test_internet_has_skill_marker` / `test_bilingual_default_margins`** + **23 R3-M.2: 5 个 `TestLayoutConfigSchema` 锁 LAYOUT_CONFIG 5 个可读性参数 schema + 比例不变量 + 9 个 helper 集成(`TestHeadingHierarchy` 4 + `TestSectionSpacing` 2 + `TestBulletSpacing` 2 + `TestMetaSpacing` 1, 验证参数真的写到 docx run.font.size / paragraph_format.space_before/after) + 5 个 `TestAcademicRenderer`(dispatch / 无项目名 H2 / 无独立 period meta / 无 summary / education 在 projects 前) + 4 个 `TestReadabilityAcrossLayouts`(body>=9pt / meta>=8pt / 4 间距>=0 / line_spacing [1.15, 1.5])** + **20 R3-M.3: 6 `TestAcademicLayout`(default compact / compact 不渲染 H2+meta+summary 3 case / detailed 恢复 H2+meta+summary 3 case) + 4 `TestBilingualHeader`(中文姓名 / 英文姓名 when present / graceful no en when absent / 居中) + 3 `TestBilingualEducation`(line / school_en when present / graceful) + 3 `TestBilingualProject`(title / title_en when present / graceful) + 2 `TestBilingualDispatch`(bilingual 走 _render_bilingual / classic 仍走 _render_classic) + 2 `TestMaterialsBilingualSchema`(真实 materials 无 _en 字段 bilingual 不抛异常 + build_sections 透传 _en 字段 schema 锁)** + **19 R3-P: 3 `TestSystemPromptV2` 锁 SYSTEM_PROMPT 含 few-shot 示例(基础 + jd_focus)+ 7 条硬性约束 + 5 `TestNewSchemaExtraction` 锁新 schema 验证(接受 / 拒绝重复 index / 越界 / 空 text / count 不匹配)+ 3 `TestRetryOnInvalid` 锁 retry 成功 / retry 仍失败降级 / 网络错误不 retry + 8 `TestSchemaValidationUnit` 锁 _validate_new_schema / _validate_legacy_schema 单元函数** + **8 R4-F: 5 `TestFunctionCalling` 锁 tools schema 结构 / 默认不挂 / jd_focus=None 不挂 / 启用挂载 / tool_calls 解析失败降级原文 + 3 `TestEvaluateBulletJdMatch` 锁 evaluate_bullet_jd_match 工具函数 surface 命中 + missing 列表** + **12 R4-A: 9 `TestAgentLoop` 锁 max_step 上限 / 工具成功路径 / 工具失败回退 / 连续 3 步仍无 output 降级 / trace 格式 / 网络错误不入 loop / max_step=0 走老路径 / 单步单工具约束 / execute_tool_call known+unknown 工具 + 3 `TestLogAgentTrace` 锁 trace 写入格式 + 文件创建 + 字段完整性** + **11 R4-M: 8 `TestSessionAPI` 锁 create/append/get/clear/上限 10 FIFO/不存在 session_id 静默忽略/空 session_id 静默忽略/唯一性 + 3 `TestSessionIntegration` 锁 session_id 拼接到 LLM messages / session=None 不拼接 / 多轮同 session 累积**),**283 passed + 0 skipped**(R3-G 移植自 worktree `eb7e841` + 当前 main R3.5+ borrowed pool / KEYWORD_GROUPS 适配 + R3-G bug hunt 加 2 个边界回归;baiyun_product 第三次复核改 '别投' label 跟 match_score score=33 '低' 一致, 8/8 = 100% 准确率),含 R2#1 baseline 锁死 + R3-A 加权 score/tier/recommendation/bugfix 回归 + R3-J layout dispatcher 视觉差异回归 + **R3-I 6 role 字节级 baseline hash 锁死 jd_context=None 路径** + **R3.5 阈值 80/60 锁死 + 6 份 ground truth 验证** + **R3.5+ borrowed pool + 'AI' surface 锁死 + 3 bugfix 回归** + **R3.5+ (b) PM 维度 surface 锁死 + 3 pm_dimensions 回归** + **R3.5.1 score_thresholds 实跑模式锁死 + 5 score_thresholds_live 回归** + **R3-G resume_parser 锁死 .docx/.pdf/.txt 解析边界 + resume_perspective 同义词 alias 算法 + 借调池去重 false negative + emoji/特殊字符归一化 + .exe 错误格式拒收** + **R3-M.1 MVP 8 套模板 dispatch + visuals 视觉差异 + 黑白打印友好** + **R3-M.2 LAYOUT_CONFIG 5 个可读性参数 + academic 专属 renderer 简化项目 highlights + 8 套模板可读性 invariant(body>=9pt / meta>=8pt / 4 间距>=0 / line_spacing 范围)** + **R3-M.3 bilingual_mode 激活 + 3 bilingual section helper + academic_layout compact/detailed 分支 + build_sections _en 字段透传 + 真实数据 graceful 降级验证** + **R3-P Prompt 工程升级 + SYSTEM_PROMPT v2 few-shot + 显式 JSON schema + 失败 retry 1 次 + 旧 schema 保留兼容** |
| **7. 监测** | `backend/logs/generation.log` 记录每次生成(时间/role/文件/大小/状态);**Round 2 加 LLM 失败降级事件计数**(改写失败时回原文,不写日志防 PII 泄漏) |
| **8. 监控** | FastAPI 默认 exception handler;前端 `ElMessage.error` 捕获 |

---

## 启动方式

### 后端
```bash
cd backend
pip install -r requirements.txt   # 首次
python main.py                    # http://127.0.0.1:8000
```

### 前端
```bash
cd frontend
npm install                       # 首次
npm run dev                       # http://127.0.0.1:5173
```

### 端到端
1. 启后端 → 启前端 → 浏览器开 `http://127.0.0.1:5173`
2. 选岗位(默认 大模型技术度量) → 点「预览」
3. Review 各模块内容 → 点「确认下载」→ docx 落盘 `backend/output/`

---

## 目录结构

```
简历帮/
├── AGENTS.md                  # 项目级 agent 指令(给 OpenCode / Codex 等读)
├── README.md                  # 本文件
├── backend/
│   ├── main.py                # FastAPI 入口 + CORS
│   ├── api/
│   │   ├── materials.py       # 素材库 CRUD
│   │   ├── resume.py          # 简历预览/生成/角色列表
│   │   └── jd.py              # Round 2 #2: JD 解析 + 匹配度评分
│   ├── core/
│   │   ├── generator.py       # sections 构造 + docx 渲染(+ Round 2 #3 LLM hook)
│   │   ├── jd_parser.py       # Round 2 #2: KEYWORD_GROUPS + parse_jd + match_score
│   │   ├── llm_rewriter.py    # Round 2 #3: OpenAI 兼容 HTTP,4 道防线静默降级
│   │   └── logger.py          # 本地日志
│   ├── tests/
│   │   ├── conftest.py
│   │   ├── test_jd_parser.py       # 53 pytest 用例(R2#2 关键词 + R3-A 加权/tier/recommendation + bugfix 回归)
│   │   ├── test_api_jd.py          # 3 pytest 用例(R3-A FastAPI TestClient 集成)
│   │   ├── test_llm_rewriter.py    # 16 pytest 用例(含 R2#1 baseline 锁死)
│   │   ├── test_generator_layouts.py # 39 pytest 用例(R3-J 5 套 layout dispatcher + 视觉差异 + invalid + backward-compat + R3-M.1 3 套新模板 + R3-M.2 5 schema + 9 helper 集成 + 5 academic + 4 readability = 23 新增)
│   │   └── test_threshold_tuning.py # 11 pytest 用例(R3.5 阈值常量锁死 + 6 ground truth + 2 meta)
│   ├── data/
│   │   └── materials.json     # 素材库(单人唯一真源,脱敏版)
│   ├── .env.example           # Round 2 #3: LLM_API_KEY / LLM_BASE_URL / LLM_MODEL / LLM_ENABLED 模板
│   ├── logs/                  # 生成历史 .log(被 gitignore,本地保留)
│   ├── output/                # 生成的 docx(被 gitignore,本地保留)
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── App.vue            # 三段式主界面 + JD 评分卡(Round 2)
│   │   ├── api/index.ts       # axios 封装(materialsApi / resumeApi / jdApi)
│   │   └── main.ts
│   ├── package.json
│   ├── vite.config.ts         # /api 代理 → :8000
│   └── dist/                  # 构建产物(vite build 产出,被 gitignore)
└── .harness/                  # 多 agent 协作脚手架
    ├── agent.md               # orchestrator 路由与节奏规则
    ├── reins/
    │   ├── developer/agent.md # 实施 rein 角色定义
    │   └── tester/agent.md    # 验证 rein 角色定义
    ├── docs/                  # 架构 / 开发流程 / 隐私部署
    └── memory/MEMORY.md       # 团队共享记忆
```

> 注:`backend/output/` 和 `backend/logs/` 已在 `.gitignore` 内,只保留在本地不外发。

---

## 后续规划

### ✅ 已完成
- **Round 1**: 素材库 + 单 role 预览/生成 + fallback 链 + 本地日志
- **Round 2**: 6 个 role 全启用 + JD 解析/匹配度评分 + LLM 智能改写项目描述 + 前端 JD 评分卡 + `.harness/` 多 agent 协作脚手架
  - Round 2 收尾 commit: `d932bcc merge: Round 2 integration — JD 解析 + LLM 改写`
  - 远端: https://github.com/JJ704sd/Resume-Buff
- **Round 3-A**: JD 解析 MVP 升级 — KEYWORD_GROUPS weight 三元组 (必选 1.0 / 加分 0.5) + tier 上下文窗口识别(必选/优先/加分)+ 加权 score + 业务阈值 banner(≥80 高 / 60-79 中 / <60 低)+ bugfix(UI 阈值一致 + 死代码清理 + 签名修正)
  - R3-A 收尾 commit: `931da41 chore(round3#a): gitignore orchestrator scratch` + `9ceeaf6 fix(round3#a): bug hunt — UI 阈值一致 + 死代码清理 + 注释对齐`
- **Round 3-J**: 简历模板库 — 5 套排版 (`classic` / `single_column` / `two_column` / `minimal` / `technical`) 由 `LAYOUT_CONFIG` 驱动视觉差异(颜色/字号/行距/margin/header 对齐/skills 前缀/项目底纹/双栏 table),前端 radio 选模板,API `template` 字段透传到 `render_docx` 的 `_LAYOUT_DISPATCH`,日志记录 template。
  - R3-J 收尾 commit: `30bbd36 merge: Round 3-J — 简历模板库 (5 套排版)` + `ed346d8 feat(round3#j): 简历模板库`
- **Round 3-E**: CI 验证(`scripts/verify.ps1` 全量 pytest + vue-tsc + build + `scripts/hooks/pre-push` 自动挡 push + `scripts/install-hooks.ps1` 一键 setup) — 用 `git config core.hooksPath scripts/hooks` 把 hook 目录指向仓库内可版本控制位置,Windows only(PowerShell 5.1),跳过用 `git push --no-verify`。
  - 启用: `powershell -ExecutionPolicy Bypass -File scripts/install-hooks.ps1`
- **Round 3-M.1/M.2/M.3**: 8 套模板精细打磨(academic / internet / bilingual 3 套新模板 + A4 规范 + 8 套可读性参数化 + bilingual_mode 激活 + academic_layout compact/detailed 二级选项);`test_generator_layouts.py` 16 → 39 case
- **Round 3-G**: 外部简历上传 + 简历视角评分(`POST /api/resume/parse-external` 解析 docx/pdf/txt + `match_score` external_resume_text 参数 + `resume_perspective` 块 + 前端 ResumeUploader el-upload drag)
- **Round 3-P**: LLM Prompt 工程升级(SYSTEM_PROMPT v2 + 2 个 few-shot 示例 + 显式 JSON schema + 失败 retry 1 次 + 旧 schema 兼容)
- **Round 3.5 / 3.5+ / 3.5.1**: match_score bug 修复(borrowed pool + 'AI' surface + PM 维度 surface) + score_thresholds 实跑模式 + 8/8 = 100% 准确率
- **Round 4 Agent MVP**: Function Calling 协议接入(R4-F tools schema + evaluate_bullet_jd_match 工具函数 + 旧路径字节级一致)+ Agent Loop(R4-A max_step=3 + 单工具约束 + trace 日志)+ Session 记忆(R4-M 进程内 deque 上限 10 + 隐私隔离);pytest 252 → 283
  - R4 收尾 commit: `60a18b8 docs(round4): 测试数 252 -> 283 + R4 Agent MVP 当前能力表 + AGENTS 锁点 + ROADMAP/MEMORY 同步` + `8e2ce91 Merge pull request #1 from JJ704sd/feat/round4-agent-mvp`
  - 4 个实施 commit: `a4c9156` (R4-F) / `ac90e13` (R4-A) / `c5ec652` (R4-M) / `ba536df` (R4-M integration)
  - 远端 PR: https://github.com/JJ704sd/Resume-Buff/pull/1 (PR merge 时 GitHub 自动删除 head branch `feat/round4-agent-mvp`,无需手动 `git branch -D` / `git push origin --delete`)
- **Round 5-A Agent 增强(Phase 1 + Phase 2 + Phase 3 + Phase 4)**:
  - Phase 1: Agent 编排层(`core/agent_workflow.py` 受控 Plan-and-Execute)+ 工具注册表(`core/agent_tools.py` AGENT_TOOLS 4 个核心 + 统一 `execute_agent_tool()` 入口);`enable_agent_workflow` 字段默认 False 字节级一致;20 个新 pytest (320 → 320 全绿,283 老测试零回退)
  - Phase 2: 结构化 JSONL trace(`log_agent_trace_jsonl` + 11 字段 schema + request_id 短 uuid)+ 会话回放(`scripts/replay_agent_trace.py` argparse CLI + markdown 摘要);旧 `agent_trace.log` 不动兼容共存;32 个新 pytest (320 → 352 全绿);**安全审查无 P0/P1 阻塞** — JSONL 不存原文 PII / 写入失败不阻断 / replay 不输出敏感内容
  - Phase 3: 轻量 RAG evidence(`core/evidence.py` 切片 projects/skills/honors/certs 为 snippets + `retrieve_evidence` 复用 `KEYWORD_GROUPS` surface/normalized 做 lexical retrieval + 稳定排序 `(-confidence, source_type, source_id)`);`core/agent_workflow.py` has_jd 时任务图插入 retrieve_evidence step(失败降级 use_default 不阻断主流程);`core/llm_rewriter.py` `evidence` kwarg + `_build_request_payload` `evidence_summary` 字段 + `SYSTEM_PROMPT` 第 8 条约束"只能基于 evidence 改写";evidence=None 字节级一致(老测试零回退);`PreviewRequest.enable_agent_workflow=True` 时 preview 返回值新增 `evidence_summary` 字段(供前端高级信息区);**零向量数据库 / 零 embedding API / 零新依赖**(spec §5.3);62 个新 pytest (352 → 416 全绿);**安全审查无 P0/P1 阻塞** — trace 不含 evidence text 原文 / evidence_summary 不含 PII(材料已脱敏)/ 无新增外部网络调用
  - Phase 4: Agent 离线评测报告(`scripts/evaluate_agent_workflow.py` 跑固定 eval set 12 JD = jd_samples 8 份非公告型 + v4_strong 4 份 × 4 组开关对照 (FC × AW 笛卡尔积);记录 jd_id / role / expected_label / score / recommendation / schema_pass / fallback_used / tools_used / latency_ms / error_type / pii_safe 11 字段;报告 `AI岗位JD库_agent_eval报告.md` 含 8 节: eval set 概览 / 四组对照总览 / score 一致性 / 每 JD 工具调用摘要 / 失败 case / 隐私检查 / 结论 / 与既有脚本关系;无 LLM key 时全部走原文 fallback,脚本不报错;**不挂 pre-push hook**(spec §12 #3 默认手动脚本);**不修改既有 match_score / `score_thresholds.py` / `match_golden_targets.py` / `replay_agent_trace.py`**;PII 用 placeholder 白名单 (`13800000000` / `your_email@example.com`) 容忍公开脱敏版 demo;11 个新 pytest (416 → 427 全绿);**安全审查无 P0/P1 阻塞** — 报告不含真实 PII / 不读 private 备份 / 无外部网络依赖
  - **R5-A closeout**(`b60a215` fix commit):基于 `.planning/agent-architecture-audit/findings.md` 修复 4 个 bug — (A) `enable_external_resume` 字段透传 (api / generator / workflow 整链, 替换 hardcoded `False`); (B) workflow preview 返回值新增 `agent_summary` 字典 (含 request_id / steps_executed / tools_used / fallback_used / latency_ms 5 字段, 对齐 spec §8.2); (C) `execute_agent_tool` 加 `_validate_required_args` 主动 schema 校验 (callable 前校验 input_schema.required, 缺字段返 TOOL_ARGS_INVALID); (D) 隐性 bug 修复: `match_score` schema/参数名 `role` → `target_role` 对齐 `jd_parser.match_score` 函数签名(三方不一致导致 workflow 调 match_score 时 TypeError 被兜底, 主流程无感但工具日志始终 error);14 个新 pytest (`TestEnableExternalResumePassthrough` ×3 + `TestAgentSummaryField` ×7 + `TestAgentToolArgsValidation` ×4 含 schema 字段名防回归);427 → **441 全绿** (416 baseline + 25 R5-A Phase 1-3 + 14 closeout 新增), 416 老测试零回退;不挂 pre-push hook;不破坏既有 baseline 字节级一致
  - R5-A closeout 收尾 commit: `b60a215 fix(round5-a closeout): agent_summary + enable_external_resume + tool args validation + match_score schema bugfix`
  - **R5-B Phase 2A 工具契约 / 权限 / 真实数据流**(`core/tool_schema.py` 轻量 JSON schema validator 子集(type / required / properties / items / minimum / maximum,零依赖纯 stdlib);`core/agent_tools.py` 升级 `_validate_required_args` → 委托 `validate_schema`,新增 `_check_permission_context(spec, context)` 校验 `allow_jd_text` / `allow_materials` / `allow_external_resume` / `max_pii_risk`,权限不匹配返 PRIVACY_VIOLATION(早于 schema 校验);`ToolSpec.metadata={"affects_preview": bool}` 新增 + `affects_preview()` helper;`retrieve_evidence` 标 `affects_preview=True`(output 真正注入 build_sections → rewrite_highlights);`core/agent_workflow.py` 新增 `_build_step_context(tool_name, has_jd, has_external_resume)`,任务图每个工具步骤派发 context;`agent_summary.tools_used` 升级为有效语义 — 只列 `affects_preview=True` 且 `status=success` 的工具(展示型工具 `parse_jd` / `match_score` / `evaluate_bullet_jd_match` / `rewrite_highlights` 不列);错误描述只含字段名 + 类型名 + 权限名,不含 args / JD / bullet 原文(spec §6.4 隐私);**46 个新 pytest**(`test_tool_schema.py` 19 + `test_agent_tools.py` TestToolPermissionContext/TestAffectsPreview/TestExecuteAgentToolSchemaIntegration 18 + `test_agent_workflow.py` TestWorkflowEffectiveTools/TestWorkflowContextDispatch 9),441 → **487 全绿**,441 老测试零回退;**不挂 pre-push hook**(spec §12 #3 默认手动脚本);**不破坏老路径**(`enable_agent_workflow=False` 字节级一致 — `agent_summary` 字段只在 workflow 路径加);**不引入新 LLM 调用 / 不引入新依赖**(纯 stdlib + dataclass);**不实际消费** external_resume / 不把 eval 挂 pre-push(留 Phase 3 / Phase 5);**不实施 GUI Agent 面板**(留 Phase 4,等用户明确启动)

### 🎯 后续候选(等用户拍)
- **R3-B**: LLM prompt 模板库 — 按 role 区分 system prompt(产品/算法/度量风格差异)
- **R3-C**: LLM 缓存层 — 同 role+intention+bullet 复用上次改写,省 token
- **R3-D**: 求职信 / 自我介绍生成 — README 之前提的能力,`.docx` 多一份输出
- **R3-F**: 异步化 + 评测强化 — Round 2 #3 已知限制 + 8 要素 #6
- **R3.5**: 阈值调优 — 用真实 JD 数据校准 80/60 阈值(R3-A 当前是占位)

### 📌 默认不启动(长期 P3,等用户明确)
- 多端同步、云端部署、账号系统、多用户协作
