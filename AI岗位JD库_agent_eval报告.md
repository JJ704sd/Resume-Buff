# AI 岗位 JD 库 — Agent Workflow 离线评测报告

> 版本: R5-A Phase 4 (Agent eval 报告, 2026-06-27)  
> Eval set: **12 份 JD** (jd_samples 8 份 + v4_strong 4 份)  
> LLM 启用: **❌ (fallback)**  
> 阈值: 高 ≥ 80 / 中 ≥ 60 / 低 < 60  
> 四组对照: 4 种 (FC × AW)  

## 一、Eval set 概览

| jd_id | company | role_id | source | expected_label | text 长度 |
|---|---|---|---|---|---|
| `baiyun_2026_algorithm` | 百运网 | `algorithm` | jd_samples | 推荐投 | 320 字符 |
| `baiyun_2026_fullstack` | 百运网 | `general` | jd_samples | 推荐投 | 169 字符 |
| `baiyun_2026_product` | 百运网 | `product` | jd_samples | 别投 | 170 字符 |
| `baiyun_2026_qa` | 百运网 | `test_qa` | jd_samples | 推荐投 | 187 字符 |
| `deepseek_2026_agi_match` | DeepSeek | `algorithm` | jd_samples | 推荐投 | 402 字符 |
| `deepseek_2026_data_label` | DeepSeek | `data_annot` | jd_samples | 推荐投 | 392 字符 |
| `alibaba_2026_data_eng` | 阿里巴巴 | `data_annot` | jd_samples | 建议补充 | 339 字符 |
| `bytedance_2026_qa` | 字节跳动 | `test_qa` | jd_samples | 推荐投 | 345 字符 |
| `JD-B014` | 字节跳动 | `algorithm` | jd_v4_strong | v4_no_ground_truth | 379 字符 |
| `JD-B015` | 字节跳动 | `test_qa` | jd_v4_strong | v4_no_ground_truth | 399 字符 |
| `JD-A011` | 阿里巴巴 | `data_annot` | jd_v4_strong | v4_no_ground_truth | 378 字符 |
| `JD-BY003` | 百运网 | `product` | jd_v4_strong | v4_no_ground_truth | 186 字符 |

> 注: v4_strong 样本无 user 标定的 ground truth label, expected 仅作参考  

## 二、四组开关对照总览

| 组合 | N | schema_pass_rate | fallback_rate | avg_latency_ms | pii_safe_rate | tools_used (top) | fallback_category |
|---|---|---|---|---|---|---|---|
| baseline (FC=F, AW=F) | 12 | 100.0% | 0.0% | 1 | 100.0% | — | none×12 |
| FC only (FC=T, AW=F) | 12 | 100.0% | 0.0% | 1 | 100.0% | n/a (FC enabled, old path)×12 | llm_disabled_fallback×12 |
| AW only (FC=F, AW=T) | 12 | 100.0% | 0.0% | 10 | 100.0% | retrieve_evidence×12 | llm_disabled_fallback×12 |
| FC+AW (FC=T, AW=T) | 12 | 100.0% | 0.0% | 8 | 100.0% | retrieve_evidence×12 | llm_disabled_fallback×12 |

## 三、score / recommendation 一致性(开 FC/AW 不应影响 match_score)

- score 一致: **12 / 12**  
- recommendation 一致: **12 / 12**  

✅ 所有 JD 在 4 组开关下 score 与 recommendation 完全一致 (match_score 纯规则化, 不受 FC / AW 开关影响, 符合预期)

## 四、每个 JD 工具调用摘要

### `baiyun_2026_algorithm` — role=`algorithm`, expected=推荐投, source=jd_samples

| 组合 | request_id (前4字符) | score | recommendation | schema_pass | fallback_category | latency_ms | tools_used |
|---|---|---|---|---|---|---|---|
| baseline (FC=F, AW=F) | `—` | 86 | 高 | ✅ | `none` | 1 | — |
| FC only (FC=T, AW=F) | `—` | 86 | 高 | ✅ | `llm_disabled_fallback` | 2 | n/a (FC enabled, old path) |
| AW only (FC=F, AW=T) | `r2fb` | 86 | 高 | ✅ | `llm_disabled_fallback` | 11 | retrieve_evidence |
| FC+AW (FC=T, AW=T) | `rda3` | 86 | 高 | ✅ | `llm_disabled_fallback` | 9 | retrieve_evidence |

### `baiyun_2026_fullstack` — role=`general`, expected=推荐投, source=jd_samples

| 组合 | request_id (前4字符) | score | recommendation | schema_pass | fallback_category | latency_ms | tools_used |
|---|---|---|---|---|---|---|---|
| baseline (FC=F, AW=F) | `—` | 100 | 高 | ✅ | `none` | 1 | — |
| FC only (FC=T, AW=F) | `—` | 100 | 高 | ✅ | `llm_disabled_fallback` | 0 | n/a (FC enabled, old path) |
| AW only (FC=F, AW=T) | `r487` | 100 | 高 | ✅ | `llm_disabled_fallback` | 12 | retrieve_evidence |
| FC+AW (FC=T, AW=T) | `rd5d` | 100 | 高 | ✅ | `llm_disabled_fallback` | 9 | retrieve_evidence |

### `baiyun_2026_product` — role=`product`, expected=别投, source=jd_samples

| 组合 | request_id (前4字符) | score | recommendation | schema_pass | fallback_category | latency_ms | tools_used |
|---|---|---|---|---|---|---|---|
| baseline (FC=F, AW=F) | `—` | 33 | 低 | ✅ | `none` | 2 | — |
| FC only (FC=T, AW=F) | `—` | 33 | 低 | ✅ | `llm_disabled_fallback` | 1 | n/a (FC enabled, old path) |
| AW only (FC=F, AW=T) | `r870` | 33 | 低 | ✅ | `llm_disabled_fallback` | 12 | retrieve_evidence |
| FC+AW (FC=T, AW=T) | `rf3d` | 33 | 低 | ✅ | `llm_disabled_fallback` | 9 | retrieve_evidence |

### `baiyun_2026_qa` — role=`test_qa`, expected=推荐投, source=jd_samples

| 组合 | request_id (前4字符) | score | recommendation | schema_pass | fallback_category | latency_ms | tools_used |
|---|---|---|---|---|---|---|---|
| baseline (FC=F, AW=F) | `—` | 100 | 高 | ✅ | `none` | 2 | — |
| FC only (FC=T, AW=F) | `—` | 100 | 高 | ✅ | `llm_disabled_fallback` | 0 | n/a (FC enabled, old path) |
| AW only (FC=F, AW=T) | `ra38` | 100 | 高 | ✅ | `llm_disabled_fallback` | 10 | retrieve_evidence |
| FC+AW (FC=T, AW=T) | `rade` | 100 | 高 | ✅ | `llm_disabled_fallback` | 8 | retrieve_evidence |

### `deepseek_2026_agi_match` — role=`algorithm`, expected=推荐投, source=jd_samples

| 组合 | request_id (前4字符) | score | recommendation | schema_pass | fallback_category | latency_ms | tools_used |
|---|---|---|---|---|---|---|---|
| baseline (FC=F, AW=F) | `—` | 80 | 高 | ✅ | `none` | 1 | — |
| FC only (FC=T, AW=F) | `—` | 80 | 高 | ✅ | `llm_disabled_fallback` | 0 | n/a (FC enabled, old path) |
| AW only (FC=F, AW=T) | `r865` | 80 | 高 | ✅ | `llm_disabled_fallback` | 12 | retrieve_evidence |
| FC+AW (FC=T, AW=T) | `r8a9` | 80 | 高 | ✅ | `llm_disabled_fallback` | 9 | retrieve_evidence |

### `deepseek_2026_data_label` — role=`data_annot`, expected=推荐投, source=jd_samples

| 组合 | request_id (前4字符) | score | recommendation | schema_pass | fallback_category | latency_ms | tools_used |
|---|---|---|---|---|---|---|---|
| baseline (FC=F, AW=F) | `—` | 83 | 高 | ✅ | `none` | 2 | — |
| FC only (FC=T, AW=F) | `—` | 83 | 高 | ✅ | `llm_disabled_fallback` | 2 | n/a (FC enabled, old path) |
| AW only (FC=F, AW=T) | `rc55` | 83 | 高 | ✅ | `llm_disabled_fallback` | 11 | retrieve_evidence |
| FC+AW (FC=T, AW=T) | `r359` | 83 | 高 | ✅ | `llm_disabled_fallback` | 8 | retrieve_evidence |

### `alibaba_2026_data_eng` — role=`data_annot`, expected=建议补充, source=jd_samples

| 组合 | request_id (前4字符) | score | recommendation | schema_pass | fallback_category | latency_ms | tools_used |
|---|---|---|---|---|---|---|---|
| baseline (FC=F, AW=F) | `—` | 67 | 中 | ✅ | `none` | 1 | — |
| FC only (FC=T, AW=F) | `—` | 67 | 中 | ✅ | `llm_disabled_fallback` | 1 | n/a (FC enabled, old path) |
| AW only (FC=F, AW=T) | `r86c` | 67 | 中 | ✅ | `llm_disabled_fallback` | 10 | retrieve_evidence |
| FC+AW (FC=T, AW=T) | `raf6` | 67 | 中 | ✅ | `llm_disabled_fallback` | 9 | retrieve_evidence |

### `bytedance_2026_qa` — role=`test_qa`, expected=推荐投, source=jd_samples

| 组合 | request_id (前4字符) | score | recommendation | schema_pass | fallback_category | latency_ms | tools_used |
|---|---|---|---|---|---|---|---|
| baseline (FC=F, AW=F) | `—` | 100 | 高 | ✅ | `none` | 1 | — |
| FC only (FC=T, AW=F) | `—` | 100 | 高 | ✅ | `llm_disabled_fallback` | 1 | n/a (FC enabled, old path) |
| AW only (FC=F, AW=T) | `rd25` | 100 | 高 | ✅ | `llm_disabled_fallback` | 10 | retrieve_evidence |
| FC+AW (FC=T, AW=T) | `rf91` | 100 | 高 | ✅ | `llm_disabled_fallback` | 9 | retrieve_evidence |

### `JD-B014` — role=`algorithm`, expected=v4_no_ground_truth, source=jd_v4_strong

| 组合 | request_id (前4字符) | score | recommendation | schema_pass | fallback_category | latency_ms | tools_used |
|---|---|---|---|---|---|---|---|
| baseline (FC=F, AW=F) | `—` | 100 | 高 | ✅ | `none` | 1 | — |
| FC only (FC=T, AW=F) | `—` | 100 | 高 | ✅ | `llm_disabled_fallback` | 0 | n/a (FC enabled, old path) |
| AW only (FC=F, AW=T) | `r202` | 100 | 高 | ✅ | `llm_disabled_fallback` | 10 | retrieve_evidence |
| FC+AW (FC=T, AW=T) | `r254` | 100 | 高 | ✅ | `llm_disabled_fallback` | 8 | retrieve_evidence |

### `JD-B015` — role=`test_qa`, expected=v4_no_ground_truth, source=jd_v4_strong

| 组合 | request_id (前4字符) | score | recommendation | schema_pass | fallback_category | latency_ms | tools_used |
|---|---|---|---|---|---|---|---|
| baseline (FC=F, AW=F) | `—` | 100 | 高 | ✅ | `none` | 1 | — |
| FC only (FC=T, AW=F) | `—` | 100 | 高 | ✅ | `llm_disabled_fallback` | 1 | n/a (FC enabled, old path) |
| AW only (FC=F, AW=T) | `r82d` | 100 | 高 | ✅ | `llm_disabled_fallback` | 8 | retrieve_evidence |
| FC+AW (FC=T, AW=T) | `r451` | 100 | 高 | ✅ | `llm_disabled_fallback` | 8 | retrieve_evidence |

### `JD-A011` — role=`data_annot`, expected=v4_no_ground_truth, source=jd_v4_strong

| 组合 | request_id (前4字符) | score | recommendation | schema_pass | fallback_category | latency_ms | tools_used |
|---|---|---|---|---|---|---|---|
| baseline (FC=F, AW=F) | `—` | 67 | 中 | ✅ | `none` | 0 | — |
| FC only (FC=T, AW=F) | `—` | 67 | 中 | ✅ | `llm_disabled_fallback` | 0 | n/a (FC enabled, old path) |
| AW only (FC=F, AW=T) | `reb5` | 67 | 中 | ✅ | `llm_disabled_fallback` | 9 | retrieve_evidence |
| FC+AW (FC=T, AW=T) | `r37f` | 67 | 中 | ✅ | `llm_disabled_fallback` | 7 | retrieve_evidence |

### `JD-BY003` — role=`product`, expected=v4_no_ground_truth, source=jd_v4_strong

| 组合 | request_id (前4字符) | score | recommendation | schema_pass | fallback_category | latency_ms | tools_used |
|---|---|---|---|---|---|---|---|
| baseline (FC=F, AW=F) | `—` | 33 | 低 | ✅ | `none` | 1 | — |
| FC only (FC=T, AW=F) | `—` | 33 | 低 | ✅ | `llm_disabled_fallback` | 1 | n/a (FC enabled, old path) |
| AW only (FC=F, AW=T) | `r96e` | 33 | 低 | ✅ | `llm_disabled_fallback` | 9 | retrieve_evidence |
| FC+AW (FC=T, AW=T) | `rb58` | 33 | 低 | ✅ | `llm_disabled_fallback` | 8 | retrieve_evidence |

## 五、失败 case 分析

✅ 本轮无失败 case (无 error_type / schema_pass=False / pii_safe=False)

## 六、隐私检查摘要

- **数据源**: 仅读 `backend/data/materials.json`(公开脱敏版),不读任何 private 备份
- **报告输出字段**: jd_id / role_id / company / title / score / recommendation / schema_pass / fallback_used / fallback_category / tools_used / latency_ms / pii_safe / request_id 短串 (前 4 字符)
- **不含**: 真实姓名 / 手机号 / 邮箱 / 完整学校名 / 完整 JD 全文 / 完整 bullet / **完整 request_id (r + 8 hex)**
- **PII 模式扫描**: 11 位手机号 / email 模式 / 国内常见学校关键词, 全报告递归扫描结果见下方
  - 报告主体自检: ✅ pass

### 6.1 fallback taxonomy 摘要 (R5-C Phase 1)

按 spec §2.2, fallback 类别:

| 类别 | 含义 | 来源 |
|---|---|---|
| `none` | 无 fallback | `agent_summary.fallback_used=False` 且无 error |
| `llm_disabled_fallback` | 无 LLM key, FC/AW 改写走原文 | `is_llm_enabled()==False` 且 FC=T 或 AW=T |
| `tool_error_fallback` | 工具失败, workflow 降级 | `agent_summary.fallback_used=True` + reason 含 `tool_error` |
| `schema_retry_fallback` | LLM schema retry 后仍失败 | `fallback_reason` 含 `schema` |
| `workflow_abort_fallback` | required step 失败 / evaluate_one 抛异常 | `fallback_reason` 含 `required` 或 `evaluate_one.error_type` 非 None |

**全局 fallback_category 分布**:

| 类别 | 计数 |
|---|---|
| `none` | 12 |
| `llm_disabled_fallback` | 36 |
| `tool_error_fallback` | 0 |
| `schema_retry_fallback` | 0 |
| `workflow_abort_fallback` | 0 |

## 七、结论

- **schema pass rate 4 组均 100%** (12 JD × 4 = 48 次 preview 调用全部通过 schema 校验)
- **fallback rate 4 组均 0%** (无意外降级)
- **score 一致性 12/12**: match_score 纯规则化, 4 组开关对 score 无影响, 符合预期
- **recommendation 一致性 12/12**: 4 组开关对 recommendation 无影响
- **AW 开启 vs baseline 平均 latency 差**: +9ms (AW 走完整任务图, baseline 走老路径, 预期有少量 overhead)
- **LLM 启用**: ❌ (无 key, FC / AW 走原文 fallback)  
  - 真实 LLM 场景下 FC+AW 的 latency 会显著高于 fallback (HTTP RTT 决定), 当前评测反映的是离线 fallback 路径的真实表现
- **fallback taxonomy 摘要**: none × 12 / llm_disabled × 36 / tool_error × 0 / schema_retry × 0 / workflow_abort × 0

---

## 八、与既有脚本的关系

- `scripts/score_thresholds.py`: 阈值调优, 单维度 match_score 准确率, 跟本脚本独立
- `scripts/match_golden_targets.py`: 黄金 JD × 6 role 全量扫描, 跟本脚本独立
- `scripts/replay_agent_trace.py`: 单 request_id trace 回放, 跟本脚本独立
- 本脚本: 评测 Agent workflow 4 组开关在固定 eval set 上的稳定性 / 延迟 / 降级率
- **不挂 pre-push hook** (spec §12 #3 已明确默认手动)

