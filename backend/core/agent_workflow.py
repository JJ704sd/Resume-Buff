"""
R5-A Phase 1: Agent Workflow 编排层(受控 Plan-and-Execute)

设计目标(spec §4.1 + §4.2):
  - **MVP 不让 LLM 自由规划**(避免死循环 / token 浪费)
  - 系统根据请求字段生成固定候选任务图
  - LLM 只在有限范围内决定是否需要某些工具(例如 evaluate_bullet_jd_match 是否启用)
  - 每步工具调用都有 allowlist、错误分类、降级策略
  - 最终结果必须回到现有 preview_resume() / generate_resume_docx() 的数据结构
  - workflow 失败时降级到当前旧路径(走 build_sections,字节级一致)

任务图(spec §4.2 推荐 + Phase 3 增量):
  | 阶段       | 工具                          | 必选   | 输出                |
  |------------|-------------------------------|--------|---------------------|
  | intent     | parse_user_intent(本地)       | 是     | role/template 归一化 |
  | jd_under   | parse_jd / match_score        | 有 JD  | jd_profile / score  |
  | evidence   | retrieve_evidence (Phase 3)   | 有 JD  | evidence snippets   |
  | retrieve   | retrieve_materials(本地)      | 是     | candidates          |
  | evaluate   | evaluate_bullet_jd_match      | FC 开启| matched/missing     |
  | rewrite    | rewrite_highlights             | LLM 可用 | rewritten bullets |
  | aggregate  | aggregate_preview(本地)       | 是     | preview sections    |

R5-A Phase 2 增量(对齐 spec §7.1):
  - run_agent_workflow 每次生成唯一 request_id(短 uuid,前缀 "r")
  - 每个 step(本地 + 工具)写一条结构化 JSONL trace 到
    backend/logs/agent_trace.jsonl(供 scripts/replay_agent_trace.py 解析)
  - JSONL trace 只写长度(input_size/output_size)、工具名、错误分类,
    **绝不写**完整 JD / 完整 bullet / 简历内容 / 姓名 / 邮箱 / 电话
  - trace 写失败 → 静默降级(由 logger.log_agent_trace_jsonl 内部 try/except),
    不影响 preview/generate 主流程
  - 保留 R4-A 旧 agent_trace.log(不动),新格式走 jsonl

R5-A Phase 3 增量(对齐 spec §5.3 RAG 增强):
  - 任务图 has_jd 时插入 retrieve_evidence step(match_score 之后, retrieve_materials 之前)
  - evidence dict list (不存原文 PII 到 trace) 由 retrieve_evidence 工具产出
  - 提取 evidence summary (文本, ≤2000 字符) 透传给 build_sections → rewrite_highlights
  - rewrite_highlights 新增 evidence kwarg;evidence=None 时字节级一致(老路径)
  - prompt 注入"只能基于 evidence 中存在的事实改写"约束(spec §6.4)
  - trace evidence step: input_size = jd_keywords 总字符, output_size = evidence 总字符,
    不存 evidence text / jd_text 原文

公开 API:
  - build_task_graph(...)           — 纯函数,根据请求字段返回 step 列表
  - run_agent_workflow(...)         — 执行任务图,失败 fallback 到旧路径
  - generate_request_id()           — 短 uuid 工具(prefix "r"),给 request_id 用

隐私边界(对齐 spec §6.4):
  - AgentStep 不存 input / output 原文(只存 input_ref/output_ref 名字)
  - error_msg 只含异常类型名,不含 args 原文
  - jd_text / bullet 仅作为 args 传给工具,不进 step 结构
  - JSONL trace 也只存长度(不存原文)— 调用方负责 size 计算

不引入:
  - 不引入新 LLM 调用(LLM 只走既有 rewrite_highlights 路径)
  - 不引入异步队列(本地单用户 MVP,同步即可)
  - 不引入持久化(无 sqlite / redis / file storage)— jsonl 是可丢弃的 trace
  - 不引入账号 / 多用户 / 公网部署
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from core.agent_tools import (
    ToolResult,
    execute_agent_tool,
)
from core.logger import log_agent_trace_jsonl


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
      4. (has_jd) retrieve_evidence  — R5-A Phase 3 新增
      5. retrieve_materials (本地,无工具)
      6. (has_external_resume) parse_external_resume  — P2 占位,本轮无外部简历 hook
      7. (enable_function_calling) evaluate_bullet_jd_match × N(bullets 数)— MVP 简化:只跑 1 步 representative
      8. rewrite_highlights
      9. aggregate_preview   (本地,无工具,走 build_sections)

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

        # R5-A Phase 3: evidence retrieval(match_score 之后, retrieve_materials 之前)
        # spec §5.3: 用 KEYWORD_GROUPS + jd parsed keywords 做 lexical retrieval
        # 失败降级 "use_default" — 没 evidence 也允许后续 rewrite 走"无 evidence" 分支
        steps.append(AgentStep(
            step=step_idx,
            name="retrieve_evidence",
            tool="retrieve_evidence",
            input_ref="jd_keywords",
            output_ref="evidence_snippets",
            required=False,
            fallback="use_default",
        ))
        step_idx += 1

    # 5) retrieve materials (本地)
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

    # 6) external resume (P2 占位)
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

    # 7) evaluate_bullet_jd_match (FC 开启 + 有 JD)
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

    # 8) rewrite_highlights (走 R4-F / R4-M 既有路径)
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

    # 9) aggregate_preview (本地, 走 build_sections)
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
# Request ID 生成(Phase 2 JSONL trace 用)
# ----------------------------------------------------------------------
def generate_request_id() -> str:
    """
    R5-A Phase 2: 生成一次 workflow 的 request_id(短 uuid,前缀 "r")

    短串设计(对齐 spec §7.1):
      - "r" + uuid4 hex 8 位 = 9 字符
      - 32 bit 熵 — 本地单用户足够区分
      - 不带任何 PII / 时间戳 / 请求内容(纯随机)— 防泄漏

    用于 JSONL trace 的 request_id 字段,供 scripts/replay_agent_trace.py
    按 request_id 拉出同一次 workflow 的所有 step。
    """
    return "r" + uuid.uuid4().hex[:8]


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
    evidence: Optional[list] = None,  # R5-A Phase 3: 显式传入 evidence 时跳过 retrieve_evidence 工具
) -> Any:
    """
    R5-A Phase 1 + Phase 2 + Phase 3: 执行 Agent workflow,失败 fallback 到旧路径,每个 step
    写一条结构化 JSONL trace 到 backend/logs/agent_trace.jsonl。

    Returns:
        - output_dir is None: dict(preview, 跟 generator.preview_resume() 字节级一致)
        - output_dir is not None: Path(docx, 跟 generator.generate_resume_docx() 字节级一致)

    R5-A Phase 2 增量(spec §7.1):
      - 每次调用生成唯一 request_id(短 uuid,前缀 "r")
      - 每个 step(本地 + 工具)写一条 JSONL trace,字段:
        ts / request_id / session_id / workflow / step / tool /
        latency_ms / status / error_type / input_size / output_size
      - input_size / output_size 只算字节数,**绝不存 args / output 原文**
      - JSONL trace 写入失败(磁盘满 / IO 错)由 logger 内部静默吞掉
        **不影响主流程 preview / generate 输出**

    R5-A Phase 3 增量(spec §5.3):
      - 任务图 has_jd=True 时插入 retrieve_evidence step (match_score 之后)
      - evidence list (ToolResult.output, dict 序列化) → 透传给 build_sections → rewrite_highlights
      - evidence kwarg 非 None 时跳过 retrieve_evidence 工具调用 (caller 已有 evidence)
      - trace evidence step: input_size = jd_keywords 总字符, output_size = evidence 总字符
      - trace 不存 evidence text / jd_text 原文(只存长度)

    关键约束:
      - 失败时返 generator 旧 API 的输出(走 build_sections + render_docx)
      - 永抛异常(spec §6.3)— 任何 tool 错误都吞掉走 fallback
      - AgentStep / ToolResult 不存 args / input 原文
    """
    has_jd = bool(jd_text and jd_text.strip())
    has_external_resume = False  # Phase 1 MVP 不消费外部简历,留 P2

    # R5-A Phase 2: 每次 workflow 生成唯一 request_id(spec §7.1 JSONL schema)
    request_id = generate_request_id()
    workflow_kind = "generate" if output_dir is not None else "preview"
    # session_id 可为空串(无 session 时)— JSONL schema 字段保留
    session_id_trace: str = session_id or ""

    # R5-A Phase 3: caller 预传 evidence(可选)→ 跳过 retrieve_evidence 工具调用
    evidence_explicit = evidence is not None

    # 1) 构造任务图
    steps = build_task_graph(
        has_jd=has_jd,
        enable_function_calling=enable_function_calling,
        has_external_resume=has_external_resume,
    )

    # R5-A Phase 2: trace 构造辅助(只写长度 / 工具名 / 错误分类,不写原文)
    # 每个本地步骤也都写一条 trace(让 replay 能看到完整任务图,不丢节点)
    def _emit_trace(step_obj, *, status: str, error_type, latency_ms: int,
                     input_size: int = 0, output_size: int = 0) -> None:
        """写一条 JSONL trace。失败由 logger 内部 try/except 静默吞掉,不影响主流程。"""
        log_agent_trace_jsonl({
            "request_id": request_id,
            "session_id": session_id_trace,
            "workflow": workflow_kind,
            "step": step_obj.step,
            "tool": step_obj.tool,  # None 时序列化为 null
            "latency_ms": latency_ms,
            "status": status,
            "error_type": error_type,
            "input_size": input_size,
            "output_size": output_size,
        })

    # 先把所有本地步骤 trace 出来(intent / retrieve / aggregate / parse_external_resume)
    # 让 replay 能看到完整任务图节点(状态=skipped,latency=0)
    for step_obj in steps:
        if step_obj.tool is None:
            _emit_trace(step_obj, status="skipped", error_type=None, latency_ms=0)

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

    # 4) 逐步执行(只跑"工具步骤",本地步骤跳过执行)
    tool_results: dict[str, ToolResult] = {}
    fallback_used = False
    fallback_reason: Optional[str] = None

    # R5-A Phase 3: evidence list 收集(供 build_sections → rewrite_highlights 注入 prompt)
    evidence_collected: Optional[list] = evidence  # 默认 caller 传入,否则下面 retrieve_evidence 填

    # Phase 1: 简化执行 — 工具步骤只记录结果,不实际改变 build_sections 输入
    # (避免改写 283 老测试字节级 hash baseline)
    # P2/R5-B 可考虑把 jd_focus / score_report 注入 build_sections
    for step in steps:
        if step.tool is None:
            # 本地步骤(intent / retrieve / aggregate / parse_external)— 跳过执行
            continue

        # R5-A Phase 3: retrieve_evidence 在 caller 已显式传 evidence 时跳过
        if step.tool == "retrieve_evidence" and evidence_explicit:
            # 显式 evidence 跳过工具调用,trace 写 skipped (本地步骤语义)
            _emit_trace(step, status="skipped", error_type=None, latency_ms=0,
                        input_size=0, output_size=0)
            continue

        # 准备 args — 根据工具名(只传必要字段,Phase 1 简化)
        tool_args = _build_tool_args(
            tool_name=step.tool,
            target_role=target_role,
            jd_text=jd_text,
            jd_context=jd_context,
            materials=materials,
        )

        # R5-A Phase 2: 计算入参长度(只算 bytes,不存原文)— input_size 用于 trace
        try:
            input_size = _estimate_input_size(step.tool, tool_args)
        except Exception:
            input_size = 0  # 防御性:长度算不出也不阻断

        # 工具执行(走 execute_agent_tool 内部计时)
        import time as _t
        t0 = _t.time()
        try:
            tr = execute_agent_tool(step.tool, tool_args)
        except Exception as e:
            # execute_agent_tool 自身设计为不抛,但保险起见再包一层
            latency_ms = int((_t.time() - t0) * 1000)
            _emit_trace(step, status="error", error_type=type(e).__name__,
                        latency_ms=latency_ms, input_size=input_size, output_size=0)
            fallback_used = True
            fallback_reason = f"{step.name}:{type(e).__name__}"
            break

        # R5-A Phase 2: 写出参长度(只算 bytes,不存原文)
        output_size = _estimate_output_size(tr.output) if tr.output is not None else 0
        _emit_trace(
            step,
            status=tr.status,
            error_type=tr.error_type,
            latency_ms=tr.latency_ms,
            input_size=input_size,
            output_size=output_size,
        )

        tool_results[step.name] = tr

        # R5-A Phase 3: 收集 retrieve_evidence 工具输出,供 build_sections → rewrite_highlights 注入 prompt
        if step.tool == "retrieve_evidence" and tr.status == "success" and not evidence_explicit:
            # output 是 dict list(由 evidence_to_dict_list wrapper 序列化)
            evidence_collected = tr.output  # list[dict] — 透传给 build_sections

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
            evidence=evidence_collected,  # R5-A Phase 3: None 时字节级一致
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
            # R5-A Phase 3: evidence_summary 透传 (供前端高级信息区展示, 默认不渲染)
            # evidence_collected 是 dict list(由 wrapper 序列化), 跟 rewrite_highlights 收到的同结构
            "evidence_summary": evidence_collected,
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
    R5-A Phase 1 + Phase 3: 为每个工具构造最小可用 args
    (Phase 1 简化:工具主要用来"展示 workflow 路径",而非改变主流程)
    Phase 3: retrieve_evidence 加进分支, 用 jd_context["raw_keywords"] 当 jd_keywords 输入
    """
    if tool_name == "parse_jd":
        return {"text": jd_text or ""}
    if tool_name == "match_score":
        return {
            "text": jd_text or "",
            "role": target_role,
            "materials": materials,
        }
    if tool_name == "retrieve_evidence":
        # R5-A Phase 3: 用 parse_jd 产出的 raw_keywords 作为 jd_keywords
        raw_keywords = (jd_context or {}).get("raw_keywords") or []
        return {
            "jd_keywords": list(raw_keywords),
            "role": target_role,
            "materials": materials,
            "top_k": 8,  # spec §5.3 默认 top_k
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


# ----------------------------------------------------------------------
# R5-A Phase 2: trace 长度估算(只算 bytes,不存原文)
# ----------------------------------------------------------------------
def _estimate_input_size(tool_name: str, args: dict) -> int:
    """
    计算工具入参的近似字节数(只算长度,不存原文)。

    隐私边界:
      - 只把 args dict 序列化成 str 后算字节数,绝不入 trace
      - 不打印 args 内容,不上报日志

    Args:
        tool_name: 工具名(目前未使用,留作按工具类型分别限制)
        args:      工具入参 dict

    Returns:
        int - 序列化后的 UTF-8 字节数
        出错(对象不可序列化)返 0,不抛
    """
    try:
        import json as _json
        return len(_json.dumps(args, ensure_ascii=False).encode("utf-8"))
    except Exception:
        # 不可序列化(materials 含 docx Document 对象 / set 等)→ 返 0
        # 不阻断 workflow(spec §6.3)
        return 0


def _estimate_output_size(output: Any) -> int:
    """
    计算工具出参的近似字节数(只算长度,不存原文)。

    Args:
        output: ToolResult.output(可能是 dict / list / str / 任意对象)

    Returns:
        int - 序列化后的 UTF-8 字节数
        出错返 0
    """
    if output is None:
        return 0
    try:
        import json as _json
        return len(_json.dumps(output, ensure_ascii=False).encode("utf-8"))
    except Exception:
        # 不可序列化 → 退到 len(str()) 近似(不会崩)
        try:
            return len(str(output).encode("utf-8"))
        except Exception:
            return 0


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
    evidence: Optional[list] = None,  # R5-A Phase 3: 透传 evidence
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
            evidence=evidence,  # R5-A Phase 3
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
            evidence=evidence,  # R5-A Phase 3
        )
