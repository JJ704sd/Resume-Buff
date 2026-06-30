"""
Round 6-A Phase 1+2 + R6-B Phase 2+4: interview agent API

端点:
  - POST /api/interview/start      创建 session + 选缺口 + 返第一问
  - POST /api/interview/reply      answer / skip / rephrase / switch_gap / draft_now
  - POST /api/interview/draft      强制生成 draft_card(can_draft=True 才返)
  - POST /api/interview/save-card  把编辑过的 draft_card 追加为新 project(Phase 2)

R6-B Phase 2 增量(spec §5.3):
  - StartRequest 增加 enable_interview_llm: bool = False
  - StartResponse 增加 interview_mode + mode_warning optional 字段
  - create_session 接受 enable_interview_llm, 决定 session.interview_mode + mode_warning
  - ReplyResponse 增加 extraction_summary + question_plan optional 字段
  - ReplyRequest **不重复**传开关, reply 沿用 session.interview_mode
  - 隐私边界: API response 不含 API key / prompt / source_span / user_message 明文

R6-B Phase 4 增量(spec §7):
  - /draft endpoint 在 build_draft_card 之后调 interview_verifier, 把
    verification(5 数字) + confidence_notes(list[str]) 注入到 card dict
    → DraftResponse.draft_card 含 verification + confidence_notes(前端显示 / 风险提示用)
  - /save-card 端点不重复做 verification, 走 interview_agent.save_card
    把 session.verification_summary 写入 _interview_meta.verification 摘要
    (4 数字 + warnings + extraction_mode, **不**含 draft_card / user_message / source_span 明文)
  - 老前端不消费新字段也不报错(Pydantic 接受任意 dict)

约束(plan §1.3 / §2.3 + spec §5.3):
  - 不 import core.llm_rewriter / core.agent_workflow
  - 不挂到 resume_router,独立 router
  - 错误码对齐 plan:
      422  jd_text 空 / > 50k / target_role 不在 ENABLED_ROLES / message > 2000
           edited_card 缺字段 / draft_bullets 空 / 超长
      404  session_id 不存在
      400  action 不在合法 enum / action=draft_now 但 can_draft=False
           save_mode != "append_project"
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from core.generator import ENABLED_ROLES, load_materials
from core.interview_agent import (
    ActionType,
    InterviewState,
    apply_action,
    build_draft_card,
    can_draft,
    create_session,
    get_session,
    next_question,
    save_card,
)
from core.interview_prompts import (
    INTERVIEW_MAX_JD_TEXT_LEN,
    INTERVIEW_MAX_MESSAGE_LEN,
)


router = APIRouter()


# ----------------------------------------------------------------------
# Pydantic 模型
# ----------------------------------------------------------------------
class StartRequest(BaseModel):
    target_role: str = Field(..., description="6 个 role id 之一")
    jd_text: str = Field(..., description="JD 全文, 50k 字符上限")
    # R6-B Phase 2(spec §5.3): 智能抽取开关
    # False(默认)→ 老路径字节级一致, rules 模式
    # True + LLM_API_KEY 在 env → llm_assisted 模式
    # True + 无 key → 仍返 rules 模式 + mode_warning(spec §5.1)
    enable_interview_llm: bool = Field(
        default=False,
        description="是否启用智能抽取; 失败自动回退 rules 模式, 不抛错",
    )


class _GapDict(BaseModel):
    gap_id: str
    label: str
    reason: str
    keywords: list[str] = []
    tier: str
    priority: float
    suggested_slots: list[str] = []


class _MessageDict(BaseModel):
    slot: str
    text: str
    quick_replies: list[str] = []


class _ProgressDict(BaseModel):
    captured: dict[str, bool]
    turn_count: int
    can_draft: bool


class StartResponse(BaseModel):
    session_id: str
    state: str
    selected_gap: dict[str, Any]
    message: dict[str, Any] | None
    progress: dict[str, Any]
    # R6-B Phase 2(spec §5.3): 暴露 mode 给前端显示
    # 旧前端不消费也不报错(spec §5.3 "所有新增字段均为 optional 或有默认值")
    interview_mode: str = Field(
        default="rules",
        description='抽取模式: "rules" | "llm_assisted"',
    )
    mode_warning: str | None = Field(
        default=None,
        description="用户可见模式说明(智能抽取不可用时给出原因摘要)",
    )


class ReplyRequest(BaseModel):
    session_id: str = Field(..., description="start 返的 session_id")
    message: str = Field(default="", description="用户回答(answer 时必填)")
    action: str = Field(
        ..., description="answer / skip_question / rephrase_question / switch_gap / draft_now",
    )


class ReplyResponse(BaseModel):
    state: str
    message: dict[str, Any] | None
    captured_delta: dict[str, Any] | None
    progress: dict[str, Any]
    can_draft: bool
    force_draft: bool
    # R6-B Phase 2(spec §5.3): 本轮抽取摘要 + 下一问策略占位
    # 老前端不消费也不报错; 旧路径(extraction_summary=None)字节级一致
    extraction_summary: dict[str, Any] | None = Field(
        default=None,
        description=(
            "本轮抽取摘要: extractor / fallback_used / captured_slots / "
            "low_confidence_slots. 非 answer 动作为 None."
        ),
    )
    question_plan: dict[str, Any] | None = Field(
        default=None,
        description=(
            "下一问策略占位(Phase 2: slot + reason_code + low_confidence_slots; "
            "Phase 3 由 interview_policy 填充)"
        ),
    )


class DraftRequest(BaseModel):
    session_id: str


class DraftResponse(BaseModel):
    state: str
    draft_card: dict[str, Any]


class SaveRequest(BaseModel):
    """Phase 2 save-card 入参(plan §2.3)"""
    session_id: str = Field(..., description="start 返的 session_id")
    edited_card: dict[str, Any] = Field(
        ..., description="前端编辑过的 draft_card (title/responsibility/actions/draft_bullets 必填)",
    )
    save_mode: str = Field(
        ..., description='Phase 2 只接受 "append_project"',
    )


class SaveResponse(BaseModel):
    """Phase 2 save-card 返回(plan §2.3 步骤 10)"""
    ok: bool
    material_ref: dict[str, Any]
    refresh: dict[str, Any]
    preview_score_delta: dict[str, Any] | None = None


# ----------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------
def _validate_start_input(target_role: str, jd_text: str) -> None:
    """422 if 空 / 超长 / 未知 role。"""
    if not jd_text or not jd_text.strip():
        raise HTTPException(status_code=422, detail="jd_text 不能为空")
    if len(jd_text) > INTERVIEW_MAX_JD_TEXT_LEN:
        raise HTTPException(
            status_code=422,
            detail=f"jd_text 长度 {len(jd_text)} 超过上限 {INTERVIEW_MAX_JD_TEXT_LEN}",
        )
    if target_role not in ENABLED_ROLES:
        raise HTTPException(
            status_code=422,
            detail=(
                f"target_role {target_role!r} 未启用,"
                f"当前已启用: {sorted(ENABLED_ROLES)}"
            ),
        )


def _validate_message(message: str) -> None:
    if len(message or "") > INTERVIEW_MAX_MESSAGE_LEN:
        raise HTTPException(
            status_code=422,
            detail=f"message 长度 {len(message)} 超过上限 {INTERVIEW_MAX_MESSAGE_LEN}",
        )


def _parse_action(action_str: str) -> ActionType:
    try:
        return ActionType(action_str)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"action {action_str!r} 不在合法 enum: {[a.value for a in ActionType]}",
        )


def _gap_to_dict(gap) -> dict[str, Any]:
    return {
        "gap_id": gap.gap_id,
        "label": gap.label,
        "reason": gap.reason,
        "keywords": list(gap.keywords),
        "tier": gap.tier,
        "priority": float(gap.priority),
        "suggested_slots": list(gap.suggested_slots),
    }


# ----------------------------------------------------------------------
# 端点 1: POST /api/interview/start
# ----------------------------------------------------------------------
@router.post("/start", response_model=StartResponse)
def interview_start(req: StartRequest):
    """
    创建 interview session:
      - 校验 jd_text + target_role
      - create_session: parse_jd + match_score + 选缺口
      - 返 session_id + selected_gap + 第一问

    R6-B Phase 2(spec §5.3):
      - 接受 enable_interview_llm 开关
      - 返 interview_mode + mode_warning(给前端显示)
      - 不传 enable=False 时与 R6-A Phase 1 字节级一致
    """
    _validate_start_input(req.target_role, req.jd_text)
    mats = load_materials()
    sess = create_session(
        req.target_role, req.jd_text, mats,
        enable_interview_llm=req.enable_interview_llm,
    )
    first_q = next_question(sess)
    return StartResponse(
        session_id=sess.session_id,
        state=sess.state.value,
        selected_gap=_gap_to_dict(sess.selected_gap) if sess.selected_gap else {},
        message=first_q,
        progress={
            "captured": {slot: False for slot in (
                "background", "responsibility", "action", "method",
                "difficulty", "result", "metric",
            )},
            "turn_count": sess.turn_count,
            "can_draft": can_draft(sess),
        },
        # R6-B Phase 2(spec §5.3): 把 session mode / warning 暴露给前端
        interview_mode=sess.interview_mode,
        mode_warning=sess.mode_warning,
    )


# ----------------------------------------------------------------------
# 端点 2: POST /api/interview/reply
# ----------------------------------------------------------------------
@router.post("/reply", response_model=ReplyResponse)
def interview_reply(req: ReplyRequest):
    """
    用户回复 / 动作:
      - answer: 填槽 + 下一问 (or draft)
      - skip_question: skip_count + 1, 连续 2 次强制 draft
      - rephrase_question: 同一 slot 换 prompt
      - switch_gap: 重置 slots / turn / skip, 选新 gap
      - draft_now: 强制 draft(can_draft=False → 400)

    R6-B Phase 2(spec §5.3):
      - ReplyRequest **不**重复传 enable_interview_llm, 沿用 session.interview_mode
      - ReplyResponse 增加 extraction_summary / question_plan optional 字段
    """
    sess = get_session(req.session_id)
    if sess is None:
        raise HTTPException(
            status_code=404,
            detail=f"session_id {req.session_id!r} 不存在",
        )

    _validate_message(req.message)
    action = _parse_action(req.action)

    try:
        new_sess, resp = apply_action(sess, action, req.message or None)
    except ValueError as e:
        # draft_now 但 can_draft=False 等
        raise HTTPException(status_code=400, detail=str(e))

    return ReplyResponse(
        state=new_sess.state.value,
        message=resp.get("message"),
        captured_delta=resp.get("captured_delta"),
        progress=resp.get("progress", {}),
        can_draft=resp.get("can_draft", False),
        force_draft=resp.get("force_draft", False),
        # R6-B Phase 2(spec §5.3): 抽取摘要 + 下一问策略
        # 非 answer 动作为 None; 老前端不消费也不报错
        extraction_summary=resp.get("extraction_summary"),
        question_plan=resp.get("question_plan"),
    )


# ----------------------------------------------------------------------
# 端点 3: POST /api/interview/draft
# ----------------------------------------------------------------------
@router.post("/draft", response_model=DraftResponse)
def interview_draft(req: DraftRequest):
    """
    强制生成 draft_card。
    can_draft=False → 400。

    R6-B Phase 4(spec §7): build_draft_card 之后调 verify_draft_card,
    把 verification(5 字段) + confidence_notes(list[str]) 注入到 card dict,
    并缓存到 sess.verification_summary 供 /save-card 写 _interview_meta.verification。

    隐私边界: API response 不含 user_message / source_span / API key / draft_card 原文;
    verification.warnings 只列 slot 名 + bullet 索引 + 前 30 字摘要(spec §7 锁)。
    """
    sess = get_session(req.session_id)
    if sess is None:
        raise HTTPException(
            status_code=404,
            detail=f"session_id {req.session_id!r} 不存在",
        )

    if not can_draft(sess):
        raise HTTPException(
            status_code=400,
            detail="can_draft=False, 槽位未填齐, 请继续追问或补充回答",
        )

    card = build_draft_card(sess)
    sess.draft_card = card

    # R6-B Phase 4(spec §7): 挂 verifier 摘要
    from core.interview_verifier import (
        compute_confidence_notes,
        verify_draft_card,
    )

    verification = verify_draft_card(card, sess)
    confidence_notes = compute_confidence_notes(sess)
    sess.verification_summary = verification
    if isinstance(card, dict):
        card["verification"] = verification
        card["confidence_notes"] = confidence_notes

    # /draft 成功后系统已进入"待确认素材卡"状态, 跟响应语义保持一致。
    # 之前 `sess.state = sess.state` 是 no-op, ASKING 状态下调 /draft 会
    # 返回 state="ASKING", 与"已生成 draft_card"语义不一致 — 前端素材卡
    # 视图依赖 state==DRAFT_READY, 会拿不到卡片。
    sess.state = InterviewState.DRAFT_READY
    return DraftResponse(
        state=sess.state.value,
        draft_card=card,
    )


# ----------------------------------------------------------------------
# 端点 4 (Phase 2): POST /api/interview/save-card
# ----------------------------------------------------------------------
@router.post("/save-card", response_model=SaveResponse)
def interview_save_card(req: SaveRequest):
    """
    把编辑过的 draft_card 追加为新 project 到 materials.json(plan §2.3)。

    错误码:
      404  session_id 不存在
      400  save_mode != "append_project" (Phase 2 暂不支持 append_to_existing_project, 决策点 D4)
      422  edited_card 缺字段 / draft_bullets 空 / 单条 > 200 字

    隐私边界(spec §12):
      - trace 只存 input_size / output_size 字节数, 不存 edited_card 原文
      - 真实 materials.json 不应在测试 / 冒烟时被改 — 用 DEFAULT_MATERIALS_PATH 走默认路径,
        测试必须 monkeypatch DEFAULT_MATERIALS_PATH 指向 tmp_path
    """
    sess = get_session(req.session_id)
    if sess is None:
        raise HTTPException(
            status_code=404,
            detail=f"session_id {req.session_id!r} 不存在",
        )

    try:
        result = save_card(sess, req.edited_card, req.save_mode)
    except ValueError as e:
        # save_mode 错 → 400; edited_card 字段错 → 422
        msg = str(e)
        if "save_mode" in msg:
            raise HTTPException(status_code=400, detail=msg)
        raise HTTPException(status_code=422, detail=msg)

    return SaveResponse(
        ok=result.get("ok", True),
        material_ref=result.get("material_ref", {}),
        refresh=result.get("refresh", {}),
        preview_score_delta=result.get("preview_score_delta"),
    )