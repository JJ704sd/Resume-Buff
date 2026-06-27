# R3.5.1 — 阈值调优 confusion matrix 报告 (R3.5.1 (实跑模式, 2026-06-27))
> 评估样本: 8 份 (排除 2 份公告型)
> 阈值: 高>=80 / 中>=60
> 实跑模式: score = match_score(text, role_id_hint, materials)['score']
> 准确率: **100%** (8/8)

## 评估集 label 分布

- 推荐投: 6
- 别投: 1
- 建议补充: 1

## 详细分类

| id | role | true label | score | pred | match | coverage (sk/to/do) | note |
|---|---|---|---|---|---|---|---|
| baiyun_2026_algorithm | algorithm | 推荐投 | 86 | 高 | ✅ | 1.0/1.0/0.5 | AI 推断: 最高分 100 (role=algorithm). coverage: skills=100%, tools=100%, domains=100% |
| baiyun_2026_fullstack | general | 推荐投 | 100 | 高 | ✅ | 1.0/1.0/1.0 | AI 推断: 最高分 100 (role=general). coverage: skills=100%, tools=100%, domains=100%.  |
| baiyun_2026_product | product | 别投 | 33 | 低 | ✅ | 1.0/1.0/0.0 | user 复核 (2026-06-27 第三次, 3 次 label 变更): R3.5+ (b) 加 PM 维度 surface (物流/工业工程/原型/流程 |
| baiyun_2026_qa | test_qa | 推荐投 | 100 | 高 | ✅ | 1.0/1.0/1.0 | user 复核 (AI 推断 '别投', 复核改 '推荐投'): JD 明写 '至少掌握 Python 或 Typescript', 用户有 Python, m |
| deepseek_2026_agi_match | algorithm | 推荐投 | 80 | 高 | ✅ | 0.8/1.0/1.0 | AI 推断: 最高分 80 (role=algorithm). coverage: skills=80%, tools=100%, domains=100%.  |
| deepseek_2026_data_label | data_annot | 推荐投 | 83 | 高 | ✅ | 0.8/1.0/1.0 | AI 推断: 最高分 83 (role=data_annot). coverage: skills=83%, tools=100%, domains=100%. |
| alibaba_2026_data_eng | data_annot | 建议补充 | 67 | 中 | ✅ | 0.7/1.0/1.0 | AI 推断: 最高分 67 (role=data_annot). coverage: skills=67%, tools=100%, domains=100%. |
| bytedance_2026_qa | test_qa | 推荐投 | 100 | 高 | ✅ | 1.0/1.0/1.0 | AI 推断: 最高分 100 (role=test_qa). coverage: skills=100%, tools=100%, domains=100%.  |

## Confusion Matrix

| true \ pred | 高 | 中 | 低 |
|---|---|---|---|
| 推荐投 | 6 | 0 | 0 |
| 建议补充 | 0 | 1 | 0 |
| 别投 | 0 | 0 | 1 |

## 结论

- 当前阈值 **80/60 准确率 100%** ≥ 85%, 保留

## R3.5.1 vs R3.5 差异说明

- R3.5 报告读 frozen top_score (R3.5 时 AI 推断 score 写死), 不会随 match_score 改动更新
- R3.5.1 改为实跑 match_score, 反映当前 match_score 实现 + 真实素材库状态
- frozen 字段 (top_score / top_role / top_coverage / all_role_scores) 仍保留在 jd_samples.json 作为历史 snapshot, 不删除以保留 R3.5 时点的 ground truth
- baiyun_2026_product 修后 score=33 ('低') vs ground truth '中', 根因 user 素材库缺 PM 经验, 待 user 补 PM 素材 (R3.5+ (b) commit ed57e25)
