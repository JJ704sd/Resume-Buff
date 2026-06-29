# 简历帮 (Resume-Buff)

个人简历助手:用一份结构化素材库,按岗位和 JD 生成多份针对性 `.docx` 简历。

本项目是本地单用户工具。`PUT /api/materials` 当前无鉴权,不要直接暴露到公网。公开仓库中的 `backend/data/materials.json` 是脱敏示例数据;真实个人数据应只保留在本地。

## 当前状态

- GitHub 仓库:`JJ704sd/Resume-Buff`
- 默认分支:`main`
- 当前功能基线:**R6-A Phase 1+2+3+5 脚手架全部完成**(后端 `interview_agent` 状态机 + save-card 写库闭环 + 前端右侧 chat panel / 移动端 drawer + eval 脚本 offline 实测 `total=10` 跑通;Phase 4 LLM 抽取未启动);R5-E 4 phase 全部完成(`scripts/evaluate_prompt_versions.py --mode {offline,live,auto}` + 4 个 prompt version 注册表 + 可选 LLM-as-Judge;**手动脚本,默认仍 offline**);R5-D 6 phase 真实 LLM eval 闭环延续
- **默认 prompt 仍为 `v2-baseline`**:R5-E 新增 3 个候选 prompt (v3-priority / v4-counterexample / v5-minimal) 属实验,本轮**不 rollout winner**,后续基于 live A/B 报告决定
- 后端测试基线:**729 passed + 0 skipped**
- 真实 LLM eval (`scripts/evaluate_prompt_versions.py --mode live` / `scripts/evaluate_agent_workflow.py --mode live`) 是手动脚本,不进入默认启动流程;`scripts/evaluate_interview_agent.py --mode live` 脚本内显式拒绝(Phase 4 未启)
- 详细开发锁点:见 [AGENTS.md](AGENTS.md)
- 阶段记录和路线图:见 [.harness/docs/ROADMAP.md](.harness/docs/ROADMAP.md)

## 核心能力

- 素材库管理:把项目、技能、荣誉、证书沉淀为唯一事实源。
- 岗位定制:支持度量、产品、算法、标注、测试、通用等方向。
- JD 匹配评分:解析 JD 关键词、经验、学历和领域要求,输出 0-100 匹配度和高/中/低建议。
- 简历预览与生成:先预览模块内容,人工确认后再生成 `.docx`。
- 模板选择:内置 classic、single_column、two_column、minimal、technical、academic、internet、bilingual 等排版。
- 外部简历视角:可解析外部简历文本,对比 JD 与素材库覆盖情况。
- 可选 LLM 改写:有 key 时改写项目亮点,无 key 时静默降级为原文。
- **JD 驱动简历面试官 (R6-A Phase 1+2+3)**:粘贴 JD → 系统选一个最值得补的缺口 → 一问一答 → 生成 draft_card → 用户编辑 → 写回素材库(`save_card` 原子写闭环)→ 触发预览与评分刷新;桌面右侧 380px 聊天栏 / 移动端全屏 drawer;规则版槽位抽取(不调 LLM)。
- **Prompt 版本化 + A/B 评测 harness (R5-E)**:默认 prompt 仍是 `v2-baseline`;新增 3 个候选 prompt 版本 (`v3-priority` / `v4-counterexample` / `v5-minimal`) 属实验,`scripts/evaluate_prompt_versions.py --mode offline` 跑 12 JD × 4 version 对比,**手动脚本不进入默认启动流程**;可选 `--judge on` 启用 LLM-as-Judge 评分。
- Agent workflow 诊断:默认关闭;开启后可查看 evidence、工具摘要、bullet 评估、trace replay 等诊断信息。

## 不做什么

- 不自动投递。
- 不爬招聘网站,JD 由用户粘贴。
- 不追踪 HR 或面试进度。
- 不做账号、多用户或云端协作。
- 不替代人工确认,下载前仍需要用户 review。

## 快速启动

后端:

```bash
cd backend
pip install -r requirements.txt
python main.py
```

后端默认地址:`http://127.0.0.1:8000`

前端:

```bash
cd frontend
npm install
npm run dev
```

前端默认地址:`http://127.0.0.1:5173`

本地使用流程:

1. 启动后端和前端。
2. 打开 `http://127.0.0.1:5173`。
3. 选择岗位方向和模板。
4. 可选:粘贴 JD、上传外部简历、开启 Agent workflow 诊断。
5. 点击预览,确认内容后下载 `.docx`。

## 配置

- 素材库:`backend/data/materials.json`
- 本地私有备份建议:`backend/data/_private_backup.json` (已被 `.gitignore` 忽略)
- LLM 配置模板:`backend/.env.example`
- 输出目录:`backend/output/` (本地保留,不入库)
- 运行日志:`backend/logs/` (本地保留,不入库)

常用环境变量:

```bash
LLM_ENABLED=true
LLM_API_KEY=your_key
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=your_model
```

## 验证

后端全量测试:

```bash
cd backend
D:\python3.11\python.exe -m pytest tests/ -v
```

前端类型检查和构建:

```bash
cd frontend
npx vue-tsc --noEmit
npm run build
```

安装 pre-push hook:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/install-hooks.ps1
```

## 项目结构

```text
backend/
  main.py                 FastAPI 入口
  api/materials.py        素材库 CRUD
  api/resume.py           预览、生成、角色列表
  core/generator.py       sections 构造和 docx 渲染
  core/jd_parser.py       JD 解析、匹配评分、外部简历对比
  core/agent_workflow.py  Agent workflow 编排
  core/agent_tools.py     Agent 工具注册和权限校验
  core/evidence.py        轻量 evidence 检索
  data/materials.json     脱敏示例素材库

frontend/
  src/App.vue             主界面
  src/api/index.ts        API 类型和 axios 封装
  vite.config.ts          /api 代理到后端

scripts/
  replay_agent_trace.py   Agent trace 回放
  evaluate_agent_workflow.py  R5-D 离线评测报告 (FC × AW 4 开关对照)
  evaluate_prompt_versions.py  R5-E Prompt A/B 评测 (4 prompt version 对比 + 可选 judge)
  evaluate_interview_agent.py  R6-A Phase 5 interview agent 评测 (脚手架; live mode 脚本内拒绝,Phase 4 未启)
  verify.ps1             本地验证脚本

.harness/
  docs/                  架构、路线图、阶段报告
  memory/                协作记忆
```

## JD 资料库

仓库包含个人用 AI 岗位 JD 资料库和评估脚本:

- `AI岗位JD库_v4_intern.json`
- `AI岗位JD库_v4_intern_筛选报告.md`
- `AI岗位JD库_v4_黄金标的match报告.md`
- `scripts/build_v4.py`
- `scripts/score_intern_match.py`
- `scripts/match_golden_targets.py`

扩库时优先更新脚本中的数据源,再重新生成 JSON 和报告。
