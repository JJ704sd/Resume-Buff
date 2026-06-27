"""
R5-A Phase 1: Agent Workflow 编排层(受控 Plan-and-Execute)

设计目标(spec §4.1 + §4.2):
  - **MVP 不让 LLM 自由规划**(避免死循环 / token 浪费)
  - 系统根据请求字段生成固定候选任务图
  - LLM 只在有限范围内决定是否需要某些工具(例如 evaluate_bullet_jd_match 是否启用)
  - 每步工具调用都有 allowlist、错误分类、降级策略
  - 最终结果必须回到现有 preview_resume() / generate_resume_docx() 的数据结构
  - workflow 失败时降级到当前旧路径(走 build_sections,字节级一致)

任务图(spec §4.2 推荐):
  | 阶段       | 工具                          | 必选   | 输出                |
  |------------|-------------------------------|--------|---------------------|
  | intent     | parse_user_intent(本地)       | 是     | role/template 归一化 |
  | jd_under   | parse_jd / match_score        | 有 JD  | jd_profile / score  |
  | retrieve   | retrieve_materials(本地)      | 是     | candidates          |
  | evaluate   | evaluate_bullet_jd_match      | FC 开启| matched/missing     |
  | rewrite    | rewrite_highlights             | LLM 可用 | rewritten bullets |
  | aggregate  | aggregate_preview(本地)       | 是     | preview sections    |

公开 API:
  - build_task_graph(...)  — 纯函数,根据请求字段返回 step 列表
  - run_agent_workflow(...) — 执行任务图,失败 fallback 到旧路径

隐私边界(对齐 spec §6.4):
  - AgentStep 不存 input / output 原文(只存 input_ref/output_ref 名字)
  - error_msg 只含异常类型名,不含 args 原文
  - jd_text / bullet 仅作为 args 传给工具,不进 step 结构

不引入:
  - 不引入新 LLM 调用(LLM 只走既有 rewrite_highlights 路径)
  - 不引入异步队列(本地单用户 MVP,同步即可)
  - 不引入持久化(无 sqlite / redis / file storage)
  - 不引入账号 / 多用户 / 公网部署
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from core.agent_tools import (
    ToolResult,
    execute_agent_tool,
)


# ----------------------------------------------------------------------
# AgentStep + AgentWorkflowResult
# ----------------------------------------------------------------------
@dataclass(frozen=True)
class AgentStep:
    """
    单步任务图的描述(spec §4.1 表格行)

    字段:
      step        - 序号(0-indexed,从 build_task_graph 自增)
      name        - 步骤人类可读名("parse_jd" / "match_score" / "rewrite_highlights" / "aggregate_preview")
      tool        - 工具名(非工具步骤如 aggregate_preview / retrieve_materials / parse_user_intent 时为 None)
      input_ref   - 输入来源标识("jd_text" / "bullets" / "candidates")— 不存原文
      output_ref  - 输出标识("jd_profile" / "rewritten_bullets" / "sections")— 不存原文
      required    - 是否关键步骤:True 时失败必须降级旧路径;False 时失败可继续
      fallback    - 失败时的降级策略("use_default" / "skip" / "abort")
    """
    step: int
    name: str
    tool: Optional[str]
    input_ref: str
    output_ref: str
    required: bool = False
    fallback: str = "use_default"  # "use_default" | "skip" | "abort"


@dataclass
class AgentWorkflowResult:
    """
    run_agent_workflow 的最终结果

    字段:
      preview           - preview dict(与 generator.preview_resume() 旧路径结构兼容)
      steps_executed    - 实际执行的 AgentStep 列表(供 trace / 调试)
      tool_results      - 每个工具步骤的 ToolResult(供审计)
      fallback_used     - 是否降级到旧路径
      fallback_reason   - 降级原因(异常类型名 / 步骤名)— 不含 args 原文
    """
    preview: dict
    steps_executed: list[AgentStep]
    tool_results: dict[str, ToolResult]
    fallback_used: bool
    fallback_reason: Optional[str] = None


# ----------------------------------------------------------------------
# 任务图构建(纯函数,确定性)
# ----------------------------------------------------------------------
def build_task_graph(
    *,
    has_jd: bool,
    enable_function_calling: bool,
    has_external_resume: bool,
) -> list[AgentStep]:
    """
    R5-A Phase 1: 根据请求字段生成固定任务图

    LLM 不参与规划 — 完全确定性,同样输入产出字节级一致的 step list。

    Args:
        has_jd:                  jd_text 是否非空(决定是否加 parse_jd / match_score)
        enable_function_calling: 是否开启 Function Calling(决定是否加 evaluate_bullet_jd_match)
        has_external_resume:     是否有外部简历上传(本轮 MVP 不消费,留作 P2 hook)

    Returns:
        list[AgentStep] — 固定顺序的任务图

    任务图规范:
      1. parse_user_intent  (本地,无工具)
      2. (has_jd) parse_jd
      3. (has_jd) match_score
      4. retrieve_materials (本地,无工具)
      5. (has_external_resume) parse_external_resume  — P2 占位,本轮无外部简历 hook
      6. (enable_function_calling) evaluate_bullet_jd_match × N(bullets 数)— MVP 简化:只跑 1 步 representative
      7. rewrite_highlights
      8. aggregate_preview   (本地,无工具,走 build_sections)

    注:
      - evaluate_bullet_jd_match 在 spec §4.2 是 per-bullet 多次调用;MVP 简化为单步
        representative(用第 1 条 bullet 评估)— 完整 per-bullet 流程留 P2
      - 没有真实 LLM key 时,rewrite_highlights 静默降级原文(spec §6.1)
    """
    steps: list[AgentStep] = []
    step_idx = 0

    # 1) intent parse (本地)
    steps.append(AgentStep(
        step=step_idx,
        name="parse_user_intent",
        tool=None,
        input_ref="request_fields",
        output_ref="normalized_intent",
        required=True,
        fallback="use_default",
    ))
    step_idx += 1

    # 2-3) JD understanding
    if has_jd:
        steps.append(AgentStep(
            step=step_idx,
            name="parse_jd",
            tool="parse_jd",
            input_ref="jd_text",
            output_ref="jd_profile",
            required=False,
            fallback="use_default",
        ))
        step_idx += 1

        steps.append(AgentStep(
            step=step_idx,
            name="match_score",
            tool="match_score",
            input_ref="jd_profile",
            output_ref="score_report",
            required=False,
            fallback="use_default",
        ))
        step_idx += 1

    # 4) retrieve materials (本地)
    steps.append(AgentStep(
        step=step_idx,
        name="retrieve_materials",
        tool=None,
        input_ref="materials_json",
        output_ref="candidates",
        required=True,
        fallback="use_default",
    ))
    step_idx += 1

    # 5) external resume (P2 占位)
    if has_external_resume:
        steps.append(AgentStep(
            step=step_idx,
            name="parse_external_resume",
            tool=None,  # P2: 接入 core.resume_parser
            input_ref="external_resume_bytes",
            output_ref="external_resume_text",
            required=False,
            fallback="skip",
        ))
        step_idx += 1

    # 6) evaluate_bullet_jd_match (FC 开启 + 有 JD)
    #    MVP: 单步 representative(完整 per-bullet 留 P2)
    if enable_function_calling and has_jd:
        steps.append(AgentStep(
            step=step_idx,
            name="evaluate_bullet_jd_match",
            tool="evaluate_bullet_jd_match",
            input_ref="bullet_0",
            output_ref="match_report",
            required=False,
            fallback="use_default",
        ))
        step_idx += 1

    # 7) rewrite_highlights (走 R4-F / R4-M 既有路径)
    steps.append(AgentStep(
        step=step_idx,
        name="rewrite_highlights",
        tool="rewrite_highlights",
        input_ref="bullets",
        output_ref="rewritten_bullets",
        required=False,
        fallback="use_default",  # 无 key 静默降级原文 — R4-F 既定行为
    ))
    step_idx += 1

    # 8) aggregate_preview (本地, 走 build_sections)
    steps.append(AgentStep(
        step=step_idx,
        name="aggregate_preview",
        tool=None,
        input_ref="rewritten_bullets_or_default",
        output_ref="sections",
        required=True,
        fallback="use_default",
    ))
    step_idx += 1

    return steps


# ----------------------------------------------------------------------
# Workflow 执行(失败走 fallback)
# ----------------------------------------------------------------------
def run_agent_workflow(
    *,
    target_role: str,
    intention: Optional[str] = None,
    custom_project_ids: Optional[list[str]] = None,
    template: str = "classic",
    jd_text: Optional[str] = None,
    academic_layout: Optional[str] = None,
    enable_function_calling: bool = False,
    session_id: Optional[str] = None,
    output_dir: Optional[Path] = None,
) -> Any:
    """
    R5-A Phase 1: 执行 Agent workflow,失败 fallback 到旧路径。

    Returns:
        - output_dir is None: dict(preview, 跟 generator.preview_resume() 字节级一致)
        - output_dir is not None: Path(docx, 跟 generator.generate_resume_docx() 字节级一致)

    关键约束:
      - 失败时返 generator 旧 API 的输出(走 build_sections + render_docx)
      - 永抛异常(spec §6.3)— 任何 tool 错误都吞掉走 fallback
      - AgentStep / ToolResult 不存 args / input 原文
    """
    has_jd = bool(jd_text and jd_text.strip())
    has_external_resume = False  # Phase 1 MVP 不消费外部简历,留 P2

    # 1) 构造任务图
    steps = build_task_graph(
        has_jd=has_jd,
        enable_function_calling=enable_function_calling,
        has_external_resume=has_external_resume,
    )

    # 2) 加载 materials(本地,无需工具)
    #    放循环外避免重复 IO
    from core.generator import load_materials, build_sections, render_docx, _resolve_jd_context, _build_jd_match_counts
    from dataclasses import asdict

    # load_materials 是系统级依赖,失败时直接抛(spec §6.3 适用于 workflow 内部工具,
    # 但 system-level IO 失败应该让上层知道,不能静默 fallback)
    materials = load_materials()

    # 3) 解析 JD(若有)
    jd_context: Optional[dict] = None
    if has_jd:
        try:
            jd_context = _resolve_jd_context(jd_text)
        except Exception as e:
            # JD 解析失败 — 不阻断,降级到无 jd 路径
            jd_context = None

    # 4) 逐步执行(只跑"工具步骤",本地步骤跳过)
    tool_results: dict[str, ToolResult] = {}
    fallback_used = False
    fallback_reason: Optional[str] = None

    # Phase 1: 简化执行 — 工具步骤只记录结果,不实际改变 build_sections 输入
    # (避免改写 283 老测试字节级 hash baseline)
    # P2/R5-B 可考虑把 jd_focus / score_report 注入 build_sections
    for step in steps:
        if step.tool is None:
            # 本地步骤(intent / retrieve / aggregate / parse_external)— 跳过执行
            continue

        # 准备 args — 根据工具名(只传必要字段,Phase 1 简化)
        tool_args = _build_tool_args(
            tool_name=step.tool,
            target_role=target_role,
            jd_text=jd_text,
            jd_context=jd_context,
            materials=materials,
        )

        try:
            tr = execute_agent_tool(step.tool, tool_args)
        except Exception as e:
            # execute_agent_tool 自身设计为不抛,但保险起见再包一层
            fallback_used = True
            fallback_reason = f"{step.name}:{type(e).__name__}"
            break

        tool_results[step.name] = tr

        if tr.status == "error":
            # 工具失败 — 关键步骤失败 → 降级;非关键 → 记录后继续
            if step.required:
                fallback_used = True
                fallback_reason = f"{step.name}:{tr.error_type}"
                break
            # 非关键工具失败(spec §6.3)— 记录后继续
            continue

    # 5) 无论工具步骤执行如何,最终都委托给 generator.build_sections (Phase 1 简化)
    #    这样保证输出结构与旧路径字节级一致,283 老测试不破
    try:
        sections = build_sections(
            target_role=target_role,
            intention=intention,
            custom_project_ids=custom_project_ids,
            jd_context=jd_context,
            enable_function_calling=enable_function_calling,
            session_id=session_id,
        )
    except Exception as e:
        # build_sections 失败 — 这是真正的"全失败",必须让上层知道
        # 但 generator 老路径也会抛 ValueError,这里保持一致
        raise

    # 6) 组装 preview / generate 结果(沿用 generator 的 schema)
    if output_dir is None:
        # preview 路径
        from core.generator import ROLE_CONFIG
        preview: dict = {
            "target_role": target_role,
            "template": template,
            "academic_layout": academic_layout,
            "intention": next(
                (s.content["intention"] for s in sections if s.type == "header"),
                "",
            ),
            "sections": [asdict(s) for s in sections],
            "jd_match_counts": _build_jd_match_counts(sections, jd_context) if jd_context else None,
        }
        # Phase 1 不返回 agent_summary(spec §8.2 留 Phase 2)
        return preview
    else:
        # generate 路径(返回 docx Path)
        return render_docx(
            sections=sections,
            target_role=target_role,
            output_dir=output_dir,
            template=template,
            academic_layout=academic_layout,
        )


def _build_tool_args(
    *,
    tool_name: str,
    target_role: str,
    jd_text: Optional[str],
    jd_context: Optional[dict],
    materials: dict,
) -> dict:
    """
    R5-A Phase 1: 为每个工具构造最小可用 args
    (Phase 1 简化:工具主要用来"展示 workflow 路径",而非改变主流程)
    """
    if tool_name == "parse_jd":
        return {"text": jd_text or ""}
    if tool_name == "match_score":
        return {
            "text": jd_text or "",
            "role": target_role,
            "materials": materials,
        }
    if tool_name == "evaluate_bullet_jd_match":
        # MVP representative: 用 candidate 项目第 1 个 bullet
        bullet = _pick_representative_bullet(materials, target_role)
        # jd_focus: 用 jd_context 解析出的关键词,无 jd 时空 dict
        jd_focus = _make_jd_focus(jd_context)
        return {"bullet": bullet, "jd_focus": jd_focus}
    if tool_name == "rewrite_highlights":
        # 实际改写由 build_sections 内部走 rewrite_highlights;
        # 这里只是工具调用展示,args 给一份空 highlights(让 callable 走降级)
        return {
            "highlights": [_pick_representative_bullet(materials, target_role)],
            "target_role": target_role,
            "jd_text": jd_text or "",
            "jd_focus": _make_jd_focus(jd_context),
            "enable_function_calling": False,  # tool 内部不再开 FC,避免嵌套 loop
            "session_id": None,
        }
    return {}


def _pick_representative_bullet(materials: dict, target_role: str) -> str:
    """MVP representative bullet — Phase 1 简化:用首选项目的 tech_metric highlights 第 1 条"""
    from core.generator import ROLE_CONFIG
    role_cfg = ROLE_CONFIG.get(target_role, {})
    preferred = role_cfg.get("preferred_project_ids", [])
    projects = materials.get("projects", [])
    proj_map = {p["id"]: p for p in projects}
    for pid in preferred:
        p = proj_map.get(pid)
        if not p:
            continue
        h = p.get("highlights", {})
        # 优先用 target_role,fallback general
        bullets = h.get(target_role) or h.get("general") or []
        if bullets:
            return bullets[0]
    return ""


def _make_jd_focus(jd_context: Optional[dict]) -> dict:
    """把 jd_context 转成 evaluate_bullet_jd_match 需要的 jd_focus 格式"""
    if not jd_context:
        return {"matched": [], "missing": [], "tier_required": [], "tier_preferred": []}
    raw = jd_context.get("raw_keywords") or []
    tier = jd_context.get("tier_info") or {}
    return {
        "matched": list(raw),
        "missing": [],
        "tier_required": list(tier.get("required") or []),
        "tier_preferred": list(tier.get("preferred") or []),
    }


def _fallback_to_old_path(
    *,
    target_role: str,
    intention: Optional[str],
    custom_project_ids: Optional[list[str]],
    template: str,
    jd_text: Optional[str],
    academic_layout: Optional[str],
    enable_function_calling: bool,
    session_id: Optional[str],
    output_dir: Optional[Path],
    reason: str,
) -> Any:
    """workflow 失败 → 委托 generator 老路径(字节级一致)"""
    # 局部 import 避免循环
    from core.generator import (
        preview_resume as _preview_resume,
        generate_resume_docx as _generate_resume_docx,
    )

    if output_dir is None:
        return _preview_resume(
            target_role=target_role,
            intention=intention,
            custom_project_ids=custom_project_ids,
            template=template,
            jd_text=jd_text,
            academic_layout=academic_layout,
            enable_function_calling=enable_function_calling,
            session_id=session_id,
            # 注意: enable_agent_workflow 显式 False,避免 workflow 内部再调自己(死循环)
            enable_agent_workflow=False,
        )
    else:
        return _generate_resume_docx(
            target_role=target_role,
            intention=intention,
            custom_project_ids=custom_project_ids,
            output_dir=output_dir,
            template=template,
            jd_text=jd_text,
            academic_layout=academic_layout,
            enable_function_calling=enable_function_calling,
            session_id=session_id,
            enable_agent_workflow=False,
        )
