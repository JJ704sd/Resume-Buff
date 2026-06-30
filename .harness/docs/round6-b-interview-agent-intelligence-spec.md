# Round 6-B — 面试官智能体可信增强 Spec

> 适用项目: 简历帮 / Resume-Buff  
> 参考项目: [JJ704sd/Resume-Buff](https://github.com/JJ704sd/Resume-Buff) (`main`)  
> 本地日期: 2026-06-30  
> 状态: 下一轮候选 spec, 未实施  
> 本地基线: `119575c docs(round6-a): sync active baseline 739 after phase 4`  
> 当前能力基线: R6-A Phase 1+2+3+4+5 已完成,后端活跃基线 **739 tests collected**。`/api/interview/draft` 状态 bug 已由 `37ad00c fix(round6-a): set draft endpoint state to draft ready` 修复;LLM slot extraction 已由 `074b364 feat(round6-a): add llm slot extraction to interview agent` 落地。  
> 公开 README/ROADMAP 可能仍停留在 R6-A Phase 4 未启、729 baseline 的描述;R6-B 以本地 AGENTS.md 与代码现状为准。

---

## 0. 结论

R6-B 不应该重做“LLM 槽位抽取”,也不应该把面试官改成自由聊天 Agent。R6-A Phase 4 已经在 `backend/core/interview_agent.py` 内实现了可选 LLM slot extraction:

- `extract_slots(..., llm_enabled=False)` 默认规则路径,保持 R6-A Phase 1 行为。
- `llm_enabled=True` 且有 key 时走 stdlib `urllib` 调 OpenAI-compatible `/chat/completions`。
- JSON / schema 错误 retry 1 次;网络错误不 retry;失败全部 fallback 规则版。
- prompt 独立放在 `core.interview_prompts`,不进 `PROMPT_VERSIONS`,且 user template 不含 `{jd_text}`。

所以 R6-B 的真实增量是 **可信增强层**:

```text
用户回答
→ 现有规则 + 可选 LLM 抽取
→ 为抽取结果补 slot_meta: confidence / source_span_hash / turn_index / extractor
→ deterministic policy 根据缺失、低置信度、轮数决定下一问
→ draft_card 生成后做 fact verification
→ 用户确认后才 save_card 写库
→ eval compare 证明 llm_assisted 相比 rules 是否真正提升
→ 前端只暴露“智能抽取 / 规则模式 / 需确认”,不暴露技术术语
```

第一性原理:Resume-Buff 是本地单用户简历素材工具。价值不是“像 Agent”,而是帮用户把真实经历更省力、更可追溯地变成可复用素材。任何智能化都必须服从四个约束:

1. **不编造**:没有用户来源的事实不能进入素材库。
2. **不越权**:LLM 不能自主写库、不能自主选工具、不能替代人工确认。
3. **不泄漏**:trace / eval report / stdout 不含 user_message、prompt、raw response、source_span 明文或 API key。
4. **不破坏旧路径**:`enable_interview_llm=False` 或无 key 时,start → reply → draft → save-card 仍照常完成。

---

## 1. 当前现状

### 1.1 已完成能力

R6-A 本地现状:

- `backend/core/interview_agent.py`
  - 面试 session 状态机。
  - 4 个固定 gap: `process_metric` / `tech_metric` / `communication` / `domain_x`。
  - 规则 gap selection / slot extraction / draft_card / save_card。
  - R6-A Phase 4 已加入可选 LLM slot extraction,但尚未通过 API/前端暴露为用户可控模式。
- `backend/core/interview_prompts.py`
  - 问题模板、快捷回复、收束条件。
  - `SLOT_EXTRACTION_SYSTEM_PROMPT` / `SLOT_EXTRACTION_USER_TEMPLATE` / `INTERVIEW_LLM_TIMEOUT_SEC`。
- `backend/api/interview.py`
  - `/api/interview/start`
  - `/api/interview/reply`
  - `/api/interview/draft`
  - `/api/interview/save-card`
  - `interview_draft()` 已显式设置 `InterviewState.DRAFT_READY`。
- `frontend/src/components/InterviewAgentPanel.vue`
  - 桌面右侧聊天栏 + 移动端 drawer。
  - 草稿卡编辑与 save-card 后刷新 match / preview。
- `scripts/evaluate_interview_agent.py`
  - 规则版 offline eval scaffold。
  - 当前脚本仍写着“Phase 4 LLM 未上线”的旧说明,这是 R6-B 需要修正的文档/脚本口径之一。

### 1.2 真实短板

当前短板不是“没有 LLM”,而是 LLM 抽取还没有形成产品闭环:

| 短板 | 当前状态 | R6-B 应补 |
|---|---|---|
| 抽取结果不可追溯 | `extract_slots()` 返回 slot 值,不沉淀 source/provenance 摘要 | `slot_meta` 只存 hash/len/turn/confidence/extractor |
| 用户不能控制智能模式 | API/前端 `StartRequest` 还没有 `enable_interview_llm` | start 时选择 rules / llm_assisted,reply 沿用 session mode |
| 下一问仍偏模板化 | `next_question()` 主要按固定 slot 顺序 | policy 根据缺失和低置信度挑下一问 |
| draft 缺核验摘要 | draft_card 直接基于 captured slots 生成 | verifier 标出低置信度和无来源 claim |
| eval 没有对照组 | 脚本只有规则 baseline | `--extractor rules|llm|compare` 对照 |

---

## 2. 产品原则

### 2.1 用户雇用“面试官”的任务

用户不是来体验聊天机器人,而是来完成一个本地工作:

> 把自己说不清的真实经历,整理成可确认、可追溯、可复用的简历素材。

因此智能体的价值排序是:

1. **真实**:不能把模型猜测、建议、JD 要求写成用户经历。
2. **省力**:少问、问准、允许用户自然表达。
3. **可解释**:能解释某个素材点来自第几轮回答的哪类事实。
4. **可回退**:没有 key / LLM 失败时规则路径仍可用。
5. **可评测**:智能化收益必须能被 eval compare 观察。

### 2.2 LLM 权限边界

LLM 可以参与:

- 从单轮用户回答中抽取结构化槽位。
- 在已选定 slot 的前提下,把问题表达改得更自然。
- 对 draft_card 做只读事实一致性检查。
- 在 eval 脚本中与规则版对比。

LLM 不可以参与:

- 自主选择任意工具。
- 自主写入 `materials.json`。
- 基于 JD 或常识补充用户没说过的事实。
- 把完整 JD、完整 user_message、完整 draft_card 写入 trace / report。
- 默认开启 live eval。
- 替换 `core.agent_workflow.py` 或把 interview agent 接入通用 Agent 工具图。

---

## 3. 方案取舍

### 方案 A: 自由聊天 Agent

让 LLM 接管对话、自由追问、自由抽取和生成素材。

结论:不采用。它看起来最“智能”,但最难证明没有编造,也会破坏当前状态机、pytest 锁点和本地隐私边界。

### 方案 B: 另建 `interview_llm.py` 重做抽取

把 R6-B 做成新的 interview LLM adapter、prompt、HTTP call 和 retry/fallback。

结论:不采用为默认路径。因为本地 R6-A Phase 4 已经在 `interview_agent.py` 内落地了这些能力,现在重复拆模块会制造迁移风险。只有当后续维护确认 `interview_agent.py` 继续膨胀到难以测试时,再单独做“机械拆分,行为不变”的重构 round。

### 方案 C: 基于既有 LLM 抽取补可信闭环(采用)

保留 R6-A 状态机、save-card 闭环和已实现的 `extract_slots(..., llm_enabled=...)`,新增:

- `slot_meta` provenance 摘要。
- API/前端可控的 `enable_interview_llm`。
- deterministic question policy。
- draft verifier。
- eval compare。

这是最符合第一性原理的路径:不扩大行动权,只补“事实来源、决策依据、保存前确认、收益证明”。

---

## 4. 总体架构

```text
api/interview.py
  -> create_session(..., interview_mode)
  -> apply_action(...)
       -> extract_slots(..., llm_enabled=session.interview_mode == "llm_assisted")
       -> merge captured_slots
       -> update slot_meta
       -> interview_policy.plan_next_question(session)
       -> build_draft_card(session)
       -> interview_verifier.verify_draft_card(card, session)
       -> save_card(session, edited_card, save_mode)

scripts/evaluate_interview_agent.py
  -> --extractor rules | llm | compare
  -> same eval set
  -> privacy-safe metrics report
```

### 4.1 文件边界

新增或修改:

| 文件 | 职责 |
|---|---|
| `backend/core/interview_agent.py` | 保留 orchestration;增加 session mode、slot_meta 更新、调用 policy/verifier |
| `backend/core/interview_policy.py` | deterministic next-question policy,不调用网络 |
| `backend/core/interview_verifier.py` | draft_card fact verification,不写库 |
| `backend/api/interview.py` | Start/Reply/Draft response 增加 optional 字段 |
| `frontend/src/api/index.ts` | 增加 interview mode / extraction summary / verification 类型 |
| `frontend/src/components/InterviewAgentPanel.vue` | 最小 UI:智能抽取 toggle、模式状态、warning 展示 |
| `scripts/evaluate_interview_agent.py` | 支持 extractor compare;修正旧 Phase 4 口径 |

暂不新增:

- 不新增 `backend/core/interview_llm.py`。
- 不迁移已实现的 `_call_llm_for_slot_extraction()`。
- 不修改 `core.agent_workflow.py` / `core.agent_tools.py` / `core.tool_schema.py`。
- 不修改 `PROMPT_VERSIONS` 或默认 resume rewrite prompt。

---

## 5. 数据模型

### 5.1 InterviewSession 扩展

新增可选字段,必须有默认值以保持旧测试构造兼容:

```python
interview_mode: str = "rules"          # "rules" | "llm_assisted"
mode_warning: str | None = None
slot_meta: dict[str, Any] = field(default_factory=dict)
question_plan: dict[str, Any] | None = None
verification_summary: dict[str, Any] | None = None
```

约束:

- `interview_mode="rules"`:不调 LLM。
- `interview_mode="llm_assisted"`:有 key 且 env 允许时调 LLM;失败 fallback rules。
- `mode_warning` 只写用户可见摘要,例如“智能抽取不可用,已使用规则模式”。
- `slot_meta` 不存 user_message / source_span 明文。

### 5.2 slot_meta

示例:

```python
{
  "action": [
    {
      "extractor": "llm",
      "confidence": 0.92,
      "turn_index": 2,
      "source_span_hash": "sha256:abcd1234",
      "source_span_len": 9,
      "reason_code": "explicit_action"
    }
  ],
  "metric": [
    {
      "extractor": "rules",
      "confidence": 0.75,
      "turn_index": 3,
      "source_span_hash": "sha256:ef901234",
      "source_span_len": 4,
      "reason_code": "regex_metric"
    }
  ]
}
```

规则:

- LLM `source_span` 只允许在当前函数调用内做匹配和 hash,不得进入 session / trace / API response。
- 规则抽取没有精确 span 时,可使用当前 user_message 中命中的最短证据片段;找不到时只记录 `extractor="rules"`、`confidence`、`turn_index`。
- `confidence` 范围 `[0.0, 1.0]`,bool 不接受。
- list slot 最多保留 5 条 meta。

### 5.3 API optional 字段

`StartRequest`:

```python
enable_interview_llm: bool = False
```

`StartResponse` 增加:

```python
interview_mode: Literal["rules", "llm_assisted"]
mode_warning: str | None
```

`ReplyResponse` 增加:

```python
extraction_summary: {
  "extractor": "rules" | "llm" | "mixed",
  "fallback_used": bool,
  "captured_slots": list[str],
  "low_confidence_slots": list[str]
} | None

question_plan: {
  "slot": str,
  "reason_code": str,
  "low_confidence_slots": list[str]
} | None
```

`DraftResponse.draft_card` 可增加:

```python
confidence_notes: list[str]
verification: {
  "claims_total": int,
  "claims_supported": int,
  "low_confidence_claims": int,
  "unsupported_claims": int
}
```

所有新增字段均为 optional 或有默认值,老前端不消费也不应报错。

---

## 6. 下一问策略

新增 `backend/core/interview_policy.py`:

```python
def plan_next_question(session: InterviewSession) -> dict[str, Any]:
    ...
```

返回:

```python
{
  "slot": "metric",
  "reason_code": "missing_metric_before_draft",
  "question": "如果想得起来,有没有一个数字能说明效果?没有也可以直接说没有。",
  "quick_replies": ["没有数据", "大概有", "想不起来", "整理成素材"],
  "can_draft": True,
  "low_confidence_slots": ["result"]
}
```

优先级:

1. 尚未满足任一 `CAN_DRAFT_CONDITIONS` 的必要 slot。
2. 已有值但 `confidence < 0.6` 的 slot。
3. 当前 gap 的 `suggested_slots` 尚未覆盖的 slot。
4. `turn_count >= MAX_TURNS_PER_GAP - 1` 时优先问 `result` 或 `metric`。
5. 连续 skip 达上限时强制 draft。

防重复:

- 同一 slot 不连续问两次,除非上一次 confidence < 0.4。
- `rephrase_question` 只能改写当前 slot 的问法,不能换 slot。
- `switch_gap` 后清空或隔离旧 gap 的 question plan,避免跨 gap 混用。

LLM 不决定 slot 顺序。若后续加入 LLM question rewrite,也只能在 policy 已选 slot 后改写问题文本,并且默认关闭。

---

## 7. Draft 核验

新增 `backend/core/interview_verifier.py`:

```python
def verify_draft_card(card: dict[str, Any], session: InterviewSession) -> dict[str, Any]:
    ...
```

目标:

- 不调用 LLM 也能跑。
- 检查 draft_bullets 中的量化数字是否能在 captured slots 或 slot_meta 中找到来源。
- 检查每条 bullet 是否至少有 action / responsibility / result 中的一类来源。
- 对 `confidence < 0.6` 的 slot 生成 warning。
- 不阻止保存,但让前端在保存前展示确认提示。

输出:

```python
{
  "claims_total": 3,
  "claims_supported": 3,
  "low_confidence_claims": 1,
  "unsupported_claims": 0,
  "warnings": ["结果描述置信度较低,保存前请确认。"]
}
```

`save_card()` 写入 `_interview_meta` 时可追加摘要:

```python
"_interview_meta": {
  "source_gap_id": "...",
  "source_session_id": "...",
  "created_at": "...",
  "warnings": [...],
  "extraction_mode": "llm_assisted",
  "verification": {
    "claims_total": 3,
    "claims_supported": 3,
    "unsupported_claims": 0
  }
}
```

禁止把完整对话、source_span 明文、draft_card 原文写入 `_interview_meta`。

---

## 8. Eval 设计

扩展 `scripts/evaluate_interview_agent.py`:

```powershell
D:\python3.11\python.exe scripts/evaluate_interview_agent.py --mode offline --extractor rules
D:\python3.11\python.exe scripts/evaluate_interview_agent.py --mode offline --extractor compare
D:\python3.11\python.exe scripts/evaluate_interview_agent.py --mode live --extractor compare --output backend/logs/interview_eval_report_live.md
```

`--extractor`:

- `rules`:当前规则 baseline,默认。
- `llm`:只跑 llm_assisted。offline 时不得发网络,应标记 `llm_disabled_fallback`。
- `compare`:同一批样本跑 rules + llm_assisted,报告对照。

指标:

| 指标 | 含义 |
|---|---|
| `schema_pass_rate` | expected slots 是否被填齐 |
| `avg_completeness` | draft_card 六类字段完整度 |
| `fabrication_violations_count` | verifier 发现无来源硬事实数量 |
| `fallback_rate` | llm_assisted 中 fallback 占比 |
| `avg_turns_to_draft` | 达到可 draft 的平均轮数 |
| `low_confidence_slot_rate` | 低置信度 slot 占比 |
| `p95_latency_ms` | 单样本端到端 p95 |

live mode 仍必须手动运行,不挂 pre-push。stdout / report 不允许出现 user_message、prompt、raw response、source_span、API key。

产品判断目标:

- `schema_pass_rate` 相比 rules baseline 明显提升,目标 ≥0.60。
- `avg_completeness` 目标 ≥0.70。
- `fabrication_violations_count = 0`。
- `fallback_rate` live 环境目标 ≤0.20。

这些目标用于判断是否默认开放智能抽取,不作为 CI 硬门槛。

---

## 9. 前端最小呈现

`InterviewAgentPanel.vue` 只做最小 UI:

- 启动区域增加 `智能抽取` toggle,默认关闭。
- tooltip: `实验功能:有 key 时帮助识别你回答中的多个事实;失败会自动回到规则模式。`
- 面板 header 显示:
  - `规则模式`
  - `智能抽取`
  - `已回退规则模式`
- draft_card 区域显示 `confidence_notes`。
- 保存前若有 low confidence / unsupported warning,弹确认提示。

禁止:

- 前台出现 `Agent Workflow` / `trace` / `schema` / `ToolResult`。
- 向普通用户展示 LLM prompt / raw response。
- 把 source_span 明文展示在 UI 中。

---

## 10. 测试策略

### Phase 0: 基线校准

目标:

- 删除 spec / eval 脚本中过时的“Phase 4 未上线”叙述。
- 保持 `/api/interview/draft` bugfix 回归测试。
- 确认 739 baseline 口径。

验证:

```powershell
cd backend
D:\python3.11\python.exe -m pytest tests/test_interview_api.py::TestDraftEndpoint tests/test_interview_agent.py::TestLLMSlotExtraction tests/test_interview_agent.py::TestInterviewPromptRegistry -q
```

### Phase 1: slot_meta provenance

新增/修改测试:

- `tests/test_interview_agent.py`
  - `InterviewSession` 新字段默认不破坏旧构造。
  - rules mode 会写基本 slot_meta。
  - llm_assisted mode 会把 valid source_span 转成 hash/len,不存明文。
  - invalid source_span 被丢弃或降级,不污染 session。

### Phase 2: API mode 开关

新增/修改测试:

- `tests/test_interview_api.py`
  - `StartRequest.enable_interview_llm=False` 默认 rules。
  - 无 key 且 enable=True 时 start 成功,返回 rules + mode_warning。
  - 有 key 且 enable=True 时 session mode 为 llm_assisted。
  - `ReplyRequest` 不重复传开关,沿用 session mode。

### Phase 3: policy skeleton

新增 `tests/test_interview_policy.py`:

- missing required slot 优先。
- low confidence slot 优先。
- turn_count 接近上限时优先 result/metric。
- consecutive skip 强制 draft。
- rephrase 不换 slot。

### Phase 4: draft verifier

新增 `tests/test_interview_verifier.py`:

- 量化数字有来源 → pass。
- 量化数字无来源 → warning。
- action/responsibility 无来源 → warning。
- low confidence slot → confidence_notes。
- verifier summary 不含 source_span 明文。

### Phase 5: eval compare

修改 `tests/test_interview_eval.py`:

- `--extractor rules` 默认行为不变。
- `--extractor compare` 输出 rules / llm_assisted 两组。
- offline compare 不调用 `urllib.request.urlopen`。
- report 不含 user_message / prompt / raw response。
- metrics 含 fallback_rate / low_confidence_slot_rate / p95_latency_ms。

### Phase 6: frontend

无 Vitest 配置,沿用 R6-A 前端验收:

```powershell
cd frontend
npx vue-tsc --noEmit
npm run build
```

浏览器 smoke:

- 桌面 1280x800:toggle 可见,不挤压预览。
- 移动 375x812:drawer 内 toggle / warning 不与输入区冲突。
- 无 key:开启智能抽取后明确显示已回退规则模式。

---

## 11. 分阶段落地建议

最小有价值闭环:

```text
Phase 0 基线校准
→ Phase 1 slot_meta provenance
→ Phase 2 API mode 开关
→ Phase 5 eval compare
```

确认数据有收益后再做:

```text
Phase 3 confidence-aware policy
→ Phase 4 draft verifier
→ Phase 6 frontend 最小呈现
```

原因:

- 先补 provenance,否则 LLM 抽取仍不可解释。
- 先补 API mode,否则前端和 eval 都没有稳定入口。
- 先做 eval compare,否则无法判断智能抽取是否值得继续产品化。
- frontend 不先行复杂化,避免 UI 上出现没有数据支撑的“智能开关”。

---

## 12. 成功指标

工程指标:

- `enable_interview_llm=False` 时 R6-A 行为保持兼容。
- 无 key / LLM 失败时仍能完成 start → reply → draft → save-card。
- 测试不写真实 `backend/data/materials.json`。
- trace / report / stdout 不含 user_message、prompt、raw response、source_span 明文、API key。
- 不引入新第三方依赖。
- 不修改 `core.agent_workflow.py` / `core.agent_tools.py` / `core.tool_schema.py`。
- 不修改 `PROMPT_VERSIONS` / 默认简历改写 prompt。

产品指标:

- compare 中 `schema_pass_rate ≥ 0.60` 或相对 rules baseline 明显提升。
- compare 中 `avg_completeness ≥ 0.70`。
- `fabrication_violations_count = 0`。
- 平均追问轮数不超过 rules baseline。
- 用户保存前能看到低置信度或 unsupported warning。

---

## 13. 非目标清单

R6-B 不做:

- 不做自由聊天助手。
- 不做模拟面试训练。
- 不做自动投递。
- 不做账号 / 云端 / 多用户。
- 不引入向量数据库、Redis、后台队列。
- 不把完整对话持久化。
- 不让 LLM 自动保存素材。
- 不重构已落地的 LLM slot extraction 到新模块。
- 不改默认 resume rewrite prompt。
- 不 rollout R5-E prompt winner。
- 不把 live eval report 自动入库。

---

## 14. 验收命令

后端局部:

```powershell
cd backend
D:\python3.11\python.exe -m pytest tests/test_interview_api.py tests/test_interview_agent.py tests/test_interview_policy.py tests/test_interview_verifier.py tests/test_interview_eval.py -q
```

后端全量:

```powershell
cd backend
D:\python3.11\python.exe -m pytest tests/ -q
```

eval offline:

```powershell
D:\python3.11\python.exe scripts/evaluate_interview_agent.py --mode offline --extractor compare --output backend/logs/interview_eval_report.md
```

前端:

```powershell
cd frontend
npx vue-tsc --noEmit
npm run build
```

隐私自检:

```powershell
Select-String -LiteralPath backend\logs\interview_eval_report.md -Pattern "用户原文哨兵|LLM_API_KEY|BEGIN PROMPT|source_span" -SimpleMatch
```

期望:无匹配。

---

## 15. 分阶段执行提示词

下面的提示词给后续实现 agent 使用。每个阶段都应在开始前重新读取 `AGENTS.md` 和本 spec,并遵守“新增行为必须有 pytest 覆盖、测试不得污染真实 materials.json、不挂 pre-push、不主动 push”的项目约束。

### Prompt 0 — 基线校准

```text
你在 D:\简历帮 工作。请执行 R6-B Phase 0: 基线校准。

目标:
1. 阅读 AGENTS.md 与 .harness/docs/round6-b-interview-agent-intelligence-spec.md。
2. 确认当前本地基线是 R6-A Phase 1+2+3+4+5,LLM slot extraction 已落地,active baseline 为 739 tests collected。
3. 修正 scripts/evaluate_interview_agent.py 中仍写着“Phase 4 LLM 未上线”的注释、错误信息和报告标题口径,但不要改变脚本行为。
4. 保持 /api/interview/draft 的 DRAFT_READY bugfix 和回归测试不回退。

边界:
- 不新增 LLM 调用。
- 不修改 core.agent_workflow.py / core.agent_tools.py / core.tool_schema.py。
- 不修改 PROMPT_VERSIONS。
- 不写真实 backend/data/materials.json。

验证:
cd backend
D:\python3.11\python.exe -m pytest tests/test_interview_api.py::TestDraftEndpoint tests/test_interview_agent.py::TestLLMSlotExtraction tests/test_interview_agent.py::TestInterviewPromptRegistry tests/test_interview_eval.py -q
```

### Prompt 1 — slot_meta provenance

```text
你在 D:\简历帮 工作。请执行 R6-B Phase 1: slot_meta provenance。

目标:
1. 在 InterviewSession 中增加 interview_mode、mode_warning、slot_meta、question_plan、verification_summary 默认字段。
2. 为 rules extraction 和现有 llm extraction 的结果生成 slot_meta。
3. LLM source_span 只在当前函数内验证并转换为 sha256 hash + length + turn_index,不得存明文。
4. 对 list slot 最多保留 5 条 meta;confidence 必须是 0.0-1.0 的 number,bool 不接受。
5. 保持 extract_slots(..., llm_enabled=False) 旧行为兼容。

边界:
- 不新增 interview_llm.py。
- 不迁移现有 _call_llm_for_slot_extraction。
- trace/session/API response 不得包含 user_message 或 source_span 明文。

测试:
- 在 tests/test_interview_agent.py 增加覆盖:默认字段兼容、rules meta、llm source_span hash、invalid source_span 降级、slot_meta 隐私。

验证:
cd backend
D:\python3.11\python.exe -m pytest tests/test_interview_agent.py -q
```

### Prompt 2 — API mode 开关

```text
你在 D:\简历帮 工作。请执行 R6-B Phase 2: API mode 开关。

目标:
1. StartRequest 增加 enable_interview_llm: bool = False。
2. StartResponse 增加 interview_mode 与 mode_warning optional 字段。
3. create_session 或 API 层根据 enable_interview_llm + LLM_API_KEY/env 决定 session.interview_mode。
4. ReplyRequest 不重复传开关,reply 沿用 session.interview_mode。
5. ReplyResponse 增加 optional extraction_summary / question_plan,先可返回最小摘要。

边界:
- enable_interview_llm=False 必须完全保持 rules 路径。
- enable=True 但无 key 时 start 不失败,返回 rules + mode_warning。
- 不把 API key、prompt、source_span 明文放入响应。

测试:
- 修改 tests/test_interview_api.py 覆盖默认 rules、无 key fallback、有 key llm_assisted、reply 沿用 session mode、响应不含隐私原文。

验证:
cd backend
D:\python3.11\python.exe -m pytest tests/test_interview_api.py tests/test_interview_agent.py -q
```

### Prompt 3 — confidence-aware policy

```text
你在 D:\简历帮 工作。请执行 R6-B Phase 3: confidence-aware policy。

目标:
1. 新增 backend/core/interview_policy.py。
2. 实现 plan_next_question(session) deterministic policy。
3. 优先级:必要 slot 缺失 > confidence < 0.6 > gap suggested_slots 未覆盖 > 接近轮数上限时 result/metric > 连续 skip 强制 draft。
4. next_question() 内部使用 policy,但对旧前端的 message 输出结构保持兼容。
5. rephrase_question 不换 slot;switch_gap 后不混用旧 gap question_plan。

边界:
- policy 不调用网络,不调用 LLM。
- LLM 不决定 slot 顺序。
- 不修改 save_card 行为。

测试:
- 新增 tests/test_interview_policy.py 覆盖 missing required、low confidence、turn limit、skip forced draft、rephrase 不换 slot。
- tests/test_interview_agent.py 增加 next_question 集成断言。

验证:
cd backend
D:\python3.11\python.exe -m pytest tests/test_interview_policy.py tests/test_interview_agent.py -q
```

### Prompt 4 — draft verifier

```text
你在 D:\简历帮 工作。请执行 R6-B Phase 4: draft verifier。

目标:
1. 新增 backend/core/interview_verifier.py。
2. 实现 verify_draft_card(card, session)。
3. 检查 draft_bullets 中量化数字是否有 captured_slots/slot_meta 来源。
4. 检查每条 bullet 是否至少有 action/responsibility/result 类来源。
5. 低置信度 slot 生成 confidence_notes。
6. DraftResponse.draft_card 可带 verification/confidence_notes。
7. save_card 写入 _interview_meta.verification 摘要,不写原文。

边界:
- verifier 默认不调 LLM。
- unsupported_claims 不阻止保存,只生成 warning。
- 不把 draft_card 原文写入 trace/report/meta。

测试:
- 新增 tests/test_interview_verifier.py。
- 修改 tests/test_interview_api.py 覆盖 draft response optional verification 与 save-card meta 摘要。

验证:
cd backend
D:\python3.11\python.exe -m pytest tests/test_interview_verifier.py tests/test_interview_api.py tests/test_interview_agent.py -q
```

### Prompt 5 — eval compare

```text
你在 D:\简历帮 工作。请执行 R6-B Phase 5: eval compare。

目标:
1. 扩展 scripts/evaluate_interview_agent.py 支持 --extractor rules|llm|compare。
2. rules 保持当前默认行为。
3. llm/compare 在 offline 模式不得发网络,应标记 llm_disabled_fallback。
4. live mode 只允许用户手动运行,不挂 pre-push。
5. 报告增加 rules vs llm_assisted 对照表和 fallback_rate、low_confidence_slot_rate、p95_latency_ms。

边界:
- report/stdout 不含 user_message、prompt、raw response、source_span、API key。
- live mode 单测必须 monkeypatch,不真实发网络。
- 不修改 evaluate_agent_workflow.py / evaluate_prompt_versions.py。

测试:
- 修改 tests/test_interview_eval.py 覆盖 rules 默认、compare 双组、offline 不调 urlopen、report 隐私、metrics 新字段。

验证:
cd backend
D:\python3.11\python.exe -m pytest tests/test_interview_eval.py -q
D:\python3.11\python.exe scripts/evaluate_interview_agent.py --mode offline --extractor compare --output backend/logs/interview_eval_report.md
```

### Prompt 6 — frontend 最小呈现

```text
你在 D:\简历帮 工作。请执行 R6-B Phase 6: frontend 最小呈现。

目标:
1. frontend/src/api/index.ts 增加 enable_interview_llm、interview_mode、mode_warning、extraction_summary、question_plan、verification/confidence_notes 类型。
2. InterviewAgentPanel.vue 启动区域增加“智能抽取”toggle,默认关闭。
3. 面板 header 显示规则模式 / 智能抽取 / 已回退规则模式。
4. draft_card 区域显示 confidence_notes。
5. 保存前若 verification.unsupported_claims > 0 或 low_confidence_claims > 0,展示确认提示。

边界:
- 不显示 Agent Workflow / trace / schema / ToolResult。
- 不显示 prompt、raw response、source_span 明文。
- 移动端 drawer 不能被 toggle/warning 挤坏。

验证:
cd frontend
npx vue-tsc --noEmit
npm run build

浏览器 smoke:
- 桌面 1280x800:toggle 可见,不挤压预览。
- 移动 375x812:drawer 内 toggle/warning 不与输入区冲突。
- 无 key:开启智能抽取后显示已回退规则模式。
```

---

## 16. R6-B 收尾记录 (Phase 7 — Prompt 7 落地, 2026-06-30)

> 本节为 R6-B 收尾记录,由 orchestrator 在所有 phase 落地后追加。涵盖完成阶段、关键指标、测试结果、遗留风险、下一轮建议。

### 16.1 完成阶段

| Phase | 范围 | Commit | pytest 增量 | 累计 |
|---|---|---|---|---|
| Phase 0 | 基线校准 (`scripts/evaluate_interview_agent.py` 口径修正) | 与 R6-A Phase 4 doc 同步合并 (`119575c`) | +0 | 739 |
| Phase 1 | slot_meta provenance (默认字段 + hash + confidence) | 在 Phase 2 同一 commit (`f665c35`) | +29 | 768 |
| Phase 2 | API mode 开关 (`enable_interview_llm` / `interview_mode` / `extraction_summary` / `question_plan`) | `f665c35` | +11 | 768 |
| Phase 3 | confidence-aware policy (`backend/core/interview_policy.py` deterministic 8 步链) | `d1622bb` | +41 | 809 |
| Phase 4 | draft verifier (`backend/core/interview_verifier.py` 双源命中 + confidence_notes) | `51f6450` | +31 | 840 |
| Phase 4 doc 同步 | baseline 840 锁 | `7b756fc` | +0 | 840 |
| Phase 5 | eval compare (`--extractor {rules, llm, compare}` + fallback_category + 对照表) | `b1635fc` | +23 | **863** |
| Phase 6 | frontend 最小呈现 (toggle + 三态标签 + 置信度 + 事实核验) | `be250e3` | +0 (前端) | 863 |
| Phase 7 | 收尾 (README / ROADMAP / AGENTS / spec 四方同步) | (待用户授权 push) | +0 | 863 |

> **注**:Phase 1 +29 是 `tests/test_interview_agent.py::TestPhase1SlotMeta*` 系列,Phase 2 收尾时一起算入;Phase 0 文档口径修正确实 +0 新 pytest(纯脚本文案)。

### 16.2 关键指标 (offline compare 实测, 2026-06-30)

**跑测命令**:`D:\python3.11\python.exe scripts/evaluate_interview_agent.py --mode offline --extractor compare --output backend/logs/interview_eval_report.md`

| 指标 | 全局 | rules | llm 意图 (offline → 强制规则 fallback) | Delta |
|---|---|---|---|---|
| 样本数 | 20 | 10 | 10 | — |
| `schema_pass_rate` | 0.30 | 0.30 | 0.30 | +0.00 |
| `avg_completeness` | 0.53 | 0.53 | 0.53 | +0.00 |
| `fallback_rate` | 0.50 | 0.00 | 1.00 | +1.00 (offline 预期) |
| `fabrication_violations` | 0 | 0 | 0 | 0 (✅ 目标达成) |
| `avg_latency_ms` | 1 | 1 | 1 | 0 |
| `p95_latency_ms` | 2 | 2 | 2 | 0 |
| `low_confidence_slot_rate` | 0.23 | 0.23 | 0.23 | 0 |

**按 source 分组**:

| source | total | schema_pass_rate | avg_completeness | fabric_viol | low_conf_rate |
|---|---|---|---|---|---|
| `plan_baseline` | 6 | 0.33 | 0.56 | 0 | 0.22 |
| `simulated_user_v1` | 14 | 0.29 | 0.52 | 0 | 0.24 |

**fallback_category 分布**:

| 类别 | 数量 | 占比 |
|---|---|---|
| `none` | 10 | 0.50 |
| `llm_disabled_fallback` | 10 | 0.50 |
| `tool_error_fallback` | 0 | 0.00 |
| `schema_retry_fallback` | 0 | 0.00 |
| `workflow_abort_fallback` | 0 | 0.00 |

> offline compare 双组 delta = 0,因为 llm 意图路径在 offline 模式强制走规则版 + 标 `llm_disabled_fallback`。**live mode + 已配置 LLM 凭据**才会真发网络,那时 delta 才反映 LLM 抽取质量(spec §8 product gate)。

### 16.3 测试结果

- **后端全量**:`D:\python3.11\python.exe -m pytest tests/ -q` → **863 passed in 82.86s**
- **前端类型检查**:`cd frontend && npx vue-tsc --noEmit` → **0 error**
- **前端构建**:`cd frontend && npm run build` → 成功 (`dist/index.html 0.48 kB / assets/index-*.css 369.43 kB / assets/index-*.js 1104.35 kB`)
- **offline compare**:`scripts/evaluate_interview_agent.py --mode offline --extractor compare` → 报告生成 `backend/logs/interview_eval_report.md` (132 行, 8 章节)
- **隐私自检**:`Select-String -LiteralPath backend\logs\interview_eval_report.md -Pattern "用户原文哨兵|LLM_API_KEY|BEGIN PROMPT|source_span" -SimpleMatch` → **无匹配**(报告不含 user_message / prompt / raw response / source_span / API key / env var 名 / Bearer / key 前缀)
- **git status**:`?? .planning/面试题解/` 唯一未跟踪项(用户自己的面试题解草稿,跟 R6-B 无关,未入库)

### 16.4 收尾验证清单 (Phase 7 完成标准)

- [x] AGENTS.md R6-B Phase 0-6 锁点全部到位 (7 段,R6-B 起点 baseline 739 → 终点 863)
- [x] README.md "当前状态" + "核心能力" + scripts 列表 同步 R6-B 落地 (基线 863 / R6-B 6 phase 全完成 / interview agent 默认 rules 路径)
- [x] ROADMAP.md 顶部快照 + "最近 7 个 commit" + 新增 R6-B section 同步 (活跃基线 863)
- [x] round6-b spec §16 收尾记录 (本节) append 完毕
- [x] 后端全量 863 passed + 0 skipped
- [x] 前端 vue-tsc 0 error + npm run build 成功
- [x] offline compare 报告生成 + 隐私自检通过
- [x] git status 无真实 materials.json 污染 + logs/dist/output 等运行产物正确 gitignore
- [x] 无真实个人素材 / LLM 凭据入库

### 16.5 遗留风险

1. **LLM 抽取真实收益待验证** — offline compare 双组 delta = 0(预期内),需用户在 chat panel 跑 10+ 轮真实对话 + 配置 LLM key 后跑 live compare,才能判断 `schema_pass_rate` / `avg_completeness` 相对 rules baseline 是否真正提升(spec §12 产品指标:`schema_pass_rate ≥ 0.60` / `avg_completeness ≥ 0.70`)
2. **`schema_pass_rate = 0.30` 全局仍偏低** — 跟 R6-A Phase 5 baseline 持平,LLM 路径未启动;待 live eval 验证后,若仍 < 0.60,需排查 `extract_slots` rules 路径是否漏关键 slot 或 prompt 是否需要重写
3. **`interview_agent.py` 文件继续膨胀** — 当前含 orchestrator + slot_meta + policy 接入 + verifier 接入 + LLM call + save-card,文件 ~800 行;若 R6-C 拆 `core/interview_llm.py`,需做"机械拆分,行为不变"重构 round(spec §3 方案 B 备选)
4. **R6-B Phase 1 的 29 个 slot_meta 测试散落** — `tests/test_interview_agent.py::TestPhase1SlotMeta*` 跟 R6-A Phase 1 旧 case 同文件,粒度尚可但可读性边际下降;若未来 phase 加新功能,建议单独建 `tests/test_interview_slot_meta.py`
5. **offline compare 报告** 含 `samples / descriptions` 字段未来可能扩展(如 per-gap metrics),需在 R6-C 时同步更新 `tests/test_interview_eval.py` 锁

### 16.6 下一轮建议 (P1 候选)

| 选项 | 描述 | 触发条件 | 工作量估算 |
|---|---|---|---|
| **(a) R6-C live eval 收益验证** | 用户跑 10+ 轮真实对话 + 配置 LLM key 后,跑 `scripts/evaluate_interview_agent.py --mode live --extractor compare`,验证 schema_pass_rate 是否 ≥ 0.60 / avg_completeness 是否 ≥ 0.70 | R6-B spec §8 product gate | 0 代码 + 1 报告 + 文档同步(~1 小时) |
| **(b) R6-C 拆 `core/interview_llm.py`** | 把 `interview_agent.py` 里的 LLM call / slot extraction / fallback 抽到独立模块,行为不变,纯机械拆分 | `interview_agent.py` > 1000 行 或 用户明确要求 | ~300 行(模块 + 测试),机械拆分 1-2 小时 |
| **(c) R5-F prompt rollout** | 若 R5-E live A/B 报告显示 v3-priority / v4-counterexample / v5-minimal 中有稳定 winner,切默认 prompt(保留 v2-baseline 显式回退路径) | R5-E live 报告有明确 winner 数据 | ~50 行(改 baseline 常量 + 测试),10 分钟 |

> **推荐顺序**:先做 (a) 验证 R6-B 是否真正提升产品价值,再决定走 (b) 重构还是 (c) 切 prompt。

### 16.7 R6-B 不做 (再次重申)

- 不做自由聊天助手 / 模拟面试训练 / 自动投递
- 不做账号 / 云端 / 多用户
- 不引入向量数据库 / Redis / 后台队列
- 不把完整对话持久化
- 不让 LLM 自动保存素材
- 不重构已落地的 LLM slot extraction 到新模块(R6-C 候选,不在本 round)
- 不改默认 resume rewrite prompt
- 不 rollout R5-E prompt winner
- 不把 live eval report 自动入库(spec §13 非目标清单)

### 16.8 收尾 commit (待用户授权后 push)

- (本 round) `docs(round6-b): sync active baseline 863 after phase 5`
  - 文件: `README.md` / `.harness/docs/ROADMAP.md` / `.harness/docs/round6-b-interview-agent-intelligence-spec.md`
  - 范围: 仅文档同步,不改业务逻辑 / 后端代码 / 前端代码 / 测试
  - 验证: 后端 863 passed + 前端 build 成功 + offline compare 通过 + 隐私自检通过 + git status 无污染
