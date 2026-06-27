# R3-M.1 — 加 3 套新模板 + A4 排版规范(Plan)

> 状态: ⏸️ plan 阶段 (2026-06-27)
> 拆分背景: R3-M "简历排版改进" 拆成 3 个 round 推进 (R3-M.1 / R3-M.2 / R3-M.3), user 同意按 M.1 → M.2 → M.3 推进
> 参考项目: [reactive-resume](https://github.com/amruthpillai/reactive-resume) (39.1k stars, 15 套差异化模板)

## 目标

5 套 → 8 套差异化模板 + 严格 A4 排版规范 + 黑白打印友好

## 范围

### 新增 3 套模板

| ID | 名称 | 风格 | 适用场景 | 主要 config 差异 |
|---|---|---|---|---|
| `academic` | 学术 CV | 学术风 | 读博 / 出国申请 | font_size_body=11, line_spacing=1.5, margins_cm=(2.5,2.5,2.5,2.5), header_align=center, skill_marker="" |
| `internet` | 互联网简洁 | 字节阿里 style | 互联网公司投递 | font_size_body=10, line_spacing=1.2, margins_cm=(1.5,1.5,1.5,1.5), header_align=left, skill_marker="▸ " |
| `bilingual` | 中英双语 | 双语 header / 项目副标题 | 外企 / 海外岗位 | font_size_body=10.5, line_spacing=1.3, margins_cm=(2.0,2.0,2.0,2.0), header_align=center |

### A4 排版规范

- **所有 8 套模板 `margins_cm` 严格 A4** (297mm × 210mm)
  - 默认上下 2.0cm, 左右 1.8cm (现有 5 套大部分已满足)
  - 新 3 套按各自风格调整,但都不超过 2.5cm 上下 / 2.5cm 左右
- **字号不小于 9pt** (打印缩小可读)
- **行距 1.15-1.5** (现有 5 套已满足)
- **黑白打印友好**: 任何模板 `use_color=False` 时 docx 仍生成有效 (颜色作为装饰, 内容靠粗体 / 字号区分)

### 后端改动

#### 1. `backend/core/generator.py` LAYOUT_CONFIG 加 3 项

```python
LAYOUT_CONFIG = {
    # ... 现有 5 套不动 ...
    "academic": {
        "name": "学术 CV",
        "description": "适合读博 / 出国申请,字号 11pt 行距 1.5 边距 2.5cm,教育背景优先",
        "use_color": True,
        "header_align": "center",
        "font_size_body": 11.0,
        "line_spacing": 1.5,
        "margins_cm": (2.5, 2.5, 2.5, 2.5),
        "two_column": False,
        "shaded_highlights": False,
        "skill_marker": "",
        "academic_mode": True,  # 新增 flag: 项目 highlights 简化
    },
    "internet": {
        "name": "互联网简洁",
        "description": "字节阿里 style,字号 10pt 行距 1.2 边距 1.5cm 单栏紧凑",
        "use_color": True,
        "header_align": "left",
        "font_size_body": 10.0,
        "line_spacing": 1.2,
        "margins_cm": (1.5, 1.5, 1.5, 1.5),
        "two_column": False,
        "shaded_highlights": False,
        "skill_marker": "▸ ",
    },
    "bilingual": {
        "name": "中英双语",
        "description": "header / 教育 / 项目双语,适合外企或海外岗位",
        "use_color": True,
        "header_align": "center",
        "font_size_body": 10.5,
        "line_spacing": 1.3,
        "margins_cm": (2.0, 2.0, 2.0, 2.0),
        "two_column": False,
        "shaded_highlights": False,
        "skill_marker": "",
        "bilingual_mode": True,  # 新增 flag: header / 项目双语
    },
}
```

#### 2. 渲染器扩展

- **大多数情况**: 复用 `_render_classic` alias 模式 (类似 `single_column` / `minimal` / `technical`)
- **`academic`**: 可能需要专门 `_render_academic` 函数, 简化项目 highlights (去掉"项目经验"前缀, 直接列论文 / 项目名)
  - 实现: 检测 `layout_cfg["academic_mode"]`, 在 `_render_project_group_to` 里简化 bullet 渲染
- **`bilingual`**: 改动最大, header / education / project 标题双语
  - 实现: 检测 `layout_cfg["bilingual_mode"]`, 加 helper `_render_bilingual_header_to` / `_render_bilingual_education_to`
  - 数据源: materials.json 已支持双语字段 (basics.name_en / education.school_en / projects.title_en) — 需确认

#### 3. 前端改动

**零** — `/api/resume/roles` 自动遍历 LAYOUT_CONFIG 暴露新模板, App.vue `v-for="t in templates"` 自动加 radio

### 测试覆盖

| 测试类 | 新增 case | 验证 |
|---|---|---|
| `TestLayoutDispatch` | `test_academic_dispatches_to_renderer` / `test_internet_dispatches_to_renderer` / `test_bilingual_dispatches_to_renderer` | 3 个新模板都能正常生成有效 docx |
| `TestLayoutVisuals` | `test_academic_larger_font_size` / `test_internet_smaller_font_size` / `test_internet_has_skill_marker` / `test_bilingual_margins_2_0cm` | 各自 config 差异化 |
| `TestA4Spec` (新) | `test_all_templates_margins_within_a4` / `test_all_templates_font_size_min_9pt` / `test_all_templates_line_spacing_valid_range` | A4 排版规范锁死 |
| `TestBwPrintFriendly` (新) | `test_docx_valid_when_color_disabled` (临时 `use_color=False` 注入验证) | 黑白打印兜底 |

预估: ~30 个新测试 case

## 实施路径

1. **Step 1: 后端 config 加 3 项 + 验证 dispatch** (~80 行 + ~15 测试)
2. **Step 2: academic renderer 简化 highlights** (~50 行 + ~5 测试)
3. **Step 3: bilingual renderer 双语 header / 项目** (~100 行 + ~10 测试)
4. **Step 4: A4 规范 + 黑白打印测试** (~50 行 + ~5 测试)
5. **Step 5: 文档同步** (AGENTS.md 测试数 + README.md 当前能力表)

每个 step 独立 commit + 跑全量 pytest 验证

## 工作量

- 后端代码: ~230 行 (3 项 config ~80 + academic renderer ~50 + bilingual renderer ~100)
- 测试: ~170 行 (~30 个 case)
- 文档: ~50 行 (AGENTS.md + README.md)
- **总计: ~450 行** (略高于 ROADMAP 估算的 350, 因为 bilingual renderer 比预想复杂)

## 依赖

- 无新增依赖 (python-docx 已装)
- materials.json 需确认双语字段 (basics.name_en / education.school_en / projects.title_en), 如果没有需 user 提供

## 触发条件

user 说 "开始做 R3-M.1" 启动实施

## 不做

- 用户可定制排版 (留 R3-M.3)
- 现有 5 套模板的细节打磨 (留 R3-M.2)
- PDF 导出 / 多语言 / 暗色模式 (留未来 round)

## 风险评估

- **Risk 1**: bilingual renderer 需要 materials.json 双语字段, 可能不完整 → 实施前先确认; 不完整时用 fallback (仅 header 双语)
- **Risk 2**: academic_mode 简化逻辑可能影响现有项目渲染 → 测试覆盖完整即可
- **Risk 3**: docx 字体在 Windows / Mac / Linux 表现可能不一致 → 用通用字体 (宋体 / 微软雅黑 / Calibri)

## 验收标准

- pytest 183 + 30 新增 = 213 passed + 0 skipped
- vue-tsc 0 error
- npm run build 成功
- pre-push hook 全绿
- 手动验证: 8 个模板都能生成有效 docx, 3 个新模板视觉差异明显