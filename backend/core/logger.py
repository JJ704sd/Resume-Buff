"""
本地日志模块(轻量,Round 1 满足"监测/监控"基础需求)

记录:每次 generate 调用
格式: [ISO 时间] role=xxx intention=xxx filename=xxx size=xxx status=xxx [template=xxx]
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