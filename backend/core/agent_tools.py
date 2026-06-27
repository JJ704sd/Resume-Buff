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

注意:
  - 本模块不引入任何 LLM 调用,纯工具注册 / 调用包装
  - 导入 jd_parser / llm_rewriter 是稳定的下游,无循环依赖风险
  - Phase 1 不在 ToolResult 里存 args / input 原文(隐私)
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from core.jd_parser import (
    evaluate_bullet_jd_match,
    match_score,
    parse_jd,
)
from core.llm_rewriter import rewrite_highlights


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
      input_schema - 输入 schema 描述(dict,Phase 1 不强校验)
    """
    name: str
    callable: Callable[..., Any]
    permission: str
    pii_risk: str
    timeout_ms: int
    input_schema: Optional[dict] = None


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
# 首批 4 个工具:
#   - parse_jd                    : 结构化抽取 JD 的硬性要求 / 关键词
#   - match_score                 : JD ↔ 素材库匹配打分(返回 score + coverage)
#   - evaluate_bullet_jd_match    : 内容理解 — 单条 bullet 对 JD 关键词覆盖度
#   - rewrite_highlights          : 生成与编辑 — 改写 bullets
#
# 后续 P2 可能加:
#   - retrieve_materials          : 检索 — 从素材库找候选 evidence(Phase 3 RAG 时接入)
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
                "role": {"type": "string"},
                "materials": {"type": "object"},
            },
            "required": ["text", "role", "materials"],
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
            },
            "required": ["highlights", "target_role"],
        },
    ),
}


# ----------------------------------------------------------------------
# 统一执行入口
# ----------------------------------------------------------------------
def execute_agent_tool(
    tool_name: str,
    args: Optional[dict] = None,
    context: Optional[dict] = None,
) -> ToolResult:
    """
    工具执行统一入口(对齐 spec §5.1)

    流程:
      1. allowlist 校验: tool_name 不在 AGENT_TOOLS → TOOL_NOT_ALLOWED
      2. 计时
      3. 调 spec.callable(**args) — 失败也返 ToolResult,绝不抛
      4. TypeError  → TOOL_ARGS_INVALID(args 类型 / 名字错)
      5. 其他异常   → TOOL_RUNTIME_ERROR

    Args:
        tool_name:  工具名(必须在 AGENT_TOOLS)
        args:       工具调用参数 dict(传 None 等价于 {})
        context:    调用上下文(暂未使用,预留—Phase 2 可能用于 trace 注入)

    Returns:
        ToolResult(status="success"|"error", output / error_type / latency_ms / ...)
        **绝不抛异常**

    隐私(对齐 spec §6.4):
      - ToolResult 不存 args 原文(本模块不缓存)
      - error_msg 仅含异常类型名,不含 args 内容
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

    # 2) 计时 + 执行
    t0 = time.time()
    try:
        output = spec.callable(**args)
    except TypeError as e:
        # args 缺失或类型错 — 例如少传了 required 参数
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
