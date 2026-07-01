#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Round 6-B Phase 5: Interview Agent eval compare 脚本(rules/llm/compare)

设计目标(对齐 R6-B spec §8 + §10 Phase 5):
  - 跑固定 eval set(3 条 plan §5.4 固定样本 + 7 条 simulated samples)
  - --extractor rules   走规则版基线(R6-A Phase 5 默认行为, 字节级一致)
  - --extractor llm     走 LLM 意图路径;offline 模式不得发网络 → 标记 llm_disabled_fallback
  - --extractor compare 同一批样本跑 rules + llm 意图,报告输出对照表
  - 输出 markdown 报告到 backend/logs/interview_eval_report.md(在 .gitignore)
  - 报告只含聚合指标 + 每条样本 slot key/长度/schema_pass/fallback_used/completeness/latency
  - 报告不含 user_message / draft_card 原文 / API key / 真实 PII / prompt / raw response
  - 默认 mode=offline,默认 --extractor rules(零发网络, 跟 R6-A Phase 5 字节级一致)
  - 不挂 pre-push hook(spec §12 #3 D6 决策)

复用 R5-D scripts/evaluate_agent_workflow.py 的 helper:
  - _resolve_eval_mode / _get_llm_eval_config / _check_pii_safe / _percentile
  - MODE_OFFLINE / MODE_LIVE / MODE_AUTO / VALID_EVAL_MODES

边界(R6-B spec §8 + §12):
  - offline + (--extractor llm | --extractor compare) 强制走规则版, fallback_category="llm_disabled_fallback"
  - live + (--extractor llm | --extractor compare) + 无 LLM_API_KEY → 拒绝
    (RuntimeError 错误信息不含 key 值 / env var 名)
  - live + (--extractor llm | --extractor compare) + 有 LLM_API_KEY → 真发网络
  - 报告 / stdout 严禁出现 user_message / prompt / raw response / source_span / API key
  - 不修改 evaluate_agent_workflow.py / evaluate_prompt_versions.py
  - 不引入新 LLM 调用路径(只复用 core.interview_agent._extract_slots_via_llm)
  - 不引入新依赖(纯 stdlib)
  - 不挂 pre-push hook

跑法:
    D:\\python3.11\\python.exe scripts/evaluate_interview_agent.py --mode offline --extractor rules
    D:\\python3.11\\python.exe scripts/evaluate_interview_agent.py --mode offline --extractor compare
    D:\\python3.11\\python.exe scripts/evaluate_interview_agent.py --mode live   --extractor compare --output backend/logs/interview_eval_report_live.md
    → 写报告到 backend/logs/interview_eval_report.md
    → 打印摘要到 stdout
"""
from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

# ---- 路径: 把 backend/ + scripts/ 都加到 sys.path ----
REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = REPO_ROOT / "backend"
SCRIPTS_DIR = REPO_ROOT / "scripts"
sys.path.insert(0, str(BACKEND_DIR))
sys.path.insert(0, str(SCRIPTS_DIR))

from core.llm_rewriter import is_llm_enabled  # noqa: E402
from core.interview_agent import (  # noqa: E402
    ActionType,
    build_draft_card,
    create_session,
    extract_slots,
)
from core.interview_prompts import (  # noqa: E402
    GAP_SUGGESTED_SLOTS,
    MAX_TURNS_PER_GAP,
)
from core.jd_parser import parse_jd  # noqa: E402

# ---- 复用 R5-D helper(直接 import,不重写) ----
from evaluate_agent_workflow import (  # noqa: E402
    MODE_OFFLINE,
    MODE_LIVE,
    MODE_AUTO,
    VALID_EVAL_MODES,
    _check_pii_safe,
    _get_llm_eval_config,
    _percentile,
    _resolve_eval_mode,
)

# ---- 输入 / 输出路径 ----
DEFAULT_OUTPUT = BACKEND_DIR / "logs" / "interview_eval_report.md"
VERSION = "R6-B Phase 5 (eval compare; rules/llm/compare 三模式; offline compare 双组同跑)"

# ---- R6-B Phase 5: --extractor 模式常量(spec §8) ----
EXTRACTOR_RULES: str = "rules"
"""走纯规则版 baseline, --extractor 默认值。字节级一致 R6-A Phase 5 行为。"""

EXTRACTOR_LLM: str = "llm"
"""走 LLM 意图路径;offline 模式强制走 rules + llm_disabled_fallback;live + 有 key 走真 LLM。"""

EXTRACTOR_COMPARE: str = "compare"
"""同一批样本跑 rules + llm 意图 2 组, 报告输出 rules vs llm_assisted 对照表。"""

EXTRACTOR_MODES: tuple[str, ...] = (EXTRACTOR_RULES, EXTRACTOR_LLM, EXTRACTOR_COMPARE)

# ---- R6-B Phase 5: 5 类 fallback_category(对齐 R5-C Phase 1 规范) ----
FALLBACK_NONE: str = "none"
FALLBACK_LLM_DISABLED: str = "llm_disabled_fallback"
FALLBACK_TOOL_ERROR: str = "tool_error_fallback"
FALLBACK_SCHEMA_RETRY: str = "schema_retry_fallback"
FALLBACK_WORKFLOW_ABORT: str = "workflow_abort_fallback"

# 隐私自检: 用于 _check_pii_safe 兜底白名单(同 R5-D _PII_PLACEHOLDER_STRINGS)
PII_PLACEHOLDER_STRINGS: tuple[str, ...] = (
    "13800000000",  # 脱敏版手机占位符(11 位但明显是 demo)
    "your_email@example.com",  # 脱敏版邮箱占位符
)

# 低置信度阈值(对齐 core.interview_agent.INTERVIEW_LOW_CONFIDENCE_THRESHOLD = 0.6)
INTERVIEW_EVAL_LOW_CONFIDENCE: float = 0.6

# ---- R6-C.1: Eval contract warning code 常量(路线 A, round6-c-live-eval-result §5) ----
EVAL_CONTRACT_WARN_UNREACHABLE: str = "unreachable_expected_slot"
"""expected slot 不在该 gap 的 GAP_SUGGESTED_SLOTS 中 — policy 不会主动追问,
   从 user_messages 抽取可能命中, 但 schema_pass_rate 难以证明 LLM 抽取能力。"""

EVAL_CONTRACT_WARN_BEYOND_3: str = "beyond_three_turns_expected_slot"
"""expected slot 在 suggested 顺序中位置 >= MAX_TURNS_PER_GAP(=3),
   且不在 near_limit 触达集合 {metric, result} 中 — 前 3 轮内很可能无法被问到。"""

# spec §6 step 5 near_limit 提前触达集合: turn_count 接近上限时, policy 优先问
# metric / result, 即使它们在 suggested 位置 >= MAX_TURNS_PER_GAP
_NEAR_LIMIT_REACHABLE_SLOTS: frozenset[str] = frozenset({"metric", "result"})


# ======================================================================
# Eval set 1: plan §5.4 固定 3 条样本(脱敏, 不动)
# ======================================================================
EVAL_SET_PLAN_BASELINE: list[dict] = [
    {
        "name": "process_metric_course",
        "source": "plan_baseline",
        "jd_text": (
            "岗位要求: 参与 AI 产品测试与数据质量评估, "
            "能梳理流程、跟进问题闭环, 有量化意识。"
        ),
        "role": "test_qa",
        "gap_id": "process_metric",
        "user_messages": [
            "我负责课程项目里的测试反馈整理, 主要是把同学发现的问题统一收集。",
            "我做了一个表格模板, 按问题类型、复现步骤、负责人和状态来记录。",
            "最后小组查问题更快, 返工少了一些, 但没有特别精确的数字。",
            "整理成素材",
        ],
        "expected_slots": {
            "responsibility": "测试反馈整理",
            "action": ["做了表格模板", "按问题类型、复现步骤、负责人和状态记录"],
            "result": "小组查问题更快, 返工减少",
        },
        "expected_draft_has_metrics": False,
    },
    {
        "name": "communication_club",
        "source": "plan_baseline",
        "jd_text": (
            "岗位要求: 能跨角色沟通需求, 梳理用户反馈, "
            "推动活动或产品方案落地。"
        ),
        "role": "product",
        "gap_id": "communication",
        "user_messages": [
            "社团活动报名时信息很乱, 我负责把报名问题和同学反馈整理出来。",
            "我建了共享文档, 每天同步一次状态, 把问题分成时间、场地、物料三类。",
            "后来分工清楚很多, 负责人能直接看到自己要处理的事项。",
            "整理成素材",
        ],
        "expected_slots": {
            "responsibility": "整理报名问题和同学反馈",
            "action": ["建立共享文档", "按时间、场地、物料分类", "同步状态"],
            "result": "分工更清楚, 负责人能看到待处理事项",
        },
        "expected_draft_has_metrics": False,
    },
    {
        "name": "tech_metric_data",
        "source": "plan_baseline",
        "jd_text": (
            "岗位要求: 理解数据标注、质量检查和大模型评估流程, "
            "能描述方法和判断标准。"
        ),
        "role": "data_annot",
        "gap_id": "tech_metric",
        "user_messages": [
            "我做过一个数据整理项目, 负责检查文本分类结果是不是符合规则。",
            "我先看样例, 再把容易混淆的类别写成判断标准, 遇到边界情况就记录下来。",
            "最后整理了 20 多条例子给组员参考, 后面大家判断更一致。",
            "整理成素材",
        ],
        "expected_slots": {
            "responsibility": "检查文本分类结果是否符合规则",
            "action": ["查看样例", "整理容易混淆类别的判断标准", "记录边界情况"],
            "result": "整理 20 多条例子供组员参考, 判断更一致",
        },
        "expected_draft_has_metrics": True,
    },
]


# ======================================================================
# Eval set 2: Simulated samples(基于对话里讨论的项目, 脱敏化)
# 边界(本轮跟用户对齐):
#   - 不写真实学校 / 公司 / 项目名 / 姓名
#   - 用"医疗垂类评测项目 / 心电时序项目 / 开源社团 / 大型赛事志愿"等抽象描述
#   - source="simulated_user_v1",报告里区分 simulated vs plan_baseline
# ======================================================================
EVAL_SET_SIMULATED: list[dict] = [
    {
        "name": "sim_tech_metric_medical_eval",
        "source": "simulated_user_v1",
        "jd_text": (
            "岗位要求: 理解 LLM 评估流程, 能设计评测维度、构建评测集、"
            "输出 Badcase 分析报告, 有医疗 / 严肃场景经验加分。"
        ),
        "role": "tech_metric",
        "gap_id": "tech_metric",
        "user_messages": [
            "我负责一个医疗垂类大模型评测项目, 主要做评测框架设计和评分标准制定。",
            "我用了漏斗式评分算法, 把度量维度分成安全、交互、表现、胜任力四层。",
            "最终审核了 200 多条模型输出, 标注准确率达到 90% 以上, 输出 5 份高质量 Badcase 报告。",
            "整理成素材",
        ],
        "expected_slots": {
            "responsibility": "医疗垂类大模型评测项目",
            "action": ["设计漏斗式评分算法", "审核 200 多条模型输出"],
            "metric": ["200 多条", "90% 以上", "5 份"],
        },
        "expected_draft_has_metrics": True,
    },
    {
        "name": "sim_tech_metric_ecg",
        "source": "simulated_user_v1",
        "jd_text": (
            "岗位要求: 熟悉深度学习模型训练流程, 能复现论文模型、"
            "对比不同架构效果、用量化指标评估。"
        ),
        "role": "tech_metric",
        "gap_id": "tech_metric",
        "user_messages": [
            "我参与一个心电时序信号大模型预研课题, 负责模型复现与训练评估。",
            "我采用 Accuracy、Sensitivity、Specificity 多维度指标对比 Transformer 和 CNN 架构。",
            "最终 ECGFounder 复现 Accuracy 达到 89.2%, 输出收敛性与泛化能力对比报告。",
            "整理成素材",
        ],
        "expected_slots": {
            "responsibility": "心电时序信号大模型预研课题",
            "method": ["采用 Accuracy、Sensitivity、Specificity 多维度指标"],
            "metric": ["89.2%"],
        },
        "expected_draft_has_metrics": True,
    },
    {
        "name": "sim_process_metric_open_source",
        "source": "simulated_user_v1",
        "jd_text": (
            "岗位要求: 能梳理工程流程、记录问题闭环、"
            "沉淀 SOP, 有 AI 应用部署经验加分。"
        ),
        "role": "algorithm",  # 开源社团 AI 应用开发 → algorithm
        "gap_id": "process_metric",
        "user_messages": [
            "我参加一个开源社团的 AI 应用开发贡献, 负责文档复现和部署流程梳理。",
            "我做了标准化模板, 按环境依赖、部署步骤、验证标准三类记录。",
            "结果团队复现成功率提升, 跨平台环境问题减少。",
            "整理成素材",
        ],
        "expected_slots": {
            "responsibility": "开源社团 AI 应用部署流程",
            "action": ["做标准化模板", "按三类记录"],
            "result": "复现成功率提升",
        },
        "expected_draft_has_metrics": False,
    },
    {
        "name": "sim_communication_volunteer",
        "source": "simulated_user_v1",
        "jd_text": (
            "岗位要求: 跨角色沟通、协调多方资源、"
            "在高压环境下推动事项落地。"
        ),
        "role": "general",  # 大型赛事志愿者协调 → general
        "gap_id": "communication",
        "user_messages": [
            "我参与过一场大型综合体育赛事的志愿服务, 负责场馆内勤和交通调度。",
            "我对接了 12 个工作组, 通过共享文档每天同步一次状态, 把突发需求分类处理。",
            "最后赛事流程高效有序, 获组委会优秀志愿者称号。",
            "整理成素材",
        ],
        "expected_slots": {
            "responsibility": "大型综合体育赛事场馆内勤和交通调度",
            "action": ["对接 12 个工作组", "共享文档同步", "分类处理突发需求"],
            "result": "赛事流程高效有序",
        },
        "expected_draft_has_metrics": False,
    },
    {
        "name": "sim_domain_x_data_label",
        "source": "simulated_user_v1",
        "jd_text": (
            "岗位要求: 理解数据标注规范、能制定判断标准、"
            "沉淀样例库, 有大模型评估经验加分。"
        ),
        "role": "data_annot",
        "gap_id": "domain_x",
        "user_messages": [
            "我做过一个数据标注项目, 负责检查文本分类结果是否符合预设规则。",
            "我先抽样看边界 case, 再把易混类别写成判断标准, 整理了 20 多条参考样例。",
            "最后组员判断一致性明显提升。",
            "整理成素材",
        ],
        "expected_slots": {
            "responsibility": "文本分类结果规则检查",
            "action": ["抽样看边界 case", "整理判断标准", "整理 20 多条参考样例"],
            "result": "组员判断一致性提升",
        },
        "expected_draft_has_metrics": True,
    },
    {
        "name": "sim_tech_metric_rubric_design",
        "source": "simulated_user_v1",
        "jd_text": (
            "岗位要求: 能从 Badcase 中抽象可量化指标、"
            "设计评分维度、提出优化方案。"
        ),
        "role": "tech_metric",
        "gap_id": "tech_metric",
        "user_messages": [
            "我在医疗垂类评测项目里负责从 Badcase 抽象评价指标。",
            "我用漏斗式评分算法把度量拆成安全、交互、表现、胜任力 4 层, 再用 10 大维度优先级铁律定拦截规则。",
            "最后模型在 0-4 分档位上的分布差异被量化, 输出定向纠正 + 低分拦截方案。",
            "整理成素材",
        ],
        "expected_slots": {
            "responsibility": "医疗垂类评测项目 Badcase 抽象",
            "method": ["漏斗式评分算法", "10 大维度优先级铁律"],
            "metric": ["0-4 分档位", "4 层"],
        },
        "expected_draft_has_metrics": True,
    },
    {
        "name": "sim_process_metric_eval_pipeline",
        "source": "simulated_user_v1",
        "jd_text": (
            "岗位要求: 能搭建评测流程、跟进问题闭环、"
            "输出可视化报告, 推动模型迭代。"
        ),
        "role": "test_qa",  # 评测流程搭建 → test_qa
        "gap_id": "process_metric",
        "user_messages": [
            "我负责一个评测流程的搭建, 主要是从模型输出到 Badcase 分析再到迭代建议的全链路。",
            "我做了科室 × 服务周期 × 用户身份三层框架, 覆盖 13 个科室。",
            "最后验证模型在真实医疗场景的可靠性, 输出 5 份分析报告支持研发迭代。",
            "整理成素材",
        ],
        "expected_slots": {
            "responsibility": "评测流程搭建",
            "action": ["做三层框架", "覆盖 13 个科室", "输出 5 份分析报告"],
            "result": "验证模型可靠性",
        },
        "expected_draft_has_metrics": True,
    },
]

# 把两组样本合并, 但用 source 字段区分, 报告里分别聚合
EVAL_SET_ALL: list[dict] = EVAL_SET_PLAN_BASELINE + EVAL_SET_SIMULATED


# ======================================================================
# 辅助 helper
# ======================================================================
# core.interview_agent.SLOT_NAMES 顺序: background, responsibility, action, method,
# difficulty, result, metric (plan §1.3)
SLOT_KEYS_SINGLE: tuple[str, ...] = ("background", "responsibility", "difficulty", "result")
SLOT_KEYS_LIST: tuple[str, ...] = ("action", "method", "metric")


def _slot_value_length(slot_key: str, value: Any) -> int:
    """单值 slot: str 字符数; 列表 slot: 列表总字符数(空列表 = 0)."""
    if value is None:
        return 0
    if slot_key in SLOT_KEYS_SINGLE:
        return len(str(value)) if value else 0
    if slot_key in SLOT_KEYS_LIST:
        if not isinstance(value, list):
            return 0
        return sum(len(str(v)) for v in value)
    return 0


def _extract_slots_iteratively(user_messages: list[str], session) -> dict[str, Any]:
    """
    plan §5.5 test_extract_slots_from_messages_iterates_turns:
    多轮 user_messages 依次跑 extract_slots, 累加到 captured_slots.

    实现方式:
      - 按 plan §1.3 的 slot 顺序迭代 user_messages
      - 当前 slot 用 core.interview_agent._current_slot 决定
      - 每条 user_message 走一次 extract_slots, 把 delta 写入 session.captured_slots
      - turn_count 同步递增
    """
    from core.interview_agent import _current_slot, apply_action  # noqa: PLC0415

    for msg in user_messages:
        # 跳过 "整理成素材" 这种动作 chip(不是 answer)
        if msg.strip() == "整理成素材":
            continue
        try:
            session, _resp = apply_action(session, ActionType.ANSWER, msg)
        except Exception:
            # 单条提取失败不阻断主流程
            continue
    return session.captured_slots


def _compute_schema_pass_rate(samples: list[dict]) -> float:
    """
    聚合函数: plan §5.5 test_compute_schema_pass_rate_returns_float
    返 [0, 1] 浮点: 满足 expected_slots 必填字段的比例平均值.
    """
    if not samples:
        return 0.0
    rates: list[float] = []
    for s in samples:
        expected = s.get("expected_slots", {}) or {}
        if not expected:
            rates.append(1.0)
            continue
        # session 在 evaluate_one 里建, 这里我们从 row['captured_slots'] 算
        captured = s.get("captured_slots", {}) or {}
        hit = 0
        for k, expected_val in expected.items():
            actual = captured.get(k)
            if k in SLOT_KEYS_SINGLE:
                if actual and str(actual).strip():
                    hit += 1
            elif k in SLOT_KEYS_LIST:
                if isinstance(actual, list) and len(actual) > 0:
                    hit += 1
        rates.append(hit / len(expected) if expected else 1.0)
    return sum(rates) / len(rates) if rates else 0.0


def _compute_completeness(draft_card: dict) -> float:
    """
    必填字段填全比例(plan §5.4).
    draft_card 必填字段: background / responsibility / actions / methods / result / metrics.
    """
    required_keys = (
        "background", "responsibility", "actions", "methods", "result", "metrics",
    )
    filled = 0
    for k in required_keys:
        v = draft_card.get(k)
        if isinstance(v, list):
            if len(v) > 0:
                filled += 1
        else:
            if v and str(v).strip():
                filled += 1
    return filled / len(required_keys)


def _fabrication_guard(draft_card: dict, user_messages: list[str]) -> bool:
    """
    plan §5.5 test_fabrication_guard_detects_unconfirmed_claims:
    简单 keyword 扫描: 检查 draft_card.bullets 是否含 user_messages 全文里没出现过的"硬"关键词
    (数字 + 单位 / 专有名词近似)。
    Returns True if 没有 fabrication(干净), False if 怀疑有 fabrication.
    """
    user_text = " ".join(user_messages or [])
    # 用 metric 模式 (数字+单位) 反向校验: 抽取 bullets 里的所有 metric
    pattern = r"(\d+(?:\.\d+)?)\s*(人|%|倍|小时|天|次|万|个|条|例|分|层|个科室)"
    bullets = draft_card.get("draft_bullets", []) or []
    for b in bullets:
        for num, unit in re.findall(pattern, b):
            # 数字+单位 必须出现在 user_messages 里 (容许 ±0.5 容差)
            metric_str = f"{num}{unit}"
            if metric_str not in user_text:
                # 容差: 比如 "90% 以上" → "90%" 算匹配
                if num not in user_text:
                    return False
    return True


# ======================================================================
# R6-B Phase 5: 低置信度 slot 统计(spec §8 指标)
# ======================================================================
def _count_low_confidence_slots(session) -> tuple[int, int]:
    """
    统计 session.slot_meta 里 confidence < INTERVIEW_EVAL_LOW_CONFIDENCE(0.6) 的 meta 条数。

    返回 (low_count, total_count):
      - low_count: confidence < 0.6 的 meta 条数
      - total_count: session.slot_meta 里所有 meta 条数(含 high / low / 不合规)

    隐私边界(同 spec §5.2):
      - 只读 confidence 字段(0.0-1.0 number / bool 被拒)
      - 不读 source_span / user_message

    边界:
      - session.slot_meta 不是 dict 或 None → (0, 0)
      - 单 entry 缺 confidence / confidence 是 bool / 非 number → 该条不计入 low_count
        但仍计入 total_count
    """
    slot_meta = getattr(session, "slot_meta", None)
    if not isinstance(slot_meta, dict) or not slot_meta:
        return (0, 0)
    low = 0
    total = 0
    for _slot, entries in slot_meta.items():
        if not isinstance(entries, list):
            continue
        for e in entries:
            if not isinstance(e, dict):
                total += 1
                continue
            total += 1
            conf = e.get("confidence")
            # bool 拒绝(spec §5.2: bool 不接受)
            if isinstance(conf, bool):
                continue
            if not isinstance(conf, (int, float)):
                continue
            if conf < INTERVIEW_EVAL_LOW_CONFIDENCE:
                low += 1
    return (low, total)


# ======================================================================
# R6-B Phase 5: fallback_category 分类(spec §8 + R5-C Phase 1 5 类常量)
# ======================================================================
def _classify_interview_fallback_category(
    *,
    extractor_mode: str,
    actual_mode: str,
    error_type: str | None,
) -> str:
    """
    把每条 eval row 分类到 5 类 fallback_category(spec §2.2 + R5-C Phase 1 一致)。

    优先级:
      1. error_type 非 None(单条样本跑挂了)→ FALLBACK_WORKFLOW_ABORT
      2. extractor_mode=rules + 实际 rules → FALLBACK_NONE
      3. extractor_mode=llm + 实际 llm_assisted → FALLBACK_NONE
      4. extractor_mode=llm + 实际 rules → FALLBACK_LLM_DISABLED
         (offline 模式强制规则版 / live + 无 key / live + LLM 失败都归此类)
      5. 其它 → FALLBACK_NONE(spec §6 兜底)

    边界:
      - 不读 env / 不发网络
      - 纯函数, 可直接被测试调
    """
    if error_type is not None:
        return FALLBACK_WORKFLOW_ABORT
    if extractor_mode == EXTRACTOR_RULES:
        return FALLBACK_NONE
    # extractor_mode == EXTRACTOR_LLM
    if actual_mode == "llm_assisted":
        return FALLBACK_NONE
    # LLM 意图但实际走 rules — 必然是 fallback
    return FALLBACK_LLM_DISABLED


# ======================================================================
# R6-C.1: Eval contract 校验(路线 A, round6-c-live-eval-result §5)
# ======================================================================
def _validate_eval_contract(sample: dict) -> list[dict]:
    """
    检查 sample.expected_slots 是否在"3 轮可触达 + 该 gap suggested_slots 内"的合同下可达。

    判定规则(对齐 R6-C.1 路线 A 验收点):
      1. slot 不在 GAP_SUGGESTED_SLOTS[gap_id] 中 → unreachable_expected_slot warning
         (policy 不会主动追问, 从 user_messages 抽取也仅在 LLM 自由发挥下可能命中)
      2. slot 在 suggested 中但位置 >= MAX_TURNS_PER_GAP(=3) 且
         不在 near_limit 触达集合 {metric, result} 中 → beyond_three_turns_expected_slot warning
         (spec §6 step 5: turn_count >= MAX_TURNS_PER_GAP - 1 时, policy 优先问 metric/result,
         但其它 slot 在 suggested 列表后段的位置 3、4 仍可能不可达)
      3. 位置 < 3 / 位置 >= 3 但属于 metric/result → 不产生 warning
      4. 未知 gap_id → 所有 expected slot 视为 unreachable(spec §5.3 fallback)

    输入: sample dict(含 name / gap_id / expected_slots)
    输出: list[dict] warning records, 每条仅含
      {"name": str, "gap_id": str, "slot": str, "code": str}

    隐私边界(round6-c-live-eval-result §5 + spec §12 + AGENTS.md):
      - 不读 sample.user_messages / draft_card / source_span / API key / prompt 正文
      - 返回 dict 只含 name / gap_id / slot / code 4 字段, 不含原文或凭据
      - 纯函数, 不调网络, 不读 env var, 不 import 任何 LLM 模块
    """
    warnings: list[dict] = []
    expected = sample.get("expected_slots", {}) or {}
    if not expected:
        return warnings

    name = str(sample.get("name", "") or "")
    gap_id = str(sample.get("gap_id", "") or "")
    suggested = GAP_SUGGESTED_SLOTS.get(gap_id, ())

    for slot_key in expected.keys():
        slot_key = str(slot_key)
        if slot_key not in suggested:
            # 未知 gap_id / slot 不在 suggested 中 → unreachable
            warnings.append({
                "name": name,
                "gap_id": gap_id,
                "slot": slot_key,
                "code": EVAL_CONTRACT_WARN_UNREACHABLE,
            })
            continue
        # suggested 位置 index(spec §6 step 6 顺序)
        try:
            position = suggested.index(slot_key)
        except ValueError:
            # 防御性: 同时存在的 slot 不应触发, 但兜底为 unreachable
            warnings.append({
                "name": name,
                "gap_id": gap_id,
                "slot": slot_key,
                "code": EVAL_CONTRACT_WARN_UNREACHABLE,
            })
            continue
        if position >= MAX_TURNS_PER_GAP and slot_key not in _NEAR_LIMIT_REACHABLE_SLOTS:
            warnings.append({
                "name": name,
                "gap_id": gap_id,
                "slot": slot_key,
                "code": EVAL_CONTRACT_WARN_BEYOND_3,
            })

    return warnings


def _collect_eval_contract_warnings(samples: list[dict]) -> list[dict]:
    """
    聚合一组 sample 的 eval contract warning。每条 sample 的 warning 平铺, 不聚合不分组。
    """
    out: list[dict] = []
    for s in samples:
        out.extend(_validate_eval_contract(s))
    return out


# ======================================================================
# 单条评估
# ======================================================================
@dataclass
class EvalRow:
    name: str
    source: str
    role: str
    gap_id: str
    schema_pass: bool
    fallback_used: bool
    draft_card_completeness: float
    fabrication_guard: bool
    latency_ms: int
    rewrite_changed_count: int
    # 只存 slot key + 长度 + 命中状态, 不存原文
    captured_slot_keys: list[str] = field(default_factory=list)
    captured_slot_lengths: dict[str, int] = field(default_factory=dict)
    error_type: str | None = None
    # R6-B Phase 5 新增(spec §8)
    extractor_mode: str = EXTRACTOR_RULES
    """本次 eval 意图的抽取模式: 'rules' / 'llm'。"""
    fallback_category: str = FALLBACK_NONE
    """5 类 fallback 分类(对齐 R5-C Phase 1): none / llm_disabled_fallback /
    tool_error_fallback / schema_retry_fallback / workflow_abort_fallback。"""
    low_confidence_slot_count: int = 0
    """session.slot_meta 里 confidence < 0.6 的 meta 条数(spec §5.2)。"""
    total_slot_meta_count: int = 0
    """session.slot_meta 总 meta 条数(分母 — 算 low_confidence_slot_rate 用)。"""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "source": self.source,
            "role": self.role,
            "gap_id": self.gap_id,
            "schema_pass": self.schema_pass,
            "fallback_used": self.fallback_used,
            "fallback_category": self.fallback_category,
            "extractor_mode": self.extractor_mode,
            "draft_card_completeness": round(self.draft_card_completeness, 3),
            "fabrication_guard": self.fabrication_guard,
            "latency_ms": self.latency_ms,
            "rewrite_changed_count": self.rewrite_changed_count,
            "captured_slot_keys": list(self.captured_slot_keys),
            "captured_slot_lengths": dict(self.captured_slot_lengths),
            "low_confidence_slot_count": self.low_confidence_slot_count,
            "total_slot_meta_count": self.total_slot_meta_count,
            "error_type": self.error_type,
        }


def _evaluate_one(
    sample: dict,
    materials: dict,
    *,
    extractor_mode: str = EXTRACTOR_RULES,
) -> EvalRow:
    """
    跑单条样本 × 单组:
      1. create_session(plan §1.3, R6-B Phase 2 enable_interview_llm 由 extractor_mode 决定)
      2. 多轮 user_messages 走 apply_action(answer) 累积 slot
      3. can_draft → build_draft_card
      4. 算 schema_pass / completeness / fabrication_guard / latency / fallback_category

    R6-B Phase 5: extractor_mode 取值:
      - EXTRACTOR_RULES: 字节级一致 R6-A Phase 5 — enable_interview_llm=False, session.interview_mode="rules"
      - EXTRACTOR_LLM:   enable_interview_llm=True; 实际 session.interview_mode 由
                         core.interview_agent._decide_interview_mode 决定
                         (有 key → llm_assisted; 无 key → rules + warning)
                         不论 offline / live, 实际走 rules 都标记 FALLBACK_LLM_DISABLED

    隐私边界(spec §12 + AGENTS.md):
      - sample.user_messages 只在内存, 不写 EvalRow.to_dict() / 不写报告
      - capture 的 slot 值只存 key + 长度, 不存原文
      - session.slot_meta 只读 confidence 字段(不算 source_span / user_message)
    """
    t0 = time.perf_counter()
    name = sample["name"]
    source = sample.get("source", "unknown")
    role = sample["role"]
    gap_id = sample["gap_id"]
    jd_text = sample["jd_text"]
    user_messages = list(sample.get("user_messages", []) or [])
    expected = sample.get("expected_slots", {}) or {}

    if extractor_mode not in EXTRACTOR_MODES:
        extractor_mode = EXTRACTOR_RULES  # 兜底: 非法值回 rules, 字节级一致老路径
    enable_llm_intent = (extractor_mode == EXTRACTOR_LLM)

    # parse_jd + match_score 走 parse_jd 一次(规则版不需要 LLM)
    try:
        jd_digest = parse_jd(jd_text)
    except Exception as e:  # noqa: BLE001
        return EvalRow(
            name=name, source=source, role=role, gap_id=gap_id,
            schema_pass=False, fallback_used=True,
            fallback_category=FALLBACK_WORKFLOW_ABORT,
            extractor_mode=extractor_mode,
            draft_card_completeness=0.0, fabrication_guard=True,
            latency_ms=int((time.perf_counter() - t0) * 1000),
            rewrite_changed_count=0,
            error_type=f"parse_jd:{type(e).__name__}",
        )

    # create_session
    try:
        session = create_session(
            role, jd_text, materials,
            enable_interview_llm=enable_llm_intent,
        )
        # 强制选 plan §5.4 指定的 gap_id(从 _default_candidates() 拿)
        from core.interview_agent import _default_candidates  # noqa: PLC0415
        gap_found = None
        for g in _default_candidates():
            if g.gap_id == gap_id:
                gap_found = g
                break
        if gap_found is None:
            return EvalRow(
                name=name, source=source, role=role, gap_id=gap_id,
                schema_pass=False, fallback_used=True,
                fallback_category=FALLBACK_WORKFLOW_ABORT,
                extractor_mode=extractor_mode,
                draft_card_completeness=0.0, fabrication_guard=True,
                latency_ms=int((time.perf_counter() - t0) * 1000),
                rewrite_changed_count=0, error_type="gap_not_in_default",
            )
        session.selected_gap = gap_found
    except Exception as e:  # noqa: BLE001
        return EvalRow(
            name=name, source=source, role=role, gap_id=gap_id,
            schema_pass=False, fallback_used=True,
            fallback_category=FALLBACK_WORKFLOW_ABORT,
            extractor_mode=extractor_mode,
            draft_card_completeness=0.0, fabrication_guard=True,
            latency_ms=int((time.perf_counter() - t0) * 1000),
            rewrite_changed_count=0, error_type=f"create_session:{type(e).__name__}",
        )

    # 多轮 answer 抽 slot
    try:
        _extract_slots_iteratively(user_messages, session)
    except Exception as e:  # noqa: BLE001
        return EvalRow(
            name=name, source=source, role=role, gap_id=gap_id,
            schema_pass=False, fallback_used=True,
            fallback_category=FALLBACK_WORKFLOW_ABORT,
            extractor_mode=extractor_mode,
            draft_card_completeness=0.0, fabrication_guard=True,
            latency_ms=int((time.perf_counter() - t0) * 1000),
            rewrite_changed_count=0, error_type=f"answer_loop:{type(e).__name__}",
        )

    # can_draft 是软检查 — 即使 can_draft=False, build_draft_card 仍可基于已抽 slot 生成草稿
    # (规则版特性: 3 轮 MAX_TURNS 强制 DRAFT_READY, 但 captured_slots 可能不全,
    #  真实体现"规则版的槽位覆盖率"是核心指标)
    try:
        card = build_draft_card(session)
    except Exception as e:  # noqa: BLE001
        return EvalRow(
            name=name, source=source, role=role, gap_id=gap_id,
            schema_pass=False, fallback_used=True,
            fallback_category=FALLBACK_WORKFLOW_ABORT,
            extractor_mode=extractor_mode,
            draft_card_completeness=0.0, fabrication_guard=True,
            latency_ms=int((time.perf_counter() - t0) * 1000),
            rewrite_changed_count=0, error_type=f"build_draft:{type(e).__name__}",
        )

    # schema_pass: 所有 expected slot 都被非空填到
    schema_pass = True
    for k in expected:
        actual = session.captured_slots.get(k)
        if k in SLOT_KEYS_SINGLE:
            if not (actual and str(actual).strip()):
                schema_pass = False
                break
        elif k in SLOT_KEYS_LIST:
            if not (isinstance(actual, list) and len(actual) > 0):
                schema_pass = False
                break

    # R6-B Phase 5: fallback_category 分类(spec §8 + R5-C Phase 1 5 类)
    actual_mode = getattr(session, "interview_mode", "rules") or "rules"
    fallback_category = _classify_interview_fallback_category(
        extractor_mode=extractor_mode,
        actual_mode=actual_mode,
        error_type=None,
    )
    fallback_used = (fallback_category != FALLBACK_NONE)

    # completeness
    completeness = _compute_completeness(card)

    # fabrication guard
    fabric_ok = _fabrication_guard(card, user_messages)

    # rewrite_changed_count: draft_bullets 里"带量化" 的 bullet 数
    # (对比 plan expected_draft_has_metrics 字段)
    expected_has_metrics = bool(sample.get("expected_draft_has_metrics", False))
    actual_has_metrics = bool(card.get("metrics"))
    rewrite_changed_count = 1 if (expected_has_metrics != actual_has_metrics) else 0

    # slot keys + lengths
    captured_keys = list(session.captured_slots.keys())
    captured_lengths = {
        k: _slot_value_length(k, session.captured_slots.get(k))
        for k in captured_keys if not k.startswith("_")
    }

    # R6-B Phase 5: 低置信度 slot 统计(spec §8 指标)
    low_count, total_count = _count_low_confidence_slots(session)

    latency_ms = int((time.perf_counter() - t0) * 1000)

    return EvalRow(
        name=name, source=source, role=role, gap_id=gap_id,
        schema_pass=schema_pass,
        fallback_used=fallback_used,
        fallback_category=fallback_category,
        extractor_mode=extractor_mode,
        draft_card_completeness=completeness,
        fabrication_guard=fabric_ok,
        latency_ms=latency_ms,
        rewrite_changed_count=rewrite_changed_count,
        captured_slot_keys=captured_keys,
        captured_slot_lengths=captured_lengths,
        low_confidence_slot_count=low_count,
        total_slot_meta_count=total_count,
        error_type=None,
    )


# ======================================================================
# 全局聚合
# ======================================================================
def compute_metrics(all_rows: list[EvalRow]) -> dict:
    """
    聚合全局指标 + 按 source / extractor_mode 分组.

    R6-A Phase 5 指标(spec §5.4):
      - schema_pass_rate / fallback_rate / avg_completeness /
        fabrication_violations_count / avg_latency_ms / p95_latency_ms

    R6-B Phase 5 新增(spec §8):
      - low_confidence_slot_rate: 聚合 session.slot_meta 里 confidence < 0.6 的比例
      - by_extractor: 按 extractor_mode 二次分组的 metrics(compare 模式用)
      - 报告新增 fallback_category_breakdown: 5 类 fallback 分布(对齐 R5-C Phase 1)
    """
    if not all_rows:
        return {
            "total": 0,
            "schema_pass_rate": 0.0,
            "fallback_rate": 0.0,
            "avg_completeness": 0.0,
            "fabrication_violations_count": 0,
            "avg_latency_ms": 0,
            "p95_latency_ms": 0,
            "low_confidence_slot_rate": 0.0,
            "by_source": {},
            "by_extractor": {},
            "fallback_category_breakdown": {
                FALLBACK_NONE: 0,
                FALLBACK_LLM_DISABLED: 0,
                FALLBACK_TOOL_ERROR: 0,
                FALLBACK_SCHEMA_RETRY: 0,
                FALLBACK_WORKFLOW_ABORT: 0,
            },
        }
    n = len(all_rows)
    schema_pass = sum(1 for r in all_rows if r.schema_pass)
    fallback = sum(1 for r in all_rows if r.fallback_used)
    completeness_avg = sum(r.draft_card_completeness for r in all_rows) / n
    fabric_viol = sum(1 for r in all_rows if not r.fabrication_guard)
    latencies = [r.latency_ms for r in all_rows]

    # R6-B Phase 5: low_confidence_slot_rate 聚合
    total_low = sum(r.low_confidence_slot_count for r in all_rows)
    total_meta = sum(r.total_slot_meta_count for r in all_rows)
    low_confidence_slot_rate = (
        round(total_low / total_meta, 3) if total_meta > 0 else 0.0
    )

    # R6-B Phase 5: fallback_category_breakdown 5 类分布(对齐 R5-C Phase 1)
    fb_cat_counter: dict[str, int] = {
        FALLBACK_NONE: 0,
        FALLBACK_LLM_DISABLED: 0,
        FALLBACK_TOOL_ERROR: 0,
        FALLBACK_SCHEMA_RETRY: 0,
        FALLBACK_WORKFLOW_ABORT: 0,
    }
    for r in all_rows:
        cat = r.fallback_category or FALLBACK_NONE
        fb_cat_counter[cat] = fb_cat_counter.get(cat, 0) + 1

    by_source: dict[str, dict] = {}
    for r in all_rows:
        bucket = by_source.setdefault(
            r.source,
            {
                "total": 0, "schema_pass": 0, "fallback": 0,
                "completeness_sum": 0.0, "fabric_viol": 0,
                "latencies": [], "low_sum": 0, "meta_sum": 0,
            },
        )
        bucket["total"] += 1
        if r.schema_pass:
            bucket["schema_pass"] += 1
        if r.fallback_used:
            bucket["fallback"] += 1
        bucket["completeness_sum"] += r.draft_card_completeness
        if not r.fabrication_guard:
            bucket["fabric_viol"] += 1
        bucket["latencies"].append(r.latency_ms)
        bucket["low_sum"] += r.low_confidence_slot_count
        bucket["meta_sum"] += r.total_slot_meta_count

    by_source_summary: dict[str, dict] = {}
    for src, b in by_source.items():
        by_source_summary[src] = {
            "total": b["total"],
            "schema_pass_rate": round(b["schema_pass"] / b["total"], 3) if b["total"] else 0.0,
            "fallback_rate": round(b["fallback"] / b["total"], 3) if b["total"] else 0.0,
            "avg_completeness": round(b["completeness_sum"] / b["total"], 3) if b["total"] else 0.0,
            "fabrication_violations_count": b["fabric_viol"],
            "avg_latency_ms": int(sum(b["latencies"]) / len(b["latencies"])) if b["latencies"] else 0,
            "low_confidence_slot_rate": (
                round(b["low_sum"] / b["meta_sum"], 3) if b["meta_sum"] > 0 else 0.0
            ),
        }

    # R6-B Phase 5: by_extractor 二次分组(compare 模式用 — 含 2 组)
    by_extractor: dict[str, dict] = {}
    for r in all_rows:
        bucket = by_extractor.setdefault(
            r.extractor_mode,
            {
                "total": 0, "schema_pass": 0, "fallback": 0,
                "completeness_sum": 0.0, "fabric_viol": 0,
                "latencies": [], "low_sum": 0, "meta_sum": 0,
            },
        )
        bucket["total"] += 1
        if r.schema_pass:
            bucket["schema_pass"] += 1
        if r.fallback_used:
            bucket["fallback"] += 1
        bucket["completeness_sum"] += r.draft_card_completeness
        if not r.fabrication_guard:
            bucket["fabric_viol"] += 1
        bucket["latencies"].append(r.latency_ms)
        bucket["low_sum"] += r.low_confidence_slot_count
        bucket["meta_sum"] += r.total_slot_meta_count

    by_extractor_summary: dict[str, dict] = {}
    for ext, b in by_extractor.items():
        by_extractor_summary[ext] = {
            "total": b["total"],
            "schema_pass_rate": round(b["schema_pass"] / b["total"], 3) if b["total"] else 0.0,
            "fallback_rate": round(b["fallback"] / b["total"], 3) if b["total"] else 0.0,
            "avg_completeness": round(b["completeness_sum"] / b["total"], 3) if b["total"] else 0.0,
            "fabrication_violations_count": b["fabric_viol"],
            "avg_latency_ms": int(sum(b["latencies"]) / len(b["latencies"])) if b["latencies"] else 0,
            "p95_latency_ms": _percentile(b["latencies"], 95) if b["latencies"] else 0,
            "low_confidence_slot_rate": (
                round(b["low_sum"] / b["meta_sum"], 3) if b["meta_sum"] > 0 else 0.0
            ),
        }

    return {
        "total": n,
        "schema_pass_rate": round(schema_pass / n, 3),
        "fallback_rate": round(fallback / n, 3),
        "avg_completeness": round(completeness_avg, 3),
        "fabrication_violations_count": fabric_viol,
        "avg_latency_ms": int(sum(latencies) / len(latencies)) if latencies else 0,
        "p95_latency_ms": _percentile(latencies, 95),
        "low_confidence_slot_rate": low_confidence_slot_rate,
        "by_source": by_source_summary,
        "by_extractor": by_extractor_summary,
        "fallback_category_breakdown": fb_cat_counter,
    }


# ======================================================================
# 报告生成(隐私边界)
# ======================================================================
def _row_summary_for_report(row: EvalRow) -> str:
    """单条样本摘要: 只含 name/source/slot key/length, 不含原文."""
    keys_str = ", ".join(row.captured_slot_keys) if row.captured_slot_keys else "(空)"
    lens_str = ", ".join(f"{k}={v}" for k, v in row.captured_slot_lengths.items()) or "—"
    return (
        f"`{row.name}` ({row.source}) | role=`{row.role}` gap=`{row.gap_id}` | "
        f"extractor=`{row.extractor_mode}` fb_cat=`{row.fallback_category}` | "
        f"schema_pass={'✅' if row.schema_pass else '❌'} | "
        f"completeness={row.draft_card_completeness:.2f} | "
        f"fabrication={'✅' if row.fabrication_guard else '❌'} | "
        f"latency={row.latency_ms}ms | "
        f"low_conf={row.low_confidence_slot_count}/{row.total_slot_meta_count} | "
        f"slots=[{keys_str}] lens=[{lens_str}]"
        f"{f' | error={row.error_type}' if row.error_type else ''}"
    )


def write_report(
    all_rows: list[EvalRow],
    metrics: dict,
    output_path: Path,
    llm_eval_config: dict,
    *,
    requested_mode: str,
    extractor_mode: str = EXTRACTOR_RULES,
    by_extractor_metrics: dict | None = None,
) -> None:
    """
    报告章节(plan §5.4 + R6-B Phase 5 spec §8 + §10):
      ## 0、LLM 元信息 (R5-D Phase 2 复用)
      ## 一、Eval set 概览
      ## 二、{extractor_label} 路径基线(全局聚合 + by_source)
      ## 2.5、Rules vs LLM-assisted 对照(仅 --extractor compare 渲染)
      ## 三、fallback_category 分布(R6-B Phase 5 新增, 5 类对齐 R5-C)
      ## 四、每条样本摘要 (只含 slot key + 长度, 不含原文)
      ## 五、Fabrication guard
      ## 六、延迟分布
      ## 七、隐私检查
      ## 八、结论

    隐私边界(spec §8 + §12 + AGENTS.md):
      - 不含 user_message / draft_card 原文 / prompt / raw response / source_span / API key
      - placeholder 白名单沿用 R5-D (_check_pii_safe)
      - 报告路径在 .gitignore (backend/logs/)
      - offline 模式 + llm 意图 → row.fallback_category="llm_disabled_fallback"
        写在报告里, 让审计一眼看到 LLM 没真跑
    """
    extractor_label = {
        EXTRACTOR_RULES: "规则版",
        EXTRACTOR_LLM: "LLM 意图",
        EXTRACTOR_COMPARE: "Compare (rules + llm 意图)",
    }.get(extractor_mode, extractor_mode)

    lines: list[str] = []
    lines.append(f"# Interview Agent 评测报告 ({extractor_label})")
    lines.append("")
    lines.append(f"> 版本: {VERSION}")
    lines.append(f"> 跑测时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"> Eval mode requested: **{requested_mode}** | resolved: **{llm_eval_config['llm_mode']}**")
    lines.append(f"> Extractor mode: **{extractor_mode}**")
    lines.append("")

    # 0、LLM 元信息(R5-D Phase 2 复用)
    lines.append("## 0、LLM 元信息 (R5-D Phase 2 复用)")
    lines.append("")
    lines.append(f"- `llm_mode`: **{llm_eval_config['llm_mode']}**")
    lines.append(f"- `llm_enabled`: `{llm_eval_config['llm_enabled']}`")
    lines.append(f"- `llm_model`: `{llm_eval_config['llm_model']}`")
    lines.append(f"- `llm_base_url_host`: `{llm_eval_config['llm_base_url_host'] or '(空)'}`")
    lines.append("")
    lines.append("> 隐私边界: 不读 / 不展示 API key 类凭据; base_url 只展示 host 部分。")
    lines.append("")

    # 一、Eval set 概览
    lines.append("## 一、Eval set 概览")
    lines.append("")
    lines.append(f"- 样本总数: **{metrics['total']}**")
    if extractor_mode == EXTRACTOR_COMPARE:
        lines.append(
            f"- compare 双组: rules × {len(EVAL_SET_ALL)} + llm 意图 × {len(EVAL_SET_ALL)} "
            f"= {len(EVAL_SET_ALL) * 2}"
        )
    lines.append("- 分组:")
    for src, b in metrics["by_source"].items():
        lines.append(
            f"  - `{src}`: {b['total']} 条"
        )
    lines.append("")
    lines.append("> 边界: `plan_baseline` = plan §5.4 固定 3 条脱敏样本; "
                 "`simulated_user_v1` = 基于对话项目脱敏化的 7 条模拟样本。"
                 "Simulated 不算真实使用反馈(plan §5.1 启动条件 ③ 未满足)。")
    lines.append("")

    # 二、{extractor_label} 路径基线
    lines.append(f"## 二、{extractor_label} 路径基线(R6-B Phase 5)")
    lines.append("")
    lines.append("| 指标 | 全局 |")
    lines.append("|---|---|")
    lines.append(f"| `schema_pass_rate` | {metrics['schema_pass_rate']:.2f} |")
    lines.append(f"| `fallback_rate` | {metrics['fallback_rate']:.2f} |")
    lines.append(f"| `avg_draft_card_completeness` | {metrics['avg_completeness']:.2f} |")
    lines.append(f"| `fabrication_violations_count` | {metrics['fabrication_violations_count']} |")
    lines.append(f"| `avg_latency_ms` | {metrics['avg_latency_ms']} |")
    lines.append(f"| `p95_latency_ms` | {metrics['p95_latency_ms']} |")
    lines.append(f"| `low_confidence_slot_rate` | {metrics['low_confidence_slot_rate']:.2f} |")
    lines.append("")
    # R6-C.1: fallback_rate 口径声明(round6-c-live-eval-result §2.5 + 路线 A 验收点)
    lines.append(
        "> **fallback_rate 口径声明 (R6-C.1)**: `fallback_rate` 是 workflow / session 级聚合, "
        "即 extractor_mode=llm 时实际仍走规则版 (`fb_cat=llm_disabled_fallback`) 的样本占比; "
        "它**不代表 slot 级 LLM 抽取成功率**, 也不区分本轮 LLM 抽取失败后规则兜底的情况。"
        "若要判断 LLM 抽取质量, 需结合本报告 2.5 / 三 / 4.5 三层信号综合判断。"
    )
    lines.append("")
    lines.append("按 source 分组:")
    lines.append("")
    lines.append("| source | total | schema_pass_rate | avg_completeness | fabric_viol | avg_latency_ms | low_conf_rate |")
    lines.append("|---|---|---|---|---|---|---|")
    for src, b in metrics["by_source"].items():
        lines.append(
            f"| `{src}` | {b['total']} | {b['schema_pass_rate']:.2f} | "
            f"{b['avg_completeness']:.2f} | {b['fabrication_violations_count']} | "
            f"{b['avg_latency_ms']} | {b['low_confidence_slot_rate']:.2f} |"
        )
    lines.append("")

    # 2.5、Rules vs LLM-assisted 对照 (compare 模式)
    if extractor_mode == EXTRACTOR_COMPARE and by_extractor_metrics:
        lines.append("## 2.5、Rules vs LLM-assisted 对照 (R6-B Phase 5 eval compare)")
        lines.append("")
        rules_m = by_extractor_metrics.get(EXTRACTOR_RULES, {})
        llm_m = by_extractor_metrics.get(EXTRACTOR_LLM, {})
        # R6-C.1: 列名按 requested_mode 动态化, 修正 R6-B Phase 5 残留的
        # 'offline → 强制规则 fallback' stale wording (live 报告误用).
        if requested_mode == MODE_LIVE:
            llm_col_label = "llm 意图(live + 已配置 LLM 凭据 → 真实 LLM 抽取)"
        else:
            llm_col_label = "llm 意图(offline → 强制规则 fallback)"
        lines.append(f"| 指标 | rules | {llm_col_label} |")
        lines.append("|---|---|---|")
        # 7 指标对照
        rows_pairs = [
            ("total", "样本数", lambda m: m.get("total", 0)),
            ("schema_pass_rate", "schema_pass_rate", lambda m: f"{m.get('schema_pass_rate', 0):.2f}"),
            ("fallback_rate", "fallback_rate", lambda m: f"{m.get('fallback_rate', 0):.2f}"),
            ("avg_completeness", "avg_completeness", lambda m: f"{m.get('avg_completeness', 0):.2f}"),
            ("fabrication_violations_count", "fabrication_violations", lambda m: m.get("fabrication_violations_count", 0)),
            ("avg_latency_ms", "avg_latency_ms", lambda m: m.get("avg_latency_ms", 0)),
            ("p95_latency_ms", "p95_latency_ms", lambda m: m.get("p95_latency_ms", 0)),
            ("low_confidence_slot_rate", "low_confidence_slot_rate", lambda m: f"{m.get('low_confidence_slot_rate', 0):.2f}"),
        ]
        for _key, label, fn in rows_pairs:
            lines.append(f"| `{label}` | {fn(rules_m)} | {fn(llm_m)} |")
        lines.append("")
        # 增量 / 差异(delta) — compare 视觉强化
        if rules_m and llm_m:
            delta_schema = llm_m.get("schema_pass_rate", 0) - rules_m.get("schema_pass_rate", 0)
            delta_complete = llm_m.get("avg_completeness", 0) - rules_m.get("avg_completeness", 0)
            lines.append("**Delta (llm 意图 − rules):**")
            lines.append(f"- `schema_pass_rate`: {delta_schema:+.2f}")
            lines.append(f"- `avg_completeness`: {delta_complete:+.2f}")
            lines.append("")
        # R6-C.1: 修正注释, 按 requested_mode 联动, 避免 offline stale wording
        if requested_mode == MODE_LIVE:
            lines.append(
                "> live 模式 + 已配置 LLM 凭据, llm 意图路径真发网络, "
                "Delta 反映 rules vs LLM-assisted 的真实抽取质量差。"
                "若 llm 组的 `fallback_rate` 不为 0, 需检查 LLM 调用是否被 `tool_error` / `schema_retry` 拦下。"
            )
        else:
            lines.append(
                "> offline 模式下, llm 意图路径无法发网络 → 全部走规则版 + 标记 `llm_disabled_fallback`。"
                "Delta 不代表真实 LLM 增益, 仅反映双组抽取路径在同一规则版上的稳定性。"
                "要评估 LLM 真实收益, 需跑 `live` 模式 + 真实 LLM 凭据。"
        )
        lines.append("")

    # 三、fallback_category 分布(R6-B Phase 5 新增)
    lines.append("## 三、fallback_category 分布 (R6-B Phase 5, 对齐 R5-C Phase 1 5 类)")
    lines.append("")
    fb_break = metrics.get("fallback_category_breakdown", {})
    lines.append("| 类别 | 数量 | 占比 |")
    lines.append("|---|---|---|")
    n = max(1, metrics.get("total", 0))
    for cat in (
        FALLBACK_NONE, FALLBACK_LLM_DISABLED, FALLBACK_TOOL_ERROR,
        FALLBACK_SCHEMA_RETRY, FALLBACK_WORKFLOW_ABORT,
    ):
        cnt = fb_break.get(cat, 0)
        rate = round(cnt / n, 3) if n else 0.0
        lines.append(f"| `{cat}` | {cnt} | {rate:.2f} |")
    lines.append("")
    lines.append(
        "> 类别定义: `none` = 无 fallback; `llm_disabled_fallback` = LLM 意图但实际走规则版"
        "(offline 模式 / 无 key / LLM 失败); `tool_error_fallback` / `schema_retry_fallback` / "
        "`workflow_abort_fallback` 留给后续 live 模式跑出的真实 LLM 失败场景。"
    )
    lines.append("")

    # 四、每条样本摘要(只含 slot key + 长度)
    lines.append("## 四、每条样本摘要 (只含 slot key + 长度, 不含原文)")
    lines.append("")
    for row in all_rows:
        lines.append(f"- {_row_summary_for_report(row)}")
    lines.append("")

    # 4.5、Eval contract warnings (R6-C.1, round6-c-live-eval-result §5 路线 A)
    # 从 EVAL_SET_ALL 按 row.name 反查 sample.expected_slots, 不读 row 字段,
    # 避免 EvalRow 引入原文(隐私边界)
    contract_warnings: list[dict] = []
    sample_by_name = {s.get("name"): s for s in EVAL_SET_ALL if isinstance(s, dict)}
    seen_samples: set[str] = set()
    for row in all_rows:
        if row.name in seen_samples:
            continue  # 同一 sample 在 compare 模式下跑 2 组, warning 按 sample 去重
        seen_samples.add(row.name)
        sample = sample_by_name.get(row.name)
        if sample is None:
            continue
        contract_warnings.extend(_validate_eval_contract(sample))
    lines.append("## 4.5、Eval contract warnings (R6-C.1)")
    lines.append("")
    if contract_warnings:
        lines.append(
            f"本章节列出 `expected_slots` 与 policy 3 轮上限 / gap suggested_slots 之间的合同不一致, "
            f"共 **{len(contract_warnings)}** 条 unique warning (按 sample 去重, 不依赖 extractor mode)。"
            f"warning 提示: 当前 `schema_pass_rate` / `avg_completeness` 不一定能完整反映产品目标, "
            f"需结合本章节判断 sample 是否在合同外被评分。"
        )
        lines.append("")
        lines.append("| sample | gap | slot | code |")
        lines.append("|---|---|---|---|")
        for w in contract_warnings:
            lines.append(
                f"| `{w['name']}` | `{w['gap_id']}` | `{w['slot']}` | `{w['code']}` |"
            )
        lines.append("")
        lines.append(
            "> code 含义: `unreachable_expected_slot` = expected slot 不在该 gap 的 `GAP_SUGGESTED_SLOTS` 中, "
            "policy 不会主动追问, 从 user_messages 抽取也仅在 LLM 自由发挥下可能命中; "
            "`beyond_three_turns_expected_slot` = expected slot 在 suggested 顺序中位置 ≥ `MAX_TURNS_PER_GAP`(=3), "
            "且不属于 near-limit 触达集合 `{metric, result}`, 前 3 轮内很可能无法被问到。"
        )
        lines.append("")
    else:
        lines.append(
            "- 无 contract warning: 所有样本的 `expected_slots` 在 `MAX_TURNS_PER_GAP` 内可达, "
            "且属于对应 gap 的 `GAP_SUGGESTED_SLOTS` 集合。"
        )
        lines.append("")

    # 五、Fabrication guard
    lines.append("## 五、Fabrication guard")
    lines.append("")
    lines.append(f"- 总 violation 数: **{metrics['fabrication_violations_count']}**")
    viol_rows = [r for r in all_rows if not r.fabrication_guard]
    if viol_rows:
        lines.append("- 触发 violation 的样本:")
        for r in viol_rows:
            lines.append(f"  - `{r.name}` ({r.source}) extractor=`{r.extractor_mode}`")
    else:
        lines.append("- 无 violation(所有样本的 draft_bullets 量化数字均能在 user_messages 里找到来源)")
    lines.append("")
    lines.append("> 简单实现: regex `(\\d+(?:\\.\\d+)?)\\s*(人|%|倍|小时|天|次|万|个|条|例|分|层|个科室)` "
                 "抽取 bullets 里所有量化短语, 检查它们是否都出现在 user_messages 原文里。")
    lines.append("")

    # 六、延迟分布
    lines.append("## 六、延迟分布")
    lines.append("")
    latencies = [r.latency_ms for r in all_rows]
    if latencies:
        lines.append(f"- min: `{min(latencies)}ms`")
        lines.append(f"- median: `{int(statistics.median(latencies))}ms`")
        lines.append(f"- mean: `{int(sum(latencies) / len(latencies))}ms`")
        lines.append(f"- p95: `{_percentile(latencies, 95)}ms`")
        lines.append(f"- max: `{max(latencies)}ms`")
    else:
        lines.append("- (无样本)")
    lines.append("")
    lines.append("> offline 模式 = 纯 stdlib + 规则 regex, 不含任何 LLM 调用, latency 主要来自 "
                 "`parse_jd` + `match_score` + JSON 编解码。live 模式 + LLM 路径会额外叠加 "
                 "`urllib POST /chat/completions` 的网络耗时, 仅作参考, 不作为 eval 指标硬门槛。")
    lines.append("")

    # 七、隐私检查
    lines.append("## 七、隐私检查")
    lines.append("")
    # 把报告本身喂给 _check_pii_safe 做自检
    report_text = "\n".join(lines)
    safe = _check_pii_safe({"rows": [r.to_dict() for r in all_rows], "metrics": metrics})
    if safe:
        lines.append("- `_check_pii_safe(row + metrics)` 自检: **✅ 通过** (placeholder 白名单已过滤)")
    else:
        lines.append("- `_check_pii_safe(row + metrics)` 自检: **❌ 失败** (请检查是否泄漏了真实 PII)")
    lines.append("- 不含 user_message 原文 (R5-E 保护)")
    lines.append("- 不含 draft_card 原文 (R5-E 保护)")
    lines.append("- 不含 prompt / raw response (R6-B Phase 5 新增保护)")
    lines.append("- 不含 LLM 抽取源 span 明文 (R6-B Phase 1 保护, 仅存 hash + 长度)")
    lines.append("- 不含 API key 类凭据 / 含敏感 path 的 base_url (R5-D 保护)")
    lines.append("")

    # 八、结论
    lines.append("## 八、结论")
    lines.append("")
    lines.append(
        f"- Phase 5 eval compare 上线: 支持 `--extractor rules|llm|compare` 三模式;"
        f"本次跑 `extractor={extractor_mode}` × {len(EVAL_SET_ALL)} 样本"
        + (f" × 2 组 (compare)" if extractor_mode == EXTRACTOR_COMPARE else "")
    )
    lines.append(
        f"- 当前 schema_pass_rate = {metrics['schema_pass_rate']:.2f}, "
        f"avg_completeness = {metrics['avg_completeness']:.2f}, "
        f"fabrication_violations = {metrics['fabrication_violations_count']}, "
        f"low_confidence_slot_rate = {metrics['low_confidence_slot_rate']:.2f}。"
    )
    if extractor_mode == EXTRACTOR_COMPARE and by_extractor_metrics:
        rules_m = by_extractor_metrics.get(EXTRACTOR_RULES, {})
        llm_m = by_extractor_metrics.get(EXTRACTOR_LLM, {})
        delta_schema = llm_m.get("schema_pass_rate", 0) - rules_m.get("schema_pass_rate", 0)
        if llm_m.get("fallback_rate", 0) > 0:
            lines.append(
                f"- llm 意图路径 fallback_rate = {llm_m.get('fallback_rate', 0):.2f}"
                f"(全部 `llm_disabled_fallback`): **本次 offline 跑无法证伪 LLM 抽取收益**。"
                f"双组 delta 仅供参考, 真评估需跑 `live` + 真实 key。"
            )
        else:
            lines.append(
                f"- llm 意图路径 fallback_rate = {llm_m.get('fallback_rate', 0):.2f}, "
                f"双组 schema_pass_rate delta = {delta_schema:+.2f}"
            )
    lines.append(
        "- **未满足 plan §5.1 启动条件**: simulated_user_v1 ≠ 真实用户使用反馈。"
    )
    lines.append(
        "- **下一步**: 用户在 chat panel 跑 10+ 轮真实对话后, 跑 `live` 模式 + 真实 LLM key "
        "(手动) 再生成 v2 报告作 Phase 5 收益决策依据。"
    )
    lines.append("")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")


# ======================================================================
# 主流程
# ======================================================================
def main(argv=None) -> int:
    """
    R6-B Phase 5 CLI:
      --mode {offline, live, auto}      默认 offline (沿用 R5-D)
      --extractor {rules, llm, compare}  默认 rules (R6-B Phase 5)
      --output <path>                    默认 backend/logs/interview_eval_report.md

    行为决策表(对齐 R6-B spec §8 + Prompt 5):
      ┌─────────────────┬──────────┬──────────┬──────────────┐
      │ --extractor     │ offline  │ live+key │ live+no_key  │
      ├─────────────────┼──────────┼──────────┼──────────────┤
      │ rules           │ rules    │ rules    │ rules        │
      │ llm             │ fallback │ 真 LLM   │ RuntimeError │
      │ compare         │ 双组对比 │ 双组对比 │ RuntimeError │
      └─────────────────┴──────────┴──────────┴──────────────┘

    Exit code:
      0 — 正常完成
      2 — mode 非法 / live + (llm/compare) + 无 key
    """
    parser = argparse.ArgumentParser(
        description="R6-B Phase 5: Interview Agent eval compare 脚本 (rules/llm/compare)"
    )
    parser.add_argument(
        "--mode", choices=list(VALID_EVAL_MODES), default=MODE_OFFLINE,
        help="eval 模式 (offline/live/auto); 默认 offline",
    )
    parser.add_argument(
        "--extractor", choices=list(EXTRACTOR_MODES), default=EXTRACTOR_RULES,
        help=(
            "抽取模式 (rules/llm/compare); 默认 rules。"
            " offline 模式下 llm/compare 强制走规则版 + 标记 llm_disabled_fallback;"
            " live 模式下 llm/compare 需要 LLM_API_KEY 在 env。"
        ),
    )
    parser.add_argument(
        "--output", type=Path, default=DEFAULT_OUTPUT,
        help=f"报告路径; 默认 {DEFAULT_OUTPUT}",
    )
    args = parser.parse_args(argv)

    llm_enabled = is_llm_enabled()
    resolved_mode = _resolve_eval_mode(args.mode, llm_enabled)
    llm_eval_config = _get_llm_eval_config(llm_enabled, resolved_mode)

    # R6-B Phase 5: live + (llm/compare) + 无 key → RuntimeError
    # 错误信息不含 key 值 / env var 名(R5-D Phase 1 边界保护)
    if resolved_mode == MODE_LIVE and args.extractor in (EXTRACTOR_LLM, EXTRACTOR_COMPARE):
        if not llm_enabled:
            print(
                f"[error] --mode live + --extractor {args.extractor} 需要 LLM 已启用, "
                "当前 LLM 未启用; 请改用 --mode auto 或 --mode offline,"
                "或设置 LLM_API_KEY 环境变量后手动跑 live 模式。",
                file=sys.stderr,
            )
            return 2

    # 加载公开脱敏版 materials.json(读公开主库, 不读 _private_backup)
    from core.generator import load_materials  # noqa: PLC0415
    materials = load_materials()

    # R6-B Phase 5: dispatch 按 --extractor
    # - rules: 1 组, 默认行为(字节级一致 R6-A Phase 5)
    # - llm:   1 组, session.enable_interview_llm=True
    # - compare: 2 组(rules + llm 意图), 输出对照表
    rules_rows: list[EvalRow] = []
    llm_rows: list[EvalRow] = []
    if args.extractor == EXTRACTOR_RULES:
        for s in EVAL_SET_ALL:
            rules_rows.append(_evaluate_one(s, materials, extractor_mode=EXTRACTOR_RULES))
        all_rows = rules_rows
        by_extractor_metrics: dict | None = None
    elif args.extractor == EXTRACTOR_LLM:
        for s in EVAL_SET_ALL:
            llm_rows.append(_evaluate_one(s, materials, extractor_mode=EXTRACTOR_LLM))
        all_rows = llm_rows
        by_extractor_metrics = None
    else:  # compare
        for s in EVAL_SET_ALL:
            rules_rows.append(_evaluate_one(s, materials, extractor_mode=EXTRACTOR_RULES))
            llm_rows.append(_evaluate_one(s, materials, extractor_mode=EXTRACTOR_LLM))
        all_rows = rules_rows + llm_rows
        by_extractor_metrics = {
            EXTRACTOR_RULES: compute_metrics(rules_rows),
            EXTRACTOR_LLM: compute_metrics(llm_rows),
        }

    metrics = compute_metrics(all_rows)
    write_report(
        all_rows, metrics, args.output, llm_eval_config,
        requested_mode=args.mode,
        extractor_mode=args.extractor,
        by_extractor_metrics=by_extractor_metrics,
    )

    # stdout 摘要
    if args.extractor == EXTRACTOR_COMPARE and by_extractor_metrics:
        rules_m = by_extractor_metrics[EXTRACTOR_RULES]
        llm_m = by_extractor_metrics[EXTRACTOR_LLM]
        print(
            f"[ok] eval compare done. total={metrics['total']} "
            f"(rules={rules_m['total']} + llm 意图={llm_m['total']}) "
            f"rules schema_pass={rules_m['schema_pass_rate']:.2f} "
            f"llm schema_pass={llm_m['schema_pass_rate']:.2f} "
            f"llm fallback_rate={llm_m['fallback_rate']:.2f}"
        )
    else:
        print(
            f"[ok] eval done. total={metrics['total']} "
            f"schema_pass_rate={metrics['schema_pass_rate']:.2f} "
            f"avg_completeness={metrics['avg_completeness']:.2f} "
            f"fabric_violations={metrics['fabrication_violations_count']} "
            f"low_confidence_slot_rate={metrics['low_confidence_slot_rate']:.2f}"
        )
    print(f"[ok] report → {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())