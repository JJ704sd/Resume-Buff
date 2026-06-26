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
- **2026-06-26**：Round 3-G（外部简历实时读取 + JD 评分联动）**cancelled** — 用户选完 scope 后主动叫停；worker 仍落地完整 MVP（**1467 行新增**），按 2026-06-26 hygiene 决策 **commit 到 `feat/r3g-resume-upload` 分支保留**（不 merge 不 push），重启时直接 cherry-pick
- **2026-06-26**：清理 `backend/output/` 6 个含真实 PII 的产物（陈佳豪 docx ×3 + audit_test + test_audit + preview_audit.json）— A 任务收尾
- **2026-06-26**：Round 3-J 完成 — 简历模板库（5 套排版 `classic` / `single_column` / `two_column` / `minimal` / `technical`），**88 个 pytest 用例全绿**（53 jd_parser + 3 api_jd + 16 llm_rewriter + **16 generator_layouts**），前端 radio 选模板 + 后端 `_LAYOUT_DISPATCH` 渲染分发 + 日志记 template
- **2026-06-26**：Round 3-E 完成 — pre-push hook（`scripts/verify.ps1` 全量 pytest + vue-tsc + build + `scripts/hooks/pre-push` 自动挡 push + `scripts/install-hooks.ps1` 一键 setup），用 `git config core.hooksPath scripts/hooks` 把 hook 目录指向仓库内可版本控制位置，Windows only（PowerShell 5.1），跳过用 `git push --no-verify`
- **2026-06-26**：Round 3-I 完成 — JD-driven generation（让评分卡的"准"真正落到生成结果里）。**新 `core/jd_ranker.py` 纯规则排序**（命中数倒序 + tie 维持原顺序，3 函数 `rank_projects` / `rank_highlights` / `rank_skill_groups`）；`generator.py` / `preview_resume` / `generate_resume_docx` 加可选 `jd_context` / `jd_text` 关键字参数（默认 None → 字节级一致）；`llm_rewriter.py` system prompt 加 matched 识别 + missing 不编造 + tier 引导（jd_focus=None 时 user message schema 完全不变）；`api/resume.py` PreviewRequest / GenerateRequest 加 jd_text 字段 + 422 校验（>50k 字符）；前端 `App.vue` 加 jdAware 复选框 + section 命中关键词角标。**113 个 pytest 全绿**（88 baseline + 25 新增），6 role 字节级 baseline hash 在 test 里固化锁死 jd_context=None 路径。**coder 在 wrap-up 阶段被 15min cap kill 但实施 100% 完成 + commit 已就位**；owner 接手 merge + 文档同步（coder 在 deliverable.md 标好 merge commit message 模板）

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
| P2 | Round 3.5：阈值调优 | ⏸️ 等用户在 `简历帮知识库/jd_samples.json` 补 ≥10 份 JD |
| P2 | Round 3-G：外部简历实时读取 + JD 评分联动 | ⏸️ Cancelled（2026-06-26；**MVP 1467 行 commit 在 `feat/r3g-resume-upload` 分支保留**） |
| P2 | Round 3-J：简历模板库（默认/单栏/双栏/简洁/技术） | ✅ 完成（5 套排版 + 16 测试，2026-06-26） |
| P2 | Round 3-E：CI 验证（pre-push hook） | ✅ 完成（2026-06-26） |
| P2 | Round 3-K：求职信（规则版，基于素材库 + role + JD） | ⏸️ 2026-06-26 暂缓：用户认为求职信在国内使用频率低，等真有人明确说"我要写求职信"再开 |
| P2 | Round 3-M：简历导出多格式（docx → pdf / md / html） | 待启动 |
| P3 | 云端部署 / 多端同步 | 暂停（等用户明确启动） |

## 已知陷阱

- `App.vue` 的 `defaultActive` 是手写 list（如 `['education', 'project_group', 'skills']`），加新 section type 时记得同步
- `ROLE_DISPLAY` 在 `backend/api/resume.py` 顶部，与 `ROLE_CONFIG` 分离 — 加新 role 时**两处都要改**
- `materials.json._meta.source_files` 是历史简历文件名（脱敏版用了占位符），改 schema 时记得保持这个字段
- 前端 `axios` 报错信息走 `e?.response?.data?.detail ?? e?.message ?? '未知错误'` — 后端 HTTPException 的 `detail` 会原样展示，不要在那里塞 PII
- `backend/output/` 容易堆积含真实姓名的 docx / json — 每次跑完生成记得用 mavis-trash 清 PII 文件（参考 2026-06-26 A 任务）

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
