"""
本地日志模块(轻量,Round 1 满足"监测/监控"基础需求)

记录:每次 generate 调用
格式: [ISO 时间] role=xxx intention=xxx filename=xxx size=xxx status=xxx
"""
from datetime import datetime
from pathlib import Path

LOG_PATH = Path(__file__).parent.parent / "logs" / "generation.log"
LOG_PATH.parent.mkdir(exist_ok=True)


def log_generation(
    role: str,
    intention: str,
    filename: str,
    size_bytes: int,
    status: str = "success",
) -> None:
    """写入一行 generation log"""
    ts = datetime.now().isoformat(timespec="seconds")
    line = (
        f"[{ts}] role={role} intention={intention} "
        f"file={filename} size={size_bytes}B status={status}\n"
    )
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line)
