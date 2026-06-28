"""
R5-A Phase 2: 结构化 JSONL Agent Trace Replay 脚本
R5-C Phase 5: 加 fallback category 摘要 + tools_used 交叉验证

用途:
  按 request_id 或 session_id 拉出 backend/logs/agent_trace.jsonl 中的一次 workflow
  所有 step,生成 markdown 风格的摘要(只含指标 / 工具名 / 错误分类,不输出任何
  原文 / JD / bullet / 简历内容 / PII)。

用法:
  # 按 request_id 拉(单次 workflow)
  python scripts/replay_agent_trace.py --request-id r12345678

  # 按 session_id 拉(可能多次 workflow 跨多轮对话)
  python scripts/replay_agent_trace.py --session-id sabcdef12

  # 自定义 jsonl 路径
  python scripts/replay_agent_trace.py --request-id r12345678 \\
        --path backend/logs/agent_trace.jsonl

  # R5-C Phase 5: 交叉验证 tools_used (跟外部报告 agent_summary.tools_used 对账)
  python scripts/replay_agent_trace.py --request-id r12345678 \\
        --tools-used retrieve_evidence,parse_jd

输出格式(markdown):
  # Agent Trace Replay
  - request_id: r12345678
  - workflow:   preview
  - session_id: sabcdef12
  - steps:      5
  - total_latency_ms: 124

  | step | tool | latency_ms | status | error_type | input_size | output_size |
  |------|------|------------|--------|------------|------------|-------------|
  | 0    | (local) | 0 | skipped |  | 0 | 0 |
  | 1    | parse_jd | 18 | success |  | 1234 | 812 |
  ...

  ## Fallback Summary
  - category:     none
  - error_steps:  0
  - tool_errors:  []

  ## Tools Cross-Validation (R5-C Phase 5)
  - expected:     retrieve_evidence, parse_jd
  - observed:     retrieve_evidence, parse_jd
  - matched:      retrieve_evidence, parse_jd
  - missing:      []
  - unexpected:   []

设计原则:
  - **隐私优先**: 只读 JSONL 中固定 schema 字段(ts / request_id / session_id /
    workflow / step / tool / latency_ms / status / error_type / input_size /
    output_size);绝不打印任何原文 / dict body
  - **容错**: 文件不存在 / 单行损坏 / 字段缺失都不抛,降级跳过
  - **零依赖**: 只用 Python stdlib(json / argparse / pathlib),无第三方包
  - **本地单用户**: 不联网,只读本地 jsonl
  - **R5-C Phase 5**: 加 fallback category 摘要(本地推断,自包含)+ tools_used 交叉
    验证(可选,显式传 --tools-used 才输出)— 仍只输出 schema 字段,不泄漏原文
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Iterable


# JSONL schema 字段(对齐 core/logger.JSONL_TRACE_FIELDS)
TRACE_FIELDS = (
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

# 渲染表格列顺序(摘要友好,不含原文敏感字段)
TABLE_COLUMNS = (
    "step",
    "tool",
    "latency_ms",
    "status",
    "error_type",
    "input_size",
    "output_size",
)

# R5-C Phase 5: fallback category 分类常量(对齐 spec §2.2)
# trace 里只能直接推断 none / tool_error_fallback;其他类别(llm_disabled /
# schema_retry / workflow_abort)依赖 trace 外信息,这里统一标 unknown 让 caller
# 知道 trace 信号不足以分类。
FALLBACK_CATEGORY_NONE = "none"
FALLBACK_CATEGORY_TOOL_ERROR = "tool_error_fallback"
FALLBACK_CATEGORY_UNKNOWN = "unknown (trace 信号不足, 需查 agent_summary)"

# R5-C Phase 5: tools_used 交叉验证结果状态常量
CROSS_VALIDATE_OK = "ok"
CROSS_VALIDATE_MISSING = "missing"
CROSS_VALIDATE_UNEXPECTED = "unexpected"
CROSS_VALIDATE_EMPTY = "empty"


def _read_jsonl(path: Path) -> Iterable[dict]:
    """
    逐行读 JSONL,坏行(解析失败 / 空行)静默跳过,绝不抛。

    Yields:
        dict - 解析成功的事件;坏行被忽略
    """
    if not path.exists():
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    # 单行损坏不阻断(append-only 文件可能被人为编辑)
                    continue
                if isinstance(event, dict):
                    yield event
    except OSError:
        # 文件权限 / IO 错 → 视作空
        return


def filter_events(
    events: Iterable[dict],
    *,
    request_id: str | None,
    session_id: str | None,
) -> list[dict]:
    """
    按 request_id / session_id 过滤事件。

    - request_id 优先: 严格匹配(单次 workflow)
    - session_id: 匹配所有同 session 的 workflow(MVP 用法)
    - 二者都给 → request_id 优先(session_id 仅作交叉校验/备注)
    - 都不给 → 返空列表(spec: 必须显式选 ID,避免误输出全量)
    """
    if not request_id and not session_id:
        return []

    matched: list[dict] = []
    for ev in events:
        if request_id and ev.get("request_id") == request_id:
            matched.append(ev)
        elif session_id and ev.get("session_id") == session_id:
            matched.append(ev)
    # 按 ts + step 排序(让 replay 顺序稳定)
    matched.sort(key=lambda e: (str(e.get("ts") or ""), int(e.get("step") or 0)))
    return matched


def render_markdown(events: list[dict]) -> str:
    """
    把 events 列表渲染成 markdown 摘要。

    输出包含:
      - 顶部 4 行: request_id / workflow / session_id / steps / total_latency_ms
      - 表格: step / tool / latency_ms / status / error_type / input_size / output_size
      - 错误汇总: status=error 的 event 列表(只含工具名 + 错误分类)
      - R5-C Phase 5: Fallback Summary 段 — 含本地推断的 category + error_steps 计数

    隐私: 仅渲染 schema 字段,不打印任何原文 / dict body

    多 workflow 处理:
      - 当 events 跨多个 request_id 或 workflow(典型场景: 按 session_id 拉)
        顶部 summary 显示 "multiple (N)" 而不是只显示第一个,避免误导
    """
    if not events:
        return "# Agent Trace Replay\n\n(无匹配事件)\n"

    # 1) 顶部摘要 — 统计唯一 request_id / workflow
    unique_request_ids = sorted({e.get("request_id", "") for e in events})
    unique_workflows = sorted({e.get("workflow", "") for e in events})
    unique_sessions = sorted({e.get("session_id", "") for e in events})

    # request_id: 单值显示, 多值显示列表(防止顶部 summary 误导)
    if len(unique_request_ids) == 1:
        request_id_display = f"`{unique_request_ids[0]}`"
    else:
        ids_csv = ", ".join(f"`{r}`" for r in unique_request_ids if r)
        request_id_display = f"multiple ({ids_csv})"
    # workflow / session 同理
    if len(unique_workflows) == 1:
        workflow_display = f"`{unique_workflows[0]}`"
    else:
        workflow_display = ", ".join(f"`{w}`" for w in unique_workflows if w)
    if len(unique_sessions) == 1:
        session_id_display = f"`{unique_sessions[0]}`"
    else:
        ss_csv = ", ".join(f"`{s}`" for s in unique_sessions if s)
        session_id_display = f"multiple ({ss_csv})"

    total_latency = sum(int(e.get("latency_ms") or 0) for e in events)
    tools_used = sorted({
        str(e.get("tool")) for e in events
        if e.get("tool") is not None
    })

    lines: list[str] = []
    lines.append("# Agent Trace Replay")
    lines.append("")
    lines.append(f"- request_id:       {request_id_display}")
    lines.append(f"- workflow:         {workflow_display}")
    lines.append(f"- session_id:       {session_id_display}")
    lines.append(f"- steps:            {len(events)}")
    lines.append(f"- total_latency_ms: {total_latency}")
    if tools_used:
        lines.append(f"- tools_used:       {', '.join(tools_used)}")
    lines.append("")

    # 2) 主表格
    header = "| " + " | ".join(TABLE_COLUMNS) + " |"
    sep = "| " + " | ".join("---" for _ in TABLE_COLUMNS) + " |"
    lines.append(header)
    lines.append(sep)
    for ev in events:
        row: list[str] = []
        for col in TABLE_COLUMNS:
            val = ev.get(col)
            if val is None:
                row.append("")
            elif col == "tool":
                # 本地步骤 tool 为 None → 显示 (local) 标识
                row.append("(local)" if val is None else str(val))
            else:
                row.append(str(val))
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")

    # 3) 错误汇总(只含工具名 + 错误分类,不输出 error_msg / args 原文)
    error_events = [e for e in events if e.get("status") == "error"]
    if error_events:
        lines.append("## Errors")
        lines.append("")
        for e in error_events:
            tool = e.get("tool") or "(local)"
            et = e.get("error_type") or "(none)"
            step = e.get("step", "?")
            lines.append(f"- step={step} tool={tool} error_type={et}")
        lines.append("")

    # 4) R5-C Phase 5: Fallback Summary 段
    #    基于 trace 自身 status/error_type 推断 category (只覆盖 none/tool_error)
    #    其他类别(llm_disabled/schema_retry/workflow_abort)依赖 trace 外信息,
    #    标 unknown 提示 caller 查 agent_summary(spec §2.2)
    fb_summary = summarize_fallback(events)
    lines.append("## Fallback Summary")
    lines.append("")
    lines.append(f"- category:    `{fb_summary['category']}`")
    lines.append(f"- error_steps: {fb_summary['error_count']}")
    if fb_summary["tool_errors"]:
        lines.append("- tool_errors:")
        for e in fb_summary["tool_errors"]:
            lines.append(f"  - step={e['step']} tool={e['tool']} error_type={e['error_type']}")
    else:
        lines.append("- tool_errors: (none)")
    lines.append("")

    return "\n".join(lines)


# ----------------------------------------------------------------------
# R5-C Phase 5: fallback category 推断 + tools_used 交叉验证
# ----------------------------------------------------------------------
def summarize_fallback(events: list[dict]) -> dict:
    """
    从 trace events 推断 fallback 摘要。

    Returns:
        dict {
            "category":     str (none / tool_error_fallback / unknown),
            "error_count":  int (status=error 的 step 数),
            "tool_errors":  list[dict] (只含 step / tool / error_type,不含原文),
        }

    限制(spec §2.2):
      - trace 不含 agent_summary,无法直接读 fallback_reason
      - llm_disabled / schema_retry / workflow_abort 三类需 agent_summary 才能分类
      - 本函数只能准确区分 none / tool_error_fallback;其余归 unknown

    隐私: 仅从 trace 11 个 schema 字段读,绝不输出原文 / JD / bullet。
    """
    error_events = [
        e for e in events
        if e.get("status") == "error"
    ]

    if not error_events:
        category = FALLBACK_CATEGORY_NONE
    else:
        # trace 里至少有一个 status=error → 推断为 tool_error_fallback
        # 注: required step 失败会导致 workflow 主循环抛异常,workflow 走 fallback
        # 路径, 但 trace 仍可能写出 status=error 的 step;这里统一归 tool_error
        # (区分不出来 workflow_abort vs tool_error,除非读 agent_summary)
        category = FALLBACK_CATEGORY_TOOL_ERROR

    tool_errors = [
        {
            "step": e.get("step", "?"),
            "tool": e.get("tool") or "(local)",
            "error_type": e.get("error_type") or "(none)",
        }
        for e in error_events
    ]

    return {
        "category": category,
        "error_count": len(error_events),
        "tool_errors": tool_errors,
    }


def cross_validate_tools_used(
    events: list[dict],
    expected_tools: list[str] | None,
) -> dict:
    """
    R5-C Phase 5: 把 caller 给的 expected_tools (如 agent_summary.tools_used)
    跟 trace 里实际记录的 tool 调用做交叉验证。

    Args:
        events:         filter_events 返回的事件列表
        expected_tools: caller 提供的工具名列表 (caller 通常来自 agent_summary)

    Returns:
        dict {
            "expected":     list[str],
            "observed":     list[str] (trace 里实际出现的有序去重),
            "matched":      list[str] (expected ∩ observed),
            "missing":      list[str] (expected - observed),
            "unexpected":   list[str] (observed - expected),
            "status":       str (ok / missing / unexpected / empty),
        }

    隐私: 仅比对工具名字符串, 不接触 args / JD / bullet 原文。
    """
    if not expected_tools:
        return {
            "expected": [],
            "observed": _observed_tools(events),
            "matched": [],
            "missing": [],
            "unexpected": [],
            "status": CROSS_VALIDATE_EMPTY,
        }

    expected_set = set(expected_tools)
    observed = _observed_tools(events)
    observed_set = set(observed)
    matched = sorted(expected_set & observed_set)
    missing = sorted(expected_set - observed_set)
    unexpected = sorted(observed_set - expected_set)

    if missing and unexpected:
        status = CROSS_VALIDATE_MISSING  # 同时 missing + unexpected 也标 missing
    elif missing:
        status = CROSS_VALIDATE_MISSING
    elif unexpected:
        status = CROSS_VALIDATE_UNEXPECTED
    else:
        status = CROSS_VALIDATE_OK

    return {
        "expected": list(expected_tools),
        "observed": observed,
        "matched": matched,
        "missing": missing,
        "unexpected": unexpected,
        "status": status,
    }


def _observed_tools(events: list[dict]) -> list[str]:
    """
    从 events 里按调用顺序提取去重的工具名列表(跳过本地步骤 tool=None)。
    仅接受 str 类型的 tool, 非 str(数字 / dict / 列表等)跳过(spec: 工具名是 schema 固定 str)。
    """
    seen: set[str] = set()
    ordered: list[str] = []
    for ev in events:
        t = ev.get("tool")
        if not isinstance(t, str) or t == "":
            continue
        if t not in seen:
            seen.add(t)
            ordered.append(t)
    return ordered


def render_tools_cross_validation(cross: dict) -> list[str]:
    """
    把 cross_validate_tools_used 的结果渲染成 markdown 行列表。
    不输出原文 / dict body, 只显示工具名字符串。

    caller 通常在 main() 里:
        cross = cross_validate_tools_used(events, expected_tools)
        if cross['status'] != CROSS_VALIDATE_EMPTY:
            lines.extend(render_tools_cross_validation(cross))
    """
    lines: list[str] = []
    if cross["status"] == CROSS_VALIDATE_EMPTY:
        return lines

    lines.append("## Tools Cross-Validation (R5-C Phase 5)")
    lines.append("")
    expected_str = ", ".join(f"`{t}`" for t in cross["expected"]) or "(none)"
    observed_str = ", ".join(f"`{t}`" for t in cross["observed"]) or "(none)"
    matched_str = ", ".join(f"`{t}`" for t in cross["matched"]) or "(none)"
    missing_str = ", ".join(f"`{t}`" for t in cross["missing"]) or "(none)"
    unexpected_str = ", ".join(f"`{t}`" for t in cross["unexpected"]) or "(none)"

    lines.append(f"- status:     `{cross['status']}`")
    lines.append(f"- expected:   {expected_str}")
    lines.append(f"- observed:   {observed_str}")
    lines.append(f"- matched:    {matched_str}")
    lines.append(f"- missing:    {missing_str}")
    lines.append(f"- unexpected: {unexpected_str}")
    lines.append("")
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="按 request_id / session_id 拉出 JSONL trace 并生成 markdown 摘要",
    )
    parser.add_argument(
        "--request-id",
        type=str,
        default=None,
        help="单次 workflow 的 request_id(短 uuid,前缀 'r')",
    )
    parser.add_argument(
        "--session-id",
        type=str,
        default=None,
        help="多轮 session 的 session_id(短 uuid,前缀 's')",
    )
    parser.add_argument(
        "--path",
        type=str,
        default=None,
        help="JSONL trace 文件路径(默认 backend/logs/agent_trace.jsonl)",
    )
    parser.add_argument(
        "--tools-used",
        type=str,
        default=None,
        help=(
            "R5-C Phase 5: 期望的 tools_used 列表(逗号分隔),"
            "跟 trace 实际记录做交叉验证, 不传则不输出 Cross-Validation 段。"
            "典型用法: 跟 evaluate_agent_workflow.py 输出的 agent_summary.tools_used 对账。"
        ),
    )
    args = parser.parse_args(argv)

    # 至少给一个 id(避免误输出全量)
    if not args.request_id and not args.session_id:
        parser.error("必须至少传 --request-id 或 --session-id 之一")

    # 默认路径(相对 cwd 解析,容忍 user 从仓库根目录跑)
    if args.path:
        trace_path = Path(args.path)
    else:
        # 脚本在 scripts/,默认指向 backend/logs/agent_trace.jsonl
        # 用 __file__ 的 parent.parent 推断 backend/ 位置
        backend_dir = Path(__file__).resolve().parent.parent / "backend"
        trace_path = backend_dir / "logs" / "agent_trace.jsonl"

    events_iter = _read_jsonl(trace_path)
    events = filter_events(
        events_iter,
        request_id=args.request_id,
        session_id=args.session_id,
    )
    md = render_markdown(events)

    # R5-C Phase 5: 可选 tools_used 交叉验证段
    if args.tools_used:
        expected = [t.strip() for t in args.tools_used.split(",") if t.strip()]
        cross = cross_validate_tools_used(events, expected)
        md = md.rstrip("\n") + "\n\n" + "\n".join(render_tools_cross_validation(cross))

    sys.stdout.write(md)
    if not md.endswith("\n"):
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())