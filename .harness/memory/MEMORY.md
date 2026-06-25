# 简历帮 — 团队共享记忆

> 跨 round 沉淀的项目级事实，orchestrator / developer / tester 都可读写。
> 私人化的偏好 / 个人数据**不放这里**，放个人 agent memory。

## 项目里程碑

- **2026-06-24**：Round 1 MVP 完成（commit `b2e5dbf`）— 4 项目 + 7 技能组 + 3 荣誉 + 1 证书，基础 docx 生成 + 强制预览
- **2026-06-24**：PII scrub + private backup 隔离（commit `cca78a3`）
- **2026-06-24**：README 隐私/部署边界声明（commit `4e3f1e9`）
- **2026-06-25**：Round 2 #1 — 启用全部 6 个 role 方向（commit `14fc0eb`）
- **2026-06-25**：README 当前能力表同步（commit `0467b29`）

## 技术栈定型

- 后端：Python + FastAPI + python-docx + pymupdf
- 前端：Vue 3 + TypeScript + Vite + Element Plus + axios
- 不引入：ESLint / Prettier / Vitest / pytest（**用户偏好**：保持栈精简，避免配置膨胀）
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
| P1 | Round 2 #2：JD 解析 / 匹配度评分 | 待启动 |
| P1 | Round 2 #3：LLM 智能改写项目描述 | 待启动 |
| P2 | Round 3：求职信 / 模板库 / 历史偏好 | 远期 |
| P3 | 云端部署 / 多端同步 | 暂停（等用户明确启动） |

## 已知陷阱

- `App.vue` 的 `defaultActive` 是手写 list（如 `['education', 'project_group', 'skills']`），加新 section type 时记得同步
- `ROLE_DISPLAY` 在 `backend/api/resume.py` 顶部，与 `ROLE_CONFIG` 分离 — 加新 role 时**两处都要改**
- `materials.json._meta.source_files` 是历史简历文件名（脱敏版用了占位符），改 schema 时记得保持这个字段
- 前端 `axios` 报错信息走 `e?.response?.data?.detail ?? e?.message ?? '未知错误'` — 后端 HTTPException 的 `detail` 会原样展示，不要在那里塞 PII

## 改动记录（重要决策）

- **2026-06-24**：决定不引入 pytest — Round 1 以手测为主，pytest 配置成本高于价值
- **2026-06-24**：决定 frontend 不加 ESLint — Vite 默认够用，配 ESLint 收益小
- **2026-06-24**：决定 `materials.json` 公开脱敏 + 真实数据走 `_private_backup.json`（`.gitignore`）
- **2026-06-25**：决定 frontend 用 Element Plus 而不是自研组件 — 节省 UI 工作量
- **2026-06-25**：决定强制两段式（preview → generate）— 防止用户投错简历