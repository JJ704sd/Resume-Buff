"""
core/resume_parser.py 单元测试 — R3-G
测核心逻辑: docx/pdf/txt 字节流解析 + 后缀分派 + 错误路径
不测 thin wrapper (e.g. dict.get),只测边界 + 数据完整性。

运行:
  cd D:\\r3g-resume-upload\\backend
  D:\\python3.11\\python.exe -m pytest tests/test_parse_external.py -v
"""
import io

import pytest
from docx import Document

from core.resume_parser import (
    EmptyResumeError,
    UnsupportedFormatError,
    parse_resume_bytes,
    read_docx,
    read_pdf,
    read_txt,
    _looks_like_heading,
)


# ======================================================================
# 辅助:在内存里构造 docx / pdf 字节流(不落盘)
# ======================================================================
def _make_docx_bytes(paragraphs: list[str]) -> bytes:
    """用 python-docx 构造一个最小 docx,返回 bytes。"""
    doc = Document()
    for text in paragraphs:
        doc.add_paragraph(text)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _make_pdf_bytes(paragraphs: list[str]) -> bytes:
    """用 pymupdf 构造一个最小 pdf,返回 bytes。"""
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    # 拼成多行文本,每行一段
    page.insert_text(
        (72, 72),
        "\n".join(paragraphs),
        fontsize=12,
    )
    buf = io.BytesIO()
    doc.save(buf)
    doc.close()
    return buf.getvalue()


# ======================================================================
# _looks_like_heading: 标题判定(纯函数,无 IO)
# ======================================================================
class TestLooksLikeHeading:
    def test_chinese_section_headings(self):
        """常见中文简历章节标题应判定为 heading。"""
        for h in [
            "项目经历",
            "教育背景",
            "工作经历",
            "个人技能",
            "专业技能",
            "自我评价",
            "实习经历",
            "荣誉奖项",
        ]:
            assert _looks_like_heading(h), f"应判定为标题: {h}"

    def test_markdown_heading(self):
        """# markdown 风格也应识别。"""
        assert _looks_like_heading("# 项目经验")
        assert _looks_like_heading("# 个人简介")

    def test_bracketed_heading(self):
        """【xxx】风格也应识别。"""
        assert _looks_like_heading("【项目经历】")
        assert _looks_like_heading("【个人技能】")

    def test_non_heading_text(self):
        """普通正文 / 长段文本 / 纯空白不应识别为 heading。"""
        for text in [
            "本人在 2022 年参加了 XX 项目,负责后端开发",
            "Python 熟练,熟悉 PyTorch 框架",
            "",
            "   ",
            "Python",  # 单词不算
        ]:
            assert not _looks_like_heading(text), f"不应判定为标题: {text!r}"


# ======================================================================
# read_docx: docx 字节流解析
# ======================================================================
class TestReadDocx:
    def test_basic_paragraphs_and_heading_detection(self):
        """读真实 docx,验证 paragraphs 数量 + is_heading 判定。"""
        data = _make_docx_bytes([
            "个人简介",
            "我是一名 AI 算法工程师",
            "项目经历",
            "基于 PyTorch 训练大模型",
            "熟悉 Python 和 Docker",
            "教育背景",
            "某大学 计算机科学 硕士",
        ])
        paras = read_docx(data)

        assert len(paras) == 7, f"应识别 7 段,实际 {len(paras)}"
        # 每段都有 idx / text / is_heading
        for p in paras:
            assert set(p.keys()) >= {"idx", "text", "is_heading"}

        # 标题判定
        assert paras[0]["text"] == "个人简介"
        assert paras[0]["is_heading"] is True
        assert paras[1]["text"] == "我是一名 AI 算法工程师"
        assert paras[1]["is_heading"] is False
        assert paras[2]["is_heading"] is True  # 项目经历
        assert paras[3]["is_heading"] is False  # 长正文
        assert paras[5]["is_heading"] is True  # 教育背景

        # idx 连续从 0 开始
        for i, p in enumerate(paras):
            assert p["idx"] == i

    def test_empty_data_raises(self):
        """0 字节 → EmptyResumeError。"""
        with pytest.raises(EmptyResumeError):
            read_docx(b"")

    def test_invalid_data_raises_value_error(self):
        """坏字节流 → ValueError(包成 422)。"""
        with pytest.raises(ValueError, match="docx 解析失败"):
            read_docx(b"this is not a docx file")

    def test_preserves_empty_paragraphs_with_idx(self):
        """空行保留(idx 仍递增,text 为空)。"""
        data = _make_docx_bytes(["第一段", "", "第三段"])
        paras = read_docx(data)
        assert len(paras) == 3
        assert paras[0]["text"] == "第一段"
        assert paras[1]["text"] == ""
        assert paras[1]["is_heading"] is False
        assert paras[2]["text"] == "第三段"


# ======================================================================
# read_pdf: pdf 字节流解析
# ======================================================================
class TestReadPdf:
    def test_basic_paragraphs_with_page_number(self):
        """读真实 pdf,验证段落 + page 字段。
        注:用 ASCII 文本(英文简历/章节标题),避免 pymupdf 默认字体不支持 CJK 的问题。
        中文文本已在 docx/txt 测试里覆盖,这里只验 PDF 解析 + page 字段。"""
        data = _make_pdf_bytes([
            "Personal Info",
            "AI engineer with Python experience",
            "Projects",
            "Built PyTorch-based LLM evaluator",
        ])
        paras = read_pdf(data)

        assert len(paras) == 4
        for p in paras:
            assert set(p.keys()) >= {"idx", "text", "is_heading", "page"}
            assert p["page"] == 1, f"page 应为 1(单页),实际 {p['page']}"

        # 标题判定 — PDF 这里我们用 markdown 风格 (# Projects) 来验证 is_heading
        assert paras[0]["text"] == "Personal Info"
        assert paras[0]["is_heading"] is False  # 纯英文标题词不在中文 patterns 里

    def test_pdf_markdown_heading_detected(self):
        """PDF 里 # markdown 风格标题应被识别。"""
        data = _make_pdf_bytes([
            "# Projects",
            "Built a LLM evaluator",
            "# Education",
            "Master of CS",
        ])
        paras = read_pdf(data)
        assert len(paras) == 4
        assert paras[0]["text"] == "# Projects"
        assert paras[0]["is_heading"] is True
        assert paras[2]["is_heading"] is True
        assert paras[1]["is_heading"] is False

    def test_empty_data_raises(self):
        """0 字节 → EmptyResumeError。"""
        with pytest.raises(EmptyResumeError):
            read_pdf(b"")

    def test_invalid_data_raises_value_error(self):
        """坏字节流 → ValueError。"""
        with pytest.raises(ValueError, match="pdf 解析失败"):
            read_pdf(b"not a pdf")

    def test_page_count_inferred_correctly(self):
        """单页 pdf → page_count 正确推断。"""
        data = _make_pdf_bytes([
            "First paragraph here",
            "Second paragraph here",
            "Third paragraph here",
        ])
        result = parse_resume_bytes("test.pdf", data)
        assert result["page_count"] == 1
        assert len(result["paragraphs"]) == 3


# ======================================================================
# read_txt: txt 字节流解析
# ======================================================================
class TestReadTxt:
    def test_basic_paragraphs(self):
        """读 utf-8 文本,验证 paragraphs 数量 + is_heading。"""
        text = "个人简介\n我是一名 AI 算法工程师\n项目经历\n基于 PyTorch"
        paras = read_txt(text.encode("utf-8"))

        assert len(paras) == 4
        assert paras[0]["text"] == "个人简介"
        assert paras[0]["is_heading"] is True
        assert paras[1]["is_heading"] is False
        assert paras[2]["is_heading"] is True  # 项目经历

    def test_empty_data_raises(self):
        """0 字节 → EmptyResumeError。"""
        with pytest.raises(EmptyResumeError):
            read_txt(b"")

    def test_gbk_encoded_text(self):
        """GBK 编码的简历(老 .txt)应能正确解析。"""
        text = "个人简介\n技术栈:Python PyTorch"
        paras = read_txt(text.encode("gbk"))
        assert len(paras) == 2
        assert "Python" in paras[1]["text"]

    def test_skip_blank_lines(self):
        """空行不计入段落。"""
        text = "第一段\n\n\n第二段\n"
        paras = read_txt(text.encode("utf-8"))
        assert len(paras) == 2
        assert paras[0]["text"] == "第一段"
        assert paras[1]["text"] == "第二段"


# ======================================================================
# parse_resume_bytes: 后缀分派 + 顶层 dict
# ======================================================================
class TestParseResumeBytesDispatch:
    def test_docx_dispatch(self):
        """后缀 .docx → 走 read_docx,page_count 应为 None。"""
        data = _make_docx_bytes(["第一段", "项目经历", "PyTorch 训练"])
        result = parse_resume_bytes("test.docx", data)
        assert result["filename"] == "test.docx"
        assert result["size_bytes"] == len(data)
        assert result["page_count"] is None
        assert len(result["paragraphs"]) == 3
        assert "共 3 段" in result["note"]
        assert "(1 标题)" in result["note"]  # 项目经历

    def test_pdf_dispatch(self):
        """后缀 .pdf → 走 read_pdf,page_count 应有值。"""
        data = _make_pdf_bytes(["第一段", "项目经历"])
        result = parse_resume_bytes("test.pdf", data)
        assert result["filename"] == "test.pdf"
        assert result["page_count"] == 1
        assert len(result["paragraphs"]) == 2

    def test_txt_dispatch(self):
        """后缀 .txt → 走 read_txt,page_count 应为 None。"""
        text = "个人简介\n技术栈:Python"
        result = parse_resume_bytes("test.txt", text.encode("utf-8"))
        assert result["filename"] == "test.txt"
        assert result["page_count"] is None
        assert len(result["paragraphs"]) == 2

    def test_uppercase_suffix_normalized(self):
        """大写后缀应能识别(.DOCX → docx 分派)。"""
        data = _make_docx_bytes(["hello"])
        result = parse_resume_bytes("resume.DOCX", data)
        assert len(result["paragraphs"]) == 1

    def test_unsupported_format_raises(self):
        """不支持的格式(.zip) → UnsupportedFormatError。"""
        with pytest.raises(UnsupportedFormatError, match="不支持的文件类型"):
            parse_resume_bytes("test.zip", b"PK header")

    def test_no_suffix_raises(self):
        """无后缀 → UnsupportedFormatError。"""
        with pytest.raises(UnsupportedFormatError, match=r"\(无后缀\)"):
            parse_resume_bytes("resume", b"some content")

    def test_empty_data_raises(self):
        """0 字节 → EmptyResumeError(顶层分派也校验)。"""
        with pytest.raises(EmptyResumeError, match="文件为空"):
            parse_resume_bytes("test.docx", b"")

    def test_filename_basename_only(self):
        """filename 路径 → 只保留 basename,防止前端传完整路径。"""
        data = _make_docx_bytes(["hi"])
        result = parse_resume_bytes("C:\\Users\\test\\my_resume.docx", data)
        assert result["filename"] == "my_resume.docx"

    def test_note_includes_counts(self):
        """note 字段应包含段落数和标题数。"""
        data = _make_docx_bytes(["个人简介", "正文", "项目经历", "PyTorch 训练"])
        result = parse_resume_bytes("test.docx", data)
        # note 格式:"解析成功,共 N 段(M 标题)"
        assert "解析成功" in result["note"]
        assert "4 段" in result["note"]
        assert "2 标题" in result["note"]  # 个人简介 + 项目经历


# ======================================================================
# 错误处理: API 层的 5MB / 415 / 422 边界
# ======================================================================
class TestErrorPaths:
    def test_unsupported_format_message_mentions_supported_types(self):
        """错误消息应告诉用户支持的格式。"""
        with pytest.raises(UnsupportedFormatError) as exc_info:
            parse_resume_bytes("test.xlsx", b"some data")
        msg = str(exc_info.value)
        assert ".docx" in msg
        assert ".pdf" in msg
        assert ".txt" in msg

    def test_corrupt_docx_raises_value_error(self):
        """格式坏(docx 文件但内容损坏)→ ValueError(API 层会包成 422)。"""
        with pytest.raises(ValueError):
            parse_resume_bytes("test.docx", b"PK\x03\x04corrupted")

    def test_corrupt_pdf_raises_value_error(self):
        """格式坏(pdf 但内容损坏)→ ValueError。"""
        with pytest.raises(ValueError):
            parse_resume_bytes("test.pdf", b"%PDF-1.4 corrupted stream")

    def test_large_file_accepted_in_parser(self):
        """解析器本身**不**限制大小(由 API 层 5MB 限制兜底)。
        接近 5MB 的字节流(多行)应能正常解析。"""
        # 构造 ~1.7MB 多行 txt(每行一段,模拟大简历)
        lines = [f"这是第 {i} 段简历正文" for i in range(30000)]
        big_text = "\n".join(lines)
        data = big_text.encode("utf-8")
        assert len(data) > 500_000  # 至少 500KB
        result = parse_resume_bytes("big.txt", data)
        assert result["size_bytes"] == len(data)
        assert len(result["paragraphs"]) == 30000