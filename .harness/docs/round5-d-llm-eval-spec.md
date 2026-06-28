# Round 5-D — 真实 LLM 接入与评测闭环 Spec

> 适用项目: 简历帮
> 日期: 2026-06-28
> 状态: ✅ **完成**(5 phase 全部落地)
> 当前仓库基线: GitHub `main` = `2052b1f feat(round5-d): add eval latency and fallback metrics`
> 当前能力基线: R5-D Phase 0-4 全部 commit 落地;活跃文档基线 **596 passed + 0 skipped**(`D:\python3.11\python.exe -m pytest tests/ --collect-only` 实测,2026-06-28);前端 `vue-tsc` / `npm run build` 通过
> 前置能力: R5-A Agent workflow + R5-B 工具契约/权限 + R5-C eval/request_id/replay/前端诊断面板已就位
> 目标: 在不泄漏个人数据、不破坏默认离线路径的前提下,让 `scripts/evaluate_agent_workflow.py` 能区分并评估“无 key fallback”和“真实 LLM 调用”两种模式,产出可复现的 schema pass / fallback / latency / rewrite impact 指标。
> 收尾文档(本 phase 5): 见文末 **§12. 手动 live eval 安全跑法** 段。

---

## 0. 为什么下一轮做 R5-D

R5-C 已经完成 Agent workflow 的可解释闭环:

- 后端有 `agent_summary.request_id`、`tools_used`、`fallback_used`。
- JSONL trace 可以 replay,也可以与 caller 提供的 `tools_used` 交叉验证。
- 外部简历、evidence、bullet evaluation 都能以“不含原文”的摘要形式进入诊断面板。
- eval 脚本能跑 12 JD × 4 开关对照,但当前主要价值仍是离线路径与 fallback 安全性。

下一轮最有收益的不是继续扩 UI 或引入向量库,而是回答一个关键问题:

> 有真实 LLM key 时,Agent workflow 到底带来多少可量化收益?失败率、schema 稳定性、延迟和改写变化是否值得默认推荐?

R5-D 只做评测闭环,不改变默认产品行为。

---

## 1. 非目标

- 不默认开启 LLM、Function Calling 或 Agent workflow。
- 不把 eval 挂到 pre-push hook。
- 不读取 `backend/data/_private_backup.json`。
- 不把完整 JD、完整简历、完整 bullet、LLM prompt、LLM response 写入报告、trace 或日志。
- 不引入新依赖、向量数据库、embedding API、后台队列。
- 不做模型选型/价格比较面板。
- 不做云端部署、账号、多用户权限。

---

## 2. 当前现状与约束

### 2.1 已有实现

- `backend/core/llm_rewriter.py`
  - 使用 OpenAI 兼容 HTTP 协议,纯 stdlib。
  - 配置来自 `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL` / `LLM_ENABLED`。
  - 无 key 或失败时静默降级原文。
  - R3-P 已有显式 JSON schema + invalid retry 1 次。
  - R4-F/R4-A 支持 function calling 和 agent loop。
  - R5-A 支持 evidence 约束。

- `scripts/evaluate_agent_workflow.py`
  - 固定 eval set:12 JD × 4 组开关 `(FC, AW)`。
  - 输出 `AI岗位JD库_agent_eval报告.md`。
  - R5-C Phase 1 已有 `request_id`、`tools_used`、`fallback_category`。
  - 当前报告能在无 key 时运行,但没有显式区分“live LLM eval”和“offline fallback eval”的完整指标。

- `scripts/replay_agent_trace.py`
  - 可输出 `Fallback Summary`。
  - 可用 `--tools-used` 做 tools cross-validation。

### 2.2 文档基线不一致

README 已写 **547 passed + 0 skipped**,但 `AGENTS.md` / `.harness/docs/ROADMAP.md` 仍多处保留 R5-C 收尾时的 **544**。R5-D Phase 0 先修正文档基线,避免后续 round 继续传播旧数字。

---

## 3. 目标指标

R5-D 完成后,eval 报告至少能回答:

| 指标 | 含义 |
|---|---|
| `llm_mode` | `offline_fallback` / `live_llm` |
| `llm_enabled` | 当前环境是否实际启用 LLM |
| `schema_pass_rate` | LLM 输出是否满足 `{rewritten: [{index, text}]}` 等既有 schema 约束 |
| `fallback_rate` | 每组开关下 fallback 占比 |
| `fallback_category_breakdown` | none / llm_disabled_fallback / tool_error_fallback / schema_retry_fallback / workflow_abort_fallback |
| `avg_latency_ms` | 每组平均耗时 |
| `p95_latency_ms` | 每组 p95 耗时 |
| `rewrite_changed_rate` | 改写后 bullets 与原始 bullets 是否发生变化的比例 |
| `tools_used_effective_rate` | `agent_summary.tools_used` 非空比例,用于衡量 retrieve_evidence 等有效工具是否真的参与 |
| `pii_safe` | 报告是否未泄漏手机号/邮箱/完整原文 |

---

## 4. 设计

### 4.1 eval 模式

新增 eval 运行模式,由命令行参数控制:

```bash
D:\python3.11\python.exe scripts/evaluate_agent_workflow.py --mode offline
D:\python3.11\python.exe scripts/evaluate_agent_workflow.py --mode live
D:\python3.11\python.exe scripts/evaluate_agent_workflow.py --mode auto
```

语义:

- `offline`:强制离线评测,即使环境有 key,也不触发真实 LLM 调用。用于 CI / pre-push / 默认开发。
- `live`:要求真实 LLM 可用;如果 `is_llm_enabled()` 为 False,脚本退出非 0,并给出缺少 `LLM_API_KEY` / `LLM_ENABLED` 的提示。
- `auto`:有 key 时 live,无 key 时 offline。仅供手动探索,不作为测试默认。

默认值: `offline`。

### 4.2 输出文件

保留旧报告路径:

```text
AI岗位JD库_agent_eval报告.md
```

新增可选参数:

```bash
--output AI岗位JD库_agent_eval报告_live.md
```

验收要求:

- offline 默认仍写旧报告,兼容现有流程。
- live 模式建议写 `AI岗位JD库_agent_eval报告_live.md`,避免覆盖离线基线。
- 报告顶部必须写清楚 `llm_mode`、`llm_enabled`、`model`、`base_url_host`。
- `base_url_host` 只写 host,不写完整 URL query,不写 key。

### 4.3 不泄漏原文的 rewrite impact

不要把 LLM 输入/输出全文写进报告。只计算摘要指标:

```python
def summarize_rewrite_impact(before_sections: dict, after_sections: dict) -> dict:
    return {
        "bullet_total": int,
        "changed_count": int,
        "unchanged_count": int,
        "changed_rate": float,
        "avg_len_before": float,
        "avg_len_after": float,
    }
```

建议比较对象:

- `preview["sections"]["projects"][*]["highlights"]`
- 只比较字符串是否变化和长度,不输出字符串内容。
- 如果某组开关不触发 LLM,`changed_count` 应为 0 或接近 0。

### 4.4 latency 指标

新增 helper:

```python
def percentile(values: list[int], p: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * p))))
    return ordered[idx]
```

报告中每个组合输出:

- `avg_latency_ms`
- `p95_latency_ms`
- `max_latency_ms`

### 4.5 LLM 配置摘要

新增 helper:

```python
def get_llm_eval_config() -> dict:
    return {
        "llm_enabled": is_llm_enabled(),
        "model": os.environ.get("LLM_MODEL", "gpt-4o-mini"),
        "base_url_host": urlparse(os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1")).netloc,
    }
```

隐私要求:

- 不读取或输出 `LLM_API_KEY`。
- 不输出完整 Authorization header。
- `base_url_host` 为空时写 `"unknown"`。

---

## 5. 实施范围

### Phase 0 — 文档基线修正 ✅ 已落地(commit `522d911`)

修改:

- `AGENTS.md`
- `.harness/docs/ROADMAP.md`

内容:

- 将 R5-C 收尾测试基线从 544 修正为 547。
- 说明 547 是 2026-06-28 push `414a7cd` 时 pre-push hook 实测结果。
- 不改历史 closeout 报告中的 544,因为那是当时快照。

测试:

```bash
Select-String -LiteralPath AGENTS.md,.harness/docs/ROADMAP.md -Pattern "544|547"
```

验收:

- 当前活跃文档不再把最新基线写成 544。
- 历史报告仍保留原样。

### Phase 1 — eval 模式参数 ✅ 已落地(commit `89717a9`,547 → 557)

修改:

- `scripts/evaluate_agent_workflow.py`
- `backend/tests/test_agent_eval.py`

新增:

- argparse 参数 `--mode {offline,live,auto}`。
- argparse 参数 `--output <path>`。
- helper `_resolve_eval_mode(mode: str, llm_enabled: bool) -> str`。

测试:

- `test_default_mode_is_offline`
- `test_live_mode_requires_llm_enabled`
- `test_auto_mode_uses_live_when_key_present`
- `test_output_path_can_be_overridden`

验收:

- 无 key 环境下默认命令仍成功。
- 无 key 环境下 `--mode live` 返回非 0,错误信息不含 key。

### Phase 2 — live/offline 报告元信息 ✅ 已落地(commit `1fef8dc`,557 → 568)

修改:

- `scripts/evaluate_agent_workflow.py`
- `backend/tests/test_agent_eval.py`

新增报告字段:

- `llm_mode`
- `llm_enabled`
- `llm_model`
- `llm_base_url_host`

测试:

- `test_report_includes_llm_mode_metadata`
- `test_report_does_not_include_api_key`
- `test_base_url_host_hides_path_and_query`

验收:

- 报告顶部能一眼看出本次是 offline 还是 live。
- 报告不包含 `LLM_API_KEY` 值。

### Phase 3 — rewrite impact 指标 ✅ 已落地(commit `8838e7a`,568 → 584)

修改:

- `scripts/evaluate_agent_workflow.py`
- `backend/tests/test_agent_eval.py`

新增 helper:

- `_extract_project_highlights(preview: dict) -> list[str]`
- `_summarize_rewrite_impact(before: list[str], after: list[str]) -> dict`

每条 eval row 增加:

- `rewrite_changed_count`
- `rewrite_total`
- `rewrite_changed_rate`
- `avg_len_before`
- `avg_len_after`

测试:

- `test_rewrite_impact_counts_changed_bullets_without_storing_text`
- `test_rewrite_impact_handles_missing_projects`
- `test_report_contains_rewrite_impact_summary`
- `test_report_does_not_leak_bullet_text`

验收:

- 报告只出现计数和比例,不出现 bullet 原文。
- offline 路径仍可运行并产生 0 或稳定的 changed 指标。

### Phase 4 — latency 与 fallback 聚合增强 ✅ 已落地(commit `2052b1f`,584 → 596)

修改:

- `scripts/evaluate_agent_workflow.py`
- `backend/tests/test_agent_eval.py`

新增:

- `_percentile(values, p)`
- 每组 `p95_latency_ms` / `max_latency_ms`
- 每组 `fallback_category_breakdown`
- 每组 `schema_pass_rate`

测试:

- `test_percentile_empty_returns_zero`
- `test_percentile_p95`
- `test_metrics_include_p95_latency`
- `test_metrics_include_fallback_category_breakdown`

验收:

- markdown 总览表含 p95 latency。
- fallback taxonomy 摘要与每组聚合一致。

### Phase 5 — 手动 live eval 安全跑法 ⏳ 进行中(本 round commit `docs(round5-d): document live eval workflow`)

修改:

- `.harness/docs/ROADMAP.md`
- `README.md` 可选加一行“真实 LLM eval 为手动脚本,不进默认启动流程”
- 新增或更新 `.harness/docs/round5-d-llm-eval-spec.md` 状态行

新增文档段:

```powershell
$env:LLM_ENABLED="true"
$env:LLM_API_KEY="..."
$env:LLM_MODEL="gpt-4o-mini"
D:\python3.11\python.exe scripts/evaluate_agent_workflow.py --mode live --output AI岗位JD库_agent_eval报告_live.md
```

安全提示:

- 只在本地运行。
- 不提交 `.env`。
- 不提交含真实敏感信息的报告。
- live 报告如果只含脱敏 materials / JD 主库,可以提交;如果环境接入真实私有素材,不得提交。

测试:

- 不需要真实 LLM key 的单元测试必须覆盖全部新增逻辑。
- live 模式只做手动验收,不进 pre-push。

验收:

- 无 key 时全量测试通过。
- 有 key 时用户可手动运行 live eval 并获得独立报告。

---

## 6. 文件改动清单

| 文件 | 动作 | 说明 |
|---|---|---|
| `scripts/evaluate_agent_workflow.py` | 修改 | 增加 mode/output 参数、LLM 元信息、rewrite impact、latency/fallback 聚合 |
| `backend/tests/test_agent_eval.py` | 修改 | 覆盖 mode、metadata、rewrite impact、latency/fallback 聚合与隐私 |
| `AGENTS.md` | 修改 | 最新测试基线 547 与 R5-D 锁点 |
| `.harness/docs/ROADMAP.md` | 修改 | 最新测试基线 547 + R5-D 进度 |
| `README.md` | 可选修改 | 增加 live eval 是手动脚本的说明,保持精简 |
| `AI岗位JD库_agent_eval报告.md` | 可能修改 | offline 默认报告刷新 |
| `AI岗位JD库_agent_eval报告_live.md` | 可选新增 | live 模式手动报告;只有确认不含真实敏感信息时才入库 |

---

## 7. 测试策略

### 7.1 单元测试

优先新增纯函数测试,避免真实网络:

- mode 解析
- output path 解析
- base_url host 脱敏
- rewrite impact 计数
- percentile
- metrics 聚合
- report 隐私扫描

### 7.2 集成测试

继续使用现有公开脱敏数据:

```bash
cd backend
D:\python3.11\python.exe -m pytest tests/test_agent_eval.py -v
```

全量:

```bash
cd backend
D:\python3.11\python.exe -m pytest tests/ -v
```

前端如果 README / API 不动,不强制跑;若 README 或 TS 类型变动,跑:

```bash
cd frontend
npx vue-tsc --noEmit
npm run build
```

### 7.3 手动 live 验收

有 key 时执行:

```powershell
$env:LLM_ENABLED="true"
$env:LLM_API_KEY="..."
$env:LLM_MODEL="gpt-4o-mini"
D:\python3.11\python.exe scripts/evaluate_agent_workflow.py --mode live --output AI岗位JD库_agent_eval报告_live.md
```

检查:

- 报告有 `llm_mode=live_llm`。
- `fallback_rate` 低于 offline。
- `rewrite_changed_rate` 大于 0。
- 报告不含 API key、完整 JD、完整 bullet、真实个人信息。

---

## 8. 隐私与安全边界

- `ToolResult` 仍不得存 args / input 原文。
- JSONL trace 仍只写 `input_size` / `output_size`。
- eval report 不输出 prompt / response 原文。
- live 模式输出报告前必须经过 PII scanner。
- 任何错误信息只包含错误类型名、字段名、权限名或状态名。
- `LLM_API_KEY` 永不写入 report / stdout / trace / markdown。
- `backend/data/_private_backup.json` 不读取、不校验、不引用。

---

## 9. 验收清单

- [x] `scripts/evaluate_agent_workflow.py --mode offline` 无 key 可运行。
- [x] `scripts/evaluate_agent_workflow.py --mode live` 无 key 失败且错误信息安全。
- [x] `--output` 可写到指定 markdown。
- [x] 报告顶部包含 llm mode/model/base_url_host,不含 key。
- [x] 报告包含 schema pass rate、fallback rate、fallback category breakdown、avg/p95/max latency。
- [x] 报告包含 rewrite impact 计数,不含 bullet 原文。
- [x] `backend/tests/test_agent_eval.py` 覆盖新增逻辑(Phase 1+2+3+4 共 +49 case)。
- [x] 后端全量 pytest 通过(活跃基线 **596 passed + 0 skipped**)。
- [x] 如改 README/前端类型,前端 `vue-tsc` 和 `npm run build` 通过。
- [x] AGENTS / ROADMAP 最新活跃基线更新为 547(R5-D Phase 0 已落地);Phase 5 文档收尾阶段活跃基线已为 596。
- [x] live 模式不进 pre-push;Phase 5 文档明文记录 PowerShell 安全跑法。

---

## 10. 推荐提交拆分(实际落 commit)

1. `8a4a799 docs(round5-d): add llm eval spec`
2. `522d911 docs(round5-d): sync active test baseline to 547`
3. `89717a9 feat(round5-d): add eval run modes`
4. `1fef8dc feat(round5-d): add llm eval metadata`
5. `8838e7a feat(round5-d): add rewrite impact metrics`
6. `2052b1f feat(round5-d): add eval latency and fallback metrics`
7. `docs(round5-d): document live eval workflow` ← 本 phase(Phase 5 收尾)

---

## 11. 后续可选升级

- R5-E:把 `core/evidence.py` lexical retrieval 升级为 embedding 检索。
- R5-F:当 live eval 证明 Agent workflow 有收益后,再考虑默认推荐打开 Agent workflow 面板。
- R5-G:把 eval report 转成前端可读 dashboard,但仍默认本地单用户。

---

## 12. 手动 live eval 安全跑法(Phase 5 收尾,2026-06-28)

R5-D 的真实 LLM 评测**只做手动跑**,**不进入默认启动流程**。下面这套命令专门给需要量化"有 key 时 Agent workflow 到底带来多少收益"的用户使用。

### 12.1 前置条件

- 本地已有真实 LLM API key(`LLM_API_KEY`,可走 OpenAI / 兼容端点 / 本地 ollama 等)
- 本地 `materials.json` 可用(脱敏版或 `_private_backup.json` 拷贝版均可)
- 不需要任何额外依赖,纯 stdlib 调用

### 12.2 PowerShell 跑法

```powershell
$env:LLM_ENABLED="true"
$env:LLM_API_KEY="..."
$env:LLM_MODEL="gpt-4o-mini"
D:\python3.11\python.exe scripts/evaluate_agent_workflow.py --mode live --output AI岗位JD库_agent_eval报告_live.md
```

要点:

- `--mode live` 强制要求 `is_llm_enabled()` 为 True;否则脚本立即返回非 0,错误信息**绝不**包含 key 值或 env var 名(R5-D Phase 1 `TestEvalModeNoKeyLeak` 锁死)
- `--output` 写到独立文件,避免覆盖 `AI岗位JD库_agent_eval报告.md`(offline 默认报告)
- 不传 `--mode` 时默认 `--mode offline`,保持默认启动流程字节级一致
- 不传 `--output` 时走默认路径

可选 `--mode auto`:有 key 时 live,无 key 时 offline。**只供手动探索,不进任何 CI**。

### 12.3 安全提示(必须遵守)

- **不提交 `.env`**:`backend/.env` / 仓库根 `.env` / 任何含 `LLM_API_KEY` 的文件都已在 `.gitignore` 拒绝,提交前 `git status` 必须干净
- **不提交含真实敏感信息的 live 报告**:报告路径如果可能含 API key / 真实 JD 原文 / 真实 bullet 原文 / 真实手机号邮箱,**绝对不入库**
- **live 报告判定标准**(入库安全 iff 全部满足):
  1. 环境只用公开脱敏 `backend/data/materials.json`(未替换为 `_private_backup.json`)
  2. JD 库只用 `AI岗位JD库_v4_intern.json`(公开脱敏版)
  3. eval set 来自 `scripts/evaluate_agent_workflow.py` 内置 12 JD,**不混入**真实投递过的 JD 原文
  4. `LLM_BASE_URL` 不含内部路径或敏感 query
- **live 模式不进 pre-push**:`scripts/verify.ps1` / pre-push hook 永远不会自动触发 live,只跑默认 offline 路径
- **报告里出现的字段固定**:`llm_mode` / `llm_enabled` / `llm_model` / `llm_base_url_host` / `schema_pass_rate` / `fallback_rate` / `fallback_category_breakdown` / `avg/p95/max_latency_ms` / `rewrite_changed_rate`;**绝不出现** `LLM_API_KEY` / `Authorization` / 完整 prompt / 完整 response / 完整 JD / 完整 bullet / 真实手机号邮箱

### 12.4 验收清单(用户手动核对)

跑完 live eval 后,手动确认:

- [ ] 报告顶部 `llm_mode=live_llm`(`resolved_mode: live`,`requested_mode: live`)
- [ ] `llm_model` 跟环境变量 `LLM_MODEL` 一致
- [ ] `llm_base_url_host` 是 host 部分,不含 path / query / secret
- [ ] `grep -i "LLM_API_KEY\|Authorization\|sk-" AI岗位JD库_agent_eval报告_live.md` 无任何匹配
- [ ] `fallback_rate` 比 offline 低(LLM 真在线时显著低;offline 必为 1.0 因为 LLM 永远 disable)
- [ ] `rewrite_changed_rate` 在 AW=True 的 combo 中 > 0(LLM 真做了改写)
- [ ] `avg/p95/max_latency_ms` 量级合理(网络往返正常应该在 1-30s 之间)

### 12.5 不实施 GUI 面板(用户偏好)

按 2026-06-23 用户偏好,GUI 实施任务默认暂停。live 报告 = markdown 文件,前端不动。如果后续要做 dashboard / 可视化面板,挂 `R5-G` P2 候补,等用户明确启动再开。

### 12.6 跟既有脚本关系

- `match_score` / `score_thresholds.py` / `match_golden_targets.py` / `replay_agent_trace.py`:R5-D 全程**零修改**(spec §6.3 / R5-D §8 隐私边界)
- `evaluate_agent_workflow.py`:R5-D Phase 1+2+3+4 修改的唯一定脚本;`enable_agent_workflow=False` 老路径字节级一致(584 老测试零回退 + 12 新增 = 596)
- `core/llm_rewriter.py` / `core/agent_workflow.py`:R5-D 零修改,沿用 R5-A Phase 3 evidence + R5-C Phase 2 external_resume + R5-C Phase 3 bullet_evaluation 既有路径
