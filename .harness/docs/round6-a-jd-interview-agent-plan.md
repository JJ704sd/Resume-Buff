# Round 6-A — JD-Driven Interview Agent 实施计划

> 状态: 📝 待实施(plan 文档,父 spec: `.harness/docs/round6-a-jd-interview-agent-spec.md`,本文件不是 spec,不改 spec 文字)
> 父 ROADMAP: `.harness/docs/ROADMAP.md` 1. P1 段(待本 round 收尾时把 baseline 数字 + commit hash 写回)
> 父 spec 章节锚点: §0 结论 / §4 核心流程 / §5 缺口选择 / §6 追问策略 / §7 数据模型 / §8 API 草案 / §9 写库 / §10 前端 / §11 后端分层 / §12 隐私 / §13 测试 / §14 分阶段
> Round 标签: `feat(round6-a): jd-interview-agent` — 按 Phase 拆 commit(每个 Phase 一个独立 commit + 全量绿再走下一个)
> 工作量估算: Phase 1 ~350 行 / Phase 2 ~120 行 / Phase 3 ~300 行 / Phase 4 ~150 行 / Phase 5 ~200 行;新测试预计 +35 ~ +45 pytest
> 严格 R5-E 保护: 不改 `SYSTEM_PROMPT` 默认内容 / 不改 `PROMPT_VERSION_BASELINE` / 不改 `enable_agent_workflow=False` 老路径 / 不动 `agent_workflow.py` 既有字段 / 不挂 pre-push 新脚本
> 不触碰范围: `.planning/面试讲解/` 整个目录 / `.planning/agent-architecture-audit/` / 已有 8 套模板渲染器 / 任何无关模块

---

## 0. 背景(为什么开这一轮)

R5-A/B/C/D/E 5 轮迭代把 Agent workflow 做到了"可评测 + 可解释 + 可被前端安全消费",但**用户视角下,这套能力还没进入主流程** — 用户仍然只看到"贴 JD → 评分 → 改写 bullets → 下载 docx"。本轮目标:

- 把 R5-A/B/C 的 `agent_summary` / `evidence_summary` / `external_resume_perspective` / `bullet_evaluations` **消费在用户主动路径上**
- 用"JD 驱动简历面试官"产品形态,把 Agent 能力包装成"帮我补一段经历"的具体任务
- **不替代** R5-E 的 prompt rollout 决策;interview_agent 走自己的 prompt 模块(不进 `PROMPT_VERSIONS`)

### 0.1 R5-E 基线确认(plan 启动前必跑)

| 项目 | 期望 | 命令 |
|---|---|---|
| 测试基线 | 683 passed + 0 skipped | `cd backend && D:\python3.11\python.exe -m pytest tests/ --collect-only -q` |
| 默认 prompt | `PROMPT_VERSION_BASELINE = "v2-baseline"` | `python -c "from core.llm_rewriter import PROMPT_VERSION_BASELINE; print(PROMPT_VERSION_BASELINE)"` |
| 老路径稳定 | `enable_agent_workflow=False` 时 preview 不含 `agent_summary` / `evidence_summary` / `external_resume_perspective` / `bullet_evaluations` 任一字段 | 跑 test_api_jd.py + test_r5c_phase2_external_resume.py + test_r5c_phase3_bullet_evaluation.py 既有 case |
| 系统 prompt | `SYSTEM_PROMPT` 字符串未被任何分支替换 | `python -c "from core.llm_rewriter import SYSTEM_PROMPT, _resolve_prompt_version, _select_system_prompt; assert _select_system_prompt(None, None) is SYSTEM_PROMPT"` |

### 0.2 父 spec 的 4 个硬冲突如何在本 plan 解决(plan 不改 spec 文字,本节只是落地策略)

| Spec 冲突点 | Plan 处理 | 决策点编号 |
|---|---|---|
| §9.1 project schema 与现有 materials.json 不一致(highlights flat list vs dict) | Phase 2 落地时按真实 schema 写:`highlights[role_key]` dict + 加 `category="interview_captured"` + `tags=["interview_agent"]` | **D1** |
| §5.1 evidence_summary 作为缺口来源(实际是 snippet list,不是 keyword coverage) | Phase 1 缺口选择**只用** `match_score.missing_keywords` + `parse_jd` 摘要;`external_resume_perspective` / `bullet_evaluations` 只有在后续阶段显式传入诊断摘要时才作为加分输入;不用 evidence_summary | 已解决(无须决策) |
| §7.1/§12.1 trace 写入策略没说怎么走 | Phase 1 复用现有 `agent_trace.jsonl`,写 `workflow="interview"` + 数字 `step=0/1/2...` + `tool` enum `"gap_select"`/`"slot_extract"`/`"draft_card"`;`request_id="ia"+8 hex`;`input_size/output_size` 只算字节数;**不扩 schema,不写新 logger** | **D2** |
| §8.1 enable_agent_workflow 字段拿了不消费 | Phase 1 API schema **不加这个字段**,缺口选择直接调 `parse_jd` 与 `match_score`,不走 `run_agent_workflow`,不调用 `_evaluate_top_bullets` | 已解决(无须决策) |

---

## 1. Phase 1 — 后端面试循环 MVP(最高优先级,先做)

### 1.1 目标

最小可用后端:用户贴 JD → 系统选一个缺口 → 一问一答 → 用户回答 → 系统捕捉槽位 → 达到收束条件 → 生成 draft_card。**不写库 / 不上前端 / 不接 LLM 抽取(规则抽取即可) / 不动 agent_workflow**。

### 1.2 范围

**新增**:
- `backend/core/interview_prompts.py` — 问题模板库 + 槽位定义 + draft_card schema 提示
- `backend/core/interview_agent.py` — 状态机 + 缺口选择规则 + 槽位抽取(规则版)+ draft_card 生成
- `backend/api/interview.py` — FastAPI router,暴露 `POST /api/interview/start|reply|draft`
- `backend/tests/test_interview_agent.py` — 状态机 / 缺口选择 / 槽位抽取 / draft_card 单测
- `backend/tests/test_interview_api.py` — start/reply/draft HTTP 接口测试

**修改**:
- `backend/main.py` — 1 行改动,注册 `interview_router`

**不修改**(显式列出防止误改):
- `backend/core/llm_rewriter.py`(任何字符)
- `backend/core/agent_workflow.py`(任何字符)
- `backend/core/agent_tools.py`(任何字符)
- `backend/core/jd_parser.py`(任何字符)
- `backend/core/evidence.py`(任何字符)
- `backend/api/resume.py` / `backend/api/materials.py` / `backend/api/jd.py`(任何字符)
- `backend/data/materials.json`(任何字符)
- 任何 frontend 文件
- 任何 `scripts/` 文件

### 1.3 新增文件设计要点

#### `backend/core/interview_prompts.py`(~120 行)

模块常量,无 class:

```text
常量(纯 dict / str,无副作用):
  SLOT_NAMES: tuple[str, ...] = ("background", "responsibility", "action", "method",
                                    "difficulty", "result", "metric")
  GAP_SUGGESTED_SLOTS: dict[str, tuple[str, ...]] = {
      "process_metric":  ("responsibility", "action", "result", "metric"),
      "tech_metric":     ("background", "responsibility", "action", "method", "result"),
      "communication":   ("background", "action", "method", "result"),
      "domain_x":        ("responsibility", "action", "method", "difficulty", "result"),
  }  # gap_id → 该缺口下建议追问的 slot 顺序(Phase 1 用 4 个固定 gap_id)

  GAP_LABELS: dict[str, str] = {
      "process_metric": "流程优化/量化结果",
      "tech_metric":    "技术深度/方法论",
      "communication":  "协同/沟通",
      "domain_x":       "领域经验/项目深度",
  }

  GAP_REASONS: dict[str, str] = {
      "process_metric": "JD 多次强调流程、协同和指标, 当前素材库证据不足",
      "tech_metric":    "JD 强调技术方法论, 但你的项目缺少方法描述",
      "communication":  "JD 要求协同能力, 素材库里相关经历不足",
      "domain_x":       "JD 关注的领域经验在你的素材库覆盖偏弱",
  }

  QUESTION_TEMPLATES: dict[tuple[str, str], str] = {
      # (gap_id, slot) → 问题模板;Phase 1 完全模板化, 不调 LLM
      ("process_metric", "responsibility"): "你当时主要负责哪一块? 可以从「分析、设计、执行、协调、测试」里选一个最接近的。",
      ("process_metric", "action"):         "你具体做了什么动作? 先不用写得正式, 像讲给面试官听一样说就行。",
      ("process_metric", "result"):         "最后带来了什么变化? 比如减少了返工、让协作更顺、覆盖更多场景。",
      ("process_metric", "metric"):         "有没有数字可以支持? 比如人数、次数、时长、准确率、效率、覆盖范围。没有也可以直接说没有。",
      ("tech_metric", "background"):       "这个经历发生在什么项目或场景里? 可以先说一句背景。",
      ("tech_metric", "responsibility"):   "你在里面承担的是分析、开发、测试、协调,还是别的角色?",
      ("tech_metric", "action"):           "你最能体现技术方法的一步是什么? 例如建模、标注规则、评估、自动化、数据处理。",
      ("tech_metric", "method"):           "当时用了什么方法、工具或判断标准? 不需要很专业,说清楚你怎么做的就行。",
      ("communication", "background"):     "这段经历里有没有需要和别人协作、沟通或对齐的场景?",
      ("communication", "action"):         "你具体怎么推动沟通? 比如整理信息、拉齐目标、分工、跟进、复盘。",
      ("communication", "method"):         "你用了什么方式让事情推进? 例如会议、文档、表格、原型、流程图或检查清单。",
      ("communication", "result"):         "沟通之后有什么变化? 比如减少误解、缩短周期、让交付更稳定。",
      ("domain_x", "responsibility"):      "这个经历和目标岗位最相关的一块是什么? 你负责了哪部分?",
      ("domain_x", "action"):              "你做了哪些能体现这个领域理解的动作?",
      ("domain_x", "method"):              "你当时依据了什么规则、业务逻辑或用户需求来判断?",
      ("domain_x", "difficulty"):          "这个场景里最难、最卡或最容易出错的点是什么?",
  }

  QUICK_REPLIES_BY_SLOT: dict[str, tuple[str, ...]] = {
      "responsibility": ("我负责执行", "我负责分析", "我负责协调", "不确定", "换个问法", "跳过这个问题"),
      "action":         ("执行了一个动作", "设计了一个方案", "推动了一件事", "想不起来", "换个问法", "跳过这个问题"),
      "background":     ("课程项目", "社团活动", "比赛经历", "实习/兼职", "换个问法", "跳过这个问题"),
      "method":         ("用了表格/文档", "用了工具", "按流程推进", "没有固定方法", "换个问法", "跳过这个问题"),
      "difficulty":     ("时间紧", "信息不清楚", "协作难", "技术不熟", "换个问法", "跳过这个问题"),
      "result":         ("让流程变快", "减少了错误", "让协作更顺", "没有明显结果", "换个问法", "跳过这个问题"),
      "metric":         ("大概有", "没有数据", "想不起来", "换个问法", "跳过这个问题"),
  }

  CAN_DRAFT_CONDITIONS: tuple[tuple[str, ...], ...] = (
      ("background", "action", "result"),
      ("responsibility", "action", "metric"),
      ("responsibility", "action", "result"),
  )  # 满足任一组合即可收束; spec §4.4

  MAX_TURNS_PER_GAP = 3  # spec §4.4 上限, 不机械卡死

  INTERVIEW_MAX_MESSAGE_LEN = 2000       # spec §12.2
  INTERVIEW_MAX_DRAFT_LEN = 20_000       # spec §12.2
  INTERVIEW_MAX_SESSION_ID_LEN = 64      # spec §12.2
  INTERVIEW_MAX_JD_TEXT_LEN = 50_000     # 沿用 jd.py 的 _MAX_TEXT_LEN
```

**R5-E 保护**:本文件 import 任何 `core.llm_rewriter` 都会破坏字节级稳定,所以**完全不 import**,纯常量文件。

#### `backend/core/interview_agent.py`(~250 行)

模块结构(纯函数 + dataclass + 一个进程内 dict,无外部副作用):

```text
公开 API:
  class InterviewState(str, Enum): EMPTY / DIAGNOSING / ASKING / DRAFT_READY / SAVED / ABORTED
  class ActionType(str, Enum):    answer / skip_question / rephrase_question / switch_gap / draft_now

  @dataclass(frozen=True)
  class GapCandidate:
      gap_id: str
      label: str
      reason: str
      keywords: list[str]
      source: list[str]         # 数据源: ["match_score"] / ["parse_jd"] / ["manual"]
      tier: str                 # "required" / "preferred" / "bonus"
      priority: float
      suggested_slots: list[str]

  @dataclass
  class InterviewSession:
      session_id: str           # "ia" + 8 hex
      target_role: str
      jd_digest: dict           # parse_jd 输出(只缓存摘要, 不存原文)
      selected_gap: GapCandidate | None
      state: InterviewState
      turn_count: int
      captured_slots: dict[str, Any]  # {background: str?, responsibility: str?, actions: [...], ...}
      skip_count: int            # 连续 skip 数, 达 2 强制收束(spec §4.4)
      draft_card: dict | None
      message_log: list[dict]    # [{role: "user", content: "..."}] 只在内存, 不写 trace 原文

  def create_session(target_role: str, jd_text: str, materials: dict) -> InterviewSession
  def select_gap(session: InterviewSession) -> GapCandidate      # 规则打分, 不用 LLM
  def next_question(session: InterviewSession) -> dict          # 返回 {slot, text, quick_replies}
  def extract_slots(user_message: str, current_slot: str, session: InterviewSession) -> dict
                                                                   # 规则抽取, 不调 LLM
  def can_draft(session: InterviewSession) -> bool
  def build_draft_card(session: InterviewSession) -> dict
  def apply_action(session: InterviewSession, action: ActionType, user_message: str | None) -> tuple[InterviewSession, dict]
                                                                   # 统一状态转移入口
  def get_session(session_id: str) -> InterviewSession | None
  def reset_session(session_id: str) -> bool                     # 用于 switch_gap

  进程内存储:
  _INTERVIEW_SESSIONS: dict[str, InterviewSession] = {}          # 与 core/session.py 隔离(决策点 D3)

  trace 写入: 通过 core.logger.log_agent_trace_jsonl 调用,
              request_id 自生成 "ia" + 8 hex,
              workflow="interview",
              step 为数字递增值(0=start/gap_select, 1..N=slot_extract, draft_card=最后一步),
              tool in {"gap_select", "slot_extract", "draft_card"},
              input_size/output_size 算字节数,
              不存原文, 不存 user_message
```

**核心算法(规则版缺口选择,spec §5.3)**:
```text
priority =
    + 4 if tier == "required"
    + 2 if tier == "preferred"
    + 1 if tier == "bonus"
    + 3 if 该 gap 的关键词出现在 match_score.missing_keywords
    + 2 if parse_jd 摘要中该类关键词重复出现(同类 >= 2)
    + 2 if gap_id in 可追问 gap 白名单(process_metric / tech_metric / communication / domain_x)
    - 5 if gap 属于"不该优先追问"白名单(spec §5.4:学历/年限/证书/硬技能/无相邻证据)
排序: priority desc, gap_id asc(稳定排序)
取 Top 1 = selected_gap

Phase 1 不读取 `agent_summary` / `external_resume_perspective` / `bullet_evaluations`;后续如果要把这些诊断摘要纳入优先级,必须先新增明确入参和测试,不得 import `core.agent_workflow` 的内部 helper。
```

**槽位抽取规则(Phase 1 无 key 路径)**:
```text
输入: user_message (str), current_slot (str)
输出: 更新 captured_slots[current_slot]

规则:
  - background:    整段当 string, 截 200 字
  - responsibility: 在 user_message 里找 ["负责" / "主管" / "owner" / "主导"] 后面到下一个标点前的短语, 没找到整段当 string
  - action:        按 ";" / "。" / "，" / "\n" 切, 每段 trim, 非空段入 actions[] 列表
  - method:        找 ["用了" / "采用" / "基于" / "通过"] 后面到句末, 入 methods[]
  - difficulty:    找 ["难" / "坑" / "卡" / "问题"] 周围 30 字窗口
  - result:        找 ["结果" / "最后" / "最终" / "产出"] 后面到句末
  - metric:        regex 找数字 + 单位(人 / % / 倍 / 小时 / 天 / 次 / 万...), 入 metrics[]
警告: 未命中任何关键词 → 加 1 条 warning "未识别槽位内容, 已存原文供用户编辑"
```

**R5-E 保护**:
- 不 import `core.llm_rewriter`
- 不 import `core.agent_workflow`;Phase 1 只用 `core.jd_parser.parse_jd` 与 `core.jd_parser.match_score` 两个公开函数
- 验证:`import core.llm_rewriter as llm; from core.interview_agent import *; assert llm._select_system_prompt(None, None) is llm.SYSTEM_PROMPT` 仍成立

#### `backend/api/interview.py`(~150 行)

FastAPI router,与 `api/resume.py` 同风格:

```text
class StartRequest(BaseModel):
    target_role: str
    jd_text: str
    # Phase 1 不加 enable_agent_workflow / external_resume_text;
    # interview_agent 只消费本次 JD + materials 计算缺口

class StartResponse(BaseModel):
    session_id: str
    state: str
    selected_gap: dict
    message: dict    # {role, type, slot, text, quick_replies}
    progress: dict   # {captured: {slot: bool}, turn_count, can_draft}

class ReplyRequest(BaseModel):
    session_id: str
    message: str = ""
    action: str     # answer | skip_question | rephrase_question | switch_gap | draft_now

class ReplyResponse(BaseModel):
    state: str
    message: dict | None
    captured_delta: dict | None
    progress: dict

class DraftResponse(BaseModel):
    state: str
    draft_card: dict

错误处理:
  - 422: jd_text 空 / > 50k / target_role 不在 ENABLED_ROLES
  - 422: message > 2000 chars
  - 404: session_id 不存在
  - 400: action 不在合法 enum
  - 400: action="draft_now" 但 can_draft=False(spec §4.4 收束条件未满足, 不强推)

端点:
  POST /api/interview/start
  POST /api/interview/reply
  POST /api/interview/draft

不端点:
  ❌ POST /api/interview/save-card  (留 Phase 2)
  ❌ GET  /api/interview/session/{id} (Phase 1 前端不需要)
```

**R5-E 保护**:`api/interview.py` 完全独立 router,不挂到 `resume_router` 上。

### 1.4 测试设计

#### `backend/tests/test_interview_agent.py`(新增,~10-12 case)

```text
TestSessionLifecycle:
  test_create_session_returns_ia_prefix        # session_id 以 "ia" 开头
  test_get_session_returns_none_for_unknown    # 不存在 id 返 None
  test_reset_session_clears_state              # switch_gap 后状态重置

TestGapSelection:
  test_select_gap_prioritizes_required_tier    # required tier 分数 > preferred > bonus
  test_select_gap_uses_match_score_missing     # missing_keywords 影响选择
  test_select_gap_does_not_import_workflow     # 不依赖 agent_workflow 内部 helper
  test_select_gap_ignores_uninterviewable      # "学历" / "年限" 类 gap -5 分落选
  test_select_gap_returns_top_one              # 始终返 1 个 gap

TestSlotExtractionRules:
  test_extract_background_returns_short_string
  test_extract_action_splits_on_punctuation
  test_extract_method_finds_tool_keyword
  test_extract_metric_regex_finds_numbers

TestDraftCard:
  test_can_draft_true_when_required_combo      # background+action+result 满足
  test_can_draft_true_when_alt_combo           # responsibility+action+metric 满足
  test_build_draft_card_contains_required_fields
  test_draft_card_warnings_for_missing_quant

TestStateMachine:
  test_apply_action_skip_increments_skip_count
  test_two_consecutive_skips_forces_draft       # 连续 2 次 skip 触发 draft 提示
  test_max_turns_per_gap_caps_at_three

TestTracePrivacy:
  test_trace_does_not_contain_user_message     # mock log_agent_trace_jsonl, 抓 input_size 字段不含原文
  test_trace_does_not_contain_draft_card_text  # mock 同上, draft_card text 不入 trace
```

#### `backend/tests/test_interview_api.py`(新增,~5-6 case)

```text
TestStartEndpoint:
  test_start_happy_path_returns_session_and_question
  test_start_empty_jd_returns_422
  test_start_overlong_jd_returns_422
  test_start_unknown_role_returns_422           # target_role 不在 ENABLED_ROLES

TestReplyEndpoint:
  test_reply_answer_extracts_slot
  test_reply_skip_advances_slot
  test_reply_draft_now_returns_draft_card
  test_reply_unknown_session_returns_404

TestDraftEndpoint:
  test_draft_returns_card_when_can_draft_true
  test_draft_returns_400_when_cannot_draft_yet
```

### 1.5 验收命令

```powershell
# 1) 跑新测试
Set-Location -LiteralPath D:\简历帮\backend
D:\python3.11\python.exe -m pytest tests/test_interview_agent.py tests/test_interview_api.py -v

# 2) 跑全量回归 — 必须保持 683 老测试 0 回退
D:\python3.11\python.exe -m pytest tests/ -v

# 3) 验证 R5-E baseline
D:\python3.11\python.exe -m pytest tests/test_prompt_versioning.py tests/test_prompt_eval.py tests/test_r5c_phase2_external_resume.py tests/test_r5c_phase3_bullet_evaluation.py -v

# 4) 验证老路径字节级稳定
D:\python3.11\python.exe -c "from core.llm_rewriter import SYSTEM_PROMPT, _select_system_prompt, PROMPT_VERSION_BASELINE; assert PROMPT_VERSION_BASELINE == 'v2-baseline'; assert _select_system_prompt(None, None) is SYSTEM_PROMPT; print('OK R5-E stable')"

# 5) 启动后端冒烟(可选,本 phase 不强制端到端,纯前端手测留给 Phase 3)
python main.py
# 在另一个 shell:
# curl http://127.0.0.1:8000/api/health → {"status":"ok"}
# curl -X POST http://127.0.0.1:8000/api/interview/start -H 'Content-Type: application/json' -d '{"target_role":"test_qa","jd_text":"岗位要求: 参与 AI 产品测试与数据质量评估, 能梳理流程并跟进问题闭环。"}' → 返 session_id + 第一问
```

### 1.6 预期基线

`683 → 683 + 17 = 700 passed + 0 skipped`(Phase 1 新增 17 测试,683 老测试零回退)。

### 1.7 commit 风格

```text
feat(round6-a): add interview agent backend mvp
- new module core/interview_prompts.py (template questions + slot defs)
- new module core/interview_agent.py (state machine + gap selection + slot extract + draft_card)
- new module api/interview.py (start/reply/draft endpoints)
- new test file tests/test_interview_agent.py (11 case)
- new test file tests/test_interview_api.py (6 case)
- main.py: register interview router (1 line)
- 不改 R5-E 任何 baseline 字段(SYSTEM_PROMPT / prompt_version / agent_summary / evidence_summary / external_resume_perspective / bullet_evaluations)
- 老路径 enable_agent_workflow=False 字节级一致
- 17 个新 pytest 全绿, 683 老测试零回退
```

---

## 2. Phase 2 — save-card 写库与刷新闭环

### 2.1 目标

新增 `POST /api/interview/save-card` 端点;Phase 1 生成的 draft_card → 用户在前端编辑后 → 追加为新 project 到 `materials.json` → 前端自动刷新 `match_score` + `preview_resume`。

### 2.2 范围

**新增**:
- `backend/core/interview_agent.py` — `save_card(session, edited_card, save_mode) -> dict` 函数(在 Phase 1 模块里扩)
- `backend/api/interview.py` — `save-card` 端点 + `SaveRequest` / `SaveResponse` model

**修改**:
- `backend/core/interview_agent.py` — 新增 save-card 的材料库读写 helper,支持 `materials_path` 注入以便测试走临时文件
- `backend/data/materials.json` — **仅生产/手动使用时运行期追加 project**,不作为本 Phase 的 git diff;测试和冒烟必须使用临时 copy,禁止直接改真实文件

**不修改**:跟 Phase 1 一样。

### 2.3 关键实现要点(决策点 D1 落地点)

```text
save_card 输入:
  - session: InterviewSession
  - edited_card: dict      # 前端编辑过的 draft_card(可能修改了 title / draft_bullets / actions 等)
  - save_mode: str         # Phase 2 只接受 "append_project", 其他 400
  - materials_path: Path | None = None  # 仅测试/冒烟传入;None 时默认 backend/data/materials.json

save_card 内部:
  1. 校验 session 存在
  2. 校验 edited_card 必填字段: title / responsibility / actions / draft_bullets
  3. 校验 draft_bullets 非空 + 每条 <= 200 字
  4. 生成 project id: "interview_" + 日期 + "_" + 3 位序号(查现有 id 避免冲突)
  5. 构造新 project 结构(决策点 D1):
     {
       "id": "interview_20260629_001",
       "name": edited_card["title"],
       "period": "",                              # 用户没填, 留空
       "role": edited_card.get("responsibility", ""),  # 沿用现有 role 单字符串
       "category": "interview_captured",         # 新增 category 枚举值
       "summary": edited_card.get("summary", ""),
       "highlights": {                            # 关键:按 role 分类的 dict!
         session.target_role: edited_card["draft_bullets"],
         "general":            edited_card["draft_bullets"],  # 双写入, 换 role 不丢
       },
       "tags": ["interview_agent"] + edited_card.get("skills", []),
       # 额外字段(不进 build_sections, 仅作审计):
       "_interview_meta": {
         "source_gap_id": session.selected_gap.gap_id,
         "source_session_id": session.session_id,
         "created_at": "2026-06-29T19:30:00+08:00",
         "warnings": edited_card.get("warnings", []),
       }
     }
  6. 读 materials.json:
     - 在 `core/interview_agent.py` 内新增 `_load_materials_for_save(materials_path)` / `_atomic_save_materials(data, materials_path)` 两个私有 helper
     - 默认路径为 `backend/data/materials.json`
     - 测试必须传临时 `materials_path`
     - 不 import `api.materials._load/_save`,避免 API 私有 helper 泄漏到 core 层
  7. projects.append(new_project) + _meta.last_updated = now
  8. 原子写: tmp file + os.replace(避免半写崩文件)
  9. round-trip 自检: 立即调 preview_resume(target_role=session.target_role), 断言至少 1 条新 highlight 出现在 sections
  10. 返:
     {
       "ok": true,
       "material_ref": {"type": "project", "id": new_project["id"]},
       "refresh": {"should_refresh_preview": true, "should_refresh_match": true},
       "preview_score_delta": {"before": 50, "after": 65},  # 可选, 空就 None
     }
  11. session.state = SAVED
  12. 写一条 trace: workflow="interview", step 为数字递增值, tool="save_card",
      input_size=edited_card 字节数, output_size=new_project 字节数,
      不存 draft_card 原文 / 不存 user_message

错误处理:
  - 404: session 不存在
  - 400: save_mode != "append_project" (Phase 2 暂不支持 append_to_existing_project, 决策点 D4)
  - 422: edited_card 缺字段 / draft_bullets 空 / 单条超长
  - 500: IO 错(原子写已防止半写, 但万一 disk 满)
```

**R5-E 保护**:
- 新 project 的 `highlights` 是 dict 不是 flat list,跟现有 schema 字节级兼容(用 `from core.generator import _pick_highlights` 自检)
- 不动 `_meta.version` / `_meta.source_files`
- 不改 PUT /api/materials 既有路径

### 2.4 测试设计

#### 扩展 `test_interview_agent.py`(+3 case)

```text
TestSaveCard:
  test_save_card_writes_to_temp_materials_path          # 验证测试不触碰真实 data/materials.json
  test_save_card_generates_unique_project_id             # 连续 2 次 save 不冲突
  test_save_card_round_trip_through_preview_resume       # 写完 preview_resume 能 pick 到
```

#### 扩展 `test_interview_api.py`(+4 case)

```text
TestSaveCardEndpoint:
  test_save_card_happy_path_writes_project
  test_save_card_invalid_save_mode_returns_400
  test_save_card_missing_required_field_returns_422
  test_save_card_empty_bullets_returns_422
```

### 2.5 验收命令

```powershell
Set-Location -LiteralPath D:\简历帮\backend

# 1) 新增测试
D:\python3.11\python.exe -m pytest tests/test_interview_agent.py tests/test_interview_api.py -v

# 2) 全量回归 — 必须 683+17 → 700+7 = 707 绿
D:\python3.11\python.exe -m pytest tests/ --collect-only -q

# 3) 端到端冒烟
D:\python3.11\python.exe -c "
import json
import shutil
import tempfile
from pathlib import Path
from core.interview_agent import GapCandidate, InterviewSession, InterviewState, save_card

source = Path('data/materials.json')
with tempfile.TemporaryDirectory() as td:
    temp_path = Path(td) / 'materials.json'
    shutil.copy2(source, temp_path)
    gap = GapCandidate(
        gap_id='process_metric',
        label='流程优化/量化结果',
        reason='测试 save-card 写入闭环',
        keywords=['流程', '效率'],
        source=['manual'],
        tier='required',
        priority=9.0,
        suggested_slots=['responsibility', 'action', 'result', 'metric'],
    )
    session = InterviewSession(
        session_id='ia_smoke001',
        target_role='test_qa',
        jd_digest={},
        selected_gap=gap,
        state=InterviewState.DRAFT_READY,
        turn_count=3,
        captured_slots={},
        skip_count=0,
        draft_card=None,
        message_log=[],
    )
    edited_card = {
        'title': '测试流程优化经历',
        'responsibility': '负责测试流程梳理',
        'summary': '通过整理用例和反馈链路提升测试协作效率',
        'actions': ['梳理问题反馈表', '统一测试记录格式'],
        'draft_bullets': ['梳理测试反馈流程, 统一记录格式, 提升多人协作效率'],
        'skills': ['测试流程'],
        'warnings': [],
    }
    result = save_card(session, edited_card, 'append_project', materials_path=temp_path)
    assert result['ok']
    materials_after = json.loads(temp_path.read_text(encoding='utf-8'))
    assert any(p['id'] == result['material_ref']['id'] for p in materials_after['projects'])
    original = json.loads(source.read_text(encoding='utf-8'))
    assert not any(p['id'] == result['material_ref']['id'] for p in original['projects'])
print('OK save-card round-trip')
"
```

### 2.6 预期基线

`700 → 707 passed + 0 skipped`(Phase 2 新增 7 测试,700 老测试零回退)。

### 2.7 commit 风格

```text
feat(round6-a): save interview draft card to materials
- core/interview_agent.py: add save_card() function
- api/interview.py: add POST /api/interview/save-card endpoint
- test_interview_agent.py: +3 case (project dict / id uniqueness / round-trip)
- test_interview_api.py: +4 case (happy path / invalid save_mode / missing field / empty bullets)
- 新 project schema 跟现有 materials.json 兼容: highlights 走 {role_key: [...]} dict + category="interview_captured"
- 7 个新 pytest 全绿, 700 老测试零回退
- 老 PUT /api/materials 路径不动
```

---

## 3. Phase 3 — 前端右侧聊天栏

### 3.1 目标

桌面端右侧常驻 380px 聊天栏 + 移动端底部按钮打开全屏抽屉。组件化 3 个新 .vue 文件,App.vue 只加挂载点(<200 行 diff)。

### 3.2 范围

**新增**:
- `frontend/src/components/InterviewAgentPanel.vue`(主聊天栏,~200 行)
- `frontend/src/components/InterviewDraftCard.vue`(素材卡编辑区,~100 行)
- `frontend/src/components/InterviewProgressPills.vue`(已捕捉事实进度,~50 行)

**修改**:
- `frontend/src/api/index.ts` — 加 5 个 TS 类型 + 4 个 API 函数
- `frontend/src/App.vue` — 加 interview state refs + 挂载点(<200 行 diff)
- `frontend/src/api/index.ts` 已经有 `AgentSummary` / `EvidenceSummary` / `ExternalResumePerspective` / `BulletEvaluation`,沿用 R5-C Phase 4 的 import 风格

**不修改**:其他 vue 组件 / vite.config / main.ts / package.json。

### 3.3 新增文件设计要点

#### `frontend/src/api/index.ts` 增量

```text
新增类型:
  InterviewState = 'EMPTY' | 'DIAGNOSING' | 'ASKING' | 'DRAFT_READY' | 'SAVED' | 'ABORTED'
  InterviewAction = 'answer' | 'skip_question' | 'rephrase_question' | 'switch_gap' | 'draft_now'
  InterviewMessage = { role: 'assistant' | 'user'; type?: 'question'; slot?: string; text: string; quick_replies?: string[] }
  InterviewProgress = { captured: Record<string, boolean>; turn_count: number; can_draft: boolean }
  InterviewGap = { gap_id: string; label: string; reason: string; keywords?: string[]; tier?: string; priority?: number; suggested_slots?: string[] }
  InterviewDraftCard = { title: string; target_role?: string; source_gap_id?: string; background: string; responsibility: string; actions: string[]; methods: string[]; difficulty: string; result: string; metrics: string[]; skills: string[]; draft_bullets: string[]; warnings: string[] }
  InterviewStartRequest  = { target_role: string; jd_text: string }
  InterviewStartResponse = { session_id: string; state: InterviewState; selected_gap: InterviewGap; message: InterviewMessage; progress: InterviewProgress }
  InterviewReplyRequest  = { session_id: string; message: string; action: InterviewAction }
  InterviewReplyResponse = { state: InterviewState; message: InterviewMessage | null; captured_delta: Record<string, any> | null; progress: InterviewProgress }
  InterviewDraftResponse = { state: InterviewState; draft_card: InterviewDraftCard }
  InterviewSaveRequest   = { session_id: string; edited_card: InterviewDraftCard; save_mode: 'append_project' }
  InterviewSaveResponse  = { ok: boolean; material_ref: { type: 'project'; id: string }; refresh: { should_refresh_preview: boolean; should_refresh_match: boolean }; preview_score_delta?: { before: number; after: number } | null }

新增 API 函数(axios 封装):
  interviewApi.start(req: InterviewStartRequest): Promise<InterviewStartResponse>
  interviewApi.reply(req: InterviewReplyRequest): Promise<InterviewReplyResponse>
  interviewApi.draft(session_id: string): Promise<InterviewDraftResponse>
  interviewApi.saveCard(req: InterviewSaveRequest): Promise<InterviewSaveResponse>
```

#### `InterviewAgentPanel.vue` 设计

```text
Props: 无
Emits:
  refresh-match:    []       # 通知 App.vue 重跑 jdApi.match
  refresh-preview:  []       # 通知 App.vue 重跑 resumeApi.preview

内部 state(refs):
  sessionId: string = ''
  state: InterviewState = 'EMPTY'
  selectedGap: InterviewGap | null
  messages: InterviewMessage[]    # [{role:'assistant', ...}, {role:'user', text:'...'}, ...]
  progress: InterviewProgress
  draftCard: InterviewDraftCard | null
  userInput: string = ''
  loading: boolean = false

布局(桌面):
  右侧 sticky 380px 宽
  Header: "简历面试官"
  [空状态] 居中提示 + "让面试官帮我补经历" 按钮
  [诊断中] "正在找最值得补的一块经历证据..."
  [追问中]
    当前缺口 tag + reason
    消息流(滚动)
    ProgressPills 组件
    快捷回复 chips
    输入框 + 快捷回复点击
    "整理成素材" / "换一个缺口" 按钮
  [DRAFT_READY]
    DraftCard 组件 + "确认写入素材库" / "继续追问" / "先保存草稿" / "丢弃" 按钮

布局(移动端):
  右下 FAB 按钮 "简历面试官"
  点击 → el-drawer 全屏 + 上面所有内容

启动逻辑:
  1. 空状态按钮 → 拿当前 jdText + selectedRole → 调 start
  2. 启动后 messages[0] = assistant 的第一问
  3. 用户输入或点 chip → reply
  4. state=DRAFT_READY → 显示 DraftCard
  5. 用户编辑 + 点确认 → saveCard → emit refresh-match + refresh-preview
```

**R5-E 保护**:Panel 不直接 import `AgentSummary` 等 workflow 字段,避免误用;Panel 只用自己 5 个新类型。

#### `App.vue` 改动设计

```text
新增 ref:
  interviewPanelRef = ref<InstanceType<typeof InterviewAgentPanel> | null>(null)
  // 不需要 sessionId 在 App.vue, Panel 自己管

template 改动:
  不用新的 <el-row> 包住整个现有 template。
  当前 App.vue 已经是 stage 驱动:
    - stage === 'select': 现有角色配置左栏 + 素材库概览右栏
    - stage === 'preview': 预览页 + R5-C Agent Workflow 诊断面板
    - stage === 'done': 下载完成页

  推荐插入方式:
    1. 保留现有 stage template 内部结构,不改已有 select 阶段的 16/8 栅格。
    2. 在最外层 app container 内新增桌面 sidecar 容器:
       <div class="app-shell">
         <main class="app-main">
           <!-- 现有 stage-indicator + stage templates 原样移动进这里 -->
         </main>
         <InterviewAgentPanel
           v-if="!isMobile"
           class="interview-sidecar"
           :target-role="selectedRole"
           :jd-text="jdText"
           :external-resume-text="externalResumeText"
           @refresh-match="onRefreshMatch"
           @refresh-preview="onPreview"
         />
       </div>
    3. `.app-main` 使用 `min-width: 0`, `.interview-sidecar` 固定 `width: 380px; flex: 0 0 380px; position: sticky; top: 16px; max-height: calc(100vh - 32px)`。
    4. preview 阶段不把面试官面板塞进既有 Agent Workflow 诊断面板;两者职责不同:一个是用户交互,一个是高级诊断。

mobile 检测:
  用 window.matchMedia('(max-width: 768px)') → isMobile ref
  isMobile=true → 不渲染桌面 sidecar, 渲染右下 FAB + el-drawer 全屏聊天
  isMobile=false → 渲染桌面 sidecar

新方法:
  onRefreshMatch():  调 jdApi.match(currentJdText, selectedRole, externalResumeText.value || undefined) → 更新 jdResult
```

**App.vue diff 硬约束**:**新增代码不超过 200 行**(包含 import / ref / template / methods / comments)。超过则拆组件,reviewer 一票否决。

### 3.4 测试设计

**0 个新单元测试**(当前前端未配置 Vitest/组件测试 runner,本 Phase 不引入新 npm 依赖)。但必须补 1 轮浏览器级 UX smoke:
- 桌面 1280x800: 面试官 sidecar 不挤掉 select 阶段素材库概览,也不覆盖 preview 核心内容
- 移动端 375x812: 只显示 FAB,点击后进入全屏 drawer,输入框/快捷回复/素材卡按钮不溢出
- 保存素材后触发 `refresh-match` 与 `refresh-preview` 两个事件

执行方式:
- Codex/本地有 Playwright 工具时,用浏览器自动化跑 start → reply → draft → save 的 happy path,并保存桌面/移动端截图到 `.planning/round6-a-ux/`
- 没有 Playwright 工具时,按下面 8 项手测,截图同样放 `.planning/round6-a-ux/`

UX 验收用例(spec §13.4 复用,8 项):
1. 粘贴 JD 后启动面试官 → 看到第一问
2. 面试官只选一个缺口 → selectedGap 唯一
3. 连续回答 2-3 次后能生成素材卡
4. 用户点"不知道" → 系统换问法(rephrase_question)
5. 用户编辑素材卡后保存 → materials.json 写入新 project
6. 保存后预览刷新 → previewData 含新 project highlights
7. 关闭 LLM key 后仍可走模板追问(Phase 1 已支持)
8. 移动端聊天栏变为全屏抽屉(el-drawer)

### 3.5 验收命令

```powershell
Set-Location -LiteralPath D:\简历帮\frontend

# 1) 类型检查 — 必须 0 error
npx vue-tsc --noEmit

# 2) 构建 — 必须成功
npm run build

# 3) 启动 dev server + 手测 8 项验收
npm run dev
# 浏览器打开 http://127.0.0.1:5173
# (后端必须先 python backend/main.py)

# 4) 浏览器级 UX smoke:
#    桌面 1280x800 看 sidecar 不挤占素材库概览 / 预览核心信息
#    移动端 375x812 看底部 FAB + 全屏 drawer
#    截图保存到 .planning/round6-a-ux/
```

### 3.6 commit 风格

```text
feat(round6-a): add interview agent chat panel
- frontend/src/components/InterviewAgentPanel.vue (主聊天栏, ~200 行)
- frontend/src/components/InterviewDraftCard.vue (素材卡编辑, ~100 行)
- frontend/src/components/InterviewProgressPills.vue (进度条, ~50 行)
- frontend/src/api/index.ts: +5 TS 类型 + 4 API 函数
- frontend/src/App.vue: +InterviewAgentPanel 挂载点 + mobile FAB (diff < 200 行)
- vue-tsc --noEmit 0 error
- npm run build 成功
- 浏览器级 UX smoke 通过(桌面 + 移动端截图留档)
```

---

## 4. Phase 4 — LLM 抽取增强(延后启动)

### 4.1 启动条件

- Phase 3 上线后至少 1-2 周,用户跑过 5+ 轮真实面试
- 确认规则抽取的"action 切成列表"误切割率高 / "metric regex 漏数字"等问题确实影响体验
- **不与 R5-E prompt rollout 决策捆绑**;即便 R5-F 决定切 winner,Phase 4 仍可独立推进

### 4.2 目标

用 LLM 从用户自由回答里抽取 slot,fallback 到 Phase 1 规则抽取。**不进 PROMPT_VERSIONS**(决策点 D5)。

### 4.3 范围

**新增**:
- `backend/core/interview_prompts.py` — 增补 `SLOT_EXTRACTION_SYSTEM_PROMPT` + `SLOT_EXTRACTION_USER_TEMPLATE` 常量

**修改**:
- `backend/core/interview_agent.py` — `extract_slots` 函数加 LLM 分支(有 key 时)
- 任何 `core/llm_rewriter.py` / `core/agent_workflow.py` — **完全不动**

**LLM 调用方式**:**直接用 stdlib urllib POST `/chat/completions`**(跟 R5-E Phase 3 的 `_call_judge` 同源),不通过 `rewrite_highlights`,不污染 prompt versioning 链路。

**LLM 配置口径**:不得各写一套 env/default 逻辑。Phase 4 在 `interview_agent.py` 内新增 `_resolve_interview_llm_config(...)` 小 helper,字段口径对齐 `scripts/evaluate_agent_workflow.py::_get_llm_eval_config` 与 `scripts/evaluate_prompt_versions.py` 的 judge 配置:
- API key 只读 `LLM_API_KEY` 或显式入参,永不进入返回给前端/报告/trace 的 dict
- base_url 用显式入参 → `LLM_BASE_URL` → `core.llm_rewriter.DEFAULT_BASE_URL`
- model 用显式入参 → `LLM_MODEL` → `core.llm_rewriter.DEFAULT_MODEL`
- 对外可展示的元信息只保留 `llm_enabled` / `llm_model` / `llm_base_url_host`,不展示 path/query/key

### 4.4 关键设计要点

```text
extract_slots 新签名:
  def extract_slots(
      user_message: str,
      current_slot: str,
      session: InterviewSession,
      *,
      llm_enabled: bool = False,    # Phase 4 新增参数
      llm_api_key: str | None = None,
      llm_base_url: str | None = None,
      llm_model: str | None = None,
  ) -> dict:
      """
      Phase 1 行为(llm_enabled=False): 规则抽取, 字节级一致
      Phase 4 行为(llm_enabled=True + 有 key): 调 LLM, schema retry 1 次(沿用 _call_with_retry 模式),
                                                失败 fallback 到规则抽取, 不抛
      """

LLM 路径:
  config = _resolve_interview_llm_config(
      llm_enabled=llm_enabled,
      llm_api_key=llm_api_key,
      llm_base_url=llm_base_url,
      llm_model=llm_model,
  )
  if not config["enabled_for_call"]:
      return extract_slots_by_rules(user_message, current_slot, session)

  system_prompt = SLOT_EXTRACTION_SYSTEM_PROMPT   # 独立常量, 不进 PROMPT_VERSIONS
  user_prompt = SLOT_EXTRACTION_USER_TEMPLATE.format(
      slot=current_slot,
      user_message=user_message,
  )
  payload = {
      "model": config["model"],
      "messages": [
          {"role": "system", "content": system_prompt},
          {"role": "user", "content": user_prompt},
      ],
      "response_format": {"type": "json_object"},
  }
  # 调 stdlib urllib POST config["base_url"].rstrip("/") + "/chat/completions"
  # schema retry 1 次(strict_retry=True), 网络错不 retry
  # 失败 fallback 到规则路径
```

**R5-E 保护**:
- `SLOT_EXTRACTION_SYSTEM_PROMPT` 是**新常量**,不进 `PROMPT_VERSIONS`,不挂 `evaluate_prompt_versions.py`
- 验证:`from core.llm_rewriter import PROMPT_VERSIONS; assert "v6-interview-slot" not in PROMPT_VERSIONS` 跑通
- 不改 `SYSTEM_PROMPT` / `_resolve_prompt_version` / `_select_system_prompt` 任何一行

### 4.5 测试设计

#### 扩展 `test_interview_agent.py`(+5 case)

```text
TestLLMSlotExtraction:
  test_llm_extraction_disabled_falls_back_to_rules     # llm_enabled=False 走规则
  test_llm_extraction_with_key_calls_llm                # mock urllib, 验证调 1 次
  test_llm_extraction_invalid_json_retries_once          # mock 返非 JSON, retry 1 次
  test_llm_extraction_schema_error_falls_back_to_rules  # schema 不符, 不阻断, fallback
  test_llm_extraction_network_error_falls_back_to_rules  # 网络错, 不抛, fallback

TestInterviewPromptRegistry:
  test_slot_extraction_prompt_registered                  # SLOT_EXTRACTION_SYSTEM_PROMPT 是非空 str
  test_slot_extraction_prompt_excludes_jd_full_text       # 模板不含 {jd_text}, 防止泄漏
  test_interview_prompts_not_in_llm_rewriter_registry    # 验证 PROMPT_VERSIONS 不含 interview prompt key
```

### 4.6 验收命令

```powershell
Set-Location -LiteralPath D:\简历帮\backend

# 1) 新增测试
D:\python3.11\python.exe -m pytest tests/test_interview_agent.py -v -k "LLMSlot or InterviewPrompt"

# 2) 全量回归
D:\python3.11\python.exe -m pytest tests/ --collect-only -q

# 3) R5-E 保护再次验证
D:\python3.11\python.exe -c "
from core.llm_rewriter import SYSTEM_PROMPT, _select_system_prompt, PROMPT_VERSIONS, PROMPT_VERSION_BASELINE
assert PROMPT_VERSION_BASELINE == 'v2-baseline'
assert _select_system_prompt(None, None) is SYSTEM_PROMPT
assert 'v6-interview-slot' not in PROMPT_VERSIONS
assert 'v6-interview-draft' not in PROMPT_VERSIONS
print('OK R5-E + Phase 4 boundary stable')
"
```

### 4.7 预期基线

`707 → 715 passed + 0 skipped`(Phase 4 新增 8 测试,707 老测试零回退)。

### 4.8 commit 风格

```text
feat(round6-a): add llm slot extraction to interview agent
- core/interview_prompts.py: add SLOT_EXTRACTION_SYSTEM_PROMPT (独立常量)
- core/interview_agent.py: extract_slots 加 LLM 分支(llm_enabled=False 字节级一致)
- test_interview_agent.py: +8 case (LLM 抽取 + prompt registry)
- LLM prompt 不进 PROMPT_VERSIONS, 不进 evaluate_prompt_versions.py
- 8 个新 pytest 全绿, 707 老测试零回退
```

---

## 5. Phase 5 — eval 脚本与体验指标(延后启动)

### 5.1 启动条件

- Phase 4 上线 + 真实 LLM key 接入 + 用户跑 10+ 轮真实面试
- 有真实数据可以评测"规则 vs LLM 抽取的 schema pass rate / draft completeness / fabrication guard"

### 5.2 目标

新增 `scripts/evaluate_interview_agent.py` — 跑固定 eval set(模拟用户回答 + ground truth slot)对比 Phase 1 规则版 vs Phase 4 LLM 版,输出 markdown 报告(只含聚合指标,不存 user_message / draft_card 原文)。

### 5.3 范围

**新增**:
- `scripts/evaluate_interview_agent.py`(参考 R5-D `evaluate_agent_workflow.py` + R5-E `evaluate_prompt_versions.py` 风格,~200 行)
- `backend/tests/test_interview_eval.py`(~6 case)

**修改**:
- `scripts/install-hooks.ps1` — **不加** interview eval 到 pre-push(spec §12 决策点 D6)

**不修改**:`evaluate_agent_workflow.py` / `evaluate_prompt_versions.py` / 任何 `core/` 模块。

### 5.4 关键设计要点

```text
复用 R5-D / R5-E helper:
  from scripts.evaluate_agent_workflow import (
      load_eval_set, _resolve_eval_mode, _get_llm_eval_config,
      _percentile, _check_pii_safe,
  )

新增:
  EVAL_SET: list[dict] = [
      {
          "name": "process_metric_course",
          "jd_text": "岗位要求: 参与 AI 产品测试与数据质量评估, 能梳理流程、跟进问题闭环, 有量化意识。",
          "role": "test_qa",
          "gap_id": "process_metric",
          "user_messages": [
              "我负责课程项目里的测试反馈整理, 主要是把同学发现的问题统一收集。",
              "我做了一个表格模板, 按问题类型、复现步骤、负责人和状态来记录。",
              "最后小组查问题更快, 返工少了一些, 但没有特别精确的数字。",
              "整理成素材",
          ],
          "expected_slots": {                                     # ground truth
              "responsibility": "测试反馈整理",
              "action": ["做了表格模板", "按问题类型、复现步骤、负责人和状态记录"],
              "result": "小组查问题更快, 返工减少",
          },
          "expected_draft_has_metrics": False,                    # 校验点
      },
      {
          "name": "communication_club",
          "jd_text": "岗位要求: 能跨角色沟通需求, 梳理用户反馈, 推动活动或产品方案落地。",
          "role": "product",
          "gap_id": "communication",
          "user_messages": [
              "社团活动报名时信息很乱, 我负责把报名问题和同学反馈整理出来。",
              "我建了共享文档, 每天同步一次状态, 把问题分成时间、场地、物料三类。",
              "后来分工清楚很多, 负责人能直接看到自己要处理的事项。",
              "整理成素材",
          ],
          "expected_slots": {
              "responsibility": "整理报名问题和同学反馈",
              "action": ["建立共享文档", "按时间、场地、物料分类", "同步状态"],
              "result": "分工更清楚, 负责人能看到待处理事项",
          },
          "expected_draft_has_metrics": False,
      },
      {
          "name": "tech_metric_data",
          "jd_text": "岗位要求: 理解数据标注、质量检查和大模型评估流程, 能描述方法和判断标准。",
          "role": "data_annot",
          "gap_id": "tech_metric",
          "user_messages": [
              "我做过一个数据整理项目, 负责检查文本分类结果是不是符合规则。",
              "我先看样例, 再把容易混淆的类别写成判断标准, 遇到边界情况就记录下来。",
              "最后整理了 20 多条例子给组员参考, 后面大家判断更一致。",
              "整理成素材",
          ],
          "expected_slots": {
              "responsibility": "检查文本分类结果是否符合规则",
              "action": ["查看样例", "整理容易混淆类别的判断标准", "记录边界情况"],
              "result": "整理 20 多条例子供组员参考, 判断更一致",
          },
          "expected_draft_has_metrics": True,
      },
  ]

CLI:
  --mode {offline, live, auto}  # 沿用 R5-D 默认 offline
  --output <path>  # 默认 backend/logs/interview_eval_report.md

指标(每条样本输出):
  schema_pass: bool                     # 槽位是否符合 expected schema
  fallback_used: bool                   # 是否走规则 fallback
  draft_card_completeness: float        # 必填字段填全比例
  fabrication_guard: bool               # 是否包含未确认内容
  latency_ms: int                       # 单轮耗时
  rewrite_changed_count: int            # draft_bullets 与原回答差异数

聚合(全局):
  schema_pass_rate / fallback_rate / avg_completeness /
  fabrication_violations_count / avg_latency_ms / p95_latency_ms

报告章节:
  ## 0、LLM 元信息 (R5-D Phase 2 复用)
  ## 一、Eval set 概览
  ## 二、规则版 vs LLM 版 schema pass 对照
  ## 三、每条样本摘要(只含 slot key + 长度, 不含原文)
  ## 四、Fabrication guard
  ## 五、延迟分布
  ## 六、隐私检查
  ## 七、结论
```

**R5-E 保护**:
- 报告**绝不存** user_message / draft_card 原文(只存 schema_pass / 长度 / 计数)
- `_check_pii_safe` 复用 R5-D placeholder 白名单
- 离线模式不发 HTTP
- 报告路径默认放 `backend/logs/`(在 `.gitignore`),不入库

### 5.5 测试设计

#### `backend/tests/test_interview_eval.py`(新增,~6 case)

```text
TestEvalHelpers:
  test_extract_slots_from_messages_iterates_turns       # 模拟 4 轮回答, 每轮跑 extract_slots
  test_compute_schema_pass_rate_returns_float            # 聚合函数返 [0, 1]
  test_completeness_calculates_required_field_ratio      # completeness 算法
  test_fabrication_guard_detects_unconfirmed_claims      # 简单 keyword 扫描

TestEvalReport:
  test_report_contains_no_user_message_text              # 写报告后 grep 确认无模拟回答原文
  test_report_offline_mode_does_not_call_urlopen         # mock urlopen, assert_not_called
```

### 5.6 验收命令

```powershell
Set-Location -LiteralPath D:\简历帮\backend

# 1) 新增测试
D:\python3.11\python.exe -m pytest tests/test_interview_eval.py -v

# 2) 全量回归
D:\python3.11\python.exe -m pytest tests/ --collect-only -q

# 3) 跑 eval(offline 模式, 不发 HTTP)
D:\python3.11\python.exe scripts/evaluate_interview_agent.py --mode offline
# 报告写到 backend/logs/interview_eval_report.md, 检查不含模拟用户回答原文
Select-String -Path backend/logs/interview_eval_report.md -Pattern "课程项目测试流程" -SimpleMatch
# 应该没匹配
```

### 5.7 预期基线

`715 → 721 passed + 0 skipped`(Phase 5 新增 6 测试,715 老测试零回退)。

### 5.8 commit 风格

```text
chore(round6-a): add interview eval script and offline report
- scripts/evaluate_interview_agent.py (~200 行)
- backend/tests/test_interview_eval.py (6 case)
- backend/logs/interview_eval_report.md (offline report, gitignored)
- 6 个新 pytest 全绿, 715 老测试零回退
- 报告不含 user_message / draft_card 原文
- live mode 不挂 pre-push hook
```

---

## 6. 全局约束:跨 Phase R5-E 保护 checklist

每个 Phase commit 前必跑(写进 commit message body 也行):

```powershell
Set-Location -LiteralPath D:\简历帮\backend

# 1) 老 prompt 字节级稳定
D:\python3.11\python.exe -c "
from core.llm_rewriter import (
    SYSTEM_PROMPT, _select_system_prompt, _resolve_prompt_version,
    PROMPT_VERSIONS, PROMPT_VERSION_BASELINE,
)
assert PROMPT_VERSION_BASELINE == 'v2-baseline'
assert _resolve_prompt_version(None) == 'v2-baseline'
assert _resolve_prompt_version('') == 'v2-baseline'
assert _select_system_prompt(None, None) is SYSTEM_PROMPT
assert _select_system_prompt('v2-baseline', None) is SYSTEM_PROMPT
# 验证 interview prompt 没污染 PROMPT_VERSIONS
for key in PROMPT_VERSIONS:
    assert not key.startswith('v6-interview'), f'leaked interview prompt into PROMPT_VERSIONS: {key}'
print('OK R5-E prompt baseline stable')
"

# 2) 老 workflow 路径字节级稳定
D:\python3.11\python.exe -c "
from api.resume import PreviewRequest
# enable_agent_workflow=False 默认 preview 响应不含 workflow-only 字段
import inspect
src = inspect.getsource(PreviewRequest)
# 这些字段必须在 schema 里
for f in ['enable_agent_workflow', 'enable_external_resume', 'external_resume_text', 'prompt_version']:
    assert f in src, f'missing field: {f}'
# Phase 1 不应改 PreviewRequest 字段顺序
print('OK PreviewRequest field order stable')
"

# 3) 全量测试
D:\python3.11\python.exe -m pytest tests/ -v

# 4) pre-push hook 全绿(已注册的话)
cd ..
powershell -ExecutionPolicy Bypass -File scripts/verify.ps1
```

如果任何一条失败 → 不 commit,先修。

---

## 7. 决策点(plan 启动前需要你确认)

| 编号 | 决策点 | 推荐选项 | 触发时机 |
|---|---|---|---|
| **D1** | materials.json 新 project schema 落点 | (a) 顶层额外字段 + `_interview_meta` 子 dict + `category="interview_captured"` | Phase 2 启动前 |
| **D2** | interview trace 写入策略 | 复用 `agent_trace.jsonl`,写 `workflow="interview"` + 数字 `step` + `tool` enum `{"gap_select", "slot_extract", "draft_card", "save_card"}` | Phase 1 启动前 |
| **D3** | session 存储命名空间隔离 | interview 用独立 dict `core/interview_agent.py::_INTERVIEW_SESSIONS`, 不复用 `core/session.py`, 前缀 `ia_` | Phase 1 启动前 |
| **D4** | save_mode 第二种(`append_to_existing_project`)何时支持 | Phase 2 不支持, 只接受 `append_project`, 留 Phase 6(用户没要就不做) | Phase 2 启动前 |
| **D5** | Phase 4 LLM prompt 是否进 `PROMPT_VERSIONS` | **不进**, 独立 `core/interview_prompts.py` 常量, 不绑 prompt rollout 决策 | Phase 4 启动前 |
| **D6** | Phase 5 eval 脚本是否挂 pre-push | **不挂**, 沿用 R5-D / R5-E 风格手动脚本 | Phase 5 启动前 |

**plan 默认假设前 4 个决策都按推荐选项执行**。如果你想换任何一项,告诉我,我改 plan。

---

## 8. 风险与回退

| 风险 | 触发条件 | 回退方案 |
|---|---|---|
| Phase 1 状态机写复杂, 测试覆盖不足 | Phase 1 收尾测试覆盖 < 80% 核心状态转移 | 加 case 到 ≥10, 拆 `InterviewSession` 内部 dataclass, 重写 apply_action |
| Phase 2 写库破坏 materials.json | 真实文件被测试/冒烟误写,或 round-trip 自检失败 | 测试改为临时 `materials_path`;生产路径保留原子写 tmp+os.replace;若真实文件已污染,先从 `_private_backup.json` 或 git diff 手工恢复 |
| Phase 3 App.vue diff 超 200 行 | review 时数行数 | 把 chat panel 提到独立 `<InterviewLayout>` 组件, App.vue 只挂 layout |
| Phase 4 LLM 抽取幻觉率高 | eval schema_pass < 70% | 不切默认, 保留规则版为 `extract_slots` 主路径, LLM 作为 opt-in |
| Phase 5 报告意外含 PII | grep 抓到 user_message | 修复 `_check_pii_safe` placeholder 白名单 + 加 redactor 函数 |

---

## 9. 收尾 checklist(round 完成时由 orchestrator 跑)

```text
[ ] 5 个 Phase 全部 commit 落地(可拆 PR,但每 Phase 一个独立 commit)
[ ] 全量 pytest 跑通, baseline 从 683 → 721(每个 Phase 收尾时更新 README/AGENTS/ROADMAP)
[ ] R5-E 保护 checklist 全部通过(SYSTEM_PROMPT / PROMPT_VERSIONS / 老路径字节级)
[ ] pre-push hook 仍跑默认 offline 路径, 不挂 live eval
[ ] README 顶部"当前状态"段更新到 R6-A
[ ] README "核心能力"段加"简历面试官(Phase X MVP)"一行
[ ] README scripts 列表加 evaluate_interview_agent.py
[ ] AGENTS.md Testing instructions 加 R6-A 测试锁点段(每个 Phase 收尾时写一段)
[ ] ROADMAP 顶部快照加 R6-A 5 phase 段, 活跃基线更新到 721
[ ] ROADMAP "最近 7 commit" 同步到 R6-A 系列
[ ] spec/round6-a-jd-interview-agent-spec.md 状态行从"📝 待评审后拆 implementation plan"改为"✅ 已实施"或保持"📝"看是否全部 phase 收尾
```

---

## 10. plan commit 风格(round 收尾时由 orchestrator 写)

```text
docs(round6-a): add implementation plan

- 5 phase 拆分(Phase 1 后端 MVP → Phase 5 eval)
- 4 个 spec 硬冲突的 plan 落地策略(冲突 1-4)
- 每个 phase 列出文件改动 + 测试设计 + 验收命令 + commit 风格
- 6 个决策点列在 §7, 前 4 个按推荐选项默认执行
- R5-E 保护 checklist 跨 phase 复用
- baseline 估算: 683 → 721(+38 测试)
- 不改 spec 文字(spec 文件不动)
```

---

## 附录 A:Phase 文件改动汇总表

| Phase | 新增文件 | 修改文件 | 新增测试 | baseline 增量 |
|---|---|---|---|---|
| Phase 1 | `core/interview_prompts.py` / `core/interview_agent.py` / `api/interview.py` / `tests/test_interview_agent.py` / `tests/test_interview_api.py` | `main.py`(1 行)| +17 | 683 → 700 |
| Phase 2 | (无新文件) | `core/interview_agent.py`(+save_card + material IO helper) / `api/interview.py`(+save-card 端点) / `data/materials.json`(仅生产运行期追加,测试与 git diff 不改)| +7 | 700 → 707 |
| Phase 3 | `frontend/src/components/InterviewAgentPanel.vue` / `InterviewDraftCard.vue` / `InterviewProgressPills.vue` | `frontend/src/api/index.ts` / `App.vue`(<200 行 diff)| 0 单元测试 + 1 轮浏览器 UX smoke | 707 不变(只前端) |
| Phase 4 | (无新文件) | `core/interview_prompts.py`(+LLM prompt) / `core/interview_agent.py`(+LLM 分支)| +8 | 707 → 715 |
| Phase 5 | `scripts/evaluate_interview_agent.py` / `tests/test_interview_eval.py` | (无) | +6 | 715 → 721 |

## 附录 B:不触碰清单(round 启动前 archive 一次, commit 后 diff 核对)

```text
不应被修改:
  - backend/core/llm_rewriter.py          (R5-E byte-stable)
  - backend/core/agent_workflow.py        (R5-A/B/C byte-stable, 不为 Round 6-A import / move / re-export 内部 helper)
  - backend/core/agent_tools.py           (R5-A/B byte-stable)
  - backend/core/evidence.py              (R5-A Phase 3 byte-stable)
  - backend/core/jd_parser.py             (R3.5+ / R3-G byte-stable)
  - backend/core/session.py               (R4-M byte-stable)
  - backend/core/tool_schema.py           (R5-B Phase 2A byte-stable)
  - backend/api/resume.py                 (R5-E field order byte-stable)
  - backend/api/materials.py              (R3-G byte-stable, Phase 2 不 import 它的私有 _load/_save)
  - backend/api/jd.py                     (R3-G / R5-C byte-stable)
  - backend/data/materials.json structure (生产运行期只追加 project 项;测试/冒烟/commit diff 不直接改真实文件)
  - frontend/src/components/ResumeUploader.vue  (R3-G byte-stable)
  - scripts/evaluate_agent_workflow.py    (R5-D byte-stable)
  - scripts/evaluate_prompt_versions.py   (R5-E byte-stable)
  - scripts/replay_agent_trace.py         (R5-A/C byte-stable)
  - scripts/build_v4.py / score_intern_match.py / match_golden_targets.py
  - scripts/install-hooks.ps1             (Phase 1-4 不动, Phase 5 才讨论)
  - .planning/面试讲解/*                  (spec §10 决策点 D7: 完全不动)
  - .planning/agent-architecture-audit/*  (历史审计, 不动)
  - AI岗位JD库_v4_intern.json             (88 份 JD 主库, 不动)
  - 任何 frontend/node_modules / package-lock.json
  - 任何 backend/requirements.txt         (不引入新依赖)
  - 任何 .harness/docs/round6-a-jd-interview-agent-spec.md (plan 不改 spec 文字)
```

任何 diff 里出现上面文件的改动 → **立即 revert + 排查为什么被改**。
