"""
Round 6-B Phase 4: draft verifier(spec §7)

设计原则:
  - 不调 LLM 也能跑(pure stdlib + re)+ 不读 env
  - 不 mutate session / 不写文件 / 不调网络
  - verifier 输出 / _interview_meta.verification 摘要 都不含:
      user_message / source_span 明文 / draft_card 原文 / API key / jd_text
  - unsupported_claims 不阻止保存, 只生成 warning(spec §7)
  - Phase 2 老路径(verification_summary=None)字节级一致
    —— save_card 在 session.verification_summary 为 None 时不写 verification meta

公开 API:
  - verify_draft_card(card, session) -> dict
  - compute_confidence_notes(session) -> list[str]

依赖边界(AGENTS.md + spec §13):
  - 不 import core.llm_rewriter / core.agent_workflow / core.agent_tools
  - 只 import core.interview_agent(读 InterviewSession / INTERVIEW_LOW_CONFIDENCE_THRESHOLD)
    + core.interview_prompts.SLOT_NAMES
"""
from __future__ import annotations

import re
from typing import Any

from core.interview_agent import InterviewSession
from core.interview_prompts import SLOT_NAMES

# ----------------------------------------------------------------------
# 常量(spec §7 + AGENTS.md R6-B Phase 4 锁点)
# ----------------------------------------------------------------------

# 量化数字 regex — 跟 _extract_slots_by_rules.metric 同源(plan §1.3)
# 故意保持同源, 防止 verifier 与 extractor 量化口径分裂
QUANTITATIVE_PATTERN = re.compile(
    r"(\d+(?:\.\d+)?)\s*"
    r"(人|%|倍|小时|天|次|万|个|条|例)"
)

# bullet 支持来源的 slot — spec §7 "至少有 action / responsibility / result 类来源"
# 扩展包含 method / metric, 因为 draft_bullets 通常会包含这两类内容
SOURCE_SLOT_KEYS: tuple[str, ...] = (
    "responsibility", "action", "result", "method", "metric",
)

# 隐私边界最大预览长度(warnings 摘要里截到多长, spec §7 "禁止把完整 ... draft_card 原文写入 _interview_meta")
_WARNING_BULLET_PREVIEW_LEN: int = 30

# R6-G F-2.1: verifier 内部崩溃 sentinel 提示(R6-F audit §2 review-needed)
# 当 verifier 主链路 try/except 兜成全 0 计数时, 往 warnings 里塞一条短字符串,
# 让前端 UI 看到 sentinel 提示 "我崩了, 数据不可信", 不让 unsupported=0 误导用户
# 以为 "全部 verified 通过"。文字纯状态描述, 不含 user_message / source_span /
# draft_bullets / API key / jd_text / prompt 正文(隐私边界, 沿用 spec §7)。
_VERIFIER_INTERNAL_ERROR_SENTINEL: str = "事实核验未完成, 请联系开发者或重新生成"
"""verifier 主链路 try/except 兜底时附加到 warnings 的 sentinel 字符串。

边界:
  - 纯状态描述, 不含任何字段值(无 user_message / source_span / draft_bullets / API key)
  - 前端 UI 看到 sentinel 知道 verifier 崩了, 不会误判为 "全部 verified 通过"
  - 与 INTERVIEW_LOW_CONFIDENCE_THRESHOLD 类常量同源, 纯字面量
"""

_CONFIDENCE_COLLECT_ERROR_SENTINEL: str = "置信度数据收集失败, 请联系开发者或重新生成"
"""compute_confidence_notes 内部 try/except 兜底时返的 sentinel。

边界:
  - 同 _VERIFIER_INTERNAL_ERROR_SENTINEL, 纯状态描述
  - 不含 slot 名 / confidence 数字 / source_span / user_message
"""


# ----------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------
def _collect_source_strings(captured: Any) -> list[tuple[str, str]]:
    """
    把 captured dict 的 string 字段 + list 字段的每个元素拍平成 (slot_name, str) 列表。

    边界:
      - 非 dict 输入 → 返空 list(不抛)
      - 非 string/list 字段 → 跳过
      - 空字符串 / 纯空白 → 跳过
    """
    out: list[tuple[str, str]] = []
    if not isinstance(captured, dict):
        return out
    for slot_name in SLOT_NAMES:
        val = captured.get(slot_name)
        if isinstance(val, str):
            s = val.strip()
            if s:
                out.append((slot_name, s))
        elif isinstance(val, list):
            for sub in val:
                if isinstance(sub, str):
                    s = sub.strip()
                    if s:
                        out.append((slot_name, s))
    return out


def _bullet_quantitative_in_source(
    bullet: str, sources: list[tuple[str, str]]
) -> list[str]:
    """
    抽 bullet 的量化数字 token, 看是否在 sources 任一字符串里出现。
    返命中的 token 列表(便于 caller 记录 / debug, 不入 verification 输出)。

    边界:
      - bullet 非 str → 返空 list
      - sources 空 / bullet 没量化数字 → 返空 list
    """
    if not isinstance(bullet, str) or not bullet:
        return []
    matches = QUANTITATIVE_PATTERN.findall(bullet)
    if not matches:
        return []
    tokens = [f"{num}{unit}" for num, unit in matches]
    hits: list[str] = []
    for token in tokens:
        for _, src in sources:
            if token in src:
                hits.append(token)
                break
    return hits


def _bullet_mentions_slot_source(
    bullet: str, captured: Any
) -> tuple[bool, list[str]]:
    """
    bullet 是否在 SOURCE_SLOT_KEYS 任一 slot 的字符串/list 元素里出现(子串)。

    规则:
      - bullet 是 SOURCE_SLOT_KEYS 任一 slot 字符串的子串 OR
        bullet 包含 SOURCE_SLOT_KEYS 任一 slot 字符串(去空白后) →
        视为 "有来源"
      - 兼容 string 字段 + list 字段
      - 多 slot 都匹配时全部列出

    返回:
      (bool_supported, list_of_source_slot_names — 字母序去重)

    边界:
      - bullet 非 str / 空 → 返 (False, [])
      - captured 非 dict → 返 (False, [])
    """
    if not isinstance(bullet, str) or not bullet.strip():
        return (False, [])
    if not isinstance(captured, dict):
        return (False, [])
    bullet_stripped = bullet.strip()
    matched: list[str] = []
    for slot_name in SOURCE_SLOT_KEYS:
        val = captured.get(slot_name)
        if isinstance(val, str):
            s = val.strip()
            if not s:
                continue
            if s in bullet_stripped or bullet_stripped in s:
                if slot_name not in matched:
                    matched.append(slot_name)
        elif isinstance(val, list):
            for sub in val:
                if not isinstance(sub, str):
                    continue
                s = sub.strip()
                if not s:
                    continue
                if s in bullet_stripped or bullet_stripped in s:
                    if slot_name not in matched:
                        matched.append(slot_name)
                    break
    return (bool(matched), matched)


def _collect_low_confidence_slots(
    session: InterviewSession,
    threshold: float | None = None,
) -> list[str]:
    """
    从 session.slot_meta 聚合 confidence < threshold 的 slot 列表(spec §7)。

    规则:
      - 任何一个 slot 在 session.slot_meta 里的任意一条 meta entry.confidence < threshold
        → 该 slot 进入 low_confidence
      - 同一 slot 多条 meta 任一条 < threshold 即触发, slot 名只记一次
      - slot 名按字母序, 去重
      - bool 输入显式排除(spec §5.2 一致 — 防止 True/False 走 int 分支)
      - threshold=None → 用 INTERVIEW_LOW_CONFIDENCE_THRESHOLD(默认值 0.6)

    隐私边界(spec §5.2 + §7):
      - 只读 session.slot_meta(已是 hash 化后字段, 不含 user_message / source_span 明文)
    """
    if threshold is None:
        from core.interview_agent import INTERVIEW_LOW_CONFIDENCE_THRESHOLD
        threshold = INTERVIEW_LOW_CONFIDENCE_THRESHOLD
    slot_meta = getattr(session, "slot_meta", None)
    if not isinstance(slot_meta, dict):
        return []
    out: list[str] = []
    for slot_name, entries in slot_meta.items():
        if not isinstance(slot_name, str) or not slot_name:
            continue
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            conf = entry.get("confidence")
            if isinstance(conf, bool):
                continue
            if isinstance(conf, (int, float)) and float(conf) < float(threshold):
                if slot_name not in out:
                    out.append(slot_name)
                break
    out.sort()
    return out


def _bullet_involves_low_confidence_slots(
    bullet: str,
    low_conf_slots: list[str],
    captured: Any,
) -> bool:
    """
    bullet 是否涉及 low_conf_slots 任意一个 slot 的内容(简化规则)。

    简化逻辑: 用 slot 字段字符串的前半段(≥4 字)做子串匹配。
    足够轻量且不依赖 LLM, 足以标记"低置信度 slot 仍在 bullet 里出现"。

    边界:
      - low_conf_slots 空 / bullet 非 str → 返 False
      - 短于 4 字的 slot 字符串不参与匹配(防止噪音)
    """
    if not low_conf_slots or not isinstance(bullet, str) or not bullet.strip():
        return False
    if not isinstance(captured, dict):
        return False
    for slot_name in low_conf_slots:
        val = captured.get(slot_name)
        if isinstance(val, str):
            s = val.strip()
            if len(s) >= 4:
                needle = s[: max(4, len(s) // 2)]
                if needle in bullet:
                    return True
        elif isinstance(val, list):
            for sub in val:
                if isinstance(sub, str):
                    s = sub.strip()
                    if len(s) >= 4:
                        needle = s[: max(4, len(s) // 2)]
                        if needle in bullet:
                            return True
    return False


# ----------------------------------------------------------------------
# 公开 API
# ----------------------------------------------------------------------
def verify_draft_card(
    card: Any,
    session: InterviewSession,
) -> dict[str, Any]:
    """
    spec §7: 验证 draft_card 各 bullet 是否有 captured_slots / slot_meta 来源。

    输入:
      card:    build_draft_card() 生成的 draft_card dict(或不规范的 dict)
      session: InterviewSession(读 captured_slots + slot_meta)

    返回:
      {
        "claims_total":          int,    # draft_bullets 非空 str 总数
        "claims_supported":      int,    # 至少有量化数字来源 OR slot 文本来源 的 bullet 数
        "low_confidence_claims": int,    # 涉及 confidence < 0.6 slot 的 bullet 数
        "unsupported_claims":    int,    # 没有任何来源的 bullet 数
        "warnings":              list[str],  # 用户可读 warning(不含完整 bullet 原文, 仅 slot 名 + bullet 索引 + 前 30 字摘要)
      }

    不抛(spec §6.3): 任何异常 → 返零计数的 summary + 不含原文的 warnings。

    隐私边界:
      - 不调用 LLM / 不读 env / 不写文件 / 不调网络
      - 不复制完整 bullet 原文到返回 dict(spec §7 "禁止把完整 ... draft_card 原文写入 _interview_meta")
      - 不读 user_message / source_span 明文(只读 session.captured_slots / slot_meta)
      - 不返回 API key / jd_text / prompt
    """
    try:
        # 1. bullet list
        bullets: list[str] = []
        if isinstance(card, dict):
            raw = card.get("draft_bullets")
            if isinstance(raw, list):
                bullets = [b for b in raw if isinstance(b, str)]

        # 2. captured
        captured = getattr(session, "captured_slots", None)
        if not isinstance(captured, dict):
            captured = {}
        sources = _collect_source_strings(captured)

        # 3. low_conf slots
        low_conf_slots = _collect_low_confidence_slots(session)

        claims_total = len(bullets)
        claims_supported = 0
        low_confidence_claims = 0
        unsupported_claims = 0
        warnings: list[str] = []

        for idx, bullet in enumerate(bullets):
            # 量化数字 + slot 文本 双源
            quant_hits = _bullet_quantitative_in_source(bullet, sources)
            is_supported, _matched_slots = _bullet_mentions_slot_source(
                bullet, captured,
            )

            if quant_hits or is_supported:
                claims_supported += 1
            else:
                unsupported_claims += 1
                # 不复制完整原文: 用 bullet 索引 + 前 30 字摘要(spec §7 隐私边界)
                preview = bullet.strip()[:_WARNING_BULLET_PREVIEW_LEN]
                suffix = "..." if len(bullet.strip()) > _WARNING_BULLET_PREVIEW_LEN else ""
                warnings.append(
                    f"draft_bullets[{idx}] \"{preview}{suffix}\" 缺少量化数字来源或"
                    f" action/responsibility/result 类来源"
                )

            if _bullet_involves_low_confidence_slots(
                bullet, low_conf_slots, captured,
            ):
                low_confidence_claims += 1

        # low_conf slots 自身也加 1 条 warning(spec §7 + spec §9 "前端显示 confidence_notes")
        for slot_name in low_conf_slots:
            note = f"{slot_name} 槽位置信度偏低, 保存前请确认"
            warnings.append(note)

        return {
            "claims_total": claims_total,
            "claims_supported": claims_supported,
            "low_confidence_claims": low_confidence_claims,
            "unsupported_claims": unsupported_claims,
            "warnings": warnings,
        }
    except Exception:
        # spec §6.3 "失败不阻断主流程"
        # R6-G F-2.1: 兜底时附 sentinel 警告, 让前端 UI 知道 verifier 内部崩了
        # 避免 unsupported_claims=0 + low_confidence_claims=0 误导为 "全部 verified 通过"
        return {
            "claims_total": 0,
            "claims_supported": 0,
            "low_confidence_claims": 0,
            "unsupported_claims": 0,
            "warnings": [_VERIFIER_INTERNAL_ERROR_SENTINEL],
        }


def compute_confidence_notes(session: InterviewSession) -> list[str]:
    """
    从 session.slot_meta 抽出 confidence < 0.6 的 slot, 每条生成一行"人可读"说明。

    spec §7 "confidence_notes"/ spec §9 "前端显示 confidence_notes": 不暴露 source_span /
    confidence 数字 / 完整用户原文, 只输出 slot 名 + 模糊说明。

    用法:
      DraftResponse.draft_card.confidence_notes = compute_confidence_notes(session)
    """
    try:
        low_conf = _collect_low_confidence_slots(session)
    except Exception:
        # R6-G F-2.1: 兜底时返 sentinel, 前端不会误判为 "无低置信度"
        return [_CONFIDENCE_COLLECT_ERROR_SENTINEL]
    return [
        f"{slot_name} 槽位置信度偏低, 保存前请确认"
        for slot_name in low_conf
    ]


__all__ = [
    "QUANTITATIVE_PATTERN",
    "SOURCE_SLOT_KEYS",
    "verify_draft_card",
    "compute_confidence_notes",
    # R6-G F-2.1: sentinel 常量(测试可 import 验证隐私边界)
    "_VERIFIER_INTERNAL_ERROR_SENTINEL",
    "_CONFIDENCE_COLLECT_ERROR_SENTINEL",
]
