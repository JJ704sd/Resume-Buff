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

## Round 3 E 当前能力(2026-06-26)

| 功能 | 状态 |
|---|---|
| 素材库(4 项目 + 7 技能组 + 3 荣誉 + 1 证书) | ✅ |
| 6 个岗位方向(度量/产品/算法/标注/测试/通用) | ✅ |
| 生成预览(按模块)+ fallback 链(test_qa → tech_metric → general) | ✅ |
| 本地日志 `backend/logs/generation.log` | ✅ |
| JD 解析(关键词 + 经验 + 学历 + **tier 分组**) + 加权 0-100 匹配度评分 + **业务阈值 banner (高≥80 / 中 60-79 / 低<60)** | ✅ Round 2 #2 + R3-A |
| LLM 智能改写项目描述(无 key 静默降级,OpenAI 兼容 HTTP) | ✅ Round 2 #3 |
| **简历模板库**(5 套排版:`classic` / `single_column` / `two_column` / `minimal` / `technical`,前端 radio 切换 + 后端 layout dispatcher + docx 视觉差异) | ✅ Round 3 J |
| **CI 验证(pre-push hook 自动 pytest + vue-tsc + build)** | ✅ Round 3 E |

---

## 8 要素 × Round 3-A 落地表

| 要素 | Round 1 → Round 3-A 增量 |
|---|---|
| **1. 任务边界** | 本 README 顶部"做/不做"清单;`ENABLED_ROLES` 写死,**Round 2 启用 6 个 role**(度量/产品/算法/标注/测试/通用) |
| **2. 上下文** | Round 1 用"素材库 + role 模板";**Round 2 加 JD 文本解析**(skill/tool/domain/experience/education 5 维度)+ LLM 改写上下文(target_role + jd_context) |
| **3. 工具** | python-docx(写 docx) + pymupdf(读 docx/pdf) + FastAPI + Vue 3 + Element Plus + **OpenAI 兼容 HTTP(urllib stdlib,无第三方包)** + jieba-ready(预留 Round 3) |
| **4. 权限** | 本地单用户;素材库和输出目录按 user 权限隔离(不需要账号系统) |
| **5. 人工确认** | 强制两段式:`POST /preview` → 渲染 → `POST /generate`;**Round 2 加 JD 评分卡预览**(0-100 分 + 三维覆盖率 + 命中/缺失关键词);**R3-A 加业务阈值 banner**(高≥80 / 中 60-79 / 低<60,与 scoreColor/scoreTag 阈值一致) |
| **6. 评测** | Round 1 仅"事实覆盖自检";**当前 88 个 pytest 用例**(53 jd_parser + 3 api_jd + 16 llm_rewriter + **16 generator_layouts**),含 R2#1 baseline 锁死 + R3-A 加权 score/tier/recommendation/bugfix 回归 + R3-J layout dispatcher 视觉差异回归 |
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
│   │   └── test_generator_layouts.py # 16 pytest 用例(R3-J 5 套 layout dispatcher + 视觉差异 + invalid + backward-compat)
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

### 🎯 Round 3 后续候选(等用户拍)
- **R3-B**: LLM prompt 模板库 — 按 role 区分 system prompt(产品/算法/度量风格差异)
- **R3-C**: LLM 缓存层 — 同 role+intention+bullet 复用上次改写,省 token
- **R3-D**: 求职信 / 自我介绍生成 — README 之前提的能力,`.docx` 多一份输出
- **R3-F**: 异步化 + 评测强化 — Round 2 #3 已知限制 + 8 要素 #6
- **R3.5**: 阈值调优 — 用真实 JD 数据校准 80/60 阈值(R3-A 当前是占位)

### 📌 默认不启动(长期 P3,等用户明确)
- 多端同步、云端部署、账号系统、多用户协作
