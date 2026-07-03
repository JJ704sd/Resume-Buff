# Round 6-E: GitHub 同步 + Live Eval v2 决策门禁 Spec

> 适用项目: 简历帮 / Resume-Buff  
> 本地日期: 2026-07-02(起草) / 2026-07-03(closeout)  
> 状态: **closeout (2026-07-03 同步至 origin/main = 3b632c7)**  
> 推荐下一轮主题: 先把本地 R6-C/R6-D 成果同步成可审查状态, 再用真实前端对话数据决定是否继续投资 LLM slot 抽取优化。

---

## 0. 一句话结论

下一轮不应直接做 prompt 优化、retry 升级或 token 成本控制。第一性原理上, 本项目的价值不是“更多智能”, 而是把真实经历安全、可追溯、低摩擦地变成可复用简历素材。当前本地已经完成 R6-C/R6-D, 但 GitHub `origin/main` 仍停在 R6-B 收尾提交, README 也仍写着 863 baseline。继续写功能前, 需要先完成:

1. 本地/远端状态对齐: 让 R6-C/R6-D 进入一个可审查、可回退、可发布的 GitHub 状态。
2. 文档一致性对齐: README / AGENTS / ROADMAP / MEMORY / round 文档都指向同一个 930 baseline。
3. 真实 live eval v2: 用 10+ 轮前端 chat panel 真实对话样本, 跑 `--mode live --extractor compare`, 决定 LLM 抽取是否值得进入下一轮优化。

推荐命名: **R6-E: release sync + live eval v2 gate**。

---

## 1. 当前事实

### 1.1 本地 git 状态

本地仓库根目录: `D:\简历帮`

> **2026-07-03 closeout 更新**:本节初始取证(2026-07-02)记录的 `origin/main 落后 9 commit` 状态已过期。R6-E closeout 时(2026-07-03)`local HEAD = origin/main = 3b632c7`,已 sync(0 ahead / 0 behind)。R6-E Phase 4 `_do_answer` slot 对齐 Bug fix(commit `7fe798c`)经用户授权已 push 至远端。具体取证见 R6-F 报告 `.harness/docs/round6-f-project-review-bug-audit-report.md` §1.1 GitHub 状态当前事实段。
> 
> **原始取证(2026-07-02 起草时)** ↓

```text
branch: main
local HEAD: a03c8c0 docs(round6-c): refine live eval next-step plan + sync ROADMAP to 930 baseline
origin/main: 69ed431 docs(round6-b): fix stale baseline wording after phase 7 closeout
ahead/behind: origin/main...main = 0 behind / 9 ahead
untracked: .planning/面试讲解/
```

> **2026-07-03 closeout 状态**:HEAD = origin/main = `3b632c7`,已 sync(0 ahead / 0 behind);后续 R6-G 不应再把本节当现行事实引用。

本地领先远端 9 个提交:

```text
c4dc539 docs(round6-c): add live eval 操作指南
3b8b9d1 docs(round6-c): summarize live eval result and next steps
ea43473 feat(round6-c.1): eval contract warnings + live compare wording fix
a1a9fc2 feat(round6-c.2a): fix eval set contract
caab6ff feat(round6-c.2b): policy gap-specific critical slot 补足
651ea4e merge feat/round6-c.2b: policy gap-specific critical slot 补足 (路线 B)
84dd086 feat(round6-c.3): LLM 抽取可观测性 + prompt few-shot 优化
91ec8f3 feat(round6-d): 机械拆分 LLM slot 抽取模块 (行为不变)
a03c8c0 docs(round6-c): refine live eval next-step plan + sync ROADMAP to 930 baseline
```

`origin/main...main` diff 面:

```text
14 files changed, 5207 insertions(+), 1373 deletions(-)
new: .harness/docs/round6-c-live-eval-guide.md
new: .harness/docs/round6-c-live-eval-result-and-next-steps.md
new: backend/core/interview_llm.py
new: backend/tests/test_interview_llm.py
modified: AGENTS.md, ROADMAP, interview agent/policy/prompts/eval/tests
```

### 1.2 GitHub 远端状态

可靠确认:

```text
remote: https://github.com/JJ704sd/Resume-Buff.git
origin/main sha: 69ed431b72e9f5f14c233b2d66ea34ed39e32b38
origin/main date: 2026-06-30 22:22:09 +0800
remote heads: main + codex/r5b-doc-baseline + codex/r5c-agent-closeout + feat/round5-a-agent-phase1
```

受限项:

- `gh` 未登录, 无法用 CLI 查询 PR / issue / checks。
- GitHub app MCP 启动 handshake 超时。
- GitHub REST unauthenticated API 命中 rate limit / TLS handshake 错误。

因此本 spec 不把 “open PR/issue 数量” 写成确定事实。下一轮如果要创建 PR 或检查 issue, 需要先恢复 GitHub 认证或只走浏览器人工确认。

### 1.3 文档一致性现状

已对齐到 R6-D / 930 的位置:

- `AGENTS.md`
- `.harness/docs/ROADMAP.md`
- `.harness/docs/round6-c-live-eval-result-and-next-steps.md`

仍显著滞后的入口:

- `README.md` 顶部仍写 R6-B Phase 0-6 和 **863 passed + 0 skipped**。
- `README.md` scripts 列表仍描述 `evaluate_interview_agent.py` 为 R6-A/R6-B 口径, 未提 R6-C.1/C.2/C.3/R6-D。
- `.harness/memory/MEMORY.md` 未在本次取证中命中 R6-C/R6-D/930 关键词, 需要下一轮人工核对并同步。

### 1.4 代码边界现状

R6-D 后关键文件体量:

```text
backend/core/interview_agent.py: 1676 lines
backend/core/interview_llm.py: 613 lines
scripts/evaluate_interview_agent.py: 1826 lines
```

当前已完成的核心能力:

- R6-C.1: eval contract warnings + live compare wording fix。
- R6-C.2A: eval set product_goal / contract_note。
- R6-C.2B: policy gap-specific critical slots step 4.5。
- R6-C.3: LLM observability + response_format json_object + slot prompt few-shot。
- R6-D: LLM slot 抽取模块机械拆分, 行为不变。

当前活跃基线按 AGENTS / ROADMAP 为:

```text
backend tests: 930 passed + 0 skipped
frontend: vue-tsc --noEmit 0 error + npm run build success
offline compare: rules schema_pass=0.30 / llm intent schema_pass=0.30 / offline llm fallback_rate=1.00
```

---

## 2. 第一性原理

Resume-Buff 是本地单用户简历素材工具。下一轮决策应服从五条约束:

1. **真实性优先**: 没有用户来源的事实不能进入素材库。
2. **可追溯优先**: 智能抽取必须能解释来源, 但报告和持久化不能泄露原文。
3. **默认可用优先**: 没有 LLM key / 网络失败时 rules 路径仍必须完整可用。
4. **可审查优先**: 本地 9 个提交不应长期只存在于本机; 远端应能展示真实项目状态。
5. **证据优先**: 只有真实 live v2 证明 LLM 相比 rules 有质量收益, 才值得继续做 prompt/retry/token 优化。

由此推出: 下一轮的核心不是增加新行为, 而是建立 **发布同步 + 真实收益验证** 的门禁。

---

## 3. 方案取舍

### 方案 A: 直接做 LLM prompt / retry / token 优化

不推荐。R6-C.0 live compare 已显示 LLM 相比 rules 的 `schema_pass_rate` 和 `avg_completeness` delta 为 0。R6-C.3 虽补齐 observability, 但还没有真实前端 10+ 轮对话数据。此时优化 prompt 可能是在静态 eval set 上调参, 不能证明产品收益。

### 方案 B: 只做 GitHub push / PR, 不跑 live v2

不够。它能解决远端滞后, 但不能回答 R6-B/R6-C 一直悬着的问题: 智能抽取是否值得默认开放或继续投资。

### 方案 C: GitHub 同步 + 文档一致性 + live eval v2 gate

推荐。它把本地事实发布成可审查状态, 同时把下一步 LLM 投资建立在真实使用证据上。若 live v2 通过门槛, 再进入 R6-F prompt/retry/token 优化; 若不通过, 保持 rules 默认并转向文档/素材/评测集质量。

---

## 4. R6-E 范围

### Phase 0: 取证与冻结范围

目标:

- 再次确认 `main` 是否仍 ahead `origin/main` 9 个提交。
- 确认工作区除 `.planning/面试讲解/` 和本 spec 外没有未预期变更。
- 记录 `origin/main` 与 `main` 的 sha、提交列表、diff stat。
- 明确 GitHub 查询能力: `gh auth status` / GitHub app / REST API 是否可用。

不做:

- 不修改业务代码。
- 不 push。
- 不把 `.planning/面试讲解/` 入库。

### Phase 1: 文档一致性修复

目标:

- 更新 `README.md` 顶部当前状态:
  - R6-C.1/C.2A/C.2B/C.3 + R6-D 已完成。
  - backend baseline 改为 930 passed + 0 skipped。
  - `interview_llm.py` 已拆分, 默认仍 rules。
  - `evaluate_interview_agent.py` 已支持 contract warnings / product_goal / observability。
- 核对并更新 `.harness/memory/MEMORY.md`:
  - 记录 R6-C/R6-D 里程碑。
  - 记录 GitHub 远端仍滞后到 R6-B 的事实。
  - 记录 R6-E 下一步门禁。
- 保持 `AGENTS.md` 和 `ROADMAP.md` 不回退。

验收:

```powershell
Select-String -LiteralPath README.md,.harness\memory\MEMORY.md -Pattern "863|R6-B Phase 0+1+2+3+4+5+6" -Context 1,1
```

预期: 不再把 863 / R6-B 当作当前活跃基线。

### Phase 2: 本地验证

目标:

- 证明 R6-C/R6-D 在当前机器上仍可复现。
- 证明 README/MEMORY 文档修复没有伴随业务代码变更。

命令:

```powershell
cd backend
D:\python3.11\python.exe -m pytest tests/ -q

cd ..\frontend
npx vue-tsc --noEmit
npm run build

cd ..
D:\python3.11\python.exe scripts/evaluate_interview_agent.py --mode offline --extractor compare --output backend/logs/interview_eval_report_r6e_offline.md
```

隐私检查:

```powershell
Select-String -LiteralPath backend\logs\interview_eval_report_r6e_offline.md -Pattern "LLM_API_KEY|BEGIN PROMPT|source_span|Bearer|sk-" -SimpleMatch
```

预期:

- backend: 930 passed + 0 skipped。
- frontend: typecheck/build 通过。
- offline compare: rules 与 llm intent 指标相同, llm intent fallback 为 offline 预期。
- report 不包含 prompt / source_span / API key 类字符串。

### Phase 3: GitHub 同步准备

目标:

- 在用户明确授权后, 选择一种发布方式:
  - 直接 push `main` 到 `origin/main`。
  - 或创建 `codex/r6e-sync-live-eval-gate` 分支并开 draft PR。
- 如果 GitHub 认证不可用, 停在本地可交付状态, 不伪造 PR/issue 状态。

推荐:

- 若只是个人仓库且用户确认可直接同步: push `main`。
- 若用户想保留审查面: 建分支 + draft PR。

不做:

- 不在未授权情况下 push。
- 不提交 `backend/logs/`、`frontend/dist/`、`backend/output/`。
- 不提交 `.planning/面试讲解/`。

### Phase 4: 真实 chat panel 数据采集

目标:

- 用户在前端 InterviewAgentPanel 中跑至少 10 轮真实对话。
- 每轮覆盖不同类型经历, 至少包含:
  - 2 条 `tech_metric`
  - 2 条 `communication`
  - 2 条 `process_metric`
  - 2 条 `domain_x`
  - 2 条用户自由选择
- 允许开启智能抽取 toggle, 但默认仍 rules。

数据边界:

- 不把完整 user_message 入库。
- 不把真实对话原文提交到 git。
- 若需要样本标签, 只记录 sample id、gap、expected slot key、product_goal、人工备注, 不记录原文。

### Phase 5: live eval v2

目标:

- 配置 LLM key 后手动运行:

```powershell
D:\python3.11\python.exe scripts/evaluate_interview_agent.py --mode live --extractor compare --output backend/logs/interview_eval_report_live_v2.md
```

- 产出 v2 报告后只记录聚合指标到文档, 不提交完整日志。

核心指标:

```text
schema_pass_rate_delta = llm - rules
avg_completeness_delta = llm - rules
fabrication_violations_count
fallback_rate
slot_source_breakdown.llm
llm_parse_retry_count
llm_to_rules_slot_fallback_count
low_confidence_slot_rate
p95_latency_ms
```

通过门槛:

- `fabrication_violations_count == 0`
- live `fallback_rate <= 0.20`
- `slot_source_breakdown.llm > 0`
- `schema_pass_rate` 或 `avg_completeness` 相比 rules 有明确正收益
- 报告隐私扫描无命中

强门槛, 用于考虑默认开放智能抽取:

- `schema_pass_rate >= 0.60`
- `avg_completeness >= 0.70`
- `fabrication_violations_count == 0`
- 用户主观确认追问更省力, 且无明显误抽取

### Phase 6: 决策记录

根据 live v2 结果写一段结论到 `.harness/docs/round6-c-live-eval-result-and-next-steps.md` 或新建 R6-E closeout:

| 结果 | 下一步 |
|---|---|
| LLM 明显优于 rules 且无隐私/幻觉问题 | 启动 R6-F: prompt/retry/token 优化 |
| LLM 仅持平 rules | 保持 rules 默认, 优先扩 eval set / 改真实样本合同 |
| LLM 误抽取或 fallback 高 | 暂停 LLM 投资, 修 fallback / schema / prompt 边界 |
| GitHub 同步受阻 | 先解决认证/PR 流程, 不继续堆本地功能 |

---

## 5. 非目标

R6-E 不做:

- 不改 `backend/core/interview_policy.py` 的 step 4.5。
- 不改 `backend/core/interview_llm.py` 的 prompt / retry / schema。
- 不把 `SLOT_EXTRACTION_SYSTEM_PROMPT` 接入 `PROMPT_VERSIONS`。
- 不默认开启 `enable_interview_llm`。
- 不把 live eval report 或真实对话原文提交到仓库。
- 不新增账号、鉴权、云部署、多用户。
- 不做自由聊天助手、模拟面试训练或自动投递。

---

## 6. 可能改动文件

R6-E 预计只改文档:

```text
README.md
.harness/memory/MEMORY.md
.harness/docs/round6-e-github-sync-live-eval-v2-spec.md
可选: .harness/docs/ROADMAP.md
可选: .harness/docs/round6-c-live-eval-result-and-next-steps.md
```

除非验证发现真实 bug, 不改:

```text
backend/core/
backend/api/
frontend/src/
scripts/evaluate_interview_agent.py
```

---

## 7. 验收标准

R6-E 完成时必须满足:

- [ ] README 不再宣称当前 baseline 是 863。
- [ ] MEMORY 记录 R6-C/R6-D 完成状态与 R6-E 门禁。
- [ ] `git status --short` 没有意外业务代码变更。
- [ ] backend 全量测试通过。
- [ ] frontend typecheck/build 通过。
- [ ] offline compare 可复现并通过隐私扫描。
- [ ] GitHub 同步方式已由用户确认。
- [ ] 若执行 push/PR, 远端能看到 R6-C/R6-D 9 个提交或对应 PR。
- [ ] 若执行 live v2, 报告只以聚合指标进入文档, 不提交原始日志。
- [ ] 下一轮是否进入 R6-F 有明确数据依据。

---

## 8. 给执行 agent 的提示词

```text
你在 D:\简历帮 工作。请执行 R6-E: GitHub 同步 + Live Eval v2 决策门禁。

先读 AGENTS.md 和 .harness/docs/round6-e-github-sync-live-eval-v2-spec.md。

目标:
1. 核对本地 main 是否仍比 origin/main ahead 9。
2. 修 README.md 与 .harness/memory/MEMORY.md 的当前基线, 让它们与 AGENTS/ROADMAP 的 R6-D/930 baseline 一致。
3. 不修改 backend/core、backend/api、frontend/src 或 scripts, 除非验证发现必须修的真实 bug。
4. 跑 backend 全量 pytest、frontend typecheck/build、offline compare 和隐私扫描。
5. 在没有用户明确授权前不要 push。若 GitHub auth 不可用, 如实记录 blocker。
6. 不提交 backend/logs、frontend/dist、backend/output、.planning/面试讲解。

验收命令:
git -C D:\简历帮 status --short --branch
git -C D:\简历帮 rev-list --left-right --count origin/main...main
cd D:\简历帮\backend
D:\python3.11\python.exe -m pytest tests/ -q
cd D:\简历帮\frontend
npx vue-tsc --noEmit
npm run build
cd D:\简历帮
D:\python3.11\python.exe scripts/evaluate_interview_agent.py --mode offline --extractor compare --output backend/logs/interview_eval_report_r6e_offline.md
Select-String -LiteralPath backend\logs\interview_eval_report_r6e_offline.md -Pattern "LLM_API_KEY|BEGIN PROMPT|source_span|Bearer|sk-" -SimpleMatch
```

---

## 9. 收尾记录模板

```markdown
## R6-E Closeout

- local HEAD:
- origin/main before:
- sync mode: direct push / draft PR / not synced
- backend tests:
- frontend typecheck:
- frontend build:
- offline compare:
- privacy scan:
- live v2 run: yes/no
- live v2 key metrics:
- decision:
  - continue to R6-F prompt/retry/token optimization: yes/no
  - keep rules default: yes/no
  - blockers:
```
