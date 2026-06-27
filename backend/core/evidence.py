"""
R5-A Phase 3: 轻量 RAG — Evidence Snippet 检索

设计目标 (spec §5.3):
  - 不引入向量数据库 / embedding API
  - 复用现有 KEYWORD_GROUPS surface/normalized 做 lexical retrieval
  - 每个 evidence snippet 包含: source_type / source_id / text / matched_keywords / confidence
  - LLM 改写只能引用 evidence 中存在的事实,不得编造

evidence 来源 (从 materials.json 切):
  - projects.highlights[role|general|...]  →  source_type="project", source_id=p["id"]
  - skills[group][items]                    →  source_type="skill",   source_id=group
  - honors[].name / certs[].name            →  source_type="honor"|"cert"

关键约束 (spec §6.4 + Phase 3 任务约束):
  - 不记录完整 evidence 文本到日志 / trace
  - 不记录完整 JD 到日志 / trace
  - 无 evidence 时(关键词全部没命中)→ 返空 list,LLM 走"无 evidence 约束"分支
  - 排序必须稳定 (confidence desc → source_type → source_id), 让 LLM 摄入顺序一致

公开 API:
  - EvidenceSnippet              — snippet 数据结构(frozen=True 防运行期被改)
  - build_evidence_snippets      — 从 materials 切 snippets (无关键词过滤)
  - retrieve_evidence            — 按 jd_keywords + role 做 lexical retrieval, 返 top-k
  - _summarize_evidence_for_prompt — 把 evidence 列表压缩成 LLM 友好的 summary 文本(截断)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from core.jd_parser import KEYWORD_GROUPS


# ----------------------------------------------------------------------
# EvidenceSnippet 数据结构
# ----------------------------------------------------------------------
@dataclass(frozen=True)
class EvidenceSnippet:
    """
    单条 evidence 片段 (从 materials 切出来的"事实"单元).

    字段:
      source_type       - "project" | "skill" | "honor" | "cert"
      source_id         - 来源 id (project.id / skill group 名 / honor name / cert name)
      text              - 事实原文 (单句 bullet / skill item / honor name)
      matched_keywords  - 这条 evidence 里命中 JD 关键词的 normalized 列表(去重)
      confidence        - 置信度 [0.0, 1.0], 命中数 / 关键词总数(降权处理:多关键词同时命中加分)
                          - 0.0 = 没命中任何关键词(由 build_evidence_snippets 给; retrieve_evidence 一般不返)
                          - 1.0 = 高置信(命中多个高权重关键词)

    隐私:
      - frozen=True 防运行期被偷偷改
      - 不在 dataclass 里存 materials 整体 / jd_text 原文(只存 normalized 关键词)
    """
    source_type: str
    source_id: str
    text: str
    matched_keywords: tuple[str, ...] = field(default_factory=tuple)
    confidence: float = 0.0


# ----------------------------------------------------------------------
# Snippet 构造 (无关键词过滤)
# ----------------------------------------------------------------------
def build_evidence_snippets(
    materials: dict,
    *,
    role: Optional[str] = None,
) -> list[EvidenceSnippet]:
    """
    从 materials 切 evidence snippets (不过滤关键词 — 只切片).

    Args:
        materials: 已加载的素材库 dict (来自 core.generator.load_materials)
        role:     当前 target_role (决定 projects.highlights 取哪个 role 视角)
                  None → 取 "general" 视角 (保留所有项目 highlights 的最宽口径)

    Returns:
        list[EvidenceSnippet] — 全部 snippets (projects/skills/honors/certs)
        排序: source_type 升序 (cert → honor → project → skill), source_id 升序
              — 稳定可测, 与 retrieve_evidence 的排序无关 (那是按 confidence 排)

    切片规则:
      - projects[*].highlights: 取 role 视角的 highlights, 若没有 fallback 到 "general",
        再没有 → 跳过该项目
      - skills[group]: 每个 item (单条 skill) 切一条 snippet, source_id = group 名
      - honors[*].name: 一条 honor 一条 snippet
      - certs[*].name: 一条 cert 一条 snippet (cert issuer 拼到 text 后面作为补充信息)

    注意:
      - 不读 education / basics 字段 (与 RAG 目标偏离, 不进 evidence 库)
      - 失败防御: 单条数据缺失/类型错, 静默跳过, 不抛 (让 build_evidence_snippets 永远成功)
    """
    snippets: list[EvidenceSnippet] = []

    # ----- 1) projects.highlights 切片 -----
    projects = materials.get("projects") or []
    target_role = role or "general"
    for p in projects:
        if not isinstance(p, dict):
            continue
        pid = str(p.get("id", ""))
        if not pid:
            continue
        highlights = p.get("highlights") or {}
        if not isinstance(highlights, dict):
            continue
        # 优先级: target_role → general → 跳过
        role_highlights = highlights.get(target_role) or highlights.get("general") or []
        if not isinstance(role_highlights, list):
            continue
        for h in role_highlights:
            if not isinstance(h, str):
                continue
            text = h.strip()
            if not text:
                continue
            snippets.append(EvidenceSnippet(
                source_type="project",
                source_id=pid,
                text=text,
            ))

    # ----- 2) skills[group] 切片 -----
    skills = materials.get("skills") or {}
    if isinstance(skills, dict):
        for group, items in skills.items():
            if not isinstance(items, list):
                continue
            group_id = str(group)
            for item in items:
                if not isinstance(item, str):
                    continue
                text = item.strip()
                if not text:
                    continue
                snippets.append(EvidenceSnippet(
                    source_type="skill",
                    source_id=group_id,
                    text=text,
                ))

    # ----- 3) honors 切片 -----
    honors = materials.get("honors") or []
    for h in honors:
        if not isinstance(h, dict):
            continue
        name = str(h.get("name", "")).strip()
        if not name:
            continue
        date = str(h.get("date", "")).strip()
        text = f"{name} ({date})" if date else name
        snippets.append(EvidenceSnippet(
            source_type="honor",
            source_id=name,
            text=text,
        ))

    # ----- 4) certs 切片 -----
    certs = materials.get("certs") or []
    for c in certs:
        if not isinstance(c, dict):
            continue
        name = str(c.get("name", "")).strip()
        if not name:
            continue
        issuer = str(c.get("issuer", "")).strip()
        date = str(c.get("date", "")).strip()
        tail_bits = [b for b in (issuer, date) if b]
        text = f"{name} ({' · '.join(tail_bits)})" if tail_bits else name
        snippets.append(EvidenceSnippet(
            source_type="cert",
            source_id=name,
            text=text,
        ))

    # 排序: source_type 升序 → source_id 升序 (稳定, 便于测试)
    snippets.sort(key=lambda s: (s.source_type, s.source_id, s.text))
    return snippets


# ----------------------------------------------------------------------
# Lexical Retrieval
# ----------------------------------------------------------------------
def _build_keyword_to_weight() -> dict[str, float]:
    """
    构造 normalized → weight 反查表 (从 KEYWORD_GROUPS).
    同一 normalized 跨 group 出现 → 取最大 weight (跟 match_score 保持一致).
    """
    kw_weight: dict[str, float] = {}
    for group_keywords in KEYWORD_GROUPS.values():
        for surface, normalized, w in group_keywords:
            if normalized not in kw_weight or w > kw_weight[normalized]:
                kw_weight[normalized] = w
    return kw_weight


# 全 module 共享 (不可变, 启动时构建一次, 节省重复 IO)
_KEYWORD_WEIGHT: dict[str, float] = _build_keyword_to_weight()


def _keyword_hit(snippet_text: str, jd_keywords: list[str]) -> list[str]:
    """
    给一段 snippet text, 找出其中命中的 normalized 关键词.

    复用 match_score 的扫描思路:
      - lowercase + 中文标点 → 英文标点 (走 jd_parser._normalize_text)
      - 对每个 jd_keyword, 检查"任一 surface 出现在 text 中" → 命中
      - 命中返回 normalized 列表 (去重, 保持 jd_keywords 给的顺序)

    不写日志 / 不抛异常 (防御性).
    """
    # 防御: jd_keywords 为 None 或非 iterable → 返空 list (不抛)
    if not jd_keywords:
        return []
    # 局部 import 避免循环 + 测试时 jd_parser 已可用
    from core.jd_parser import _normalize_text

    norm_text = _normalize_text(snippet_text)
    hits: list[str] = []
    seen: set[str] = set()
    for kw in jd_keywords:
        if not isinstance(kw, str) or not kw or kw in seen:
            continue
        # 找这个 kw 在 KEYWORD_GROUPS 里所有 surface
        surfaces: list[str] = []
        for group_keywords in KEYWORD_GROUPS.values():
            for surface, normalized, _w in group_keywords:
                if normalized == kw:
                    surfaces.append(surface)
        # 任一 surface 在 text 里出现 → 命中
        if any(s.lower() in norm_text for s in surfaces):
            hits.append(kw)
            seen.add(kw)
    return hits


def _compute_confidence(matched: list[str], jd_keywords: list[str]) -> float:
    """
    给一段 evidence 算 confidence ∈ [0.0, 1.0].

    算法 (Phase 3 MVP):
      - 基础分: matched 数 / jd_keywords 总数 (缺 jd_keywords 时返 0.0)
      - 权重加成: matched 关键词的 KEYWORD_GROUPS weight 总和 / 所有 jd_keyword 的 weight 总和
      - 取两者中较大者 (让"少量高权重命中"也能得高分, 而不是被"低权重多匹配"稀释)

    设计意图:
      - 1 个核心关键词命中 (weight 1.0) 在 5 个关键词中 → 0.5 分 (跟"5 个权重 0.5 都命中"等量)
      - 0 命中 → 0.0 (不应进 retrieve_evidence 返回, 由 caller 过滤)
      - 全部命中 → 1.0

    防御:
      - jd_keywords 空 → 返 0.0 (避免除零)
    """
    if not jd_keywords:
        return 0.0
    if not matched:
        return 0.0

    # 1) 命中比例
    hit_ratio = len(matched) / len(jd_keywords)

    # 2) 加权比例 (拿 matched 和 jd_keywords 各自的 weight 总和)
    matched_w = sum(_KEYWORD_WEIGHT.get(kw, 0.5) for kw in matched)
    all_w = sum(_KEYWORD_WEIGHT.get(kw, 0.5) for kw in jd_keywords)
    weighted_ratio = matched_w / all_w if all_w > 0 else 0.0

    # 取较大者 → 让少量高权重命中也能拿到较好分数
    confidence = max(hit_ratio, weighted_ratio)
    # 钳到 [0.0, 1.0]
    return max(0.0, min(1.0, confidence))


def retrieve_evidence(
    jd_keywords: list[str],
    role: str,
    materials: dict,
    *,
    top_k: int = 8,
    min_confidence: float = 0.0,
) -> list[EvidenceSnippet]:
    """
    按 jd_keywords + role 做 lexical retrieval, 返 top-k evidence.

    算法 (Phase 3 MVP):
      1) build_evidence_snippets(materials, role=role) → 全部 snippets
      2) 对每条 snippet, 用 _keyword_hit 找出 matched_keywords
      3) 过滤 matched 为空的 snippet (除非 min_confidence < 1.0 时允许 0 命中,
         当前实现: 0 命中一律过滤, 防止 evidence summary 噪声)
      4) 按 _compute_confidence 计算 confidence
      5) 过滤 min_confidence 以下
      6) 排序: confidence DESC → source_type ASC → source_id ASC (稳定)
      7) 截断 top_k

    Args:
        jd_keywords:    归一化后的 JD 关键词列表 (来自 parse_jd / match_score)
        role:           当前 target_role (决定 projects.highlights 取哪个 role 视角)
        materials:      已加载的素材库 dict
        top_k:          返回最多 top_k 条 (默认 8, 跟 spec §5.3 一致)
        min_confidence: 置信度门槛 (默认 0.0; LLM 改写场景一般 0.0 即可, 让 LLM 看全)

    Returns:
        list[EvidenceSnippet] — top-k evidence, 稳定排序, 0 命中 snippet 已过滤

    关键约束:
      - 无关键词命中时 → 返空 list (不是低 confidence, 直接空, 让 LLM 走"无 evidence"分支)
      - 排序稳定 (Tuple key), 同 input 多次调用返字节级一致
      - 不修改输入 materials
    """
    if not jd_keywords:
        return []

    snippets = build_evidence_snippets(materials, role=role)
    if not snippets:
        return []

    scored: list[EvidenceSnippet] = []
    for snip in snippets:
        matched = _keyword_hit(snip.text, jd_keywords)
        if not matched:
            # 0 命中 → 跳过 (不让噪声进 summary)
            continue
        confidence = _compute_confidence(matched, jd_keywords)
        if confidence < min_confidence:
            continue
        # frozen=True, 必须构造新对象 (不能 in-place 改 matched_keywords / confidence)
        scored.append(EvidenceSnippet(
            source_type=snip.source_type,
            source_id=snip.source_id,
            text=snip.text,
            matched_keywords=tuple(matched),
            confidence=confidence,
        ))

    # 稳定排序: confidence DESC → source_type ASC → source_id ASC
    scored.sort(key=lambda s: (-s.confidence, s.source_type, s.source_id))

    return scored[:max(0, top_k)]


# ----------------------------------------------------------------------
# LLM Prompt 友好的 Evidence Summary (Phase 3 关键交付)
# ----------------------------------------------------------------------
# 单条 snippet 文本在 summary 里的最大字符数 (防 prompt 爆)
_SNIPPET_TEXT_LIMIT = 80
# 整个 summary 文本最大字符数 (防 prompt 爆)
_SUMMARY_MAX_CHARS = 2000


def _summarize_evidence_for_prompt(
    evidence_list: list[EvidenceSnippet],
    *,
    max_chars: int = _SUMMARY_MAX_CHARS,
) -> str:
    """
    把 evidence 列表压缩成 LLM 友好的 summary 字符串 (供 rewrite_highlights 注入 prompt).

    输出格式:
      [1] (project/company_medical_eval) 构建包含 100 个测试用例的医疗分质量评测集...
      [2] (skill/ai_ml) PyTorch 深度学习框架...
      [3] (honor/数学建模竞赛三等奖) 数学建模竞赛三等奖 (2025)

    用途:
      - rewrite_highlights 接收 evidence kwarg 后, 把这个 summary 注入 user_payload
      - LLM 看到的不是完整 evidence dict, 而是"事实摘录 + 来源标识"
      - 隐私: 完整 text 仍可能含 PII (姓名/学校/公司), 但用户材料已脱敏, summary 跟原文同口径

    Args:
        evidence_list: retrieve_evidence 返回的列表 (已排序)
        max_chars:     summary 总字符上限 (默认 2000, 防止 prompt token 爆)

    Returns:
        str — markdown-ish 多行文本, 末尾 "...(N more)" 表示被截断
        空 evidence_list → "" (空字符串, 跟 evidence=None 字节级一致)
    """
    if not evidence_list:
        return ""

    parts: list[str] = []
    total = 0
    truncated = 0
    for i, ev in enumerate(evidence_list, 1):
        # 截断单条文本
        text = ev.text
        if len(text) > _SNIPPET_TEXT_LIMIT:
            text = text[:_SNIPPET_TEXT_LIMIT].rstrip() + "..."
        line = f"[{i}] ({ev.source_type}/{ev.source_id}) {text}"
        # 检查总字符
        if total + len(line) + 1 > max_chars:
            truncated = len(evidence_list) - (i - 1)
            break
        parts.append(line)
        total += len(line) + 1  # +1 for newline

    summary = "\n".join(parts)
    if truncated > 0:
        summary += f"\n...({truncated} more)"
    return summary


# ----------------------------------------------------------------------
# 工具函数: Evidence 列表 → dict (供 ToolResult.output / preview 输出)
# ----------------------------------------------------------------------
def evidence_to_dict_list(evidence_list: list[EvidenceSnippet]) -> list[dict]:
    """
    把 EvidenceSnippet 列表序列化成 dict 列表 (JSON 友好).

    注意: 不返回完整 materials, 不返回 jd_text 原文。
    """
    return [
        {
            "source_type": ev.source_type,
            "source_id": ev.source_id,
            "text": ev.text,
            "matched_keywords": list(ev.matched_keywords),
            "confidence": round(ev.confidence, 3),
        }
        for ev in evidence_list
    ]
