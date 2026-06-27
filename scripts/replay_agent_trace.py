"""
R5-A Phase 2: 结构化 JSONL Agent Trace Replay 脚本

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

设计原则:
  - **隐私优先**: 只读 JSONL 中固定 schema 字段(ts / request_id / session_id /
    workflow / step / tool / latency_ms / status / error_type / input_size /
    output_size);绝不打印任何原文 / dict body
  - **容错**: 文件不存在 / 单行损坏 / 字段缺失都不抛,降级跳过
  - **零依赖**: 只用 Python stdlib(json / argparse / pathlib),无第三方包
  - **本地单用户**: 不联网,只读本地 jsonl
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

    return "\n".join(lines)


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
    sys.stdout.write(md)
    if not md.endswith("\n"):
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())