#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
按"实习岗"维度对 v2 库重筛
判定规则:
- strong: 标题明文"实习"/"Intern" / 薪资"元/天" / 正文"实习生 HC"等强信号
- campus_to_intern: 校招岗(应届/26-27届/年限≤1/牛客校招页),应届生可转实习通道
- weak: 1-3 年经验,AI 相关但没明说校招/应届(初级社招,实习一般进不去)
- none: 3+ 年经验或资深岗(50K+ / 高级/专家/资深字眼)
"""
import json
import re
from pathlib import Path

SRC = Path(r"D:\简历帮\AI岗位JD库_v4_intern.json")
DST_JSON = Path(r"D:\简历帮\AI岗位JD库_v4_intern.json")
DST_REPORT = Path(r"D:\简历帮\AI岗位JD库_v4_intern_筛选报告.md")

# 实习强信号关键词
STRONG_TITLE = ["实习", "Intern"]
STRONG_TEXT = ["实习生", "实习期", "实习岗", "实习生 HC", "实习通道"]
STRONG_SALARY_PATTERN = re.compile(r"\d+\s*-\s*\d+\s*元\s*/\s*天")  # 300-500元/天

# 校招可转实习
CAMPUS_TITLE = ["校招", "应届", "届"]
CAMPUS_YEAR_REGEX = re.compile(r"(20\s?2[5-7]\s?届|2[5-7]\s?届)")  # 兼容 26届 / 2026 届 / 26 届
CAMPUS_TEXT = ["应届生", "在校生", "可实习", "实习生和校招"]

# 资深岗标记
SENIOR_TITLE = ["高级", "资深", "专家", "Senior", "Sr.", "Top"]
SENIOR_SALARY_MIN_K = 50  # 50K+

# 经验年限提取 — 严格匹配:数字+年+(经验/工作/研究/算法/开发等)
# 用 \d{1,2} 避免 2023/2026 这种年份被误抓
YEAR_PATTERN = re.compile(
    r"(\d{1,2})\s*年(?:\s*以上)?\s*(?:工作经验?|工作经历|算法经验|开发经验|研究经历|NLP\s*经验|深度学习|智能产品|测试经验|产品经验|经验|工作)"
)
YEAR_LIMIT_PATTERN = re.compile(r"(\d+)\s*年(?:以下)?(?:经验|工作)?")
NONE_PATTERN = re.compile(r"经验不限|无经验要求|不限")


def detect_intern_match(jd: dict) -> tuple[str, list[str]]:
    """返回 (intern_match_level, reasons[])"""
    title = jd.get("title", "")
    text = jd.get("full_text", "")
    salary = jd.get("salary_range", "")
    url = jd.get("source_url", "")
    reasons = []

    combined_text = f"{title}\n{text}\n{salary}"

    # ========== 强信号判定 ==========
    if any(k in title for k in STRONG_TITLE):
        reasons.append(f"标题含 '实习'/'Intern' ({title})")
        return "strong", reasons
    if STRONG_SALARY_PATTERN.search(salary):
        reasons.append(f"薪资以'元/天'计 ({salary}) — 典型实习薪资")
        return "strong", reasons
    for kw in STRONG_TEXT:
        if kw in text or kw in salary:
            reasons.append(f"正文/薪资含 '{kw}'")
            return "strong", reasons

    # 牛客网校招专页 → 一律豁免资深判定(校招薪资 50K+ 是白菜价,不是资深)
    is_nowcampus = "nowcoder.com" in url

    # ========== 资深岗判定 ==========
    # 临时探测:标题/正文是否已含校招信号(届次标识/校招/应届)
    has_campus_signal = (
        any(k in title for k in CAMPUS_TITLE)
        or bool(CAMPUS_YEAR_REGEX.search(combined_text))
        or any(k in combined_text for k in CAMPUS_TEXT)
        or is_nowcampus
    )
    is_senior = False
    if any(k in title for k in SENIOR_TITLE) and not has_campus_signal:
        is_senior = True
        reasons.append(f"标题含资深关键词: {[k for k in SENIOR_TITLE if k in title]}")
    # 薪资下限提取 (取第一个数字,单位 K) — 校招岗豁免
    salary_match = re.search(r"(\d+)\s*-\s*(\d+)\s*K", salary)
    if salary_match and not has_campus_signal:
        lo, hi = int(salary_match.group(1)), int(salary_match.group(2))
        if lo >= SENIOR_SALARY_MIN_K or hi >= 80:
            is_senior = True
            reasons.append(f"薪资 {lo}-{hi}K 偏高(资深级)")

    # 提取经验年限
    years_match = YEAR_PATTERN.findall(text)
    years_req = max([int(y) for y in years_match], default=0)

    # ========== 校招可转实习 ==========
    is_campus = is_nowcampus  # 牛客校招页默认是校招
    if is_nowcampus:
        reasons.append("URL 为牛客网校招专页(默认校招)")
    # 标题含校招/应届
    for kw in CAMPUS_TITLE:
        if kw in title:
            is_campus = True
            reasons.append(f"标题含 '{kw}'")
    # 文本含 26/27 届 (regex 兼容 "26届"/"2026 届"/"26 届")
    m = CAMPUS_YEAR_REGEX.search(combined_text)
    if m:
        is_campus = True
        reasons.append(f"文本含届次标识 '{m.group(0).strip()}'")
    # 文本含应届/在校生
    for kw in CAMPUS_TEXT:
        if kw in combined_text:
            is_campus = True
            reasons.append(f"文本含 '{kw}'")
    # 经验年限 ≤ 1
    if 0 < years_req <= 1 and not is_senior:
        is_campus = True
        reasons.append(f"经验要求仅 {years_req} 年,门槛低")
    # 经验不限(同时搜 text 和 salary,有的 JD 把"经验不限"写在 salary 字段)
    if (NONE_PATTERN.search(text) or NONE_PATTERN.search(salary)) and not is_senior:
        is_campus = True
        reasons.append("经验不限")

    if is_campus and not is_senior:
        return "campus_to_intern", reasons

    # ========== 弱匹配 ==========
    if 1 < years_req <= 3 and not is_senior:
        reasons.append(f"经验要求 {years_req} 年(1-3 年区间,初级社招,实习一般不开放)")
        return "weak", reasons
    if years_req == 0 and not is_senior:
        # 没明说年限,但也没明说校招 — 看 title 是否偏 PM/算法硬核岗
        reasons.append("未明说年限,但也无校招/应届标识(默认初级社招)")
        return "weak", reasons

    # ========== 无匹配 ==========
    if years_req >= 3:
        reasons.append(f"经验要求 {years_req} 年(3+ 年,明确社招)")
    if is_senior:
        reasons.append("资深岗/高级岗")
    if not reasons:
        reasons.append("默认社招")
    return "none", reasons


def main():
    data = json.loads(SRC.read_text(encoding="utf-8"))
    jds = data["jds"]

    # 统计 + 加标签
    stats = {"strong": 0, "campus_to_intern": 0, "weak": 0, "none": 0}
    intern_jds = []

    for jd in jds:
        level, reasons = detect_intern_match(jd)
        jd["intern_match"] = level
        jd["intern_match_reasons"] = reasons
        stats[level] += 1
        intern_jds.append(jd)

    # 排序: strong > campus_to_intern > weak > none, 同级按总分降序
    order = {"strong": 0, "campus_to_intern": 1, "weak": 2, "none": 3}
    intern_jds.sort(key=lambda x: (order[x["intern_match"]], -x["scores"]["total"]))

    # 更新 meta
    data["jds"] = intern_jds
    data["_meta"]["version"] = "4.0.0-intern"
    data["_meta"]["generated_at"] = "2026-06-26"
    data["_meta"]["filter_dimension"] = "实习岗匹配度（v4 补搜版）"
    data["_meta"]["intern_match_rules"] = {
        "strong": "标题/正文/薪资强信号:实习/Intern/元/天/实习生 HC",
        "campus_to_intern": "校招可转实习:校招/应届/26-27届/经验≤1年/牛客校招页",
        "weak": "1-3 年初级社招,实习一般不开放",
        "none": "3+ 年经验或资深岗"
    }
    data["_meta"]["stats"]["intern_match"] = stats
    data["_meta"]["stats"]["total"] = len(intern_jds)

    # 输出 JSON
    DST_JSON.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    print(f"[OK] {DST_JSON} ({DST_JSON.stat().st_size} bytes)")

    # 生成 Markdown 报告
    md = []
    md.append("# AI 岗位 JD 库 v4 — 实习岗筛选报告（补搜版）\n")
    md.append(f"> 筛选日期: 2026-06-26  \n")
    md.append(f"> 筛选维度: **实习岗匹配度** (用户需求: 校招岗位为主, 搜索目标 = **实习岗**)  \n")
    md.append(f"> 数据基础: v4.0 ({len(intern_jds)} 份 JD, = v3 42 份 + 补搜 {len(intern_jds) - 42} 份)  \n")
    md.append(f"> 输出: AI岗位JD库_v4_intern.json\n\n")

    md.append("## 一、判定规则\n\n")
    md.append("| 等级 | 判定标准 | 实习可行性 |")
    md.append("|---|---|---|")
    md.append("| 🟢 **strong** | 标题明文\"实习\"/\"Intern\" / 薪资\"元/天\" / 正文\"实习生 HC\" | **直接可投实习** |")
    md.append("| 🟡 **campus_to_intern** | 校招岗(应届/26-27届/经验≤1年/牛客校招页) | **应届生通道,实习可转** |")
    md.append("| 🟠 **weak** | 1-3 年经验,无校招/应届标识 | 实习一般不开放 |")
    md.append("| 🔴 **none** | 3+ 年经验 或 资深岗(高级/专家/50K+) | **社招,实习不可投** |")
    md.append("\n")

    md.append("## 二、统计概览\n\n")
    md.append(f"- 总计: **{len(intern_jds)}** 份")
    md.append(f"- 🟢 strong (直接可投实习): **{stats['strong']}** 份 ({stats['strong']/len(intern_jds)*100:.0f}%)")
    md.append(f"- 🟡 campus_to_intern (校招可转实习): **{stats['campus_to_intern']}** 份 ({stats['campus_to_intern']/len(intern_jds)*100:.0f}%)")
    md.append(f"- 🟠 weak (初级社招,实习不开放): **{stats['weak']}** 份 ({stats['weak']/len(intern_jds)*100:.0f}%)")
    md.append(f"- 🔴 none (社招,实习不可投): **{stats['none']}** 份 ({stats['none']/len(intern_jds)*100:.0f}%)")
    md.append("")
    md.append(f"**核心结论**: v4 库共 **{len(intern_jds)}** 份 (= v3 42 份 + 补搜 {len(intern_jds) - 42} 份),其中 **{stats['strong'] + stats['campus_to_intern']}** 份实习可投/可转 ({((stats['strong']+stats['campus_to_intern'])/len(intern_jds))*100:.0f}%)。v3 仅有 8 份 (19%),v4 补搜后清单从 19% 跃升至 {((stats['strong']+stats['campus_to_intern'])/len(intern_jds))*100:.0f}% (**5.9x 增长**)。\n\n")

    md.append("## 三、🟢 强实习匹配 (直接可投)\n")
    strong_jds = [j for j in intern_jds if j["intern_match"] == "strong"]
    if strong_jds:
        md.append("| JD ID | 公司 | 标题 | 评分 | 实习信号 |")
        md.append("|---|---|---|---|---|")
        for j in strong_jds:
            md.append(f"| {j['id']} | {j['company']} | {j['title']} | {j['scores']['total']} | {', '.join(j['intern_match_reasons'])} |")
    else:
        md.append("_(无)_")
    md.append("")

    md.append("## 四、🟡 校招可转实习 (应届通道)\n")
    campus_jds = [j for j in intern_jds if j["intern_match"] == "campus_to_intern"]
    if campus_jds:
        md.append("| JD ID | 公司 | 标题 | 评分 | 校招信号 |")
        md.append("|---|---|---|---|---|")
        for j in campus_jds:
            md.append(f"| {j['id']} | {j['company']} | {j['title']} | {j['scores']['total']} | {', '.join(j['intern_match_reasons'])} |")
    else:
        md.append("_(无)_")
    md.append("")

    md.append("## 五、🟠 弱匹配 (初级社招,实习不开放)\n")
    md.append("| JD ID | 公司 | 标题 | 评分 | 备注 |")
    md.append("|---|---|---|---|---|")
    for j in [x for x in intern_jds if x["intern_match"] == "weak"]:
        md.append(f"| {j['id']} | {j['company']} | {j['title']} | {j['scores']['total']} | {', '.join(j['intern_match_reasons'])} |")
    md.append("")

    md.append("## 六、🔴 社招为主 (实习不可投)\n")
    md.append("| JD ID | 公司 | 标题 | 评分 | 备注 |")
    md.append("|---|---|---|---|---|")
    for j in [x for x in intern_jds if x["intern_match"] == "none"]:
        md.append(f"| {j['id']} | {j['company']} | {j['title']} | {j['scores']['total']} | {', '.join(j['intern_match_reasons'])} |")
    md.append("")

    md.append("## 七、按公司维度统计\n\n")
    md.append("| 公司 | 🟢strong | 🟡campus | 🟠weak | 🔴none | 实习可投小计 |")
    md.append("|---|---|---|---|---|---|")
    by_co = {}
    for j in intern_jds:
        co = j["company"]
        by_co.setdefault(co, {"strong": 0, "campus_to_intern": 0, "weak": 0, "none": 0})
        by_co[co][j["intern_match"]] += 1
    for co, s in sorted(by_co.items()):
        intern_ok = s["strong"] + s["campus_to_intern"]
        md.append(f"| {co} | {s['strong']} | {s['campus_to_intern']} | {s['weak']} | {s['none']} | **{intern_ok}** |")
    md.append("")

    md.append("## 八、下一步建议\n\n")
    md.append(f"1. **补搜成果**: v3 (42) → v4 ({len(intern_jds)}) 新增 {len(intern_jds) - 42} 份实习岗,实习可投清单从 8 → {stats['strong'] + stats['campus_to_intern']} 份 (**5.9x 增长**)")
    md.append("2. **投递策略 — 按等级分批**:")
    md.append("   - 🟢 **第一波**（直接投, 实习 40 份）: 阿里通义 7 个、字节 ByteIntern 7 个、美团 5 个、DeepSeek 3 个、腾讯 2 个、华为云 / 第四范式 / 启元世界 / BOSS 直聘 等")
    md.append("   - 🟡 **第二波**（应届通道, 7 份）: 拼多多 / 阿里通义测开 / 钉钉 AI PM / 字节 AI 测试开发 / 腾讯 2026 校招 等")
    md.append("   - 🟠 **第三波**（待评估 weak 23 份）: 部分 weak 岗可能实际开放应届通道,需逐个验证 JD 全文")
    md.append("3. **重点黄金标的 (按优先级)**:")
    md.append("   - **JD-B010** 字节 ByteIntern 2027 届（7000+ 名, 研发 4800+ 转正率 50%+）")
    md.append("   - **JD-B011** 字节 Seed Top Seed（顶尖人才计划, 虚拟股激励）")
    md.append("   - **JD-A012** 阿里 2027 届（AI 岗占 80%, 16 个业务集团）")
    md.append("   - **JD-D003** DeepSeek AGI 大模型实习（北京, 500-1000 元/天, 转正名额, 租房补 3000/月）")
    md.append("   - **JD-T009** 腾讯 2026 实习（10000+ 岗, AI 大幅扩招, 技术 60%+）")
    md.append("   - **JD-AT001** 蚂蚁 2026 春招（70%+ AI 岗, 6 城）")
    md.append("4. **保留 v2/v3 库**: 社招 JD 未来找全职仍可用,不必删除\n")

    DST_REPORT.write_text("\n".join(md), encoding="utf-8")
    print(f"[OK] {DST_REPORT} ({DST_REPORT.stat().st_size} bytes)")
    print(f"\n[Stats] strong={stats['strong']} campus_to_intern={stats['campus_to_intern']} weak={stats['weak']} none={stats['none']}")


if __name__ == "__main__":
    main()