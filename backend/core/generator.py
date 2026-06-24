"""
简历生成器核心逻辑

设计:
  - 把"构造 sections(结构化内容)"和"写 docx(物理排版)"完全解耦
  - preview()  和 generate_docx() 共享 build_sections() 的输出,保证预览 = 下载
  - Round 1: 规则化选项目 + 模板化排版(不接 LLM)
  - Round 2: 接 LLM 智能改写项目描述(改写层接在 build_sections 之前)
"""
import json
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

from docx import Document
from docx.shared import Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn


MATERIALS_PATH = Path(__file__).parent.parent / "data" / "materials.json"

# ----------------------------------------------------------------------
# 范围声明 (Round 1): 只启用 "tech_metric",其他 5 个 role 暂留 config 但不暴露
# ----------------------------------------------------------------------
ENABLED_ROLES = ["tech_metric"]

ROLE_CONFIG = {
    "tech_metric": {
        "intention": "大模型技术度量实习生",
        "preferred_project_ids": ["tencent_medical_eval", "edan_ecg", "datawhale", "volunteer"],
        "skill_keys": ["ai_ml", "evaluation_metrics", "tools", "programming_languages", "documentation", "medical"],
        "self_eval_key": "tech_metric",
        "title_color": RGBColor(0x1F, 0x4E, 0x79),  # 深蓝
    },
    # ---- 预留: Round 2 启用 ----
    # "data_annot": { ... }
    # "product": { ... }
    # "algorithm": { ... }
    # "test_qa": { ... }
    # "general": { ... }
}

SKILL_LABEL = {
    "programming_languages": "编程语言",
    "ai_ml": "AI / 算法",
    "tools": "工程与工具",
    "evaluation_metrics": "评测指标",
    "medical": "医学素养",
    "documentation": "文档与协作",
    "data": "数据处理",
}


# ----------------------------------------------------------------------
# Section 数据类(可序列化为 JSON 给前端预览)
# ----------------------------------------------------------------------
@dataclass
class Section:
    type: str  # "header" | "education" | "project" | "skills" | "honors" | "self_eval"
    title: str
    content: dict = field(default_factory=dict)


# ----------------------------------------------------------------------
# 工具
# ----------------------------------------------------------------------
def load_materials() -> dict:
    with open(MATERIALS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _pick_highlights(project: dict, target_role: str) -> list[str]:
    """优先用 target_role 专属 highlights,降级 general"""
    h = project.get("highlights", {})
    return h.get(target_role) or h.get("general") or []


# ----------------------------------------------------------------------
# Sections 构造 (preview 和 docx 共用这一份)
# ----------------------------------------------------------------------
def build_sections(
    target_role: str,
    intention: Optional[str] = None,
    custom_project_ids: Optional[list[str]] = None,
) -> list[Section]:
    """
    构造完整的简历 sections 列表(可序列化为 JSON 预览,也可喂给 docx 渲染)。
    """
    if target_role not in ROLE_CONFIG:
        raise ValueError(f"不支持的岗位: {target_role},可选: {list(ROLE_CONFIG.keys())}")
    if target_role not in ENABLED_ROLES:
        raise ValueError(f"岗位 {target_role} 暂未启用 (Round 1 仅 tech_metric)。"

                              )

    materials = load_materials()
    role_cfg = ROLE_CONFIG[target_role]
    final_intention = intention or role_cfg["intention"]
    preferred_ids = custom_project_ids or role_cfg["preferred_project_ids"]

    sections: list[Section] = []

    # ----- Header -----
    b = materials["basics"]
    sections.append(Section(
        type="header",
        title=b["name"],
        content={
            "name": b["name"],
            "intention": final_intention,
            "contact": f"{b['phone']}  |  {b['email']}  |  现居 {b['location']}",
        },
    ))

    # ----- Education -----
    edu = materials["education"]
    sections.append(Section(
        type="education",
        title="教育背景",
        content={
            "line": f"{edu['school']} · {edu['college']} · {edu['major']} · {edu['degree']}  |  {edu['period']}({edu['year']})",
            "courses": "、".join(edu.get("core_courses", [])),
            "highlights": edu.get("highlights", []),
        },
    ))

    # ----- Projects -----
    proj_sections = []
    proj_map = {p["id"]: p for p in materials["projects"]}
    for pid in preferred_ids:
        if pid not in proj_map:
            continue
        p = proj_map[pid]
        proj_sections.append(Section(
            type="project",
            title=p["name"],
            content={
                "role": p["role"],
                "period": p["period"],
                "summary": p.get("summary", ""),
                "highlights": _pick_highlights(p, target_role),
                "tags": p.get("tags", []),
            },
        ))
    sections.append(Section(type="project_group", title="项目经历", content={"projects": [asdict(s) for s in proj_sections]}))

    # ----- Skills -----
    skills_content = []
    skills = materials["skills"]
    for key in role_cfg["skill_keys"]:
        items = skills.get(key, [])
        if not items:
            continue
        skills_content.append({
            "label": SKILL_LABEL.get(key, key),
            "items": items,
        })
    sections.append(Section(type="skills", title="相关技能", content={"groups": skills_content}))

    # ----- Honors & Certs -----
    honors = []
    for h in materials.get("honors", []):
        date = h.get("date", "")
        honors.append(f"{h['name']}  ({date})" if date else h["name"])
    for c in materials.get("certs", []):
        date = c.get("date", "")
        issuer = c.get("issuer", "")
        tail = f"  ·  {issuer}  ({date})" if date else f"  ·  {issuer}"
        honors.append(f"{c['name']}{tail}")
    sections.append(Section(type="honors", title="荣誉与证书", content={"items": honors}))

    # ----- Self Eval -----
    self_eval_key = role_cfg["self_eval_key"]
    sentences = materials.get("self_eval_versions", {}).get(self_eval_key) \
        or materials.get("self_eval_versions", {}).get("general", [])
    sections.append(Section(type="self_eval", title="自我评价", content={"sentences": sentences}))

    return sections


# ----------------------------------------------------------------------
# docx 渲染(消费 sections)
# ----------------------------------------------------------------------
def _set_chinese_font(run, font_name: str = "微软雅黑", size_pt: float = 10.5):
    run.font.name = font_name
    run.font.size = Pt(size_pt)
    rPr = run._element.get_or_add_rPr()
    rFonts = rPr.find(qn("w:rFonts"))
    if rFonts is None:
        from docx.oxml import OxmlElement
        rFonts = OxmlElement("w:rFonts")
        rPr.append(rFonts)
    rFonts.set(qn("w:eastAsia"), font_name)
    rFonts.set(qn("w:ascii"), font_name)
    rFonts.set(qn("w:hAnsi"), font_name)


def _setup_doc() -> Document:
    doc = Document()
    for section in doc.sections:
        section.top_margin = Cm(1.8)
        section.bottom_margin = Cm(1.8)
        section.left_margin = Cm(2.0)
        section.right_margin = Cm(2.0)
    style = doc.styles["Normal"]
    style.font.name = "微软雅黑"
    style.font.size = Pt(10.5)
    rPr = style.element.get_or_add_rPr()
    from docx.oxml import OxmlElement
    rFonts = rPr.find(qn("w:rFonts"))
    if rFonts is None:
        rFonts = OxmlElement("w:rFonts")
        rPr.append(rFonts)
    rFonts.set(qn("w:eastAsia"), "微软雅黑")
    return doc


def _add_h1(doc: Document, text: str, color: RGBColor):
    p = doc.add_paragraph()
    run = p.add_run(text)
    _set_chinese_font(run, size_pt=12)
    run.bold = True
    run.font.color.rgb = color
    p.paragraph_format.space_before = Pt(8)
    p.paragraph_format.space_after = Pt(4)
    return p


def _add_h2(doc: Document, text: str):
    p = doc.add_paragraph()
    run = p.add_run(text)
    _set_chinese_font(run, size_pt=10.5)
    run.bold = True
    p.paragraph_format.space_before = Pt(4)
    p.paragraph_format.space_after = Pt(2)
    return p


def _add_meta_line(doc: Document, text: str):
    p = doc.add_paragraph()
    run = p.add_run(text)
    _set_chinese_font(run, size_pt=9)
    run.italic = True
    run.font.color.rgb = RGBColor(0x80, 0x80, 0x80)
    p.paragraph_format.space_after = Pt(2)
    return p


def _add_text(doc: Document, text: str, size_pt: float = 10):
    p = doc.add_paragraph()
    run = p.add_run(text)
    _set_chinese_font(run, size_pt=size_pt)
    p.paragraph_format.line_spacing = 1.3
    return p


def _add_bullet(doc: Document, text: str):
    p = doc.add_paragraph(style="List Bullet")
    run = p.add_run(text)
    _set_chinese_font(run, size_pt=10)
    p.paragraph_format.line_spacing = 1.25
    return p


def render_docx(sections: list[Section], target_role: str, output_dir: Path) -> Path:
    """根据 sections 生成 .docx"""
    materials = load_materials()
    role_cfg = ROLE_CONFIG[target_role]
    color = role_cfg["title_color"]
    intention = next((s.content["intention"] for s in sections if s.type == "header"), role_cfg["intention"])

    output_dir.mkdir(parents=True, exist_ok=True)
    doc = _setup_doc()

    for s in sections:
        if s.type == "header":
            c = s.content
            # 姓名
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            run = p.add_run(c["name"])
            _set_chinese_font(run, size_pt=22)
            run.bold = True
            p.paragraph_format.space_after = Pt(4)
            # 求职意向
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            run = p.add_run(f"求职意向:{c['intention']}")
            _set_chinese_font(run, size_pt=11)
            run.font.color.rgb = color
            p.paragraph_format.space_after = Pt(4)
            # 联系方式
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            run = p.add_run(c["contact"])
            _set_chinese_font(run, size_pt=10)
            run.font.color.rgb = RGBColor(0x60, 0x60, 0x60)
            p.paragraph_format.space_after = Pt(8)

        elif s.type == "education":
            _add_h1(doc, s.title, color)
            _add_h2(doc, s.content["line"])
            if s.content.get("courses"):
                _add_text(doc, f"核心课程:{s.content['courses']}")
            for h in s.content.get("highlights", []):
                _add_bullet(doc, h)

        elif s.type == "project_group":
            _add_h1(doc, s.title, color)
            for proj in s.content["projects"]:
                c = proj["content"]
                _add_h2(doc, f"{proj['title']}  |  {c['role']}")
                _add_meta_line(doc, c["period"])
                if c.get("summary"):
                    _add_text(doc, c["summary"])
                for h in c.get("highlights", []):
                    _add_bullet(doc, h)

        elif s.type == "skills":
            _add_h1(doc, s.title, color)
            for g in s.content["groups"]:
                _add_text(doc, f"{g['label']}: " + "、".join(g["items"]))

        elif s.type == "honors":
            _add_h1(doc, s.title, color)
            for item in s.content["items"]:
                _add_bullet(doc, item)

        elif s.type == "self_eval":
            _add_h1(doc, s.title, color)
            for sent in s.content["sentences"]:
                _add_bullet(doc, sent)

    safe = re.sub(r"[^\w\u4e00-\u9fff]+", "_", intention)
    filename = f"{materials['basics']['name']}_{safe}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.docx"
    out_path = output_dir / filename
    doc.save(str(out_path))
    return out_path


# ----------------------------------------------------------------------
# 公开 API
# ----------------------------------------------------------------------
def preview_resume(
    target_role: str,
    intention: Optional[str] = None,
    custom_project_ids: Optional[list[str]] = None,
) -> dict:
    """返回结构化预览(JSON 友好)"""
    sections = build_sections(target_role, intention, custom_project_ids)
    return {
        "target_role": target_role,
        "intention": next((s.content["intention"] for s in sections if s.type == "header"), ""),
        "sections": [asdict(s) for s in sections],
    }


def generate_resume_docx(
    target_role: str,
    intention: Optional[str] = None,
    custom_project_ids: Optional[list[str]] = None,
    output_dir: Path = Path("output"),
) -> Path:
    """生成定制版简历 .docx(供 preview 确认后调用)"""
    sections = build_sections(target_role, intention, custom_project_ids)
    return render_docx(sections, target_role, output_dir)
