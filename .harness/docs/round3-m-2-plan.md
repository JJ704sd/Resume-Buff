# R3-M.2 — 8 套模板细节打磨 + 可读性优化(Plan)

> 状态: ✅ 完成 (2026-06-27) — 5 个 commit (`7541810` ~ `6390403`),213 passed,0 skipped
> 上游: R3-M.1 MVP 已收尾(commit `b521092` + `e6eb820`,190 passed)
> 落地: 5 个可读性参数 + academic 专属 renderer + 23 个新 pytest(原计划 30,合并 TestHierarchyInvariants 到 TestHeadingHierarchy,覆盖不变)
> 拆分背景: R3-M "简历排版改进" 拆 3 个 round 推进,本轮 = 中期方向 1 + 3
> 拆分原则:
> - **方向 1**(模板视觉差异化):academic 加专属 renderer(简化 highlights + 教育背景前置)
> - **方向 3**(可读性优化):标题层级 / 段间距 / 字号比例参数化 + 8 套 config 微调
> - **不包含**:bilingual 双语 renderer(留 R3-M.3 方向 6);用户可定制排版面板(留 R3-M.3)

## 现状盘点

### 8 套 LAYOUT_CONFIG(R3-M.1 后)
| ID | name | 差异化 config | renderer |
|---|---|---|---|
| `classic` | 经典 | font=10.5/line=1.3/margin=(1.8,1.8,2.0,2.0)/color=True/header=center/shaded=False/marker="" | `_render_classic` |
| `single_column` | 单栏紧凑 | font=10.0/line=1.15/margin=(1.5,1.5,1.8,1.8) | `_render_classic` 别名 |
| `two_column` | 双栏 | font=10.5/line=1.25/margin=(1.8,1.8,2.0,2.0)/two_column=True | `_render_two_column`(结构差异) |
| `minimal` | 极简 | font=10.5/line=1.3/color=False/header=center | `_render_classic` 别名 |
| `technical` | 技术感 | font=10.5/line=1.3/shaded=True/marker="■ "/header=left | `_render_classic` 别名 |
| `academic` | 学术 CV | font=11.0/line=1.5/margin=(2.5,2.5,2.5,2.5)/header=center/academic_mode=True | **`_render_classic`**(MVP 占位,flag 未生效) |
| `internet` | 互联网简洁 | font=10.0/line=1.2/margin=(1.5,1.5,1.5,1.5)/marker="▸ "/header=left | `_render_classic` |
| `bilingual` | 中英双语 | font=10.5/line=1.3/margin=(2.0,2.0,2.0,2.0)/bilingual_mode=True | **`_render_classic`**(MVP 占位,flag 未生效) |

### 关键痛点(可读性)
- **`_add_h1` 字号硬编码 12pt**:不能按模板比例缩放(academic 12 偏小,bilingual 12 偏大)
- **`_add_h2` 字号 = font_size_body**:跟正文同字号,层次扁平
- **`_add_meta_line` 字号硬编码 9pt**:小到边缘(academic 11pt body 时 9pt meta 太小)
- **段间距硬编码**:`_add_h1` space_before=8 / after=4;`_add_h2` before=4 / after=2;`_add_meta_line` after=2;bullet 没设 after
- **8 套模板视觉差异主要靠 config**:font / margin / line_spacing / color / header_align / shaded / marker / two_column,这些已差异化,但**字号比例 + 段间距比例没差异化**,academic 和 internet 在层次感上几乎一样
- **academic_mode / bilingual_mode flag 完全 dead code**:没在 renderer 里判断

## 目标

1. **8 套模板细节打磨**(可读性方向)
   - 标题层级参数化:H1 / H2 / meta 字号比例 + 加粗策略
   - 段间距参数化:section_spacing / item_spacing / meta_spacing
   - bullet 段间距统一
2. **academic 加专属 renderer**(差异化方向)
   - 项目 highlights 简化(去掉项目名 + role 行,直接 bullet 列)
   - 教育背景前置(教育 → 项目 顺序)
3. **~30 个新 pytest**:段间距 baseline + 字号比例 + academic 专属行为 + 8 套可读性
4. **测试数 190 → 220+,0 skipped**

## 范围

### 1. generator.py 改动

#### 1.1 LAYOUT_CONFIG 加 4 个可读性参数(8 套全部更新)

每个 config 加:
- `h1_size_ratio`:H1 字号 = body * h1_size_ratio(默认 1.20,academic 1.15,bilingual 1.18)
- `h2_size_ratio`:H2 字号 = body * h2_size_ratio(默认 1.05,internet 1.0)
- `section_spacing_pt`:H1 段前后距(默认 before=8/after=4,academic 10/5,internet 6/3)
- `meta_spacing_pt`:meta 行段后距(默认 2,academic 3)
- `item_spacing_pt`:bullet 段后距(默认 0,bilingual 2)

#### 1.2 helper 函数改造

- `_add_h1`:字号从 `layout_cfg["h1_size_ratio"] * font_size_body` 算,space_before/after 用 `section_spacing_pt`
- `_add_h2`:字号从 `layout_cfg["h2_size_ratio"] * font_size_body` 算,space_before/after 用 `section_spacing_pt / 2`
- `_add_meta_line`:字号 = font_size_body * 0.88(默认 9.24 ≈ 9),space_after 用 `meta_spacing_pt`
- `_add_bullet`:加 `space_after = Pt(item_spacing_pt)`,line_spacing 沿用 layout_cfg.line_spacing
- `_add_shaded_highlight`:同上
- `_add_skill_line`:加 `space_after = Pt(item_spacing_pt)`

#### 1.3 academic 专属 renderer

- 新增 `_render_academic(doc, sections, role_cfg, layout_cfg)`
- 关键差异:
  1. **教育背景前置**:build_sections 输出顺序固定(目前 education → projects → skills → honors → self_eval),academic 模式下需要在 renderer 里把 education 提到 project_group 之前(注意:build_sections 已经把 education 放第一位,只需要在 renderer 里把 project_group 和 education 调换顺序)
  2. **项目 highlights 简化**:`_render_project_group_to` 加 `academic_mode` 判断,academic 模式下:
     - 不渲染 H2 "项目名 | role" 行(直接进 highlights)
     - 不渲染 meta line(时间 / 周期)
     - 不渲染 summary(学术 CV 不需要)
     - 直接列 highlights 为 bullets
  3. **header 字号略大**:academic 模板 header 字号 22 → 24(已在 helper 里改)
- `_LAYOUT_DISPATCH["academic"] = _render_academic`

#### 1.4 bilingual 模板 — 只做可读性参数化,不做双语(留给 R3-M.3)

`bilingual_mode` flag 保留 dead code(注释保留),本轮不做双语实现。R3-M.3 时再激活。

### 2. 测试改动

#### 2.1 新增 pytest 测试类(~30 个 case)

| 测试类 | case 数 | 验证内容 |
|---|---|---|
| `TestHeadingHierarchy` | 6 | 8 套模板 H1 > H2 > body 字号比例正确(参数化 + 模板差异化断言) |
| `TestSectionSpacing` | 4 | 段间距 baseline + 8 套模板段间距差异化(before/after Pt) |
| `TestBulletSpacing` | 3 | bullet 段间距统一 + 跟 item_spacing_pt 联动 |
| `TestAcademicRenderer` | 5 | academic 简化 highlights(无 project name H2 + 无 meta line + 无 summary)+ education 在 project_group 前 |
| `TestReadabilityAcrossLayouts` | 4 | 8 套模板扫一遍生成 docx 有效 + 字号 ≥ 9pt + 段间距 ≥ 0 + 行距在 [1.15, 1.5] |
| `TestHierarchyInvariants` | 3 | 8 套模板 H1 字号永远 > H2 字号 > body 字号(防 regression) |
| `TestLayoutConfigSchema` | 5 | 8 套模板 LAYOUT_CONFIG 必含新参数(h1_size_ratio / h2_size_ratio / section_spacing_pt / meta_spacing_pt / item_spacing_pt),缺一即 fail |

合计 ~30 个 case

#### 2.2 现有测试调整

- `test_internet_smaller_font_size` / `test_academic_larger_font_size` 沿用,不动
- `test_internet_has_skill_marker` / `test_bilingual_default_margins` 沿用,不动
- `test_layout_generates_valid_docx`(参数化遍历 LAYOUT_CONFIG.keys())自动覆盖 academic 新 renderer

### 3. 文档改动

- `AGENTS.md` 测试数 190 → 220+
- `README.md` 当前能力表加 R3-M.2 落地说明
- `.harness/docs/ROADMAP.md` R3-M.2 → ✅ 完成(快照移到顶部)
- 本文件 `.harness/docs/round3-m-2-plan.md` 已存在,完成时由 orchestrator 改 status

## 工作量

- 后端代码: ~250 行(helper 改造 ~80 + academic renderer ~50 + config 精修 ~50 + 测试 ~120)
- pytest 增量: ~30 个 case,代码量 ~150 行
- 文档: ~30 行
- **总计: ~430 行**(略低于 ROADMAP 估算 500,bilingual 留给 R3-M.3)

## 实施步骤(每步独立 commit)

1. **Step 1**:helper 函数加可读性参数 + 8 套 config 精修(无新行为)
   - 文件: `backend/core/generator.py`
   - 测试: `tests/test_generator_layouts.py` 加 `TestLayoutConfigSchema`(5 个 case 锁死 schema)
   - 跑全量 pytest 验证绿(190 + 5 = 195)
2. **Step 2**:标题层级 + 段间距参数化生效
   - 文件: `backend/core/generator.py`(_add_h1 / _add_h2 / _add_meta_line / _add_bullet / _add_skill_line 改造)
   - 测试: 加 `TestHeadingHierarchy`(6) + `TestSectionSpacing`(4) + `TestBulletSpacing`(3) + `TestHierarchyInvariants`(3)
   - 跑全量 pytest 验证绿(195 + 16 = 211)
3. **Step 3**:academic 专属 renderer
   - 文件: `backend/core/generator.py` 加 `_render_academic` + `_dispatch_section` 加 academic_mode 路径 + `_LAYOUT_DISPATCH` 替换
   - 测试: 加 `TestAcademicRenderer`(5 个 case)
   - 跑全量 pytest 验证绿(211 + 5 = 216)
4. **Step 4**:可读性扫描 + 收尾
   - 文件: 加 `TestReadabilityAcrossLayouts`(4 个 case)扫 8 套模板字号 + 段间距 + 行距合理性
   - 测试: 216 + 4 = 220
5. **Step 5**:文档同步(AGENTS.md 测试数 + README 当前能力表)
   - 单独 commit `docs(round3-m.2): ...`

## 验收标准

- pytest 190 → 220+ passed,0 skipped
- `cd frontend && npx vue-tsc --noEmit` 0 error(本轮无前端改动,作为回归保护)
- `cd frontend && npm run build` 成功(同上)
- 8 套模板手动生成 docx 都能正常打开 + 视觉差异明显
- pre-push hook 全绿
- 4-5 个独立 commit,每个对应一个 step

## 风险评估

- **Risk 1**:`_add_h1` / `_add_h2` / `_add_meta_line` 是核心 helper,所有模板都走,改动会全局影响
  → 缓解:Step 1 先加参数默认值(跟旧值一致),Step 2 才激活模板差异化;每步独立跑全量验证
- **Risk 2**:academic 简化 highlights 可能让项目信息缺失
  → 缓解:测试 `TestAcademicRenderer` 锁死"教育前置 + 无 H2 + 无 meta",保持其他 renderer 行为不变
- **Risk 3**:bullet 段间距加 space_after 可能让学术 / 极简模板过散
  → 缓解:每个模板可单独配 item_spacing_pt,默认 0 保持现状,academic 改 2,bilingual 改 2
- **Risk 4**:helper 改造影响 two_column 模板的双栏布局
  → 缓解:`test_two_column_has_table` + `TestLayoutDispatch.test_layout_generates_valid_docx` 已锁死,任何回归会立刻 fail

## 不做(留给后续 round)

- bilingual 双语 header / 教育 / 项目副标题(R3-M.3 方向 6)
- 用户可定制排版面板(R3-M.3)
- PDF 导出 / 暗色模式 / 拖拽排序(未来 round)
- self_eval 段优化(目前某些 role 是空,需要材料库补,不是本 round 范围)

## 触发条件

user 说"开始 R3-M.2" 启动实施。