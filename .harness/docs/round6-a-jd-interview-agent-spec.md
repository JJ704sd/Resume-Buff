# Round 6-A: JD-Driven Interview Agent Spec

> 适用项目: 简历帮 / Resume-Buff  
> GitHub: `JJ704sd/Resume-Buff`  
> 日期: 2026-06-29  
> 状态: Draft spec, 待评审后拆 implementation plan  
> 目标: 把现有“JD 评分 + Agent 诊断 + LLM 改写”升级为一个用户能自然使用的 **JD 驱动简历面试官**。它从目标 JD 出发, 选择最值得补的一个经历缺口, 通过聊天追问收集事实, 经用户确认后写回素材库, 并刷新简历预览。

---

## Baseline

本 spec 基于 2026-06-29 本地 `main` 的 R5-E closeout 状态撰写:

- 最新本地提交: `c110a51 docs(round5-e): close prompt ab harness round`。
- README / AGENTS / ROADMAP 已同步 R5-E 活跃基线: **683 passed + 0 skipped**。
- R5-E 已完成 prompt versioning + A/B eval harness + 可选 LLM-as-Judge:
  - `backend/core/llm_rewriter.py` 已有 `PROMPT_VERSION_BASELINE = "v2-baseline"` 与 `PROMPT_VERSIONS`。
  - `prompt_version` 已透传 API / generator / workflow / rewriter。
  - `scripts/evaluate_prompt_versions.py` 已可跑 offline/auto/live prompt A/B。
  - 默认 prompt **仍为 `v2-baseline`**, 不在 R6-A 默认切换 winner。
- 当前未提交变更只包含本 spec 与本地 `.planning/面试讲解/` 草稿目录; R5-E 代码本身已经提交完成。
- GitHub 远端在本次核对时因本机 TLS 握手失败未能 `git ls-remote`, 因此本 spec 以本地 `main`、README、AGENTS、ROADMAP 与提交历史为准。

R6-A 不接管 R5-E 的 prompt rollout 决策。若后续要切换默认 prompt, 应单独走 R5-E closeout / R5-F prompt rollout; 本轮只把现有 Agent 能力产品化为“简历面试官”主路径。

---

## 0. 结论

第一版不要做自由聊天 Agent。推荐做 **JD 驱动的单缺口面试循环**:

```text
用户粘贴 JD
→ 系统分析 JD 与素材库缺口
→ 选择一个最值得补的缺口
→ 右侧“简历面试官”开始一问一答
→ 用户回答
→ 系统抽取结构化事实
→ 生成待确认素材卡
→ 用户确认 / 编辑
→ 写回 materials.json
→ 自动刷新 JD 评分与简历预览
```

这不是为了显得更像 Agent, 而是为了让用户真正完成一轮“把模糊经历变成可信素材”的任务。它满足 Agent 的最低闭环:

- 感知: 读取 JD、当前素材库、已有 evidence、bullet 评估。
- 决策: 选择最值得追问的一个缺口, 决定下一问。
- 行动: 发起追问、抽取事实、生成素材卡、写入素材库。
- 反馈: 重新跑 match/preview, 告诉用户本轮补充带来的变化。

---

## 1. 第一性原理

### 1.1 用户真正缺的不是“生成简历”

目标用户通常不是没有经历, 而是不知道哪些细节值得写:

- 只会写“负责活动策划 / 参与项目开发 / 完成数据整理”。
- 不知道 HR/JD 关心的是动作、方法、难点、结果和量化指标。
- 不知道怎么把课程、社团、比赛、项目经历映射到岗位能力。
- 害怕 AI 乱编, 但自己又不知道怎么补充事实。

因此产品核心不应该是“帮你生成一段很漂亮的经历”, 而是:

> 帮用户把真实经历问清楚, 再整理成可确认、可追溯、可复用的素材。

### 1.2 简历优化的信任边界

简历可以优化表达, 但不能凭空编造。系统必须把内容分成三层:

| 层级 | 含义 | 是否可写入素材库 |
|---|---|---|
| 用户已提供事实 | 来自用户回答或原素材库 | 可以, 但仍需用户确认 |
| 系统抽取/归纳 | 从用户事实里压缩整理 | 可以, 需展示给用户确认 |
| 系统建议补充 | AI 认为还缺的信息或可能的追问方向 | 不可直接写入 |

任何素材写入都必须经过用户确认。LLM 不能直接把猜测写进 `materials.json`。

### 1.3 用户努力是最稀缺资源

聊天体验的关键不是“问得多”, 而是“让用户愿意继续回答”。第一版必须遵循:

- 每次只问一个问题。
- 每轮只补一个缺口。
- 允许“不知道 / 跳过 / 换个问法”。
- 问题要有回答脚手架, 避免空白输入焦虑。
- 用户随时能收束成素材卡。
- 每轮结束要有即时正反馈。

### 1.4 Agent 能力提升应服务产品闭环

当前项目已经具备 R5-E 后的较扎实基础:

- `backend/core/agent_workflow.py`: 确定性任务图、`agent_summary`、`evidence_summary`、外部简历视角、bullet 评估、JSONL trace。
- `backend/core/agent_tools.py`: 工具注册表、schema 校验、权限 context、PII 风险分级。
- `backend/core/llm_rewriter.py`: LLM 改写、schema retry、Function Calling、Agent Loop、session、evidence 约束、prompt versioning, 且默认稳定在 `v2-baseline`。
- `scripts/evaluate_agent_workflow.py`: R5-D 真实 LLM eval 闭环、latency、fallback taxonomy、rewrite impact。
- `scripts/evaluate_prompt_versions.py`: R5-E prompt A/B eval harness, 固定 FC/AW 变量后只比较 `prompt_version`。
- `frontend/src/App.vue`: 已有 Agent Workflow 开关和高级诊断面板。
- `backend/api/materials.py`: 已有 `PUT /api/materials` 整体替换素材库能力。

下一步的价值不是再堆工具, 而是让这些能力进入用户主流程。

---

## 2. 产品定位

### 2.1 前台名称

前台不使用 “Agent Workflow” 作为主入口。建议命名:

- 主名称: **简历面试官**
- 备用: **经历挖掘助手**
- 技术诊断入口仍可叫: **Agent Workflow 诊断**

前台一句话:

> 我会根据目标 JD, 先帮你补最影响匹配度的一块经历。

### 2.2 第一版入口

入口选择: **从目标 JD 开始**。

原因:

- 复用现有 JD parser、match_score、evidence、bullet_evaluations。
- 用户目标明确, 不需要从“你有什么经历”这种大空题开始。
- 每个问题都能解释为“为什么问这个”, 降低用户抵触。
- 写回素材后可以立即看到 JD 匹配与预览变化。

### 2.3 UI 形态

桌面端:

- 右侧常驻聊天栏。
- 左侧保留现有岗位/JD/预览主流程。
- 聊天栏不挤占预览核心信息; 宽度建议 360-420px。

移动端:

- 底部按钮打开全屏抽屉。
- 不做窄右栏。
- 保留同一套状态机和 API。

### 2.4 与现有高级诊断面板的关系

新“简历面试官”是普通用户主体验。现有 Agent Workflow 诊断面板是高级解释/调试入口。

普通用户默认看到:

- 当前在补哪个 JD 缺口。
- 下一问。
- 已捕捉事实进度。
- 待确认素材卡。
- 写入后的匹配变化。

高级用户点击“查看依据”后才看到:

- evidence 数量与来源分布。
- request_id。
- tools_used。
- fallback 状态。
- bullet_evaluations 摘要。

---

## 3. 非目标

第一版明确不做:

- 不做全自由聊天助手。
- 不做自动投递、招聘网站抓取、HR 跟踪。
- 不做模拟面试/八股训练。
- 不做多用户、账号系统、云端同步。
- 不自动写入素材库。
- 不把完整 JD、完整简历、完整用户回答写入 JSONL trace 或 eval report。
- 不把 AI 猜测当作用户事实。
- 不要求引入向量数据库、Redis、后台队列。
- 不默认打开 LLM live eval 或 prompt A/B。

---

## 4. 核心用户流程

### 4.1 空状态

触发条件:

- 用户未粘贴 JD, 或 JD 为空。

文案建议:

```text
粘贴目标 JD 后, 我可以像面试官一样帮你把最关键的一段经历问清楚。
```

按钮/提示:

- `粘贴 JD 后开始`
- 若已有 JD: `让面试官帮我补经历`

### 4.2 诊断状态

触发条件:

- 用户粘贴 JD 并点击启动。

系统动作:

1. 调用现有 JD match 能力。
2. 读取材料库 summary。
3. 获取 evidence_summary / bullet_evaluations。
4. 计算候选缺口。
5. 选择一个优先缺口。

用户可见文案:

```text
我看完这个 JD 了。当前最值得补的是“流程优化/量化结果”证据。
JD 反复提到流程、协同、指标, 但你的素材库里这块证据还不够。
我先问一个问题。
```

### 4.3 追问状态

每次只问一个问题。问题必须绑定一个槽位:

| 槽位 | 目的 | 示例问题 |
|---|---|---|
| background | 场景 | 这件事发生在课程项目、比赛、社团还是实习里? |
| responsibility | 职责 | 你当时主要负责方案设计、执行推进、数据分析, 还是协调沟通? |
| action | 动作 | 你具体做了哪一步? 可以先用一句话说。 |
| method | 方法/工具 | 你用了什么方法、工具或流程来解决? |
| difficulty | 难点 | 当时最麻烦的问题是什么? |
| result | 结果 | 最后带来了什么变化或产出? |
| metric | 量化 | 有没有人数、时间、准确率、效率、成本、数量之类的数据? 没有也可以说没有。 |

每个问题提供快捷回复:

- `我负责执行`
- `我负责分析`
- `我负责协调`
- `没有数据`
- `想不起来`
- `换个问法`
- `跳过这个问题`

### 4.4 追问收束

默认围绕一个缺口最多追问 3 轮, 但不机械卡死。收束条件:

- 已有 `background + action + result`。
- 或已有 `responsibility + action + metric`。
- 或用户点击 `整理成素材`。
- 或连续两次回答“不知道/跳过”。

收束提示:

```text
信息已经够整理成一张素材卡了。你可以现在生成, 也可以继续补一个量化结果。
```

按钮:

- `整理成素材`
- `继续追问`
- `换一个缺口`

### 4.5 确认状态

生成待确认素材卡。字段建议:

```json
{
  "title": "经历标题",
  "target_roles": ["product", "test_qa"],
  "source_gap": "流程优化/量化结果",
  "background": "",
  "responsibility": "",
  "actions": [],
  "methods": [],
  "difficulty": "",
  "result": "",
  "metrics": [],
  "skills": [],
  "draft_bullets": [],
  "confidence_notes": []
}
```

素材卡 UI 必须可编辑。按钮:

- `确认写入素材库`
- `继续追问`
- `先保存草稿`
- `丢弃`

写入前提示:

```text
这些内容会写入你的本地素材库。请确认没有夸大或不真实的信息。
```

### 4.6 写入成功

写入后自动刷新:

- JD match score。
- preview_resume。
- 简历面试官当前状态。

反馈文案:

```text
已写入素材库。这个 JD 的“流程优化/量化结果”缺口现在有了新证据。
```

若能计算前后变化:

```text
匹配度 62 → 71。新增可用 bullet 2 条。
```

若分数未变化:

```text
素材已保存。评分暂时没变, 但这段经历会在后续生成时作为可用证据。
```

---

## 5. 缺口选择策略

第一版缺口选择应确定性为主, LLM 可作为表达层, 不作为无约束规划器。

### 5.1 候选缺口来源

候选缺口来自:

- `match_score(...).missing_keywords`
- `tier_info.required / preferred / bonus`
- `external_resume_perspective.need_keywords`
- `external_resume_perspective.materials_can_cover`
- `bullet_evaluations[].missing_keywords`
- `evidence_summary` 覆盖不足的关键词

### 5.2 排序维度

不要只按 missing keyword 排序。综合:

| 维度 | 含义 | 第一版建议 |
|---|---|---|
| JD 重要性 | required > preferred > bonus | required 加权最高 |
| 可补性 | 素材库已有接近 evidence | 可补性越高越优先 |
| 追问适配度 | 是否适合通过用户回忆补充 | 经验/结果/流程类优先 |
| 预览影响 | 补完是否可能影响 bullets/score | 可影响 preview 优先 |
| 用户负担 | 是否需要用户查很多资料 | 低负担优先 |

### 5.3 建议的 scoring

```python
priority =
  jd_tier_weight
  + coverability_weight
  + interviewability_weight
  + preview_impact_weight
  - user_effort_penalty
```

第一版可以先用规则表, 不必引入 LLM 排序:

- required: +4
- preferred: +2
- bonus: +1
- materials_can_cover 命中: +3
- evidence 中有相邻关键词: +2
- bullet_evaluations 中反复 missing: +2
- 属于可追问槽位: +2
- 需要硬证书/学历/真实工作年限: -5

### 5.4 不该优先追问的缺口

以下缺口不适合通过聊天补:

- 学历要求。
- 年限要求。
- 明确证书。
- 用户明显不具备的硬技能。
- 需要真实公司/项目经历但素材库完全无相邻证据。

这些应该提示为“建议补充学习/经历”, 而不是诱导用户编造。

---

## 6. 面试问题生成策略

### 6.1 问题不是闲聊

每个问题必须有结构化目的:

```json
{
  "question_id": "q_001",
  "gap_id": "process_metric",
  "slot": "metric",
  "question": "有没有能量化的结果, 比如节省时间、减少错误、覆盖人数或产出数量?",
  "quick_replies": ["没有数据", "大概有", "我想不起来", "换个问法"]
}
```

### 6.2 问题模板优先

第一版建议先做模板 + 少量 LLM润色, 不做完全 LLM 自由生成。

模板示例:

- 背景:
  ```text
  这段经历发生在哪个场景里? 课程项目、比赛、社团、实习, 还是个人项目?
  ```
- 职责:
  ```text
  你当时主要负责哪一块? 可以从“分析、设计、执行、协调、测试”里选一个最接近的。
  ```
- 动作:
  ```text
  你具体做了什么动作? 先不用写得正式, 像讲给面试官听一样说就行。
  ```
- 结果:
  ```text
  最后有什么结果? 产出了文档、系统、报告、活动, 还是让流程变快/更稳定?
  ```
- 量化:
  ```text
  有没有数字可以支持? 比如人数、次数、时长、准确率、效率、覆盖范围。没有也可以直接说没有。
  ```

### 6.3 避免压迫感的文案

不推荐:

```text
请详细描述你的项目背景、任务、行动和结果。
```

推荐:

```text
不用写正式, 先说一句: 你当时具体负责了哪一步?
```

不推荐:

```text
请提供量化指标。
```

推荐:

```text
如果想得起来, 有没有一个数字能说明效果? 没有也没关系。
```

---

## 7. 数据模型

### 7.1 Conversation session

建议新增轻量后端模块:

```text
backend/core/interview_agent.py
backend/api/interview.py
backend/tests/test_interview_agent.py
```

第一版 session 可继续进程内保存, 与 `core/session.py` 风格一致, 不做持久化。每条消息只在内存中保留, 不写 trace 原文。

```python
InterviewSession = {
    "session_id": "ia_xxx",
    "target_role": "product",
    "jd_digest": {...},
    "selected_gap": {...},
    "state": "diagnosing|asking|draft_ready|saved|aborted",
    "turn_count": 0,
    "captured_slots": {
        "background": None,
        "responsibility": None,
        "actions": [],
        "methods": [],
        "difficulty": None,
        "result": None,
        "metrics": []
    },
    "draft_card": None
}
```

隐私要求:

- JSONL trace 只写 `session_id/request_id/state/slot/input_size/output_size/status`。
- 不写用户回答原文。
- 不写完整 JD。
- 不写素材卡完整正文到 trace。

### 7.2 Gap model

```python
GapCandidate = {
    "gap_id": "process_metric",
    "label": "流程优化/量化结果",
    "keywords": ["流程", "效率", "指标"],
    "source": ["match_score", "bullet_evaluations"],
    "tier": "required",
    "priority": 8.5,
    "reason": "JD 多次强调流程和量化结果, 当前素材库命中不足",
    "suggested_slots": ["responsibility", "action", "result", "metric"]
}
```

前端展示 `label` 和 `reason`, 不展示完整 JD 原文。

### 7.3 Draft card model

```python
DraftMaterialCard = {
    "card_id": "card_xxx",
    "source": "interview_agent",
    "target_role": "product",
    "source_gap_id": "process_metric",
    "title": "经历标题",
    "summary": "一句话概述",
    "background": "",
    "responsibility": "",
    "actions": [],
    "methods": [],
    "difficulty": "",
    "result": "",
    "metrics": [],
    "skills": [],
    "draft_bullets": [],
    "evidence_level": "user_confirmed_required",
    "warnings": []
}
```

`evidence_level` 第一版固定为 `user_confirmed_required`, 表示必须确认后才能写库。

---

## 8. API 草案

### 8.1 Start interview

```http
POST /api/interview/start
```

Request:

```json
{
  "target_role": "product",
  "jd_text": "...",
  "external_resume_text": null,
  "enable_agent_workflow": true
}
```

Response:

```json
{
  "session_id": "ia_12345678",
  "state": "asking",
  "selected_gap": {
    "gap_id": "process_metric",
    "label": "流程优化/量化结果",
    "reason": "JD 多次强调流程、协同和指标, 当前素材库证据不足"
  },
  "message": {
    "role": "assistant",
    "type": "question",
    "slot": "responsibility",
    "text": "这个 JD 很看重流程和量化结果。你有没有一段经历, 是你推动某个流程变清楚、变快或更稳定的?",
    "quick_replies": ["有, 是项目里", "有, 是社团里", "不确定", "换个缺口"]
  },
  "progress": {
    "captured": {
      "background": false,
      "responsibility": false,
      "action": false,
      "result": false,
      "metric": false
    },
    "turn_count": 0,
    "can_draft": false
  }
}
```

### 8.2 Reply

```http
POST /api/interview/reply
```

Request:

```json
{
  "session_id": "ia_12345678",
  "message": "我在课程项目里负责整理测试流程, 后来把测试用例模板统一了。",
  "action": "answer"
}
```

`action` allowed:

- `answer`
- `skip_question`
- `rephrase_question`
- `switch_gap`
- `draft_now`

Response:

```json
{
  "state": "asking",
  "message": {
    "role": "assistant",
    "type": "question",
    "slot": "result",
    "text": "这个动作最后带来了什么变化? 比如减少返工、让协作更顺、覆盖更多测试场景。",
    "quick_replies": ["减少返工", "协作更顺", "覆盖更多场景", "没有明显结果"]
  },
  "captured_delta": {
    "responsibility": "整理测试流程",
    "actions": ["统一测试用例模板"]
  },
  "progress": {
    "turn_count": 1,
    "can_draft": false
  }
}
```

### 8.3 Draft card

```http
POST /api/interview/draft
```

Request:

```json
{
  "session_id": "ia_12345678"
}
```

Response:

```json
{
  "state": "draft_ready",
  "draft_card": {
    "title": "课程项目测试流程优化",
    "target_role": "test_qa",
    "source_gap_id": "process_metric",
    "background": "课程项目中需要多人协作完成测试。",
    "responsibility": "负责整理测试流程和测试用例模板。",
    "actions": ["统一测试用例模板", "梳理测试步骤"],
    "methods": [],
    "result": "提升协作清晰度, 减少重复沟通。",
    "metrics": [],
    "draft_bullets": [
      "梳理课程项目测试流程, 统一测试用例模板, 提升多人协作与用例复用效率"
    ],
    "warnings": ["当前缺少可量化指标, 写入前建议确认是否有次数、人数或时间数据。"]
  }
}
```

### 8.4 Save card

```http
POST /api/interview/save-card
```

Request:

```json
{
  "session_id": "ia_12345678",
  "edited_card": {
    "title": "...",
    "background": "...",
    "actions": [],
    "result": "...",
    "draft_bullets": []
  },
  "save_mode": "append_project"
}
```

`save_mode` 第一版建议只支持:

- `append_project`: 追加为一个新 project。
- `append_to_existing_project`: 可选 P2, 用户选择已有 project 后追加 highlights。

Response:

```json
{
  "ok": true,
  "material_ref": {
    "type": "project",
    "id": "interview_project_20260629_001"
  },
  "refresh": {
    "should_refresh_preview": true,
    "should_refresh_match": true
  }
}
```

---

## 9. 写入 materials.json 策略

### 9.1 第一版建议

为了尽快落地, 第一版先支持 **追加新项目**。不要一开始做复杂 merge。

生成 project:

```json
{
  "id": "interview_project_20260629_001",
  "name": "课程项目测试流程优化",
  "period": "",
  "role_tags": ["test_qa", "general"],
  "summary": "课程项目中负责梳理测试流程和统一测试用例模板。",
  "highlights": [
    "梳理课程项目测试流程, 统一测试用例模板, 提升多人协作与用例复用效率"
  ],
  "source": "interview_agent",
  "source_gap": "process_metric",
  "created_at": "2026-06-29"
}
```

如果现有 schema 不允许 `source/source_gap/created_at`, 第一版可以放入 `_meta` 或只保留标准字段, 但 spec 建议增加可选字段, 便于后续审计。

### 9.2 写库安全

写入前必须:

- 校验 required fields。
- 校验 `draft_bullets` 非空。
- 限制单条 bullet 长度。
- 去除空字符串。
- 生成唯一 project id。
- 保留原 `materials.json` 结构。
- 不写入 session 原始对话。

### 9.3 回滚与草稿

第一版至少支持:

- `先保存草稿`: 只存前端状态或后端内存 session, 不写 `materials.json`。
- 写库失败: 保留 draft_card, 允许重试。

P2 可做:

- `backend/data/materials.backup.<timestamp>.json` 本地备份。
- 素材卡撤销写入。

---

## 10. 前端体验规格

### 10.1 右侧聊天栏结构

建议组件:

```text
frontend/src/components/InterviewAgentPanel.vue
frontend/src/components/InterviewDraftCard.vue
frontend/src/components/InterviewProgressPills.vue
```

如果第一版想更快, 可以先集成在 `App.vue`, 但建议组件化, 避免 `App.vue` 继续膨胀。

### 10.2 信息架构

聊天栏包含:

1. Header: `简历面试官`
2. 当前缺口: 一行 tag + reason
3. 聊天消息区
4. 已捕捉事实进度
5. 输入框 + 快捷回复
6. 当前可操作按钮
7. 素材卡确认区

### 10.3 关键文案

启动按钮:

```text
让面试官帮我补经历
```

诊断中:

```text
正在找最值得补的一块经历证据...
```

追问开场:

```text
我先只问一个问题。你可以随便说, 不用写成简历语言。
```

用户不知道:

```text
没关系, 我换个更好答的问法。
```

生成素材卡:

```text
我把刚才的信息整理成素材卡了。请确认哪些是真实准确的。
```

保存成功:

```text
已写入素材库, 预览已刷新。
```

### 10.4 禁止文案

避免:

- `Agent`
- `workflow`
- `trace`
- `schema`
- `ToolResult`
- `RAG`
- `Function Calling`

这些只出现在“查看依据/高级诊断”里。

### 10.5 状态可见性

必须让用户知道:

- 当前正在补哪个能力点。
- 已问了几轮。
- 已捕捉哪些事实。
- 是否可以生成素材卡。
- 是否已经写入素材库。

### 10.6 移动端

移动端改为:

- 右下固定按钮: `简历面试官`
- 点击打开全屏抽屉。
- 抽屉内同样显示当前缺口、聊天、素材卡。
- 素材卡编辑区域不要和键盘冲突。

---

## 11. 后端实现分层

### 11.1 新模块职责

`backend/core/interview_agent.py`

- 选择缺口。
- 管理 session state。
- 生成下一问。
- 抽取用户回答中的结构化槽位。
- 判断是否可生成素材卡。
- 生成 draft_card。
- 将 confirmed card 转换为 materials project patch。

`backend/api/interview.py`

- 暴露 start/reply/draft/save-card API。
- 做请求长度限制。
- 不写原文日志。
- 调用 `materials` 读写能力。

`backend/core/interview_prompts.py` 或同文件常量

- 问题模板。
- 槽位定义。
- draft card schema 提示。

### 11.2 LLM 使用边界

第一版 LLM 用于:

- 从用户回答中抽取结构化槽位。
- 将槽位整理成 draft_card。
- 可选地润色问题语气。

第一版 LLM 不用于:

- 自由选择任意工具。
- 自动写库。
- 生成用户未提供的事实。
- 保存完整对话。

无 key fallback:

- 使用规则模板追问。
- 简单关键词抽取槽位。
- draft_card 可降级为“用户回答摘要 + 待用户手动编辑”。

### 11.3 与现有 Agent workflow 的关系

`interview_agent` 不替代 `agent_workflow`。它消费现有 workflow/score 的摘要结果:

- start 时可调用 `preview_resume(enable_agent_workflow=True)` 获取 `agent_summary/evidence_summary/bullet_evaluations`。
- 或直接调用底层 `match_score/retrieve_evidence/_evaluate_top_bullets`。

建议第一版为减少耦合:

- 缺口选择直接调用 `match_score` 与已有 helper。
- 不强依赖完整 `run_agent_workflow` 输出。
- 保存后再调用现有 preview/match 刷新前端。

---

## 12. 隐私与安全

### 12.1 PII 边界

不能写入:

- `backend/logs/agent_trace.jsonl`
- `backend/logs/generation.log`
- eval report
- replay markdown

的内容:

- 用户完整回答。
- 完整 JD。
- 完整素材卡。
- 真实姓名/电话/邮箱。

可以写:

- `session_id`
- `gap_id`
- `slot`
- `status`
- `input_size`
- `output_size`
- `latency_ms`
- `error_type`

### 12.2 API 长度限制

建议:

- `jd_text`: 沿用 50,000 chars。
- `message`: 2,000 chars。
- `session_id`: 64 chars。
- `draft_card` 字段总量: 20,000 chars。

### 12.3 权限边界

`PUT /api/materials` 当前无鉴权, 本项目仍是本地单用户工具。新增 `/api/interview/save-card` 同样只适合本地使用, README/AGENTS 需继续强调不要公网暴露。

### 12.4 防编造策略

保存前必须提示:

```text
请确认这些内容都来自你的真实经历。AI 建议不会自动写入。
```

draft_card 中 `warnings` 要显示:

- 缺少量化指标。
- 存在模糊表达。
- 某项是系统建议, 尚未得到用户确认。

---

## 13. 测试策略

### 13.1 后端单元测试

新增 `backend/tests/test_interview_agent.py`:

- `test_select_gap_prioritizes_required_and_coverable`
- `test_select_gap_ignores_uninterviewable_degree_gap`
- `test_start_session_returns_one_question`
- `test_reply_extracts_slot_without_raw_trace`
- `test_can_draft_after_background_action_result`
- `test_draft_card_contains_no_unconfirmed_claim`
- `test_save_card_requires_user_confirmation`
- `test_save_card_appends_project_with_unique_id`
- `test_no_llm_fallback_uses_template_questions`
- `test_interview_trace_logs_sizes_only`

### 13.2 API 测试

新增 `backend/tests/test_interview_api.py`:

- start/reply/draft/save-card happy path。
- empty JD returns 400。
- overlong message returns 422。
- unknown session returns 404。
- save-card invalid draft returns 400。
- save-card does not log raw user answer。

### 13.3 前端类型/构建

新增 API 类型:

- `InterviewStartRequest`
- `InterviewStartResponse`
- `InterviewReplyRequest`
- `InterviewReplyResponse`
- `InterviewDraftCard`
- `InterviewSaveResponse`

验证:

```powershell
Set-Location -LiteralPath D:\简历帮\frontend
npx vue-tsc --noEmit
npm run build
```

### 13.4 UX 验收用例

人工验收至少覆盖:

1. 粘贴 JD 后启动面试官。
2. 面试官只选择一个缺口。
3. 连续回答 2-3 次后可生成素材卡。
4. 用户点击“不知道”后系统换问法。
5. 用户编辑素材卡后保存。
6. 保存后预览刷新。
7. 关闭 LLM key 后仍可走模板追问。
8. 移动端聊天栏变为全屏抽屉。

---

## 14. 分阶段落地建议

### Phase 1: 后端面试循环 MVP

目标:

- 新增 `core/interview_agent.py`。
- 新增 `/api/interview/start|reply|draft`。
- 内存 session。
- 缺口选择规则。
- 模板追问。
- draft_card 生成。
- 不写库。

验收:

- 后端测试覆盖状态机。
- 无 LLM key 可跑通。
- trace 不含用户回答原文。

### Phase 2: 写库与刷新闭环

目标:

- 新增 `/api/interview/save-card`。
- 追加 project 到 `materials.json`。
- 保存后前端刷新 materials summary、match、preview。
- 写入失败保留 draft。

验收:

- 保存前必须用户确认。
- 写入后 project id 唯一。
- 老 `PUT /api/materials` 不破坏。

### Phase 3: 前端右侧聊天栏

目标:

- 新增 `InterviewAgentPanel.vue`。
- 桌面右侧栏。
- 移动端全屏抽屉。
- 快捷回复。
- 已捕捉事实进度。
- 素材卡编辑确认。

验收:

- `vue-tsc --noEmit`。
- `npm run build`。
- Playwright 或人工截图检查桌面/移动端不重叠。

### Phase 4: LLM 抽取增强

目标:

- 在有 key 时使用 LLM 从回答中抽取 slots。
- JSON schema 严格验证。
- 失败 fallback 到规则抽取。
- prompt 明确禁止编造。

验收:

- schema retry 覆盖。
- unknown/invalid LLM output 不阻断。
- draft_card warnings 能标出未确认信息。

### Phase 5: 评测与体验指标

目标:

- 新增离线 eval: 固定 JD + 模拟用户回答。
- 输出 schema pass、draft completeness、fabrication guard、latency。
- 不输出用户回答原文。

验收:

- 报告只含聚合指标。
- 可对比模板模式 vs LLM 抽取模式。

---

## 15. 成功指标

产品指标:

- 用户能在 3 分钟内完成一轮“缺口 → 素材卡”。
- 每轮平均问题数 <= 4。
- 用户可随时生成素材卡。
- 写库前 100% 有确认。
- 无 key 时可完成基础流程。

质量指标:

- draft_card 必含 `title/responsibility/actions/draft_bullets`。
- 若无量化指标, 必须提示 warning, 不硬编数字。
- 保存后 preview 能刷新。
- 新增素材能被后续 `match_score/retrieve_evidence` 使用。

工程指标:

- 不破坏 `enable_agent_workflow=False` 老路径。
- 不引入新外部依赖。
- 不把 live LLM eval 挂 pre-push。
- 后端新增测试覆盖核心状态机与隐私边界。
- 前端通过 `vue-tsc --noEmit` 和 build。

---

## 16. 风险与应对

| 风险 | 影响 | 应对 |
|---|---|---|
| 用户回答太短 | 抽取不到素材 | 换问法 + 快捷回复 + 允许继续追问 |
| 用户没有量化数据 | bullet 质量一般 | 明确 warning, 不编数字 |
| LLM 编造 | 信任受损 | schema + evidence/user answer 约束 + 用户确认 + warnings |
| 写库破坏 materials.json | 主流程受损 | save-card 最小 patch + 测试 + 可选备份 |
| App.vue 继续膨胀 | 维护困难 | 新建组件, App.vue 只接状态 |
| 移动端拥挤 | 体验差 | 移动端全屏抽屉 |
| 与 Agent 诊断概念混乱 | 用户困惑 | 前台叫“简历面试官”, 技术诊断隐藏 |

---

## 17. Open Questions

1. 第一版保存素材时, 是否只允许追加新 project, 还是也允许选择已有 project 追加 highlights?
   - 推荐: Phase 1/2 只追加新 project, P2 再做 merge。

2. 是否需要草稿持久化?
   - 推荐: 第一版不持久化, 只保留当前页面/内存 session。写库前关闭页面会丢失, 但实现更快。

3. 是否要在主页面默认展示右侧栏?
   - 推荐: 桌面默认展示入口, 启动后展开; 移动端默认按钮。

4. LLM 抽取是否 Phase 1 就上?
   - 推荐: Phase 1 先模板 + 规则抽取, Phase 4 再上 LLM 抽取增强。

---

## 18. 推荐实施顺序

最小可用版本:

```text
Phase 1 后端状态机
→ Phase 2 写库
→ Phase 3 前端聊天栏
```

之后再做:

```text
Phase 4 LLM 抽取增强
→ Phase 5 eval 与体验指标
```

这样可以最快验证核心假设:

> 用户是否愿意围绕 JD 缺口回答 2-3 个问题, 并把结果确认写入素材库。

如果这个假设成立, 后续再提高 LLM 智能度才有意义。否则继续优化 Agent Loop 或 prompt 都只是技术上更漂亮, 产品上未必更有用。
