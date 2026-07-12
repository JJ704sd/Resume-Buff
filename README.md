<div align="center">

# 🚀 简历帮 · Resume-Buff

**一份结构化素材库，按岗位方向和 JD 一键生成多份针对性简历。**

[English](#english) · 本地单用户工具 · 不做任何爬虫、不做任何投递、不做任何云端同步

</div>

<div align="center">

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)
![Vue](https://img.shields.io/badge/Vue-3.5+-4FC08D?logo=vuedotjs&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.134-009688?logo=fastapi&logoColor=white)
![pytest](https://img.shields.io/badge/pytest-948%20passed-0A9B7C?logo=pytest&logoColor=white)
![License](https://img.shields.io/badge/license-MIT--style-lightgrey)
![Local--only](https://img.shields.io/badge/run-localhost--only-blueviolet)

</div>

---

## ✨ 这是什么

投实习时,你大概率会准备 **6 个岗位方向 × 多份针对性简历**:技术度量 / 算法 / 产品 / 数据标注 / 测试 / 通用。
每份都要从同一份项目经历里挑不同项目、换不同表达、套不同模板。

**简历帮做的事** —— 把"项目 / 技能 / 荣誉 / 证书"沉淀为唯一事实源,按岗位和 JD 自动选材 + 排版 + 生成 `.docx`。

> 简历帮 ≠ 简历生成器,它是一个**带 JD 匹配评分和面试官补全**的个人投简历工具。

---

## 🎯 核心能力

| 模块 | 能做什么 |
| :--- | :--- |
| 📚 **素材库** | 一次维护,所有简历共享。结构化存储项目 / 技能 / 荣誉 / 证书。 |
| 🎯 **岗位定制** | 6 个方向 `tech_metric` / `product` / `algorithm` / `data_annot` / `test_qa` / `general`,每个角色自动选最匹配的项目。 |
| 📄 **8 套模板** | `classic` / `single_column` / `two_column` / `minimal` / `technical` / `academic` / `internet` / `bilingual`,支持学术 / 互联网 / 中英双语等不同风格。 |
| 🔍 **JD 匹配评分** | 粘贴 JD → 解析关键词 / 经验 / 学历 → 0-100 匹配度 + 高/中/低建议 + 缺什么补什么。 |
| 📎 **外部简历对比** | 上传你已有的 `.docx` / `.pdf` 简历,自动对比"你有但素材库没有"和"素材库有但你没写"。 |
| ✍️ **预览 → 确认 → 下载** | 先看模块内容,人工确认后再生成 `.docx`,所见即所得,改完再下载。 |

<details>
<summary><b>🤖 进阶能力(可选,不影响主流程)</b></summary>

- **🧠 可选 LLM 改写** — 有 `LLM_API_KEY` 时改写项目亮点;无 key 时**静默降级**为原文,不出错不卡住。
- **🛰️ Agent Workflow 诊断** — 默认关闭。开启后预览页出现 evidence / 工具摘要 / bullet 评估 / trace 回放,适合想知道"系统到底跑了啥"的开发者。
- **💬 JD 驱动简历面试官** — 粘贴 JD,系统挑一个最值得补的缺口 → 一问一答 → 生成 `draft_card` → 事实核验 + 低置信度提示 → 你编辑 → 写回素材库。下次再投类似岗位,这条素材已经在库里。**desktop 380px 侧栏 / 移动端全屏 drawer。**
- **🧪 离线评测 harness** — 4 个评测脚本:`replay_agent_trace.py` / `evaluate_agent_workflow.py` (4 开关对照) / `evaluate_prompt_versions.py` (4 prompt 对比 + 可选 judge) / `evaluate_interview_agent.py` (规则 vs LLM)。**手动跑,不入默认启动流程。**

</details>

---

## 🚀 快速开始

### 1. 启动后端

```bash
cd backend
pip install -r requirements.txt
python main.py
```

> 默认地址:`http://127.0.0.1:8000`
> 健康检查:`curl http://127.0.0.1:8000/api/health` → `{"status":"ok"}`

### 2. 启动前端

```bash
cd frontend
npm install
npm run dev
```

> 默认地址:`http://127.0.0.1:5173`

### 3. 五步生成你的第一份简历

1. 打开 `http://127.0.0.1:5173`,从左侧选**岗位方向**(如 `tech_metric`)。
2. 选**模板**(如 `classic` 或 `academic`)。
3. *(可选)* 在 JD 框粘贴目标岗位的 JD,点"匹配评分"看 0-100 分 + 缺什么。
4. 点"预览",看模块内容,不满意可改素材库或换模板。
5. 满意后点"下载",得到 `.docx` 文件。

> 💡 第一次没素材很正常,前端右上角有"素材库"入口,把所有项目 / 技能 / 证书一次性填进去就行。

---

## 🎨 岗位方向 & 简历模板

| 岗位方向 (`role_id`) | 意图 | 主推项目 | 适用 |
| :--- | :--- | :--- | :--- |
| `tech_metric` | 大模型技术度量实习 | 医疗评测 / ECG / Datawhale | AI Eval / 评测岗 |
| `product` | AI 产品经理实习 | 医疗评测 / Datawhale | AI PM 岗 |
| `algorithm` | 医疗 AI 算法实习 | ECG / 医疗评测 | 算法岗 |
| `data_annot` | 大模型数据标注实习 | 医疗评测 / Datawhale | 标注 / 数据岗 |
| `test_qa` | AI 测试 / QA 实习 | 医疗评测 / ECG | 测试 / QA 岗 |
| `general` | 通用 | 全部 | 不确定方向时 |

| 模板 (`template_id`) | 风格 | 适用 |
| :--- | :--- | :--- |
| `classic` | 经典单栏 | 通用 |
| `single_column` | 紧凑单栏 | 互联网公司 |
| `two_column` | 左右双栏 | 节省页数 |
| `minimal` | 极简 | 突出项目本身 |
| `technical` | 技术风 | 算法 / 研发岗 |
| `academic` | 学术 CV | 学术申请 / 研究岗 |
| `internet` | 互联网简洁 | 字节 / 阿里 style |
| `bilingual` | 中英双语 | 跨境 / 外企 |

---

## 🗂️ 项目结构

```text
简历帮/
├── backend/                     # FastAPI 后端
│   ├── main.py                  # 入口
│   ├── api/                     # materials / resume / jd / interview 4 个路由
│   ├── core/                    # generator / jd_parser / agent_* / interview_* 业务核心
│   ├── data/materials.json      # 脱敏示例素材库(真实数据走 _private_backup.json)
│   └── tests/                   # 948 个 pytest
│
├── frontend/                    # Vue 3 + Vite 单页
│   ├── src/App.vue              # 主界面
│   ├── src/components/          # 聊天 / 上传 / 进度条
│   └── src/api/index.ts         # API 封装 + 类型
│
├── scripts/                     # 4 个评测 + trace 回放 + JD 库构建
│   ├── replay_agent_trace.py
│   ├── evaluate_agent_workflow.py
│   ├── evaluate_prompt_versions.py
│   ├── evaluate_interview_agent.py
│   ├── build_v4.py              # JD 库构建
│   └── verify.ps1               # 本地全量验证
│
├── AI岗位JD库_v4_intern.*       # 个人用 AI 岗位 JD 资料库(86 份,4 级实习匹配)
│
├── AGENTS.md                    # 给 AI agent 看的开发手册(★ 内部信息)
└── README.md                    # 你正在看
```

---

## 🔍 AI 岗位 JD 资料库

仓库自带一份**个人用 AI 岗位 JD 资料库**,86 份分 4 级(strong / campus_to_intern / weak / none),附匹配评分实测。

- `AI岗位JD库_v4_intern.json` — 主库(86 份 JD)
- `AI岗位JD库_v4_intern_筛选报告.md` — 4 级规则 + 52 份实习可投清单
- `AI岗位JD库_v4_黄金标的match报告.md` — 黄金 JD × 6 role 实测对比
- `scripts/build_v4.py` / `score_intern_match.py` / `match_golden_targets.py` — 扩库 / 打标 / 实测脚本

> 投递前,把目标 JD 全文跑一次 `match_score(text, role, materials)`,先看素材库匹配度,缺什么再补什么。

---

## 🛠️ 开发与测试

```bash
# 后端全量测试(948 个用例,约 16s)
cd backend
D:\python3.11\python.exe -m pytest tests/ -q

# 前端类型检查 + 构建
cd frontend
npx vue-tsc --noEmit
npm run build

# 一键本地全量验证(后端 + 前端)
powershell -ExecutionPolicy Bypass -File scripts/verify.ps1
```

**可选 LLM 配置**(`backend/.env`):

```bash
LLM_ENABLED=true
LLM_API_KEY=your_key_here
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=your_model
```

> 没设 key 也能跑,所有 LLM 路径会**静默降级**为规则版,不影响主流程。

**安装 pre-push hook**:`powershell -ExecutionPolicy Bypass -File scripts/install-hooks.ps1`

---

## 🔒 隐私与边界

**项目只做这些:**

- 在你本机 8000 / 5173 端口跑
- 读你维护的 `materials.json`,写 `.docx` 到本地 `output/`
- 评估脚本读 JD 库,生成 Markdown 报告到 `backend/logs/`

**项目明确不做这些:**

- ❌ 不自动投递
- ❌ 不爬招聘网站(JD 由你粘贴)
- ❌ 不追踪 HR / 面试进度
- ❌ 不做账号 / 多用户 / 云端协作
- ❌ 不替代人工确认,下载前你 review
- ❌ **不暴露公网** —— `PUT /api/materials` 无鉴权,只服务本地

**真实数据**:`backend/data/_private_backup.json`(.gitignore),clone 后 `cp` 一份到 `materials.json` 即用。

> 📖 详细隐私边界见 [`.harness/docs/privacy-deploy.md`](.harness/docs/privacy-deploy.md)。

---

## 📚 延伸阅读

| 你想知道… | 看这里 |
| :--- | :--- |
| 内部开发流程 / round 锁点 / pytest 边界 | [`AGENTS.md`](AGENTS.md) |
| 未来规划 / 各 round 设计文档 | [`.harness/docs/ROADMAP.md`](.harness/docs/ROADMAP.md) |
| 系统架构总览 | [`.harness/docs/system-architecture.md`](.harness/docs/system-architecture.md) |
| 隐私 / 部署边界细则 | [`.harness/docs/privacy-deploy.md`](.harness/docs/privacy-deploy.md) |
| 内部测试开发参考 | [`.harness/docs/resume-buff-test-development-interview-guide.md`](.harness/docs/resume-buff-test-development-interview-guide.md) |
| 内部架构详情 | [`.harness/docs/architecture.md`](.harness/docs/architecture.md) |

---

<div align="center">

Made with ❤️ for job-hunting season · 本地单用户工具,代码随用随改

</div>

<a id="english"></a>

## English Quick Reference

**Resume-Buff** — a local single-user resume assistant.

One structured `materials.json` (projects / skills / honors / certs) → pick a role (6 options) + a template (8 options) + optionally paste a JD → get a tailored `.docx` resume.

- **Backend:** Python 3.11+ / FastAPI / 948 pytest passing
- **Frontend:** Vue 3 + Vite + Element Plus
- **Privacy:** local-only, no auth, no cloud, no tracking. **Do not expose to public network.**
- **Optional LLM:** set `LLM_API_KEY` to enable smart rewrite / JD-driven interview agent. Without a key, everything silently falls back to rules.

See [`AGENTS.md`](AGENTS.md) for the full developer handbook.
