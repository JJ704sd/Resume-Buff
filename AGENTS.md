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

- 后端 `pytest`：Round 3.5+(b) 收尾后有 **131 个用例**（53 jd_parser + 3 api_jd + 16 llm_rewriter + 16 generator_layouts + 25 generator_jd_aware + 11 threshold_tuning + 3 bugfix_r35plus + **3 pm_dimensions**），**131 passed + 1 skipped**（baiyun_2026_product 修后 score='低' vs label='中' 仍 gap, 根因 user 素材库缺 PM 经验）
  - 跑：`cd backend && D:\python3.11\python.exe -m pytest tests/ -v`
  - 新增行为必须有 pytest 覆盖（核心逻辑 / 边界 / 集成），thin wrapper / URL 字面量 / mock 自指 → 不写
  - **每轮独立验证 + 清理冗余测试**：跑全量绿后审视新增文件是否冗余
  - **bugfix 必须加回归测试**：覆盖每个 score 区间 + 每个死代码删除点,防止回潮
  - **R3-I 起：6 role 字节级 hash baseline 锁死** —— 不传 JD 时 `build_sections(target_role)` 输出必须与固化 hash 一致,任何 baseline 漂移立刻 fail,防止后续 round 不小心改默认排序路径
  - **R3.5 起：阈值 80/60 锁死 + 6 份 ground truth 验证** —— `tests/test_threshold_tuning.py` 锁 `_classify_recommendation` 在 `≥80 高 / ≥60 中 / 否则低`;基于 `简历帮知识库/jd_samples.json` 8 份 ground truth（排除 2 份公告型）跑 match_score 断言分类正确
  - **R3.5+ 起：borrowed pool + 'AI' surface 锁死** —— `match_score(text, role, materials, include_borrowed=True)` 默认开 borrowed pool（全素材库扫描，缓解跨 role false negative）；`KEYWORD_GROUPS['skills']` 加 `('AI', 'LLM', 0.5)`；`TestMatchScoreBugfixR35Plus` 3 个测试覆盖 baiyun_qa / baiyun_product 修后 score>0 + include_borrowed=False 旧行为保留
  - **R3.5+ (b) 起：PM 维度 surface 锁死** —— `KEYWORD_GROUPS['domains']` 加 4 个 PM 维度 surface（物流/工业工程/原型/流程图，0.5 加分）让 match_score 精确识别 baiyun_2026_product 等 PM 岗位缺失;suggestions 给"补 PM 维度素材"指引;`TestMatchScorePMDimensions` 3 个测试锁死 missing 含 PM 4 项 + suggestions 提到 PM 关键词 + KEYWORD_GROUPS 字典级断言
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