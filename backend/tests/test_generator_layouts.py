"""
Round 3 J: 5 套排版模板 — generator.py layout dispatcher 行为测试

测点:
  - TestLayoutDispatch        5 套 layout 都能生成合法 docx + 默认 = classic
  - TestLayoutVisuals         视觉差异 — 颜色 / 斜体 / 底纹 / ■ marker / table / 字号
  - TestLayoutInvalid         非法 template 抛 ValueError
  - TestLayoutBackwardCompat  preview / generate 不传 template 也能工作

测"核心逻辑",不测:
  - 单纯 dict.get 取值
  - URL 字面量
  - mock 自指
"""
import re
import zipfile
from pathlib import Path

import pytest

from core.generator import (
    LAYOUT_CONFIG,
    generate_resume_docx,
    preview_resume,
    render_docx,
    build_sections,
)


# ----------------------------------------------------------------------
# 辅助:从 docx zip 内部读取并断言
# ----------------------------------------------------------------------
def _read_xml(path: Path, member: str = "word/document.xml") -> str:
    with zipfile.ZipFile(path) as z:
        return z.read(member).decode("utf-8")


def _docx_color_values(path: Path) -> set[str]:
    """提取 docx 内的所有 w:color 值(uppercase)。黑色 000000 也算在结果里。"""
    xml = _read_xml(path)
    return {v.upper() for v in re.findall(r'<w:color\s+w:val="([0-9A-Fa-f]{6})"', xml)}


def _docx_has_shd(path: Path) -> bool:
    """docx 是否包含 w:shd 元素(technical 模板的项目 highlight 底纹)"""
    return "w:shd" in _read_xml(path)


def _docx_has_italic(path: Path) -> bool:
    """docx 是否包含 w:i 元素(minimal 模板所有行都不应斜体)"""
    return bool(re.search(r"<w:i\s*/>|<w:i\s", _read_xml(path)))


def _docx_contains_text(path: Path, marker: str) -> bool:
    """docx 是否包含指定文本(technical 模板的 ■ skill marker)"""
    return marker in _read_xml(path)


def _docx_has_table(path: Path) -> bool:
    """docx 是否包含 w:tbl 元素(two_column 模板的双栏布局)"""
    return "<w:tbl" in _read_xml(path)


def _docx_normal_style_pt(path: Path) -> float | None:
    """读取 word/styles.xml 里 Normal 样式的 w:sz 字号(half-pt → pt)"""
    styles_xml = _read_xml(path, "word/styles.xml")
    m = re.search(r'<w:style[^>]*w:styleId="Normal"[^>]*>.*?</w:style>', styles_xml, re.DOTALL)
    if not m:
        return None
    sz = re.search(r'<w:sz[^/]*w:val="(\d+)"', m.group(0))
    if not sz:
        return None
    return int(sz.group(1)) / 2


# ----------------------------------------------------------------------
# TestLayoutDispatch: 5 套 layout 都能生成合法 docx + 默认 = classic
# ----------------------------------------------------------------------
class TestLayoutDispatch:
    @pytest.mark.parametrize("template", list(LAYOUT_CONFIG.keys()))
    def test_layout_generates_valid_docx(self, tmp_path: Path, template: str):
        out = generate_resume_docx(
            target_role="tech_metric",
            output_dir=tmp_path,
            template=template,
        )
        # 文件落地 + 体积合理
        assert out.exists(), f"{template}: 文件未生成"
        assert out.stat().st_size > 5_000, f"{template}: 文件过小 ({out.stat().st_size}B)"
        # 合法 zip + 关键 xml 存在
        assert zipfile.is_zipfile(out), f"{template}: 不是合法 zip"
        with zipfile.ZipFile(out) as z:
            assert "word/document.xml" in z.namelist(), f"{template}: 缺 document.xml"
            assert "word/styles.xml" in z.namelist(), f"{template}: 缺 styles.xml"

    def test_default_template_equals_classic(self, tmp_path: Path):
        """不传 template 与显式 template='classic' 行为一致"""
        out_default = generate_resume_docx(target_role="tech_metric", output_dir=tmp_path)
        out_classic = generate_resume_docx(
            target_role="tech_metric", output_dir=tmp_path, template="classic"
        )
        # 同色集合 + 同斜体
        assert _docx_color_values(out_default) == _docx_color_values(out_classic)
        assert _docx_has_italic(out_default) == _docx_has_italic(out_classic)
        # 同字号
        assert _docx_normal_style_pt(out_default) == _docx_normal_style_pt(out_classic)


# ----------------------------------------------------------------------
# TestLayoutVisuals: 视觉差异 — 颜色 / 斜体 / 底纹 / ■ marker / table / 字号
# ----------------------------------------------------------------------
class TestLayoutVisuals:
    def test_classic_uses_color(self, tmp_path: Path):
        """classic 至少要有 1 个非黑 RGBColor(深蓝/灰/中灰等)"""
        out = generate_resume_docx(
            target_role="tech_metric", output_dir=tmp_path, template="classic"
        )
        colors = _docx_color_values(out)
        non_black = {c for c in colors if c != "000000"}
        assert non_black, f"classic 应有非黑颜色,实际 {colors}"

    def test_minimal_no_color(self, tmp_path: Path):
        """minimal 全文黑 — 不写任何 w:color 元素"""
        out = generate_resume_docx(
            target_role="tech_metric", output_dir=tmp_path, template="minimal"
        )
        colors = _docx_color_values(out)
        assert colors == set(), f"minimal 应无颜色,实际 {colors}"

    def test_minimal_no_italic(self, tmp_path: Path):
        """minimal 所有行都不斜体 — meta 行(项目时间)不上 italic"""
        out = generate_resume_docx(
            target_role="tech_metric", output_dir=tmp_path, template="minimal"
        )
        assert not _docx_has_italic(out), "minimal 不应有 italic 元素"

    def test_technical_has_shaded_highlights(self, tmp_path: Path):
        """technical 项目 highlights 用浅灰底纹 — w:shd 元素存在"""
        out = generate_resume_docx(
            target_role="tech_metric", output_dir=tmp_path, template="technical"
        )
        assert _docx_has_shd(out), "technical 应有 w:shd 底纹元素"

    def test_technical_skill_marker(self, tmp_path: Path):
        """technical 技能行前缀 ■ 标识"""
        out = generate_resume_docx(
            target_role="tech_metric", output_dir=tmp_path, template="technical"
        )
        assert _docx_contains_text(out, "■"), "technical 技能行应含 ■ 标识"

    def test_two_column_has_table(self, tmp_path: Path):
        """two_column 下方双栏 — 必有 w:tbl"""
        out = generate_resume_docx(
            target_role="tech_metric", output_dir=tmp_path, template="two_column"
        )
        assert _docx_has_table(out), "two_column 应有 w:tbl 元素"
        # 反向断言:classic 应无 table
        out_classic = generate_resume_docx(
            target_role="tech_metric", output_dir=tmp_path, template="classic"
        )
        assert not _docx_has_table(out_classic), "classic 不应有 table(回归保护)"

    def test_single_column_font_size(self, tmp_path: Path):
        """single_column Normal style 字号 = 10pt(行距紧凑、适合 1 页纸)"""
        out = generate_resume_docx(
            target_role="tech_metric", output_dir=tmp_path, template="single_column"
        )
        size_pt = _docx_normal_style_pt(out)
        assert size_pt == pytest.approx(10.0), f"single_column Normal 应为 10pt,实际 {size_pt}pt"


# ----------------------------------------------------------------------
# TestLayoutInvalid: 非法 template 抛 ValueError
# ----------------------------------------------------------------------
class TestLayoutInvalid:
    def test_invalid_template_raises(self, tmp_path: Path):
        """template='foo' 不在 LAYOUT_CONFIG → ValueError"""
        with pytest.raises(ValueError, match="不支持的模板"):
            generate_resume_docx(
                target_role="tech_metric", output_dir=tmp_path, template="foo"
            )


# ----------------------------------------------------------------------
# TestLayoutBackwardCompat: preview / generate 不传 template 也能工作
# ----------------------------------------------------------------------
class TestLayoutBackwardCompat:
    def test_preview_resume_default_template(self):
        """preview_resume 不传 template → 默认 classic"""
        data = preview_resume(target_role="tech_metric")
        # Round 3 J: preview 返回里带 template 字段
        assert data.get("template") == "classic"
        # sections 仍正常返回
        assert len(data["sections"]) >= 1
        assert data["target_role"] == "tech_metric"

    def test_generate_resume_docx_default_template(self, tmp_path: Path):
        """generate_resume_docx 不传 template → 默认走 classic 渲染"""
        out = generate_resume_docx(target_role="tech_metric", output_dir=tmp_path)
        assert out.exists()
        # classic 视觉特征:有 italic(项目时间 meta 行)
        assert _docx_has_italic(out), "默认 template 应走 classic(classic 有 italic meta)"
        assert _docx_normal_style_pt(out) == pytest.approx(10.5)


# ----------------------------------------------------------------------
# TestLayoutVisualsR3M1: Round 3 M.1 新增 3 套模板的差异化 config 断言
# (dispatch 覆盖由现有 TestLayoutDispatch.test_layout_generates_valid_docx 参数化
#  自动扩展 — 该 parametrize 遍历 LAYOUT_CONFIG.keys(),新增 3 项自动覆盖 3 个新模板)
# ----------------------------------------------------------------------
class TestLayoutVisualsR3M1:
    def test_academic_larger_font_size(self):
        """academic font_size_body = 11.0(读博 / 出国申请 字号偏大)"""
        assert LAYOUT_CONFIG["academic"]["font_size_body"] == pytest.approx(11.0), (
            f"academic font_size_body 应为 11.0, 实际 {LAYOUT_CONFIG['academic']['font_size_body']}"
        )

    def test_internet_smaller_font_size(self):
        """internet font_size_body = 10.0(字节阿里 style 单页紧凑)"""
        assert LAYOUT_CONFIG["internet"]["font_size_body"] == pytest.approx(10.0), (
            f"internet font_size_body 应为 10.0, 实际 {LAYOUT_CONFIG['internet']['font_size_body']}"
        )

    def test_internet_has_skill_marker(self):
        """internet skill_marker = '▸ '(互联网简历技术感前缀)"""
        assert LAYOUT_CONFIG["internet"]["skill_marker"] == "▸ ", (
            f"internet skill_marker 应为 '▸ ', 实际 {LAYOUT_CONFIG['internet']['skill_marker']!r}"
        )

    def test_bilingual_default_margins(self):
        """bilingual margins 接近 2.0cm 四边(双语布局相对宽松)"""
        margins = LAYOUT_CONFIG["bilingual"]["margins_cm"]
        assert margins == pytest.approx((2.0, 2.0, 2.0, 2.0)), (
            f"bilingual margins 应为 (2.0, 2.0, 2.0, 2.0), 实际 {margins}"
        )