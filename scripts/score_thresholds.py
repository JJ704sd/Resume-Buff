"""R3.5 Phase 3: 用 10 份 ground truth 跑当前 match_score 阈值的 confusion matrix,
识别 false negative / false positive, 决定要不要调阈值。
"""
import json
from pathlib import Path
from collections import Counter

SAMPLES = Path(r"D:/简历帮/简历帮知识库/jd_samples.json")

# 当前 R3-A 占位阈值
CURRENT_HIGH = 80
CURRENT_MID = 60


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

    # 排除公告型 (不参与阈值评估, match_score 不适用)
    eval_samples = [s for s in samples if s["label"] != "公告型"]
    skipped = [s for s in samples if s["label"] == "公告型"]

    print("=" * 80)
    print(f"R3.5 Phase 3 — Confusion Matrix (阈值 高>={CURRENT_HIGH} / 中>={CURRENT_MID})")
    print("=" * 80)
    print()
    print(f"评估样本: {len(eval_samples)} 份 (排除 {len(skipped)} 份公告型)")
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
        score = s["top_score"]
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
            "note": s.get("label_note", "")[:80],
        })

    accuracy = correct / len(eval_samples) if eval_samples else 0
    print(f"准确率: {correct}/{len(eval_samples)} = {accuracy:.0%}")
    print()
    print("详细分类:")
    for d in details:
        mark = "✅" if d["match"] else "❌"
        print(f"  {mark} {d['id'].ljust(35)} score={d['score']:3d}  true={d['true']:8s} pred={d['pred']:4s}")
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
        print(f"  · {s['id']} (score={s['top_score']}, role={s['top_role']}) — match_score 不适用")

    # 写报告 markdown
    report = []
    report.append("# R3.5 Phase 3 — 阈值调优 confusion matrix 报告\n")
    report.append(f"> 评估样本: {len(eval_samples)} 份 (排除 {len(skipped)} 份公告型)\n")
    report.append(f"> 阈值: 高>={CURRENT_HIGH} / 中>={CURRENT_MID}\n")
    report.append(f"> 准确率: **{accuracy:.0%}** ({correct}/{len(eval_samples)})\n\n")
    report.append("## 评估集 label 分布\n\n")
    for k, v in label_dist.most_common():
        report.append(f"- {k}: {v}\n")
    report.append("\n")
    report.append("## 详细分类\n\n")
    report.append("| id | true label | score | pred | match | note |\n")
    report.append("|---|---|---|---|---|---|\n")
    for d in details:
        mark = "✅" if d["match"] else "❌"
        note = d["note"].replace("|", "\\|").replace("\n", " ")
        report.append(f"| {d['id']} | {d['true']} | {d['score']} | {d['pred']} | {mark} | {note} |\n")
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
        report.append(f"- 当前阈值 **{CURRENT_HIGH}/{CURRENT_MID} 准确率 {accuracy:.0%}** ≥ 85%, 保留\n")
    else:
        report.append(f"- 当前阈值 **{CURRENT_HIGH}/{CURRENT_MID} 准确率 {accuracy:.0%}** < 85%, **需要进一步分析**\n")
        report.append("- false negative 都是 match_score 漏匹配 (score=0 但 label=推荐投/建议补充), 不是阈值问题\n")
        report.append("- 见下方 match_score 漏匹配清单\n\n")
        report.append("### match_score 漏匹配清单 (R3.5.5 候选修)\n\n")
        for d in details:
            if d["match"]:
                continue
            report.append(f"- `{d['id']}` (true={d['true']}, score={d['score']}, pred={d['pred']})\n")

    out = Path(r"D:/简历帮/AI岗位JD库_v4_intern_阈值调优报告.md")
    out.write_text("".join(report), encoding="utf-8")
    print(f"\n[OK] 报告写入: {out}")


if __name__ == "__main__":
    main()