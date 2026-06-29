# AI 岗位 JD 库 — Prompt A/B 评测报告

> 版本: R5-E Phase 2 (Prompt A/B 评测脚本, 2026-06-29)  
> Eval set: **12 份 JD** (沿用 R5-D eval set)  
> Eval mode: **offline** (requested: `offline`)  
> 评测配置: **enable_function_calling=True + enable_agent_workflow=True** (固定)  
> Prompt versions: **4 个** — v2-baseline, v3-priority, v4-counterexample, v5-minimal  
> runs_per_version: **1**  
> Judge: **off** (model: `(disabled)`)  

## 0、LLM 元信息 (沿用 R5-D Phase 2 格式)

| 字段 | 值 |
|---|---|
| `llm_mode` | `offline` |
| `llm_enabled` | `False` |
| `llm_model` | `gpt-4o-mini` |
| `llm_base_url_host` | `api.openai.com` |

> 隐私边界: 报告不含任何 API key 类凭据; base_url 只展示 host 部分。

## 1、Prompt 版本总览

| key | 定位 | 长度 (字符) |
|---|---|---|
| `v2-baseline` | 当前生产 prompt (R3-P 主体 + evidence 约束), 回归基线字节级锁死 | 1548 |
| `v3-priority` | 优先级铁律版 (P0-P4 显式声明冲突优先级), 测结构化排序对 LLM 稳定性 | 379 |
| `v4-counterexample` | 反例强化版 (v3 + 4 条禁止事项), 压低 preamble / 顺序错位 / 跨 bullet 借事实 | 514 |
| `v5-minimal` | 极简版 (≈5 句话), 测短 prompt 是否比工程化长 prompt 更稳定 | 167 |

> 注: 报告**不展示** prompt 正文, 长度仅作版本量级参考。

## 2、By Version 指标表

| Version | N | schema_pass_rate | fallback_rate | avg_latency_ms | p95_latency_ms | max_latency_ms | avg_rewrite_changed_rate | avg_len_after | tier_required_hit_rate | pii_safe_rate | judge_qs_avg | hallucination_rate | tier_hit_rate(j) | judge_err |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `v2-baseline` | 12 | 100.0% | 0.0% | 5 | 6 | 6 | 0.0% | 44.1 | 0.0% | 100.0% | — | — | — | 0 |
| `v3-priority` | 12 | 100.0% | 0.0% | 5 | 6 | 6 | 0.0% | 44.1 | 0.0% | 100.0% | — | — | — | 0 |
| `v4-counterexample` | 12 | 100.0% | 0.0% | 5 | 6 | 6 | 0.0% | 44.1 | 0.0% | 100.0% | — | — | — | 0 |
| `v5-minimal` | 12 | 100.0% | 0.0% | 5 | 6 | 6 | 0.0% | 44.1 | 0.0% | 100.0% | — | — | — | 0 |

> 注: `tier_required_hit_rate` 当前占位 0.0, 需 R5-F embedding RAG 接入 tier_required 评估  
> 注: offline 模式 (LLM 未启用) 时 `avg_rewrite_changed_rate` 接近 0, 走原文 fallback  
> 注: judge 列(`judge_qs_avg` / `hallucination_rate` / `tier_hit_rate(j)` / `judge_err`) 默认 `--judge off` 时显示 `—`; live + judge=on 才会有数字 (R5-E Phase 3)  

## 3、By JD 摘要

总样本: 12 JD × 4 versions × 1 runs = **48 条记录**

| jd_id | role | version | schema_pass | fallback_cat | latency_ms | rewrite_rate |
|---|---|---|---|---|---|---|
| `baiyun_2026_algorithm` | `algorithm` | `v2-baseline` | ✅ | `llm_disabled_fallback` | 5 | 0/11 (0%) |
| `baiyun_2026_algorithm` | `algorithm` | `v3-priority` | ✅ | `llm_disabled_fallback` | 4 | 0/11 (0%) |
| `baiyun_2026_algorithm` | `algorithm` | `v4-counterexample` | ✅ | `llm_disabled_fallback` | 5 | 0/11 (0%) |
| `baiyun_2026_algorithm` | `algorithm` | `v5-minimal` | ✅ | `llm_disabled_fallback` | 5 | 0/11 (0%) |
| `baiyun_2026_fullstack` | `general` | `v2-baseline` | ✅ | `llm_disabled_fallback` | 6 | 0/18 (0%) |
| `baiyun_2026_fullstack` | `general` | `v3-priority` | ✅ | `llm_disabled_fallback` | 5 | 0/18 (0%) |
| `baiyun_2026_fullstack` | `general` | `v4-counterexample` | ✅ | `llm_disabled_fallback` | 5 | 0/18 (0%) |
| `baiyun_2026_fullstack` | `general` | `v5-minimal` | ✅ | `llm_disabled_fallback` | 6 | 0/18 (0%) |
| `baiyun_2026_product` | `product` | `v2-baseline` | ✅ | `llm_disabled_fallback` | 5 | 0/12 (0%) |
| `baiyun_2026_product` | `product` | `v3-priority` | ✅ | `llm_disabled_fallback` | 6 | 0/12 (0%) |
| `baiyun_2026_product` | `product` | `v4-counterexample` | ✅ | `llm_disabled_fallback` | 5 | 0/12 (0%) |
| `baiyun_2026_product` | `product` | `v5-minimal` | ✅ | `llm_disabled_fallback` | 4 | 0/12 (0%) |
| `baiyun_2026_qa` | `test_qa` | `v2-baseline` | ✅ | `llm_disabled_fallback` | 5 | 0/15 (0%) |
| `baiyun_2026_qa` | `test_qa` | `v3-priority` | ✅ | `llm_disabled_fallback` | 5 | 0/15 (0%) |
| `baiyun_2026_qa` | `test_qa` | `v4-counterexample` | ✅ | `llm_disabled_fallback` | 4 | 0/15 (0%) |
| `baiyun_2026_qa` | `test_qa` | `v5-minimal` | ✅ | `llm_disabled_fallback` | 5 | 0/15 (0%) |
| `deepseek_2026_agi_match` | `algorithm` | `v2-baseline` | ✅ | `llm_disabled_fallback` | 5 | 0/11 (0%) |
| `deepseek_2026_agi_match` | `algorithm` | `v3-priority` | ✅ | `llm_disabled_fallback` | 6 | 0/11 (0%) |
| `deepseek_2026_agi_match` | `algorithm` | `v4-counterexample` | ✅ | `llm_disabled_fallback` | 5 | 0/11 (0%) |
| `deepseek_2026_agi_match` | `algorithm` | `v5-minimal` | ✅ | `llm_disabled_fallback` | 5 | 0/11 (0%) |
| `deepseek_2026_data_label` | `data_annot` | `v2-baseline` | ✅ | `llm_disabled_fallback` | 4 | 0/8 (0%) |
| `deepseek_2026_data_label` | `data_annot` | `v3-priority` | ✅ | `llm_disabled_fallback` | 5 | 0/8 (0%) |
| `deepseek_2026_data_label` | `data_annot` | `v4-counterexample` | ✅ | `llm_disabled_fallback` | 6 | 0/8 (0%) |
| `deepseek_2026_data_label` | `data_annot` | `v5-minimal` | ✅ | `llm_disabled_fallback` | 5 | 0/8 (0%) |
| `alibaba_2026_data_eng` | `data_annot` | `v2-baseline` | ✅ | `llm_disabled_fallback` | 4 | 0/8 (0%) |
| `alibaba_2026_data_eng` | `data_annot` | `v3-priority` | ✅ | `llm_disabled_fallback` | 6 | 0/8 (0%) |
| `alibaba_2026_data_eng` | `data_annot` | `v4-counterexample` | ✅ | `llm_disabled_fallback` | 5 | 0/8 (0%) |
| `alibaba_2026_data_eng` | `data_annot` | `v5-minimal` | ✅ | `llm_disabled_fallback` | 5 | 0/8 (0%) |
| `bytedance_2026_qa` | `test_qa` | `v2-baseline` | ✅ | `llm_disabled_fallback` | 4 | 0/15 (0%) |
| `bytedance_2026_qa` | `test_qa` | `v3-priority` | ✅ | `llm_disabled_fallback` | 4 | 0/15 (0%) |
| `bytedance_2026_qa` | `test_qa` | `v4-counterexample` | ✅ | `llm_disabled_fallback` | 6 | 0/15 (0%) |
| `bytedance_2026_qa` | `test_qa` | `v5-minimal` | ✅ | `llm_disabled_fallback` | 4 | 0/15 (0%) |
| `JD-B014` | `algorithm` | `v2-baseline` | ✅ | `llm_disabled_fallback` | 4 | 0/11 (0%) |
| `JD-B014` | `algorithm` | `v3-priority` | ✅ | `llm_disabled_fallback` | 5 | 0/11 (0%) |
| `JD-B014` | `algorithm` | `v4-counterexample` | ✅ | `llm_disabled_fallback` | 4 | 0/11 (0%) |
| `JD-B014` | `algorithm` | `v5-minimal` | ✅ | `llm_disabled_fallback` | 5 | 0/11 (0%) |
| `JD-B015` | `test_qa` | `v2-baseline` | ✅ | `llm_disabled_fallback` | 5 | 0/15 (0%) |
| `JD-B015` | `test_qa` | `v3-priority` | ✅ | `llm_disabled_fallback` | 5 | 0/15 (0%) |
| `JD-B015` | `test_qa` | `v4-counterexample` | ✅ | `llm_disabled_fallback` | 5 | 0/15 (0%) |
| `JD-B015` | `test_qa` | `v5-minimal` | ✅ | `llm_disabled_fallback` | 5 | 0/15 (0%) |
| `JD-A011` | `data_annot` | `v2-baseline` | ✅ | `llm_disabled_fallback` | 4 | 0/8 (0%) |
| `JD-A011` | `data_annot` | `v3-priority` | ✅ | `llm_disabled_fallback` | 5 | 0/8 (0%) |
| `JD-A011` | `data_annot` | `v4-counterexample` | ✅ | `llm_disabled_fallback` | 5 | 0/8 (0%) |
| `JD-A011` | `data_annot` | `v5-minimal` | ✅ | `llm_disabled_fallback` | 5 | 0/8 (0%) |
| `JD-BY003` | `product` | `v2-baseline` | ✅ | `llm_disabled_fallback` | 5 | 0/12 (0%) |
| `JD-BY003` | `product` | `v3-priority` | ✅ | `llm_disabled_fallback` | 5 | 0/12 (0%) |
| `JD-BY003` | `product` | `v4-counterexample` | ✅ | `llm_disabled_fallback` | 5 | 0/12 (0%) |
| `JD-BY003` | `product` | `v5-minimal` | ✅ | `llm_disabled_fallback` | 5 | 0/12 (0%) |

## 4、fallback taxonomy 摘要

| 类别 | 计数 |
|---|---|
| `none` | 0 |
| `llm_disabled_fallback` | 48 |
| `tool_error_fallback` | 0 |
| `schema_retry_fallback` | 0 |
| `workflow_abort_fallback` | 0 |

> offline 模式: `llm_disabled_fallback` 应占大多数, 因 LLM 关闭时 FC/AW 走原文  
> live 模式: `none` 占多数, `tool_error_fallback` / `schema_retry_fallback` 反映 prompt 稳定性差异  

## 5、Judge 摘要 (R5-E Phase 3)

> Judge 默认关闭 (`--judge off`), 本节无数据。  
> 手动跑 `--judge on` 时: live 模式 + LLM 已启用才会真正发起 judge HTTP 调用; offline 模式 judge 强制 disabled (避免误发 HTTP)。  

## 6、Winner 建议

> offline 模式: 报告不产生 winner 建议 — offline 路径下所有 prompt 走原文 fallback, 真实 prompt 差异需在 live 模式 + judge 开启时观察。  

## 7、隐私检查

- **数据源**: 仅读 `backend/data/materials.json` (公开脱敏版), 不读 private 备份  
- **报告输出字段**: prompt_version / jd_id / role_id / N / schema_pass_rate / fallback_rate / latency_ms (avg / p95 / max) / rewrite_impact / pii_safe_rate / fallback_category / judge_quality_score_avg / hallucination_rate / tier_required_hit_rate(j) / judge_error_count (R5-E Phase 3)  
- **不含**: 完整 prompt 正文 / JD 全文 / bullet 原文 / 改写后 bullet 原文 / **LLM response 原文** / **API key** / **judge reasoning / chain-of-thought**  
- **PII 模式扫描**: 11 位手机号 / email 模式 / 国内常见学校关键词, 全报告递归扫描结果见下方  
  - 报告主体自检: ✅ pass  

## 8、与既有脚本的关系

- `scripts/evaluate_agent_workflow.py`: 评测 FC × AW 4 组开关, 跟本脚本独立  
- `scripts/replay_agent_trace.py`: 单 request_id trace 回放, 跟本脚本独立  
- 本脚本: 评测同一 workflow (FC=T, AW=T) 下不同 prompt_version 的稳定性 / 延迟 / 降级率  
- **不挂 pre-push hook** (spec §12 #3 已明确默认手动脚本)  
- **不修改** `evaluate_agent_workflow.py` / `match_score` / `llm_rewriter` / `agent_workflow`  

