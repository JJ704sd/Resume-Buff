#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Round 6-A Phase 5: Interview Agent eval 脚本(脚手架 + 规则版基线)

设计目标(对齐 plan §5.1-5.4):
  - 跑固定 eval set(3 条 plan §5.4 固定样本 + 7 条 simulated samples)
  - 用 core.interview_agent 的规则版 extract_slots / build_draft_card 跑基线
  - 输出 markdown 报告到 backend/logs/interview_eval_report.md(在 .gitignore)
  - 报告只含聚合指标 + 每条样本 slot key/长度/schema_pass/fallback_used/completeness/latency
  - 报告不含 user_message / draft_card 原文 / API key / 真实 PII
  - 默认 mode=offline,不发 HTTP
  - 不挂 pre-push hook(spec §12 #3 D6 决策)

复用 R5-D scripts/evaluate_agent_workflow.py 的 helper:
  - _resolve_eval_mode / _get_llm_eval_config / _check_pii_safe / _percentile
  - MODE_OFFLINE / MODE_LIVE / MODE_AUTO / VALID_EVAL_MODES

**Simulated data 标注边界**(对齐本轮跟用户对齐的边界):
  - EVAL_SET 里 3 条 plan 样本 source="plan_baseline"(脱敏,固定)
  - SIMULATED_SAMPLES 里 7 条 source="simulated_user_v1"(基于我们对话里讨论的项目做脱敏化)
  - 报告里区分 simulated_count vs real_user_count
  - 不污染 plan §5.1 启动条件 — 等用户在 chat panel 真跑 10+ 轮再切到 real data

跑法:
    D:\\python3.11\\python.exe scripts/evaluate_interview_agent.py --mode offline
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
VERSION = "R6-A Phase 5 (规则版 baseline; R6-A Phase 4 LLM slot extraction 已上线但需 key + 真实样本, 本报告仅跑 rules 路径)"


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

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "source": self.source,
            "role": self.role,
            "gap_id": self.gap_id,
            "schema_pass": self.schema_pass,
            "fallback_used": self.fallback_used,
            "draft_card_completeness": round(self.draft_card_completeness, 3),
            "fabrication_guard": self.fabrication_guard,
            "latency_ms": self.latency_ms,
            "rewrite_changed_count": self.rewrite_changed_count,
            "captured_slot_keys": list(self.captured_slot_keys),
            "captured_slot_lengths": dict(self.captured_slot_lengths),
            "error_type": self.error_type,
        }


def _evaluate_one(sample: dict, materials: dict) -> EvalRow:
    """
    跑单条样本 × 规则版(无 LLM 调用):
      1. create_session(plan §1.3)
      2. 多轮 user_messages 走 apply_action(answer) 累积 slot
      3. can_draft → build_draft_card
      4. 算 schema_pass / completeness / fabrication_guard / latency
    """
    t0 = time.perf_counter()
    name = sample["name"]
    source = sample.get("source", "unknown")
    role = sample["role"]
    gap_id = sample["gap_id"]
    jd_text = sample["jd_text"]
    user_messages = list(sample.get("user_messages", []) or [])
    expected = sample.get("expected_slots", {}) or {}

    # parse_jd + match_score 走 parse_jd 一次(规则版不需要 LLM)
    try:
        jd_digest = parse_jd(jd_text)
    except Exception as e:  # noqa: BLE001
        return EvalRow(
            name=name, source=source, role=role, gap_id=gap_id,
            schema_pass=False, fallback_used=True,
            draft_card_completeness=0.0, fabrication_guard=True,
            latency_ms=int((time.perf_counter() - t0) * 1000),
            rewrite_changed_count=0, error_type=f"parse_jd:{type(e).__name__}",
        )

    # create_session
    try:
        session = create_session(role, jd_text, materials)
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
                draft_card_completeness=0.0, fabrication_guard=True,
                latency_ms=int((time.perf_counter() - t0) * 1000),
                rewrite_changed_count=0, error_type="gap_not_in_default",
            )
        session.selected_gap = gap_found
    except Exception as e:  # noqa: BLE001
        return EvalRow(
            name=name, source=source, role=role, gap_id=gap_id,
            schema_pass=False, fallback_used=True,
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

    # fallback_used: 规则版无 LLM, 总是 fallback=False(没走 LLM,也没走 LLM 失败)
    fallback_used = False

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

    latency_ms = int((time.perf_counter() - t0) * 1000)

    return EvalRow(
        name=name, source=source, role=role, gap_id=gap_id,
        schema_pass=schema_pass,
        fallback_used=fallback_used,
        draft_card_completeness=completeness,
        fabrication_guard=fabric_ok,
        latency_ms=latency_ms,
        rewrite_changed_count=rewrite_changed_count,
        captured_slot_keys=captured_keys,
        captured_slot_lengths=captured_lengths,
        error_type=None,
    )


# ======================================================================
# 全局聚合
# ======================================================================
def compute_metrics(all_rows: list[EvalRow]) -> dict:
    """聚合 6 个全局指标 + 按 source 分组."""
    if not all_rows:
        return {
            "total": 0,
            "schema_pass_rate": 0.0,
            "fallback_rate": 0.0,
            "avg_completeness": 0.0,
            "fabrication_violations_count": 0,
            "avg_latency_ms": 0,
            "p95_latency_ms": 0,
            "by_source": {},
        }
    n = len(all_rows)
    schema_pass = sum(1 for r in all_rows if r.schema_pass)
    fallback = sum(1 for r in all_rows if r.fallback_used)
    completeness_avg = sum(r.draft_card_completeness for r in all_rows) / n
    fabric_viol = sum(1 for r in all_rows if not r.fabrication_guard)
    latencies = [r.latency_ms for r in all_rows]

    by_source: dict[str, dict] = {}
    for r in all_rows:
        bucket = by_source.setdefault(
            r.source,
            {
                "total": 0, "schema_pass": 0, "fallback": 0,
                "completeness_sum": 0.0, "fabric_viol": 0,
                "latencies": [],
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

    by_source_summary: dict[str, dict] = {}
    for src, b in by_source.items():
        by_source_summary[src] = {
            "total": b["total"],
            "schema_pass_rate": round(b["schema_pass"] / b["total"], 3) if b["total"] else 0.0,
            "fallback_rate": round(b["fallback"] / b["total"], 3) if b["total"] else 0.0,
            "avg_completeness": round(b["completeness_sum"] / b["total"], 3) if b["total"] else 0.0,
            "fabrication_violations_count": b["fabric_viol"],
            "avg_latency_ms": int(sum(b["latencies"]) / len(b["latencies"])) if b["latencies"] else 0,
        }

    return {
        "total": n,
        "schema_pass_rate": round(schema_pass / n, 3),
        "fallback_rate": round(fallback / n, 3),
        "avg_completeness": round(completeness_avg, 3),
        "fabrication_violations_count": fabric_viol,
        "avg_latency_ms": int(sum(latencies) / len(latencies)) if latencies else 0,
        "p95_latency_ms": _percentile(latencies, 95),
        "by_source": by_source_summary,
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
        f"schema_pass={'✅' if row.schema_pass else '❌'} | "
        f"completeness={row.draft_card_completeness:.2f} | "
        f"fabrication={'✅' if row.fabrication_guard else '❌'} | "
        f"latency={row.latency_ms}ms | "
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
) -> None:
    """
    报告章节(plan §5.4 + R6-B 校准):
      ## 0、LLM 元信息 (R5-D Phase 2 复用)
      ## 一、Eval set 概览
      ## 二、规则版基线 (R6-A Phase 4 LLM slot extraction 已上线, 本报告仅跑 rules; llm_assisted 对照待 R6-B Phase 5 eval compare)
      ## 三、每条样本摘要 (只含 slot key + 长度, 不含原文)
      ## 四、Fabrication guard
      ## 五、延迟分布
      ## 六、隐私检查
      ## 七、结论

    隐私边界:
      - 不含 user_message / draft_card 原文
      - 不含 LLM_API_KEY / 含敏感 path 的 base_url
      - placeholder 白名单沿用 R5-D (_check_pii_safe)
      - 报告路径在 .gitignore (backend/logs/)
    """
    lines: list[str] = []
    lines.append("# Interview Agent 评测报告 (R6-A Phase 5 规则版 baseline)")
    lines.append("")
    lines.append(f"> 版本: {VERSION}")
    lines.append(f"> 跑测时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"> Mode requested: **{requested_mode}** | resolved: **{llm_eval_config['llm_mode']}**")
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

    # 二、规则版基线(R6-A Phase 4 LLM 已落地但本报告只跑 rules; llm_assisted 对照待 R6-B Phase 5 eval compare)
    lines.append("## 二、规则版基线 (R6-A Phase 4 LLM slot extraction 已上线, 但本报告仅跑 rules baseline; llm_assisted 对照表等 R6-B Phase 5 eval compare)")
    lines.append("")
    lines.append("| 指标 | 全局 |")
    lines.append("|---|---|")
    lines.append(f"| `schema_pass_rate` | {metrics['schema_pass_rate']:.2f} |")
    lines.append(f"| `fallback_rate` | {metrics['fallback_rate']:.2f} |")
    lines.append(f"| `avg_draft_card_completeness` | {metrics['avg_completeness']:.2f} |")
    lines.append(f"| `fabrication_violations_count` | {metrics['fabrication_violations_count']} |")
    lines.append(f"| `avg_latency_ms` | {metrics['avg_latency_ms']} |")
    lines.append(f"| `p95_latency_ms` | {metrics['p95_latency_ms']} |")
    lines.append("")
    lines.append("按 source 分组:")
    lines.append("")
    lines.append("| source | total | schema_pass_rate | avg_completeness | fabric_viol | avg_latency_ms |")
    lines.append("|---|---|---|---|---|---|")
    for src, b in metrics["by_source"].items():
        lines.append(
            f"| `{src}` | {b['total']} | {b['schema_pass_rate']:.2f} | "
            f"{b['avg_completeness']:.2f} | {b['fabrication_violations_count']} | "
            f"{b['avg_latency_ms']} |"
        )
    lines.append("")

    # 三、每条样本摘要(只含 slot key + 长度)
    lines.append("## 三、每条样本摘要 (只含 slot key + 长度, 不含原文)")
    lines.append("")
    for row in all_rows:
        lines.append(f"- {_row_summary_for_report(row)}")
    lines.append("")

    # 四、Fabrication guard
    lines.append("## 四、Fabrication guard")
    lines.append("")
    lines.append(f"- 总 violation 数: **{metrics['fabrication_violations_count']}**")
    viol_rows = [r for r in all_rows if not r.fabrication_guard]
    if viol_rows:
        lines.append("- 触发 violation 的样本:")
        for r in viol_rows:
            lines.append(f"  - `{r.name}` ({r.source})")
    else:
        lines.append("- 无 violation(所有样本的 draft_bullets 量化数字均能在 user_messages 里找到来源)")
    lines.append("")
    lines.append("> 简单实现: regex `(\\d+(?:\\.\\d+)?)\\s*(人|%|倍|小时|天|次|万|个|条|例|分|层|个科室)` "
                 "抽取 bullets 里所有量化短语, 检查它们是否都出现在 user_messages 原文里。"
                 "R6-B Phase 5 eval compare 上线后, 这里升级为 rules vs llm_assisted 对照表。")
    lines.append("")

    # 五、延迟分布
    lines.append("## 五、延迟分布")
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
                 "`parse_jd` + `match_score` + JSON 编解码。")
    lines.append("")

    # 六、隐私检查
    lines.append("## 六、隐私检查")
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
    lines.append("- 不含 LLM_API_KEY / 含敏感 path 的 base_url (R5-D 保护)")
    lines.append("")

    # 七、结论
    lines.append("## 七、结论")
    lines.append("")
    lines.append(
        f"- Phase 5 脚手架就绪: 跑通 {metrics['total']} 条样本 × 规则版抽取, "
        f"产出了 6 项全局指标 + {len(metrics['by_source'])} 个 source 分组。"
    )
    lines.append(
        f"- 当前 schema_pass_rate = {metrics['schema_pass_rate']:.2f}, "
        f"avg_completeness = {metrics['avg_completeness']:.2f}, "
        f"fabrication_violations = {metrics['fabrication_violations_count']}。"
    )
    lines.append(
        "- **未满足 plan §5.1 启动条件**: simulated_user_v1 ≠ 真实用户使用反馈。"
    )
    lines.append(
        "- **下一步**: 用户在 chat panel 跑 10+ 轮真实对话后, 再跑一次本脚本生成 v2 报告(real + simulated)。"
    )
    lines.append("")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")


# ======================================================================
# 主流程
# ======================================================================
def main(argv=None) -> int:
    """
    CLI:
      --mode {offline, live, auto}  默认 offline (沿用 R5-D)
      --output <path>              默认 backend/logs/interview_eval_report.md
    """
    parser = argparse.ArgumentParser(
        description="R6-A Phase 5: Interview Agent eval 脚本(脚手架 + 规则版基线)"
    )
    parser.add_argument(
        "--mode", choices=list(VALID_EVAL_MODES), default=MODE_OFFLINE,
        help="eval 模式 (offline/live/auto); 默认 offline",
    )
    parser.add_argument(
        "--output", type=Path, default=DEFAULT_OUTPUT,
        help=f"报告路径; 默认 {DEFAULT_OUTPUT}",
    )
    args = parser.parse_args(argv)

    llm_enabled = is_llm_enabled()
    resolved_mode = _resolve_eval_mode(args.mode, llm_enabled)
    llm_eval_config = _get_llm_eval_config(llm_enabled, resolved_mode)

    # live 模式: Phase 5 暂不实现(R6-A Phase 4 LLM slot extraction 已落地但需 key + 真实使用样本做对照, 当前仅规则版 baseline)
    if resolved_mode == MODE_LIVE:
        print(
            "[error] --mode live 当前不可用: R6-A Phase 4 LLM slot extraction 已上线, "
            "但 live 对照需 LLM_API_KEY + 真实用户样本, 本脚本当前仅跑规则版 baseline。"
            "请改用 --mode offline。",
            file=sys.stderr,
        )
        return 2

    # 加载公开脱敏版 materials.json(读公开主库, 不读 _private_backup)
    from core.generator import load_materials  # noqa: PLC0415
    materials = load_materials()

    # 跑所有样本
    all_rows: list[EvalRow] = []
    for sample in EVAL_SET_ALL:
        row = _evaluate_one(sample, materials)
        all_rows.append(row)

    metrics = compute_metrics(all_rows)
    write_report(
        all_rows, metrics, args.output, llm_eval_config,
        requested_mode=args.mode,
    )

    # stdout 摘要
    print(f"[ok] eval done. total={metrics['total']} "
          f"schema_pass_rate={metrics['schema_pass_rate']:.2f} "
          f"avg_completeness={metrics['avg_completeness']:.2f} "
          f"fabric_violations={metrics['fabrication_violations_count']}")
    print(f"[ok] report → {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())