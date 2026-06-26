# R3.5 Phase 3 — 阈值调优 confusion matrix 报告
> 评估样本: 8 份 (排除 2 份公告型)
> 阈值: 高>=80 / 中>=60
> 准确率: **75%** (6/8)

## 评估集 label 分布

- 推荐投: 6
- 建议补充: 2

## 详细分类

| id | true label | score | pred | match | note |
|---|---|---|---|---|---|
| baiyun_2026_algorithm | 推荐投 | 100 | 高 | ✅ | AI 推断: 最高分 100 (role=algorithm). coverage: skills=100%, tools=100%, domains=100% |
| baiyun_2026_fullstack | 推荐投 | 100 | 高 | ✅ | AI 推断: 最高分 100 (role=general). coverage: skills=100%, tools=100%, domains=100%.  |
| baiyun_2026_product | 建议补充 | 0 | 低 | ❌ | user 复核 (AI 推断 '别投', 复核改 '建议补充'): AI/LLM/Prompt/Python 命中, 缺物流/工业工程/原型工具 (Proces |
| baiyun_2026_qa | 推荐投 | 0 | 低 | ❌ | user 复核 (AI 推断 '别投', 复核改 '推荐投'): JD 明写 '至少掌握 Python 或 Typescript', 用户有 Python, m |
| deepseek_2026_agi_match | 推荐投 | 80 | 高 | ✅ | AI 推断: 最高分 80 (role=algorithm). coverage: skills=80%, tools=100%, domains=100%.  |
| deepseek_2026_data_label | 推荐投 | 83 | 高 | ✅ | AI 推断: 最高分 83 (role=data_annot). coverage: skills=83%, tools=100%, domains=100%. |
| alibaba_2026_data_eng | 建议补充 | 67 | 中 | ✅ | AI 推断: 最高分 67 (role=data_annot). coverage: skills=67%, tools=100%, domains=100%. |
| bytedance_2026_qa | 推荐投 | 100 | 高 | ✅ | AI 推断: 最高分 100 (role=test_qa). coverage: skills=100%, tools=100%, domains=100%.  |

## Confusion Matrix

| true \ pred | 高 | 中 | 低 |
|---|---|---|---|
| 推荐投 | 5 | 0 | 1 |
| 建议补充 | 0 | 1 | 1 |
| 别投 | 0 | 0 | 0 |

## 结论

- 当前阈值 **80/60 准确率 75%** < 85%, **需要进一步分析**
- false negative 都是 match_score 漏匹配 (score=0 但 label=推荐投/建议补充), 不是阈值问题
- 见下方 match_score 漏匹配清单

### match_score 漏匹配清单 (R3.5.5 候选修)

- `baiyun_2026_product` (true=建议补充, score=0, pred=低)
- `baiyun_2026_qa` (true=推荐投, score=0, pred=低)
