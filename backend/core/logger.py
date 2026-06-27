"""
本地日志模块(轻量,Round 1 满足"监测/监控"基础需求)

记录:每次 generate 调用
格式: [ISO 时间] role=xxx intention=xxx filename=xxx size=xxx status=xxx [template=xxx]

R4-A: 新增 log_agent_trace — 写 agent loop 推理链路 trace(纯文本)
  格式: [ISO 时间] session=xxx step=N tool=xxx latency_ms=N outcome=xxx
  路径: backend/logs/agent_trace.log(独立日志,不混 generation.log)
  隐私: 不写 message content / bullet 内容,只写 session_id + step + 工具名 + 延迟 + 结果

R5-A Phase 2: 新增 log_agent_trace_jsonl — 结构化 JSONL trace(可被 replay 脚本解析)
  格式: 一行一个 JSON 对象,字段固定 schema(spec §7.1)
    ts / request_id / session_id / workflow / step / tool /
    latency_ms / status / error_type / input_size / output_size
  路径: backend/logs/agent_trace.jsonl(跟 agent_trace.log 并存,新格式)
  隐私: 不写完整 JD / 完整 bullet / 简历内容 / 姓名 / 邮箱 / 电话 / session 内容
        只写长度(input_size/output_size)+ 工具名 + 错误分类
  失败策略: 写入失败(磁盘满 / IO 错 / 解码错)必须静默降级,绝不影响 preview/generate 主流程
"""
import json
from datetime import datetime
from pathlib import Path

LOG_PATH = Path(__file__).parent.parent / "logs" / "generation.log"
LOG_PATH.parent.mkdir(exist_ok=True)

# R4-A: agent trace 独立日志(跟 generation.log 分离,便于专项分析)
AGENT_TRACE_PATH = Path(__file__).parent.parent / "logs" / "agent_trace.log"

# R5-A Phase 2: 结构化 JSONL trace(供 scripts/replay_agent_trace.py 解析)
AGENT_TRACE_JSONL_PATH = Path(__file__).parent.parent / "logs" / "agent_trace.jsonl"


# JSONL trace event 的稳定 schema(spec §7.1 + Phase 2 任务约定)
# 故意保持字符串/数字/None,不存 dict / list — 防止下游误用
JSONL_TRACE_FIELDS = (
    "ts",
    "request_id",
    "session_id",
    "workflow",
    "step",
    "tool",
    "latency_ms",
    "status",
    "error_type",
    "input_size",
    "output_size",
)


def _safe_int(value, default: int = 0) -> int:
    """安全转 int(防止 None / 字符串入参)— 失败返 default"""
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_str(value, default: str = "") -> str:
    """安全转 str(防止 None 入参)— 失败返 default"""
    if value is None:
        return default
    try:
        return str(value)
    except Exception:
        return default


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


# ----------------------------------------------------------------------
# R5-A Phase 2: 结构化 JSONL trace(供 replay 脚本解析)
# ----------------------------------------------------------------------
def log_agent_trace_jsonl(event: dict) -> None:
    """R5-A Phase 2: 写一条结构化 JSONL trace 到 backend/logs/agent_trace.jsonl

    Schema 固定(spec §7.1 + Phase 2 任务约定):
      ts            - ISO 时间(自动补,调用方不传)
      request_id    - 一次 preview/generate 的唯一 id(短 uuid,前缀 "r")
      session_id    - 多轮 session id(短 uuid,前缀 "s");空时为 ""
      workflow      - "preview" | "generate"
      step          - int,0-indexed 步骤序号(本地步骤也写,但 tool=None)
      tool          - 工具名(str);本地步骤时为 None(序列化为 null)
      latency_ms    - int,本步耗时(本地步骤也写 0)
      status        - "success" | "error" | "skipped"
      error_type    - 错误分类(str,成功时为 None → 序列化为 null)
      input_size    - int,入参长度(字符串字节数);本地步骤写 0
      output_size   - int,出参长度(字符串字节数);本地步骤写 0

    写入策略:
      - append 模式(同一文件持续追加,每次一行 JSON)
      - 调用方传 event 时缺 ts 字段会自动补(datetime.now ISO 到秒)
      - 缺字段一律用空值填充,绝不抛 KeyError(spec §6.3 可靠性)
      - 写入失败(磁盘满 / 权限错 / 编码错)→ try/except 静默吞掉
        **绝不影响 preview/generate 主流程**(spec §6.3)

    隐私边界(spec §6.4):
      - event 字典里禁止出现完整 JD / bullet / 简历内容字段
      - 调用方负责只传长度(input_size / output_size)而非原文
      - 任何 PII 字段(姓名/邮箱/电话/session 内容)由调用方提前剔除
    """
    if not isinstance(event, dict):
        # 防御性:调用方传错类型 → 静默忽略,绝不抛(spec §6.3)
        return

    # 1) 稳定 schema 字段填充(缺的字段用 None / 0 / "" 默认)
    safe_event: dict = {}
    safe_event["ts"] = _safe_str(event.get("ts") or datetime.now().isoformat(timespec="seconds"))
    safe_event["request_id"] = _safe_str(event.get("request_id"))
    safe_event["session_id"] = _safe_str(event.get("session_id"))
    safe_event["workflow"] = _safe_str(event.get("workflow"))
    safe_event["step"] = _safe_int(event.get("step"), 0)
    # tool 可能是 None(本地步骤)— 保留 None,JSON 序列化为 null
    tool_val = event.get("tool")
    safe_event["tool"] = _safe_str(tool_val) if tool_val is not None else None
    safe_event["latency_ms"] = _safe_int(event.get("latency_ms"), 0)
    safe_event["status"] = _safe_str(event.get("status"))
    # error_type 也允许 None(成功时)
    et_val = event.get("error_type")
    safe_event["error_type"] = _safe_str(et_val) if et_val is not None else None
    safe_event["input_size"] = _safe_int(event.get("input_size"), 0)
    safe_event["output_size"] = _safe_int(event.get("output_size"), 0)

    # 2) 序列化 + 写入(失败静默降级)
    try:
        line = json.dumps(safe_event, ensure_ascii=False, separators=(",", ":"))
        AGENT_TRACE_JSONL_PATH.parent.mkdir(exist_ok=True)
        with open(AGENT_TRACE_JSONL_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        # 任何 IO / 编码 / 序列化错误 → 静默吞掉
        # spec §6.3: trace 写失败不能影响主流程
        return