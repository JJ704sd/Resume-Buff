#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
v4 黄金标的 match_score 实测:
  - JD-B010 字节 ByteIntern 2027 届
  - JD-D003 DeepSeek AGI 大模型实习
  - JD-A012 阿里 2027 届实习生 (AI 80%+)

跑 3 JD × 6 role = 18 次 match_score, 输出对比表 + 改进建议
"""
import json
import sys
from pathlib import Path

# 把 backend 加进 sys.path 让 core 模块可导
sys.path.insert(0, str(Path(r"D:\简历帮\backend")))

from core.jd_parser import parse_jd, match_score  # noqa: E402
from core.generator import load_materials, ENABLED_ROLES  # noqa: E402

# 路径
JD_V4 = Path(r"D:\简历帮\AI岗位JD库_v4_intern.json")
OUT_REPORT = Path(r"D:\简历帮\AI岗位JD库_v4_黄金标的match报告.md")

GOLDEN_IDS = ["JD-B010", "JD-D007", "JD-A012"]


def get_jd_text(jd_id: str) -> dict:
    data = json.loads(JD_V4.read_text(encoding="utf-8"))
    for jd in data["jds"]:
        if jd["id"] == jd_id:
            return jd
    raise KeyError(f"未找到 {jd_id}")


def main():
    materials = load_materials()

    report: list[str] = []
    report.append("# AI 黄金标的 × 素材库 match_score 实测报告\n")
    report.append(f"> 测试日期: 2026-06-26  \n")
    report.append(f"> 素材库: backend/data/materials.json (版本 {materials.get('_meta', {}).get('version', '?')})  \n")
    report.append(f"> 评分规则: KEYWORD_GROUPS 加权 (skill=1.0, 加分=0.5)  \n")
    report.append(f"> 推荐阈值: ≥80 高 / 60-79 中 / <60 低  \n\n")
    report.append("## ⚠️ 评分局限性说明（必读）\n\n")
    report.append("- **JD-B010 字节 ByteIntern** / **JD-A012 阿里 2027 届**：这 2 份是\"**招聘规模公告型 JD**\"，")
    report.append("full_text 主要是招聘规模 + 业务集团列表，**不含具体技能关键词**。")
    report.append("  - JD-B010：只匹配到 1 个 `LLM`，全 role 100 分 = **false positive**（应解读为\"无明确技术门槛\"，适合海投）")
    report.append("  - JD-A012：0 个关键词，全 role 0 分 = **false negative**（实际是大池子，靠学历 + 学校光环）")
    report.append("- **JD-D007 DeepSeek AGI 大模型实习**：是真正的\"**技术要求型 JD**\"，评分有参考价值\n\n")
    report.append("**建议**：对公告型 JD，应结合学校层次 + GPA + 转正概率综合判断，不要只看 match_score。\n\n")
    report.append("---\n\n")

    # 汇总表: 3 JD × 6 role
    summary_rows: list[list[str]] = []
    summary_rows.append(["JD ID", "公司", "标题", "tech_metric", "product", "algorithm", "data_annot", "test_qa", "general"])

    detailed_results: dict[str, dict[str, dict]] = {}

    for jd_id in GOLDEN_IDS:
        jd = get_jd_text(jd_id)
        jd_full_text = jd.get("full_text", "")
        jd_parsed = parse_jd(jd_full_text)

        report.append(f"## {jd_id} — {jd['company']}：{jd['title']}\n\n")
        report.append(f"> 评分: **{jd['scores']['total']}** ({jd['scores']['grade']})  \n")
        report.append(f"> 实习信号: {jd.get('intern_match', '?')} — {', '.join(jd.get('intern_match_reasons', []))[:120]}  \n\n")

        report.append("### JD 解析 (parse_jd)\n\n")
        report.append(f"- **技能关键词**: {', '.join(jd_parsed['skills']) or '_(无)_'}  \n")
        report.append(f"- **工具关键词**: {', '.join(jd_parsed['tools']) or '_(无)_'}  \n")
        report.append(f"- **领域关键词**: {', '.join(jd_parsed['domains']) or '_(无)_'}  \n")
        report.append(f"- **经验要求**: {jd_parsed['experience_years']}  \n")
        report.append(f"- **学历要求**: {jd_parsed['education']}  \n")
        report.append(f"- **tier_info**: required=`{', '.join(jd_parsed['tier_info'].get('required', []))}` | "
                       f"preferred=`{', '.join(jd_parsed['tier_info'].get('preferred', []))}` | "
                       f"bonus=`{', '.join(jd_parsed['tier_info'].get('bonus', []))}`  \n\n")

        report.append("### 6 个 role 的 match_score 对比\n\n")
        report.append("| role | 评分 | 推荐 | matched | missing | coverage (sk/to/do) | 建议 |\n")
        report.append("|---|---|---|---|---|---|---|\n")

        detailed_results[jd_id] = {}
        row = [jd_id, jd["company"], jd["title"][:30] + ("…" if len(jd["title"]) > 30 else "")]

        for role in ENABLED_ROLES:
            res = match_score(jd_full_text, role, materials)
            detailed_results[jd_id][role] = res
            row.append(f"{res['score']} ({res['recommendation']})")

            cov = res["coverage"]
            matched_str = ", ".join(res["matched_keywords"][:5]) or "—"
            missing_str = ", ".join(res["missing_keywords"][:5]) or "—"
            sug_first = res["suggestions"][0] if res["suggestions"] else ""
            cov_str = f"{cov['skills']}/{cov['tools']}/{cov['domains']}"

            report.append(
                f"| `{role}` | **{res['score']}** | {res['recommendation']} | "
                f"{matched_str} | {missing_str} | {cov_str} | "
                f"{sug_first[:80]}{'…' if len(sug_first) > 80 else ''} |\n"
            )

        report.append("\n")
        summary_rows.append(row)

    # 汇总对比表
    report.append("---\n\n## 三份黄金 JD × 6 role 总览\n\n")
    report.append("| " + " | ".join(summary_rows[0]) + " |\n")
    report.append("|" + "|".join(["---"] * len(summary_rows[0])) + "|\n")
    for row in summary_rows[1:]:
        report.append("| " + " | ".join(row) + " |\n")
    report.append("\n")

    # 找出最佳 role × JD 组合 + 重点建议
    report.append("## 重点建议（按 JD 分组）\n\n")
    for jd_id in GOLDEN_IDS:
        jd = get_jd_text(jd_id)
        results = detailed_results[jd_id]
        best_role = max(results.keys(), key=lambda r: results[r]["score"])
        best_res = results[best_role]

        report.append(f"### {jd_id} → `{best_role}` (最佳匹配 {best_res['score']} 分)\n\n")
        report.append(f"**推荐意见**: {best_res['recommendation']}  \n\n")
        report.append(f"**匹配关键词** ({len(best_res['matched_keywords'])}):  \n")
        report.append(f"`{', '.join(best_res['matched_keywords']) or '—'}`\n\n")
        report.append(f"**缺失关键词** ({len(best_res['missing_keywords'])}):  \n")
        report.append(f"`{', '.join(best_res['missing_keywords']) or '—'}`\n\n")
        report.append("**完整建议**:\n\n")
        for i, s in enumerate(best_res["suggestions"], 1):
            report.append(f"{i}. {s}\n")
        report.append("\n")

    # 写报告
    OUT_REPORT.write_text("".join(report), encoding="utf-8")
    print(f"[OK] {OUT_REPORT} ({OUT_REPORT.stat().st_size} bytes)")

    # 同时打印 summary 到 stdout
    print("\n=== Summary ===")
    for row in summary_rows:
        print(" | ".join(row))


if __name__ == "__main__":
    main()