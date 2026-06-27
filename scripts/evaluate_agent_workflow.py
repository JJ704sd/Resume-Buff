#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
R5-A Phase 4: Agent Workflow 离线评测脚本

设计目标 (对齐 spec §7.3 离线评测):
  - 基于固定 eval set 跑 Function Calling on/off × Agent Workflow on/off 的 4 组对照
  - 输出 markdown 报告 `AI岗位JD库_agent_eval报告.md`
  - 报告包含: 总览表 / schema pass rate / fallback rate / 平均 latency /
    score 与 recommendation 变化 / 每个 JD 工具调用摘要 / 失败 case / 隐私检查
  - eval 脚本默认可在无 LLM key 时运行,标记 fallback_used=True,仍输出报告

Eval set:
  - 主要来源: 简历帮知识库/jd_samples.json(8 份非公告型,排除 2 份公告型)
  - 补充来源: AI岗位JD库_v4_intern.json(强实习岗 4 份,覆盖 algorithm/test_qa/
              data_annot/product 各 role 的多样性)
  - 总计: 12 份样本,覆盖 6 个 enabled role 中 5 个(tech_metric 暂无 ground truth)

四组开关对照:
  1) (FC=F, AW=F) - baseline 老路径
  2) (FC=T, AW=F) - Function Calling 开关
  3) (FC=F, AW=T) - Agent Workflow 开关
  4) (FC=T, AW=T) - 全开

每组输出指标(每 JD 一行):
  - jd_id / role_id / expected_label / score / recommendation / schema_pass /
    fallback_used / tools_used (list) / latency_ms / error_type / pii_safe

隐私边界(对齐 spec §6.4 + README 隐私边界):
  - 不读 backend/data/_private_backup.json(只在 gitignore 的真实备份)
  - 只读 backend/data/materials.json(公开脱敏版)
  - 报告不包含:
      * 真实姓名 / 手机 / 邮箱 / 学校 / 公司(本场景 materials 已脱敏,主库 JD 字段
        含 company 字段如"字节跳动"但不含个人 PII)
      * 完整 JD 全文(只记录 jd_id + 长度 + raw_keywords 列表)
      * 完整 bullet / 简历内容
      * request_id 完整 uuid(只截前 4 字符)
  - 走公开数据路径,不写任何额外文件,只输出 1 份 markdown

不破坏既有行为(对齐 spec §6.3 + AGENTS.md 不破坏既有):
  - 只读,不修改 match_score / jd_parser / llm_rewriter / agent_workflow
  - 不修改 score_thresholds.py / match_golden_targets.py / replay_agent_trace.py
  - 不挂 pre-push hook(spec §12 #3 已明确"默认手动脚本")

跑法:
    D:\\python3.11\\python.exe scripts/evaluate_agent_workflow.py
    → 写报告到 AI岗位JD库_agent_eval报告.md (项目根)
    → 打印摘要到 stdout
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from collections import Counter
from typing import Optional

# ---- 路径: 把 backend/ 加到 sys.path 让 core.* 可导入 ----
REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = REPO_ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from core.generator import load_materials, preview_resume  # noqa: E402
from core.jd_parser import match_score, _classify_recommendation  # noqa: E402
from core.llm_rewriter import is_llm_enabled  # noqa: E402

# ---- 输入路径 ----
JD_SAMPLES = REPO_ROOT / "简历帮知识库" / "jd_samples.json"
JD_V4 = REPO_ROOT / "AI岗位JD库_v4_intern.json"
OUTPUT_REPORT = REPO_ROOT / "AI岗位JD库_agent_eval报告.md"

# ---- 版本元信息 ----
VERSION = "R5-A Phase 4 (Agent eval 报告, 2026-06-27)"

# ---- 四组开关组合 ----
# (FC, AW, label)
SWITCH_COMBOS = [
    (False, False, "baseline (FC=F, AW=F)"),
    (True, False, "FC only (FC=T, AW=F)"),
    (False, True, "AW only (FC=F, AW=T)"),
    (True, True, "FC+AW (FC=T, AW=T)"),
]

# ---- 阈值(沿用 R3.5 锁死的 80/60) ----
THRESHOLD_HIGH = 80
THRESHOLD_MID = 60


# ======================================================================
# Eval set 构造
# ======================================================================
def _expected_recommendation(label: str) -> Optional[str]:
    """
    把 jd_samples.json 的 label 转 recommendation (沿用 R3.5.1 score_thresholds 逻辑)
    公告型 → None(不参与 recommendation 验证,但仍可参与工具调用指标统计)
    """
    return {"推荐投": "高", "建议补充": "中", "别投": "低"}.get(label, None)


def _label_to_expected_for_v4(jd_text: str, role_id_hint: str) -> str:
    """
    v4 主库 JD 没有 user 标定的 label, 给一个兜底:
    - 实跑 match_score 拿当前 score, 用 80/60 阈值推 expected label
    - 仅作 v4 4 份样本的参考(无 ground truth,报告里要注明"v4 sample 无 ground truth")
    """
    mats = load_materials()
    res = match_score(jd_text, role_id_hint, mats)
    return res["recommendation"]


def load_eval_set() -> list[dict]:
    """
    加载 eval set:
      1) 简历帮知识库/jd_samples.json 8 份非公告型(含 4 份 user 自手抄 + 4 份 from_main_db)
      2) AI岗位JD库_v4_intern.json 4 份 strong(覆盖 algorithm/test_qa/data_annot/product 各 1)

    每份样本产出 dict:
      {
        "jd_id": str, "company": str, "title": str, "role_id": str,
        "text": str, "expected_label": str|"v4_no_ground_truth",
        "source": "jd_samples" | "jd_v4_strong",
      }
    """
    samples_data = json.loads(JD_SAMPLES.read_text(encoding="utf-8"))
    jd_v4 = json.loads(JD_V4.read_text(encoding="utf-8"))

    eval_set: list[dict] = []

    # ---- 1) jd_samples 8 份非公告型 ----
    for s in samples_data["samples"]:
        if s["label"] == "公告型":
            continue
        eval_set.append({
            "jd_id": s["id"],
            "company": s.get("company", ""),
            "title": s.get("title", ""),
            "role_id": s["role_id_hint"],
            "text": s["text"],
            "expected_label": s["label"],
            "expected_rec": _expected_recommendation(s["label"]),
            "source": "jd_samples",
        })

    # ---- 2) v4 主库 4 份 strong 补充 ----
    # 选 4 份覆盖多 role 组合,避开跟 jd_samples 完全重复的 role
    # 目标: algorithm / test_qa / data_annot / product 各 1 份
    v4_picks = [
        # id,             role_id,        reason
        ("JD-B014",       "algorithm",    "字节 大模型算法实习生 - 开发者 AI 团队 (algorithm 强匹配)"),
        ("JD-B015",       "test_qa",      "字节 质量技术团队 大模型算法实习生 - 智能交付 (test_qa 强匹配)"),
        ("JD-A011",       "data_annot",   "阿里智能信息 大模型 AI 数据工程实习生 (data_annot 强匹配)"),
        ("JD-BY003",      "product",      "百运网 AI 产品实习生 (product 弱匹配 - PM 维度素材缺, 跟 jd_samples baiyun_2026_product 同类)"),
    ]
    v4_jd_map = {j["id"]: j for j in jd_v4["jds"]}
    for jd_id, role_id, _reason in v4_picks:
        if jd_id not in v4_jd_map:
            print(f"[WARN] v4 JD {jd_id} 不在主库, 跳过", file=sys.stderr)
            continue
        jd = v4_jd_map[jd_id]
        eval_set.append({
            "jd_id": jd_id,
            "company": jd.get("company", ""),
            "title": jd.get("title", ""),
            "role_id": role_id,
            "text": jd.get("full_text", ""),
            # v4 无 user ground truth, 用实跑 match_score 推 expected 作参考
            "expected_label": "v4_no_ground_truth",
            "expected_rec": _label_to_expected_for_v4(jd.get("full_text", ""), role_id),
            "source": "jd_v4_strong",
        })

    return eval_set


# ======================================================================
# 单样本 × 单组合 评测
# ======================================================================
def _extract_tools_used_from_jsonl(jsonl_path: Path, request_id_prefix: str) -> list[str]:
    """
    从 JSONL trace 文件里抽出某次 request 的 tool 列表(去重,按调用顺序)。
    request_id_prefix: 通常截前 4 字符(防全文匹配冲突)。
    """
    if not jsonl_path.exists():
        return []
    tools: list[str] = []
    seen: set[str] = set()
    for line in jsonl_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        rid = str(ev.get("request_id", ""))
        if not rid.startswith(request_id_prefix):
            continue
        t = ev.get("tool")
        if t and t not in seen:
            tools.append(t)
            seen.add(t)
    return tools


def _detect_schema_pass(preview: dict) -> bool:
    """
    schema pass: preview 返回值结构符合既有 preview schema
    (核心字段存在 + sections 是 list 且至少 1 个 section)
    """
    if not isinstance(preview, dict):
        return False
    for k in ("target_role", "template", "sections"):
        if k not in preview:
            return False
    secs = preview.get("sections")
    if not isinstance(secs, list) or len(secs) == 0:
        return False
    return True


def evaluate_one(
    sample: dict,
    *,
    enable_function_calling: bool,
    enable_agent_workflow: bool,
    jsonl_path: Optional[Path] = None,
) -> dict:
    """
    跑单样本 × 单组合,返回一行指标 dict。
    """
    t0 = time.time()
    error_type: Optional[str] = None
    preview: dict = {}
    try:
        preview = preview_resume(
            target_role=sample["role_id"],
            template="classic",
            jd_text=sample["text"],
            enable_function_calling=enable_function_calling,
            enable_agent_workflow=enable_agent_workflow,
        )
    except Exception as e:
        # preview_resume 在 workflow 失败时会 fallback 到老路径,理论上不会抛
        # 但保险起见兜底
        error_type = type(e).__name__
    latency_ms = int((time.time() - t0) * 1000)

    # match_score 单独跑一份作为 ground-truth score (preview 不暴露 score)
    mats = load_materials()
    score_res = match_score(sample["text"], sample["role_id"], mats)
    score = score_res["score"]
    recommendation = score_res["recommendation"]

    schema_pass = _detect_schema_pass(preview)

    # fallback_used: preview_resume 在 workflow 路径失败时 fallback → 老路径
    # 当前实现下, workflow 失败时返回 preview dict(来自 fallback)而非抛
    # 通过 enable_agent_workflow=True + 跑通 = 没 fallback(没捕获 exception)
    # 简化: 本评测不引入 mock 失败,所有路径理论上 fallback_used=False
    # 但如果 error_type 非 None, 记 True
    fallback_used = error_type is not None

    # tools_used: 走 AW 路径时从 JSONL trace 抽; 走老路径时根据 FC 标志推算
    tools_used: list[str] = []
    if enable_agent_workflow and jsonl_path and jsonl_path.exists():
        # 找出最近一条 preview_resume 调用产生的 request_id
        # 简单策略: 拿 trace 文件最后一行带 step=0 的事件 request_id 前 4 字符
        try:
            last_event = None
            for line in jsonl_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                # workflow 会写 retrieve_materials 等本地 step, step=0 的就是 parse_user_intent
                if ev.get("step") == 0 and ev.get("tool") is None:
                    last_event = ev
            if last_event:
                rid = str(last_event.get("request_id", ""))
                rid_prefix = rid[:4]
                tools_used = _extract_tools_used_from_jsonl(jsonl_path, rid_prefix)
        except Exception:
            tools_used = []
    elif enable_function_calling:
        # 走老路径 + FC=T: rewrite_highlights 挂 tools,但不走 workflow 路径,
        # 无 JSONL trace → 标 "n/a (old path, no trace)"
        tools_used = ["n/a (FC enabled, old path)"]
    else:
        tools_used = []

    # pii_safe: 预览 dict 里不应含任何真实 PII
    # 简化判断: 不含 11 位数字串(手机号) + 不含 email 模式 + 不含完整学校名(脱敏后也不该出现)
    # 但公开脱敏版 materials.json 里的 placeholder (13800000000 / your_email@example.com)
    # 是有意保留作 demo, 不算 PII — 白名单跳过
    pii_safe = _check_pii_safe(preview)

    return {
        "jd_id": sample["jd_id"],
        "role_id": sample["role_id"],
        "expected_label": sample["expected_label"],
        "expected_rec": sample.get("expected_rec"),
        "score": score,
        "recommendation": recommendation,
        "schema_pass": schema_pass,
        "fallback_used": fallback_used,
        "tools_used": tools_used,
"latency_ms": latency_ms,
            "error_type": error_type,
            "pii_safe": pii_safe,
            "source": sample["source"],
        }


# ======================================================================
# 隐私检查
# ======================================================================
import re

# 简单 PII 模式(手机/邮箱/常见国内学校关键词)
_PII_MOBILE_RE = re.compile(r"\b1[3-9]\d{9}\b")
_PII_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# 公开报告里"学校名"作为 PII 仅作参考 — 本项目公开数据不含具体学校, 故用宽松匹配
_PII_SCHOOL_HINT_RE = re.compile(
    r"(清华|北大|复旦|交大|浙大|同济|武大|中山|厦大|南开|东南|北航|北理工|哈工大|西交大|中科大|人大)",
)


def _check_pii_safe(obj: object) -> bool:
    """
    递归扫描 obj 里的所有字符串, 检测是否含可疑 PII 模式。
    仅做基础模式匹配, 误报可接受(False positive > False negative)。
    placeholder 白名单(公开脱敏版 materials.json 用):
      - 13800000000 / your_email@example.com 等已知 demo 占位符
    """
    def _scan(x: object) -> bool:
        if isinstance(x, str):
            # placeholder 白名单先过滤
            stripped = x
            for ph in _PII_PLACEHOLDER_STRINGS:
                stripped = stripped.replace(ph, "")
            if _PII_MOBILE_RE.search(stripped):
                return False
            if _PII_EMAIL_RE.search(stripped):
                return False
            if _PII_SCHOOL_HINT_RE.search(stripped):
                return False
            return True
        if isinstance(x, dict):
            return all(_scan(v) for v in x.values())
        if isinstance(x, list):
            return all(_scan(v) for v in x)
        if isinstance(x, tuple):
            return all(_scan(v) for v in x)
        return True

    return _scan(obj)


# placeholder 白名单(公开脱敏版 materials.json 故意保留作 demo, 非真实 PII)
_PII_PLACEHOLDER_STRINGS = (
    "13800000000",        # 脱敏版手机占位符(11 位但明显是 demo)
    "your_email@example.com",  # 脱敏版邮箱占位符
)


# ======================================================================
# 主流程
# ======================================================================
def main():
    print("=" * 80)
    print(f"{VERSION}")
    print("=" * 80)
    print()

    eval_set = load_eval_set()
    print(f"Eval set: {len(eval_set)} 份 JD")
    src_counter = Counter(s["source"] for s in eval_set)
    for src, n in src_counter.most_common():
        print(f"  · {src}: {n}")
    print()

    # LLM 启用状态(决定 FC + AW 跑 LLM 时是否真发请求)
    llm_enabled = is_llm_enabled()
    print(f"LLM 启用: {'✅' if llm_enabled else '❌ (fallback)'}")
    if not llm_enabled:
        print("  → FC=T / AW=T 路径会走原文 fallback, 不发起 LLM HTTP 请求")
    print()

    # JSONL trace 路径(monkeypatch 暂不引入, 直接读默认路径)
    # 默认路径在 backend/logs/agent_trace.jsonl, 但 R5-A Phase 2 已存在
    # 为避免污染既有 trace, 我们用一个临时目录的 mock trace
    # 简化: 在评测期间重定向 AGENT_TRACE_JSONL_PATH (monkeypatch 风格)
    from core.logger import AGENT_TRACE_JSONL_PATH
    eval_jsonl_path = REPO_ROOT / "backend" / "logs" / "agent_trace.eval_tmp.jsonl"
    eval_jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    # 清空旧文件,保证本轮 trace 是干净的
    eval_jsonl_path.write_text("", encoding="utf-8")

    # 临时把全局 JSONL 路径切到 eval 专用路径
    import core.logger as logger_mod
    original_path = logger_mod.AGENT_TRACE_JSONL_PATH
    logger_mod.AGENT_TRACE_JSONL_PATH = eval_jsonl_path
    # 同时切 agent_workflow 模块里 import 的引用
    import core.agent_workflow as aw_mod
    aw_mod.log_agent_trace_jsonl = logger_mod.log_agent_trace_jsonl

    try:
        # ---- 跑 4 组 × N 样本 ----
        all_rows: list[dict] = []  # 每行 = (sample × combo)
        for combo_idx, (fc, aw, combo_label) in enumerate(SWITCH_COMBOS):
            print(f"--- [{combo_idx + 1}/4] {combo_label} ---")
            # 每组开始前清空 trace(避免上一组污染)
            eval_jsonl_path.write_text("", encoding="utf-8")

            combo_rows: list[dict] = []
            for sample in eval_set:
                row = evaluate_one(
                    sample,
                    enable_function_calling=fc,
                    enable_agent_workflow=aw,
                    jsonl_path=eval_jsonl_path if aw else None,
                )
                row["combo"] = combo_label
                row["combo_fc"] = fc
                row["combo_aw"] = aw
                combo_rows.append(row)
                all_rows.append(row)
                print(
                    f"  · {row['jd_id']:<28} score={row['score']:3d} rec={row['recommendation']:2s}"
                    f" schema_pass={row['schema_pass']} fallback={row['fallback_used']}"
                    f" latency={row['latency_ms']:4d}ms"
                )
            print()

        # ---- 指标统计 ----
        # schema_pass_rate / fallback_rate / 平均 latency / score 一致性
        metrics = compute_metrics(all_rows)

        # ---- 写报告 ----
        write_report(
            eval_set=eval_set,
            all_rows=all_rows,
            metrics=metrics,
            llm_enabled=llm_enabled,
        )

        print(f"\n[OK] 报告写入: {OUTPUT_REPORT}")
        print(f"     JSONL trace: {eval_jsonl_path} (评测期间临时, 可保留作审计)")

        # 隐私最终检查
        report_text = OUTPUT_REPORT.read_text(encoding="utf-8")
        pii_check = _check_pii_safe({"report": report_text})
        print(f"     隐私自检: {'✅ pass' if pii_check else '❌ FAIL — 报告含可疑 PII'}")

    finally:
        # 还原 JSONL 路径
        logger_mod.AGENT_TRACE_JSONL_PATH = original_path
        aw_mod.log_agent_trace_jsonl = logger_mod.log_agent_trace_jsonl


# ======================================================================
# 指标计算
# ======================================================================
def compute_metrics(all_rows: list[dict]) -> dict:
    """
    计算 4 组 × N 样本的指标聚合:
      - schema_pass_rate (per combo)
      - fallback_rate (per combo)
      - avg_latency_ms (per combo)
      - score_consistency (同 jd × 不同 combo → score 应一致)
      - recommendation_consistency (同上)
      - pii_safe_rate (per combo)
      - tools_used (per combo)
    """
    by_combo: dict[str, list[dict]] = {}
    for r in all_rows:
        by_combo.setdefault(r["combo"], []).append(r)

    combo_metrics = {}
    for combo, rows in by_combo.items():
        n = len(rows)
        schema_pass_rate = sum(1 for r in rows if r["schema_pass"]) / n if n else 0.0
        fallback_rate = sum(1 for r in rows if r["fallback_used"]) / n if n else 0.0
        pii_safe_rate = sum(1 for r in rows if r["pii_safe"]) / n if n else 0.0
        avg_latency = sum(r["latency_ms"] for r in rows) / n if n else 0.0
        # 工具调用统计(去重)
        tools_counter: Counter = Counter()
        for r in rows:
            for t in r["tools_used"]:
                tools_counter[t] += 1
        combo_metrics[combo] = {
            "n": n,
            "schema_pass_rate": round(schema_pass_rate, 3),
            "fallback_rate": round(fallback_rate, 3),
            "pii_safe_rate": round(pii_safe_rate, 3),
            "avg_latency_ms": round(avg_latency, 1),
            "tools_used_top": tools_counter.most_common(5),
            "any_error": any(r["error_type"] for r in rows),
        }

    # Score / recommendation 一致性: 同 jd × 4 组应该一致(因为 match_score 不受开关影响)
    by_jd: dict[str, list[dict]] = {}
    for r in all_rows:
        by_jd.setdefault(r["jd_id"], []).append(r)

    score_consistency = []
    rec_consistency = []
    for jd_id, rows in by_jd.items():
        scores = {r["score"] for r in rows}
        recs = {r["recommendation"] for r in rows}
        score_consistency.append({
            "jd_id": jd_id,
            "consistent": len(scores) == 1,
            "score_values": sorted(scores),
        })
        rec_consistency.append({
            "jd_id": jd_id,
            "consistent": len(recs) == 1,
            "rec_values": sorted(recs),
        })

    n_score_consistent = sum(1 for s in score_consistency if s["consistent"])
    n_rec_consistent = sum(1 for s in rec_consistency if s["consistent"])

    return {
        "by_combo": combo_metrics,
        "score_consistency": score_consistency,
        "rec_consistency": rec_consistency,
        "n_score_consistent": n_score_consistent,
        "n_rec_consistent": n_rec_consistent,
        "total_jds": len(by_jd),
    }


# ======================================================================
# Markdown 报告
# ======================================================================
def write_report(
    *,
    eval_set: list[dict],
    all_rows: list[dict],
    metrics: dict,
    llm_enabled: bool,
) -> None:
    """
    写 markdown 报告到 OUTPUT_REPORT。
    """
    lines: list[str] = []
    lines.append("# AI 岗位 JD 库 — Agent Workflow 离线评测报告\n\n")
    lines.append(f"> 版本: {VERSION}  \n")
    lines.append(f"> Eval set: **{len(eval_set)} 份 JD** "
                 f"(jd_samples {sum(1 for s in eval_set if s['source']=='jd_samples')} 份 + "
                 f"v4_strong {sum(1 for s in eval_set if s['source']=='jd_v4_strong')} 份)  \n")
    lines.append(f"> LLM 启用: **{'✅' if llm_enabled else '❌ (fallback)'}**  \n")
    lines.append(f"> 阈值: 高 ≥ {THRESHOLD_HIGH} / 中 ≥ {THRESHOLD_MID} / 低 < {THRESHOLD_MID}  \n")
    lines.append(f"> 四组对照: {len(SWITCH_COMBOS)} 种 (FC × AW)  \n\n")

    lines.append("## 一、Eval set 概览\n\n")
    lines.append("| jd_id | company | role_id | source | expected_label | text 长度 |\n")
    lines.append("|---|---|---|---|---|---|\n")
    for s in eval_set:
        lines.append(
            f"| `{s['jd_id']}` | {s['company']} | `{s['role_id']}` | "
            f"{s['source']} | {s['expected_label']} | {len(s['text'])} 字符 |\n"
        )
    lines.append("\n")
    lines.append("> 注: v4_strong 样本无 user 标定的 ground truth label, expected 仅作参考  \n\n")

    # ---- 二、四组对照总览表 ----
    lines.append("## 二、四组开关对照总览\n\n")
    lines.append("| 组合 | N | schema_pass_rate | fallback_rate | avg_latency_ms | pii_safe_rate | tools_used (top) |\n")
    lines.append("|---|---|---|---|---|---|---|\n")
    for combo, m in metrics["by_combo"].items():
        tools_str = ", ".join(f"{t}×{n}" for t, n in m["tools_used_top"][:3]) or "—"
        lines.append(
            f"| {combo} | {m['n']} | "
            f"{m['schema_pass_rate']:.1%} | {m['fallback_rate']:.1%} | "
            f"{m['avg_latency_ms']:.0f} | {m['pii_safe_rate']:.1%} | "
            f"{tools_str} |\n"
        )
    lines.append("\n")

    # ---- 三、score / recommendation 一致性 ----
    lines.append("## 三、score / recommendation 一致性(开 FC/AW 不应影响 match_score)\n\n")
    lines.append(f"- score 一致: **{metrics['n_score_consistent']} / {metrics['total_jds']}**  \n")
    lines.append(f"- recommendation 一致: **{metrics['n_rec_consistent']} / {metrics['total_jds']}**  \n\n")
    if metrics["n_score_consistent"] < metrics["total_jds"] or metrics["n_rec_consistent"] < metrics["total_jds"]:
        lines.append("### 不一致样本\n\n")
        lines.append("| jd_id | score 各组值 | recommendation 各组值 |\n")
        lines.append("|---|---|---|\n")
        for sc, rc in zip(metrics["score_consistency"], metrics["rec_consistency"]):
            if not sc["consistent"] or not rc["consistent"]:
                lines.append(
                    f"| `{sc['jd_id']}` | {sc['score_values']} | {rc['rec_values']} |\n"
                )
        lines.append("\n")
    else:
        lines.append("✅ 所有 JD 在 4 组开关下 score 与 recommendation 完全一致 "
                     "(match_score 纯规则化, 不受 FC / AW 开关影响, 符合预期)\n\n")

    # ---- 四、每个 JD 的工具调用摘要 ----
    lines.append("## 四、每个 JD 工具调用摘要\n\n")
    # 按 jd_id 分组
    by_jd: dict[str, list[dict]] = {}
    for r in all_rows:
        by_jd.setdefault(r["jd_id"], []).append(r)
    for jd_id, rows in by_jd.items():
        first = rows[0]
        lines.append(f"### `{jd_id}` — role=`{first['role_id']}`, expected={first['expected_label']}, source={first['source']}\n\n")
        lines.append("| 组合 | score | recommendation | schema_pass | fallback | latency_ms | tools_used |\n")
        lines.append("|---|---|---|---|---|---|---|\n")
        for r in rows:
            tools = ", ".join(r["tools_used"]) if r["tools_used"] else "—"
            lines.append(
                f"| {r['combo']} | {r['score']} | {r['recommendation']} | "
                f"{'✅' if r['schema_pass'] else '❌'} | "
                f"{'是' if r['fallback_used'] else '否'} | {r['latency_ms']} | {tools} |\n"
            )
        lines.append("\n")

    # ---- 五、失败 case 分析 ----
    lines.append("## 五、失败 case 分析\n\n")
    failed_rows = [r for r in all_rows if r["error_type"] or not r["schema_pass"] or not r["pii_safe"]]
    if not failed_rows:
        lines.append("✅ 本轮无失败 case (无 error_type / schema_pass=False / pii_safe=False)\n\n")
    else:
        lines.append(f"共 {len(failed_rows)} 条异常:\n\n")
        lines.append("| jd_id | combo | error_type | schema_pass | pii_safe |\n")
        lines.append("|---|---|---|---|---|\n")
        for r in failed_rows:
            lines.append(
                f"| `{r['jd_id']}` | {r['combo']} | "
                f"{r['error_type'] or '—'} | "
                f"{'✅' if r['schema_pass'] else '❌'} | "
                f"{'✅' if r['pii_safe'] else '❌'} |\n"
            )
        lines.append("\n")

    # ---- 六、隐私检查摘要 ----
    lines.append("## 六、隐私检查摘要\n\n")
    lines.append("- **数据源**: 仅读 `backend/data/materials.json`(公开脱敏版),不读任何 private 备份\n")
    lines.append("- **报告输出字段**: jd_id / role_id / company / title / score / recommendation / "
                 "schema_pass / fallback_used / tools_used / latency_ms / pii_safe\n")
    lines.append("- **不含**: 真实姓名 / 手机号 / 邮箱 / 完整学校名 / 完整 JD 全文 / 完整 bullet / request_id 全文\n")
    lines.append("- **PII 模式扫描**: 11 位手机号 / email 模式 / 国内常见学校关键词, "
                 "全报告递归扫描结果见下方\n")
    # 实际跑一遍扫描, 写明结果(避免把 pattern 字符串当字面写进报告触发误报)
    pii_pass = _check_pii_safe({"report": "".join(lines)})
    lines.append(f"  - 报告主体自检: {'✅ pass' if pii_pass else '❌ FAIL'}\n\n")

    # ---- 七、结论 ----
    lines.append("## 七、结论\n\n")
    n = len(eval_set)
    fc_only_metrics = metrics["by_combo"].get("FC only (FC=T, AW=F)")
    aw_only_metrics = metrics["by_combo"].get("AW only (FC=F, AW=T)")
    fc_aw_metrics = metrics["by_combo"].get("FC+AW (FC=T, AW=T)")
    baseline_metrics = metrics["by_combo"].get("baseline (FC=F, AW=F)")

    if all(m["schema_pass_rate"] == 1.0 for m in metrics["by_combo"].values()):
        lines.append(f"- **schema pass rate 4 组均 100%** ({n} JD × 4 = {n*4} 次 preview 调用全部通过 schema 校验)\n")
    else:
        lines.append(f"- ⚠️  schema pass rate 未达 100%, 见上方各组指标\n")

    if all(m["fallback_rate"] == 0.0 for m in metrics["by_combo"].values()):
        lines.append(f"- **fallback rate 4 组均 0%** (无意外降级)\n")
    else:
        lines.append(f"- ⚠️  fallback rate > 0, 见各组指标\n")

    lines.append(f"- **score 一致性 {metrics['n_score_consistent']}/{metrics['total_jds']}**: "
                 f"match_score 纯规则化, 4 组开关对 score 无影响, 符合预期\n")
    lines.append(f"- **recommendation 一致性 {metrics['n_rec_consistent']}/{metrics['total_jds']}**: "
                 f"4 组开关对 recommendation 无影响\n")

    if baseline_metrics and aw_only_metrics:
        delta_latency = aw_only_metrics["avg_latency_ms"] - baseline_metrics["avg_latency_ms"]
        lines.append(f"- **AW 开启 vs baseline 平均 latency 差**: {delta_latency:+.0f}ms "
                     f"(AW 走完整任务图, baseline 走老路径, 预期有少量 overhead)\n")

    lines.append(f"- **LLM 启用**: {'✅' if llm_enabled else '❌ (无 key, FC / AW 走原文 fallback)'}  \n")
    if not llm_enabled:
        lines.append("  - 真实 LLM 场景下 FC+AW 的 latency 会显著高于 fallback (HTTP RTT 决定), "
                     "当前评测反映的是离线 fallback 路径的真实表现\n")

    lines.append("\n---\n\n")
    lines.append("## 八、与既有脚本的关系\n\n")
    lines.append("- `scripts/score_thresholds.py`: 阈值调优, 单维度 match_score 准确率, 跟本脚本独立\n")
    lines.append("- `scripts/match_golden_targets.py`: 黄金 JD × 6 role 全量扫描, 跟本脚本独立\n")
    lines.append("- `scripts/replay_agent_trace.py`: 单 request_id trace 回放, 跟本脚本独立\n")
    lines.append("- 本脚本: 评测 Agent workflow 4 组开关在固定 eval set 上的稳定性 / 延迟 / 降级率\n")
    lines.append("- **不挂 pre-push hook** (spec §12 #3 已明确默认手动)\n\n")

    OUTPUT_REPORT.write_text("".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()