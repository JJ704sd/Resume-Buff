# AGENTS.md

个人简历助手 — 一份素材库，一键生成多份针对性简历。本地单用户工具。

> 本仓库服务于**本地开发**：`PUT /api/materials` 无鉴权，**不要直接暴露公网**。

## Setup commands

- 后端安装依赖：`cd backend && pip install -r requirements.txt`
- 后端启动：     `cd backend && python main.py` （http://127.0.0.1:8000）
- 前端安装依赖：`cd frontend && npm install`
- 前端启动：     `cd frontend && npm run dev` （http://127.0.0.1:5173）
- 前端构建：     `cd frontend && npm run build` （产物到 `frontend/dist/`，已在 .gitignore）
- 安装 pre-push hook：`powershell -ExecutionPolicy Bypass -File scripts/install-hooks.ps1`
- 跳过 hook：`git push --no-verify`（紧急情况）
- 前端类型检查： `cd frontend && npx vue-tsc --noEmit`

## Project layout

- `backend/` — Python FastAPI 后端
  - `main.py` — FastAPI 入口与 CORS 配置
  - `api/materials.py` — 素材库 CRUD（`/api/materials`）
  - `api/resume.py` — 预览 / 生成 / 角色列表（`/api/resume`）
  - `core/generator.py` — sections 构造 + python-docx 渲染（**核心域**）
  - `core/agent_tools.py` — Agent 工具注册表 + 统一执行入口(R5-A Phase 1)
  - `core/agent_workflow.py` — 受控 Plan-and-Execute 编排器(R5-A Phase 1)
  - `core/logger.py` — `backend/logs/generation.log` 写入
  - `data/materials.json` — 素材库（**单人唯一真源**，已脱敏）
  - `output/`、`logs/` — 运行时产物（`.gitignore`，本地保留）
- `frontend/` — Vue 3 + TypeScript + Vite 单页
  - `src/App.vue` — 三段式主界面（选岗位 → 预览 → 下载）+ ② JD 评分卡
  - `src/api/index.ts` — axios 封装（`materialsApi` / `resumeApi` / `jdApi`）
  - `vite.config.ts` — `/api` 代理到 `:8000`
- `.harness/` — 多 agent 协作脚手架（`agent.md` = orchestrator；`reins/{developer,tester}/` = 两个 rein；`docs/` = 架构/流程/隐私；`memory/` = 团队共享记忆）
- `简历帮知识库/` — 个人素材草稿（`.gitignore`，不进库）

## AI 岗位 JD 资料库（v4 实习岗筛选版，2026-06-27，最近更新 2026-06-27 Round 3.5+）

> 个人用的 AI 行业 JD 池子，与 `backend/core/jd_parser.py` 的 `match_score` 联动 — 投递前先把目标 JD 全文跑 `match_score(text, role, materials)`，看素材库匹配度。

顶层 3 个文件（**只保留最新版**，旧版本已清理到回收站）：
- `AI岗位JD库_v4_intern.json` — **主库**：86 份 JD（v3 42 + 补搜实习岗 40 + Round 3.5 百运网 4），每份带 `intern_match` 4 级标签（strong / campus_to_intern / weak / none）
- `AI岗位JD库_v4_intern_筛选报告.md` — **筛选报告**：4 级规则 + 52 份实习可投清单 + 公司维度统计
- `AI岗位JD库_v4_黄金标的match报告.md` — **match_score 实测**：JD-B010 字节 / JD-D007 DeepSeek / JD-A012 阿里 3 份黄金 × 6 role = 18 次匹配对比 + 局限性说明

> R3.5 阈值调优 ground truth 如需独立保存,后续可在 `简历帮知识库/jd_samples.json` 单独建文件(含 label / label_note),不污染主库

关联 `scripts/`：
- `scripts/build_v4.py` — v4 入库脚本（v3 + 补搜 JD + 后续扩库，含 ID 去重）
- `scripts/score_intern_match.py` — 4 级实习匹配打标 + Markdown 报告生成
- `scripts/match_golden_targets.py` — 黄金 JD × 6 role 的 match_score 实测

扩库流程：
1. 在 `build_v4.py` 的 `NEW_JDS` 列表追加新 JD（注意 ID 不能跟现有 86 个重复，命名沿用 `JD-X###`，公司用首字母缩写如 BY=百运网）
2. `python scripts/build_v4.py` → 重建 `AI岗位JD库_v4_intern.json`
3. `python scripts/score_intern_match.py` → 重打 4 级标签 + 生成筛选报告
4. 旧版本文件直接 trash，**不保留 v1/v2/v3 历史**（避免目录冗余）
5. 如果是手工抄录的 JD（非网上抓），`source_url` 填 `"user_provided:<来源描述>"`、`source_quality` 用 `"unverified"`、`authenticity` 分打低分（如 18 分）

## Code style

- Python：PEP 8，类型注解推荐但不强求；函数文档串用中文说明业务含义
- TypeScript：`tsconfig.json` 启用 `strict: true`；Vue SFC 用 `<script setup lang="ts">`
- 缩进统一 2 空格；后端不用 formatter，前端不加 ESLint/Prettier 配置（沿用 Vite 默认）
- 命名：snake_case（Python）/ camelCase（TS）；role id 用 snake_case（如 `tech_metric`）

## Testing instructions

  - 后端 `pytest`：Round 5-A Phase 2 收尾后有 **352 个用例**（320 Round 5-A Phase 1 baseline + 11 R5-A Phase 2 `test_logger.py` JSONL trace + 9 R5-A Phase 2 `test_agent_workflow.py` workflow trace + 10 R5-A Phase 2 `test_agent_trace_replay.py` replay 脚本），**352 passed + 0 skipped**（R5-A Phase 2 在 Phase 1 之上加：JSONL trace 11 字段稳定 schema(spec §7.1) + input_size/output_size 只算 bytes 不存原文 + 写入失败(IO/磁盘满/编码错)静默降级不影响主流程 + request_id 短 uuid(前缀 "r") + 每个 step 含本地步骤写一条 trace(status=skipped) + `scripts/replay_agent_trace.py` argparse CLI 按 request_id/session_id 拉 markdown 摘要 + 旧 R4-A `log_agent_trace` / `agent_trace.log` 不动兼容共存）
  - 跑：`cd backend && D:\python3.11\python.exe -m pytest tests/ -v`
  - 新增行为必须有 pytest 覆盖（核心逻辑 / 边界 / 集成），thin wrapper / URL 字面量 / mock 自指 → 不写
  - **每轮独立验证 + 清理冗余测试**：跑全量绿后审视新增文件是否冗余
  - **bugfix 必须加回归测试**：覆盖每个 score 区间 + 每个死代码删除点,防止回潮
  - **R3-I 起：6 role 字节级 hash baseline 锁死** —— 不传 JD 时 `build_sections(target_role)` 输出必须与固化 hash 一致,任何 baseline 漂移立刻 fail,防止后续 round 不小心改默认排序路径
  - **R3.5 起：阈值 80/60 锁死 + 6 份 ground truth 验证** —— `tests/test_threshold_tuning.py` 锁 `_classify_recommendation` 在 `≥80 高 / ≥60 中 / 否则低`;基于 `简历帮知识库/jd_samples.json` 8 份 ground truth（排除 2 份公告型）跑 match_score 断言分类正确
  - **R3.5+ 起：borrowed pool + 'AI' surface 锁死** —— `match_score(text, role, materials, include_borrowed=True)` 默认开 borrowed pool（全素材库扫描，缓解跨 role false negative）；`KEYWORD_GROUPS['skills']` 加 `('AI', 'LLM', 0.5)`；`TestMatchScoreBugfixR35Plus` 3 个测试覆盖 baiyun_qa / baiyun_product 修后 score>0 + include_borrowed=False 旧行为保留
  - **R3.5+ (b) 起：PM 维度 surface 锁死** —— `KEYWORD_GROUPS['domains']` 加 4 个 PM 维度 surface（物流/工业工程/原型/流程图，0.5 加分）让 match_score 精确识别 baiyun_2026_product 等 PM 岗位缺失;suggestions 给"补 PM 维度素材"指引;`TestMatchScorePMDimensions` 3 个测试锁死 missing 含 PM 4 项 + suggestions 提到 PM 关键词 + KEYWORD_GROUPS 字典级断言
  - **R3.5.1 起：score_thresholds.py 实跑模式锁死** —— `scripts/score_thresholds.py` 跑 `match_score(text, role_id_hint, materials)` 拿 score / coverage, 不再读 jd_samples.json frozen top_score;`tests/test_score_thresholds.py::TestScoreThresholdsLive` 5 个测试锁死 (含 `test_live_mode_ignores_frozen_top_score` 篡改 frozen 字段验证实跑分数不变, 核心防回潮)
  - **R3-M.2 起：8 套模板可读性参数 + academic 专属 renderer 锁死** —— LAYOUT_CONFIG 8 套必含 h1_size_ratio / h2_size_ratio / section_spacing_pt(2 元组) / meta_spacing_pt / item_spacing_pt;`TestLayoutConfigSchema` 5 个 case 锁 schema;`_render_academic` 走 _LAYOUT_DISPATCH['academic'] 且项目 highlights 简化(无 H2 项目名 / 无独立 period meta / 无 summary,直接列 highlights 为 bullets);`TestReadabilityAcrossLayouts` 4 个 case 锁 body>=9pt / meta>=8pt / 4 间距>=0 / line_spacing [1.15, 1.5]
  - **R3-M.3 起：bilingual_mode 激活 + academic_layout 详细模式锁死** —— `_LAYOUT_DISPATCH['bilingual']` 切到 `_render_bilingual`(3 个 bilingual section helper:`_render_bilingual_header_to` / `_render_bilingual_education_to` / `_render_bilingual_project_group_to`;`name_en` / `school_en` / `major_en` / `title_en` 缺失时 graceful 降级到单语言);`_render_academic` 按 `academic_layout` 分支 dispatch(compact → `_render_project_group_academic_to` 默认,detailed → `_render_project_group_academic_detailed_to` 恢复 H2 + meta + summary);`TestAcademicLayout` 6 case 锁分支行为 + `TestBilingual*` 12 case 锁双语 + 真实数据 graceful + `TestMaterialsBilingualSchema` 2 case 锁 build_sections schema 透传;`PreviewRequest` / `GenerateRequest` 加 `academic_layout` 字段,`render_docx` 拷贝 LAYOUT_CONFIG 后覆盖(不污染全局)
  - **R3-P 起：Prompt 工程升级 + 显式 schema + 失败 retry 锁死** —— `SYSTEM_PROMPT` v2 含 2 个 few-shot 示例(基础改写 + jd_focus 改写)+ 7 条硬性约束(不编造 / 长度 20-50 字 / JSON schema 唯一 / jd_focus 4 条);显式 JSON schema `{rewritten: [{index: 0..N-1, text: "..."}]}` 唯一规范(index 必唯一 + 0..N-1 + non-empty str);`_call_with_retry` 解析失败 retry 1 次(`_build_request_payload` 加 `strict_retry=True` 强约束提示),网络错误不 retry(避免 token 浪费);旧 schema(顶层 array / `{rewritten: [str]}`)保留兼容(16 老 case 全绿);`TestSystemPromptV2` 3 + `TestNewSchemaExtraction` 5 + `TestRetryOnInvalid` 3 + `TestSchemaValidationUnit` 8 = 19 case 锁死
  - **R4-F 起：Function Calling 协议接入锁死** —— `TOOL_EVALUATE_SCHEMA` OpenAI tools schema + `evaluate_bullet_jd_match(bullet, jd_focus)` 工具函数(从 match_score 内部抽 surface 扫描逻辑);`rewrite_highlights` 加 `enable_function_calling: bool = False` 参数(默认关,旧路径字节级一致);`jd_focus is not None` 时挂 tools,空时走老路径;`PreviewRequest` / `GenerateRequest` 加同名字段透传;`TestFunctionCalling` 5 case 锁 tools 字段结构 / 默认不挂 / jd_focus=None 不挂 / 启用挂载 / tool_calls 解析失败降级原文 + `TestEvaluateBulletJdMatch` 3 case 锁新工具函数 surface 命中 + missing 列表
  - **R4-A 起：Agent Loop (max_step=3) + 单工具约束 + trace 日志锁死** —— `MAX_AGENT_STEPS=3` 硬上限防死循环 + 单步单工具防 token 爆 + 网络错误不进入 loop(直接降级不浪费 token);`enable_function_calling=False` 时完全不走 loop(字节级一致,旧测试不破);`logger.log_agent_trace(session_id, step, tool_name, latency_ms, outcome)` 写 `logs/agent_trace.log` 跟 `generation.log` 分离;`TestAgentLoop` 9 case 锁 max_step 上限 / 工具成功路径 / 工具失败回退 / 连续 3 步仍无 output 降级 / trace 格式 / 网络错误不入 loop / max_step=0 走老路径 / 单步单工具约束 / execute_tool_call known+unknown 工具 + `TestLogAgentTrace` 3 case 锁 trace 写入格式 + 文件创建 + 字段完整性
  - **R4-M 起：Session 记忆(进程内 deque 上限 10) + 隐私隔离锁死** —— `core/session.py` `_SESSIONS: dict[str, deque(maxlen=10)]` + 4 API(create_session / get_messages / append_message / clear_session);`rewrite_highlights` 加 `session_id: str | None = None` 参数,挂上后从 session 拉历史 messages 拼到 LLM messages 头部;`PreviewRequest` / `GenerateRequest` 加 `session_id` 字段透传;**隐私隔离** — `session_id` 由前端生成(不存 PII),后端不写 session 内容到日志(只写 session_id + 步数);MVP 不持久化(进程退出即丢),不做 TTL;`TestSessionAPI` 8 case 锁 create/append/get/clear/上限 10 FIFO/不存在 session_id 静默忽略/空 session_id 静默忽略/唯一性 + `TestSessionIntegration` 3 case 锁 session_id 拼接到 LLM messages / session=None 不拼接 / 多轮同 session 累积
  - **R4-M integration 起：session_id 整链透传锁死** —— `rewrite_highlights` → `generator.build_sections` → `api/resume.py` Preview/Generate 整链 `session_id` 字段透传(零修改上层行为,`session_id=None` 旧路径字节级一致);cherry-pick R4-M 后必须补 `TestSessionIntegration` 链路验证
  - **R5-A(Phase 1)起：Agent 编排层与工具注册锁死** —— `core/agent_tools.py` AGENT_TOOLS 含 `parse_jd` / `match_score` / `evaluate_bullet_jd_match` / `rewrite_highlights` 4 个核心工具;`execute_agent_tool(tool_name, args, context)` 统一入口:未知工具 → `ToolErrorType.TOOL_NOT_ALLOWED` 不抛 / TypeError → `TOOL_ARGS_INVALID` / 其他异常 → `TOOL_RUNTIME_ERROR`;`ToolResult` dataclass **不存 args / input 原文**(隐私边界 `TestPrivacyGuarantee::test_tool_result_has_no_args_or_input_attrs` 锁);`core/agent_workflow.py` `build_task_graph(has_jd, enable_function_calling, has_external_resume)` 确定性产任务图(LLM 不参与规划)— 同样输入字节级一致 + step 序号连续 + `AgentStep` frozen=True;`run_agent_workflow(...)` 失败时降级到旧路径(走 `build_sections` / `render_docx`),最终输出与 `generator.preview_resume / generate_resume_docx` 结构一致;`enable_agent_workflow=False`(默认)→ `preview_resume` / `generate_resume_docx` 字节级一致(R4-M 283 老测试零回退);`PreviewRequest.enable_agent_workflow` / `GenerateRequest.enable_agent_workflow` 字段顺序在 `session_id` 之后新增,前面既有字段顺序不动(Pydantic 向后兼容)
- **R5-A(Phase 2)起：结构化 JSONL trace + 会话回放锁死** —— `core/logger.py` `JSONL_TRACE_FIELDS` 11 字段稳定 schema(ts / request_id / session_id / workflow / step / tool / latency_ms / status / error_type / input_size / output_size);`log_agent_trace_jsonl(event)` 写 `backend/logs/agent_trace.jsonl`,写入失败(IO / 磁盘满 / 编码错)由 logger 内部 try/except 静默降级不影响主流程(spec §6.3);`core/agent_workflow.py` 每次 workflow 生成 request_id(短 uuid,前缀 "r"),每个 step 含本地步骤(intent / retrieve / aggregate / parse_external_resume)写一条 trace(`status="skipped"` 表示本地步骤);`input_size` / `output_size` 只算 bytes 长度不存原文(`_estimate_input_size` / `_estimate_output_size` 用 `json.dumps(...).encode("utf-8")` 算字节);`generate_request_id()` 模块级函数供调用;旧 R4-A `log_agent_trace` / `agent_trace.log` 签名/格式/路径完全不动,两个文件并存;`scripts/replay_agent_trace.py` argparse CLI `--request-id` / `--session-id` / `--path`,输出 markdown 摘要只渲染 7 列(step/tool/latency_ms/status/error_type/input_size/output_size),不输出 event 整体 dict / 任何原文;`TestLogAgentTraceJsonlSchema` 4 + `TestLogAgentTraceJsonlTypes` 3 + `TestLogAgentTraceJsonlPrivacy` 2 + `TestLogAgentTraceJsonlRobustness` 3 + `TestWorkflowJsonlTrace` 9 + `TestReplayFilter` 3 + `TestReplayMarkdown` 3 + `TestReplayScript` 3 + `TestReplayRobustness` 2 = **32 新 pytest** 全绿(320 → 352);**安全审查无 P0/P1 阻塞**
- 后端冒烟：`python main.py` 启动后访问 `http://127.0.0.1:8000/api/health` 应返回 `{"status":"ok"}`
- 前端类型检查：`cd frontend && npx vue-tsc --noEmit` 必须 0 error
- 前端构建：`cd frontend && npm run build` 必须成功
- **新增行为必须有验证**（详见 `.harness/docs/dev-workflow.md`）：
  - 后端：手测对应 API；可补充 `pytest` 用例
  - 前端：手测 UI；类型检查 + 构建为底线
- **bugfix 闭环**:
  - 复盘本轮 diff,逐文件过 — 签名/docstring/阈值是否一致
  - 修一个 bug 必须加 ≥1 个回归测试
  - 跑全量绿 + 前端构建成功才 commit

## PR & commit conventions

- 从 `main` 拉特性分支（如 `feat/round2-jd` / `fix/<scope>` / `chore/<scope>`）
- **永远不要直接 push 到 `main`** — 用 PR/MR 合并
- 提交信息遵循 conventional commits（`feat:` / `fix:` / `docs:` / `refactor:` / `chore:` / `test:`）
- 范围限定：消息中标注 round 编号（如 `feat(round2#2): JD 解析` / `fix(round3#a): bug hunt`）
- **bugfix commit 必须说明**:
  - 哪个 bug (Bug A/B/C 编号)
  - 触发条件 (e.g. score=50-59 时 UI 冲突)
  - 修复路径 (改哪几个文件 + 阈值/签名/注释)
  - 回归测试覆盖 (e.g. +6 TestBugfix*)

## Privacy & deploy

- **本地单用户**：不要加账号系统、不要把后端暴露公网
- `backend/data/materials.json` 是公开仓库版（已脱敏）；真实数据走 `backend/data/_private_backup.json`（`.gitignore`）
- clone 后想用自己的数据：`cp backend/data/_private_backup.json backend/data/materials.json`
- 生成产物 `backend/output/`、日志 `backend/logs/` 都在 `.gitignore` 内，**不要 commit**

## Security

- **不要 commit 任何真实个人信息**（姓名 / 手机 / 邮箱 / 学校 / 公司）
- 新增依赖前确认 license 兼容（MIT / Apache-2.0 / BSD 优先）
- 不要在日志里输出完整请求体（可能含 PII）— 见 `.harness/docs/privacy-deploy.md`

---

> 详细的开发流程、角色分工、素材库结构约定见 `.harness/docs/`。
> Agent 团队分工（orchestrator + developer + tester）见 `.harness/agent.md`。