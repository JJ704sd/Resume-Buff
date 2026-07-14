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
VERSION = "R6-C.3 (LLM 抽取可观测性 + prompt few-shot; rules/llm/compare 三模式)"

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
# Eval set 1: plan §5.4 固定 3 条样本(脱敏)
# R6-C.2A: 每条 sample 加 product_goal / contract_note 字段, 说明评测合同.
# plan_baseline 3 条默认 product_goal = three_turn_friendly
# (3 轮内可生成素材, 不需要完整项目事实覆盖).
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
        # ---- R6-C.2A: 评测合同标注 ----
        # 产品目标: 3 轮内可生成素材(threshold friendly).
        # 合同说明: process_metric suggested = (responsibility, action, result, metric),
        # expected (responsibility/action/result) 都在 0-2 位置, 3 轮内 100% 可达.
        # 无 contract warning, 评测合同 = policy contract.
        "product_goal": "three_turn_friendly",
        "contract_note": (
            "3 轮内可生成素材目标; responsibility/action/result 都在 process_metric "
            "suggested 0-2 位置, 3 轮内 100% 可达, 无 contract warning."
        ),
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
        # R6-C.2A: 合同调整 — 移除 responsibility (不在 communication suggested),
        # 改为 (action, method, result) 表达"3 轮内可生成素材"目标.
        # 原 expected 含 responsibility 是 R6-A Phase 5 初始设计, 但 communication
        # gap 的 policy 不追问 responsibility (GAP_SUGGESTED_SLOTS['communication']
        # = (background, action, method, result)), 评测合同不一致.
        # 新 expected 选 3 轮内合理可问的关键 slot:
        #   - action (position 1) — 3 轮内 100% 必问
        #   - method (position 2) — 3 轮内 100% 必问
        #   - result (position 3) — near_limit 触达, 第 3 轮优先问
        "expected_slots": {
            "action": ["建立共享文档", "按时间、场地、物料分类", "同步状态"],
            "method": "按时间、场地、物料分类",
            "result": "分工更清楚, 负责人能看到待处理事项",
        },
        "expected_draft_has_metrics": False,
        # ---- R6-C.2A: 评测合同标注 ----
        # 产品目标: 3 轮内可生成素材.
        # 合同说明: 原 expected 含 responsibility 不在 communication suggested;
        # 调整为 (action, method, result) 表达 3 轮内可生成素材目标.
        # 3 个 expected slot 全部在 communication suggested 0-3 位置, 无 contract warning.
        "product_goal": "three_turn_friendly",
        "contract_note": (
            "3 轮内可生成素材目标; 原 expected 含 responsibility 不在 communication "
            "suggested 中, 调整为 (action/method/result) — action(method) 在 1-2 位置 "
            "3 轮内 100% 必问, result 在 near_limit 第 3 轮优先问, 无 contract warning."
        ),
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
        # ---- R6-C.2A: 评测合同标注 ----
        # 产品目标: 3 轮内可生成素材.
        # 合同说明: tech_metric suggested = (background, responsibility, action, method, result).
        # expected (responsibility/action/result): responsibility 在 1 位置, action 在 2 位置,
        # result 在 4 位置 (near_limit 第 3 轮触达). 3 轮内合理可问, 无 contract warning.
        "product_goal": "three_turn_friendly",
        "contract_note": (
            "3 轮内可生成素材目标; responsibility/action 在 tech_metric suggested "
            "0-2 位置 3 轮内 100% 可达, result 在 near_limit 触达, 无 contract warning."
        ),
    },
]


# ======================================================================
# Eval set 2: Simulated samples(基于对话里讨论的项目, 脱敏化)
# 边界(本轮跟用户对齐):
#   - 不写真实学校 / 公司 / 项目名 / 姓名
#   - 用"医疗垂类评测项目 / 心电时序项目 / 开源社团 / 大型赛事志愿"等抽象描述
#   - source="simulated_user_v1",报告里区分 simulated vs plan_baseline
#
# R6-C.2A: simulated_user_v1 默认 product_goal = full_fact_coverage
# (完整项目事实覆盖, 保留 expected 含 3 轮外 / suggested 外的 slot, 标记需后续
#  policy 调整, 不删 expected). 合同不达标的样本(tech_metric 含 metric/method 位置 3+,
# communication 含 responsibility)用 contract_note 字段记录"需后续 policy 调整"
# 决策依据, 报告 4.6 章节会渲染.
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
        # ---- R6-C.2A: 评测合同标注 ----
        # 产品目标: 完整项目事实覆盖(full_fact_coverage).
        # 合同说明: tech_metric suggested = (background, responsibility, action, method, result),
        # 不含 metric. expected (responsibility/action/metric) 中 metric 是 process_metric 专用
        # slot, 不在 tech_metric suggested 中 → unreachable. 不删 expected, 标记"需后续 policy
        # 调整" (建议: 把 metric 加入 tech_metric suggested 末尾, 或显式声明 tech_metric
        # 同时支持 metric 抽取).
        "product_goal": "full_fact_coverage",
        "contract_note": (
            "完整项目事实覆盖目标; metric 不在 tech_metric suggested → unreachable, "
            "不删 expected, 标记需后续 policy 调整 (建议 tech_metric suggested 补 metric)."
        ),
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
        # ---- R6-C.2A: 评测合同标注 ----
        # 产品目标: 完整项目事实覆盖.
        # 合同说明: tech_metric suggested (background, responsibility, action, method, result),
        # method 在 position 3 (>= MAX_TURNS_PER_GAP) → beyond_3; metric 不在 suggested →
        # unreachable. 不删 expected, 标记"需后续 policy 调整" (建议: 扩 MAX_TURNS_PER_GAP,
        # 或把 tech_metric 的 near_limit 触达集合从 {result} 扩到 {method, result}).
        "product_goal": "full_fact_coverage",
        "contract_note": (
            "完整项目事实覆盖目标; method 在 position 3 (beyond) + metric 不在 suggested "
            "(unreachable), 不删 expected, 标记需后续 policy 调整 (建议 near_limit 触达集合 "
            "补 method, 或扩 MAX_TURNS_PER_GAP)."
        ),
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
        # ---- R6-C.2A: 评测合同标注 ----
        # 产品目标: 完整项目事实覆盖. 本 sample 合同已合规, 无 warning.
        # process_metric suggested (responsibility, action, result, metric), expected
        # (responsibility/action/result) 全在 0-2 位置 3 轮内可达.
        "product_goal": "full_fact_coverage",
        "contract_note": (
            "完整项目事实覆盖目标; responsibility/action/result 都在 process_metric "
            "suggested 0-2 位置 3 轮内可达, 无 contract warning, 合同已合规."
        ),
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
        # ---- R6-C.2A: 评测合同标注 ----
        # 产品目标: 完整项目事实覆盖.
        # 合同说明: communication suggested (background, action, method, result), 不含
        # responsibility. expected 含 responsibility → unreachable. 不删 expected, 标记
        # "需后续 policy 调整" (建议: communication suggested 补 responsibility, 或确认
        # responsibility 由 action 的"我负责"前缀兜底).
        "product_goal": "full_fact_coverage",
        "contract_note": (
            "完整项目事实覆盖目标; responsibility 不在 communication suggested → unreachable, "
            "不删 expected, 标记需后续 policy 调整 (建议 communication suggested 补 responsibility)."
        ),
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
        # ---- R6-C.2A: 评测合同标注 ----
        # 产品目标: 完整项目事实覆盖. 本 sample 合同已合规, 无 warning.
        # domain_x suggested (responsibility, action, method, difficulty, result),
        # expected (responsibility/action/result) 都在 0/1/4 位置 (含 near_limit result).
        "product_goal": "full_fact_coverage",
        "contract_note": (
            "完整项目事实覆盖目标; responsibility/action 在 domain_x suggested 0-1 位置 3 轮内 "
            "可达, result 在 near_limit 触达, 无 contract warning, 合同已合规."
        ),
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
        # ---- R6-C.2A: 评测合同标注 ----
        # 产品目标: 完整项目事实覆盖.
        # 合同说明: tech_metric suggested (background, responsibility, action, method, result).
        # method 在 position 3 (beyond) + metric 不在 suggested (unreachable).
        # 不删 expected, 标记"需后续 policy 调整" (同 sim_tech_metric_ecg).
        "product_goal": "full_fact_coverage",
        "contract_note": (
            "完整项目事实覆盖目标; method 在 position 3 (beyond) + metric 不在 suggested "
            "(unreachable), 不删 expected, 标记需后续 policy 调整 (建议 near_limit 触达集合 "
            "补 method, tech_metric suggested 补 metric)."
        ),
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
        # ---- R6-C.2A: 评测合同标注 ----
        # 产品目标: 完整项目事实覆盖. 本 sample 合同已合规, 无 warning.
        # process_metric suggested (responsibility, action, result, metric), expected
        # (responsibility/action/result) 全在 0-2 位置 3 轮内可达.
        "product_goal": "full_fact_coverage",
        "contract_note": (
            "完整项目事实覆盖目标; responsibility/action/result 都在 process_metric "
            "suggested 0-2 位置 3 轮内可达, 无 contract warning, 合同已合规."
        ),
    },
]

# 把两组样本合并, 但用 source 字段区分, 报告里分别聚合
# ======================================================================
# Eval set 3: R6-J boundary + process_metric 兜底样本 (10 条)
# R6-H 决策报告 §7 标记 process_metric 0 轮覆盖, R6-H decision 报告 §6
# 建议扩 eval set 加 LLM 优势场景 (乱答/跨 slot/长上下文/行业 jargon).
# R6-J 目标: 验证 LLM 在 boundary 场景下能否展现增量, 补 process_metric 兜底.
# 5 类各 2 条: chaos / multi_slot / long_context / jargon / process_metric_boost
# 全部 product_goal="full_fact_coverage" (跟 R6-C.2A 兼容, contract_note 标 boundary)
# R6-H spec §6 严格不做清单保持: 不改 prompt / retry / schema / token / PROMPT_VERSIONS
# ======================================================================
EVAL_SET_BOUNDARY: list[dict] = [
    # ===== 类别 1: boundary_chaos 乱答 / 口语化 (2 条) =====
    {
        "name": "boundary_chaos_annotation",
        "source": "boundary_v1",
        "jd_text": (
            "岗位要求: 理解数据标注规范、能制定判断标准、"
            "沉淀样例库, 有大模型评估经验加分。"
        ),
        "role": "data_annot",
        "gap_id": "process_metric",
        "user_messages": [
            "我那年实习, 反正就是, 数据那块儿, 啊具体啥, 嗯我想想, 标了 2000 多条吧, 应该有, 判断标准啥的我整理过",
            "我先把样例看了一遍, 然后跟同组的 3 个人对了下口径, 模糊的地方写了个判断规则",
            "后面组员问得少, 我那些规则成了组内参考",
            "整理成素材",
        ],
        "expected_slots": {
            "responsibility": "数据标注实习",
            "action": ["看样例", "跟同组 3 人对口径", "写判断规则"],
            "result": "组员问得少, 规则成组内参考",
            "metric": ["2000 多条", "3 个人"],
        },
        "expected_draft_has_metrics": True,
        "product_goal": "full_fact_coverage",
        "contract_note": (
            "完整项目事实覆盖目标; boundary 乱答/口语化场景; responsibility/action/result 在 process_metric suggested "
            "0-2 位置 3 轮内可达, metric 在 suggested 末位 3 轮内 near_limit 触达. "
            "预期 LLM 比规则版更能在散句里重组出 structured slot (action 列表)."
        ),
    },
    {
        "name": "boundary_chaos_feedback",
        "source": "boundary_v1",
        "jd_text": (
            "岗位要求: 熟悉深度学习模型训练流程, 能复现论文模型、"
            "对比不同架构效果、用量化指标评估。"
        ),
        "role": "data_annot",
        "gap_id": "tech_metric",
        "user_messages": [
            "我那个项目, 嗯, 怎么说呢, 主要是搞标注的, 对就是, 看样例那种, 跟 3 个人一起, 最后大家口径统一了",
            "我整了 20 多条样例, 比较边界那种, 然后整理成判断标准",
            "后面组员查问题快了一些, 没出过返工",
            "整理成素材",
        ],
        "expected_slots": {
            "responsibility": "看样例 + 整理判断标准",
            "action": ["看样例", "整 20 多条边界样例", "整理成判断标准"],
            "result": "组员查问题快, 没返工",
            "metric": ["20 多条", "3 个人"],
        },
        "expected_draft_has_metrics": True,
        "product_goal": "full_fact_coverage",
        "contract_note": (
            "完整项目事实覆盖目标; boundary 乱答场景; responsibility/action/result 在 tech_metric suggested 0/1/4 "
            "位置, result 在 near_limit 触达, metric 不在 suggested. "
            "预期 LLM 比规则版更能在散句中分清 responsibility 和 action 边界."
        ),
    },
    # ===== 类别 2: boundary_multi_slot 跨 slot 单回答 (2 条) =====
    {
        "name": "boundary_multi_slot_clustering",
        "source": "boundary_v1",
        "jd_text": (
            "岗位要求: 理解数据标注、质量检查和大模型评估流程, "
            "能描述方法和判断标准。"
        ),
        "role": "data_annot",
        "gap_id": "tech_metric",
        "user_messages": [
            "我在文本聚类项目里用了层次聚类 + 人工抽检, 5 个人一起做的, 用了 2 周时间, 最后聚类纯度从 0.6 升到 0.8, 准确率 0.85",
            "我们对比了 K-means 和 层次聚类, 层次聚类在边界 case 上更稳, 抽检准确率更高",
            "最后输出 5 份聚类质量报告, 团队采纳了层次聚类方案",
            "整理成素材",
        ],
        "expected_slots": {
            "responsibility": "文本聚类项目",
            "action": ["对比 K-means 和层次聚类", "人工抽检", "输出 5 份聚类质量报告"],
            "method": "层次聚类 + 人工抽检",
            "result": "团队采纳层次聚类方案",
            "metric": ["5 个人", "2 周", "0.6", "0.8", "0.85", "5 份"],
        },
        "expected_draft_has_metrics": True,
        "product_goal": "full_fact_coverage",
        "contract_note": (
            "完整项目事实覆盖目标; boundary 跨 slot 单回答场景; user_message 1 单条含 responsibility/action/method/"
            "result/metric 5 slot. tech_metric suggested 不含 metric → unreachable, "
            "method 在 position 3 beyond. 预期 LLM 比规则版更能从单回答里抽到多 slot."
        ),
    },
    {
        "name": "boundary_multi_slot_research",
        "source": "boundary_v1",
        "jd_text": (
            "岗位要求: 能跨角色沟通需求, 梳理用户反馈, "
            "推动活动或产品方案落地。"
        ),
        "role": "product",
        "gap_id": "communication",
        "user_messages": [
            "我负责用户调研 + 文档整理, 同时拉了 3 个用户访谈, 整理成需求清单交给开发, 4 周后上线 v1, 解决率 60%",
            "我每天同步一次状态, 把需求按优先级分 3 类, 开发直接看我的分类就能排期",
            "最后产品迭代效率明显提升, 跨角色沟通成本下降",
            "整理成素材",
        ],
        "expected_slots": {
            "responsibility": "用户调研 + 文档整理",
            "action": ["拉 3 个用户访谈", "整理需求清单", "每天同步状态", "按优先级分 3 类"],
            "method": "按优先级分 3 类 + 每天同步",
            "result": "产品迭代效率提升, 跨角色沟通成本下降",
            "metric": ["3 个", "4 周", "60%"],
        },
        "expected_draft_has_metrics": True,
        "product_goal": "full_fact_coverage",
        "contract_note": (
            "完整项目事实覆盖目标; boundary 跨 slot 单回答; user_message 1 含 action+method+result+metric. "
            "communication suggested 不含 responsibility, 含 (background, action, method, result). "
            "预期 LLM 比规则版更能识别 action 列表中的多个动作."
        ),
    },
    # ===== 类别 3: boundary_long_context 长上下文 100+ 字 (2 条) =====
    {
        "name": "boundary_long_context_eval_pipeline",
        "source": "boundary_v1",
        "jd_text": (
            "岗位要求: 能搭建评测流程、跟进问题闭环、"
            "输出可视化报告, 推动模型迭代。"
        ),
        "role": "test_qa",
        "gap_id": "process_metric",
        "user_messages": [
            "我当时在医疗垂类评测项目里负责评测流程搭建, 进来的时候团队没有标准化流程, 我先花 2 周时间梳理了现有标注员的标注准确率, 发现 5 个标注员之间一致性只有 60% 左右, 然后我设计了一个三层质检机制 — 抽样 1%、3%、5% 三档 — 配合标注员互查和专家仲裁, 4 周后一致性提升到 85%, 错误率从 12% 降到 4%, 输出 5 份可视化分析报告",
            "我整理了 30 多条典型 Badcase 样例, 按错误类型和严重度分级, 给标注员做培训材料",
            "最后团队采纳我的流程方案, 成为项目标准",
            "整理成素材",
        ],
        "expected_slots": {
            "responsibility": "医疗垂类评测流程搭建",
            "action": ["设计三层质检机制", "整理 30 多条 Badcase 样例", "做培训材料"],
            "result": "团队采纳流程方案成为项目标准",
            "metric": ["2 周", "5 个", "60%", "1%", "3%", "5%", "4 周", "85%", "12%", "4%", "5 份", "30 多条"],
        },
        "expected_draft_has_metrics": True,
        "product_goal": "full_fact_coverage",
        "contract_note": (
            "完整项目事实覆盖目标; boundary 长上下文场景; user_message 1 是 200+ 字长段落, 含 11 个量化数字. "
            "process_metric suggested (responsibility, action, result, metric) 3 轮内可达, "
            "但单轮 200 字里 metric 列表很长, 预期 LLM 比规则版更能在长段落里抓齐所有 metric."
        ),
    },
    {
        "name": "boundary_long_context_rubric",
        "source": "boundary_v1",
        "jd_text": (
            "岗位要求: 理解数据标注、质量检查和大模型评估流程, "
            "能描述方法和判断标准。"
        ),
        "role": "data_annot",
        "gap_id": "tech_metric",
        "user_messages": [
            "我参与一个文本分类项目的评估标准设计, 负责从 Badcase 中抽象出可量化的判断维度. 当时团队用 GPT-4 做分类, 但 Badcase 一致性只有 65%, 我花了 3 周时间分析了 500 多条 Badcase, 把判断标准拆成内容安全、格式合规、意图理解、上下文一致性 4 个维度, 每个维度再分 3 档 (高/中/低), 用这个 rubric 跟 3 个标注员对答案, 最终 inter-annotator agreement (Kappa) 达到 0.72, 准确率从 78% 升到 89%, 错判率从 22% 降到 11%",
            "我整理了 50 多条边界样例作为标注员培训材料, 团队采纳了 rubric 方案",
            "最后成了项目标准, 复用到 3 个下游任务",
            "整理成素材",
        ],
        "expected_slots": {
            "responsibility": "文本分类项目评估标准设计",
            "action": ["分析 500 多条 Badcase", "拆成 4 维度 3 档 rubric", "整理 50 多条边界样例"],
            "method": "4 维度 3 档 rubric + 标注员对答案",
            "result": "团队采纳, 复用到 3 个下游任务",
            "metric": ["65%", "3 周", "500 多条", "4", "3", "3", "0.72", "78%", "89%", "22%", "11%", "50 多条", "3 个"],
        },
        "expected_draft_has_metrics": True,
        "product_goal": "full_fact_coverage",
        "contract_note": (
            "完整项目事实覆盖目标; boundary 长上下文场景; user_message 1 是 250+ 字长段落, 含 12 个量化数字. "
            "tech_metric suggested (background, responsibility, action, method, result) 不含 metric. "
            "预期 LLM 比规则版更能在长段落里分离 method 和 action, 并抓齐 metric 列表."
        ),
    },
    # ===== 类别 4: boundary_jargon 行业 jargon (2 条) =====
    {
        "name": "boundary_jargon_llm_sft",
        "source": "boundary_v1",
        "jd_text": (
            "岗位要求: 理解 LLM 评估流程, 能设计评测维度、构建评测集、"
            "输出 Badcase 分析报告。"
        ),
        "role": "data_annot",
        "gap_id": "tech_metric",
        "user_messages": [
            "我做了 few-shot prompt, 然后用 SFT 蒸馏了一个 7B 模型, 接着走 DPO 对齐, 最终 human eval 通过率 92%, eval set 300 条",
            "我对比了 base 模型和蒸馏后模型在 5 个业务场景的效果, 蒸馏模型在长文本上更稳",
            "最后团队采纳蒸馏方案, 部署到生产环境",
            "整理成素材",
        ],
        "expected_slots": {
            "responsibility": "LLM 蒸馏与对齐",
            "action": ["做 few-shot prompt", "SFT 蒸馏 7B 模型", "走 DPO 对齐", "对比 5 个业务场景"],
            "method": "few-shot prompt + SFT 蒸馏 + DPO 对齐",
            "result": "团队采纳蒸馏方案, 部署到生产",
            "metric": ["7B", "92%", "300 条", "5 个"],
        },
        "expected_draft_has_metrics": True,
        "product_goal": "full_fact_coverage",
        "contract_note": (
            "完整项目事实覆盖目标; boundary 行业 jargon 场景; 术语: few-shot / SFT / DPO / human eval. "
            "tech_metric suggested 不含 metric. 预期 LLM 比规则版更能识别 jargon 关键词, "
            "并把 few-shot/SFT/DPO 归到 method 字段."
        ),
    },
    {
        "name": "boundary_jargon_rag",
        "source": "boundary_v1",
        "jd_text": (
            "岗位要求: 能从 Badcase 中抽象可量化指标、"
            "设计评分维度、提出优化方案。"
        ),
        "role": "data_annot",
        "gap_id": "tech_metric",
        "user_messages": [
            "我用 RAG 做检索增强, embedding 走 BGE, top-k 10, 调过 3 轮 recall@5, 最终 0.78, 配合 cross-encoder rerank, 答案准确率 85%",
            "我对比了不用 RAG 的 baseline, RAG 版本 Badcase 率从 35% 降到 15%",
            "最后团队采纳 RAG 方案, 部署到客服系统",
            "整理成素材",
        ],
        "expected_slots": {
            "responsibility": "RAG 检索增强",
            "action": ["调 3 轮 recall@5", "加 cross-encoder rerank", "对比 RAG baseline"],
            "method": "RAG + BGE embedding + top-k 10 + cross-encoder rerank",
            "result": "团队采纳, 部署到客服系统",
            "metric": ["10", "3 轮", "0.78", "85%", "35%", "15%"],
        },
        "expected_draft_has_metrics": True,
        "product_goal": "full_fact_coverage",
        "contract_note": (
            "完整项目事实覆盖目标; boundary 行业 jargon 场景; 术语: RAG / BGE / top-k / recall@5 / cross-encoder rerank. "
            "tech_metric suggested 不含 metric. 预期 LLM 比规则版更能识别 jargon 术语, "
            "并把 BGE/top-k/cross-encoder 归到 method 字段."
        ),
    },
    # ===== 类别 5: process_metric_boost process_metric 兜底 (2 条) =====
    {
        "name": "boundary_process_metric_rubric",
        "source": "boundary_v1",
        "jd_text": (
            "岗位要求: 理解数据标注规范、能制定判断标准、"
            "沉淀样例库, 有大模型评估经验加分。"
        ),
        "role": "data_annot",
        "gap_id": "process_metric",
        "user_messages": [
            "我设计了一个评估 rubric, 跟 3 个标注员对答案, 覆盖 5 个任务类型",
            "rubric 把判断标准拆成 4 个维度, 每个维度 3 档 (高/中/低), 标注员按 rubric 打分",
            "最后 inter-annotator agreement (Kappa) 达到 0.72, 准确率 85%",
            "整理成素材",
        ],
        "expected_slots": {
            "responsibility": "评估 rubric 设计",
            "action": ["设计 rubric", "跟 3 个标注员对答案", "拆 4 维度 3 档"],
            "result": "团队采纳 rubric 方案",
            "metric": ["3 个", "5 个", "4", "3", "0.72", "85%"],
        },
        "expected_draft_has_metrics": True,
        "product_goal": "full_fact_coverage",
        "contract_note": (
            "完整项目事实覆盖目标; process_metric 兜底 (R6-H §7 ⚠️ 盲点); process_metric suggested "
            "(responsibility, action, result, metric) 3 轮内可达, metric 末位 near_limit 触达. "
            "R6-H 0 轮覆盖, R6-J 补 2 条, 验证 LLM 跟 Rules 在 process_metric gap 下的 delta."
        ),
    },
    {
        "name": "boundary_process_metric_checklist",
        "source": "boundary_v1",
        "jd_text": (
            "岗位要求: 参与 AI 产品测试与数据质量评估, "
            "能梳理流程、跟进问题闭环, 有量化意识。"
        ),
        "role": "test_qa",
        "gap_id": "process_metric",
        "user_messages": [
            "我在测试组搞了一个验收 checklist, 10 项验收标准, 每项有明确 pass/fail 规则",
            "checklist 上线后, 漏测率从 30% 降到 8%, 节省回归时间 40%",
            "最后团队采纳 checklist, 复用到 3 个项目的测试流程",
            "整理成素材",
        ],
        "expected_slots": {
            "responsibility": "测试验收 checklist 设计",
            "action": ["设计 10 项 checklist", "制定 pass/fail 规则", "复用到 3 个项目"],
            "result": "团队采纳, 复用到 3 个项目",
            "metric": ["10 项", "30%", "8%", "40%", "3 个"],
        },
        "expected_draft_has_metrics": True,
        "product_goal": "full_fact_coverage",
        "contract_note": (
            "完整项目事实覆盖目标; process_metric 兜底 (R6-H §7 ⚠️ 盲点); process_metric suggested "
            "(responsibility, action, result, metric) 3 轮内可达, metric 末位 near_limit 触达. "
            "本条 role=test_qa, 显式 gap_id=process_metric, 绕过后端自动选 gap 路径."
        ),
    },
]

# R6-J: 3 组合并 = 20 条 (3 plan_baseline + 7 simulated_user_v1 + 10 boundary_v1)
EVAL_SET_ALL: list[dict] = EVAL_SET_PLAN_BASELINE + EVAL_SET_SIMULATED + EVAL_SET_BOUNDARY


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
    # R6-C.3 新增(spec: LLM 抽取可观测性 — 只存计数 / 比率, 不含原文)
    slot_source_breakdown: dict[str, int] = field(default_factory=dict)
    """R6-C.3 抽取来源分布: {rules: N, llm: M, mixed: K}
       老路径(llm_enabled=False)只 +rules; LLM 成功 +llm; LLM 失败 fallback 时 +rules。
       仅含整数 / 短字符串("rules" / "llm" / "mixed"), 不含 user_message / draft_card / prompt。
    """
    llm_parse_retry_count: int = 0
    """R6-C.3 累计 JSON parse / schema retry 次数(LLM 网络错不 retry, 不计入)。
       老路径永远 0(不走 LLM); offline 模式 llm 意图也永远 0(LLM 不发网络)。"""
    llm_to_rules_slot_fallback_count: int = 0
    """R6-C.3 累计 LLM 失败 fallback 规则版次数(网络错 + JSON 错 + schema 错 都算)。
       老路径永远 0; offline 模式 llm 意图永远 0(LLM 不发网络)。"""

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
            "slot_source_breakdown": dict(self.slot_source_breakdown),
            "llm_parse_retry_count": self.llm_parse_retry_count,
            "llm_to_rules_slot_fallback_count": self.llm_to_rules_slot_fallback_count,
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

    # R6-C.3: 收集 LLM 抽取可观测性(纯读 session 字段, 不修改)
    # session 字段由 core.interview_agent 在 _do_answer → extract_slots 时写入,
    # 这里只 snapshot 到 EvalRow 供报告聚合
    obs_breakdown = getattr(session, "slot_source_breakdown", {}) or {}
    obs_retry = int(getattr(session, "llm_parse_retry_count", 0) or 0)
    obs_fallback = int(
        getattr(session, "llm_to_rules_slot_fallback_count", 0) or 0
    )
    # defensive copy + 只取已知 key, 防 session 字段污染
    safe_breakdown: dict[str, int] = {}
    if isinstance(obs_breakdown, dict):
        for k in ("rules", "llm", "mixed"):
            v = obs_breakdown.get(k, 0)
            if isinstance(v, int) and not isinstance(v, bool):
                safe_breakdown[k] = v

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
        slot_source_breakdown=safe_breakdown,
        llm_parse_retry_count=obs_retry,
        llm_to_rules_slot_fallback_count=obs_fallback,
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
            # R6-C.3: LLM 抽取可观测性聚合
            "slot_source_breakdown_total": {"rules": 0, "llm": 0, "mixed": 0},
            "llm_parse_retry_count_total": 0,
            "llm_to_rules_slot_fallback_count_total": 0,
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

    # R6-C.3: LLM 抽取可观测性聚合(只加整数 / 短字符串, 不加原文)
    slot_source_total: dict[str, int] = {"rules": 0, "llm": 0, "mixed": 0}
    llm_retry_total = 0
    llm_fallback_total = 0
    for r in all_rows:
        for k in ("rules", "llm", "mixed"):
            slot_source_total[k] += int(r.slot_source_breakdown.get(k, 0) or 0)
        llm_retry_total += int(r.llm_parse_retry_count or 0)
        llm_fallback_total += int(r.llm_to_rules_slot_fallback_count or 0)

    by_source: dict[str, dict] = {}
    for r in all_rows:
        bucket = by_source.setdefault(
            r.source,
            {
                "total": 0, "schema_pass": 0, "fallback": 0,
                "completeness_sum": 0.0, "fabric_viol": 0,
                "latencies": [], "low_sum": 0, "meta_sum": 0,
                "source_rules": 0, "source_llm": 0, "source_mixed": 0,
                "retry_sum": 0, "fb_sum": 0,
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
        bucket["source_rules"] += int(r.slot_source_breakdown.get("rules", 0) or 0)
        bucket["source_llm"] += int(r.slot_source_breakdown.get("llm", 0) or 0)
        bucket["source_mixed"] += int(r.slot_source_breakdown.get("mixed", 0) or 0)
        bucket["retry_sum"] += int(r.llm_parse_retry_count or 0)
        bucket["fb_sum"] += int(r.llm_to_rules_slot_fallback_count or 0)

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
            "slot_source_breakdown": {
                "rules": b["source_rules"],
                "llm": b["source_llm"],
                "mixed": b["source_mixed"],
            },
            "llm_parse_retry_count_total": b["retry_sum"],
            "llm_to_rules_slot_fallback_count_total": b["fb_sum"],
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
                "source_rules": 0, "source_llm": 0, "source_mixed": 0,
                "retry_sum": 0, "fb_sum": 0,
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
        bucket["source_rules"] += int(r.slot_source_breakdown.get("rules", 0) or 0)
        bucket["source_llm"] += int(r.slot_source_breakdown.get("llm", 0) or 0)
        bucket["source_mixed"] += int(r.slot_source_breakdown.get("mixed", 0) or 0)
        bucket["retry_sum"] += int(r.llm_parse_retry_count or 0)
        bucket["fb_sum"] += int(r.llm_to_rules_slot_fallback_count or 0)

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
            "slot_source_breakdown": {
                "rules": b["source_rules"],
                "llm": b["source_llm"],
                "mixed": b["source_mixed"],
            },
            "llm_parse_retry_count_total": b["retry_sum"],
            "llm_to_rules_slot_fallback_count_total": b["fb_sum"],
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
        # R6-C.3: LLM 抽取可观测性聚合
        "slot_source_breakdown_total": slot_source_total,
        "llm_parse_retry_count_total": llm_retry_total,
        "llm_to_rules_slot_fallback_count_total": llm_fallback_total,
    }


# ======================================================================
# 报告生成(隐私边界)
# ======================================================================
def _row_summary_for_report(row: EvalRow) -> str:
    """单条样本摘要: 只含 name/source/slot key/length, 不含原文."""
    keys_str = ", ".join(row.captured_slot_keys) if row.captured_slot_keys else "(空)"
    lens_str = ", ".join(f"{k}={v}" for k, v in row.captured_slot_lengths.items()) or "—"
    # R6-C.3: 加 3 个可观测性指标到每行摘要(只含整数 / 短字符串)
    breakdown = row.slot_source_breakdown or {}
    src_str = "/".join(
        f"{k}={int(breakdown.get(k, 0) or 0)}"
        for k in ("rules", "llm", "mixed")
    )
    return (
        f"`{row.name}` ({row.source}) | role=`{row.role}` gap=`{row.gap_id}` | "
        f"extractor=`{row.extractor_mode}` fb_cat=`{row.fallback_category}` | "
        f"schema_pass={'✅' if row.schema_pass else '❌'} | "
        f"completeness={row.draft_card_completeness:.2f} | "
        f"fabrication={'✅' if row.fabrication_guard else '❌'} | "
        f"latency={row.latency_ms}ms | "
        f"low_conf={row.low_confidence_slot_count}/{row.total_slot_meta_count} | "
        f"src=[{src_str}] retries={row.llm_parse_retry_count} "
        f"fb_to_rules={row.llm_to_rules_slot_fallback_count} | "
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

    # 4.6、Eval contract: product goal (R6-C.2A, round6-c.2a 路线 A 收尾)
    # 列出每条 sample 的 product_goal + contract 决策说明.
    # schema_pass_rate 的变化必须解释为"评测合同变化" — 本表 + 4.5 章节共同支撑.
    lines.append("## 4.6、Eval contract: product goal (R6-C.2A)")
    lines.append("")
    # 去重 sample, 只列每个 sample 一次(compare 模式双组不重复)
    contract_goals: list[dict] = []
    seen_goal_samples: set[str] = set()
    for s in EVAL_SET_ALL:
        if not isinstance(s, dict):
            continue
        name = s.get("name", "")
        if name in seen_goal_samples:
            continue
        seen_goal_samples.add(name)
        goal = str(s.get("product_goal", "") or "")
        note = str(s.get("contract_note", "") or "")
        contract_goals.append({
            "name": name,
            "source": str(s.get("source", "") or ""),
            "gap_id": str(s.get("gap_id", "") or ""),
            "product_goal": goal,
            "contract_note": note,
        })
    # 3 轮内合同已合规的样本数(无 warning)
    goal_no_warning_count = sum(
        1 for g in contract_goals
        if not any(w["name"] == g["name"] for w in contract_warnings)
    )
    goal_with_warning_count = len(contract_goals) - goal_no_warning_count
    lines.append(
        f"本章节记录每条样本的 **产品目标** + expected_slots **合同决策**, 配合 4.5 章节 "
        f"(`Eval contract warnings`) 共同支撑 `schema_pass_rate` 的解读。共 **{len(contract_goals)}** "
        f"条 sample: **{goal_no_warning_count}** 条 3 轮内合同已合规, "
        f"**{goal_with_warning_count}** 条保留 expected 不删, 标记需后续 policy 调整。"
    )
    lines.append("")
    lines.append("| sample | source | gap | product_goal | 合同说明 |")
    lines.append("|---|---|---|---|---|")
    for g in contract_goals:
        lines.append(
            f"| `{g['name']}` | `{g['source']}` | `{g['gap_id']}` | "
            f"`{g['product_goal']}` | {g['contract_note']} |"
        )
    lines.append("")
    # 验收口径说明: schema_pass_rate 变化 = 评测合同变化
    lines.append(
        "> **R6-C.2A 验收口径**: 本轮 (R6-C.2A) 调整了 `communication_club` 的 `expected_slots` "
        "(移除 responsibility / 增加 method, 表达 3 轮内可生成素材目标), 并对其他 simulated 样本 "
        "标注 `product_goal=full_fact_coverage` 但保留 expected 不删 (`sim_communication_volunteer` "
        "/ `sim_tech_metric_medical_eval` / `sim_tech_metric_ecg` / `sim_tech_metric_rubric_design`)。"
        "`schema_pass_rate` 数值变化必须解读为 **评测合同变化** (expected_slots 调整 / product_goal "
        "标记), **不**解读为 LLM 抽取能力提升或下降。若需评估 LLM 真实抽取质量, 应跑 `live` 模式 + "
        "真实 LLM 凭据 + 同一合同下比较 rules vs llm_assisted 双组 delta。"
    )
    lines.append("")

    # 4.7、LLM 抽取可观测性 (R6-C.3, 不泄漏原文 — 只展示计数 / 比率)
    lines.append("## 4.7、LLM 抽取可观测性 (R6-C.3 — slot_source / retries / fallback)")
    lines.append("")
    # 全局聚合 3 指标
    breakdown_total = metrics.get("slot_source_breakdown_total", {}) or {}
    breakdown_rules = int(breakdown_total.get("rules", 0) or 0)
    breakdown_llm = int(breakdown_total.get("llm", 0) or 0)
    breakdown_mixed = int(breakdown_total.get("mixed", 0) or 0)
    breakdown_total_count = breakdown_rules + breakdown_llm + breakdown_mixed
    llm_retries_total = int(metrics.get("llm_parse_retry_count_total", 0) or 0)
    llm_fb_total = int(
        metrics.get("llm_to_rules_slot_fallback_count_total", 0) or 0
    )
    lines.append("| 指标 | 数值 |")
    lines.append("|---|---|")
    lines.append(f"| `slot_source_breakdown.rules` | {breakdown_rules} |")
    lines.append(f"| `slot_source_breakdown.llm` | {breakdown_llm} |")
    lines.append(f"| `slot_source_breakdown.mixed` | {breakdown_mixed} |")
    if breakdown_total_count > 0:
        llm_rate = round(breakdown_llm / breakdown_total_count, 3)
        lines.append(
            f"| `slot_source_breakdown.llm_rate` | {llm_rate} |"
        )
    else:
        lines.append("| `slot_source_breakdown.llm_rate` | (空) |")
    lines.append(f"| `llm_parse_retry_count_total` | {llm_retries_total} |")
    lines.append(f"| `llm_to_rules_slot_fallback_count_total` | {llm_fb_total} |")
    lines.append("")
    # by_source 拆分
    lines.append("按 source 拆分:")
    lines.append("")
    lines.append("| source | rules | llm | mixed | retries | fb_to_rules |")
    lines.append("|---|---|---|---|---|---|")
    for src, b in metrics["by_source"].items():
        s = b.get("slot_source_breakdown", {}) or {}
        lines.append(
            f"| `{src}` | {int(s.get('rules', 0) or 0)} | "
            f"{int(s.get('llm', 0) or 0)} | {int(s.get('mixed', 0) or 0)} | "
            f"{int(b.get('llm_parse_retry_count_total', 0) or 0)} | "
            f"{int(b.get('llm_to_rules_slot_fallback_count_total', 0) or 0)} |"
        )
    lines.append("")
    # by_extractor 拆分(compare 模式有用)
    if metrics.get("by_extractor"):
        lines.append("按 extractor 拆分:")
        lines.append("")
        lines.append("| extractor | rules | llm | mixed | retries | fb_to_rules |")
        lines.append("|---|---|---|---|---|---|")
        for ext, b in metrics["by_extractor"].items():
            s = b.get("slot_source_breakdown", {}) or {}
            lines.append(
                f"| `{ext}` | {int(s.get('rules', 0) or 0)} | "
                f"{int(s.get('llm', 0) or 0)} | {int(s.get('mixed', 0) or 0)} | "
                f"{int(b.get('llm_parse_retry_count_total', 0) or 0)} | "
                f"{int(b.get('llm_to_rules_slot_fallback_count_total', 0) or 0)} |"
            )
        lines.append("")
    # 隐私边界声明(R6-C.3 核心)
    lines.append(
        "> **隐私边界 (R6-C.3)**: 本章节只展示 **slot key** + **整数计数** + **比率**。"
        "**绝不**包含: user_message 原文 / prompt 正文 / LLM raw response / source_span 明文 / "
        "draft_card 原文 / API key / 含敏感 path 的 base_url。"
        "3 个指标口径: `slot_source_breakdown` = 本轮 answer 抽取的来源分布, "
        "rules=走规则版 / llm=LLM 成功 / mixed=混合(罕见); "
        "`llm_parse_retry_count` = 累计 JSON parse / schema retry 次数(网络错不 retry 不计入); "
        "`llm_to_rules_slot_fallback_count` = LLM 失败 fallback 规则版累计次数(网络 + JSON + schema 错都算)。"
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
    lines.append("- LLM 抽取可观测性只含 slot key + 整数计数 + 比率, 不含原文 (R6-C.3 保护)")
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
    # R6-C.2A: schema_pass_rate 变化 = 评测合同变化
    # 当前轮次 (R6-C.2A) 调整了 communication_club 的 expected_slots,
    # 并对其他 simulated 样本标注 product_goal / contract_note.
    # schema_pass_rate 数字变化必须解读为合同变化, 不解读为 LLM 能力变化.
    contract_change_count = sum(
        1 for s in EVAL_SET_ALL
        if isinstance(s, dict) and s.get("product_goal") in {
            "three_turn_friendly", "full_fact_coverage",
        }
    )
    if contract_change_count > 0:
        lines.append(
            f"- **R6-C.2A 合同调整**: 本轮有 **{contract_change_count}** 条样本标注了 "
            f"`product_goal` 字段 (three_turn_friendly / full_fact_coverage), 其中 "
            f"`communication_club` 的 `expected_slots` 已调整 (移除 responsibility, 改为 "
            f"action/method/result, 表达 3 轮内可生成素材目标)。`schema_pass_rate` 数值变化应"
            f"解读为 **评测合同变化**, 不解读为 LLM 抽取能力变化。详见 4.5 (warnings) / 4.6 "
            f"(product goal) 章节。"
        )
    # R6-C.3: 列出 LLM 抽取可观测性指标(让审计一眼看到 offline 模式 LLM 没真跑)
    obs_breakdown = metrics.get("slot_source_breakdown_total", {}) or {}
    obs_rules = int(obs_breakdown.get("rules", 0) or 0)
    obs_llm = int(obs_breakdown.get("llm", 0) or 0)
    obs_retries = int(metrics.get("llm_parse_retry_count_total", 0) or 0)
    obs_fb = int(metrics.get("llm_to_rules_slot_fallback_count_total", 0) or 0)
    if obs_rules or obs_llm or obs_retries or obs_fb:
        lines.append(
            f"- **R6-C.3 LLM 抽取可观测性**: `slot_source_breakdown` = "
            f"rules={obs_rules} / llm={obs_llm} / mixed={int(obs_breakdown.get('mixed', 0) or 0)}; "
            f"`llm_parse_retry_count_total` = {obs_retries}; "
            f"`llm_to_rules_slot_fallback_count_total` = {obs_fb}。"
            f"offline 模式默认 `llm=0 / retries=0 / fb=0`(LLM 不发网络), "
            f"真实 LLM 调用需在 live 模式 + 已配置 LLM 凭据时才会出现 llm>0。"
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
            " live 模式下 llm/compare 需要在环境变量里配置 LLM 凭据。"
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
    # R6-G F-2.3: 错误信息**绝不**含 key 值 / env var 名(R5-D spec §6.4 + R6-F audit §2)
    # 改用 "配置对应环境变量" 通用描述, 不写 env var 名.
    if resolved_mode == MODE_LIVE and args.extractor in (EXTRACTOR_LLM, EXTRACTOR_COMPARE):
        if not llm_enabled:
            print(
                f"[error] --mode live + --extractor {args.extractor} 需要 LLM 已启用, "
                "当前 LLM 未启用; 请改用 --mode auto 或 --mode offline,"
                "或在环境变量里配置 LLM 凭据后手动跑 live 模式。",
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