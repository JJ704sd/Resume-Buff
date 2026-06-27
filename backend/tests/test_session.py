"""
core/session 模块测试 (R4-M: Session 记忆)

锁点(8 case):
  1. create_session 返非空字符串 id
  2. 多次 create 返不同 id(唯一性)
  3. append + get_messages 累积
  4. clear_session 清空
  5. maxlen=10 上限(超出会 FIFO 弹出老的)
  6. append_message 含 tool_calls 字段
  7. 不存在的 session_id 静默忽略(get/append/clear 不抛)
  8. session_id 为空字符串时 get 返空 list / append 静默 / clear 静默

测试策略:
  - 用 monkeypatch.clear() 隔离 _SESSIONS 全局 state
  - 每个 case 独立 setUp 避免污染
"""
import pytest

from core import session as session_mod
from core.session import (
    MAX_SESSION_MESSAGES,
    _SESSIONS,
    append_message,
    clear_session,
    create_session,
    get_messages,
    session_exists,
)


@pytest.fixture(autouse=True)
def _reset_sessions():
    """每个 test 前后清空 _SESSIONS, 避免测试间污染"""
    _SESSIONS.clear()
    yield
    _SESSIONS.clear()


class TestSessionAPI:
    """R4-M: 4 个公开 API 行为测试 — 8 case 锁死行为"""

    def test_create_session_returns_string_id(self):
        """create_session() 返非空字符串 id(短串设计: 's' + 8 hex)"""
        sid = create_session()
        assert isinstance(sid, str)
        assert sid  # 非空
        # 短串格式: 's' + 8 hex
        assert sid.startswith("s"), f"session_id 应以 's' 开头, 实际: {sid}"
        assert len(sid) == 9, f"session_id 应为 9 字符('s' + 8 hex), 实际长度: {len(sid)}"
        # session 已被创建
        assert session_exists(sid)

    def test_create_session_unique_ids(self):
        """多次 create 返不同 id(本地单用户, 但仍要唯一避免 session 互串)"""
        ids = [create_session() for _ in range(10)]
        assert len(set(ids)) == 10, f"create_session 应返唯一 id, 实际: {ids}"
        # 全部 session 都被创建
        for sid in ids:
            assert session_exists(sid)

    def test_append_and_get_messages(self):
        """append_message + get_messages 累积 messages"""
        sid = create_session()
        append_message(sid, "user", "hello")
        append_message(sid, "assistant", "hi there")
        msgs = get_messages(sid)
        assert msgs == [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there"},
        ]
        # get_messages 返 list 拷贝, 外部修改不影响内部 deque
        msgs.append({"role": "user", "content": "leak"})
        msgs2 = get_messages(sid)
        assert len(msgs2) == 2, "get_messages 应返 list 拷贝, 防止外部修改"

    def test_append_message_with_tool_calls(self):
        """append_message 接受 tool_calls 字段(可选)"""
        sid = create_session()
        tc = [{"id": "call_1", "type": "function",
               "function": {"name": "evaluate_bullet_jd_match",
                            "arguments": '{"bullet": "x"}'}}]
        append_message(sid, "assistant", None, tool_calls=tc)
        msgs = get_messages(sid)
        assert len(msgs) == 1
        assert msgs[0]["role"] == "assistant"
        assert msgs[0]["tool_calls"] == tc

    def test_maxlen_10_limit_fifo(self):
        """deque maxlen=10 上限, 超出时自动 FIFO 弹出老的"""
        sid = create_session()
        # 追加 12 条 → 应只保留最后 10 条
        for i in range(12):
            append_message(sid, "user", f"msg-{i}")
        msgs = get_messages(sid)
        assert len(msgs) == MAX_SESSION_MESSAGES == 10
        # 弹出老的两条(0, 1), 保留 (2..11)
        assert msgs[0]["content"] == "msg-2"
        assert msgs[-1]["content"] == "msg-11"

    def test_clear_session(self):
        """clear_session 清空 messages(deque 保留, 内容清空)"""
        sid = create_session()
        append_message(sid, "user", "hello")
        append_message(sid, "assistant", "hi")
        assert len(get_messages(sid)) == 2

        clear_session(sid)
        assert get_messages(sid) == []
        # session 仍然存在(deque 保留)
        assert session_exists(sid)
        # 清空后可以继续 append
        append_message(sid, "user", "after-clear")
        assert get_messages(sid) == [{"role": "user", "content": "after-clear"}]

    def test_nonexistent_session_id_silent_ignore(self):
        """不存在的 session_id: get/append/clear 全部静默不抛"""
        # get_messages 返空 list
        assert get_messages("s_notexist_xx") == []
        # append_message 静默忽略
        append_message("s_notexist_xx", "user", "leak")
        assert get_messages("s_notexist_xx") == []
        # clear_session 静默忽略(不抛)
        clear_session("s_notexist_xx")
        # session_exists 返 False
        assert not session_exists("s_notexist_xx")
        # _SESSIONS 字典仍然空
        assert len(_SESSIONS) == 0

    def test_empty_session_id_silent_ignore(self):
        """session_id 为空字符串: get/append/clear 静默不抛
        (rewrite_highlights 透传 None/空 时的边界)"""
        # 空字符串 → 跟 None 一样
        assert get_messages("") == []
        append_message("", "user", "leak")
        assert get_messages("") == []
        clear_session("")
        # _SESSIONS 仍然空
        assert len(_SESSIONS) == 0
