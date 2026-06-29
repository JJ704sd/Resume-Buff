#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
R5-E Phase 2: Prompt A/B 评测脚本

设计目标 (对齐 spec §3 Phase 2 + §4 报告格式 + §6 测试策略 + §7 风险与回退):
  - 复用 R5-D 评测脚本 (scripts/evaluate_agent_workflow.py) 的 helpers
  - 固定 enable_function_calling=True + enable_agent_workflow=True, 只改变 prompt_version
  - eval set 沿用 R5-D 的 12 JD (8 份 jd_samples 非公告型 + 4 份 v4_strong)
  - 默认 mode=offline (无 LLM key 也能跑, 走原文 fallback)
  - 报告只写聚合字段: schema_pass_rate / fallback_rate / avg_latency_ms /
    p95_latency_ms / max_latency_ms / avg_rewrite_changed_rate / avg_len_after /
    tier_required_hit_rate / pii_safe_rate + judge_*
  - 报告绝不写入 JD 原文 / bullet 原文 / 改写后 bullet 原文 / prompt 正文 /
    LLM response 原文 / API key (AGENTS.md 隐私边界)

CLI:
    D:\\python3.11\\python.exe scripts/evaluate_prompt_versions.py --mode offline
    D:\\python3.11\\python.exe scripts/evaluate_prompt_versions.py --mode live --runs-per-version 3
    D:\\python3.11\\python.exe scripts/evaluate_prompt_versions.py --versions v2-baseline,v3-priority

复用 helpers (从 evaluate_agent_workflow.py 导入, 避免逻辑分叉):
  - load_eval_set
  - _resolve_eval_mode
  - _get_llm_eval_config
  - _extract_project_highlights
  - _summarize_rewrite_impact
  - _percentile
  - _check_pii_safe
  - FALLBACK_* 常量

风险缓解 (对齐 spec §7):
  - 默认 mode=offline, 不会意外发 LLM HTTP
  - 候选版本未在 PROMPT_VERSIONS 注册 → ValueError, 评测不写入报告
  - judge 默认 off, 失败不阻断主报告
  - 不挂 pre-push hook (spec §12 #3 已明确默认手动)
  - 不修改 evaluate_agent_workflow.py / match_score / llm_rewriter
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

# ---- 路径: 把 backend/ 加到 sys.path 让 core.* 可导入 ----
REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = REPO_ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))

# ---- 复用 evaluate_agent_workflow.py 的 helpers ----
# 注: 显式 import 模块名避免符号冲突, 走 module path 调用
from evaluate_agent_workflow import (  # noqa: E402
    load_eval_set,
    _resolve_eval_mode,
    _get_llm_eval_config,
    _extract_project_highlights,
    _summarize_rewrite_impact,
    _percentile,
    _check_pii_safe,
    FALLBACK_NONE,
    FALLBACK_LLM_DISABLED,
    FALLBACK_TOOL_ERROR,
    FALLBACK_SCHEMA_RETRY,
    FALLBACK_WORKFLOW_ABORT,
    MODE_OFFLINE,
    MODE_LIVE,
    MODE_AUTO,
    VALID_EVAL_MODES,
)

from core.generator import preview_resume  # noqa: E402
from core.llm_rewriter import (  # noqa: E402
    is_llm_enabled,
    PROMPT_VERSIONS,
    DEFAULT_BASE_URL,
)

# ---- 输入路径 ----
OUTPUT_REPORT = REPO_ROOT / "AI岗位JD库_prompt_ab报告.md"

# ---- 版本元信息 ----
VERSION = "R5-E Phase 2 (Prompt A/B 评测脚本, 2026-06-29)"

# ---- 4 个 prompt version 的短描述 (不依赖 PROMPT_VERSIONS 内容, 避免 prompt 正文入脚本) ----
# 报告 "Prompt 版本总览" 章节只展示 key + 一句话定位, **绝不展示 prompt 正文**。
PROMPT_VERSION_DESCRIPTIONS: dict[str, str] = {
    "v2-baseline": "当前生产 prompt (R3-P 主体 + evidence 约束), 回归基线字节级锁死",
    "v3-priority": "优先级铁律版 (P0-P4 显式声明冲突优先级), 测结构化排序对 LLM 稳定性",
    "v4-counterexample": "反例强化版 (v3 + 4 条禁止事项), 压低 preamble / 顺序错位 / 跨 bullet 借事实",
    "v5-minimal": "极简版 (≈5 句话), 测短 prompt 是否比工程化长 prompt 更稳定",
}

DEFAULT_VERSIONS = list(PROMPT_VERSION_DESCRIPTIONS.keys())


# ======================================================================
# R5-E Phase 3: 可选 LLM-as-Judge helpers
# ======================================================================
# 设计目标(对齐 spec §3 Phase 3):
#   - --judge on 才发起 judge HTTP 调用; --judge off (默认) 完全不构造 judge payload
#   - judge 输入在内存里使用 bullet_before / bullet_after / evidence_summary / jd_focus
#   - judge 输出压缩为 3 字段: quality_score (1-5) / hallucination (0/1) / tier_required_hit (0/1)
#   - 任何失败 (网络 / JSON 解析 / schema 不合法 / 超时): 当前样本 judge 字段置空,
#     judge_error 标志 +1, 主脚本继续运行
#   - judge 不 retry, 避免 token 成本失控 (跟 llm_rewriter._call_with_retry 一致)
#   - 报告**不展示** reasoning / chain-of-thought / 原 bullet / 改写后 bullet / JD 原文

# Judge HTTP 调用默认超时(秒) — 比生成调用短, 因为 judge 是辅助信号不是主路径
_JUDGE_TIMEOUT_SEC = 15

# Judge 调用的 OpenAI-compatible URL — 跟 llm_rewriter 同源
_DEFAULT_JUDGE_BASE_URL = DEFAULT_BASE_URL

# Judge prompt — 简洁系统消息, 强制只输出 JSON, 不引导推理 (防止 reasoning 泄漏)
_JUDGE_SYSTEM_PROMPT = (
    "你是简历改写质量评分员。\n"
    "严格根据提供的证据判断, 只输出 JSON, 不要解释、不要 markdown、不要多余文本。\n"
    "输出 schema: {\"quality_score\": 1-5, \"hallucination\": 0 或 1, \"tier_required_hit\": 0 或 1}\n"
    "含义:\n"
    "- quality_score: 1=严重问题, 5=高质量 (综合事实真实 / JD 对齐 / 简洁 / 量化 / 中文表达)\n"
    "- hallucination: 1=出现原 bullet / evidence 都没有的具体事实, 0=无\n"
    "- tier_required_hit: 1=有事实支撑时覆盖了 tier_required 关键词, 0=否"
)


def _validate_judge_payload(parsed: object) -> Optional[dict]:
    """
    校验 judge 返回的 dict 是否符合 schema:
      - quality_score ∈ {1, 2, 3, 4, 5} (int)
      - hallucination ∈ {0, 1} (int)
      - tier_required_hit ∈ {0, 1} (int)

    返回:
      - dict 含 3 字段 (int) 当校验通过
      - None 当任一字段缺失 / 类型错 / 范围越界

    隐私边界: 只校验数字, 不接触任何原文字段 (reasoning / chain_of_thought 等都忽略)。
    """
    if not isinstance(parsed, dict):
        return None
    qs = parsed.get("quality_score")
    if not isinstance(qs, int) or isinstance(qs, bool) or qs not in (1, 2, 3, 4, 5):
        return None
    hall = parsed.get("hallucination")
    if not isinstance(hall, int) or isinstance(hall, bool) or hall not in (0, 1):
        return None
    trh = parsed.get("tier_required_hit")
    if not isinstance(trh, int) or isinstance(trh, bool) or trh not in (0, 1):
        return None
    return {
        "quality_score": qs,
        "hallucination": hall,
        "tier_required_hit": trh,
    }


def _build_judge_user_payload(
    *,
    bullet_before: list[str],
    bullet_after: list[str],
    evidence_summary: Optional[list[dict]],
    jd_focus: Optional[dict],
) -> dict:
    """
    构造 judge 调用的 user message payload (dict, 序列化后是 user 单条 JSON 字符串)。

    输入:
      - bullet_before:  原 highlights (list[str], 通常 1-10 条)
      - bullet_after:   改写后 highlights (list[str], 同长度或更短)
      - evidence_summary: R5-A Phase 3 evidence 列表 (list[dict] / None)
      - jd_focus:       关键词字典 (dict / None, 含 matched / missing / tier_required / tier_preferred)

    输出 dict (序列化后由 _call_judge 包成 user message):
      - 所有原文按"只统计长度 + 取前 N 字符预览"的方式压缩, 防止泄露到报告 (报告**不展示**
        此 payload, 但仍严格控制大小以防 judge prompt 被滥用)

    隐私: 此 payload 在内存里用, **不写** 报告 / 日志 / trace。
    """
    def _preview_list(items: list, max_items: int = 8, max_chars: int = 80) -> list[dict]:
        """list → 短预览 list (只保留 index / chars / 文本前 max_chars), 用于 judge payload。"""
        out: list[dict] = []
        for i, x in enumerate(items[:max_items]):
            if isinstance(x, str):
                out.append({"i": i, "preview": x[:max_chars]})
            elif isinstance(x, dict):
                # evidence dict: 保留 source_type / source_id / matched_keywords / text 预览
                snippet = {
                    "i": i,
                    "source_type": str(x.get("source_type", ""))[:20],
                    "source_id": str(x.get("source_id", ""))[:40],
                    "matched_keywords": list(x.get("matched_keywords", []) or [])[:6],
                    "preview": str(x.get("text", ""))[:max_chars],
                }
                out.append(snippet)
            else:
                out.append({"i": i, "preview": str(x)[:max_chars]})
        return out

    safe_jd_focus: dict = {
        "matched": [],
        "missing": [],
        "tier_required": [],
        "tier_preferred": [],
    }
    if isinstance(jd_focus, dict):
        for k in ("matched", "missing", "tier_required", "tier_preferred"):
            v = jd_focus.get(k)
            if isinstance(v, list):
                safe_jd_focus[k] = [str(x)[:40] for x in v[:10]]

    return {
        "before": _preview_list(bullet_before or []),
        "after": _preview_list(bullet_after or []),
        "evidence": _preview_list(evidence_summary or []),
        "jd_focus": safe_jd_focus,
        "instructions": (
            "对比 before / after, 只输出 JSON 评分, 不要解释。"
        ),
    }


def _call_judge(
    *,
    bullet_before: list[str],
    bullet_after: list[str],
    evidence_summary: Optional[list[dict]],
    jd_focus: Optional[dict],
    model: str,
    base_url: str,
    api_key: str,
    timeout_sec: int = _JUDGE_TIMEOUT_SEC,
) -> tuple[Optional[dict], bool]:
    """
    调一次 LLM judge, 返回 (metrics_dict_or_None, error_flag)。

    输出:
      - ({"quality_score": int, "hallucination": int, "tier_required_hit": int}, False) 成功
      - (None, True) 任何失败 (网络 / 超时 / JSON 解析 / schema 错 / 字段越界)

    不 retry — 跟 llm_rewriter._call_with_retry 一致, 避免 token 成本失控
    (spec §7 风险与回退: "judge 引入二次 LLM 成本和不稳定 → 默认 --judge off; 失败不阻断报告")。

    隐私边界:
      - 不写日志 / trace / 报告
      - 不读 env LLM_API_KEY 之外的环境变量
      - 失败时**绝不**在返回值里包含响应原文 (response body 只用于解析, 不外传)
    """
    url = base_url.rstrip("/") + "/chat/completions"
    user_payload = _build_judge_user_payload(
        bullet_before=bullet_before,
        bullet_after=bullet_after,
        evidence_summary=evidence_summary,
        jd_focus=jd_focus,
    )
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": _JUDGE_SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
        ],
        "temperature": 0.0,
    }
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        # 4xx / 5xx — judge 失败, 不重试
        return (None, True)
    except urllib.error.URLError:
        # 网络层错误 (DNS / 连接拒绝 / 超时) — judge 失败
        return (None, True)
    except TimeoutError:
        return (None, True)
    except Exception:
        # 任何其他异常 — judge 失败 (主脚本继续)
        return (None, True)

    # 解析响应 JSON
    try:
        resp_obj = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return (None, True)
    if not isinstance(resp_obj, dict):
        return (None, True)

    # 提取 OpenAI 风格 choices[0].message.content (优先) / 直传 (兼容)
    content_str: Optional[str] = None
    try:
        choices = resp_obj.get("choices") or []
        if isinstance(choices, list) and choices:
            msg = choices[0].get("message") or {}
            content = msg.get("content")
            if isinstance(content, str):
                content_str = content
    except Exception:
        content_str = None
    if content_str is None:
        return (None, True)

    # 解析 content 里的 JSON
    try:
        parsed = json.loads(content_str)
    except (json.JSONDecodeError, TypeError):
        return (None, True)

    # schema 校验
    return (_validate_judge_payload(parsed), parsed is not None and _validate_judge_payload(parsed) is None)


def _summarize_judge_metrics(rows: list[dict]) -> dict:
    """
    聚合 judge 指标 (从 rows 列表):
      - judge_quality_score_avg: float  (None / 缺字段 → 跳过)
      - hallucination_rate:      float  (hallucination==1 的占比, 只看有 judge 评分的样本)
      - tier_required_hit_rate:  float  (tier_required_hit==1 的占比, 同上)
      - judge_error_count:       int    (judge_error==True 的样本数)
      - judge_evaluated_count:   int    (任一 judge 字段非空且非 error 的样本数)

    返回 5 字段 dict (per spec §3 Phase 3 "报告只展示聚合指标")。
    """
    evaluated_count = 0
    quality_scores: list[int] = []
    hallucinations = 0
    tier_hits = 0
    error_count = 0
    for r in rows:
        if r.get("judge_error"):
            error_count += 1
            continue
        qs = r.get("judge_quality_score")
        hall = r.get("judge_hallucination")
        trh = r.get("judge_tier_required_hit")
        if (
            isinstance(qs, int)
            and isinstance(hall, int)
            and isinstance(trh, int)
        ):
            evaluated_count += 1
            quality_scores.append(qs)
            if hall == 1:
                hallucinations += 1
            if trh == 1:
                tier_hits += 1

    avg_qs = round(sum(quality_scores) / len(quality_scores), 2) if quality_scores else 0.0
    hallucination_rate = round(hallucinations / evaluated_count, 3) if evaluated_count else 0.0
    tier_required_hit_rate = round(tier_hits / evaluated_count, 3) if evaluated_count else 0.0

    return {
        "judge_quality_score_avg": avg_qs,
        "hallucination_rate": hallucination_rate,
        "tier_required_hit_rate": tier_required_hit_rate,
        "judge_error_count": error_count,
        "judge_evaluated_count": evaluated_count,
    }


# ======================================================================
# 单样本 × 单 version × 单 run 评测
# ======================================================================
def evaluate_one(
    sample: dict,
    *,
    prompt_version: str,
    run_index: int,
    baseline_highlights: Optional[list[str]] = None,
    judge_enabled: bool = False,
    judge_model: str = "",
    judge_api_key: str = "",
    judge_base_url: str = _DEFAULT_JUDGE_BASE_URL,
) -> dict:
    """
    跑单样本 × 单 prompt_version × 单 run, 返回一行指标 dict (不含原文)。

    返回 dict 字段 (全部数字 / 短枚举, 隐私安全):
      - prompt_version: str
      - jd_id: str
      - run_index: int
      - schema_pass: bool       — preview 顶层 schema 合法
      - fallback_used: bool
      - fallback_category: str  — FALLBACK_* 5 类之一
      - latency_ms: int
      - rewrite_changed_count: int
      - rewrite_total: int
      - rewrite_changed_rate: float
      - avg_len_before: float
      - avg_len_after: float
      - tier_required_hit_rate: float  — 0.0 当无 evidence (offline 默认)
      - pii_safe: bool
      - error_type: Optional[str]     — None 或异常类名 (如 "ValueError")
      - judge_quality_score: Optional[int]   — R5-E Phase 3 (1-5, judge=off 时 None)
      - judge_hallucination:  Optional[int]   — R5-E Phase 3 (0/1,    judge=off 时 None)
      - judge_tier_required_hit: Optional[int] — R5-E Phase 3 (0/1,    judge=off 时 None)
      - judge_error: bool                     — R5-E Phase 3 (judge 调用失败 True)

    隐私:
      - 不含 JD 原文 / bullet 原文 / 改写后 bullet 原文 / prompt 正文
      - 不含 request_id / agent_summary / 工具调用详情
      - error_type 仅记录异常类名, 不含异常 args (args 可能含 prompt_version 字符串)
      - judge 字段只存数字 (0/1/1-5), judge_reasoning 不存
    """
    t0 = time.time()
    error_type: Optional[str] = None
    preview: dict = {}
    try:
        preview = preview_resume(
            target_role=sample["role_id"],
            template="classic",
            jd_text=sample["text"],
            enable_function_calling=True,  # 固定 FC=T (spec §2.3)
            enable_agent_workflow=True,    # 固定 AW=T (spec §2.3)
            prompt_version=prompt_version,
        )
    except ValueError as e:
        # R5-E Phase 1: 未知 prompt_version 抛 ValueError (错误信息只含 key, 不含 prompt 正文)
        error_type = type(e).__name__
    except Exception as e:
        # 其他异常 (workflow abort / RuntimeError 等) — 兜底
        error_type = type(e).__name__
    latency_ms = int((time.time() - t0) * 1000)

    # schema 校验
    schema_pass = _is_schema_valid(preview)

    # fallback_used 主信号:
    #   - agent_summary.fallback_used (R5-C Phase 1)
    #   - 或 evaluate_one 抛异常
    summary = preview.get("agent_summary", {}) if isinstance(preview, dict) else {}
    summary_fallback = bool(summary.get("fallback_used", False)) if isinstance(summary, dict) else False
    fallback_used = summary_fallback or error_type is not None

    # fallback_category 分类 (复用 _classify_fallback_category 语义)
    fallback_category = _classify_fallback(
        preview=preview,
        llm_enabled=is_llm_enabled(),
        error_type=error_type,
    )

    # pii_safe: 递归扫描 preview 不含可疑 PII
    pii_safe = _check_pii_safe(preview)

    # rewrite impact (offline 路径下, before/after 都来自原文 → changed=0; live 走真实 LLM)
    after_highlights = _extract_project_highlights(preview)
    before_for_impact = baseline_highlights if baseline_highlights is not None else after_highlights
    impact = _summarize_rewrite_impact(before_for_impact, after_highlights)

    # tier_required_hit_rate: 当前 evidence RAG 暂无 tier_required 信号,
    # 用 0.0 占位 (offline 走原文, 不可计算); live 时由后续 R5-F embedding RAG 接入
    tier_required_hit_rate = 0.0

    # R5-E Phase 3: 可选 LLM-as-Judge
    # judge_enabled=False → 字段全部 None / False, 不发起任何 HTTP
    judge_quality_score: Optional[int] = None
    judge_hallucination: Optional[int] = None
    judge_tier_required_hit: Optional[int] = None
    judge_error = False

    if judge_enabled and judge_api_key and judge_model and after_highlights:
        # 取 evidence_summary (R5-A Phase 3) + 简易 jd_focus (仅供 judge 参考,
        # 本评测脚本暂无 jd_focus 完整字段, 用 preview 顶层 evidence_summary 替代)
        evidence_summary = preview.get("evidence_summary") if isinstance(preview, dict) else None
        # jd_focus: 当前 evaluate_one 没有 jd_focus 入参; 走空 dict (judge 仍可基于
        # evidence + bullet 评分, 仅 tier_required_hit 字段可能偏低)
        jd_focus = None
        metrics, judge_error = _call_judge(
            bullet_before=baseline_highlights or after_highlights,
            bullet_after=after_highlights,
            evidence_summary=evidence_summary if isinstance(evidence_summary, list) else None,
            jd_focus=jd_focus,
            model=judge_model,
            base_url=judge_base_url,
            api_key=judge_api_key,
        )
        if metrics:
            judge_quality_score = metrics["quality_score"]
            judge_hallucination = metrics["hallucination"]
            judge_tier_required_hit = metrics["tier_required_hit"]

    return {
        "prompt_version": prompt_version,
        "jd_id": sample["jd_id"],
        "run_index": run_index,
        "schema_pass": schema_pass,
        "fallback_used": fallback_used,
        "fallback_category": fallback_category,
        "latency_ms": latency_ms,
        "rewrite_changed_count": impact["rewrite_changed_count"],
        "rewrite_total": impact["rewrite_total"],
        "rewrite_changed_rate": impact["rewrite_changed_rate"],
        "avg_len_before": impact["avg_len_before"],
        "avg_len_after": impact["avg_len_after"],
        "tier_required_hit_rate": tier_required_hit_rate,
        "pii_safe": pii_safe,
        "error_type": error_type,
        # R5-E Phase 3: judge 字段 (None / False 时不入聚合指标)
        "judge_quality_score": judge_quality_score,
        "judge_hallucination": judge_hallucination,
        "judge_tier_required_hit": judge_tier_required_hit,
        "judge_error": judge_error,
        # 内部字段: main() 缓存 baseline 用, 入 all_rows 前 strip
        "_after_highlights": after_highlights,
    }


def _is_schema_valid(preview: object) -> bool:
    """
    prompt A/B 评测的 schema 校验 (跟 evaluate_agent_workflow 口径一致):
    - preview 是 dict
    - 含 target_role / template / sections
    - sections 是 list 且 ≥ 1
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


def _classify_fallback(
    *,
    preview: dict,
    llm_enabled: bool,
    error_type: Optional[str],
) -> str:
    """
    prompt A/B 评测的 fallback 分类 (跟 evaluate_agent_workflow._classify_fallback_category 口径一致):
      1. evaluate_one 抛异常 → workflow_abort_fallback
      2. agent_summary.fallback_used=True → 默认 tool_error_fallback (Phase 2 简化版,
         不读 fallback_reason — 跟主脚本行为对齐)
      3. LLM 关闭 + (FC=T 或 AW=T) → llm_disabled_fallback
      4. 否则 → none

    注: 本脚本固定 FC=T + AW=T, 所以 LLM 关闭时几乎总是 llm_disabled_fallback。
    """
    summary = preview.get("agent_summary", {}) if isinstance(preview, dict) else {}
    fallback_used = bool(summary.get("fallback_used", False)) if isinstance(summary, dict) else False

    if error_type is not None:
        return FALLBACK_WORKFLOW_ABORT
    if fallback_used:
        # Phase 2 简化: 不读 fallback_reason 细分, 统一归 tool_error
        return FALLBACK_TOOL_ERROR
    if not llm_enabled:
        return FALLBACK_LLM_DISABLED
    return FALLBACK_NONE


# ======================================================================
# 指标聚合
# ======================================================================
def compute_metrics(all_rows: list[dict]) -> dict:
    """
    按 prompt_version 聚合指标 (per spec §4 章节 3 + R5-E Phase 3 judge):

    每个 version 产 14 字段 (顺序固定, judge 字段在末尾):
      - N                        int   样本数 (jd × runs_per_version)
      - schema_pass_rate         float
      - fallback_rate            float
      - avg_latency_ms           float
      - p95_latency_ms           int
      - max_latency_ms           int
      - avg_rewrite_changed_rate float   (按 rewrite_total 加权)
      - avg_len_after            float   (按 rewrite_total 加权)
      - tier_required_hit_rate   float
      - pii_safe_rate            float
      - judge_quality_score_avg  float  (R5-E Phase 3: 仅 judge_evaluated_count>0 时非零)
      - hallucination_rate       float  (R5-E Phase 3)
      - tier_required_hit_rate_judge float  (R5-E Phase 3: 与上面同名但来自 judge,
                                            避免名字冲突用 _judge 后缀)
      - judge_error_count        int    (R5-E Phase 3: 本 version 内 judge 失败样本数)

    全局额外:
      - fallback_category_total: 5 类 fallback 分布
      - judge_total_errors:      int   全局 judge_error 计数
      - judge_total_evaluated:   int   全局 judge 成功评分样本数
    """
    by_version: dict[str, list[dict]] = {}
    for r in all_rows:
        by_version.setdefault(r["prompt_version"], []).append(r)

    version_metrics: dict[str, dict] = {}
    for version, rows in by_version.items():
        n = len(rows)
        schema_pass_rate = sum(1 for r in rows if r["schema_pass"]) / n if n else 0.0
        fallback_rate = sum(1 for r in rows if r["fallback_used"]) / n if n else 0.0
        pii_safe_rate = sum(1 for r in rows if r["pii_safe"]) / n if n else 0.0

        # latency 三件套
        latency_values = [int(r["latency_ms"]) for r in rows]
        avg_latency = sum(latency_values) / n if n else 0.0
        p95_latency = _percentile(latency_values, 95)
        max_latency = max(latency_values) if latency_values else 0

        # rewrite impact 按 rewrite_total 加权
        total_changed = sum(int(r.get("rewrite_changed_count", 0)) for r in rows)
        total_counted = sum(int(r.get("rewrite_total", 0)) for r in rows)
        avg_rewrite_changed_rate = (
            round(total_changed / total_counted, 3) if total_counted > 0 else 0.0
        )
        avg_len_after_agg = (
            round(
                sum(
                    float(r.get("avg_len_after", 0.0)) * int(r.get("rewrite_total", 0))
                    for r in rows
                ) / total_counted,
                1,
            ) if total_counted > 0 else 0.0
        )

        tier_required_hit_rate = (
            round(
                sum(float(r.get("tier_required_hit_rate", 0.0)) for r in rows) / n,
                3,
            ) if n else 0.0
        )

        # R5-E Phase 3: judge 聚合(per version)
        judge_agg = _summarize_judge_metrics(rows)

        version_metrics[version] = {
            "n": n,
            "schema_pass_rate": round(schema_pass_rate, 3),
            "fallback_rate": round(fallback_rate, 3),
            "pii_safe_rate": round(pii_safe_rate, 3),
            "avg_latency_ms": round(avg_latency, 1),
            "p95_latency_ms": p95_latency,
            "max_latency_ms": max_latency,
            "avg_rewrite_changed_rate": avg_rewrite_changed_rate,
            "avg_len_after": avg_len_after_agg,
            "tier_required_hit_rate": tier_required_hit_rate,
            "judge_quality_score_avg": judge_agg["judge_quality_score_avg"],
            "hallucination_rate": judge_agg["hallucination_rate"],
            "tier_required_hit_rate_judge": judge_agg["tier_required_hit_rate"],
            "judge_error_count": judge_agg["judge_error_count"],
            "judge_evaluated_count": judge_agg["judge_evaluated_count"],
        }

    # 全局 fallback_category 分布
    from collections import Counter
    fb_counter: Counter = Counter()
    for r in all_rows:
        fb_counter[r.get("fallback_category", FALLBACK_NONE)] += 1
    fb_total_full = {
        cat: fb_counter.get(cat, 0)
        for cat in (
            FALLBACK_NONE, FALLBACK_LLM_DISABLED, FALLBACK_TOOL_ERROR,
            FALLBACK_SCHEMA_RETRY, FALLBACK_WORKFLOW_ABORT,
        )
    }

    # R5-E Phase 3: 全局 judge 总数
    judge_global = _summarize_judge_metrics(all_rows)

    return {
        "by_version": version_metrics,
        "fallback_category_total": fb_total_full,
        "total_rows": len(all_rows),
        "judge_total_errors": judge_global["judge_error_count"],
        "judge_total_evaluated": judge_global["judge_evaluated_count"],
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
    requested_mode: str,
    resolved_mode: str,
    llm_eval_config: dict,
    versions: list[str],
    runs_per_version: int,
    judge_enabled: bool,
    judge_model: str,
    judge_requested: bool = False,
    output_path: Path,
) -> None:
    """
    写 markdown 报告 (per spec §4 章节 1-6 + R5-E Phase 3 judge 段):
      1. Eval 元信息
      2. Prompt 版本总览 (key + 短描述, 不展示 prompt 正文)
      3. By Version 指标表 (含 judge 列)
      4. By JD 摘要
      5. Judge 摘要 (R5-E Phase 3)
      6. Winner 建议
      7. 隐私检查
      8. 与既有脚本的关系

    judge_enabled vs judge_requested:
      - judge_requested: 用户实际传了 --judge on
      - judge_enabled:   实际生效的 judge (offline 模式下被强制 False)
      - 报告头部 judge 状态显示用 judge_requested (更准确反映用户意图)
      - Judge 数据列 (judge_qs_avg / hallucination_rate 等) 用 judge_enabled 决定是否展示数字

    隐私边界 (AGENTS.md + spec §7):
      - 报告绝不写 prompt 正文 / JD 原文 / bullet 原文 / 改写后 bullet 原文 /
        LLM response / API key / judge reasoning / chain-of-thought
      - 末尾做一次 PII scan 自检, 失败写明
    """
    lines: list[str] = []
    lines.append("# AI 岗位 JD 库 — Prompt A/B 评测报告\n\n")
    lines.append(f"> 版本: {VERSION}  \n")
    lines.append(f"> Eval set: **{len(eval_set)} 份 JD** (沿用 R5-D eval set)  \n")
    lines.append(f"> Eval mode: **{resolved_mode}** (requested: `{requested_mode}`)  \n")
    lines.append(f"> 评测配置: **enable_function_calling=True + enable_agent_workflow=True** (固定)  \n")
    lines.append(f"> Prompt versions: **{len(versions)} 个** — {', '.join(versions)}  \n")
    lines.append(f"> runs_per_version: **{runs_per_version}**  \n")
    judge_status = "on" if judge_enabled else "off"
    if judge_requested and not judge_enabled:
        # 用户传了 --judge on 但实际被 offline 模式强制 disabled
        judge_status = "off (offline mode forces judge disabled)"
    lines.append(
        f"> Judge: **{judge_status}** "
        f"(model: `{judge_model or '(disabled)'}`)  \n\n"
    )

    # ---- 0. LLM 元信息 ----
    lines.append("## 0、LLM 元信息 (沿用 R5-D Phase 2 格式)\n\n")
    lines.append("| 字段 | 值 |\n")
    lines.append("|---|---|\n")
    lines.append(f"| `llm_mode` | `{llm_eval_config.get('llm_mode', '')}` |\n")
    lines.append(f"| `llm_enabled` | `{llm_eval_config.get('llm_enabled', False)}` |\n")
    lines.append(f"| `llm_model` | `{llm_eval_config.get('llm_model', '')}` |\n")
    lines.append(f"| `llm_base_url_host` | `{llm_eval_config.get('llm_base_url_host', '')}` |\n")
    lines.append("\n")
    lines.append("> 隐私边界: 报告不含任何 API key 类凭据; base_url 只展示 host 部分。\n\n")

    # ---- 1. Prompt 版本总览 ----
    lines.append("## 1、Prompt 版本总览\n\n")
    lines.append("| key | 定位 | 长度 (字符) |\n")
    lines.append("|---|---|---|\n")
    for v in versions:
        desc = PROMPT_VERSION_DESCRIPTIONS.get(v, "(未在 PROMPT_VERSION_DESCRIPTIONS 注册)")
        # 长度只统计纯 prompt 正文, 不展示正文
        prompt_len = len(PROMPT_VERSIONS.get(v, ""))
        lines.append(f"| `{v}` | {desc} | {prompt_len} |\n")
    lines.append("\n")
    lines.append("> 注: 报告**不展示** prompt 正文, 长度仅作版本量级参考。\n\n")

    # ---- 2. By Version 指标表 (含 R5-E Phase 3 judge 列) ----
    lines.append("## 2、By Version 指标表\n\n")
    lines.append("| Version | N | schema_pass_rate | fallback_rate | avg_latency_ms | p95_latency_ms | max_latency_ms | avg_rewrite_changed_rate | avg_len_after | tier_required_hit_rate | pii_safe_rate | judge_qs_avg | hallucination_rate | tier_hit_rate(j) | judge_err |\n")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|\n")
    for v in versions:
        m = metrics["by_version"].get(v, {})
        if not m:
            continue
        # judge 字段可能为 0.0 (judge 关闭时) — 用 "—" 显式区分 0 评分
        judge_qs = m.get("judge_quality_score_avg", 0.0)
        halluc = m.get("hallucination_rate", 0.0)
        tier_hit_j = m.get("tier_required_hit_rate_judge", 0.0)
        judge_err = m.get("judge_error_count", 0)
        judge_eval = m.get("judge_evaluated_count", 0)
        # judge=off 时 judge_evaluated_count=0 → 显示 "—"
        # judge=on 但样本全失败时 judge_evaluated_count=0 → 也显示 "—"
        if judge_eval == 0 and judge_enabled:
            judge_qs_str = "—"
            halluc_str = "—"
            tier_hit_j_str = "—"
        elif judge_eval == 0:
            # judge off (默认)
            judge_qs_str = "—"
            halluc_str = "—"
            tier_hit_j_str = "—"
        else:
            judge_qs_str = f"{judge_qs:.2f}"
            halluc_str = f"{halluc:.1%}"
            tier_hit_j_str = f"{tier_hit_j:.1%}"
        lines.append(
            f"| `{v}` | {m['n']} | "
            f"{m['schema_pass_rate']:.1%} | {m['fallback_rate']:.1%} | "
            f"{m['avg_latency_ms']:.0f} | {m['p95_latency_ms']} | {m['max_latency_ms']} | "
            f"{m['avg_rewrite_changed_rate']:.1%} | {m['avg_len_after']:.1f} | "
            f"{m['tier_required_hit_rate']:.1%} | {m['pii_safe_rate']:.1%} | "
            f"{judge_qs_str} | {halluc_str} | {tier_hit_j_str} | {judge_err} |\n"
        )
    lines.append("\n")
    lines.append("> 注: `tier_required_hit_rate` 当前占位 0.0, 需 R5-F embedding RAG 接入 tier_required 评估  \n")
    lines.append(f"> 注: offline 模式 (LLM 未启用) 时 `avg_rewrite_changed_rate` 接近 0, 走原文 fallback  \n")
    lines.append("> 注: judge 列(`judge_qs_avg` / `hallucination_rate` / `tier_hit_rate(j)` / `judge_err`) "
                 "默认 `--judge off` 时显示 `—`; live + judge=on 才会有数字 (R5-E Phase 3)  \n\n")

    # ---- 3. By JD 摘要 ----
    lines.append("## 3、By JD 摘要\n\n")
    by_jd: dict[str, list[dict]] = {}
    for r in all_rows:
        by_jd.setdefault(r["jd_id"], []).append(r)
    lines.append(f"总样本: {len(eval_set)} JD × {len(versions)} versions × {runs_per_version} runs = **{metrics['total_rows']} 条记录**\n\n")
    lines.append("| jd_id | role | version | schema_pass | fallback_cat | latency_ms | rewrite_rate |\n")
    lines.append("|---|---|---|---|---|---|---|\n")
    for sample in eval_set:
        jd_id = sample["jd_id"]
        role = sample["role_id"]
        rows = by_jd.get(jd_id, [])
        for r in rows:
            rw_total = int(r.get("rewrite_total", 0))
            rw_changed = int(r.get("rewrite_changed_count", 0))
            rw_rate_str = (
                f"{rw_changed}/{rw_total} ({float(r.get('rewrite_changed_rate', 0)):.0%})"
                if rw_total > 0 else "—"
            )
            lines.append(
                f"| `{jd_id}` | `{role}` | `{r['prompt_version']}` | "
                f"{'✅' if r['schema_pass'] else '❌'} | "
                f"`{r['fallback_category']}` | {r['latency_ms']} | {rw_rate_str} |\n"
            )
    lines.append("\n")

    # ---- 4. fallback taxonomy 摘要 ----
    lines.append("## 4、fallback taxonomy 摘要\n\n")
    lines.append("| 类别 | 计数 |\n")
    lines.append("|---|---|\n")
    total_fb = metrics.get("fallback_category_total", {})
    for cat in (
        FALLBACK_NONE, FALLBACK_LLM_DISABLED, FALLBACK_TOOL_ERROR,
        FALLBACK_SCHEMA_RETRY, FALLBACK_WORKFLOW_ABORT,
    ):
        lines.append(f"| `{cat}` | {total_fb.get(cat, 0)} |\n")
    lines.append("\n")
    lines.append("> offline 模式: `llm_disabled_fallback` 应占大多数, 因 LLM 关闭时 FC/AW 走原文  \n")
    lines.append("> live 模式: `none` 占多数, `tool_error_fallback` / `schema_retry_fallback` 反映 prompt 稳定性差异  \n\n")

    # ---- 5. Judge 摘要 (R5-E Phase 3) ----
    lines.append("## 5、Judge 摘要 (R5-E Phase 3)\n\n")
    if not judge_enabled:
        lines.append("> Judge 默认关闭 (`--judge off`), 本节无数据。  \n")
        lines.append("> 手动跑 `--judge on` 时: live 模式 + LLM 已启用才会真正发起 judge HTTP 调用; "
                     "offline 模式 judge 强制 disabled (避免误发 HTTP)。  \n\n")
    elif resolved_mode == MODE_OFFLINE:
        lines.append("> Judge 用户传 `--judge on`, 但 offline 模式强制 judge disabled (避免误发 HTTP)。  \n")
        lines.append("> 全样本 `judge_quality_score` / `hallucination` / `tier_required_hit` 为空, "
                     "`judge_error_count` 不计入。  \n\n")
    else:
        # live + judge on: 展示全局 + per version 聚合
        judge_total_errors = metrics.get("judge_total_errors", 0)
        judge_total_evaluated = metrics.get("judge_total_evaluated", 0)
        lines.append(f"> 全局 judge 评估: **{judge_total_evaluated} 样本成功评分 / "
                     f"{judge_total_errors} 样本失败**  \n\n")
        lines.append("| Version | judge_evaluated | judge_quality_score_avg | hallucination_rate | tier_required_hit_rate | judge_error_count |\n")
        lines.append("|---|---|---|---|---|---|\n")
        for v in versions:
            m = metrics["by_version"].get(v, {})
            if not m:
                continue
            judge_eval = m.get("judge_evaluated_count", 0)
            judge_err = m.get("judge_error_count", 0)
            if judge_eval == 0:
                lines.append(
                    f"| `{v}` | 0 | — | — | — | {judge_err} |\n"
                )
            else:
                lines.append(
                    f"| `{v}` | {judge_eval} | "
                    f"{m.get('judge_quality_score_avg', 0.0):.2f} | "
                    f"{m.get('hallucination_rate', 0.0):.1%} | "
                    f"{m.get('tier_required_hit_rate_judge', 0.0):.1%} | "
                    f"{judge_err} |\n"
                )
        lines.append("\n")
        lines.append("> 注: `judge_quality_score_avg` ∈ [1, 5]; `hallucination_rate` ∈ [0, 1] (1 表示 judge 认为有幻觉); "
                     "`tier_required_hit_rate` ∈ [0, 1] (1 表示全部有事实支撑的 tier_required 都被覆盖)。  \n")
        lines.append("> 注: judge 失败 (网络 / JSON 解析 / schema 错误 / 超时) 不阻断主评测, "
                     "对应样本 3 个 judge 字段置空, `judge_error_count +1`。  \n\n")

    # ---- 6. Winner 建议 ----
    lines.append("## 6、Winner 建议\n\n")
    if resolved_mode == MODE_OFFLINE:
        lines.append("> offline 模式: 报告不产生 winner 建议 — "
                     "offline 路径下所有 prompt 走原文 fallback, 真实 prompt 差异需在 live 模式 + judge 开启时观察。  \n\n")
    elif not judge_enabled:
        lines.append("> judge 关闭: 报告不产生 winner 建议 — "
                     "R5-E Phase 3 默认 judge=off, 需手动 `--judge on` 才会调用 LLM judge。  \n\n")
    else:
        judge_total_evaluated = metrics.get("judge_total_evaluated", 0)
        if judge_total_evaluated == 0:
            lines.append("> live + judge=on 但 0 个样本成功评分 (judge 全部失败 / schema 拒绝), "
                         "数据不足, **insufficient live judge data**。  \n\n")
        else:
            # 简单 winner 逻辑: judge_quality_score_avg 最高 + hallucination_rate 最低
            ranked = []
            for v in versions:
                m = metrics["by_version"].get(v, {})
                qs = m.get("judge_quality_score_avg", 0.0)
                halluc = m.get("hallucination_rate", 0.0)
                eval_count = m.get("judge_evaluated_count", 0)
                if eval_count > 0:
                    # 综合分: qs 越高越好, hallucination 越低越好; 用 (qs - halluc*5) 当 score
                    composite = qs - halluc * 5.0
                    ranked.append((v, qs, halluc, m.get("tier_required_hit_rate_judge", 0.0), composite))
            if ranked:
                ranked.sort(key=lambda x: -x[4])  # composite desc
                top = ranked[0]
                lines.append(
                    f"> 综合 `judge_quality_score_avg` 与 `hallucination_rate`, 暂定 winner 为 **`{top[0]}`** "
                    f"(quality_score_avg={top[1]:.2f}, hallucination_rate={top[2]:.1%}, "
                    f"tier_required_hit_rate={top[3]:.1%})。  \n"
                )
                lines.append("> 完整排名:  \n")
                for rank, (v, qs, halluc, tier, _) in enumerate(ranked, 1):
                    lines.append(
                        f"> {rank}. `{v}` (qs_avg={qs:.2f}, hallucination_rate={halluc:.1%}, "
                        f"tier_hit_rate={tier:.1%})  \n"
                    )
                lines.append("> 注: winner 仅作数据参考, **R5-E Phase 3 不切换默认 prompt**。  \n\n")
            else:
                lines.append("> live + judge=on 但各 version 都没拿到有效评分, 数据不足, "
                             "**insufficient live judge data**。  \n\n")

    # ---- 7. 隐私检查 ----
    lines.append("## 7、隐私检查\n\n")
    lines.append("- **数据源**: 仅读 `backend/data/materials.json` (公开脱敏版), 不读 private 备份  \n")
    lines.append("- **报告输出字段**: prompt_version / jd_id / role_id / N / schema_pass_rate / "
                 "fallback_rate / latency_ms (avg / p95 / max) / rewrite_impact / pii_safe_rate / "
                 "fallback_category / judge_quality_score_avg / hallucination_rate / "
                 "tier_required_hit_rate(j) / judge_error_count (R5-E Phase 3)  \n")
    lines.append("- **不含**: 完整 prompt 正文 / JD 全文 / bullet 原文 / 改写后 bullet 原文 / "
                 "**LLM response 原文** / **API key** / **judge reasoning / chain-of-thought**  \n")
    lines.append("- **PII 模式扫描**: 11 位手机号 / email 模式 / 国内常见学校关键词, "
                 "全报告递归扫描结果见下方  \n")
    pii_pass = _check_pii_safe({"report": "".join(lines)})
    lines.append(f"  - 报告主体自检: {'✅ pass' if pii_pass else '❌ FAIL'}  \n\n")

    # ---- 8. 与既有脚本的关系 ----
    lines.append("## 8、与既有脚本的关系\n\n")
    lines.append("- `scripts/evaluate_agent_workflow.py`: 评测 FC × AW 4 组开关, 跟本脚本独立  \n")
    lines.append("- `scripts/replay_agent_trace.py`: 单 request_id trace 回放, 跟本脚本独立  \n")
    lines.append("- 本脚本: 评测同一 workflow (FC=T, AW=T) 下不同 prompt_version 的稳定性 / 延迟 / 降级率  \n")
    lines.append("- **不挂 pre-push hook** (spec §12 #3 已明确默认手动脚本)  \n")
    lines.append("- **不修改** `evaluate_agent_workflow.py` / `match_score` / `llm_rewriter` / `agent_workflow`  \n\n")

    output_path.write_text("".join(lines), encoding="utf-8")


# ======================================================================
# 主流程
# ======================================================================
def main(argv=None):
    """
    主流程:
      1. argparse CLI
      2. mode 决策 (复用 _resolve_eval_mode)
      3. 加载 eval set (复用 load_eval_set)
      4. 校验 versions 子集
      5. 跑 (version × jd × run_index) evaluate_one
      6. compute_metrics
      7. write_report

    Args:
        argv: 命令行参数 list。None → 走空 list (便于测试 main() 直接调)。

    Exit code:
        0 — 正常
        2 — mode 非法 / live mode LLM 未启用 / version 非法
    """
    parser = argparse.ArgumentParser(
        prog="evaluate_prompt_versions.py",
        description="R5-E Phase 2: Prompt A/B 评测脚本 (固定 FC=T + AW=T, 只改变 prompt_version)",
    )
    parser.add_argument(
        "--mode",
        choices=list(VALID_EVAL_MODES),
        default=MODE_OFFLINE,
        help="Eval mode: offline (默认, 不依赖真实 LLM) / "
             "live (必须 LLM 已启用) / auto (有 key 用 live, 无 key 用 offline)",
    )
    parser.add_argument(
        "--versions",
        type=str,
        default=",".join(DEFAULT_VERSIONS),
        help=f"逗号分隔 prompt version (默认: 全部 4 个 — {','.join(DEFAULT_VERSIONS)})",
    )
    parser.add_argument(
        "--runs-per-version",
        type=int,
        default=1,
        help="每个 version 每个 JD 的重复次数 (默认 1, live 抽样可手动调到 3)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="报告输出路径 (默认: AI岗位JD库_prompt_ab报告.md)",
    )
    parser.add_argument(
        "--judge",
        choices=["off", "on"],
        default="off",
        help="是否调用 LLM judge 评分 (默认 off, R5-E Phase 3). "
             "offline 模式下 judge 强制 disabled (即使用户传 --judge on 也不发 HTTP)。",
    )
    parser.add_argument(
        "--judge-model",
        type=str,
        default=None,
        help="Judge model (env LLM_JUDGE_MODEL 优先, 否则 LLM_MODEL, 默认同 LLM_MODEL)。",
    )

    args = parser.parse_args(argv if argv is not None else [])

    # ---- 输出路径覆盖 ----
    output_path = Path(args.output) if args.output else OUTPUT_REPORT

    # ---- 解析 versions 子集 ----
    versions = [v.strip() for v in args.versions.split(",") if v.strip()]
    if not versions:
        print("[ERROR] --versions 不能为空", file=sys.stderr)
        sys.exit(2)
    unknown_versions = [v for v in versions if v not in PROMPT_VERSIONS]
    if unknown_versions:
        # 错误信息只含 key, 不含 PROMPT_VERSIONS 任何 prompt 正文
        print(
            f"[ERROR] 未知 prompt version: {unknown_versions}; "
            f"合法: {list(PROMPT_VERSIONS.keys())}",
            file=sys.stderr,
        )
        sys.exit(2)

    # ---- runs_per_version 校验 ----
    if args.runs_per_version < 1:
        print("[ERROR] --runs-per-version 必须 ≥ 1", file=sys.stderr)
        sys.exit(2)

    # ---- mode 决策 ----
    llm_enabled = is_llm_enabled()
    try:
        resolved_mode = _resolve_eval_mode(args.mode, llm_enabled)
    except (ValueError, RuntimeError) as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(2)

    # ---- judge 配置 ----
    # R5-E Phase 3 强制规则: offline 模式下 judge 强制 disabled (即使 --judge on)
    # 避免 offline 跑评测时误发 judge HTTP (用户明确要求 "offline 模式下 judge
    # 默认 disabled 或不产生真实 HTTP 调用")
    judge_requested = (args.judge == "on")
    judge_force_off = (resolved_mode == MODE_OFFLINE)
    judge_enabled = judge_requested and not judge_force_off
    if judge_requested:
        judge_model = (
            args.judge_model
            or os.environ.get("LLM_JUDGE_MODEL", "").strip()
            or os.environ.get("LLM_MODEL", "").strip()
        )
    else:
        judge_model = args.judge_model or ""

    # judge api_key / base_url: 仅 live + judge=on 时生效, evaluate_one 内
    # 也会判断 judge_api_key 是否非空, 避免空 key 时发起 HTTP
    judge_api_key = ""
    judge_base_url = _DEFAULT_JUDGE_BASE_URL
    if judge_enabled:
        # live 模式: 从 env 读 (跟 llm_rewriter._call_with_retry 同源)
        judge_api_key = os.environ.get("LLM_API_KEY", "").strip()
        # base_url 走 llm_rewriter 的 DEFAULT + env LLM_BASE_URL(若有)
        custom_base_url = os.environ.get("LLM_BASE_URL", "").strip()
        if custom_base_url:
            judge_base_url = custom_base_url

    # ---- 跑评测 ----
    print("=" * 80)
    print(f"{VERSION}")
    print(f"Mode: {args.mode} → resolved={resolved_mode} (llm_enabled={llm_enabled})")
    print(f"Versions: {versions}")
    print(f"runs_per_version: {args.runs_per_version}")
    judge_status_str = (
        "on" if judge_enabled
        else ("off (forced by offline mode)" if judge_requested else "off")
    )
    print(f"Judge: {judge_status_str} (model: {judge_model or '(n/a)'})")
    print(f"Output: {output_path}")
    print("=" * 80)
    print()

    eval_set = load_eval_set()
    print(f"Eval set: {len(eval_set)} 份 JD (沿用 R5-D)")
    print()

    # ---- 临时切 JSONL trace 路径, 跟 evaluate_agent_workflow.py 同样的模式 ----
    # (避免污染既有 agent_trace.jsonl)
    from core.logger import AGENT_TRACE_JSONL_PATH
    eval_jsonl_path = REPO_ROOT / "backend" / "logs" / "agent_trace.prompt_eval_tmp.jsonl"
    eval_jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    eval_jsonl_path.write_text("", encoding="utf-8")
    import core.logger as logger_mod
    original_path = logger_mod.AGENT_TRACE_JSONL_PATH
    logger_mod.AGENT_TRACE_JSONL_PATH = eval_jsonl_path
    import core.agent_workflow as aw_mod
    aw_mod.log_agent_trace_jsonl = logger_mod.log_agent_trace_jsonl

    all_rows: list[dict] = []
    baseline_highlights_by_jd: dict[str, list[str]] = {}

    try:
        for v in versions:
            print(f"--- Version: `{v}` ---")
            # 每 version 开始前清空 trace
            eval_jsonl_path.write_text("", encoding="utf-8")

            for sample in eval_set:
                for run_idx in range(args.runs_per_version):
                    cached_baseline = baseline_highlights_by_jd.get(sample["jd_id"])
                    row = evaluate_one(
                        sample,
                        prompt_version=v,
                        run_index=run_idx,
                        baseline_highlights=cached_baseline,
                        judge_enabled=judge_enabled,
                        judge_model=judge_model,
                        judge_api_key=judge_api_key,
                        judge_base_url=judge_base_url,
                    )
                    # v2-baseline 是 baseline, 缓存其 after_highlights 作后续 version 的 before
                    if v == "v2-baseline" and run_idx == 0:
                        baseline_highlights_by_jd[sample["jd_id"]] = row.get("_after_highlights", [])
                    row.pop("_after_highlights", None)

                    all_rows.append(row)
                    judge_marker = (
                        f" judge_qs={row['judge_quality_score']}"
                        if row.get("judge_quality_score") is not None
                        else (" judge_err" if row.get("judge_error") else "")
                    )
                    print(
                        f"  · {row['jd_id']:<28} run={run_idx} "
                        f"schema_pass={'✅' if row['schema_pass'] else '❌'} "
                        f"fallback_cat={row['fallback_category']:<24} "
                        f"rewrite_rate={row['rewrite_changed_rate']:.0%} "
                        f"latency={row['latency_ms']:4d}ms{judge_marker}"
                    )
            print()

        # ---- 指标 ----
        metrics = compute_metrics(all_rows)

        # ---- LLM 元信息 ----
        llm_eval_config = _get_llm_eval_config(llm_enabled, resolved_mode)

        # ---- 写报告 ----
        # judge_enabled 是"实际生效"标志 (offline 时被强制为 False)
        write_report(
            eval_set=eval_set,
            all_rows=all_rows,
            metrics=metrics,
            llm_enabled=llm_enabled,
            requested_mode=args.mode,
            resolved_mode=resolved_mode,
            llm_eval_config=llm_eval_config,
            versions=versions,
            runs_per_version=args.runs_per_version,
            judge_enabled=judge_enabled,
            judge_model=judge_model,
            judge_requested=judge_requested,
            output_path=output_path,
        )

        print(f"\n[OK] 报告写入: {output_path}")
        print(f"     JSONL trace (评测期间临时): {eval_jsonl_path} (可保留作审计)")

        # 隐私最终检查
        report_text = output_path.read_text(encoding="utf-8")
        pii_check = _check_pii_safe({"report": report_text})
        print(f"     隐私自检: {'✅ pass' if pii_check else '❌ FAIL — 报告含可疑 PII'}")

    finally:
        # 还原 JSONL 路径
        logger_mod.AGENT_TRACE_JSONL_PATH = original_path
        aw_mod.log_agent_trace_jsonl = logger_mod.log_agent_trace_jsonl


if __name__ == "__main__":
    main(sys.argv[1:])
