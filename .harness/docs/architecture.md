# 简历帮 — 架构与目录约定

> 本文档解释仓库每个目录 / 关键文件的用途与边界。新成员 / 新 agent 必读。

## 高层架构

```
┌────────────────────────────────────────────────────────────┐
│  浏览器 (Vue 3 SPA)                                        │
│  ─ App.vue (三段式: select → preview → done)               │
│  ─ Element Plus 组件库                                    │
│  ─ axios 调用 /api/*                                      │
└──────────────────────┬─────────────────────────────────────┘
                       │  HTTP /api/*  (vite proxy :5173 → :8000)
                       ▼
┌────────────────────────────────────────────────────────────┐
│  FastAPI 后端 (Python 3.x)                                │
│  ─ main.py        : FastAPI app + CORS + 路由挂载         │
│  ─ api/           : HTTP endpoints (materials / resume)   │
│  ─ core/          : 业务逻辑（generator.py 是核心域）      │
│  ─ data/          : 素材库 JSON（单人唯一真源）             │
│  ─ output/ logs/  : 运行时产物（.gitignore）               │
└────────────────────────────────────────────────────────────┘
```

## 目录详表

### 仓库根

| 文件 / 目录 | 用途 |
|---|---|
| `README.md` | 用户面向文档：项目说明、能力表、启动方式、目录结构、隐私声明 |
| `AGENTS.md` | AI agent 协作规范（你正在读的） |
| `.gitignore` | 排除运行时产物与个人素材 |
| `.harness/` | Mavis agent 团队配置（见本文末） |
| `.mavis/plans/` | Round 设计文档 / 决策（不进 `.harness`，独立保留） |
| `backend/` `frontend/` | 见下 |
| `简历帮知识库/` | 个人素材草稿（`.gitignore`，不入库） |

### `backend/`

| 文件 / 目录 | 用途 | 谁改 |
|---|---|---|
| `main.py` | FastAPI 入口、CORS、路由挂载 | developer（小改） |
| `api/materials.py` | 素材库 CRUD（`/api/materials`） | developer |
| `api/resume.py` | 预览 / 生成 / 角色列表（`/api/resume`） | developer |
| `core/generator.py` | **核心域**：sections 构造 + python-docx 渲染 | developer（小心） |
| `core/logger.py` | `backend/logs/generation.log` 写入 | developer |
| `data/materials.json` | **素材库真源**（公开脱敏版） | developer（schema 演进） |
| `data/_private_backup.json` | **真实数据备份**（`.gitignore`） | 用户手动管理 |
| `output/` `logs/` `__pycache__/` | 运行时产物（`.gitignore`） | 自动 |

### `frontend/`

| 文件 / 目录 | 用途 |
|---|---|
| `src/App.vue` | 三段式主界面（443 行，单文件组件） |
| `src/api/index.ts` | axios 封装：`materialsApi` / `resumeApi` + 类型导出 |
| `src/main.ts` | Vue 3 入口 |
| `index.html` | Vite 模板 |
| `vite.config.ts` | 端口 5173，`/api` 代理到 8000 |
| `tsconfig.json` | `strict: true` 启用 |
| `package.json` | 依赖：vue 3.5 / element-plus 2.9 / axios 1.7 |
| `node_modules/` `dist/` | `.gitignore` |

### `.harness/`

| 路径 | 用途 |
|---|---|
| `agent.md` | Orchestrator 路由规则 |
| `reins/developer/agent.md` | 全栈实施者 |
| `reins/tester/agent.md` | 验证守门员 |
| `docs/architecture.md` | 本文件 |
| `docs/dev-workflow.md` | 开发节奏与验证清单 |
| `docs/privacy-deploy.md` | 隐私 / 部署边界 |
| `memory/MEMORY.md` | 跨 round 共享记忆 |

## 核心域：`core/generator.py`

这是整个项目**最复杂、最容易改坏**的文件。改前必读：

- `ROLE_CONFIG` — 6 个 role 的配置（intention / fallback 顺序 / section 开关）
- `ENABLED_ROLES` — 当前启用的 role 列表（Round 2 #1 起启用全部 6 个）
- `preview_resume()` — 构造 sections 字典，**不写文件、不写日志**
- `generate_resume_docx()` — 调用 `python-docx` 写入 `.docx`
- **fallback 链**：`test_qa → tech_metric → general`（role 没匹配到项目时的兜底）

### 角色清单

| id | 显示名 | 风格 |
|---|---|---|
| `tech_metric` | 大模型技术度量 | 评测严谨 / 方法论导向 |
| `product` | AI 产品经理 | 用户视角 / 场景驱动 |
| `algorithm` | 医疗 AI 算法 | 模型复现 / 架构对比 |
| `data_annot` | 大模型数据标注 | 准确率导向 / SOP 严谨 |
| `test_qa` | AI 测试 / QA | 指标体系 / Badcase 归因 |
| `general` | 日常实习(通用) | 全面展示 / 不偏科 |

## API 速查

| Method | Path | 用途 |
|---|---|---|
| GET | `/` | 服务元信息 |
| GET | `/api/health` | 健康检查 |
| GET | `/api/resume/roles` | 启用角色列表 |
| POST | `/api/resume/preview` | 预览（不写文件） |
| POST | `/api/resume/generate` | 生成 .docx（写 `output/` + `logs/`） |
| * | `/api/materials/...` | 素材库 CRUD |

> API 文档自动生成于 `/docs`（Swagger UI）。

## 系统架构图与数据流（补全版）

> 上面的「高层架构」与「目录详表」偏目录约定（仅覆盖 materials/resume 两路由）。
> 完整的**系统分层架构图（Mermaid）+ core 模块职责表 + 四条数据流时序图（主生成 / JD 评分 / R5-C Agent / R6 面试 Agent）+ 安全隐私约束**，见：

- `system-architecture.md`（本目录，与仓库根 `架构设计文档.md` 同步）
- 仓库根 `架构设计文档.md`（同一份内容的副本）

**维护提醒**：`generator.py` / `jd_*` / `agent_*` / `interview_*` 等核心模块发生变动时，需同步更新 `system-architecture.md` 中的模块职责表与对应数据流时序图（节点名与代码实体一一对应）。