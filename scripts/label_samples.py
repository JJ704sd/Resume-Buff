"""R3.5 label 标注: 对 jd_samples.json 10 份 JD x 6 role 跑 match_score, 基于最高分推断 label"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(r"D:/简历帮/backend")))
from core.jd_parser import match_score, parse_jd  # noqa: E402
from core.generator import load_materials, ENABLED_ROLES  # noqa: E402

SAMPLES = Path(r"D:/简历帮/简历帮知识库/jd_samples.json")

# 强制覆盖 user 复核的 label. 默认 False (只推断 label=None 的样本).
# 命令行用法: python label_samples.py --force
FORCE_OVERWRITE = "--force" in sys.argv


def infer_label(top_score: int, top_role: str, coverage: dict, matched: list, missing: list) -> tuple[str, str]:
    """
    基于最高分推断 label + label_note。

    规则:
      - top_score >= 80  → 推荐投 (高分, 素材覆盖好)
      - top_score 60-79  → 建议补充 (中等, 命中关键但有缺口)
      - top_score < 60   → 别投 (低分, JD 关键要求素材库覆盖不足)

    label_note 草稿包含: 最高分 role/分, coverage (各 group), 命中关键词 (top 5), 缺失关键词 (top 5)
    用户可以基于此快速复核或修改
    """
    if top_score >= 80:
        label = "推荐投"
    elif top_score >= 60:
        label = "建议补充"
    else:
        label = "别投"

    matched_top = matched[:5] if matched else []
    missing_top = missing[:5] if missing else []
    # coverage 是 dict[group_name -> float], 列出来
    cov_str = ", ".join(f"{k}={v:.0%}" for k, v in coverage.items()) if isinstance(coverage, dict) else "n/a"
    note = (
        f"AI 推断: 最高分 {top_score} (role={top_role}). "
        f"coverage: {cov_str}. "
        f"命中关键词: {', '.join(matched_top) if matched_top else '(无)'}. "
        f"缺失关键词: {', '.join(missing_top) if missing_top else '(无)'}. "
        f"待 user 复核"
    )
    return label, note


def main():
    materials = load_materials()
    samples_data = json.loads(SAMPLES.read_text(encoding="utf-8"))
    samples = samples_data["samples"]

    print("=" * 80)
    print("R3.5 label 标注 — 跑 10 份 JD x 各自 role_id_hint role = 10 次 match_score")
    print("=" * 80)
    print()

    role_scores_summary = {}

    for i, s in enumerate(samples, 1):
        sid = s["id"]
        text = s["text"]
        role_hint = s.get("role_id_hint")
        if not role_hint or role_hint not in ENABLED_ROLES:
            print(f"[{i}/10] {sid} | SKIP: role_id_hint={role_hint} 不在 ENABLED_ROLES")
            continue

        print(f"[{i}/10] {sid} | {s.get('company','?')} | {s.get('title','')[:50]} | role_hint={role_hint}")

        # 跑 role_id_hint 指定的 role (这是 ground truth role, 不是 top score)
        try:
            r = match_score(text, role_hint, materials)
            sc = r.get("score", 0)
            cov = r.get("coverage", {})
            matched = r.get("matched_keywords", [])
            missing = r.get("missing_keywords", [])
        except Exception as e:
            print(f"  ! error: {e}")
            continue

        # 写回 sample
        s["top_score"] = sc
        s["top_role"] = role_hint
        s["top_coverage"] = cov  # dict[group_name -> float]
        s["all_role_scores"] = {role_hint: sc}
        cov_pct = ", ".join(f"{k}={v:.0%}" for k, v in cov.items()) if isinstance(cov, dict) else "n/a"
        # 只对未标注的样本推断 label (保留 user 复核)
        # 强制覆盖用 --force (命令行)
        if s.get("label") is None or FORCE_OVERWRITE:
            s["label"], s["label_note"] = infer_label(sc, role_hint, cov, matched, missing)
            print(f"  -> {role_hint} = {sc} (cov {cov_pct}), label={s['label']} [推断]")
        else:
            print(f"  -> {role_hint} = {sc} (cov {cov_pct}), label={s['label']} [保留]")

        print(f"     matched: {matched[:5]}")
        print(f"     missing: {missing[:5]}")
        print()

        role_scores_summary.setdefault(role_hint, []).append(sc)

    # 更新 _meta
    samples_data["_meta"]["labeled_at"] = "2026-06-26"
    samples_data["_meta"]["label_method"] = (
        "AI 推断 (基于当前 match_score 阈值 80/60, 按每份 JD 的 role_id_hint 跑对应 role). "
        "label_note 含 top score / coverage / 命中 / 缺失关键词. 待 user 复核."
    )
    samples_data["_meta"]["score_run_count"] = len(samples)  # 每份只跑 1 个 role

    # role 维度统计
    samples_data["_meta"]["role_score_avg"] = {
        r: round(sum(v) / len(v), 1) for r, v in role_scores_summary.items()
    }

    # label 分布
    from collections import Counter
    label_dist = Counter(s["label"] for s in samples if s.get("label"))
    samples_data["_meta"]["label_distribution"] = dict(label_dist)

    SAMPLES.write_text(
        json.dumps(samples_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[OK] {SAMPLES} 已写回, 含 AI 推断 label + 上下文")
    print()
    print("label 分布:")
    for k, v in label_dist.most_common():
        print(f"  {k}: {v}")
    print()
    print("各 role 平均分 (按 role_id_hint):")
    for r, avg in samples_data["_meta"]["role_score_avg"].items():
        print(f"  {r}: {avg}")


if __name__ == "__main__":
    main()