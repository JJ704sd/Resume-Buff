"""
JD (Job Description) 文本解析 + 匹配度评分 — 纯规则化旁路模块

设计原则 (MVP):
  - **不**联网、不调用 LLM,所有逻辑 = 关键词字典 + 正则
  - **不**写数据库,parse_jd 是无状态函数
  - **不**改 core/generator.py 主流程,只读 ROLE_CONFIG / load_materials
  - API 边界由 api/jd.py 提供;本模块不依赖 FastAPI,纯逻辑可单测

公开 API:
  - parse_jd(text)                 -> 提取关键词 / 经验 / 学历 / tier
  - match_score(text, role, mats)  -> 对当前素材库算 0-100 分 + 建议
  - KEYWORD_GROUPS                 -> 关键词字典(skills / tools / domains),三元组 (surface, normalized, weight)
"""
import re
from typing import Any

from core.generator import ENABLED_ROLES, ROLE_CONFIG, load_materials


# ----------------------------------------------------------------------
# 中文-阿拉伯数字映射 (处理 "三年以上" 这种)
# ----------------------------------------------------------------------
_CN_NUM_MAP: dict[str, int] = {
    "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
}


def _cn_to_int(s: str) -> int | None:
    """把单个数字字符(中文或阿拉伯)转 int,无法解析返 None"""
    if s.isdigit():
        return int(s)
    return _CN_NUM_MAP.get(s)


# ----------------------------------------------------------------------
# 关键词字典:每个关键词 = (surface, normalized_form, weight)
#   - surface:        在 JD 文本里查的字面
#   - normalized_form: 命中后归一化的形式(同义词 → 同一 normalized)
#   - weight:         1.0 = 必选 (必备技能) / 0.5 = 加分 (nice to have / 业务偏好)
#   同一个 normalized_form 在同一 group 内只算一次(去重)
# ----------------------------------------------------------------------
KEYWORD_GROUPS: dict[str, list[tuple[str, str, float]]] = {
    "skills": [
        # 必选权重 (1.0) — 核心算法/AI 技能,几乎所有 JD 都要求
        ("Python", "Python", 1.0),
        ("PyTorch", "PyTorch", 1.0),
        ("TensorFlow", "TensorFlow", 1.0),
        ("Transformer", "Transformer", 1.0),
        ("CNN", "CNN", 1.0),
        ("LLM", "LLM", 1.0),
        ("大模型", "LLM", 1.0),
        ("大语言模型", "LLM", 1.0),
        # R3.5+ 新增:中英文 JD 都高频出现的 "AI" 字面词
        # — 跟 "大模型"/"LLM" 语义等价,归一化到 LLM(加分权重 0.5)
        ("AI", "LLM", 0.5),
        # 加分权重 (0.5) — 领域细分 / 加分项
        ("深度学习", "深度学习", 0.5),
        ("评测", "评测", 0.5),
        ("数据标注", "数据标注", 0.5),
        ("标注", "数据标注", 0.5),
        ("Prompt", "Prompt", 0.5),
        ("prompt 工程", "Prompt", 0.5),
        ("鲁棒性", "鲁棒性", 0.5),
        ("微调", "微调", 0.5),
        ("LoRA", "LoRA", 0.5),
        ("推理", "推理", 0.5),
        ("部署", "部署", 0.5),
        ("NLP", "NLP", 0.5),
    ],
    "tools": [
        # 必选 (1.0) — 主流工程工具
        ("Docker", "Docker", 1.0),
        ("Git", "Git", 1.0),
        ("Linux", "Linux", 1.0),
        # 加分 (0.5) — 业务场景
        ("CUDA", "CUDA", 0.5),
        ("SQL", "SQL", 0.5),
        ("MySQL", "MySQL", 0.5),
        ("WSL", "WSL", 0.5),
        ("Flask", "Flask", 0.5),
        ("FastAPI", "FastAPI", 0.5),
        ("Shell", "Shell", 0.5),
    ],
    "domains": [
        # 加分 (0.5) — 业务偏好,所有 domain 都不算必选
        ("医疗", "医疗", 0.5),
        ("医学", "医疗", 0.5),
        ("临床", "医疗", 0.5),
        ("ECG", "ECG", 0.5),
        ("心电", "ECG", 0.5),
        ("NLP", "NLP", 0.5),
        ("评测", "评测", 0.5),
        # R3.5+ (PM 维度):baiyun_2026_product JD 提到, 修复后 match_score
        # 能精确识别这些 missing 关键词, suggestions 提示"补 PM 维度素材"
        ("物流", "物流", 0.5),
        ("工业工程", "工业工程", 0.5),
        ("原型", "原型", 0.5),
        ("流程图", "流程图", 0.5),
    ],
}


# ----------------------------------------------------------------------
# 工具:文本标准化 (lowercase + 中文标点 → 英文标点)
# ----------------------------------------------------------------------
_CN_PUNCT_TO_EN: dict[str, str] = {
    "，": ",", "。": ".", "；": ";", "：": ":",
    "！": "!", "？": "?",
    "（": "(", "）": ")",
    "【": "[", "】": "]",
    "「": '"', "」": '"',
    "『": "'", "』": "'",
    "、": ",",
    "“": '"', "”": '"',
    "‘": "'", "’": "'",
    "—": "-", "–": "-",
    "…": "...",
}


def _normalize_text(text: str) -> str:
    """lowercase + 中文标点 → 英文标点。JD 文本可以 >10k 字符,无副作用。"""
    if not text:
        return ""
    out: list[str] = []
    for ch in text:
        if ch in _CN_PUNCT_TO_EN:
            out.append(_CN_PUNCT_TO_EN[ch])
        else:
            out.append(ch)
    return "".join(out).lower()


# ----------------------------------------------------------------------
# 经验年限提取
# ----------------------------------------------------------------------
_YEAR_RANGE_RE = re.compile(
    r"([\d\u4e00-\u4e9f]+)\s*[-~到至]\s*([\d\u4e00-\u4e9f]+)\s*年"
)
_YEAR_MIN_RE = re.compile(r"([\d\u4e00-\u4e9f]+)\s*年\s*(?:以上|经验以上)")
_NO_LIMIT_RE = re.compile(r"(经验不限|经验无要求|不限|无要求)")


def _extract_experience(text: str) -> str:
    """从 JD 文本提取经验年限要求。

    支持的写法:
      - "1-3 年" / "1~3年" / "1到3年" / "一年到三年" -> "1-3"
      - "3 年以上" / "三年以上经验" -> "3年以上"
      - "经验不限" / "不限" -> "不限"
      - 没匹配到 -> "不限" (默认,不抛错)
    """
    m = _YEAR_RANGE_RE.search(text)
    if m:
        n1 = _cn_to_int(m.group(1))
        n2 = _cn_to_int(m.group(2))
        if n1 is not None and n2 is not None:
            return f"{min(n1, n2)}-{max(n1, n2)}"
        # 兜底:返字面
        return f"{m.group(1)}-{m.group(2)}"

    m = _YEAR_MIN_RE.search(text)
    if m:
        n = _cn_to_int(m.group(1))
        if n is not None:
            return f"{n}年以上"
        return f"{m.group(1)}年以上"

    if _NO_LIMIT_RE.search(text):
        return "不限"

    return "不限"


# ----------------------------------------------------------------------
# 学历提取(取最高要求)
# ----------------------------------------------------------------------
_EDU_ORDER: list[tuple[str, list[str]]] = [
    ("博士", ["博士", "phd"]),
    ("硕士", ["硕士", "研究生", "master"]),
    ("本科", ["本科", "bachelor"]),
    ("大专", ["大专", "专科"]),
]


def _extract_education(text: str) -> str:
    """提取学历要求(从高到低匹配,取最先命中 = 最高)。"""
    for level_name, keywords in _EDU_ORDER:
        for kw in keywords:
            if kw in text:
                return level_name
    return "不限"


# ----------------------------------------------------------------------
# Tier 修饰词识别 (上下文窗口法,非 strict regex)
# ----------------------------------------------------------------------
# 修饰词 → tier 名称 映射
# 中文 + 英文双覆盖,按"语义"分组
_TIER_KEYWORDS: dict[str, list[str]] = {
    "required": [
        "必须", "必备", "必需", "要求", "需要",
        "熟悉", "熟练", "精通",
        "required", "must", "must have", "must-have",
    ],
    "preferred": [
        "优先", "优先考虑", "优先录取", "优先选择",
        "preferred", "nice to have", "nice-to-have",
    ],
    "bonus": [
        "加分", "加分项", "加 bonus", "是加分",
        "bonus", "plus", "extra",
    ],
}

# 上下文窗口半径(字符)
_TIER_CONTEXT_RADIUS = 30

# Tier 优先级(数字越大 = 越严),仅用于 tier_info 内部"取最严"比较,
# 不参与 match_score 计算(score 走 KEYWORD_GROUPS weight 1.0/0.5)
_TIER_PRIORITY: dict[str, int] = {
    "required": 3,
    "preferred": 2,
    "bonus": 1,
}


def _classify_tier(norm_text: str) -> list[tuple[int, int, str]]:
    """
    在 JD 文本里找出所有 tier 修饰词出现的位置,记录为 (起始, 结束, tier) 区间列表。
    返回 list[tuple[int, int, str]] 供 _keyword_tier 做上下文窗口距离匹配。

    实现细节:按关键词长度倒序匹配,避免短词先匹配把长词的子串吃掉
    (例 "nice to have" 必须先于 "have")。
    """
    spans: list[tuple[int, int, str]] = []
    for tier, kws in _TIER_KEYWORDS.items():
        for kw in sorted(kws, key=len, reverse=True):
            kw_lower = kw.lower()
            start = 0
            while True:
                idx = norm_text.find(kw_lower, start)
                if idx < 0:
                    break
                spans.append((idx, idx + len(kw_lower), tier))
                start = idx + len(kw_lower)
    return spans


def _keyword_tier(norm_text: str, surface: str, tier_spans: list[tuple[int, int, str]]) -> str:
    """
    给定 surface 在 norm_text 中的出现位置,判断它属于哪个 tier。
    规则:用上下文窗口(前后 _TIER_CONTEXT_RADIUS 字符)找**最近的** tier 修饰词。
    没有命中任何 tier 修饰 → 兜底为 "required"(业务 JD 默认就是必须)。

    决策策略:"最近距离" 优先 — 因为 JD 行文里 "必须 X, 优先 Y" 中,X 物理上离 "必须"
    更近,Y 离 "优先" 更近;这种"近邻"语义最符合人类阅读直觉。

    距离定义:
      - 重叠 (区间相交): 距离 = 0
      - 不重叠: 距离 = 两个区间端点之间的字符数

    注:同一 surface 多次出现,只判断**第一次出现**位置的 tier(MVP 简化;
    实际 JD 里同一关键词重复出现概率低,第二次出现的 tier 修饰通常与第一次一致)。
    """
    surface_lower = surface.lower()
    # 拿 surface 的第一次出现
    idx = norm_text.find(surface_lower)
    if idx < 0:
        return "required"
    kw_start = idx
    kw_end = idx + len(surface_lower)

    best_tier = "required"  # 兜底:没命中任何 tier → required
    best_dist = _TIER_CONTEXT_RADIUS + 1
    for span_start, span_end, tier in tier_spans:
        # 区间距离:重叠 = 0,不重叠 = |左/右端点差|
        if kw_start >= span_end:
            dist = kw_start - span_end
        elif kw_end <= span_start:
            dist = span_start - kw_end
        else:
            dist = 0
        if dist <= _TIER_CONTEXT_RADIUS and dist < best_dist:
            best_dist = dist
            best_tier = tier

    return best_tier


def _parse_tier_info(
    norm_text: str,
    matched_normalized: list[str],
) -> dict[str, list[str]]:
    """
    给定 norm_text + 命中关键词,构建 tier_info。
    包含所有命中的关键词,按 tier 分组(上下文窗口法)。

    Tier 优先级(weight, 仅用于内部比较取"最严",不参与 score 计算):
      required > preferred > bonus
    多个 surface 指向同一 normalized,取"最严"的那个(优先级最高的)。

    关键:只考虑**实际出现在文本里**的 surface(否则同 normalized
    的"未出现 alias"会污染 tier 判断)。
    """
    tier_spans = _classify_tier(norm_text)
    tier_info: dict[str, list[str]] = {"required": [], "preferred": [], "bonus": []}
    # 用 set 避免同一 surface 多次添加(同 group 内 normalized 去重)
    seen: set[str] = set()
    for kw in matched_normalized:
        if kw in seen:
            continue
        seen.add(kw)
        # 找出这个 normalized 在哪些 group/keyword 里**实际出现** → 拿 surface
        tier = "bonus"  # 兜底:假设最弱,然后用"最严"覆盖
        found = False
        for group_name, keywords in KEYWORD_GROUPS.items():
            for surface, normalized, _w in keywords:
                if normalized == kw and surface.lower() in norm_text:
                    found = True
                    t = _keyword_tier(norm_text, surface, tier_spans)
                    # 取"最严"那个(优先级最高)
                    if _TIER_PRIORITY[t] > _TIER_PRIORITY[tier]:
                        tier = t
        if not found:
            # 兜底:这个 normalized 没有 surface 出现在文本里(理论不该发生,
            # 因为 parse_jd 调过同样的 surface 命中检查)
            tier = "required"
        if kw not in tier_info[tier]:
            tier_info[tier].append(kw)
    # 每 tier 内排序(让前端展示稳定)
    for t in tier_info:
        tier_info[t].sort()
    return tier_info


# ----------------------------------------------------------------------
# parse_jd: 关键词 + 经验 + 学历 一次性提取
# ----------------------------------------------------------------------
def parse_jd(text: str) -> dict[str, Any]:
    """
    解析 JD 文本,返回结构化结果。

    Args:
        text: 原始 JD 文本,任意长度,支持中英文混排。

    Returns:
        dict:
          - skills:        list[str]  归一化后的技能关键词
          - tools:         list[str]  工具/平台
          - domains:       list[str]  业务领域
          - experience_years: str     "1-3" / "3年以上" / "不限"
          - education:     str        "博士"/"硕士"/"本科"/"大专"/"不限"
          - raw_keywords:  list[str]  所有命中词 (skills+tools+domains 合并去重)
          - tier_info:     dict       {"required": [...], "preferred": [...], "bonus": [...]}
                                     上下文窗口法识别 JD 里的"必须/优先/加分"修饰词,
                                     命中的关键词按 tier 分组;未命中修饰词的关键词归 required
    """
    norm_text = _normalize_text(text)

    out: dict[str, Any] = {
        "skills": [],
        "tools": [],
        "domains": [],
        "experience_years": _extract_experience(norm_text),
        "education": _extract_education(norm_text),
        "raw_keywords": [],
        "tier_info": {"required": [], "preferred": [], "bonus": []},
    }

    # 按 group 提取,每个 group 内 normalized 去重
    for group_name, keywords in KEYWORD_GROUPS.items():
        seen: set[str] = set()
        for surface, normalized, _w in keywords:
            if surface.lower() in norm_text and normalized not in seen:
                out[group_name].append(normalized)
                seen.add(normalized)

    # raw_keywords: 跨 group 合并 + 去重 + 排序(让前端展示稳定)
    all_normalized: set[str] = set()
    for group_name in ("skills", "tools", "domains"):
        all_normalized.update(out[group_name])
    out["raw_keywords"] = sorted(all_normalized)

    # tier_info: 把所有命中关键词按上下文窗口里的 tier 修饰词分组
    out["tier_info"] = _parse_tier_info(
        norm_text,
        list(all_normalized),
    )

    return out


# ----------------------------------------------------------------------
# match_score: 与素材库 + role 的匹配度评分
# ----------------------------------------------------------------------
def _scan_items_into_pool(items: list[str], pool: set[str]) -> None:
    """
    把 items 列表里命中 KEYWORD_GROUPS surface 的 normalized 归入 pool(in-place)。

    实现:对每个 item 字符串,扫 KEYWORD_GROUPS 所有 surface,命中即纳入。
    同一 item 字符串里可能含多个 surface(如 "PyTorch 深度学习框架"
    → 命中 "PyTorch" + "深度学习"),会一并纳入。
    """
    for item in items:
        item_lower = item.lower()
        for group_keywords in KEYWORD_GROUPS.values():
            for surface, normalized, _w in group_keywords:
                if surface.lower() in item_lower:
                    pool.add(normalized)


def _build_candidate_pool(
    role_skill_keys: list[str],
    materials: dict,
    *,
    include_borrowed: bool = True,
) -> set[str]:
    """
    从素材库 + role 的 skill_keys 构造"可提供关键词池",由两部分构成:

      1) role 范围(强匹配):role_skill_keys 对应 items 里 surface 命中
         — 反映用户在当前 role 下的展示内容
      2) borrowed 范围(跨 role 借用,R3.5+ 新增):materials["skills"] 所有
         items 里 surface 命中(排除 role 范围已加的)
         — 反映用户在其他 role 方向上的经验,用于缓解 false negative

    Args:
        role_skill_keys: 当前 role 的 skill group 列表
        materials: 素材库 dict
        include_borrowed: True(默认) = role + borrowed 合并;
                         False = 仅 role 范围(旧行为,保留以备调用方需要
                         "严格 role 区分度"场景)

    Returns:
        合并去重后的 normalized 关键词池(set)

    设计权衡 (R3.5+):
      - 之前只查 role 范围,导致 baiyun_2026_product / baiyun_2026_qa
        触发 score=0(用户在 product/test_qa role 的 items 里没有 Python/LLM
        字面,但在其他 role 的 items 里有)
      - 引入 borrowed 池(默认开),让 score 反映"用户真实可提供"而不是
        "当前 role 展示什么"
      - coverage 算法不动,仍按 role 范围 — 保留"用户在当前 role 展示什么"
        的语义;只 score 和 matched_keywords 反映 borrowed 命中
    """
    pool: set[str] = set()
    skills = materials.get("skills", {})

    # 1) role 范围 — 强匹配(原有逻辑)
    for sk in role_skill_keys:
        items = skills.get(sk, []) or []
        _scan_items_into_pool(items, pool)

    # 2) borrowed 范围 — 跨 role 借用(新)
    if include_borrowed:
        role_set = set(role_skill_keys)
        for sk, items in skills.items():
            if sk in role_set:
                continue  # role 范围已加,跳过
            _scan_items_into_pool(items or [], pool)

    return pool


def _suggest_group_for_missing_keyword(
    kw: str, role_skill_keys: list[str]
) -> str | None:
    """
    给一个 missing 关键词,推荐在素材库哪个 skill group 里补充经验。

    启发式:根据 kw 在 KEYWORD_GROUPS 里属于哪个 group 决定。
      - tools → 推荐 "tools"
      - domains → 推荐 "medical" (示例素材库业务偏医疗)
      - skills → 推荐 role 的第一个 skill_key
    """
    for group_name, keywords in KEYWORD_GROUPS.items():
        for surface, normalized, _w in keywords:
            if normalized == kw:
                if group_name == "tools":
                    return "tools"
                if group_name == "domains":
                    return "medical"
                # skills
                return role_skill_keys[0] if role_skill_keys else None
    return None


# SKILL_LABEL 镜像 (避免 import cycle / 改 generator.py)
_SKILL_LABEL_LOCAL: dict[str, str] = {
    "programming_languages": "编程语言",
    "ai_ml": "AI / 算法",
    "tools": "工程与工具",
    "evaluation_metrics": "评测指标",
    "medical": "医学素养",
    "documentation": "文档与协作",
    "data": "数据处理",
}


def _build_suggestions(
    missing: list[str],
    score: int,
    all_parsed: bool,
    role_cfg: dict,
    skill_items_per_group: dict[str, list[str]],
) -> list[str]:
    """
    生成 2-5 条人话建议(MVP 规则化,不调 LLM)。

    决策表:
      - all_parsed 为 False (JD 没识别到任何已知关键词) → "词典不足"提示
      - missing 为空 (全命中) → "无需补充"
      - 否则 → 前 3 个 missing 推荐 skill group + 自我评价 + 求职意向
    """
    suggestions: list[str] = []

    # 1) 没识别到任何已知关键词
    if not all_parsed:
        suggestions.append(
            "未在 JD 中识别到已知技能/工具/领域关键词"
            "(关键词词典 KEYWORD_GROUPS 范围有限,可考虑扩展)"
        )
        intention = role_cfg.get("intention", "")
        if intention:
            suggestions.append(
                f"建议在求职意向部分对齐 '{intention}' 的方向"
            )
        return suggestions

    # 2) 全部命中
    if not missing:
        suggestions.append("素材库与 JD 匹配度极高,JD 关键词全部命中,无需补充")
        return suggestions

    role_skill_keys: list[str] = role_cfg.get("skill_keys", [])

    # 3) 前 3 个 missing → 推荐 skill group
    for kw in missing[:3]:
        target_group = _suggest_group_for_missing_keyword(kw, role_skill_keys)
        if target_group:
            label = _SKILL_LABEL_LOCAL.get(target_group, target_group)
            suggestions.append(
                f"素材库的 '{label}' 维度可补充 '{kw}' 的实操经验"
            )

    # 4) 自我评价建议
    suggestions.append(
        f"建议在自我评价里强调 '{missing[0]}' 相关经验"
    )

    # 5) 兜底:role 方向对齐
    intention = role_cfg.get("intention", "")
    if intention:
        suggestions.append(
            f"建议在求职意向部分对齐 '{intention}' 的方向"
        )

    # 截断到 5 条
    return suggestions[:5]


def _classify_recommendation(score: int) -> str:
    """
    把 0-100 的整数分转成"高/中/低"业务建议。

    阈值说明 (Round 3 占位,Round 3.5 用真实 JD 调优):
      - ≥ 80  → "高" (强烈推荐投递)
      - 60-79 → "中" (建议补充素材后再投递)
      - < 60  → "低" (需大幅补充素材)
    """
    if score >= 80:
        return "高"
    if score >= 60:
        return "中"
    return "低"


def match_score(
    text: str,
    target_role: str,
    materials: dict | None = None,
    *,
    include_borrowed: bool = True,
) -> dict[str, Any]:
    """
    给定 JD 文本 + target_role + materials,计算 0-100 匹配度评分 (加权)。

    Args:
        text: JD 文本
        target_role: 6 个 role id 之一,必须在 ENABLED_ROLES
        materials: 可选,外部传入素材库;不传则内部 load_materials() 读 json
        include_borrowed: R3.5+ 新增。True(默认) = 候选池包含用户其他 role
            方向上的经验(borrowed 池),用于缓解 false negative(如
            baiyun_2026_product / baiyun_2026_qa 之前 score=0);
            False = 仅当前 role 范围(旧行为,严格 role 区分度)。

    Returns:
        dict:
          - score:            int  0-100,整数 (按 KEYWORD_GROUPS weight 加权)
          - matched_keywords: list[str]
          - missing_keywords: list[str]
          - coverage:         dict[str, float]  skills/tools/domains 三维 (加权)
          - suggestions:      list[str]  2-5 条
          - role_id:          str
          - tier_info:        dict  {"required": [...], "preferred": [...], "bonus": [...]}
          - recommendation:   str   "高" / "中" / "低"

    Raises:
        ValueError: target_role 不在 ENABLED_ROLES
    """
    if target_role not in ENABLED_ROLES:
        raise ValueError(
            f"不支持/未启用的岗位: {target_role!r},"
            f"当前已启用: {ENABLED_ROLES}"
        )
    if target_role not in ROLE_CONFIG:
        raise ValueError(f"岗位 {target_role!r} 不在 ROLE_CONFIG")

    mats = materials if materials is not None else load_materials()
    role_cfg = ROLE_CONFIG[target_role]

    parsed = parse_jd(text)
    pool = _build_candidate_pool(
        role_cfg["skill_keys"], mats,
        include_borrowed=include_borrowed,
    )

    # 构建 normalized -> weight 的反查表(同 normalized 在多 group 出现取最大 weight)
    kw_weight: dict[str, float] = {}
    for group_name, keywords in KEYWORD_GROUPS.items():
        for surface, normalized, w in keywords:
            # 取最大 weight(同 normalized 在 skills/tools 跨 group 时)
            if normalized not in kw_weight or w > kw_weight[normalized]:
                kw_weight[normalized] = w

    # 按 group 算 coverage(按权重加权) + 收集 matched/missing
    matched: list[str] = []
    missing: list[str] = []
    coverage: dict[str, float] = {}
    for group_name in ("skills", "tools", "domains"):
        parsed_set = set(parsed[group_name])
        if not parsed_set:
            # 没有 JD 要求 → 视为"无要求 = 已覆盖"
            coverage[group_name] = 1.0
            continue
        hit = [k for k in parsed_set if k in pool]
        miss = [k for k in parsed_set if k not in pool]
        matched.extend(hit)
        missing.extend(miss)
        # 加权 coverage:sum(hit_w) / sum(all_w)
        all_w = sum(kw_weight.get(k, 0.5) for k in parsed_set)
        hit_w = sum(kw_weight.get(k, 0.5) for k in hit)
        coverage[group_name] = round(hit_w / all_w, 2) if all_w > 0 else 0.0

    # 整体 score: 跨 group 去重后,按权重加权的命中率
    all_parsed = (
        set(parsed["skills"]) | set(parsed["tools"]) | set(parsed["domains"])
    )
    all_matched = set(matched) & all_parsed
    if not all_parsed:
        score = 0
    else:
        all_w = sum(kw_weight.get(k, 0.5) for k in all_parsed)
        hit_w = sum(kw_weight.get(k, 0.5) for k in all_matched)
        score = round(hit_w / all_w * 100)

    # 收集 skill items (for suggestions 扩展,目前没用上,保留以备 Round 3)
    skill_items_per_group: dict[str, list[str]] = {
        sk: mats.get("skills", {}).get(sk, []) or []
        for sk in role_cfg["skill_keys"]
    }

    suggestions = _build_suggestions(
        missing=missing,
        score=score,
        all_parsed=bool(all_parsed),
        role_cfg=role_cfg,
        skill_items_per_group=skill_items_per_group,
    )

    return {
        "score": int(score),
        "matched_keywords": sorted(all_matched),
        "missing_keywords": sorted(set(missing)),
        "coverage": coverage,
        "suggestions": suggestions,
        "role_id": target_role,
        "tier_info": parsed.get("tier_info", {"required": [], "preferred": [], "bonus": []}),
        "recommendation": _classify_recommendation(int(score)),
    }
