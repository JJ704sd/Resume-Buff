"""
Round 6-A Phase 1: interview_agent 提示词 / 槽位 / 缺口配置

设计原则(plan §1.3):
  - **完全无副作用** 纯常量模块, 顶层不允许出现 import 副作用
  - **不** import core.llm_rewriter / core.agent_workflow / core.agent_tools
    (R5-E 保护: import 它们会破坏字节级稳定)
  - 所有变量都是 dict / tuple / str / int, 没有 class, 没有外部 IO

公开 API:
  - SLOT_NAMES:                tuple[str, ...]  全部槽位名
  - GAP_SUGGESTED_SLOTS:       dict[str, tuple[str, ...]]  gap_id → 推荐追问顺序
  - GAP_LABELS:                dict[str, str]   gap_id → 人话标签
  - GAP_REASONS:               dict[str, str]   gap_id → 缺口解释
  - GAP_KEYWORD_RULES:         dict[str, tuple[str, ...]]  gap_id → 触发关键词
  - GAP_CANDIDATES_FIELDS:     tuple[str, ...]  GapCandidate 字段名(给 dataclass 用)
  - QUESTION_TEMPLATES:        dict[tuple[str, str], str]  (gap_id, slot) → 问题模板
  - QUICK_REPLIES_BY_SLOT:     dict[str, tuple[str, ...]]  slot → 快捷回复
  - CAN_DRAFT_CONDITIONS:      tuple[tuple[str, ...], ...]  收束组合
  - INTERVIEWABLE_GAP_IDS:     tuple[str, ...]  可追问白名单
  - NON_INTERVIEWABLE_GAP_IDS: tuple[str, ...]  不该追问白名单(扣 5 分)
  - MAX_TURNS_PER_GAP:         int              单缺口最大轮数
  - INTERVIEW_MAX_MESSAGE_LEN: int              user_message 上限
  - INTERVIEW_MAX_DRAFT_LEN:   int              draft_card 上限
  - INTERVIEW_MAX_SESSION_ID_LEN: int           session_id 上限
  - INTERVIEW_MAX_JD_TEXT_LEN: int              jd_text 上限(沿用 api/jd.py)
"""
# ----------------------------------------------------------------------
# 槽位名(全部合法槽位)
# ----------------------------------------------------------------------
SLOT_NAMES: tuple[str, ...] = (
    "background",
    "responsibility",
    "action",
    "method",
    "difficulty",
    "result",
    "metric",
)


# ----------------------------------------------------------------------
# Gap 维度配置
# ----------------------------------------------------------------------
GAP_SUGGESTED_SLOTS: dict[str, tuple[str, ...]] = {
    "process_metric":  ("responsibility", "action", "result", "metric"),
    "tech_metric":     ("background", "responsibility", "action", "method", "result"),
    "communication":   ("background", "action", "method", "result"),
    "domain_x":        ("responsibility", "action", "method", "difficulty", "result"),
}


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


# Gap 关键词规则: 命中 parse_jd 的 raw_keywords / match_score.missing_keywords
# 即加分(用于缺口选择的优先级打分)
GAP_KEYWORD_RULES: dict[str, tuple[str, ...]] = {
    "process_metric":  ("流程", "效率", "协作", "数据", "覆盖", "闭环", "标准化", "梳理"),
    "tech_metric":     ("Python", "LLM", "算法", "评测", "建模", "评估", "推理", "标注", "深度学习"),
    "communication":   ("沟通", "协作", "推动", "复盘", "对接", "拉齐", "对齐", "协调"),
    "domain_x":        ("医疗", "心电", "ECG", "NLP"),
}


# GapCandidate 字段名(供 dataclass 字段校验, 也是测试 gap 结构的 source of truth)
GAP_CANDIDATES_FIELDS: tuple[str, ...] = (
    "gap_id", "label", "reason", "keywords", "source", "tier",
    "priority", "suggested_slots",
)


# ----------------------------------------------------------------------
# 问题模板: (gap_id, slot) → 问题文本
# ----------------------------------------------------------------------
QUESTION_TEMPLATES: dict[tuple[str, str], str] = {
    # process_metric
    ("process_metric", "responsibility"): (
        "你当时主要负责哪一块? "
        "可以从「分析、设计、执行、协调、测试」里选一个最接近的。"
    ),
    ("process_metric", "action"): (
        "你具体做了什么动作? "
        "先不用写得正式, 像讲给面试官听一样说就行。"
    ),
    ("process_metric", "result"): (
        "最后带来了什么变化? "
        "比如减少了返工、让协作更顺、覆盖更多场景。"
    ),
    ("process_metric", "metric"): (
        "有没有数字可以支持? "
        "比如人数、次数、时长、准确率、效率、覆盖范围。没有也可以直接说没有。"
    ),
    # tech_metric
    ("tech_metric", "background"): (
        "这个经历发生在什么项目或场景里? 可以先说一句背景。"
    ),
    ("tech_metric", "responsibility"): (
        "你在里面承担的是分析、开发、测试、协调,还是别的角色?"
    ),
    ("tech_metric", "action"): (
        "你最能体现技术方法的一步是什么? "
        "例如建模、标注规则、评估、自动化、数据处理。"
    ),
    ("tech_metric", "method"): (
        "当时用了什么方法、工具或判断标准? "
        "不需要很专业,说清楚你怎么做的就行。"
    ),
    ("tech_metric", "result"): (
        "这件事最后带来了什么结果? "
        "比如一致性提升、出错率下降、效率提升、流程变快。"
    ),
    # communication
    ("communication", "background"): (
        "这段经历里有没有需要和别人协作、沟通或对齐的场景?"
    ),
    ("communication", "action"): (
        "你具体怎么推动沟通? "
        "比如整理信息、拉齐目标、分工、跟进、复盘。"
    ),
    ("communication", "method"): (
        "你用了什么方式让事情推进? "
        "例如会议、文档、表格、原型、流程图或检查清单。"
    ),
    ("communication", "result"): (
        "沟通之后有什么变化? "
        "比如减少误解、缩短周期、让交付更稳定。"
    ),
    # domain_x
    ("domain_x", "responsibility"): (
        "这个经历和目标岗位最相关的一块是什么? 你负责了哪部分?"
    ),
    ("domain_x", "action"): (
        "你做了哪些能体现这个领域理解的动作?"
    ),
    ("domain_x", "method"): (
        "你当时依据了什么规则、业务逻辑或用户需求来判断?"
    ),
    ("domain_x", "difficulty"): (
        "这个场景里最难、最卡或最容易出错的点是什么?"
    ),
    ("domain_x", "result"): (
        "最后你解决了什么? 带来了什么变化?"
    ),
}


# ----------------------------------------------------------------------
# 快捷回复: 按 slot 提供 4-6 个 chip
# ----------------------------------------------------------------------
QUICK_REPLIES_BY_SLOT: dict[str, tuple[str, ...]] = {
    "responsibility": (
        "我负责执行", "我负责分析", "我负责协调",
        "不确定", "换个问法", "跳过这个问题",
    ),
    "action": (
        "执行了一个动作", "设计了一个方案", "推动了一件事",
        "想不起来", "换个问法", "跳过这个问题",
    ),
    "background": (
        "课程项目", "社团活动", "比赛经历", "实习/兼职",
        "换个问法", "跳过这个问题",
    ),
    "method": (
        "用了表格/文档", "用了工具", "按流程推进", "没有固定方法",
        "换个问法", "跳过这个问题",
    ),
    "difficulty": (
        "时间紧", "信息不清楚", "协作难", "技术不熟",
        "换个问法", "跳过这个问题",
    ),
    "result": (
        "让流程变快", "减少了错误", "让协作更顺", "没有明显结果",
        "换个问法", "跳过这个问题",
    ),
    "metric": (
        "大概有", "没有数据", "想不起来",
        "换个问法", "跳过这个问题",
    ),
}


# ----------------------------------------------------------------------
# 收束条件: 任一组合满足 → can_draft=True
# ----------------------------------------------------------------------
CAN_DRAFT_CONDITIONS: tuple[tuple[str, ...], ...] = (
    ("background", "action", "result"),
    ("responsibility", "action", "metric"),
    ("responsibility", "action", "result"),
)


# ----------------------------------------------------------------------
# 缺口白名单
# ----------------------------------------------------------------------
INTERVIEWABLE_GAP_IDS: tuple[str, ...] = (
    "process_metric",
    "tech_metric",
    "communication",
    "domain_x",
)


# 不该追问的 gap(spec §5.4: 学历 / 年限 / 证书 / 硬技能 / 无相邻证据)
# 命中这些 gap_id 的候选在 select_gap 时统一 -5 分,即使 tier=required 也无法入选
NON_INTERVIEWABLE_GAP_IDS: tuple[str, ...] = (
    "degree_required",
    "years_required",
    "cert_required",
    "hard_skill",
    "no_adjacent_evidence",
)


# ----------------------------------------------------------------------
# 状态机 / 输入上限常量
# ----------------------------------------------------------------------
MAX_TURNS_PER_GAP: int = 3
MAX_CONSECUTIVE_SKIPS: int = 2  # 连续 skip 次数上限 → 触发 draft 收束

INTERVIEW_MAX_MESSAGE_LEN: int = 2_000
INTERVIEW_MAX_DRAFT_LEN: int = 20_000
INTERVIEW_MAX_SESSION_ID_LEN: int = 64
INTERVIEW_MAX_JD_TEXT_LEN: int = 50_000  # 沿用 api/jd.py 的 _MAX_TEXT_LEN


# ----------------------------------------------------------------------
# trace 写入 schema 字段名(供 interview_agent 写 trace 时复用)
# ----------------------------------------------------------------------
INTERVIEW_TRACE_TOOLS: tuple[str, ...] = (
    "gap_select",
    "slot_extract",
    "draft_card",
)