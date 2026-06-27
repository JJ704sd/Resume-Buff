"""R3.5.1: 阈值调优实跑模式 — 跑当前 match_score 拿 score, 不读 jd_samples.json frozen top_score.

R3.5 时 score_thresholds.py 读 jd_samples.json 里的 top_score / top_role / top_coverage,
那些字段是历史 snapshot 冻结值 (R3.5 当时 AI 推断 score 写死的), 不会随 match_score
改动更新. R3.5+ / R3.5+ (b) 修 match_score 后, frozen top_score 跟实跑结果不一致,
导致本脚本的"准确率"评估失去参考价值.

R3.5.1 起改为实跑:
  - score    = match_score(text, role_id_hint, materials)["score"]
  - coverage = match_score 返回的 coverage
  - role     = role_id_hint (user 标定的期望 role; 不再 6 role 取最高 — 简化, 跟 R3.5
              报告里 top_role 不直接可比, 但阈值评估本身不依赖 6 role 扫描)

跑法:
  D:\\python3.11\\python.exe scripts/score_thresholds.py
  → 写报告到 AI岗位JD库_v4_intern_阈值调优报告.md
"""
import json
import sys
from pathlib import Path
from collections import Counter

# scripts/ 是 repo 根的子目录, backend/ 跟它平级. 把 backend/ 加到 sys.path 才能 import core.*
BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from core.generator import load_materials  # noqa: E402
from core.jd_parser import match_score  # noqa: E402

SAMPLES = Path(r"D:/简历帮/简历帮知识库/jd_samples.json")

# 当前 R3.5 锁死阈值, R3.5.1 不调
CURRENT_HIGH = 80
CURRENT_MID = 60

# R3.5.1 元信息
VERSION = "R3.5.1 (实跑模式, 2026-06-27)"


def classify(score: int, high: int, mid: int) -> str:
    """把 0-100 分按阈值转 recommendation: 高/中/低"""
    if score >= high:
        return "高"
    if score >= mid:
        return "中"
    return "低"


def label_to_rec(label: str) -> str:
    """把 ground truth label 转期望 recommendation (公告型不算)"""
    return {"推荐投": "高", "建议补充": "中", "别投": "低"}.get(label, "?")


def main():
    samples = json.loads(SAMPLES.read_text(encoding="utf-8"))["samples"]
    mats = load_materials()  # R3.5.1: 实跑 match_score 需要素材库

    # 排除公告型 (不参与阈值评估, match_score 不适用)
    eval_samples = [s for s in samples if s["label"] != "公告型"]
    skipped = [s for s in samples if s["label"] == "公告型"]

    print("=" * 80)
    print(f"{VERSION} — Confusion Matrix (阈值 高>={CURRENT_HIGH} / 中>={CURRENT_MID})")
    print("=" * 80)
    print()
    print(f"评估样本: {len(eval_samples)} 份 (排除 {len(skipped)} 份公告型)")
    print(f"实跑模式: score = match_score(text, role_id_hint, materials)['score']")
    print(f"          role = role_id_hint (user 标定的期望 role)")
    print()

    # label 分布
    label_dist = Counter(s["label"] for s in eval_samples)
    print("评估集 label 分布:")
    for k, v in label_dist.most_common():
        print(f"  {k}: {v}")
    print()

    # 跑当前阈值
    print(f"--- 当前阈值 {CURRENT_HIGH}/{CURRENT_MID} ---")
    correct = 0
    cm = Counter()  # (true_label, pred_rec) -> count
    details = []
    for s in eval_samples:
        true_label = s["label"]
        role = s["role_id_hint"]
        # R3.5.1: 实跑 match_score, 不再读 s["top_score"]
        result = match_score(s["text"], role, mats)
        score = result["score"]
        coverage = result["coverage"]
        pred_rec = classify(score, CURRENT_HIGH, CURRENT_MID)
        true_rec = label_to_rec(true_label)
        match = pred_rec == true_rec
        if match:
            correct += 1
        cm[(true_label, pred_rec)] += 1
        details.append({
            "id": s["id"],
            "true": true_label,
            "score": score,
            "pred": pred_rec,
            "match": match,
            "role": role,
            "coverage": coverage,
            "note": s.get("label_note", "")[:80],
        })

    accuracy = correct / len(eval_samples) if eval_samples else 0
    print(f"准确率: {correct}/{len(eval_samples)} = {accuracy:.0%}")
    print()
    print("详细分类:")
    for d in details:
        mark = "✅" if d["match"] else "❌"
        print(
            f"  {mark} {d['id'].ljust(35)} "
            f"score={d['score']:3d}  true={d['true']:8s} pred={d['pred']:4s}"
        )
    print()

    # 3x3 confusion matrix
    print("Confusion matrix (rows=true label, cols=pred rec):")
    print(f"  {'':12s}  pred=高   pred=中   pred=低")
    for true_l in ["推荐投", "建议补充", "别投"]:
        row = [f"  true={true_l:8s}"]
        for pred_r in ["高", "中", "低"]:
            c = cm.get((true_l, pred_r), 0)
            row.append(f"  {c:6d}  ")
        print(" ".join(row))
    print()

    # false 分析
    print("--- False 分析 ---")
    for d in details:
        if d["match"]:
            continue
        print(f"  ❌ {d['id']}")
        print(f"     score={d['score']}, true={d['true']}, pred={d['pred']}")
        print(f"     note: {d['note']}")
    print()

    # 公告型跳过说明
    print(f"--- 公告型 (不参与评估, {len(skipped)} 份) ---")
    for s in skipped:
        # R3.5.1: 公告型不实跑 (match_score 对公告型不适用), 沿用 frozen top_score 仅作展示
        print(
            f"  · {s['id']} (frozen top_score={s['top_score']}, "
            f"role={s['top_role']}) — match_score 不适用"
        )

    # 写报告 markdown
    report = []
    report.append(f"# R3.5.1 — 阈值调优 confusion matrix 报告 ({VERSION})\n")
    report.append(f"> 评估样本: {len(eval_samples)} 份 (排除 {len(skipped)} 份公告型)\n")
    report.append(f"> 阈值: 高>={CURRENT_HIGH} / 中>={CURRENT_MID}\n")
    report.append(f"> 实跑模式: score = match_score(text, role_id_hint, materials)['score']\n")
    report.append(f"> 准确率: **{accuracy:.0%}** ({correct}/{len(eval_samples)})\n\n")
    report.append("## 评估集 label 分布\n\n")
    for k, v in label_dist.most_common():
        report.append(f"- {k}: {v}\n")
    report.append("\n")
    report.append("## 详细分类\n\n")
    report.append("| id | role | true label | score | pred | match | coverage (sk/to/do) | note |\n")
    report.append("|---|---|---|---|---|---|---|---|\n")
    for d in details:
        mark = "✅" if d["match"] else "❌"
        cov = d["coverage"]
        cov_str = f"{cov.get('skills', 0):.1f}/{cov.get('tools', 0):.1f}/{cov.get('domains', 0):.1f}"
        note = d["note"].replace("|", "\\|").replace("\n", " ")
        report.append(
            f"| {d['id']} | {d['role']} | {d['true']} | {d['score']} | {d['pred']} | {mark} | {cov_str} | {note} |\n"
        )
    report.append("\n")
    report.append("## Confusion Matrix\n\n")
    report.append("| true \\ pred | 高 | 中 | 低 |\n")
    report.append("|---|---|---|---|\n")
    for true_l in ["推荐投", "建议补充", "别投"]:
        cells = [str(cm.get((true_l, pred_r), 0)) for pred_r in ["高", "中", "低"]]
        report.append(f"| {true_l} | {' | '.join(cells)} |\n")
    report.append("\n")
    report.append("## 结论\n\n")
    if accuracy >= 0.85:
        report.append(
            f"- 当前阈值 **{CURRENT_HIGH}/{CURRENT_MID} 准确率 {accuracy:.0%}** ≥ 85%, 保留\n"
        )
    else:
        report.append(
            f"- 当前阈值 **{CURRENT_HIGH}/{CURRENT_MID} 准确率 {accuracy:.0%}** < 85%, "
            "**需要进一步分析**\n"
        )
        report.append("- 误判原因见下方 False 详情\n\n")
        report.append("### False 详情\n\n")
        for d in details:
            if d["match"]:
                continue
            report.append(
                f"- `{d['id']}` (true={d['true']}, score={d['score']}, pred={d['pred']})\n"
            )
    report.append("\n## R3.5.1 vs R3.5 差异说明\n\n")
    report.append("- R3.5 报告读 frozen top_score (R3.5 时 AI 推断 score 写死), 不会随 match_score 改动更新\n")
    report.append("- R3.5.1 改为实跑 match_score, 反映当前 match_score 实现 + 真实素材库状态\n")
    report.append("- frozen 字段 (top_score / top_role / top_coverage / all_role_scores) 仍保留在 jd_samples.json "
                  "作为历史 snapshot, 不删除以保留 R3.5 时点的 ground truth\n")
    report.append("- baiyun_2026_product 修后 score=33 ('低') vs ground truth '中', "
                  "根因 user 素材库缺 PM 经验, 待 user 补 PM 素材 (R3.5+ (b) commit ed57e25)\n")

    out = Path(r"D:/简历帮/AI岗位JD库_v4_intern_阈值调优报告.md")
    out.write_text("".join(report), encoding="utf-8")
    print(f"\n[OK] 报告写入: {out}")


if __name__ == "__main__":
    main()