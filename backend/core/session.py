"""
R4-M: 进程内 Session 记忆(短期 memory)

设计原则(MVP):
  - **进程内** dict + deque 存储, 进程退出即丢(本地单用户约束)
  - **不持久化**(无 sqlite / redis), 适合 MVP demo
  - **线程不安全**(GIL 下单线程 ok, 多 worker uvicorn 需加锁 — P2)
  - **无 TTL**(进程退出即丢, 够了)
  - **deque maxlen=10**(MVP 上限, 防止长期跑内存膨胀)

公开 API(4 个):
  - create_session()           -> session_id  (uuid 短串)
  - get_messages(session_id)   -> list[dict]  (返回拷贝, 防止外部修改污染)
  - append_message(session_id, role, content, tool_calls=None)
  - clear_session(session_id)

隐私:
  - session 内容不写日志(只写 session_id + 步数到 trace, 避免 PII 泄漏)
  - session 内容由调用方(API 层)负责不写 PII 到 content 字段

集成:
  - rewrite_highlights 接受 session_id 参数, 挂上后从 get_messages 拉历史 messages 拼到 LLM messages
  - 上限 10 条(单 user/assistant/tool message 各算 1)
"""
import uuid
from collections import deque
from typing import Optional


# ----------------------------------------------------------------------
# 常量
# ----------------------------------------------------------------------
# MVP 上限: 单 session 最多 10 条消息(超出自动 FIFO 弹出老消息)
# 选 10: 平衡"够用"和"防内存膨胀" — 5 轮对话 * (user + assistant) = 10
MAX_SESSION_MESSAGES = 10


# ----------------------------------------------------------------------
# 全局存储(进程内, 线程不安全)
# ----------------------------------------------------------------------
# 类型: dict[str, deque[dict]]
# key   = session_id (uuid 短串)
# value = deque({role, content, tool_calls?}, maxlen=MAX_SESSION_MESSAGES)
#
# 线程不安全说明:
#   - 单进程单线程 OK(GIL 保护 dict 读写原子性)
#   - uvicorn 多 worker 时各 worker 独立 — session 不跨 worker 共享(MVP 接受)
#   - 同 worker 多线程并发时 dict[deque] 操作可能丢更新 — 未来加 threading.Lock(P2)
_SESSIONS: dict[str, deque] = {}


def create_session() -> str:
    """
    创建新 session, 返回 session_id(uuid 8 位短串)。

    短串设计:
      - 8 hex = 4 bytes 随机空间, 32 bit 熵 — 足够本地单用户区分
      - 比 uuid4() 短一半(36 -> 8 字符), API 传输更轻
      - 仍保留时间戳前缀 's' 便于人眼区分 session_id vs 其他 id
    """
    session_id = "s" + uuid.uuid4().hex[:8]
    # 创建空 deque(maxlen 限制, 满了自动弹出老的)
    _SESSIONS[session_id] = deque(maxlen=MAX_SESSION_MESSAGES)
    return session_id


def get_messages(session_id: str) -> list[dict]:
    """
    拿 session 的所有 messages(返回 list 拷贝, 外部修改不影响内部 deque)。

    Args:
        session_id:  create_session() 返回的 id

    Returns:
        list[dict] — 形如 [{"role": "user", "content": "..."}, ...]
        session_id 不存在时返空 list(不抛, 允许 LLM call 静默继续)
    """
    if not session_id or session_id not in _SESSIONS:
        return []
    # 返 list(deque) 的浅拷贝 — 防外部直接改 deque
    return list(_SESSIONS[session_id])


def append_message(
    session_id: str,
    role: str,
    content: str,
    tool_calls: Optional[list[dict]] = None,
) -> None:
    """
    追加一条 message 到 session 尾部。

    Args:
        session_id:  create_session() 返回的 id
        role:        "user" | "assistant" | "tool" | "system"
        content:     消息内容(str;tool message 序列化 JSON)
        tool_calls:  可选, assistant 消息含 tool_calls 时填

    Note:
        - session_id 不存在时**静默忽略**(不抛, 避免上层 build_sections 报错)
        - 超过 MAX_SESSION_MESSAGES 时 deque 自动弹出最老的
    """
    if not session_id or session_id not in _SESSIONS:
        return  # 静默忽略, MVP 简化
    msg: dict = {"role": role, "content": content}
    if tool_calls is not None:
        msg["tool_calls"] = tool_calls
    _SESSIONS[session_id].append(msg)


def clear_session(session_id: str) -> None:
    """
    清空指定 session 的所有 messages(deque 保留, 只是内容清空)。

    Args:
        session_id:  create_session() 返回的 id
    Note:
        - session_id 不存在时静默忽略
        - 不删 _SESSIONS 字典项(避免重建 deque 的开销, 也保留 maxlen)
    """
    if not session_id or session_id not in _SESSIONS:
        return
    _SESSIONS[session_id].clear()


def session_exists(session_id: str) -> bool:
    """检查 session_id 是否存在(供测试/调试用, MVP 不会主动调)"""
    return bool(session_id) and session_id in _SESSIONS
