# 简历帮 (Resume-Buff)

个人简历助手:用一份结构化素材库,按岗位和 JD 生成多份针对性 `.docx` 简历。

本项目是本地单用户工具。`PUT /api/materials` 当前无鉴权,不要直接暴露到公网。公开仓库中的 `backend/data/materials.json` 是脱敏示例数据;真实个人数据应只保留在本地。

## 当前状态

- GitHub 仓库:`JJ704sd/Resume-Buff`
- 默认分支:`main`
- 当前功能基线:**R6-G review-needed 3 项整理完成**(commit `ae0e89b`,2026-07-03):F-2.1 verifier sentinel 失败提示 / F-2.2 llm envelope 重复 except hygiene 清理 / F-2.3 stderr 错误信息脱 `LLM_API_KEY` 字面量 / `sk-` 前缀 / `Bearer` 头;+12 pytest,936 → **948 baseline**;**R6-F closeout 全部完成**(commit `a3f48b1`,docs-only + UI chip fix + 临时文件清理,0 P0/0 P1 真实 bug);**R6-E 全部完成**(Phase 1 文档同步 + Phase 4 `_do_answer` slot 优先读 `question_plan` 决策 bug fix,commit `7fe798c`);**R6-C.1+ C.2A+ C.2B+ C.3 + R6-D 全部完成**(R6-C: eval contract warnings / product_goal + contract_note / policy gap-critical slot step 4.5 / LLM 抽取可观测性 + `response_format=json_object` + prompt few-shot 优化;R6-D: 机械拆分 LLM slot 抽取到 `backend/core/interview_llm.py`,行为不变 0 新测试);**R6-B Phase 0+1+2+3+4+5+6 可信增强层全部完成**;**R6-A Phase 1+2+3+4+5 全部完成**(LLM slot extraction 已上线,phase 4 启动 1/3);R5-E 4 phase 全部完成(`scripts/evaluate_prompt_versions.py --mode {offline,live,auto}` + 4 个 prompt version 注册表 + 可选 LLM-as-Judge;**手动脚本,默认仍 offline**);R5-D 6 phase 真实 LLM eval 闭环延续
- **默认 prompt 仍为 `v2-baseline`**:R5-E 新增 3 个候选 prompt (v3-priority / v4-counterexample / v5-minimal) 属实验,本轮**不 rollout winner**,后续基于 live A/B 报告决定
- **interview agent 默认仍走 rules 路径**:`enable_interview_llm=False` 时 R6-A 行为字节级一致;**R6-D 后 LLM 抽取代码已搬到 `core/interview_llm.py`**,`core/interview_agent.py` 通过重导出保持向后兼容;前端"智能抽取"toggle 默认关闭;有 key 时回退规则模式显示 warning
- 后端测试基线:**948 passed + 0 skipped**(2026-07-03 R6-G 收尾实测 117.94s;R5-E Phase 3 收尾 683 → R6-A Phase 1+2+3+5 → 729 → R6-A Phase 4 → 739 → R6-B Phase 0+1+2 → 768 → Phase 3 → 809 → Phase 4 → 840 → Phase 5 → **863** → R6-C.1 → **877** → R6-C.2A → **889** → R6-C.2B → **909** → R6-C.3 → **930** → R6-E Phase 4 → **936** → R6-G → **948**)
- 真实 LLM eval (`scripts/evaluate_prompt_versions.py --mode live` / `scripts/evaluate_agent_workflow.py --mode live` / `scripts/evaluate_interview_agent.py --mode live`) 是手动脚本,不进入默认启动流程
- **文档一致性**:R6-G closeout:本地与 `origin/main` ahead 3 commits(`ae0e89b` / `a3f48b1` / `7811973` 三个 ahead,推送前需用户授权);**948 baseline** 已写入 `AGENTS.md` / `.harness/docs/ROADMAP.md` / `.harness/memory/MEMORY.md`;R6-H live eval v2 决策门禁 spec 已落档 `.harness/docs/round6-h-live-eval-v2-decision-gate-spec.md`(draft,等用户跑完 10+ 轮真实对话后启动 Phase 2 跑分);R6-F 项目回顾 + bug 审核报告见 `.harness/docs/round6-f-project-review-bug-audit-spec.md` + `.harness/docs/round6-f-project-review-bug-audit-report.md`
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
- **JD 驱动简历面试官 (R6-A 全 5 phase + R6-B 全 6 phase + R6-C 4 阶段 + R6-D 行为不变重构)**:粘贴 JD → 系统选一个最值得补的缺口 → 一问一答 → 生成 draft_card → 事实核验 + 低置信度提示 → 用户编辑 → 写回素材库(`save_card` 原子写闭环)→ 触发预览与评分刷新;桌面右侧 380px 聊天栏 / 移动端全屏 drawer;**R6-A Phase 4 LLM slot extraction 已上线(默认关闭,有 key 时回退规则模式 warning)** + **R6-B 可信增强层(slot_meta provenance / API mode 开关 / confidence-aware deterministic policy / draft verifier / eval compare / 前端最小呈现)** + **R6-C 评测合同化(eval contract warnings 段 + `product_goal`/`contract_note` 语义区分 + policy gap-critical slot step 4.5 三轮可达 + LLM 抽取可观测性 `slot_source_breakdown`/`retries`/`fb_to_rules` 3 字段)** + **R6-D 模块拆分(LLM slot 抽取代码搬到 `backend/core/interview_llm.py`,`interview_agent.py` 通过重导出保持向后兼容,行为不变)**。
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
  evaluate_interview_agent.py  R6-A Phase 5 + R6-B Phase 5 + R6-C.1 + C.2A + C.3 interview agent 评测 (--extractor {rules,llm,compare}; offline compare 双组同跑; live mode 脚本内拒绝; R6-C.1 新增 `## 4.5 Eval contract warnings` 章节按 sample 去重列 unreachable / beyond-3 warning;R6-C.2A 新增 `## 4.6 Eval contract: product goal` 章节按 `product_goal` 分工区分 `three_turn_friendly` / `full_fact_coverage`;R6-C.3 新增 `## 4.7 LLM 抽取可观测性` 章节含 `slot_source_breakdown` (rules/llm/mixed) + `llm_parse_retry_count` + `llm_to_rules_slot_fallback_count` 全局 / 按 source / 按 extractor (compare 模式) 拆分聚合;LLM slot 抽取代码在 R6-D 后位于 `core/interview_llm.py` 但评测脚本仍走 `core.interview_agent` 重导出符号调用)
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
