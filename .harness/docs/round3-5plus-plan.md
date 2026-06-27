# Round 3.5+ — 修 match_score 漏匹配 bug

> 父 ROADMAP: `.harness/docs/ROADMAP.md` 1. P1 段 "R3.5+ — 修 match_score 漏匹配 bug"
> Round 标签: `fix(round3.5+): match_score 漏匹配 bug`
> 工作量: 小 (预计 ~50 行核心改动 + 2 个回归测试)

---

## 0. 背景 (为什么开这一轮)

R3.5 阈值调优(commit `24dfcc5`)时跑 10 份 ground truth,发现 2 份 baiyun JD 触发 `match_score` 漏匹配(score=0),用户复核 label 后实际期望:

| JD id | role_id_hint | 当前 top_score | 用户复核 label | 期望 |
|---|---|---|---|---|
| `baiyun_2026_product` | product | **0** | "建议补充" | 应 > 0 (用户有 AI/LLM/Python 经验) |
| `baiyun_2026_qa` | test_qa | **0** | "推荐投" | 应 > 0 (用户有 Python 经验) |

详见 `简历帮知识库/jd_samples.json` `samples[*].label_note`。

---

## 1. 根因(已确认)

`backend/core/jd_parser.py::match_score` 调用 `_build_candidate_pool(role_skill_keys, materials)`:

```python
def _build_candidate_pool(role_skill_keys: list[str], materials: dict) -> set[str]:
    pool: set[str] = set()
    skills = materials.get("skills", {})
    for sk in role_skill_keys:                     # ← 只查 role 的 skill_keys
        items = skills.get(sk, []) or []
        for item in items:
            item_lower = item.lower()
            for group_keywords in KEYWORD_GROUPS.values():
                for surface, normalized, _w in group_keywords:
                    if surface.lower() in item_lower:   # ← 在 item 字符串里查 surface
                        pool.add(normalized)
    return pool
```

**问题链:**
1. `role='product'` → `role_skill_keys=['产品规划', '需求分析', ...]`(product role 的 skill group 名)
2. 用户的 `materials["skills"]` 在这些 group 下的 items 字符串里**不包含** "Python" / "LLM" / "AI" 等 surface 字面
3. pool 为空 → `parse_jd` 识别到的所有 JD 关键词都算 missing → `score=0`
4. 但用户**确实**有 Python/LLM 经验(在 `tech_metric` / `algorithm` role 下的 items 里)
5. `coverage` 算的是 JD 要求 vs 用户**当前 role 可提供**的关键词 — 这个语义没问题
6. `score` 跟 `coverage` 一样,只看 role 范围 — 这就**误判**了 false negative

**核心矛盾:** "用户能提供什么" 不等于 "用户在当前 role 下展示什么"。`coverage` 用前者语义合理,但 `score` 也用前者就把"跨方向经验"完全无视了,导致 false negative。

---

## 2. 修法(本 round 范围)

### 2.1 核心改动: `_build_candidate_pool` 引入 "全素材库扫描" 选项

```python
def _build_candidate_pool(
    role_skill_keys: list[str],
    materials: dict,
    *,
    include_borrowed: bool = True,   # 新参数
) -> set[str]:
    """
    构造"用户可提供关键词池":
      1. role 范围(强匹配):role_skill_keys 对应 items 里 surface 命中
      2. 全素材库扫描(borrowed):materials["skills"] 所有 items 里 surface 命中
         — include_borrowed=True 时合并到 pool
    """
    pool: set[str] = set()
    skills = materials.get("skills", {})

    # 1) role 范围 — 强匹配(原有逻辑)
    for sk in role_skill_keys:
        items = skills.get(sk, []) or []
        _scan_items_into_pool(items, pool)

    # 2) borrowed 范围 — 新增
    if include_borrowed:
        borrowed_items: list[str] = []
        for sk, items in skills.items():
            if sk in role_skill_keys:
                continue   # 跳过 role 范围(已加)
            for item in items or []:
                borrowed_items.append(item)
        _scan_items_into_pool(borrowed_items, pool)

    return pool
```

抽出小工具函数 `_scan_items_into_pool(items, pool)` 减少重复。

### 2.2 `match_score` 透传参数

```python
def match_score(
    text: str,
    target_role: str,
    materials: dict | None = None,
    *,
    include_borrowed: bool = True,   # 新参数,默认 True(修 bug)
) -> dict[str, Any]:
    ...
    pool = _build_candidate_pool(
        role_cfg["skill_keys"], mats,
        include_borrowed=include_borrowed,
    )
    ...
```

**为什么默认 True:** 本轮就是修 false negative,默认开;调用方如需"严格 role 区分度"可显式传 False。

### 2.3 coverage / score 算式:不变

- `coverage[group]` 仍按 role 范围算(保持"用户在当前 role 展示什么"的语义)
- `score` 改用**新 pool**(role + borrowed),反映"用户真实可提供"
- `matched_keywords` 包含 borrowed 命中
- `missing_keywords` 不变(只看 JD 要求 vs role 范围)

### 2.4 suggestions:不区分 borrowed

MVP 简化:`suggestions` 不区分"用户在当前 role 下能补"还是"借用其他 role 经验"。后续 round 再加 "borrowed" 标记。

---

## 3. 验收点(本 round Deliverables)

### 3.1 核心改动

- [ ] `backend/core/jd_parser.py`:
  - `_build_candidate_pool` 加 `include_borrowed` 参数 + 实现
  - `match_score` 透传该参数
  - 函数 docstring 中文说明业务语义
  - **签名/默认值/调用点** 三处保持一致

### 3.2 回归测试(`backend/tests/test_jd_parser.py` 追加,2 个)

- [ ] `TestMatchScoreBugfix::test_baiyun_product_should_not_be_zero`
  - 输入:`baiyun_2026_product` 的 text + `role='product'` + 真实 `materials.json`
  - 断言:`score > 0`
  - 提示:`parse_jd` 至少识别出 AI/LLM/Python 中一个,pool 现在包含 borrowed 命中

- [ ] `TestMatchScoreBugfix::test_baiyun_qa_should_not_be_zero`
  - 输入:`baiyun_2026_qa` 的 text + `role='test_qa'` + 真实 `materials.json`
  - 断言:`score > 0`
  - 提示:Python 应在 borrowed pool 中

### 3.3 显式 include_borrowed=False 测试(1 个,防回潮)

- [ ] `TestMatchScoreBugfix::test_include_borrowed_false_keeps_role_strict`
  - 输入:同上 baiyun_product + `include_borrowed=False`
  - 断言:score=0(验证参数生效,旧行为可恢复)

### 3.4 全量绿

- [ ] `cd backend && D:\python3.11\python.exe -m pytest tests/ -v` — 124 + 3 = **127 个全绿**
  - 注意:之前的 2 个 `match_score 漏匹配 bug` skip 标记可以**保留**(语义是"未修前 false negative",修了之后应该 un-xfail;但 R3.5.5 不改 test_threshold_tuning.py 里的 skip 注释,只让本轮新测试 + 原 124 都绿)

### 3.5 跑 match_golden_targets.py 复验

- [ ] 跑 `scripts/match_golden_targets.py` 重新生成 `AI岗位JD库_v4_黄金标的match报告.md`
  - 3 份黄金 JD (JD-B010 字节 / JD-D007 DeepSeek / JD-A012 阿里) × 6 role = 18 次匹配
  - 确认分数变化合理(borrowed 命中会让分数略升或保持)
- [ ] 跑 `scripts/score_thresholds.py` 重新生成阈值调优报告
  - 8 份 eval 样本(排除 2 份公告型)中,`baiyun_2026_product` / `baiyun_2026_qa` 不再 score=0

---

## 4. 不在范围(避免 scope 蔓延)

- ❌ 不改 KEYWORD_GROUPS 字典
- ❌ 不改 _classify_recommendation 阈值(80/60 锁死)
- ❌ 不改 coverage 算法(role 范围不变)
- ❌ 不改 suggestions 逻辑
- ❌ 不改 API 层(`api/jd.py` 不暴露 include_borrowed 参数,MVP 内部默认)
- ❌ 不改 R3-G worktree(cherry-pick 是另一轮)
- ❌ 不动 jd_samples.json(label / top_score 是历史 snapshot,改 round 后用脚本重新跑)

---

## 5. 风险与回滚

- **风险:** 默认 include_borrowed=True 会改变 match_score 的默认行为,可能影响 R3.5.5 之前的 124 个测试结果
  - **缓解:** 全量 127 跑通,如果有原测试 fail,优先保原行为(改默认 False),通过脚本调用方显式传 True
- **回滚:** git revert 本 round commit 即可

---

## 6. 文档同步(orchestrator 收尾做)

- [ ] `README.md` 顶部"当前能力"表 — 不需要改(match_score 行为变化对用户透明)
- [ ] `AGENTS.md` 测试数:`124` → `127`(+3 个 R3.5+ bugfix 测试)
- [ ] `AI岗位JD库_v4_黄金标的match报告.md` — 重新生成(自动)
- [ ] `AI岗位JD库_v4_intern_阈值调优报告.md` — 重新生成(自动)
- [ ] `.harness/docs/ROADMAP.md` — 把 R3.5+ entry 移到顶部"快照"段,标完成
- [ ] `.harness/memory/MEMORY.md` — 加 R3.5+ 里程碑条目

---

## 7. commit message 模板

```
fix(round3.5+): match_score 漏匹配 bug — borrowed pool

问题:
- baiyun_2026_product / baiyun_2026_qa 在 match_score 时 score=0
- 根因:_build_candidate_pool 只查 role_skill_keys 对应 items
  字符串里的 surface 命中,role 范围外的用户经验不计入 pool
  → false negative

修法:
- _build_candidate_pool 加 include_borrowed=True 参数(默认开)
- 池 = role 范围(强) + 全素材库扫描(borrowed)
- match_score 透传参数;coverage 仍按 role 范围,sscore 反映真实能力

回归测试:
- 2 个 +TestMatchScoreBugfix 验证 score>0 (baiyun_product / baiyun_qa)
- 1 个 +TestMatchScoreBugfix 验证 include_borrowed=False 时旧行为保留

测试:
- D:\python3.11\python.exe -m pytest tests/ -v → 127 全绿
```

---

_最后更新: 2026-06-27 orchestrator 创建_
