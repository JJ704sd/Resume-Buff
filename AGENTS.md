# AGENTS.md

个人简历助手 — 一份素材库，一键生成多份针对性简历。本地单用户工具。

> 本仓库服务于**本地开发**：`PUT /api/materials` 无鉴权，**不要直接暴露公网**。

## Setup commands

- 后端安装依赖：`cd backend && pip install -r requirements.txt`
- 后端启动：     `cd backend && python main.py` （http://127.0.0.1:8000）
- 前端安装依赖：`cd frontend && npm install`
- 前端启动：     `cd frontend && npm run dev` （http://127.0.0.1:5173）
- 前端构建：     `cd frontend && npm run build` （产物到 `frontend/dist/`，已在 .gitignore）
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

## Code style

- Python：PEP 8，类型注解推荐但不强求；函数文档串用中文说明业务含义
- TypeScript：`tsconfig.json` 启用 `strict: true`；Vue SFC 用 `<script setup lang="ts">`
- 缩进统一 2 空格；后端不用 formatter，前端不加 ESLint/Prettier 配置（沿用 Vite 默认）
- 命名：snake_case（Python）/ camelCase（TS）；role id 用 snake_case（如 `tech_metric`）

## Testing instructions

- 后端 `pytest`：Round 2 收尾后有 **41 个用例**（25 jd_parser + 16 llm_rewriter），全绿
  - 跑：`cd backend && D:\python3.11\python.exe -m pytest tests/ -v`
  - 新增行为必须有 pytest 覆盖（核心逻辑 / 边界 / 集成），thin wrapper / URL 字面量 / mock 自指 → 不写
  - **每轮独立验证 + 清理冗余测试**：跑全量绿后审视新增文件是否冗余
- 后端冒烟：`python main.py` 启动后访问 `http://127.0.0.1:8000/api/health` 应返回 `{"status":"ok"}`
- 前端类型检查：`cd frontend && npx vue-tsc --noEmit` 必须 0 error
- 前端构建：`cd frontend && npm run build` 必须成功
- **新增行为必须有验证**（详见 `.harness/docs/dev-workflow.md`）：
  - 后端：手测对应 API；可补充 `pytest` 用例
  - 前端：手测 UI；类型检查 + 构建为底线

## PR & commit conventions

- 从 `main` 拉特性分支（如 `feat/round2-jd` / `fix/<scope>` / `chore/<scope>`）
- **永远不要直接 push 到 `main`** — 用 PR/MR 合并
- 提交信息遵循 conventional commits（`feat:` / `fix:` / `docs:` / `refactor:` / `chore:` / `test:`）
- 范围限定：消息中标注 round 编号（如 `feat(round2#2): JD 解析`）

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