"""
R5-A Phase 1: Agent 工具注册表 + 统一执行入口

设计(spec §5.1):
  - AGENT_TOOLS 字典集中描述每个工具的元数据 + 可调用对象
  - execute_agent_tool() 是唯一调用入口:
    1. allowlist 校验(未知工具返 error,不抛)
    2. 计时(latency_ms)
    3. 异常捕获(转 ToolResult,带 error_type 分类)
  - ToolResult dataclass **不存 args / input 原文**(对齐 spec §6.4 隐私边界)

错误分类(对齐 spec §6.2):
  - network_error       : LLM/API 网络失败
  - schema_invalid      : LLM 输出不符合 schema
  - tool_not_allowed    : 非 allowlist 工具
  - tool_args_invalid   : 工具参数缺失 / 类型错误
  - tool_runtime_error  : 工具内部异常
  - privacy_violation   : 试图写入敏感内容日志或越权访问(预留,本轮不主动用)
  - max_step_exhausted  : Agent 循环达到上限

R5-A Phase 3 新增:
  - retrieve_evidence  : 轻量 RAG — 从 materials 切 evidence snippets 并按 JD 关键词检索
  - 输出 evidence_snippet dict 列表(只含 source_type/source_id/text/matched_keywords/confidence)
  - pii_risk="medium" (evidence 含真实素材片段, 跟 match_score 同级)

R5-B Phase 2A 新增 (round5-b-agent-capability-spec.md §3.1-3.3):
  - 完整轻量 schema validator: type / required / properties / items / minimum / maximum
    (见 core.tool_schema.validate_schema)
  - context 权限边界:
      * allow_jd_text         (默认 True)
      * allow_materials       (默认 True)
      * allow_external_resume (默认 False)
      * max_pii_risk          (默认 "medium")
  - 权限不匹配返回 PRIVACY_VIOLATION, 错误描述只含字段名, 不含 args 原文
  - ToolSpec.metadata 字段(向后兼容 default={})— 标 affects_preview=True 时
    agent_summary.tools_used 才列该工具(spec §3.3 有效语义)

注意:
  - 本模块不引入任何 LLM 调用,纯工具注册 / 调用包装
  - 导入 jd_parser / llm_rewriter / evidence 是稳定的下游,无循环依赖风险
  - Phase 1 不在 ToolResult 里存 args / input 原文(隐私)
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from core.jd_parser import (
    compare_resume_jd,
    evaluate_bullet_jd_match,
    match_score,
    parse_external_resume,
    parse_jd,
)
from core.llm_rewriter import rewrite_highlights
from core.evidence import (
    retrieve_evidence,
    evidence_to_dict_list,
)
from core.tool_schema import validate_schema


# ----------------------------------------------------------------------
# 错误分类常量(对齐 spec §6.2)
# ----------------------------------------------------------------------
class ToolErrorType:
    NETWORK_ERROR = "network_error"
    SCHEMA_INVALID = "schema_invalid"
    TOOL_NOT_ALLOWED = "tool_not_allowed"
    TOOL_ARGS_INVALID = "tool_args_invalid"
    TOOL_RUNTIME_ERROR = "tool_runtime_error"
    PRIVACY_VIOLATION = "privacy_violation"
    MAX_STEP_EXHAUSTED = "max_step_exhausted"


# ----------------------------------------------------------------------
# ToolSpec + ToolResult dataclass
# ----------------------------------------------------------------------
@dataclass(frozen=True)
class ToolSpec:
    """
    工具元数据(frozen=True:注册后不可变,防止运行期被偷偷换函数)

    字段:
      name         - 工具名(AGENT_TOOLS 字典 key,显式冗余便于调试)
      callable     - 实际 Python callable(签名: kwargs 形式)
      permission   - 权限标签(read_jd_text / read_jd_and_materials / ...)
      pii_risk     - PII 风险等级(low / medium / high)— 给日志审计用
      timeout_ms   - 单次调用允许最大耗时(毫秒)— MVP 只记录,不强杀
      input_schema - 输入 schema 描述(dict,Phase 2A 已升级为可校验子集)
      metadata     - 扩展元数据 dict(R5-B Phase 2A 新增)
                     - affects_preview: bool — True 时 agent_summary.tools_used 才列该工具
                     - 其他 P2 字段按需扩展

    影响 preview 的工具(R5-B Phase 2A):
      - retrieve_evidence: 输出 evidence 真正注入 build_sections → rewrite_highlights
                            → 影响 highlights 内容(affects_preview=True)
      - 其他工具(parse_jd / match_score / evaluate_bullet_jd_match / rewrite_highlights)
        在当前 workflow 里是"展示型"调用(output 未被 build_sections 实际消费)
        → affects_preview=False
        → Phase 3 升级后再重新评估
    """
    name: str
    callable: Callable[..., Any]
    permission: str
    pii_risk: str
    timeout_ms: int
    input_schema: Optional[dict] = None
    metadata: dict = field(default_factory=dict)


@dataclass
class ToolResult:
    """
    工具执行结果(永远返回,不抛异常)

    字段:
      tool        - 工具名
      status      - "success" | "error" | "skipped"
      output      - 工具返回值(失败时为 None)
      error_type  - ToolErrorType 之一;成功时为 None
      latency_ms  - 实际耗时(毫秒,含错误场景)
      error_msg   - 简短的错误摘要(不含 args 原文,防 PII)

    注意:
      - **不存 args / input 字段**(对齐 spec §6.4 隐私边界)
      - status="error" 时 output 必为 None
      - 调用方负责把 ToolResult 转 AgentStep 写入 trace
    """
    tool: str
    status: str
    output: Any = None
    error_type: Optional[str] = None
    latency_ms: int = 0
    error_msg: Optional[str] = None


# ----------------------------------------------------------------------
# AGENT_TOOLS 注册表(对齐 spec §4.2 推荐任务图 + §5.1)
# ----------------------------------------------------------------------
# Phase 1 首批 4 个工具:
#   - parse_jd                    : 结构化抽取 JD 的硬性要求 / 关键词
#   - match_score                 : JD ↔ 素材库匹配打分(返回 score + coverage)
#   - evaluate_bullet_jd_match    : 内容理解 — 单条 bullet 对 JD 关键词覆盖度
#   - rewrite_highlights          : 生成与编辑 — 改写 bullets
#
# Phase 3 新增:
#   - retrieve_evidence           : 检索 — 从 materials 切 evidence snippets 并按 JD 关键词检索
#
# 后续 P2 可能加:
#   - parse_external_resume       : 结构化抽取 — 外部简历 docx/pdf/txt(已有 core.resume_parser)
#   - render_docx                 : 发布/保存 — 实际生成 docx(MVP 用 generator.render_docx)
AGENT_TOOLS: dict[str, ToolSpec] = {
    "parse_jd": ToolSpec(
        name="parse_jd",
        callable=parse_jd,
        permission="read_jd_text",
        pii_risk="medium",
        timeout_ms=300,
        input_schema={"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
    ),
    "match_score": ToolSpec(
        name="match_score",
        callable=match_score,
        permission="read_jd_and_materials",
        pii_risk="medium",
        timeout_ms=500,
        input_schema={
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                # R5-A closeout bugfix: schema 必须跟 match_score 函数签名一致(用 target_role,不是 role)
                # 原 schema 写 role 但 match_score(text, target_role, ...) 真实参数名是 target_role
                # 导致 workflow _build_tool_args 传 "role" 时 callable 抛 TypeError
                "target_role": {"type": "string"},
                "materials": {"type": "object"},
            },
            "required": ["text", "target_role", "materials"],
        },
    ),
    "evaluate_bullet_jd_match": ToolSpec(
        name="evaluate_bullet_jd_match",
        callable=evaluate_bullet_jd_match,
        permission="read_bullet_and_jd_focus",
        pii_risk="low",
        timeout_ms=300,
        input_schema={
            "type": "object",
            "properties": {
                "bullet": {"type": "string"},
                "jd_focus": {"type": "object"},
            },
            "required": ["bullet", "jd_focus"],
        },
    ),
    "retrieve_evidence": ToolSpec(
        name="retrieve_evidence",
        # 包一层把 EvidenceSnippet 序列化成 dict list (ToolResult.output 要可序列化)
        # frozen=True dataclass 的 tuple field 不能直接 json.dumps
        callable=lambda **kw: evidence_to_dict_list(retrieve_evidence(**kw)),
        permission="read_materials_and_jd_keywords",
        pii_risk="medium",  # evidence 含真实素材片段, 跟 match_score 同级
        timeout_ms=300,
        input_schema={
            "type": "object",
            "properties": {
                "jd_keywords": {"type": "array", "items": {"type": "string"}},
                "role": {"type": "string"},
                "materials": {"type": "object"},
                "top_k": {"type": "integer", "minimum": 1, "maximum": 50},
                "min_confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            },
            "required": ["jd_keywords", "role", "materials"],
        },
        # R5-B Phase 2A: 标记 retrieve_evidence 的 output 真正影响 preview
        # (evidence 注入 build_sections → rewrite_highlights → 影响 highlights)
        metadata={"affects_preview": True},
    ),
    "rewrite_highlights": ToolSpec(
        name="rewrite_highlights",
        callable=rewrite_highlights,
        permission="read_bullet_and_jd_focus",
        pii_risk="medium",
        timeout_ms=2000,
        input_schema={
            "type": "object",
            "properties": {
                "highlights": {"type": "array", "items": {"type": "string"}},
                "target_role": {"type": "string"},
                "jd_text": {"type": "string"},
                "jd_focus": {"type": "object"},
                "enable_function_calling": {"type": "boolean"},
                "session_id": {"type": "string"},
                "evidence": {"type": "array"},  # R5-A Phase 3: EvidenceSnippet dict 列表
            },
            "required": ["highlights", "target_role"],
        },
    ),
    # R5-C Phase 2: 外部简历工具 — 让外部简历文本进入 Agent 工具链
    # 隐私边界 (round5-c-agent-capability-spec.md §3.4):
    #   - 不存 / 不返 简历段落原文 (parse_external_resume 只返 profile 统计 + 命中关键词)
    #   - 不存 / 不返 JD 原文 (compare_resume_jd 只返 4 维摘要 + 计数)
    #   - JSONL trace 只写 input_size / output_size, 不写原文
    "parse_external_resume": ToolSpec(
        name="parse_external_resume",
        callable=parse_external_resume,
        permission="read_external_resume",
        pii_risk="high",  # 含简历片段 (虽然只返关键词, 但入参本身敏感)
        timeout_ms=300,
        input_schema={
            "type": "object",
            "properties": {
                "external_resume_text": {"type": "string"},
            },
            "required": ["external_resume_text"],
        },
        # R5-C Phase 2 §3.3: 初期不标 affects_preview=True
        # 后续若让外部简历影响素材排序 / 改写, 单独升版并补 baseline 测试
        metadata={"affects_preview": False},
    ),
    "compare_resume_jd": ToolSpec(
        name="compare_resume_jd",
        callable=compare_resume_jd,
        # 同时读 JD + 外部简历 — 用 read_jd_and_external_resume 复合权限,
        # 校验同时需要 allow_jd_text + allow_external_resume
        permission="read_jd_and_external_resume",
        pii_risk="high",
        timeout_ms=500,
        input_schema={
            "type": "object",
            "properties": {
                "external_resume_text": {"type": "string"},
                "jd_text": {"type": "string"},
                "target_role": {"type": "string"},
                "materials": {"type": "object"},
            },
            "required": ["external_resume_text", "jd_text", "target_role", "materials"],
        },
        metadata={"affects_preview": False},
    ),
}


# ----------------------------------------------------------------------
# R5-B Phase 2A: Context 权限校验
# ----------------------------------------------------------------------
# Context 协议 (round5-b-agent-capability-spec.md §3.2):
#   {
#     "allow_jd_text":         bool (default True),
#     "allow_materials":       bool (default True),
#     "allow_external_resume": bool (default False),
#     "max_pii_risk":          "low" | "medium" | "high" (default "medium"),
#   }
#
# 规则:
#   - tool.permission 与 context 不匹配 -> PRIVACY_VIOLATION
#     * read_jd_text 需 allow_jd_text=True
#     * read_jd_and_materials 需 allow_jd_text=True AND allow_materials=True
#     * read_materials_and_jd_keywords 需 allow_materials=True AND allow_jd_text=True
#     * read_bullet_and_jd_focus 需 allow_jd_text=True (单 bullet 通常来自 jd_focus 上下文)
#     * external_resume 需 allow_external_resume=True
#   - tool.pii_risk > context.max_pii_risk -> PRIVACY_VIOLATION
#     * 风险等级排序: low < medium < high
#   - 错误描述只含权限 / 风险级别, 不含 args 原文

_PII_RISK_LEVEL = {"low": 0, "medium": 1, "high": 2}


def _check_permission_context(spec: ToolSpec, context: dict) -> Optional[str]:
    """
    R5-B Phase 2A: 校验 spec.permission 与 context 是否匹配.
    失败返回 str 错误描述(不含 args 原文);成功返回 None.

    注意:
      - 权限校验在 schema 校验后、callable 调用前
      - 即使校验失败, 也只返回错误描述(不含 context 原文 — 防 PII)
      - 缺省 context 字段时按默认值(True/True/False/medium)处理
    """
    permission = spec.permission
    max_pii = context.get("max_pii_risk", "medium")
    # 防御性: max_pii 必须是已知等级
    if max_pii not in _PII_RISK_LEVEL:
        max_pii = "medium"

    # 1) pii_risk 等级上限
    spec_pii_level = _PII_RISK_LEVEL.get(spec.pii_risk, _PII_RISK_LEVEL["medium"])
    ctx_pii_level = _PII_RISK_LEVEL[max_pii]
    if spec_pii_level > ctx_pii_level:
        return f"pii_risk={spec.pii_risk} exceeds context max_pii_risk={max_pii}"

    # 2) 权限匹配
    if permission == "read_jd_text":
        if not context.get("allow_jd_text", True):
            return "permission read_jd_text denied by context"
    elif permission == "read_jd_and_materials":
        if not context.get("allow_jd_text", True):
            return "permission read_jd_and_materials requires allow_jd_text"
        if not context.get("allow_materials", True):
            return "permission read_jd_and_materials requires allow_materials"
    elif permission == "read_materials_and_jd_keywords":
        if not context.get("allow_materials", True):
            return "permission read_materials_and_jd_keywords requires allow_materials"
        if not context.get("allow_jd_text", True):
            return "permission read_materials_and_jd_keywords requires allow_jd_text"
    elif permission == "read_bullet_and_jd_focus":
        if not context.get("allow_jd_text", True):
            return "permission read_bullet_and_jd_focus requires allow_jd_text"
    elif permission == "read_external_resume":
        if not context.get("allow_external_resume", False):
            return "permission read_external_resume requires allow_external_resume"
    elif permission == "read_jd_and_external_resume":
        # R5-C Phase 2: 复合权限 — 同时读 JD + 外部简历
        if not context.get("allow_jd_text", True):
            return "permission read_jd_and_external_resume requires allow_jd_text"
        if not context.get("allow_external_resume", False):
            return "permission read_jd_and_external_resume requires allow_external_resume"
    # unknown permission -> 不阻断 (宽容)

    return None


# ----------------------------------------------------------------------
# 统一执行入口
# ----------------------------------------------------------------------
def _validate_required_args(spec: ToolSpec, args: dict) -> Optional[str]:
    """
    R5-A closeout: 基于 spec.input_schema 做轻量 JSON schema 校验.

    R5-B Phase 2A 升级:
      - 委托给 core.tool_schema.validate_schema
      - 覆盖 type / required / properties / items / minimum / maximum 子集
      - 失败时只含字段名 + 类型名, 不含 args 原文 (隐私边界)

    Returns:
        None 如果 args 满足 schema
        str 错误描述(只列字段名 + 类型摘要),如果不满足
    """
    if not spec.input_schema:
        return None  # 无 schema = 不校验 (向后兼容)
    return validate_schema(spec.input_schema, args)


def execute_agent_tool(
    tool_name: str,
    args: Optional[dict] = None,
    context: Optional[dict] = None,
) -> ToolResult:
    """
    工具执行统一入口(对齐 spec §5.1)

    流程 (R5-B Phase 2A 升级):
      1. allowlist 校验: tool_name 不在 AGENT_TOOLS → TOOL_NOT_ALLOWED
      2. R5-B Phase 2A: 校验 context 权限边界
         (allow_jd_text / allow_materials / allow_external_resume / max_pii_risk)
         → PRIVACY_VIOLATION(早于 schema 校验, 防止敏感数据进入校验日志)
      3. R5-B Phase 2A: 完整 schema 校验 (type / required / properties / items / minimum / maximum)
         → TOOL_ARGS_INVALID(早于 callable 调用, 给出明确字段名 + 类型摘要)
      4. 计时
      5. 调 spec.callable(**args) — 失败也返 ToolResult, 绝不抛
      6. TypeError  → TOOL_ARGS_INVALID(args 类型 / 名字错)
      7. 其他异常   → TOOL_RUNTIME_ERROR

    Args:
        tool_name:  工具名(必须在 AGENT_TOOLS)
        args:       工具调用参数 dict(传 None 等价于 {})
        context:    调用上下文(对齐 spec §3.2, 缺省值见 _check_permission_context)

    Returns:
        ToolResult(status="success"|"error", output / error_type / latency_ms / ...)
        **绝不抛异常**

    隐私(对齐 spec §6.4):
      - ToolResult 不存 args 原文(本模块不缓存)
      - error_msg 仅含异常类型名 / 缺失字段名 / 类型摘要, 不含 args 内容
    """
    args = args or {}
    context = context or {}

    # 1) allowlist
    if tool_name not in AGENT_TOOLS:
        return ToolResult(
            tool=tool_name,
            status="error",
            output=None,
            error_type=ToolErrorType.TOOL_NOT_ALLOWED,
            latency_ms=0,
            error_msg=f"工具 {tool_name!r} 不在 allowlist",
        )

    spec = AGENT_TOOLS[tool_name]

    # 2) R5-B Phase 2A: context 权限校验 (早于 schema 校验)
    permission_err = _check_permission_context(spec, context)
    if permission_err:
        return ToolResult(
            tool=tool_name,
            status="error",
            output=None,
            error_type=ToolErrorType.PRIVACY_VIOLATION,
            latency_ms=0,
            error_msg=permission_err,  # 只含权限名 + 风险级别, 不含 args
        )

    # 3) R5-B Phase 2A: schema 校验 (type / required / properties / items / min/max)
    validation_err = _validate_required_args(spec, args)
    if validation_err:
        return ToolResult(
            tool=tool_name,
            status="error",
            output=None,
            error_type=ToolErrorType.TOOL_ARGS_INVALID,
            latency_ms=0,
            error_msg=validation_err,  # 只含字段名 + 类型摘要, 不含 args 原文
        )

    # 4) 计时 + 执行
    t0 = time.time()
    try:
        output = spec.callable(**args)
    except TypeError as e:
        # args 缺失或类型错 — 例如少传了 required 参数(spec 校验后剩余的边界情况)
        latency_ms = int((time.time() - t0) * 1000)
        return ToolResult(
            tool=tool_name,
            status="error",
            output=None,
            error_type=ToolErrorType.TOOL_ARGS_INVALID,
            latency_ms=latency_ms,
            error_msg=f"TypeError: {type(e).__name__}",  # 不含 args 原文
        )
    except Exception as e:
        # 工具内部异常 — 包含 ValueError, RuntimeError, KeyError, ...
        latency_ms = int((time.time() - t0) * 1000)
        return ToolResult(
            tool=tool_name,
            status="error",
            output=None,
            error_type=ToolErrorType.TOOL_RUNTIME_ERROR,
            latency_ms=latency_ms,
            error_msg=f"{type(e).__name__}: {type(e).__name__}",  # 只含异常类型名
        )

    latency_ms = int((time.time() - t0) * 1000)
    return ToolResult(
        tool=tool_name,
        status="success",
        output=output,
        error_type=None,
        latency_ms=latency_ms,
    )


def list_tools() -> list[str]:
    """返回所有已注册工具名(供 UI / 测试枚举)— 顺序按注册顺序"""
    return list(AGENT_TOOLS.keys())


def get_tool_spec(tool_name: str) -> Optional[ToolSpec]:
    """拿工具元数据(供测试 / 调试)— 不存在返 None"""
    return AGENT_TOOLS.get(tool_name)


def affects_preview(tool_name: str) -> bool:
    """
    R5-B Phase 2A: 判断工具是否"实际影响 preview 输出" (round5-b-agent-capability-spec.md §3.3).

    规则:
      - 取 ToolSpec.metadata["affects_preview"]
      - 默认 False(展示型工具调用, output 未被 build_sections 实际消费)
      - True 例: retrieve_evidence (output 注入 build_sections → rewrite_highlights)

    用法 (在 core.agent_workflow):
      tools_used = [t for t in executed_tools if affects_preview(t)]
    """
    spec = AGENT_TOOLS.get(tool_name)
    if spec is None:
        return False
    return bool(spec.metadata.get("affects_preview", False))
