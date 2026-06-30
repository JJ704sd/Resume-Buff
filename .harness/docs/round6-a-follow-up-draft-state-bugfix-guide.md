# Round 6-A Follow-up — `/api/interview/draft` 状态返回修复指导

> 适用项目: 简历帮 / Resume-Buff
> 日期: 2026-06-30
> 状态: 📝 修复指导文档, 未实施
> 范围: 小型 bugfix + 回归测试
> 当前基线: R6-A Phase 1+2+3+5 已完成;后端活跃基线 729 pytest;本地 `main` 已有文档提交 `6a61387 docs(round6-a): sync interview eval audit notes`

---

## 0. 目标

修复 `POST /api/interview/draft` 在 `can_draft=True` 时返回 `draft_card` 但没有把 session state 显式置为 `DRAFT_READY` 的状态一致性问题。

完成后:

- API 成功生成 draft card 时返回 `state == "DRAFT_READY"`。
- 后端进程内 session 的 `state` 同步变为 `InterviewState.DRAFT_READY`。
- 前端 `InterviewAgentPanel.vue` 能根据 `/draft` 返回状态进入素材卡视图。
- 不改变 `can_draft=False -> 400` 的现有行为。
- 不触碰 save-card 写库、LLM、eval 脚本、materials 真实数据。

---

## 1. 背景

R6-A 已完成面试官闭环:

```text
start -> reply -> draft -> save-card -> refresh preview/match
```

当前 `backend/api/interview.py::interview_draft` 的核心逻辑:

```python
card = build_draft_card(sess)
sess.draft_card = card
sess.state = sess.state  # 保持当前 state(已是 DRAFT_READY 或 ASKING)
return DraftResponse(
    state=sess.state.value,
    draft_card=card,
)
```

问题在于:

- 如果 session 已经是 `DRAFT_READY`,返回值看起来正确。
- 如果 session 只是满足 `can_draft=True`,但 state 仍是 `ASKING`,直接调用 `/draft` 会返回 `state="ASKING"`。
- 前端 `InterviewAgentPanel.vue` 的草稿卡展示分支依赖 `state === 'DRAFT_READY' && draftCard`。

因此这是一个状态一致性 bug,不是业务闭环缺失。

---

## 2. 第一性原理

`/api/interview/draft` 的语义不是“查询草稿”,而是“把当前可整理的信息收束成待确认素材卡”。

一旦 API 成功返回 `draft_card`,系统就已经进入确认状态:

```text
ASKING + can_draft=True + POST /draft
→ DRAFT_READY + draft_card
```

所以 state 必须跟响应语义一致。否则前端、测试、用户心智会出现分裂:

- 后端说“草稿生成了”。
- 前端还认为“仍在追问”。
- 用户看不到素材卡。

---

## 3. 非目标

本修复不做:

- 不引入 R6-B 的 LLM slot extraction。
- 不改 `build_draft_card()` 结构。
- 不改 `can_draft()` 收束条件。
- 不改 `apply_action(draft_now)` 行为。
- 不改 `/api/interview/save-card`。
- 不改 `materials.json`。
- 不改前端,除非测试发现前端仍无法展示。
- 不更新 eval 报告。

---

## 4. 涉及文件

### 必改

| 文件 | 改动 |
|---|---|
| `backend/api/interview.py` | `interview_draft()` 成功生成 card 后设置 `sess.state = InterviewState.DRAFT_READY` |
| `backend/tests/test_interview_api.py` | `TestDraftEndpoint::test_draft_returns_card_when_can_draft_true` 增加 state 断言 |

### 不应修改

| 文件 | 原因 |
|---|---|
| `backend/core/interview_agent.py` | `_do_draft_now()` 已正确设置 `DRAFT_READY`,本 bug 在 API endpoint |
| `backend/core/interview_prompts.py` | 与状态返回无关 |
| `backend/core/interview_agent.py::save_card` | 写库闭环已锁 |
| `scripts/evaluate_interview_agent.py` | eval 脚手架不受影响 |
| `frontend/src/components/InterviewAgentPanel.vue` | 前端逻辑依赖后端 state,先修 API |

---

## 5. TDD 修复步骤

### Step 1: 写失败测试

文件: `backend/tests/test_interview_api.py`

在 `TestDraftEndpoint::test_draft_returns_card_when_can_draft_true` 中,`data = resp.json()` 后新增:

```python
assert data["state"] == "DRAFT_READY"
```

建议完整断言块:

```python
resp = client.post("/api/interview/draft", json={"session_id": sid})
assert resp.status_code == 200, resp.text
data = resp.json()
assert data["state"] == "DRAFT_READY"
assert "draft_card" in data
card = data["draft_card"]
for f in ("title", "responsibility", "actions", "draft_bullets", "warnings"):
    assert f in card, f"draft_card 缺 {f!r}"
```

可选增强断言 session 内状态:

```python
assert sess.state.value == "DRAFT_READY"
```

如果加入这个断言,要放在调用 `/draft` 之后。

### Step 2: 运行测试确认失败

命令:

```powershell
Set-Location -LiteralPath D:\简历帮\backend
D:\python3.11\python.exe -m pytest tests/test_interview_api.py::TestDraftEndpoint::test_draft_returns_card_when_can_draft_true -q
```

预期失败:

```text
E       AssertionError: assert 'ASKING' == 'DRAFT_READY'
```

如果没有失败,先检查测试是否真的注入了 `can_draft=True` 且 session 初始 state 仍是 `ASKING`。

### Step 3: 最小实现修复

文件: `backend/api/interview.py`

当前 import 列表已经从 `core.interview_agent` 导入多个符号。需要确认是否已有 `InterviewState`:

```python
from core.interview_agent import (
    ActionType,
    apply_action,
    build_draft_card,
    can_draft,
    create_session,
    get_session,
    next_question,
    save_card,
)
```

如果没有,加入:

```python
    InterviewState,
```

然后修改 `interview_draft()`:

```python
card = build_draft_card(sess)
sess.draft_card = card
sess.state = InterviewState.DRAFT_READY
return DraftResponse(
    state=sess.state.value,
    draft_card=card,
)
```

不要用字符串 `"DRAFT_READY"` 直接赋值,因为 `InterviewSession.state` 在核心域里是 `InterviewState` enum。

### Step 4: 运行局部测试确认通过

命令:

```powershell
Set-Location -LiteralPath D:\简历帮\backend
D:\python3.11\python.exe -m pytest tests/test_interview_api.py::TestDraftEndpoint -q
```

预期:

```text
2 passed
```

### Step 5: 跑相关后端测试

命令:

```powershell
Set-Location -LiteralPath D:\简历帮\backend
D:\python3.11\python.exe -m pytest tests/test_interview_api.py tests/test_interview_agent.py -q
```

预期:

```text
all selected tests passed
```

实际数量以当前文件为准,不要在文档里硬编码 selected tests 的总数。

### Step 6: 跑全量后端测试

命令:

```powershell
Set-Location -LiteralPath D:\简历帮\backend
D:\python3.11\python.exe -m pytest tests/ -q
```

预期:

```text
729 passed
```

如仍出现既有 `UnicodeDecodeError` warning,但测试 0 failure,可记录为非阻塞既有 warning。

---

## 6. 验收标准

必须同时满足:

- `POST /api/interview/draft` 在 `can_draft=True` 时返回 200。
- response body 中 `state == "DRAFT_READY"`。
- response body 中仍包含 `draft_card`。
- session 内 `draft_card` 已写入。
- session 内 `state == InterviewState.DRAFT_READY`。
- `can_draft=False` 路径仍返回 400。
- `draft_now` reply 路径不回退。
- 全量 pytest 通过。

---

## 7. 回归风险

| 风险 | 影响 | 检查方式 |
|---|---|---|
| 忘记 import `InterviewState` | API endpoint NameError | 局部 API 测试会失败 |
| 用字符串赋值 state | 后续核心代码期望 enum 时行为不稳定 | 断言 `sess.state is InterviewState.DRAFT_READY` 或使用 enum |
| 修改 `can_draft()` | 影响状态机收束条件 | 不改 core 逻辑 |
| 修改 frontend 绕过问题 | 掩盖 API 语义错误 | 本轮先修 API |
| 测试污染真实 materials/logs | 隐私风险 | 复用现有 fixture / monkeypatch,本修复不触发 save-card |

---

## 8. 建议提交

提交范围:

```text
backend/api/interview.py
backend/tests/test_interview_api.py
```

提交信息:

```text
fix(round6-a): set draft endpoint state to draft ready
```

不要把以下文件混入同一 commit:

- `.planning/面试讲解/`
- R6-B spec 文档
- eval report
- `backend/data/materials.json`
- `backend/logs/*`

---

## 9. 后续关系

这个 bugfix 是 R6-B 之前的铺垫。

R6-B 会让 `can_draft=True` 更早、更频繁出现。如果 `/draft` 成功后不切到 `DRAFT_READY`,前端素材卡展示会更容易失效。因此本修复应先于任何 LLM slot extraction / confidence policy / draft verifier 实施。

