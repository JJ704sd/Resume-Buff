# Round 5-E — Prompt Versioning + A/B Eval Spec

> 适用项目: 简历帮 / Resume-Buff  
> GitHub: `JJ704sd/Resume-Buff` (`main`)  
> 日期: 2026-06-28  
> 状态: 待实施  
> 当前仓库基线: 本地 `main...origin/main`, 最近提交 `6ee228e docs(round5-d): refresh agent eval report`  
> 当前能力基线: R5-D 真实 LLM eval 闭环已完成;README / ROADMAP 标注 **596 passed + 0 skipped**  
> 下一轮目标: 在不改变默认生成行为的前提下,给 `SYSTEM_PROMPT` 增加显式版本选择,并新增一个隐私安全的 prompt A/B 评测脚本,让后续是否 rollout winner 有真实数据依据。

---

## 0. 仓库现状

### 0.1 已经具备的能力

当前 `main` 已经不是早期的“简历生成器”,而是一个带诊断闭环的本地单用户工具:

- 后端 FastAPI + 前端 Vue 3,默认本地运行。
- `backend/core/llm_rewriter.py` 已有 OpenAI 兼容 HTTP 调用、无 key fallback、JSON schema retry、Function Calling、Agent Loop、Session history、evidence 约束。
- `backend/core/agent_workflow.py` 已有确定性任务图、`agent_summary`、`evidence_summary`、`external_resume_perspective`、`bullet_evaluations`、JSONL trace。
- `scripts/evaluate_agent_workflow.py` 已有 `--mode {offline,live,auto}`、`--output`、12 JD eval set、fallback taxonomy、LLM 元信息、rewrite impact、latency p95/max。
- README 和 ROADMAP 已标注 R5-D 完成后测试基线为 **596 passed + 0 skipped**。

### 0.2 当前 prompt 的真实形态

`backend/core/llm_rewriter.py` 当前不是单纯的旧 v2 prompt:

- `SYSTEM_PROMPT` 是 R3-P 的 v2 主体,但文本里已经包含 evidence 相关第 8 条硬性约束。
- `EVIDENCE_CONSTRAINT_SUFFIX` 会在 `evidence_summary is not None` 时追加到 system prompt。
- `_build_request_payload(...)` 当前没有 `prompt_version` 参数。
- `rewrite_highlights(...)` 当前没有 `prompt_version` 参数。
- `generator.build_sections`、`preview_resume`、`generate_resume_docx`、`api/resume.py`、`agent_workflow.run_agent_workflow` 均没有 `prompt_version` 透传。

这意味着 R5-E 的第一目标不是“直接替换 SYSTEM_PROMPT”,而是先把当前 prompt 固化为 `v2-baseline`,再允许显式选择候选版本。

### 0.3 文档基线小债

当前 README / ROADMAP 已是 596 基线,但 `AGENTS.md` 的 Testing instructions 顶部仍保留 R5-D Phase 3 的 **584 passed + 0 skipped** 长段。R5-E Phase 0 必须先同步这个文档基线,避免下一轮继续传播旧数字。

---

## 1. 非目标

- 不在 R5-E 默认替换 `SYSTEM_PROMPT`。
- 不把 winner rollout 放进本轮;A/B 报告产生后,另开 R5-E closeout 或 R5-F 决策默认切换。
- 不默认开启 LLM、Function Calling 或 Agent workflow。
- 不把 A/B 脚本挂到 pre-push hook。
- 不引入新依赖、embedding API、向量库、后台队列或前端 UI。
- 不读取 `backend/data/_private_backup.json`。
- 不把完整 prompt、完整 JD、完整 bullet、完整 LLM response、judge chain-of-thought、API key 写入 report / trace / stdout。
- 不改 `match_score`、JD 库入库脚本、模板渲染、前端页面。

---

## 2. 设计原则

### 2.1 默认路径字节级稳定

以下调用在未显式传 `prompt_version` 时必须保持当前行为:

- `rewrite_highlights(...)`
- `_build_request_payload(..., evidence_summary=None)`
- `preview_resume(..., enable_agent_workflow=False)`
- `generate_resume_docx(..., enable_agent_workflow=False)`

实现策略:

- 保留当前 `SYSTEM_PROMPT` 常量内容不动。
- 新增 `PROMPT_VERSION_BASELINE = "v2-baseline"`。
- 新增 `PROMPT_VERSIONS` dict,其中 `"v2-baseline"` 指向当前 `SYSTEM_PROMPT`。
- 新增 `_resolve_prompt_version(prompt_version: str | None) -> str`,None 或空字符串解析为 `"v2-baseline"`。
- 新增 `_select_system_prompt(prompt_version: str | None, evidence_summary: str | None) -> str`,只负责选择 base prompt 并按现有规则追加 `EVIDENCE_CONSTRAINT_SUFFIX`。

### 2.2 候选 prompt 是显式实验,不是产品默认

R5-E 只提供候选版本:

| key | 定位 | 目的 |
|---|---|---|
| `v2-baseline` | 当前生产 prompt | 回归基线,字节级锁死 |
| `v3-priority` | 优先级铁律版 | 明确 schema / 不编造 / evidence / jd_focus 的冲突优先级 |
| `v4-counterexample` | 反例强化版 | 增加“不要做什么”,压低 preamble、顺序错位、跨 bullet 借事实 |
| `v5-minimal` | 极简版 | 测试短 prompt 是否比工程化长 prompt 更稳定 |

R5-E 不预设 winner。报告只给建议,不自动修改默认。

### 2.3 A/B 只比较 prompt,固定其他变量

Prompt A/B 脚本不再跑 R5-D 的 4 组 FC/AW 笛卡尔积,避免混入 workflow 变量。R5-E 固定一个评测配置:

- `enable_function_calling=True`
- `enable_agent_workflow=True`
- `mode=offline/live/auto` 沿用 R5-D 语义
- eval set 复用 `scripts/evaluate_agent_workflow.py::load_eval_set()` 的 12 JD
- 每个 prompt version 跑同一批 JD
- `--runs-per-version` 默认 `1`;真实 live 抽样时可手动调到 `3`

这样报告回答的是“同一 workflow 下哪个 prompt 更好”,而不是“workflow 开关是否更好”。

---

## 3. Phase 规划

### Phase 0 — 文档与基线同步

**目标:** 清掉下一轮实施前的基线歧义。

**改动:**

- `AGENTS.md`
  - 顶部活跃测试基线从 R5-D Phase 3 的 584 更新到 R5-D Phase 4/5 的 596。
  - 保留历史 round 描述,但新增一句“当前活跃基线以 README/ROADMAP 的 596 为准”。
- `.harness/docs/round5-e-prompt-optimization-spec.md`
  - 状态保持“待实施”,不写完成。

**验证:**

```powershell
Set-Location -LiteralPath D:\简历帮\backend
D:\python3.11\python.exe -m pytest tests/ --collect-only -q
```

期望:收集到 596 个测试,无 collection error。

---

### Phase 1 — Prompt 版本化基础设施

**目标:** 让后端能显式选择 prompt version,但默认路径完全不变。

**改动文件:**

- `backend/core/llm_rewriter.py`
- `backend/core/generator.py`
- `backend/core/agent_workflow.py`
- `backend/api/resume.py`
- `backend/tests/test_prompt_versioning.py` (NEW)

**后端核心改动:**

1. 在 `llm_rewriter.py` 新增版本注册表。候选 prompt 正文不要在测试里逐字硬编码,测试只锁 key、选择逻辑、长度关系和关键约束短语:

```python
PROMPT_VERSION_BASELINE = "v2-baseline"

SYSTEM_PROMPT_V3_PRIORITY = (
    "你是简历润色专家,根据目标岗位改写项目亮点(bullets 列表)。\n"
    "\n"
    "优先级从高到低,冲突时必须服从更高优先级:\n"
    "P0 JSON schema: 只输出 {\"rewritten\": [{\"index\": 0, \"text\": \"...\"}]}。\n"
    "   index 必须 0..N-1 且顺序、数量与输入 bullets 完全一致。\n"
    "P1 事实边界: 不编造数字、技能、公司、项目名、结果;每个改写必须能由原 bullet 支撑。\n"
    "P2 evidence 边界: 若提供 evidence_summary,只能引用原 bullet 或 evidence 中存在的事实。\n"
    "P3 JD 对齐: matched 必须保留;missing/tier_required 只能在有事实支撑时靠拢。\n"
    "P4 表达: 中文,每条一句话,20-50 字,突出动作、方法、结果。\n"
)

SYSTEM_PROMPT_V4_COUNTEREXAMPLE = SYSTEM_PROMPT_V3_PRIORITY + (
    "\n"
    "禁止事项:\n"
    "1. 不要输出解释、前言、Markdown 或额外字段。\n"
    "2. 不要改变 bullet 数量、index 顺序或把多条合并。\n"
    "3. 不要从其他 bullet 借事实补到当前 bullet。\n"
    "4. 不要为了 missing keyword 硬塞无依据术语。\n"
)

SYSTEM_PROMPT_V5_MINIMAL = (
    "你是简历润色专家。只输出 JSON: "
    "{\"rewritten\": [{\"index\": 0, \"text\": \"...\"}]}。"
    "index 必须 0..N-1,数量和输入 bullets 一致。"
    "不得编造原 bullet/evidence 没有的事实。"
    "若有 jd_focus,只在事实支持时贴近关键词。"
    "中文,每条一句话,20-50 字。"
)

PROMPT_VERSIONS: dict[str, str] = {
    "v2-baseline": SYSTEM_PROMPT,
    "v3-priority": SYSTEM_PROMPT_V3_PRIORITY,
    "v4-counterexample": SYSTEM_PROMPT_V4_COUNTEREXAMPLE,
    "v5-minimal": SYSTEM_PROMPT_V5_MINIMAL,
}
```

2. 新增 helper:

```python
def _resolve_prompt_version(prompt_version: str | None) -> str:
    version = (prompt_version or PROMPT_VERSION_BASELINE).strip()
    if version not in PROMPT_VERSIONS:
        raise ValueError(f"unknown prompt_version: {version}")
    return version


def _select_system_prompt(
    prompt_version: str | None,
    evidence_summary: str | None,
) -> str:
    base = PROMPT_VERSIONS[_resolve_prompt_version(prompt_version)]
    if evidence_summary is not None:
        return base + EVIDENCE_CONSTRAINT_SUFFIX
    return base
```

3. 给以下函数增加 `prompt_version: str | None = None` 或等价默认参数:

- `_build_request_payload(...)`
- `_call_with_retry(...)`
- `_call_with_agent_loop(...)`
- `rewrite_highlights(...)`
- `generator.build_sections(...)`
- `generator.preview_resume(...)`
- `generator.generate_resume_docx(...)`
- `agent_workflow.run_agent_workflow(...)`

4. `PreviewRequest` / `GenerateRequest` 新增字段:

```python
prompt_version: str | None = None
```

字段位置放在 `external_resume_text` 之后,避免打乱既有字段顺序的兼容性约定。

**候选 prompt 内容要求:**

- `v3-priority`:必须包含明确优先级链:
  1. JSON schema 与 index 顺序
  2. 不编造事实
  3. evidence 事实边界
  4. jd_focus 关键词倾斜
  5. 语言风格与字数
- `v4-counterexample`:必须包含 4 个短反例类别:
  - 不输出解释性前言
  - 不改变 bullet 数量或顺序
  - 不从其他 bullet 借事实
  - 不为 missing keyword 硬塞无依据术语
- `v5-minimal`:必须短于 `v2-baseline` 的 60%,且仍保留 schema / 不编造 / 顺序一致三条底线。

**测试:**

- `test_default_prompt_payload_bytewise_stable`
  - 调 `_build_request_payload` 不传 `prompt_version`,断言 system message 等于当前 `SYSTEM_PROMPT`。
- `test_v2_baseline_is_current_system_prompt`
  - `PROMPT_VERSIONS["v2-baseline"] is SYSTEM_PROMPT` 或内容相等。
- `test_each_prompt_version_selectable`
  - 4 个 key 都能返回非空 system prompt。
- `test_unknown_prompt_version_raises_without_prompt_leak`
  - 错误信息只含未知 key,不含 prompt 正文。
- `test_evidence_suffix_still_only_when_evidence_summary_present`
  - `evidence_summary=None` 不追加 suffix;非空时追加。
- `test_api_models_accept_prompt_version_default_none`
  - `PreviewRequest()` / `GenerateRequest()` 默认 None。
- `test_workflow_passes_prompt_version_to_build_sections`
  - mock `build_sections`,确认 workflow 透传。

**验收:**

```powershell
Set-Location -LiteralPath D:\简历帮\backend
D:\python3.11\python.exe -m pytest tests/test_prompt_versioning.py -v
D:\python3.11\python.exe -m pytest tests/test_llm_rewriter.py tests/test_agent_workflow.py -v
```

---

### Phase 2 — Prompt A/B 评测脚本

**目标:** 新增手动评测入口,复用 R5-D eval set 和安全指标,产出只含聚合数据的报告。

**新增文件:**

- `scripts/evaluate_prompt_versions.py`
- `backend/tests/test_prompt_eval.py`

**CLI:**

```powershell
D:\python3.11\python.exe scripts/evaluate_prompt_versions.py --mode offline
D:\python3.11\python.exe scripts/evaluate_prompt_versions.py --mode live --runs-per-version 3
D:\python3.11\python.exe scripts/evaluate_prompt_versions.py --versions v2-baseline,v3-priority --output AI岗位JD库_prompt_ab报告.md
```

**参数:**

| 参数 | 默认 | 说明 |
|---|---|---|
| `--mode` | `offline` | 复用 R5-D 的 `offline/live/auto` 语义 |
| `--versions` | 全部 4 个版本 | 逗号分隔 prompt version |
| `--runs-per-version` | `1` | 每个版本每个 JD 的重复次数 |
| `--output` | `AI岗位JD库_prompt_ab报告.md` | Markdown 报告路径 |
| `--judge` | `off` | `off/on`;默认不调用额外 judge |
| `--judge-model` | env `LLM_JUDGE_MODEL` or `LLM_MODEL` | 仅 `--judge on` 使用 |

**脚本复用:**

从 `scripts/evaluate_agent_workflow.py` 复用或轻量 import:

- `load_eval_set`
- `_resolve_eval_mode`
- `_get_llm_eval_config`
- `_extract_project_highlights`
- `_summarize_rewrite_impact`
- `_percentile`
- `_check_pii_safe`

**每行样本记录只保存数字和短枚举:**

```python
{
    "prompt_version": "v3-priority",
    "jd_id": "JD-B010",
    "run_index": 0,
    "schema_pass": True,
    "fallback_used": False,
    "fallback_category": "none",
    "latency_ms": 1234,
    "rewrite_changed_rate": 0.42,
    "avg_len_after": 36.5,
    "tier_required_hit_rate": 0.80,
    "judge_quality_score": None,
    "judge_hallucination": None,
    "pii_safe": True,
}
```

不得保存:

- JD 原文
- bullet 原文
- 改写后 bullet 原文
- prompt 正文
- LLM response 原文
- judge reasoning

**离线模式行为:**

- 不发起 LLM HTTP 调用。
- 报告仍生成。
- `fallback_rate` 预期为 1.0 或接近 1.0。
- `judge_*` 字段为空或 `0`,并在报告顶部标注 “judge disabled / offline fallback”。

**live 模式行为:**

- 要求 LLM 已启用,否则退出码 2。
- 每个 version × JD × run 调 `preview_resume(... prompt_version=...)`。
- 固定 `enable_function_calling=True`、`enable_agent_workflow=True`。
- live 只是手动验收脚本,不进 pre-push。

---

### Phase 3 — 可选 LLM-as-Judge

**目标:** 在已有 A/B 报告上增加可选质量评分,但不阻断离线评测。

**新增逻辑位置:**

- 优先放在 `scripts/evaluate_prompt_versions.py` 内部 helper。
- 如果文件过长,再拆 `scripts/prompt_judge.py`。

**judge 输入:**

Judge 调用可以在进程内使用原 bullet / 改写 bullet / evidence summary / jd_focus,但这些内容不得写入报告或日志。

**judge 输出 schema:**

```json
{
  "quality_score": 1,
  "hallucination": 0,
  "tier_required_hit": 1
}
```

**rubric:**

| 字段 | 范围 | 含义 |
|---|---|---|
| `quality_score` | 1-5 | 事实真实、JD 对齐、简洁、量化、中文表达 |
| `hallucination` | 0/1 | 是否出现原 bullet / evidence 都没有的具体事实 |
| `tier_required_hit` | 0/1 | 有事实支撑时是否覆盖 tier_required |

**失败策略:**

- judge 网络失败、schema 错误、超时:该样本 judge 字段置空,`judge_error_count += 1`。
- judge 失败不影响主 A/B 报告生成。
- judge 不做 retry,避免 token 成本失控。

**测试:**

- `test_judge_schema_validates_score_range`
- `test_judge_invalid_json_returns_empty_metrics`
- `test_judge_error_does_not_fail_report`
- `test_report_never_includes_judge_reasoning`

---

### Phase 4 — 文档收尾,不 rollout

**目标:** 记录能力已就位,但明确默认 prompt 未切换。

**改动:**

- `README.md`
  - 当前状态补一行:Prompt A/B eval harness 已就位,默认 prompt 仍为 `v2-baseline`。
- `AGENTS.md`
  - 增加 R5-E 锁点段:prompt versioning、A/B report、隐私边界、默认不 rollout。
- `.harness/docs/ROADMAP.md`
  - 顶部快照补 R5-E。
  - 下一候选新增 “R5-E closeout / R5-F: 基于 live A/B 报告选择 winner 并 rollout”。
- `.harness/docs/round5-e-prompt-optimization-spec.md`
  - 状态改为“完成”只能在 Phase 1-4 代码、测试、文档都落地后进行。

**不做:**

- 不改 `SYSTEM_PROMPT` 默认内容。
- 不把 `PROMPT_VERSION_BASELINE` 改到 winner。
- 不新增前端 prompt selector。

---

## 4. 报告格式

默认输出:

```text
AI岗位JD库_prompt_ab报告.md
```

建议章节:

1. Eval 元信息
   - 日期
   - mode
   - versions
   - runs_per_version
   - llm_model
   - llm_base_url_host
   - judge on/off
2. Prompt 版本总览
   - 不展示 prompt 正文,只展示 version key 和短描述。
3. By Version 指标表
   - N
   - schema_pass_rate
   - fallback_rate
   - avg_latency_ms
   - p95_latency_ms
   - max_latency_ms
   - avg_rewrite_changed_rate
   - avg_len_after
   - tier_required_hit_rate
   - judge_quality_score_avg
   - hallucination_rate
   - pii_safe_rate
4. By JD 摘要
   - 只展示 `jd_id`、version、schema/fallback/latency/rewrite 数字。
5. Winner 建议
   - 只在 live 且 judge 数据有效时给建议。
   - 若数据不足,写 “insufficient live judge data”。
6. 隐私检查
   - 报告不含 prompt 正文、JD 原文、bullet 原文、API key。

---

## 5. 成功标准

R5-E 本轮完成时必须满足:

- `prompt_version=None` 默认路径保持 `v2-baseline`。
- `v2-baseline` payload system prompt 与当前 `SYSTEM_PROMPT` 内容一致。
- 4 个 prompt version 可显式选择。
- API / generator / workflow 全链路可透传 `prompt_version`。
- `scripts/evaluate_prompt_versions.py --mode offline` 能无 key 生成报告。
- 报告不含完整 prompt / JD / bullet / LLM response / API key。
- pytest 新增覆盖 prompt versioning、A/B report、judge schema、隐私边界。
- 全量后端 pytest 通过。
- 不修改前端,不新增依赖,不挂 pre-push。

---

## 6. 测试策略

### 6.1 必跑命令

```powershell
Set-Location -LiteralPath D:\简历帮\backend
D:\python3.11\python.exe -m pytest tests/test_prompt_versioning.py tests/test_prompt_eval.py -v
D:\python3.11\python.exe -m pytest tests/ -v
```

### 6.2 脚本冒烟

```powershell
Set-Location -LiteralPath D:\简历帮
D:\python3.11\python.exe scripts/evaluate_prompt_versions.py --mode offline --output AI岗位JD库_prompt_ab报告.md
```

期望:

- exit code 0
- 报告文件存在
- 报告含 4 个 prompt version key
- 报告不含 `LLM_API_KEY`
- 报告不含 `SYSTEM_PROMPT` 正文片段

### 6.3 可选 live 验收

仅用户明确提供 key 后手动跑:

```powershell
Set-Location -LiteralPath D:\简历帮
$env:LLM_ENABLED="true"
$env:LLM_API_KEY="..."
$env:LLM_MODEL="gpt-4o-mini"
D:\python3.11\python.exe scripts/evaluate_prompt_versions.py --mode live --runs-per-version 3 --judge on --output AI岗位JD库_prompt_ab报告_live.md
```

live 报告入库前必须人工检查隐私。若含真实 JD / bullet / prompt 正文,不得提交。

---

## 7. 风险与回退

| 风险 | 缓解 |
|---|---|
| prompt_version 透传破坏默认 payload | `test_default_prompt_payload_bytewise_stable` 锁死 |
| 候选 prompt 太长导致成本增加 | 报告计算 prompt 字符数;`v5-minimal` 作为短 prompt 对照 |
| judge 引入二次 LLM 成本和不稳定 | 默认 `--judge off`;失败不阻断报告 |
| 报告泄漏原文 | 只写聚合数字 + PII scan + 测试 sentinel |
| A/B 混入 workflow 变量 | 固定 FC/AW 配置,只变 prompt_version |
| winner 决策过早 | R5-E 不 rollout,只产数据 |

---

## 8. 文件改动清单

| 文件 | 动作 | 说明 |
|---|---|---|
| `backend/core/llm_rewriter.py` | 修改 | prompt version 常量、helper、payload 选择、透传 |
| `backend/core/generator.py` | 修改 | `build_sections` / preview / generate 透传 |
| `backend/core/agent_workflow.py` | 修改 | workflow 透传 prompt version |
| `backend/api/resume.py` | 修改 | request model 增加 `prompt_version` |
| `scripts/evaluate_prompt_versions.py` | 新增 | R5-E A/B 主脚本 |
| `backend/tests/test_prompt_versioning.py` | 新增 | 版本化和字节级稳定测试 |
| `backend/tests/test_prompt_eval.py` | 新增 | A/B report、judge、隐私测试 |
| `AGENTS.md` | 修改 | 同步 596 基线 + R5-E 锁点 |
| `README.md` | 修改 | 当前状态补 prompt A/B harness |
| `.harness/docs/ROADMAP.md` | 修改 | 快照与后续 rollout 候选 |
| `.harness/docs/round5-e-prompt-optimization-spec.md` | 修改 | 本 spec |
| `AI岗位JD库_prompt_ab报告.md` | 新增 | offline 报告 |
| `AI岗位JD库_prompt_ab报告_live.md` | 可选新增 | live 报告,需人工隐私检查 |

---

## 9. 推荐提交拆分

1. `docs(round5-e): refine prompt optimization spec`
2. `docs(round5-e): sync active baseline to 596`
3. `feat(round5-e): add prompt version selection`
4. `feat(round5-e): add prompt ab eval harness`
5. `docs(round5-e): record prompt ab offline report`
6. `docs(round5-e): close prompt ab harness round`

如果执行时 live A/B 也跑通,再追加:

7. `docs(round5-e): record live prompt ab results`

注意:第 7 个提交仍不 rollout winner。

---

## 10. R5-E 之后

R5-E 完成后,下一轮再二选一:

- **R5-E closeout / R5-F prompt rollout**:基于 live A/B 报告选择 winner,把默认 prompt 从 `v2-baseline` 切到 winner,同时保留 `v2-baseline` 显式回退路径。
- **R5-F embedding RAG**:如果 prompt A/B 显示 hallucination 仍高,先升级 evidence retrieval,不要急着切 prompt。

---

_最后更新:2026-06-28。_
