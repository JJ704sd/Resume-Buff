"""
本地日志模块(轻量,Round 1 满足"监测/监控"基础需求)

记录:每次 generate 调用
格式: [ISO 时间] role=xxx intention=xxx filename=xxx size=xxx status=xxx [template=xxx]

R4-A: 新增 log_agent_trace — 写 agent loop 推理链路 trace
  格式: [ISO 时间] session=xxx step=N tool=xxx latency_ms=N outcome=xxx
  路径: backend/logs/agent_trace.log(独立日志,不混 generation.log)
  隐私: 不写 message content / bullet 内容,只写 session_id + step + 工具名 + 延迟 + 结果
"""
from datetime import datetime
from pathlib import Path

LOG_PATH = Path(__file__).parent.parent / "logs" / "generation.log"
LOG_PATH.parent.mkdir(exist_ok=True)

# R4-A: agent trace 独立日志(跟 generation.log 分离,便于专项分析)
AGENT_TRACE_PATH = Path(__file__).parent.parent / "logs" / "agent_trace.log"


def log_generation(
    role: str,
    intention: str,
    filename: str,
    size_bytes: int,
    status: str = "success",
    template: str = "classic",
    academic_layout: str | None = None,  # R3-M.3 新增,仅 template=academic 时有意义
) -> None:
    """写入一行 generation log(template 默认 classic,Round 3 J 新增)

    R3-M.3: academic_layout 在 template=academic 时附加到日志末尾 (academic_layout=detailed),
    其他模板不附加(保持日志字节级一致,避免破坏现有 log 解析测试)。
    """
    ts = datetime.now().isoformat(timespec="seconds")
    extra = f" academic_layout={academic_layout}" if (template == "academic" and academic_layout) else ""
    line = (
        f"[{ts}] role={role} intention={intention} "
        f"file={filename} size={size_bytes}B status={status} "
        f"template={template}{extra}\n"
    )
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line)


def log_agent_trace(
    session_id: str,
    step: int,
    tool_name: str,
    latency_ms: int,
    outcome: str,
) -> None:
    """R4-A: 写一行 agent loop trace 到 backend/logs/agent_trace.log

    格式: [ISO 时间] session=xxx step=N tool=xxx latency_ms=N outcome=xxx

    Args:
        session_id:  短串 id(本地单用户,R4-M 接入 session 模块后会有真正的 session)
        step:        当前 step 序号(0-indexed,MAX_AGENT_STEPS 范围内)
        tool_name:   工具名(本轮调用的工具,无工具时为 "no_tool")
        latency_ms:  本次 LLM call + 工具执行的累计延迟(毫秒)
        outcome:     结果标签:
                       - success_rewrite: 成功拿到 rewritten,流程结束
                       - tool_executed:   成功执行工具,继续 loop
                       - network_error_fallback: 网络错误,降级原文
                       - schema_fail_fallback:   解析失败,降级原文
                       - max_step_exhausted:     MAX_AGENT_STEPS 用完仍无 output

    隐私:
      - 不写 message content / bullet 内容(避免 PII 泄漏)
      - session_id 由 R4-A 临时生成(per-call 短串),R4-M 接入真正的 session 后会复用
      - 失败错误堆栈也不写(避免泄漏代码路径)

    写入策略:
      - append 模式(同 generation.log),方便增量观察
      - 文件不存在时由 Path.parent.mkdir 自动创建
    """
    ts = datetime.now().isoformat(timespec="seconds")
    line = (
        f"[{ts}] session={session_id} step={step} "
        f"tool={tool_name} latency_ms={latency_ms} outcome={outcome}\n"
    )
    with open(AGENT_TRACE_PATH, "a", encoding="utf-8") as f:
        f.write(line)