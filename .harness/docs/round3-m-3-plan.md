# R3-M.3 — bilingual 双语激活 + academic detailed 模式 (Plan)

> 状态: ✅ 完成 (2026-06-27) — 4 commit (`9f25f40` + `310cbe5` + `185c7f7` + `39c7d20`),233 passed,0 skipped
> 上游: R3-M.2 已收尾(commit `7541810` ~ `cbf76af`,213 passed);R3-M.1 MVP 完成 8 套模板
> 落地: 激活 `bilingual_mode` flag(graceful degradation) + academic 加 `academic_layout: "detailed"` 模式
> 拆分背景: R3-M "简历排版改进" 拆 3 个 round 推进,本轮 = 长期方向 6 的**最小子集**;完整用户可定制排版面板(react-resume 风)留 P2 后续开

## 现状盘点

### 8 套 LAYOUT_CONFIG(R3-M.2 后)
| ID | name | renderer | R3-M.3 变化 |
|---|---|---|---|
| `classic` | 经典 | `_render_classic` | 不动 |
| `single_column` | 单栏紧凑 | `_render_classic` 别名 | 不动 |
| `two_column` | 双栏 | `_render_two_column` | 不动 |
| `minimal` | 极简 | `_render_classic` 别名 | 不动 |
| `technical` | 技术感 | `_render_classic` 别名 | 不动 |
| `academic` | 学术 CV | **`_render_academic`**(compact 模式默认) | **加 `academic_layout: "compact" \| "detailed"` 字段**;detailed 模式走 `_render_project_group_academic_detailed_to` 恢复 H2 + period meta + summary |
| `internet` | 互联网简洁 | `_render_classic` | 不动 |
| `bilingual` | 中英双语 | **`_render_classic`**(bilingual_mode dead code) | **改走 `_render_bilingual`** + 3 个 bilingual helper(graceful degradation) |

### 关键痛点
1. **`bilingual_mode` flag 是 dead code**(M.1 留的 hook,M.2 没动,本轮激活)
2. **academic 只有 compact 模式** — 删了 H2 项目名 / period meta / summary,但部分学术场景(如博士申请 Research Statement)需要详细版
3. **materials.json 没有 `_en` 字段** — `basics.name_en` / `education.school_en` / `projects.title_en` 都缺失,完整双语渲染走不通,需要 graceful degradation

## 目标

1. **激活 `bilingual_mode`**:走 `_render_bilingual` 路径,3 个 section 都有双语版 helper
   - **graceful degradation**:`_en` 字段缺失时不抛异常,只渲染中文(单语言降级)
2. **academic 加 detailed 模式**:`LAYOUT_CONFIG["academic"]["academic_layout"] = "detailed"` 时,项目段恢复 H2 项目名 + period meta + summary(同 classic 项目段)
3. **~20-25 个新 pytest** + 测试数 213 → 235-240
4. **前端微调**:`academic_layout` 在 academic 模板下显示为单选控件;模板详情 tooltip 提示双语字段缺失时会降级

## 范围

### 1. generator.py 改动

#### 1.1 LAYOUT_CONFIG 加 `academic_layout` 字段(仅 academic)

```python
"academic": {
    # ... 现有 R3-M.2 配置不动 ...
    "academic_mode": True,
    "academic_layout": "compact",   # R3-M.3 新增: "compact" | "detailed"
                                   # compact: 简化 highlights(无 H2 / 无 meta / 无 summary)
                                   # detailed: 恢复 H2 项目名 + period meta + summary
}
```

**约束**:`academic_layout` 默认 `"compact"`,保持 R3-M.2 行为(向后兼容);`TestAcademicRenderer` 现有 5 个 case 不变。

#### 1.2 新增 `_render_bilingual` + 3 个 section helper

```python
def _render_bilingual_header_to(container, s: Section, color: RGBColor, layout_cfg: dict):
    """bilingual header: 中文姓名 + 英文姓名(如有) + 中文求职意向 + 英文小字(如有) + 联系方式"""
    c = s.content
    align = WD_ALIGN_PARAGRAPH.LEFT if layout_cfg.get("header_align") == "left" else WD_ALIGN_PARAGRAPH.CENTER

    # 姓名(中)
    p = container.add_paragraph()
    p.alignment = align
    run = p.add_run(c["name"])
    _set_chinese_font(run, size_pt=22)
    run.bold = True
    p.paragraph_format.space_after = Pt(2)

    # 姓名(英) — graceful: 没有 name_en 就不渲染
    name_en = (c.get("name_en") or "").strip()
    if name_en:
        p = container.add_paragraph()
        p.alignment = align
        run = p.add_run(name_en)
        _set_chinese_font(run, size_pt=14)
        run.italic = True
        p.paragraph_format.space_after = Pt(4)

    # 求职意向
    intention = c.get("intention", "")
    p = container.add_paragraph()
    p.alignment = align
    run = p.add_run(f"求职意向:{intention}")
    _set_chinese_font(run, size_pt=11)
    if layout_cfg.get("use_color", True):
        run.font.color.rgb = color
    p.paragraph_format.space_after = Pt(4)

    # 联系方式
    p = container.add_paragraph()
    p.alignment = align
    run = p.add_run(c["contact"])
    _set_chinese_font(run, size_pt=10)
    if layout_cfg.get("use_color", True):
        run.font.color.rgb = RGBColor(0x60, 0x60, 0x60)
    p.paragraph_format.space_after = Pt(8)


def _render_bilingual_education_to(container, s: Section, color: RGBColor, layout_cfg: dict):
    """bilingual education: 中文教育信息 + 英文小字(如有 school_en / major_en)"""
    _add_h1(container, s.title, color, layout_cfg)
    c = s.content
    line = c.get("line", "")
    school_en = (c.get("school_en") or "").strip()
    major_en = (c.get("major_en") or "").strip()
    if school_en or major_en:
        # 中文行
        _add_h2(container, line, layout_cfg)
        # 英文行
        en_line = " | ".join(x for x in [school_en, major_en] if x)
        p = container.add_paragraph()
        run = p.add_run(en_line)
        _set_chinese_font(run, size_pt=10)
        run.italic = True
        p.paragraph_format.space_after = Pt(2)
    else:
        # graceful: 单语言
        _add_h2(container, line, layout_cfg)

    if c.get("courses"):
        _add_text(container, f"核心课程:{c['courses']}", layout_cfg)
    for h in c.get("highlights", []):
        _add_bullet(container, h, layout_cfg)


def _render_bilingual_project_group_to(container, s: Section, color: RGBColor, layout_cfg: dict):
    """bilingual project: 中文项目名 + 英文副标题(如有 title_en) + 中文 highlights"""
    _add_h1(container, s.title, color, layout_cfg)
    for proj in s.content["projects"]:
        c = proj["content"]
        # 项目名(中) + role
        _add_h2(container, f"{proj['title']}  |  {c['role']}", layout_cfg)
        # 英文副标题
        title_en = (c.get("title_en") or "").strip()
        if title_en:
            p = container.add_paragraph()
            run = p.add_run(title_en)
            _set_chinese_font(run, size_pt=10)
            run.italic = True
            p.paragraph_format.space_after = Pt(2)
        # period
        _add_meta_line(container, c["period"], layout_cfg)
        # summary
        if c.get("summary"):
            _add_text(container, c["summary"], layout_cfg)
        # highlights
        for h in c.get("highlights", []):
            if layout_cfg.get("shaded_highlights", False):
                _add_shaded_highlight(container, h, layout_cfg)
            else:
                _add_bullet(container, h, layout_cfg)


def _render_bilingual(doc: Document, sections: list[Section], role_cfg: dict, layout_cfg: dict):
    """bilingual renderer: 走 _dispatch_section,但 project_group / education / header 走 bilingual 版"""
    color = role_cfg["title_color"]
    for s in sections:
        if s.type == "header":
            _render_bilingual_header_to(doc, s, color, layout_cfg)
        elif s.type == "education":
            _render_bilingual_education_to(doc, s, color, layout_cfg)
        elif s.type == "project_group":
            _render_bilingual_project_group_to(doc, s, color, layout_cfg)
        else:
            _dispatch_section(doc, s, color, layout_cfg)
```

#### 1.3 academic detailed helper

```python
def _render_project_group_academic_detailed_to(
    container, s: Section, color: RGBColor, layout_cfg: dict
):
    """academic detailed 模式: 恢复 H2 项目名 + period meta + summary(同 classic 项目段)"""
    _add_h1(container, s.title, color, layout_cfg)
    for proj in s.content["projects"]:
        c = proj["content"]
        _add_h2(container, f"{proj['title']}  |  {c['role']}", layout_cfg)
        _add_meta_line(container, c["period"], layout_cfg)
        if c.get("summary"):
            _add_text(container, c["summary"], layout_cfg)
        for h in c.get("highlights", []):
            if layout_cfg.get("shaded_highlights", False):
                _add_shaded_highlight(container, h, layout_cfg)
            else:
                _add_bullet(container, h, layout_cfg)
```

#### 1.4 `_render_academic` 加 academic_layout 分支

```python
def _render_academic(doc: Document, sections: list[Section], role_cfg: dict, layout_cfg: dict):
    """academic renderer: academic_layout 决定 project_group 走 compact 还是 detailed"""
    color = role_cfg["title_color"]
    academic_layout = layout_cfg.get("academic_layout", "compact")
    for s in sections:
        if s.type == "project_group":
            if academic_layout == "detailed":
                _render_project_group_academic_detailed_to(doc, s, color, layout_cfg)
            else:
                _render_project_group_academic_to(doc, s, color, layout_cfg)
        else:
            _dispatch_section(doc, s, color, layout_cfg)
```

#### 1.5 _LAYOUT_DISPATCH 更新

```python
_LAYOUT_DISPATCH = {
    # ... 现有 7 套不动 ...
    "academic": _render_academic,        # 行为按 academic_layout 分支
    "internet": _render_classic,
    "bilingual": _render_bilingual,      # R3-M.3 改: dead code 激活
}
```

### 2. build_sections 改动

#### 2.1 header section 透传 `name_en`

`build_sections` 里 header section 的 content 加 `name_en` 字段,从 `basics.name_en` 读,缺失给空字符串:

```python
"sections": [
    {
        "type": "header",
        "title": "个人信息",
        "content": {
            "name": basics["name"],
            "name_en": basics.get("name_en", ""),   # R3-M.3 新增
            "intention": ...,
            "contact": ...,
        }
    },
    ...
]
```

#### 2.2 education section 透传 `school_en` / `major_en`

```python
{
    "type": "education",
    ...
    "content": {
        "line": f"{edu['school']} | {edu['major']} | {edu['degree']} | {edu['period']}",
        "school_en": edu.get("school_en", ""),    # R3-M.3 新增
        "major_en": edu.get("major_en", ""),      # R3-M.3 新增
        ...
    }
}
```

#### 2.3 project section 透传 `title_en`

```python
{
    "id": proj["id"],
    "title": proj["name"],
    "title_en": proj.get("title_en", ""),   # R3-M.3 新增
    "content": { ... }
}
```

### 3. 前端改动(~30 行)

#### 3.1 类型补 `ParsedProject.title_en` / `ParsedHeader.name_en` / `ParsedEducation.school_en/major_en` / `ResumeLayoutConfig.academic_layout`

`frontend/src/api/index.ts`:
- `ParsedProject` 加 `title_en?: string`
- `ParsedHeader` 加 `name_en?: string`
- `ParsedEducation` 加 `school_en?: string` / `major_en?: string`
- `ResumeLayoutConfig` 加 `academic_layout?: 'compact' | 'detailed'`

#### 3.2 App.vue academic 模板时显示 `academic_layout` 单选

模板选择 UI 在 `academic` 模板被选中时,加一个二级选项:`学术模式: ○ 紧凑(默认,适合履历表) ○ 详细(适合 Research Statement / 学术 CV 详细版)`。

#### 3.3 模板详情 tooltip 提示双语降级

bilingual 模板详情加 tooltip:"如需完整双语 header / 教育 / 项目副标题,请在 materials.json 中补充 `basics.name_en` / `education.school_en` / `education.major_en` / `projects[].title_en` 字段。字段缺失时自动降级为单语言。"

### 4. 测试覆盖

| 测试类 | 新增 case | 验证 |
|---|---|---|
| `TestAcademicLayout` | `test_detailed_renders_h2_project_name` / `test_detailed_renders_period_meta` / `test_detailed_renders_summary` / `test_compact_does_not_render_h2` / `test_compact_does_not_render_meta` / `test_default_is_compact` | 6 case:academic_layout 字段被消费,detailed/compact 行为分明 |
| `TestBilingualHeader` | `test_header_renders_name` / `test_header_renders_name_en_when_present` / `test_header_graceful_no_en_when_absent` / `test_header_layout_center_default` | 4 case |
| `TestBilingualEducation` | `test_education_renders_line` / `test_education_renders_school_en_when_present` / `test_education_graceful_no_en_when_absent` | 3 case |
| `TestBilingualProject` | `test_project_renders_title` / `test_project_renders_title_en_when_present` / `test_project_graceful_no_en_when_absent` | 3 case |
| `TestBilingualDispatch` | `test_bilingual_layout_dispatches_to_bilingual_renderer` / `test_classic_layout_unchanged` | 2 case |
| `TestMaterialsBilingualSchema` | `test_real_materials_no_en_fields_does_not_raise` / `test_mock_materials_with_en_fields_renders_both` | 2 case:真实 materials.json 无 `_en` 字段不抛异常,docx 仍有效 |
| **小计** | **20 case** | |

预估 pytest 213 + 20 = 233 passed,0 skipped。

### 5. 文档同步

- **AGENTS.md**:`R3-M.2: 23 个` 改 `R3-M.3: 20 个 academic_layout + bilingual renderer`;测试数 `213 → 233`
- **README.md**:当前能力表加 R3-M.3 一行(bilingual 激活 + academic detailed + graceful degradation)
- **ROADMAP.md**:`R3-M.3` entry 移到顶部快照段(1 行 commit hash + 简述);R3-M 整体 entry 标 ✅ 完成

## 实施路径(5 个 step-commit)

```
Step 1: generator.py LAYOUT_CONFIG 加 academic_layout 字段 + _render_academic 分支(compact/detailed)
        + TestAcademicLayout(6 case)
        pytest 213 → 219
        commit: feat(round3-m.3 step1): academic 加 academic_layout compact/detailed 分支

Step 2: generator.py 加 3 个 bilingual section helper + _render_bilingual 入口
        + _LAYOUT_DISPATCH["bilingual"] 切到 _render_bilingual
        + TestBilingualHeader/Education/Project/Dispatch(12 case)
        pytest 219 → 231
        commit: feat(round3-m.3 step2): 激活 bilingual_mode + 3 个 bilingual section helper

Step 3: build_sections 透传 _en 字段(header/education/project)
        + TestMaterialsBilingualSchema(2 case,含真实 materials.json graceful)
        pytest 231 → 233
        commit: feat(round3-m.3 step3): build_sections 透传 _en 字段 + 真实数据 graceful 验证

Step 4: 前端 academic_layout 单选 + bilingual 模板 tooltip
        commit: feat(round3-m.3 step4): 前端 academic_layout 单选 + bilingual 降级提示

Step 5: AGENTS.md / README.md / ROADMAP.md 同步 + 测试数 213 → 233
        commit: docs(round3-m.3): 测试数 + 当前能力表 + ROADMAP 收尾
```

## 工作量

| 模块 | 改动 | 估行 |
|---|---|---|
| `backend/core/generator.py` | +180 / -10 | 学术分支 + bilingual helper |
| `backend/tests/test_generator_layouts.py` | +250 / -5 | 20 case |
| `frontend/src/api/index.ts` | +8 / -0 | 类型补字段 |
| `frontend/src/App.vue` | +20 / -5 | 单选 + tooltip |
| `AGENTS.md` | +3 / -1 | 测试数 + 锁死说明 |
| `README.md` | +5 / -1 | 当前能力表 |
| `ROADMAP.md` | +5 / -10 | R3-M 收尾 + 移到快照 |
| **总计** | **~290 行** | 略低于 R3-M.1 (450) / R3-M.2 (430),因为本轮纯后端 helper 改造 + 轻前端 |

## 验收标准

- pytest **213 → 233,0 skipped**(20 新 case,均在 30 上限内,无 thin wrapper)
- vue-tsc 0 error
- npm run build 成功
- pre-push hook 全绿
- 手动验证:
  - `academic` 模板选 compact:docx 项目段无 H2 / 无 meta / 无 summary(同 R3-M.2 行为)
  - `academic` 模板选 detailed:docx 项目段有 H2 + role / period meta / summary
  - `bilingual` 模板 + 真实 materials(无 `_en` 字段):docx header 单行中文,教育单语言,项目单语言
  - `bilingual` 模板 + mock materials(有 `name_en` / `school_en` / `title_en`):docx header 双行(中 + 英文斜体),教育有英文小字,项目有英文副标题

## 风险评估

1. **Risk 1:docx 字号过小** — bilingual header 加 `name_en` 后变成 22pt 中文 + 14pt 英文,两行可能比 classic 大。缓解:`name_en` 14pt 合理(英文 14pt 视觉上接近中文 22pt 字号),space_after=2 不让两行贴太紧
2. **Risk 2:测试 mock 复杂度** — bilingual 测试需要 mock materials,有 3 个 section × 2 个有/无 `_en` 分支 = 6 case。缓解:用 `@pytest.fixture` 抽 `bilingual_materials_with_en` / `bilingual_materials_without_en`,每个测试用 parametrize
3. **Risk 3:`academic_layout` 字段缺失时回退** — 用户已有 LAYOUT_CONFIG 可能没这个字段。缓解:`_render_academic` 用 `.get("academic_layout", "compact")` 兜底,R3-M.2 现有 5 个 case 全跑
4. **Risk 4:前端 `academic_layout` 单选默认值** — 切换模板时如果从 academic 切走再切回来,值会丢。缓解:App.vue 用 `watch(() => templates.selected, ...)` 同步 `academic_layout`,或者把 `academic_layout` 绑到 layout 字符串拼接(例:`academic:compact` / `academic:detailed`),后者更简洁

## 触发条件

user 说 "开始做 R3-M.3" 或 orchestrator 在 user 明确同意后启动

## 不做

- 用户可定制排版面板(颜色 / 字体 / 间距滑块)— 留 P2 R3-M.4
- bilingual 的 highlights 关键术语括号英文(目前只做 header / education / project 标题)— 留 R3-M.4
- 现有 5 套模板的双语适配(只针对 `bilingual` 模板)— 留 R3-M.4
- academic 的 Research Statement / Publications 段(纯文本内容层,不是排版层)— 留 future

## 依赖

- 无新增依赖(python-docx 已装)
- 无需修改 materials.json(graceful degradation 设计)
- 现有 213 测试基线不变

## 已知坑(给 worker prompt)

1. **PowerShell `git commit -m` multi `-m`** — 不要用字面 `\n`,跟 R3-M.2 一样
2. **每个 step 独立 commit + pathspec** — `git add <files>` + `git commit -m "..."`,不带 pathspec 会把所有 staged 都带走
3. **Python 解释器绝对路径** — `D:\python3.11\python.exe`,不要 `python`
4. **删除临时文件用 `mavis-trash`** — 不要 `Remove-Item` / `rm`
5. **不要 git push** — 留给 orchestrator
6. **不写真实 PII** — 任何文件 / 日志 / commit message
