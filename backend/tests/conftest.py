# 简历帮 - pytest 配置文件
# 让 tests/ 下的测试可以直接 import core / api 模块 (把 backend/ 当 root)
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))