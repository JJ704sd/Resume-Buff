"""
JD-driven 排序模块 (Round 3 I)

设计原则:
  - **不**依赖 LLM,纯规则化命中数排序
  - **不**改 ROLE_CONFIG / 不裁剪项目(只排序,不去除)
  - **稳定排序** — 命中数倒序,相同时维持原顺序(确定性硬指标)
  - 输入 parsed_jd 是 jd_parser.parse_jd() 的输出,只读 raw_keywords 字段

公开 API:
  - rank_projects(projects, parsed_jd, preferred_order) -> list[dict]
      输入:project 列表(已含 highlights 字段)、parsed JD 字典、preferred 顺序(用于 tie-break)
      输出:按命中数倒序排好的 project 列表
  - rank_highlights(highlights, parsed_jd) -> list[str]
      输入:highlight 列表、parsed JD 字典
      输出:按命中数倒序排好的 highlight 列表(不裁剪)
  - rank_skill_groups(skill_keys, materials, parsed_jd) -> list[str]
      输入:role 的 skill_keys 列表、materials 字典、parsed JD 字典
      输出:按"组内 item 命中 JD 关键词总数"倒序排好的 skill_key 列表
"""
from __future__ import annotations

from typing import Any


def _count_matches(text: str, keywords: list[str]) -> int:
    """
    命中数:每条 keyword 在 text 里出现(子串)即 +1。同 keyword 多次出现按 1 次算。
    """
    if not text or not keywords:
        return 0
    count = 0
    for kw in keywords:
        if not kw:
            continue
        if kw in text:
            count += 1
    return count


def _project_match_text(project: dict) -> str:
    """
    把 project 里跟 JD 相关的文本拼成一个大字符串用于命中数计算。
    - highlights (list[str] 或 dict)
    - tags
    - summary
    - role
    """
    parts: list[str] = []
    highlights = project.get("highlights", [])
    if isinstance(highlights, list):
        parts.extend(str(h) for h in highlights)
    elif isinstance(highlights, dict):
        # materials.json 里 highlights 是 dict[role -> list[str]]
        for v in highlights.values():
            if isinstance(v, list):
                parts.extend(str(x) for x in v)
    for tag in project.get("tags", []) or []:
        parts.append(str(tag))
    if project.get("summary"):
        parts.append(str(project["summary"]))
    if project.get("role"):
        parts.append(str(project["role"]))
    return "\n".join(parts)


def rank_projects(
    projects: list[dict],
    parsed_jd: dict | None,
    preferred_order: list[str] | None = None,
) -> list[dict]:
    """
    按 JD 命中数倒序重排 project 列表。

    - 不传 parsed_jd / parsed_jd 为空 / parsed_jd 没有 raw_keywords → 维持原顺序
    - 命中数相同 → 按原 preferred_order 顺序(若提供) / list 原顺序兜底
    - 不裁剪 — 命中 0 也保留
    """
    if not projects:
        return projects
    if parsed_jd is None:
        return list(projects)

    keywords: list[str] = parsed_jd.get("raw_keywords") or []
    if not keywords:
        return list(projects)

    # 构造 preferred_order → index 映射(tie-break 用)
    preferred_idx: dict[str, int] = {}
    if preferred_order:
        for i, pid in enumerate(preferred_order):
            preferred_idx[pid] = i

    # 计算每个 project 的命中数 + tie-break key
    def _key(p: dict) -> tuple[int, int]:
        match_text = _project_match_text(p)
        cnt = _count_matches(match_text, keywords)
        pid = p.get("id", "")
        # 命中数倒序(用 -cnt),相同时按 preferred_idx / list 原 index
        # preferred_idx 没命中时用 999999 兜底(排在最前)
        tie = preferred_idx.get(pid, 999_999)
        return (-cnt, tie)

    return sorted(projects, key=_key)


def rank_highlights(
    highlights: list[str],
    parsed_jd: dict | None,
) -> list[str]:
    """
    项目内 highlight 排序:命中数倒序,相同时维持原顺序。

    - 不传 parsed_jd / 没 keywords → 维持原顺序
    - 不裁剪 — 命中 0 也保留
    """
    if not highlights:
        return highlights
    if parsed_jd is None:
        return list(highlights)

    keywords: list[str] = parsed_jd.get("raw_keywords") or []
    if not keywords:
        return list(highlights)

    # 用 enumerate 保 stability
    indexed = list(enumerate(highlights))
    indexed.sort(key=lambda kv: (-_count_matches(kv[1], keywords), kv[0]))
    return [h for _, h in indexed]


def rank_skill_groups(
    skill_keys: list[str],
    materials: dict,
    parsed_jd: dict | None,
) -> list[str]:
    """
    skill group 排序:每个 group 算"组内 item 命中 JD 关键词总数"倒序,相同维持原顺序。

    - 不传 parsed_jd / 没 keywords → 维持原顺序
    - 不裁剪 — 命中 0 也保留
    - materials 缺 skills 段时按空字典处理
    """
    if not skill_keys:
        return skill_keys
    if parsed_jd is None:
        return list(skill_keys)

    keywords: list[str] = parsed_jd.get("raw_keywords") or []
    if not keywords:
        return list(skill_keys)

    skills = materials.get("skills", {}) or {}

    indexed = list(enumerate(skill_keys))
    def _key(kv: tuple[int, str]) -> tuple[int, int]:
        idx, key = kv
        items = skills.get(key, []) or []
        # 拼接组内所有 item → 命中数
        joined = "\n".join(str(x) for x in items)
        cnt = _count_matches(joined, keywords)
        return (-cnt, idx)

    indexed.sort(key=_key)
    return [k for _, k in indexed]
