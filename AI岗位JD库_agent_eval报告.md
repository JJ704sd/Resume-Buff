# AI 岗位 JD 库 — Agent Workflow 离线评测报告

> 版本: R5-A Phase 4 (Agent eval 报告, 2026-06-27)  
> Eval set: **12 份 JD** (jd_samples 8 份 + v4_strong 4 份)  
> LLM 启用: **✅**  
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

| 组合 | N | schema_pass_rate | fallback_rate | avg_latency_ms | pii_safe_rate | tools_used (top) |
|---|---|---|---|---|---|---|
| baseline (FC=F, AW=F) | 12 | 100.0% | 0.0% | 62785 | 100.0% | — |
| FC only (FC=T, AW=F) | 12 | 100.0% | 0.0% | 62785 | 100.0% | n/a (FC enabled, old path)×12 |
| AW only (FC=F, AW=T) | 12 | 100.0% | 0.0% | 83143 | 100.0% | parse_jd×12, match_score×12, retrieve_evidence×12 |
| FC+AW (FC=T, AW=T) | 12 | 100.0% | 0.0% | 83134 | 100.0% | parse_jd×12, match_score×12, retrieve_evidence×12 |

## 三、score / recommendation 一致性(开 FC/AW 不应影响 match_score)

- score 一致: **12 / 12**  
- recommendation 一致: **12 / 12**  

✅ 所有 JD 在 4 组开关下 score 与 recommendation 完全一致 (match_score 纯规则化, 不受 FC / AW 开关影响, 符合预期)

## 四、每个 JD 工具调用摘要

### `baiyun_2026_algorithm` — role=`algorithm`, expected=推荐投, source=jd_samples

| 组合 | score | recommendation | schema_pass | fallback | latency_ms | tools_used |
|---|---|---|---|---|---|---|
| baseline (FC=F, AW=F) | 86 | 高 | ✅ | 否 | 61161 | — |
| FC only (FC=T, AW=F) | 86 | 高 | ✅ | 否 | 61105 | n/a (FC enabled, old path) |
| AW only (FC=F, AW=T) | 86 | 高 | ✅ | 否 | 81494 | parse_jd, match_score, retrieve_evidence, rewrite_highlights |
| FC+AW (FC=T, AW=T) | 86 | 高 | ✅ | 否 | 81375 | parse_jd, match_score, retrieve_evidence, evaluate_bullet_jd_match, rewrite_highlights |

### `baiyun_2026_fullstack` — role=`general`, expected=推荐投, source=jd_samples

| 组合 | score | recommendation | schema_pass | fallback | latency_ms | tools_used |
|---|---|---|---|---|---|---|
| baseline (FC=F, AW=F) | 100 | 高 | ✅ | 否 | 81406 | — |
| FC only (FC=T, AW=F) | 100 | 高 | ✅ | 否 | 81407 | n/a (FC enabled, old path) |
| AW only (FC=F, AW=T) | 100 | 高 | ✅ | 否 | 101811 | parse_jd, match_score, retrieve_evidence, rewrite_highlights |
| FC+AW (FC=T, AW=T) | 100 | 高 | ✅ | 否 | 101858 | parse_jd, match_score, retrieve_evidence, evaluate_bullet_jd_match, rewrite_highlights |

### `baiyun_2026_product` — role=`product`, expected=别投, source=jd_samples

| 组合 | score | recommendation | schema_pass | fallback | latency_ms | tools_used |
|---|---|---|---|---|---|---|
| baseline (FC=F, AW=F) | 33 | 低 | ✅ | 否 | 61039 | — |
| FC only (FC=T, AW=F) | 33 | 低 | ✅ | 否 | 61222 | n/a (FC enabled, old path) |
| AW only (FC=F, AW=T) | 33 | 低 | ✅ | 否 | 81410 | parse_jd, match_score, retrieve_evidence, rewrite_highlights |
| FC+AW (FC=T, AW=T) | 33 | 低 | ✅ | 否 | 81490 | parse_jd, match_score, retrieve_evidence, evaluate_bullet_jd_match, rewrite_highlights |

### `baiyun_2026_qa` — role=`test_qa`, expected=推荐投, source=jd_samples

| 组合 | score | recommendation | schema_pass | fallback | latency_ms | tools_used |
|---|---|---|---|---|---|---|
| baseline (FC=F, AW=F) | 100 | 高 | ✅ | 否 | 81394 | — |
| FC only (FC=T, AW=F) | 100 | 高 | ✅ | 否 | 81395 | n/a (FC enabled, old path) |
| AW only (FC=F, AW=T) | 100 | 高 | ✅ | 否 | 101921 | parse_jd, match_score, retrieve_evidence, rewrite_highlights |
| FC+AW (FC=T, AW=T) | 100 | 高 | ✅ | 否 | 101825 | parse_jd, match_score, retrieve_evidence, evaluate_bullet_jd_match, rewrite_highlights |

### `deepseek_2026_agi_match` — role=`algorithm`, expected=推荐投, source=jd_samples

| 组合 | score | recommendation | schema_pass | fallback | latency_ms | tools_used |
|---|---|---|---|---|---|---|
| baseline (FC=F, AW=F) | 80 | 高 | ✅ | 否 | 61079 | — |
| FC only (FC=T, AW=F) | 80 | 高 | ✅ | 否 | 61022 | n/a (FC enabled, old path) |
| AW only (FC=F, AW=T) | 80 | 高 | ✅ | 否 | 81402 | parse_jd, match_score, retrieve_evidence, rewrite_highlights |
| FC+AW (FC=T, AW=T) | 80 | 高 | ✅ | 否 | 81388 | parse_jd, match_score, retrieve_evidence, evaluate_bullet_jd_match, rewrite_highlights |

### `deepseek_2026_data_label` — role=`data_annot`, expected=推荐投, source=jd_samples

| 组合 | score | recommendation | schema_pass | fallback | latency_ms | tools_used |
|---|---|---|---|---|---|---|
| baseline (FC=F, AW=F) | 83 | 高 | ✅ | 否 | 40705 | — |
| FC only (FC=T, AW=F) | 83 | 高 | ✅ | 否 | 40745 | n/a (FC enabled, old path) |
| AW only (FC=F, AW=T) | 83 | 高 | ✅ | 否 | 61123 | parse_jd, match_score, retrieve_evidence, rewrite_highlights |
| FC+AW (FC=T, AW=T) | 83 | 高 | ✅ | 否 | 61068 | parse_jd, match_score, retrieve_evidence, evaluate_bullet_jd_match, rewrite_highlights |

### `alibaba_2026_data_eng` — role=`data_annot`, expected=建议补充, source=jd_samples

| 组合 | score | recommendation | schema_pass | fallback | latency_ms | tools_used |
|---|---|---|---|---|---|---|
| baseline (FC=F, AW=F) | 67 | 中 | ✅ | 否 | 40686 | — |
| FC only (FC=T, AW=F) | 67 | 中 | ✅ | 否 | 40793 | n/a (FC enabled, old path) |
| AW only (FC=F, AW=T) | 67 | 中 | ✅ | 否 | 61076 | parse_jd, match_score, retrieve_evidence, rewrite_highlights |
| FC+AW (FC=T, AW=T) | 67 | 中 | ✅ | 否 | 61140 | parse_jd, match_score, retrieve_evidence, evaluate_bullet_jd_match, rewrite_highlights |

### `bytedance_2026_qa` — role=`test_qa`, expected=推荐投, source=jd_samples

| 组合 | score | recommendation | schema_pass | fallback | latency_ms | tools_used |
|---|---|---|---|---|---|---|
| baseline (FC=F, AW=F) | 100 | 高 | ✅ | 否 | 81509 | — |
| FC only (FC=T, AW=F) | 100 | 高 | ✅ | 否 | 81433 | n/a (FC enabled, old path) |
| AW only (FC=F, AW=T) | 100 | 高 | ✅ | 否 | 101844 | parse_jd, match_score, retrieve_evidence, rewrite_highlights |
| FC+AW (FC=T, AW=T) | 100 | 高 | ✅ | 否 | 101709 | parse_jd, match_score, retrieve_evidence, evaluate_bullet_jd_match, rewrite_highlights |

### `JD-B014` — role=`algorithm`, expected=v4_no_ground_truth, source=jd_v4_strong

| 组合 | score | recommendation | schema_pass | fallback | latency_ms | tools_used |
|---|---|---|---|---|---|---|
| baseline (FC=F, AW=F) | 100 | 高 | ✅ | 否 | 61041 | — |
| FC only (FC=T, AW=F) | 100 | 高 | ✅ | 否 | 61019 | n/a (FC enabled, old path) |
| AW only (FC=F, AW=T) | 100 | 高 | ✅ | 否 | 81405 | parse_jd, match_score, retrieve_evidence, rewrite_highlights |
| FC+AW (FC=T, AW=T) | 100 | 高 | ✅ | 否 | 81455 | parse_jd, match_score, retrieve_evidence, evaluate_bullet_jd_match, rewrite_highlights |

### `JD-B015` — role=`test_qa`, expected=v4_no_ground_truth, source=jd_v4_strong

| 组合 | score | recommendation | schema_pass | fallback | latency_ms | tools_used |
|---|---|---|---|---|---|---|
| baseline (FC=F, AW=F) | 100 | 高 | ✅ | 否 | 81468 | — |
| FC only (FC=T, AW=F) | 100 | 高 | ✅ | 否 | 81416 | n/a (FC enabled, old path) |
| AW only (FC=F, AW=T) | 100 | 高 | ✅ | 否 | 101764 | parse_jd, match_score, retrieve_evidence, rewrite_highlights |
| FC+AW (FC=T, AW=T) | 100 | 高 | ✅ | 否 | 101837 | parse_jd, match_score, retrieve_evidence, evaluate_bullet_jd_match, rewrite_highlights |

### `JD-A011` — role=`data_annot`, expected=v4_no_ground_truth, source=jd_v4_strong

| 组合 | score | recommendation | schema_pass | fallback | latency_ms | tools_used |
|---|---|---|---|---|---|---|
| baseline (FC=F, AW=F) | 67 | 中 | ✅ | 否 | 40712 | — |
| FC only (FC=T, AW=F) | 67 | 中 | ✅ | 否 | 40773 | n/a (FC enabled, old path) |
| AW only (FC=F, AW=T) | 67 | 中 | ✅ | 否 | 60903 | parse_jd, match_score, retrieve_evidence, rewrite_highlights |
| FC+AW (FC=T, AW=T) | 67 | 中 | ✅ | 否 | 61055 | parse_jd, match_score, retrieve_evidence, evaluate_bullet_jd_match, rewrite_highlights |

### `JD-BY003` — role=`product`, expected=v4_no_ground_truth, source=jd_v4_strong

| 组合 | score | recommendation | schema_pass | fallback | latency_ms | tools_used |
|---|---|---|---|---|---|---|
| baseline (FC=F, AW=F) | 33 | 低 | ✅ | 否 | 61222 | — |
| FC only (FC=T, AW=F) | 33 | 低 | ✅ | 否 | 61095 | n/a (FC enabled, old path) |
| AW only (FC=F, AW=T) | 33 | 低 | ✅ | 否 | 81562 | parse_jd, match_score, retrieve_evidence, rewrite_highlights |
| FC+AW (FC=T, AW=T) | 33 | 低 | ✅ | 否 | 81406 | parse_jd, match_score, retrieve_evidence, evaluate_bullet_jd_match, rewrite_highlights |

## 五、失败 case 分析

✅ 本轮无失败 case (无 error_type / schema_pass=False / pii_safe=False)

## 六、隐私检查摘要

- **数据源**: 仅读 `backend/data/materials.json`(公开脱敏版),不读任何 private 备份
- **报告输出字段**: jd_id / role_id / company / title / score / recommendation / schema_pass / fallback_used / tools_used / latency_ms / pii_safe
- **不含**: 真实姓名 / 手机号 / 邮箱 / 完整学校名 / 完整 JD 全文 / 完整 bullet / request_id 全文
- **PII 模式扫描**: 11 位手机号 / email 模式 / 国内常见学校关键词, 全报告递归扫描结果见下方
  - 报告主体自检: ✅ pass

## 七、结论

- **schema pass rate 4 组均 100%** (12 JD × 4 = 48 次 preview 调用全部通过 schema 校验)
- **fallback rate 4 组均 0%** (无意外降级)
- **score 一致性 12/12**: match_score 纯规则化, 4 组开关对 score 无影响, 符合预期
- **recommendation 一致性 12/12**: 4 组开关对 recommendation 无影响
- **AW 开启 vs baseline 平均 latency 差**: +20358ms (AW 走完整任务图, baseline 走老路径, 预期有少量 overhead)
- **LLM 启用**: ✅  

---

## 八、与既有脚本的关系

- `scripts/score_thresholds.py`: 阈值调优, 单维度 match_score 准确率, 跟本脚本独立
- `scripts/match_golden_targets.py`: 黄金 JD × 6 role 全量扫描, 跟本脚本独立
- `scripts/replay_agent_trace.py`: 单 request_id trace 回放, 跟本脚本独立
- 本脚本: 评测 Agent workflow 4 组开关在固定 eval set 上的稳定性 / 延迟 / 降级率
- **不挂 pre-push hook** (spec §12 #3 已明确默认手动)

