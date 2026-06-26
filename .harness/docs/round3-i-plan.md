# Round 3-I — JD-driven generation 设计文档

> **目标**:让评分卡算出的"准"真正落到生成结果上。当前 `match_score` 返回 0-100 + 命中关键词,但**没传给 generator**,项目顺序、highlight 顺序、skill 顺序全是 `ROLE_CONFIG` 写死的偏好,JD 完全不参与排序。本 round 把 JD 上下文真正接入生成链路。

---

## 1. 范围(Scope)

### ✅ 做
1. **新 `core/jd_ranker.py`** — 纯规则排序,项目 / highlight / skill group 按 JD 命中数倒序
2. **`core/generator.py:build_sections()` 加可选 `jd_context` 参数** — 不传时行为完全等同于现在(向后兼容)
3. **`core/llm_rewriter.py` prompt 增强** — 把 `matched_keywords` + `missing_keywords` 显式注入 system prompt,让 LLM 改写方向聚焦 JD 实际关心的词
4. **API**:`POST /api/resume/preview` / `generate` 加可选 `jd_text` 字段(空 = 走原路径)
5. **前端**:`App.vue` preview 页加"按 JD 排序"角标 — 每 section 显示"命中 N 关键词"小标,可关
6. **`tests/test_generator_jd_aware.py`** — 新文件,~10-12 用例

### ❌ 不做
- 不裁剪项目/技能(只排序,不去除)
- 不改 `ROLE_CONFIG`
- 不动 LLM 4 道防线降级逻辑
- 不引入新依赖
- 不做"重排序后预测分"字段(可作 P2)
- 不改 `app.py` 路由挂载或 `main.py` 入口

---

## 2. 关键技术决策

### 2.1 jd_context 是可选参数,所有改动向后兼容
- `build_sections(target_role, intention, custom_project_ids, *, jd_context=None)` — 默认 None
- `preview_resume(...)` / `generate_resume_docx(...)` 透传 `jd_text` 参数
- `parse_jd(jd_text)` 在 `jd_text` 非空时调用,空时跳过
- **不传 JD 时,字节级输出与 main 完全一致** — 这是验收硬指标

### 2.2 排序用规则化,不用 LLM 决定顺序
- 排序依据:**项目/highlight/skill 命中 JD 关键词的数量**
- 命中数相同 → 维持原顺序(stable sort,确定性)
- 不引入额外 LLM 调用(已有改写路径足够)
- **确定性是验收硬指标** — 同 JD 多次生成顺序必须一致

### 2.3 排序实现
**项目排序** (`_rank_projects`):
- 拿每个项目的 `highlights[*]` 字符串,在 `parsed['raw_keywords']` 里查命中数
- 命中数倒序;命中数相同 → 按 `ROLE_CONFIG[role]['preferred_project_ids']` 原顺序

**Highlight 排序** (`_rank_highlights`):
- 每条 highlight 单独算 JD 命中数
- 命中数倒序;相同 → 原顺序
- **不裁剪**,只重排

**Skill group 排序** (`_rank_skill_groups`):
- role 的 `skill_keys` 列表里,每个 group 计算"该 group 下的 skills 命中 JD 关键词数"
- 命中数倒序;相同 → 原顺序

### 2.4 LLM prompt 增强
当前 system prompt:
> "你是简历润色专家,根据目标岗位改写项目亮点。**只**调整措辞/顺序/重点强调..."

增强后(user message 加 jd_focus 段):
```json
{
  "target_role": "tech_metric",
  "jd_context": "...",
  "bullets": [...],
  "jd_focus": {
    "matched": ["Python", "PyTorch", "LLM"],   // JD 已命中,改写时保持术语
    "missing": ["Transformer", "CNN"],         // JD 关注但没命中,改写时尝试靠拢
    "tier_required": ["Python", "PyTorch"],   // 必选,不能少
    "tier_preferred": ["评测", "Prompt"]       // 加分,可选
  }
}
```

约束(在 prompt 里写明):
- **不要**为凑 missing 关键词而编造事实(改写层硬规则)
- matched 关键词在改写后必须仍能识别
- 命中数 +1 / -1 都不影响 bullet 长度(保持 20-50 字)

### 2.5 排序 = 排序,不裁剪
- 即便某项目 JD 命中 0,仍然显示(只是排到最后)
- 即便某 skill group 命中 0,仍然显示(只是排到最后)
- 这保证向后兼容 + 排错风险可回退

---

## 3. API 改动

### 3.1 `POST /api/resume/preview`
```python
class PreviewRequest(BaseModel):
    target_role: str
    intention: str | None = None
    custom_project_ids: list[str] | None = None
    template: str = "classic"
    jd_text: str | None = None  # NEW: 可选 JD 上下文
```

### 3.2 `POST /api/resume/generate`
同上,加 `jd_text: str | None = None`。

### 3.3 `GET /api/resume/roles`
不变。

### 3.4 行为
- `jd_text` 为 None / 空字符串 → 完全走原路径(等同于 main 行为)
- `jd_text` 非空 → 走排序路径
- 422 错误:`jd_text` 长度 > 50_000 → 422(同 jd.py 的 `_MAX_TEXT_LEN`)

---

## 4. 前端改动 (`App.vue`)

### 4.1 新增 toggle
- 在 stage 1 选岗位卡片下,加一行:`按 JD 智能排序` checkbox(默认 unchecked,unchecked 时 jd_text 不传)
- 复选框未勾时,即使粘贴了 JD 文本,也不传 jd_text
- 复选框勾上时,要求 jdText 非空(否则 warning)

### 4.2 Preview 角标
- 在每 section 标题旁加小角标(只有 jdContext 存在时才显示):
  - `project_group` 段:每项目显示"命中 X 关键词"(取自项目 highlights 总命中数)
  - `skills` 段:每 group 显示"命中 X 关键词"
- 角标样式:小 chip,跟 `kw-chip` 一致

### 4.3 不改
- 三段式流程不变
- 现有评分卡不变(JD 评分照旧显示)
- 不改 5 模板切换

---

## 5. 测试计划

### 5.1 新文件 `tests/test_generator_jd_aware.py`

```
TestJdRankerProjects:
  test_rank_projects_by_match_count_desc          # 项目按命中数倒序
  test_rank_projects_tie_breaks_to_original_order  # 命中数相同维持原顺序
  test_rank_projects_zero_match_still_included     # 0 命中也保留
  test_rank_projects_deterministic                 # 多次调用结果一致
  test_rank_projects_empty_jd_returns_original     # 空 JD 走原顺序

TestJdRankerHighlights:
  test_rank_highlights_within_project              # 项目内 highlight 排序
  test_rank_highlights_no_truncation               # 不裁剪

TestJdRankerSkillGroups:
  test_rank_skill_groups_by_match                  # skill group 排序
  test_rank_skill_groups_empty_role_keys            # 边界

TestBackwardCompat:
  test_preview_no_jd_byte_identical_to_main        # 不传 jd_text → 输出 hash 完全一致(用 snapshot)
  test_generate_no_jd_byte_identical_to_main       # 同上,docx 内容一致

TestLdPromptEnhancement:
  test_prompt_contains_matched_keywords            # LLM prompt 含 matched 关键词
  test_prompt_contains_missing_keywords            # 同 missing
  test_prompt_no_hallucination_directive           # 含"不编造事实"指令

TestApiJdText:
  test_preview_with_jd_text_200                    # 200 正常
  test_preview_with_jd_text_too_long_422           # > 50k → 422
  test_generate_with_jd_text_200_blob              # 200 + docx
  test_preview_jd_text_empty_string_falls_back     # 空字符串走原路径
```

总计 ~16 用例,目标 88 + 16 = 104。

### 5.2 不动现有测试
- `tests/test_generator_layouts.py` 16 用例不许动
- `tests/test_jd_parser.py` 53 用例不许动
- `tests/test_api_jd.py` 3 用例不许动
- `tests/test_llm_rewriter.py` 16 用例不许动
- 全部 88 个原测试必须保持绿

### 5.3 Snapshot 测试
- 用 `pytest --snapshot` 不可行(没引入 syrupy),改用 hash:
  - 不传 JD 时跑 `build_sections(target_role='tech_metric')` → 序列化 JSON → sha256
  - 与 main 版本的 hash 对比(可以现在算出来写进测试,作为 baseline)

---

## 6. 验收标准

| 指标 | 通过条件 |
|---|---|
| pytest 全绿 | 88 + 新增 ≥10,总计 ≥98,0 fail |
| vue-tsc | 0 error |
| npm run build | 成功 |
| 字节级向后兼容 | 不传 JD 时,5 模板 × 6 role = 30 组合输出与 main 完全一致(JSON hash + docx hash) |
| 排序确定性 | 同 JD 多次调用,项目顺序完全一致 |
| LLM 路径 | 增强后的 prompt 在 mock 测试里被验证含 matched + missing 关键词 |
| 422 边界 | jd_text > 50_000 字符 → 422 |
| pre-push hook | 端到端跑通,挡 push 仍有效 |

---

## 7. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 排序破坏现有 R3-J 5 模板渲染 | 模板不感知 jd_context,排序在 sections 层完成 |
| LLM prompt 改大 → token 涨 | missing 限 20 字符截断 / matched 限 10 字符,prompt 总长 < 2k 字符 |
| 排序不稳定(同分打乱) | 强制 stable sort(命中数倒序,相同时维持原顺序) |
| snapshot baseline 漂移 | baseline 在测试代码里 hardcode,不依赖 fixtures |
| AGENTS.md / MEMORY.md 还在 main 工作树未提交 | 不影响 R3-I worktree(从 b110b7d HEAD 开新分支),工作树内容不跨 worktree 同步 |

---

## 8. 改动文件清单

| 文件 | 改动类型 | 估计行数 |
|---|---|---|
| `backend/core/jd_ranker.py` | 新建 | ~120 |
| `backend/core/generator.py` | 改 build_sections 签名 + 透传 jd_context | +30 |
| `backend/core/llm_rewriter.py` | 改 _build_request_payload 接受 jd_focus | +25 |
| `backend/api/resume.py` | PreviewRequest / GenerateRequest 加 jd_text 字段 | +5 |
| `backend/tests/test_generator_jd_aware.py` | 新建 | ~250 |
| `frontend/src/App.vue` | 加 checkbox + 角标 + 类型 | +60 |
| `frontend/src/api/index.ts` | Preview/Generate 函数签名加 jd_text | +5 |
| **总** | | **~500 行** |

---

## 9. 不在本轮范围(留作后续 P2)

- "重排序后预测命中率"字段
- LLM 缓存层(同 role+intention+JD 复用)
- 求职信(P1 后备,等明确需求)
- 面试自我介绍
- 简历导出多格式
- 素材库编辑 UI
- .env 自动加载

---

## 10. 时间与节奏

- 实施:1 round(developer,目标 1 session 内完成)
- 验证:1 round(tester,全量 pytest + vue-tsc + build + 向后兼容 hash 对比)
- 收尾:1 commit `feat(round3#i): JD-driven generation` + 1 merge commit
- 预计总耗时:1-2 小时(developer 30-60min, tester 15-30min)
