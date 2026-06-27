# Round 3-G — 简历上传功能 cherry-pick (功能移植, 不是简单 cherry-pick)

> 父 ROADMAP: `.harness/docs/ROADMAP.md` 1. P1 段 "R3-G — 重启 cherry-pick"
> 启动信号: 2026-06-27 user 明确"启动 R3-G 简历上传功能 cherry-pick"
> Round 标签: `feat(round3#g): resume upload + JD score from external resume`
> 工作量: 中等 (估 1-2 个 round, 主要 3-4 步)

---

## 0. 背景 (为什么开这一轮)

R3-G 是用户 2026-06-26 启动的 round, 但选完 scope 后主动 cancel(担心跟 R3-I "JD-driven generation" 体验冲突)。worker 仍落地完整 MVP(1467 行新增), 按 hygiene 决策保留在 `feat/r3g-resume-upload` 分支(HEAD `eb7e841`)。

**当前判断(2026-06-27 复盘)**: R3-I (生成新简历) 跟 R3-G (诊断现有简历) 是**互补**不重叠的功能, 启动 R3-G 有价值。

eb7e841 base 跟当前 main 脱节 (R3-I 之前的旧 base), 但 R3-G commit 本身只 +1467 / -5 (worker 提前做了"剥离"工作), 实际冲突点小。

---

## 1. 真正要移植的功能

R3-G 那个 commit `eb7e841` 的 1467 行新增拆成 9 个文件:

| 文件 | 改动 | 性质 | 冲突风险 |
|---|---|---|---|
| `backend/core/resume_parser.py` (250) | docx/pdf/txt 字节流 → 段落 list | 新增 | 无 |
| `backend/api/resume.py` (+85) | 加 `/api/resume/parse-external` endpoint | 修改 | 需合并 (R3-A 之后 resume.py 已有 preview/generate, R3-I 加过 jd_text 字段) |
| `backend/api/jd.py` (+12) | `MatchRequest` 加 `external_resume_text` 字段 | 修改 | 低 (只加字段, 不会跟现有 match_score 透传冲突) |
| `backend/core/jd_parser.py` (+94) | 加 `_build_resume_perspective()` 函数 | 修改 | **高** (R3.5+ 加了 borrowed pool + include_borrowed 参数, R3.5+ (b) 加了 PM dimension surface — 需要适配) |
| `frontend/src/components/ResumeUploader.vue` (227) | Element Plus `<el-upload drag>` | 新增 | 无 |
| `frontend/src/App.vue` (+108) | 集成上传面板 | 修改 | 中 (R3-I 改过 App.vue, 有 jdAware 复选框 + preview/generate 流程) |
| `frontend/src/api/index.ts` (+43) | axios 包装 `parseExternal` | 修改 | 低 |
| `backend/tests/test_jd_match_ext.py` (301) | match_score 加权扩展测试 | 新增 | 中 (跟 R3.5+ 的 borrowed pool 测试 + R3.5+ (b) 的 pm_dimensions 测试重叠) |
| `backend/tests/test_parse_external.py` (352) | resume parser 测试 | 新增 | 无 |

---

## 2. 修法 (本 round 实施 spec)

### 2.1 实施分 4 步

**Step 1: 纯新增文件 (零冲突, 优先级高)**
- `git show feat/r3g-resume-upload:backend/core/resume_parser.py > backend/core/resume_parser.py`
- `git show feat/r3g-resume-upload:frontend/src/components/ResumeUploader.vue > frontend/src/components/ResumeUploader.vue`
- `git show feat/r3g-resume-upload:backend/tests/test_parse_external.py > backend/tests/test_parse_external.py`

**Step 2: 适配 jd_parser.py 的 `_build_resume_perspective` 函数 (R3.5+ / R3.5+ (b) 兼容)**
- 提取 eb7e841 那个函数的核心逻辑 (have_keywords / need_keywords 计算)
- 适配到当前 main 的 `match_score()` 内部调用
- **关键适配点**:
  - 当前 main 的 `match_score` 返回里 `matched_keywords` 已经是 borrowed 池命中结果 — `_build_resume_perspective` 不需要再调 `match_score`
  - 当前 main 的 `KEYWORD_GROUPS` 已有 PM 维度 surface (物流/工业工程/原型/流程图) + 'AI' surface — `_build_resume_perspective` 用的 surface 集合应包含这些
- 输出格式: `dict {have_keywords, need_keywords, have_count, need_count}` 或 `None` (没传 external_resume_text)

**Step 3: 适配 API 层**
- `backend/api/jd.py`: `MatchRequest` 加 `external_resume_text: str | None = None` 字段
- `backend/api/jd.py`: `jd_match()` 透传 `external_resume_text` 给 `match_score`
- `backend/api/resume.py`: 加 `parse_external` endpoint (跟 eb7e841 一样, 但适配 R3-A 后的 resume.py 结构)
- `backend/core/jd_parser.py::match_score`: 加 `external_resume_text: str | None = None` 参数, 调 `_build_resume_perspective` 加进 return dict 的 `resume_perspective` 字段

**Step 4: 前端集成**
- `frontend/src/api/index.ts`: 加 `parseExternal(file: File)` API 包装
- `frontend/src/App.vue`: 在"选岗位"和"粘贴 JD"中间加 "或上传简历 (.docx/.pdf/.txt)" 按钮
  - 上传成功后, 把全文文本填到 `externalResumeText` ref
  - 算分时调 `jdApi.match(text, role, externalResumeText)`
  - 前端展示 `match_result.resume_perspective` (have_keywords / need_keywords)

---

## 3. 验收点 (Deliverables)

### 3.1 后端核心

- [ ] `backend/core/resume_parser.py` - 移植 R3-G 250 行 (纯新增)
- [ ] `backend/core/jd_parser.py` - 加 `_build_resume_perspective` 函数 + `match_score` 透传 `external_resume_text`
  - 函数签名: `match_score(text, target_role, materials=None, include_borrowed=True, external_resume_text=None)`
  - 返回 dict 加 `resume_perspective: dict | None` 字段 (跟 eb7e841 一致)
- [ ] `backend/api/jd.py` - `MatchRequest` 加 `external_resume_text` 字段
- [ ] `backend/api/resume.py` - 加 `/api/resume/parse-external` endpoint
- [ ] 启动 main.py, 冒烟测试:
  - `curl -X POST http://127.0.0.1:8000/api/jd/match -F "text=..." -F "target_role=tech_metric" -F "external_resume_text=..."` → 返回 `resume_perspective` 字段
  - `curl -X POST http://127.0.0.1:8000/api/resume/parse-external -F "file=@test.docx"` → 返回 `paragraphs` 列表

### 3.2 前端

- [ ] `frontend/src/components/ResumeUploader.vue` - 移植 R3-G 227 行 (纯新增)
- [ ] `frontend/src/api/index.ts` - 加 `parseExternal` 包装
- [ ] `frontend/src/App.vue` - 集成上传面板, 上传后填到 `externalResumeText` ref, 算分时透传
- [ ] 前端构建: `cd frontend && npx vue-tsc --noEmit` 0 error + `npm run build` 成功
- [ ] 手测: 启动 dev server, 选 role + 上传简历 + 粘贴 JD → 算分 → 看到 `resume_perspective` 列表

### 3.3 回归测试

- [ ] 移植 `test_parse_external.py` (R3-G 352 行) - docx/pdf/txt 三种格式测试
- [ ] 移植 `test_jd_match_ext.py` (R3-G 301 行) - 但需要适配 R3.5+ 的 borrowed pool 行为 (可能只取 1-2 个核心 case, 避免重复)
- [ ] 跑全量 pytest: 期望 **137 + N passed, 0 skipped** (N = 新增测试数, 估 6-10 个)
- [ ] 跑 match_golden_targets + score_thresholds 复验: 黄金标的分数不变 (R3-G 不影响 match_score 核心算法)

### 3.4 文档同步 (orchestrator 收尾做)

- [ ] `README.md` 当前能力表加 R3-G 行
- [ ] `AGENTS.md` 测试数更新
- [ ] `ROADMAP.md` R3-G entry 移到顶部"快照"段
- [ ] `MEMORY.md` 加 R3-G 里程碑条目

---

## 4. 不在范围 (避免 scope 蔓延)

- ❌ 不改 KEYWORD_GROUPS 字典 (R3.5+ / R3.5+ (b) 已加 'AI' + PM 维度)
- ❌ 不改 match_score 核心算法 (只加 external_resume_text 透传)
- ❌ 不改 _classify_recommendation 阈值 (80/60 锁死)
- ❌ 不改 score_thresholds.py (R3.5.1 实跑模式锁死)
- ❌ 不改 materials.json (user 私有数据)
- ❌ 不删 test_jd_match_ext.py (即便部分测试跟 R3.5+ 重叠, 保留作为补充)

---

## 5. 风险与回滚

- **风险 1**: R3-G worktree eb7e841 base 跟当前 main 差异大, 直接 `git cherry-pick eb7e841` 可能大面积冲突
  - **缓解**: 不走 cherry-pick, 走"功能移植"路径 — 用 `git show <commit>:<file> > <file>` 提取纯新增文件, 手动合并修改文件
- **风险 2**: `_build_resume_perspective` 跟 R3.5+ borrowed pool + R3.5+ (b) PM dimension 不兼容
  - **缓解**: 重新实现 (不复用 R3-G 的 94 行), 基于当前 main 的 `matched_keywords` 计算 have_keywords, 基于 `parsed` + `KEYWORD_GROUPS` 计算 need_keywords (用 _suggest_group_for_missing_keyword 思路)
- **回滚**: 4 步独立 commit, 任一 commit 出问题可独立 revert

---

## 6. commit 计划 (估 4 个 commit)

```
feat(round3#g): resume_parser + ResumeUploader + parse-external endpoint (Step 1+3 部分)
- backend/core/resume_parser.py (新增 250 行)
- frontend/src/components/ResumeUploader.vue (新增 227 行)
- backend/api/resume.py (加 parse-external endpoint)
- backend/api/jd.py (MatchRequest 加 external_resume_text 字段)
- backend/tests/test_parse_external.py (新增 352 行)

feat(round3#g): match_score 透传 external_resume_text + resume_perspective 字段 (Step 2+3)
- backend/core/jd_parser.py::match_score 加 external_resume_text 参数
- _build_resume_perspective 函数 (适配 R3.5+ borrowed pool + R3.5+ (b) PM 维度)
- 返回 dict 加 resume_perspective 字段

feat(round3#g): App.vue 集成上传面板 + 透传 external_resume_text (Step 4)
- frontend/src/App.vue (+100 行)
- frontend/src/api/index.ts (+30 行)
- 完整端到端: 选 role → 上传简历 → 粘贴 JD → 算分 → 看到 resume_perspective

docs(round3#g): sync ROADMAP + AGENTS + README + MEMORY to R3-G closeout
```

---

## 7. 完成判据

- [ ] 用户能上传 .docx/.pdf/.txt 简历, 后端解析不报错
- [ ] 用户粘贴 JD + 上传简历 → 算分 → 看到 score + resume_perspective (have_keywords / need_keywords)
- [ ] 没上传简历时, `resume_perspective` 字段为 None (或省略), 不影响原有 score_thresholds 8/8 = 100% 准确率
- [ ] 全量 pytest 137 + N (估 6-10) passed, 0 skipped
- [ ] 跑 match_golden_targets + score_thresholds 复验: 黄金标的分数不变, 8/8 准确率不变

---

## 8. 启动

本 round 由 orchestrator 拆 4 步实施, 每步独立 commit, 不派给 developer (单点改动 + 功能移植, 自己做更直接)。

---

_最后更新: 2026-06-27 orchestrator 创建_
