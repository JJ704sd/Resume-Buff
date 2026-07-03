# Round 6-F: 项目回顾检查 + Bug 审核 Spec

> 适用项目: 简历帮 / Resume-Buff  
> 本地日期: 2026-07-03  
> 本地仓库: `D:\简历帮`  
> GitHub 仓库: `https://github.com/JJ704sd/Resume-Buff`  
> 状态: draft spec  
> 推荐主题: 先做一次证据驱动的项目回顾和 bug 审核, 再决定是否继续投 LLM 优化或新功能。

---

## 0. 一句话结论

下一轮不应直接追加功能。当前项目已经从 R5/R6 连续快速迭代到 JD 面试官、LLM slot 抽取、可信增强、eval compare、R6-E `_do_answer` 对齐 bugfix。第一性原理上, 现在最大的风险不是"功能不够", 而是:

1. 最近多轮变更是否仍能被本地和 GitHub 共同解释清楚。
2. docs / AGENTS / README / ROADMAP / MEMORY / round spec 是否讲的是同一个当前状态。
3. R6-E Phase 4 修复的 state machine bug 是否还有同类变体。
4. 公开仓库、日志、eval 报告、LLM observability 是否仍守住隐私边界。
5. 没有 CI 的情况下, 本地验证命令是否足以作为可复现 release gate。

因此本轮定义为 **R6-F: project review + bug audit gate**。目标是产出一份问题清单和最小修复集, 而不是启动大范围重构。

---

## 1. 当前取证事实

### 1.1 本地 git 状态

2026-07-03 本地取证:

```text
branch: main
tracking: main...origin/main
HEAD: 3b632c7 chore(round6-e): API smoke 阈值 ≥2 → ≥1 bullets
origin/main: 3b632c7 via local tracking ref
dirty worktree:
  staged: AGENTS.md (+2 R6-E entries)
  untracked: backend/_r6e_p4_insert_agents_entry.py
```

最近提交:

```text
3b632c7 chore(round6-e): API smoke 阈值 ≥2 → ≥1 bullets
7fe798c fix(round6-e): _do_answer slot 优先读 question_plan 决策 (Phase 4)
669a5ef docs(round6-e): Phase 1 文档同步 — spec 落档 + README/MEMORY 对齐 930 baseline
2177d27 chore(round6-e): add .planning/面试讲解/ gitignore shield
a03c8c0 docs(round6-c): refine live eval next-step plan + sync ROADMAP to 930 baseline
91ec8f3 feat(round6-d): 机械拆分 LLM slot 抽取模块 (行为不变)
84dd086 feat(round6-c.3): LLM 抽取可观测性 + prompt few-shot 优化
```

R6-E Phase 4 关键提交 `7fe798c` 改动面:

```text
.planning/r6e_p4_api_smoke.py         | 156 +++++++++++++++++
backend/core/interview_agent.py       |  28 ++-
backend/tests/test_interview_agent.py | 319 +++++++++++++++++++++++++++++++++-
```

`3b632c7` 只调整 `.planning/r6e_p4_api_smoke.py` 的 bullet 阈值。

### 1.2 GitHub 状态

已确认:

- remote 指向 `https://github.com/JJ704sd/Resume-Buff.git`。
- 公开 GitHub REST repo 元数据曾返回: repo public, default branch `main`, open issue count 为 0。
- 公开 API 查询 open issues 返回 `[]`。
- 公开 API 查询 open PR 返回 `[]`。
- 公开 API 查询 Actions runs 返回 `{"total_count":0,"workflow_runs":[]}`。

受限项:

- GitHub MCP connector 启动失败, 报 handshake / transport error。
- 本机 `gh` 已安装, 但 `gh auth status` 显示未登录。
- 后续网络请求多次遇到 Windows schannel / TLS handshake / revocation check 错误。

本轮审核不能把 GitHub connector 或网页渲染结果当唯一事实源。远端事实优先级应为:

1. `git ls-remote origin refs/heads/main` 或 GitHub API 的 commit SHA。
2. 本地 `git show origin/main:<path>`。
3. GitHub web / raw 页面人工复核。

### 1.3 文档一致性现状

当前存在明显文档状态漂移:

- `AGENTS.md` 已暂存新增 R6-E Phase 1 和 R6-E Phase 4 两条记录, 其中 Phase 4 声明 baseline 从 930 增至 **936 passed**。
- `README.md` 当前仍写后端测试基线为 **930 passed + 0 skipped**。
- `.harness/docs/ROADMAP.md` 当前仍以 R6-D / **930** 为主。
- `.harness/memory/MEMORY.md` 已记录 R6-C.1 / C.3 / R6-D / R6-E 起步, 但其中 R6-E 仍含"本地 main 领先 origin/main 9 commit"的旧事实。
- `.harness/docs/round6-e-github-sync-live-eval-v2-spec.md` 已过期: 文内仍写 `origin/main` 停在 `69ed431`, README 仍 863, 本地 ahead 9 commits。这些在当前本地事实下已经不成立。

文档 bug 的判定标准: 如果一个入口文档让下一位 agent 或用户误以为当前 baseline 是 930、origin 落后 9 commit、README 仍 863, 它就是 P1/P2 级项目状态 bug, 即使代码行为正常。

### 1.4 代码与测试地图

后端核心文件按体量排序:

```text
backend/core/interview_agent.py     71879 bytes
backend/core/generator.py           57428 bytes
backend/core/agent_workflow.py      51361 bytes
backend/core/jd_parser.py           45663 bytes
backend/core/llm_rewriter.py        45363 bytes
backend/core/interview_policy.py    24881 bytes
backend/core/interview_llm.py       24756 bytes
backend/core/agent_tools.py         22146 bytes
backend/core/evidence.py            16946 bytes
backend/core/interview_prompts.py   13739 bytes
backend/core/interview_verifier.py  13380 bytes
```

测试体量集中在:

```text
backend/tests/test_interview_eval.py    84545 bytes
backend/tests/test_interview_agent.py   82922 bytes
backend/tests/test_agent_eval.py        72249 bytes
backend/tests/test_llm_rewriter.py      69030 bytes
backend/tests/test_agent_workflow.py    57727 bytes
backend/tests/test_interview_llm.py     51484 bytes
backend/tests/test_interview_api.py     49276 bytes
backend/tests/test_interview_policy.py  49256 bytes
```

本轮高风险代码面:

- `backend/core/interview_agent.py`: session state machine, `_do_answer`, `_current_slot`, draft/save/rephrase。
- `backend/core/interview_policy.py`: `plan_next_question`, critical slot priority, turn limit。
- `backend/core/interview_llm.py`: LLM mode, fallback, slot meta, observability, privacy hash。
- `backend/api/interview.py`: API contract and user-facing errors。
- `scripts/evaluate_interview_agent.py`: eval contract, report privacy, live/offline compare。
- `frontend/src/components/InterviewAgentPanel.vue` and `InterviewDraftCard.vue`: mode toggle, question/draft UX, confidence and verification display。

---

## 2. 第一性原理

Resume-Buff 是本地单用户简历素材工具, 不是云端招聘平台。bug 审核应从产品不可妥协项倒推:

1. **事实真实性**: 用户没有明确提供的事实不能进入素材库或简历。
2. **写入安全**: `save_card` 不能误写、重复写、污染脱敏示例库或覆盖用户已有素材。
3. **默认可用**: 无 LLM key、网络失败、GitHub 未登录时, rules 路径和本地生成仍必须可用。
4. **可追溯但不泄漏**: observability 只能记录 slot key、计数、hash 和短标签, 不能把 user_message、prompt、raw response、source_span 明文写入报告或公开仓库。
5. **可复现**: 当前状态必须能靠本地命令重建, 不能依赖"我记得上一轮跑过"。
6. **文档即接口**: AGENTS / README / ROADMAP 对 agent 是执行接口, stale 文档会制造实际 bug。

由此定义 bug:

- 任何导致事实编造、事实错槽、误写素材、无法 draft/save 的行为都是 P0/P1。
- 任何导致默认 rules 路径不可用、LLM fallback 不可解释、eval 报告误导决策的行为是 P1。
- 任何让下一位 agent 基于错误 baseline 或错误 GitHub 状态行动的文档漂移是 P1/P2。
- 任何公开仓库隐私泄漏是 P0。

---

## 3. 方案取舍

### 方案 A: 全量静态扫描

优点: 快速覆盖大量文件, 能找到 TODO、宽泛 `except Exception`、潜在隐私字符串、tracked runtime 文件。  
缺点: 噪声高, 对 state machine bug 这种行为错位检出弱。

### 方案 B: 风险驱动深挖最近变更链路

优点: 直击 R6-E Phase 4 的真实 bug 类型, 审核 `_do_answer` / `question_plan` / `extract_slots` / `/draft` / `save_card` 这一条产品主链。  
缺点: 可能漏掉旧模块里的低频问题。

### 方案 C: Release candidate 级硬化

优点: 最接近发布前验收, 覆盖本地测试、前端构建、API smoke、隐私扫描、GitHub 状态。  
缺点: 成本较高, 容易把"查 bug"扩展成大修和 CI 工程化。

推荐采用 **B 为主, A 和 C 的最小闭环为辅**:

- 用 A 建立全局风险地图。
- 用 B 审最近最可能有回归的 interview agent 主链。
- 用 C 的验证门禁证明本轮审核没有破坏现状。

---

## 4. R6-F 范围

### Phase 0: 现场保护与事实冻结

目标: 不覆盖用户或上一轮 agent 的未完成变更。

必须记录:

```powershell
git status --short --branch
git diff --cached --stat
git diff --stat
git log --oneline --decorate -n 12
git remote -v
```

验收:

- 解释 `AGENTS.md` 暂存 diff 的归属。
- 解释 `backend/_r6e_p4_insert_agents_entry.py` 是否为一次性 helper。
- 不擅自删除、unstage、commit 或 revert 这些既有变更。
- 若需要清理 helper, 先在报告中列为建议, 不在审核 spec 执行阶段直接删除。

### Phase 1: 文档与 GitHub 状态一致性审核

目标: 让项目入口文档只表达一个当前状态。

检查项:

1. `README.md` 当前 baseline 是 930 还是 936。
2. `AGENTS.md` 是否把 R6-E Phase 4 作为已落地事实。
3. `.harness/docs/ROADMAP.md` 是否仍停在 R6-D / 930。
4. `.harness/memory/MEMORY.md` 是否仍写"本地 main 领先 origin/main 9 commit"。
5. `.harness/docs/round6-e-github-sync-live-eval-v2-spec.md` 是否需要 closeout 修正, 避免继续误导后续 agent。
6. GitHub `origin/main` 的 SHA 是否等于本地 tracking ref。
7. GitHub open PR / issue / Actions 是否仍为空。

建议命令:

```powershell
git rev-parse HEAD origin/main
git show HEAD:README.md | Select-String -Pattern "930|936|R6-E|origin/main"
git show origin/main:README.md | Select-String -Pattern "930|936|R6-E|origin/main"
Select-String -LiteralPath README.md,AGENTS.md,.harness\memory\MEMORY.md,.harness\docs\ROADMAP.md,.harness\docs\round6-e-github-sync-live-eval-v2-spec.md -Pattern "863|930|936|origin/main|9 commit|69ed431|3b632c7"
```

如果 GitHub auth 可用, 补跑:

```powershell
gh auth status
gh pr list --repo JJ704sd/Resume-Buff --state open
gh issue list --repo JJ704sd/Resume-Buff --state open
gh run list --repo JJ704sd/Resume-Buff --limit 10
```

验收:

- 报告列出所有 stale 文档行号。
- 明确当前采用的活跃测试基线: 936 或 930, 以实际全量 pytest 结果为准。
- 如果 GitHub 无 Actions, 记录为"无远端 CI gate", 但不把它夸大为功能 bug。

### Phase 2: 静态风险扫描

目标: 建立 bug 审核地图, 不是立刻重构。

检查项:

- 宽泛异常吞噬: `except Exception`, 裸 `pass`。
- 隐私敏感字符串: `LLM_API_KEY`, `Bearer`, `sk-`, `BEGIN PROMPT`, `source_span`, `user_message`。
- LLM 模块反向依赖: `interview_llm.py` 不得 import `core.interview_agent` 或 `core.llm_rewriter`。
- runtime 产物入库: `backend/logs/`, `backend/output/`, `.env`, 私有 materials, live report。
- 测试 mock 路径: LLM urlopen mock 应指向 `core.interview_llm` 命名空间。

建议命令:

```powershell
Select-String -Path backend\**\*.py,frontend\src\**\*.ts,frontend\src\**\*.vue,scripts\*.py -Pattern "TODO|FIXME|BUG|HACK|except Exception|pass$"
Select-String -LiteralPath backend\core\interview_llm.py -Pattern "core.interview_agent|core.llm_rewriter|from core.interview_agent|from core.llm_rewriter"
git ls-files | Select-String -Pattern "^backend/logs/|^backend/output/|_private|\.env$|generation\.log|interview_eval_report_live"
Select-String -Path backend\tests\*.py -Pattern "interview_agent\.urllib|core.interview_agent\.urllib|core.interview_llm"
```

验收:

- 每个命中项分类为 expected / review-needed / bug。
- 对 `except Exception` 不做机械清理, 只追问是否吞掉了用户可见错误、隐私泄漏或错误 fallback。

### Phase 3: R6-E Phase 4 同类 bug 深挖

目标: 验证 `_do_answer` 优先读 `question_plan.slot` 后, 没有其他错槽和 draft 阻塞变体。

必须覆盖 gap:

- `communication`
- `process_metric`
- `tech_metric`
- `domain_x`

必须验证链路:

1. `next_question` 返回的 `question_plan.slot` 与用户下一轮 answer 的抽取 slot 一致。
2. `captured_delta` 不把 `result` 错写进 `method`。
3. 三轮内满足 `CAN_DRAFT_CONDITIONS` 的组合时 `/draft` 返回 200。
4. fallback 路径仍能在 `question_plan` 为空或 slot 为空时走 `_current_slot`。
5. `_do_rephrase` 若仍使用 `_current_slot`, 不应被本轮修复误伤。
6. message log 仍记录 asked slot, 防重复追问。

建议命令:

```powershell
cd backend
D:\python3.11\python.exe -m pytest tests/test_interview_agent.py::TestSlotExtractionAlignsWithPolicy -q
D:\python3.11\python.exe -m pytest tests/test_interview_api.py -q
cd ..
D:\python3.11\python.exe .planning\r6e_p4_api_smoke.py
```

验收:

- 4 个 gap 的 smoke 都能 `/draft` 200。
- 失败时报告实际 captured key 顺序和 expected key 顺序。
- 不把 smoke 阈值调整当成核心修复证明; 核心证明是 slot 对齐和 `/draft` 状态。

### Phase 4: 默认 rules 路径与 LLM fallback 审核

目标: 确认没有 LLM key 时产品仍可用, 有 key 时 observability 可解释。

检查项:

- `enable_interview_llm=False` 默认仍走 rules。
- `enable_interview_llm=True` 但无 key 时回退 rules, 返回 warning, 不发网络。
- `_call_llm_for_slot_extraction` request body 仍含 `response_format={"type":"json_object"}` 和 `temperature=0.0`。
- LLM parse retry 只累计 JSON / schema retry, 网络错误不误计 retry。
- fallback 计数不包含 user_message / prompt / raw response。
- `INTERVIEW_OBSERVABILITY_SCHEMA` 只允许 `rules` / `llm` / `mixed` 等短标签和整数。

建议命令:

```powershell
cd backend
D:\python3.11\python.exe -m pytest tests/test_interview_llm.py -q
D:\python3.11\python.exe -m pytest tests/test_interview_agent.py tests/test_interview_eval.py -q
```

验收:

- 老路径默认行为不需要 LLM key。
- 报告中 `slot_source_breakdown` 和 fallback 数字能解释本轮路径。

### Phase 5: Eval report 与隐私审核

目标: eval 继续能辅助决策, 但不泄漏用户原文。

必须跑:

```powershell
cd D:\简历帮
D:\python3.11\python.exe -m scripts.evaluate_interview_agent --mode offline --extractor compare --output backend/logs/interview_eval_report_r6f_audit.md
```

报告检查:

- `## 4.5 Eval contract warnings`
- `## 4.6 Eval contract: product goal`
- `## 4.7 LLM 抽取可观测性`
- `fallback_rate` 口径仍声明为 workflow / session 级。
- compare 模式区分 rules 和 llm intent。
- offline 模式 LLM 不发网络。

隐私扫描:

```powershell
Select-String -LiteralPath backend\logs\interview_eval_report_r6f_audit.md -Pattern "BEGIN PROMPT|Bearer|sk-|source_span|raw response|LLM_API_KEY"
```

验收:

- offline compare 跑通。
- 报告只提交或摘录聚合指标, 不提交原始用户消息。
- 如果扫描命中文档中的隐私规则说明, 要人工判断是否为 policy mention; 如果命中真实 secret 或原文, 判 P0。

### Phase 6: 前端与 API smoke

目标: 审查用户实际使用路径, 不只看后端单测。

最低命令:

```powershell
cd frontend
npx vue-tsc --noEmit
npm run build
```

建议人工/浏览器 smoke:

- 桌面 1280x800: InterviewAgentPanel 默认 rules 标签、智能抽取 toggle 默认关闭。
- 移动 375x812: drawer 内 toggle / question / draft card 不重叠。
- 有 verification / confidence notes 时, save 前确认弹窗只显示计数, 不显示完整 bullet 原文。
- API `/api/interview/start`、`/reply`、`/draft`、`/save` happy path。

验收:

- 前端构建成功。
- UI 不展示 prompt、raw response、source_span 明文。
- draft save 风险提示符合 R6-B Phase 6 边界。

### Phase 7: 全量验证与 bug triage

目标: 给出可执行的发现清单。

全量命令:

```powershell
cd backend
D:\python3.11\python.exe -m pytest tests/ -q
cd ..\frontend
npx vue-tsc --noEmit
npm run build
```

严重级别:

- **P0**: 隐私泄漏、素材库误写/丢失、事实编造进入保存路径、公开仓库出现 secret。
- **P1**: 默认路径不可用、R6-E slot 对齐 bug 复发、draft/save 主链阻断、文档状态足以导致错误操作。
- **P2**: eval/report 误导、GitHub 状态不可复现、测试覆盖缺口、API 错误信息不清。
- **P3**: 文案、注释、宽泛异常、低风险技术债。

每条 finding 必须包含:

```text
id:
severity:
surface:
evidence:
repro command:
expected:
actual:
recommended fix:
owner decision:
```

---

## 5. 本轮明确不做

- 不做新的 prompt 优化。
- 不改 retry/backoff/token 策略。
- 不把 LLM 抽取默认打开。
- 不改 JD 资料库筛选规则。
- 不做大规模文件拆分。
- 不引入 CI/CD 平台配置, 除非审核结论明确把"无 CI"升级为下一轮任务。
- 不提交 live eval 原始日志或真实用户原文。
- 不自动清理脏工作区文件。

---

## 6. 初始已知问题清单

这些不是最终 finding, 但应作为 R6-F 第一批审核入口:

1. **文档漂移**: `.harness/docs/round6-e-github-sync-live-eval-v2-spec.md` 仍写 origin/main 落后 9 commit、README 863 等旧事实。
2. **baseline 漂移**: `AGENTS.md` 暂存内容声明 R6-E Phase 4 后 936 passed, 但 README / ROADMAP 仍大多显示 930。
3. **工作区未收口**: `AGENTS.md` 已暂存, `backend/_r6e_p4_insert_agents_entry.py` 未跟踪。
4. **远端无 CI**: GitHub Actions runs 当前公开查询为 0, 所以所有 release gate 依赖本地命令和人工纪律。
5. **工具不稳定**: GitHub connector、`gh` auth、Windows TLS 都可能影响取证, spec 必须记录 fallback。
6. **宽泛异常较多**: 多处 `except Exception` / `pass` 需要按主链风险筛选, 避免真实错误被静默吞掉。
7. **R6-E bug 类型值得扩展审查**: `_do_answer` 与 `next_question` 曾出现决策 slot / 抽取 slot 不一致, 需要审 `_do_rephrase`、API smoke、message log 和 draft condition 的同类错位。

---

## 7. 交付物

R6-F 完成时应产出:

1. `.harness/docs/round6-f-project-review-bug-audit-report.md`
   - 当前 SHA / GitHub 状态 / dirty worktree 说明。
   - 测试与构建命令结果。
   - 隐私扫描结果。
   - findings 表。
   - 建议修复顺序。
2. 如发现 P0/P1, 配套最小修复 commit 或明确的修复计划。
3. 如只发现文档漂移, 配套 docs-only patch, 不碰核心代码。
4. 若确认当前 active baseline 是 936, 同步 README / ROADMAP / MEMORY / R6-E closeout 口径。

---

## 8. 验收门槛

R6-F 可以关闭的条件:

- [ ] 工作区所有既有变更都有归属说明。
- [ ] 当前 active baseline 只有一个数字, 且由全量 pytest 结果支撑。
- [ ] `README.md` / `AGENTS.md` / `.harness/docs/ROADMAP.md` / `.harness/memory/MEMORY.md` 不再互相冲突。
- [ ] R6-E Phase 4 slot 对齐 smoke 覆盖 4 个 gap 并通过。
- [ ] 后端全量 pytest 通过。
- [ ] 前端 `vue-tsc --noEmit` 和 `npm run build` 通过。
- [ ] offline compare report 生成并通过隐私扫描。
- [ ] GitHub PR / issue / Actions 状态已用可用工具复核; 若工具不可用, report 明确说明。
- [ ] 所有 P0/P1 findings 已修复或有用户确认的延后决策。

---

## 9. 分阶段操作提示词

### Phase 0 提示词: 现场保护

```text
你在 D:\简历帮 工作。执行 R6-F Phase 0: 现场保护与事实冻结。

不要修改、删除、unstage、commit 或 revert 任何文件。只做取证并写入审核报告草稿。

必须记录:
- git status --short --branch
- git diff --cached --stat
- git diff --cached -- AGENTS.md 的摘要
- git diff --stat
- git log --oneline --decorate -n 12
- git remote -v

特别说明 AGENTS.md 暂存变更和 backend/_r6e_p4_insert_agents_entry.py 未跟踪文件的归属、风险和建议处理方式。
```

### Phase 1 提示词: 文档与 GitHub 状态一致性

```text
执行 R6-F Phase 1: 文档与 GitHub 状态一致性审核。

目标是找出 README / AGENTS / ROADMAP / MEMORY / R6-E spec 中关于 baseline、origin/main、GitHub 同步状态的冲突。

必须检查:
- README.md
- AGENTS.md
- .harness/docs/ROADMAP.md
- .harness/memory/MEMORY.md
- .harness/docs/round6-e-github-sync-live-eval-v2-spec.md

运行:
git rev-parse HEAD origin/main
git show HEAD:README.md | Select-String -Pattern "930|936|R6-E|origin/main"
git show origin/main:README.md | Select-String -Pattern "930|936|R6-E|origin/main"
Select-String -LiteralPath README.md,AGENTS.md,.harness\memory\MEMORY.md,.harness\docs\ROADMAP.md,.harness\docs\round6-e-github-sync-live-eval-v2-spec.md -Pattern "863|930|936|origin/main|9 commit|69ed431|3b632c7"

如 gh 已登录, 再查 open PR / issue / run。输出 stale 行号、当前可信事实和建议修复顺序。
```

### Phase 2 提示词: 静态风险扫描

```text
执行 R6-F Phase 2: 静态风险扫描。

目标是建立风险地图, 不要机械修复所有命中。

检查:
- except Exception / pass 是否吞掉主链错误
- 是否有 prompt / user_message / source_span / API key 泄漏风险
- interview_llm.py 是否反向 import core.interview_agent 或 core.llm_rewriter
- 是否有 runtime / private 文件入库
- 测试 monkeypatch 是否仍指向旧的 core.interview_agent urllib 路径

每个命中分类为 expected / review-needed / bug, 并给出理由。
```

### Phase 3 提示词: R6-E 同类 bug 深挖

```text
执行 R6-F Phase 3: R6-E Phase 4 同类 bug 深挖。

重点审核 _do_answer、question_plan.slot、extract_slots、CAN_DRAFT_CONDITIONS、/draft 的一致性。

必须覆盖 communication / process_metric / tech_metric / domain_x 四个 gap。

运行:
cd backend
D:\python3.11\python.exe -m pytest tests/test_interview_agent.py::TestSlotExtractionAlignsWithPolicy -q
D:\python3.11\python.exe -m pytest tests/test_interview_api.py -q
cd ..
D:\python3.11\python.exe .planning\r6e_p4_api_smoke.py

报告 captured key 顺序、expected key 顺序、/draft 状态码。若失败, 给出最小复现和疑似根因。
```

### Phase 4 提示词: Rules 默认路径与 LLM fallback

```text
执行 R6-F Phase 4: rules 默认路径与 LLM fallback 审核。

确认 enable_interview_llm=False 不需要 LLM key, enable_interview_llm=True 但无 key 时回退 rules 并返回 warning。

检查 response_format=json_object、temperature=0.0、parse retry、fallback count、slot_source_breakdown 隐私边界。

运行:
cd backend
D:\python3.11\python.exe -m pytest tests/test_interview_llm.py -q
D:\python3.11\python.exe -m pytest tests/test_interview_agent.py tests/test_interview_eval.py -q

输出 rules / llm / fallback / observability 四类结论。
```

### Phase 5 提示词: Eval report 与隐私

```text
执行 R6-F Phase 5: eval report 与隐私审核。

运行 offline compare:
cd D:\简历帮
D:\python3.11\python.exe -m scripts.evaluate_interview_agent --mode offline --extractor compare --output backend/logs/interview_eval_report_r6f_audit.md

检查报告是否包含 4.5 / 4.6 / 4.7 章节, fallback_rate 口径是否清楚, compare 是否区分 rules 和 llm intent。

隐私扫描:
Select-String -LiteralPath backend\logs\interview_eval_report_r6f_audit.md -Pattern "BEGIN PROMPT|Bearer|sk-|source_span|raw response|LLM_API_KEY"

如果扫描命中 policy mention, 标记 expected; 如果命中真实原文或凭据, 标 P0。
```

### Phase 6 提示词: 前端与 API smoke

```text
执行 R6-F Phase 6: 前端与 API smoke。

运行:
cd frontend
npx vue-tsc --noEmit
npm run build

人工或浏览器 smoke:
- 桌面 1280x800: InterviewAgentPanel 默认 rules 标签, 智能抽取 toggle 默认关闭
- 移动 375x812: drawer 内 toggle / question / draft card 不重叠
- verification / confidence notes 展示计数, 不展示 prompt、raw response、source_span 明文
- /api/interview/start, /reply, /draft, /save happy path

输出构建结果和 UI/API 风险。
```

### Phase 7 提示词: 全量验证与 triage

```text
执行 R6-F Phase 7: 全量验证与 bug triage。

运行:
cd backend
D:\python3.11\python.exe -m pytest tests/ -q
cd ..\frontend
npx vue-tsc --noEmit
npm run build

在 .harness/docs/round6-f-project-review-bug-audit-report.md 输出 findings。

每条 finding 必须包含:
- id
- severity: P0 / P1 / P2 / P3
- surface
- evidence
- repro command
- expected
- actual
- recommended fix
- owner decision

关闭条件: P0/P1 已修复或明确延后, baseline 只有一个数字, 文档状态不冲突, 隐私扫描无真实泄漏。
```

---

## 10. 后续决策

根据 R6-F report:

- 若有 P0/P1: 先开 bugfix round, 不进入新功能。
- 若只有文档漂移: 做 docs-only closeout, 把 active baseline 同步为实际全量测试结果。
- 若代码与文档都干净: 再决定是否执行 R6-E live eval v2 或进入 R6-F+ 的 CI / release hygiene。
- 若 live eval v2 仍显示 LLM 相比 rules 没有正收益: 暂停 LLM prompt/retry/token 投资, 优先扩 eval set 或改善非 LLM 产品路径。
