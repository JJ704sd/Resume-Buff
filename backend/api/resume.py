"""
简历生成 API

Round 1 流程(带人工确认):
  1. POST /api/resume/preview  -> 返回结构化 sections,前端渲染预览
  2. 用户 review 后点"确认下载"
  3. POST /api/resume/generate -> 真正生成 .docx
  4. GET  /api/resume/download/{filename} -> 下载文件

Round 3 J: 5 套排版模板(template: classic/single_column/two_column/minimal/technical)
Round 3 I: 可选 jd_text 触发 JD-driven 排序(空 → 走原路径,字节级一致)
Round 3 G: POST /api/resume/parse-external -> 接收 .docx/.pdf/.txt 上传,
  解析为段落 list 返回(纯内存, 不落盘),
  给前端"上传外部简历 + JD 评分简历视角"提供原始数据
"""
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from core.generator import (
    preview_resume,
    generate_resume_docx,
    ENABLED_ROLES,
    ROLE_CONFIG,
    LAYOUT_CONFIG,
)
from core.resume_parser import (  # R3-G 新增: 外部简历解析
    EmptyResumeError,
    UnsupportedFormatError,
    parse_resume_bytes,
)

# R3-G: 上传大小上限 5MB (避免恶意灌入)
_MAX_UPLOAD_BYTES = 5 * 1024 * 1024

from core.logger import log_generation

router = APIRouter()

# 生成文件输出目录
OUTPUT_DIR = Path(__file__).parent.parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

# Round 3 I: 与 api/jd.py 保持一致的输入上限
_MAX_JD_TEXT_LEN = 50_000


class PreviewRequest(BaseModel):
    target_role: str
    intention: str | None = None
    custom_project_ids: list[str] | None = None
    template: str = "classic"  # Round 3 J
    jd_text: str | None = None  # Round 3 I: 可选 JD 触发排序
    # R3-M.3: academic 模板 detailed/compact 分支(None = 走 LAYOUT_CONFIG 默认 compact)
    academic_layout: str | None = None
    # R4-F: 可选 Function Calling 开关(默认 False = 走老路径,字节级一致)
    enable_function_calling: bool = False
    # R4-M: 可选 session_id(默认 None = 走老路径,字节级一致)
    session_id: str | None = None
    # R5-A Phase 1: 可选 Agent workflow 开关(默认 False = 走老路径,字节级一致)
    enable_agent_workflow: bool = False
    # R5-A closeout: 可选外部简历诊断(默认 False = P2 占位未消费,字节级一致)
    enable_external_resume: bool = False


class GenerateRequest(BaseModel):
    target_role: str
    intention: str | None = None
    custom_project_ids: list[str] | None = None
    template: str = "classic"  # Round 3 J
    jd_text: str | None = None  # Round 3 I: 可选 JD 触发排序
    # R3-M.3: academic 模板 detailed/compact 分支(None = 走 LAYOUT_CONFIG 默认 compact)
    academic_layout: str | None = None
    # R4-F: 可选 Function Calling 开关(默认 False = 走老路径,字节级一致)
    enable_function_calling: bool = False
    # R4-M: 可选 session_id(默认 None = 走老路径,字节级一致)
    session_id: str | None = None
    # R5-A Phase 1: 可选 Agent workflow 开关(默认 False = 走老路径,字节级一致)
    enable_agent_workflow: bool = False
    # R5-A closeout: 可选外部简历诊断(默认 False = P2 占位未消费,字节级一致)
    enable_external_resume: bool = False


# 每个 role 的展示名 + 风格描述(前端 listRoles 用)
ROLE_DISPLAY = {
    "tech_metric": ("大模型技术度量", "评测严谨 / 方法论导向"),
    "product":     ("AI 产品经理",   "用户视角 / 场景驱动"),
    "algorithm":   ("医疗 AI 算法",   "模型复现 / 架构对比"),
    "data_annot":  ("大模型数据标注", "准确率导向 / SOP 严谨"),
    "test_qa":     ("AI 测试 / QA",  "指标体系 / Badcase 归因"),
    "general":     ("日常实习(通用)", "全面展示 / 不偏科"),
}


def _normalize_jd_text(jd_text: str | None) -> str | None:
    """
    校验 + 规范化 jd_text:
      - None / 空字符串 / 全空白 → None(走原路径,字节级一致)
      - 长度 > 50_000 → 422
      - 其他 → strip 后返回
    """
    if jd_text is None:
        return None
    stripped = jd_text.strip()
    if not stripped:
        return None
    if len(jd_text) > _MAX_JD_TEXT_LEN:
        raise HTTPException(
            status_code=422,
            detail=f"jd_text 长度 {len(jd_text)} 超过上限 {_MAX_JD_TEXT_LEN}",
        )
    return stripped


@router.get("/roles")
def list_roles():
    """返回当前启用的岗位方向 + Round 3 J 模板列表"""
    return {
        "enabled": ENABLED_ROLES,
        "roles": [
            {
                "id": rid,
                "name": ROLE_DISPLAY.get(rid, (rid, ""))[0],
                "intention": ROLE_CONFIG[rid]["intention"],
                "tone": ROLE_DISPLAY.get(rid, (rid, ""))[1],
            }
            for rid in ENABLED_ROLES
        ],
        # Round 3 J: 前端选模板 radio 直接读这个列表
        "templates": [
            {"id": tid, "name": cfg["name"], "description": cfg["description"]}
            for tid, cfg in LAYOUT_CONFIG.items()
        ],
        "note": "Round 2 启用全部 6 个岗位方向",
    }


@router.post("/preview")
def preview(req: PreviewRequest):
    """
    预览接口: 返回结构化 sections,前端按模块渲染。
    调用 preview 不写日志(只是浏览)。
    """
    jd_text = _normalize_jd_text(req.jd_text)
    try:
        data = preview_resume(
            target_role=req.target_role,
            intention=req.intention,
            custom_project_ids=req.custom_project_ids,
            template=req.template,
            jd_text=jd_text,
            academic_layout=req.academic_layout,  # R3-M.3
            enable_function_calling=req.enable_function_calling,  # R4-F
            session_id=req.session_id,  # R4-M
            enable_agent_workflow=req.enable_agent_workflow,  # R5-A Phase 1
            enable_external_resume=req.enable_external_resume,  # R5-A closeout
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return data


@router.post("/generate")
def generate(req: GenerateRequest):
    """
    生成 .docx(用户在预览页确认后调用)。
    会写一行 generation.log。
    """
    jd_text = _normalize_jd_text(req.jd_text)
    try:
        out_path = generate_resume_docx(
            target_role=req.target_role,
            intention=req.intention,
            custom_project_ids=req.custom_project_ids,
            output_dir=OUTPUT_DIR,
            template=req.template,
            jd_text=jd_text,
            academic_layout=req.academic_layout,  # R3-M.3
            enable_function_calling=req.enable_function_calling,  # R4-F
            session_id=req.session_id,  # R4-M
            enable_agent_workflow=req.enable_agent_workflow,  # R5-A Phase 1
            enable_external_resume=req.enable_external_resume,  # R5-A closeout
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"生成失败: {e}")

    log_generation(
        role=req.target_role,
        intention=req.intention or ROLE_CONFIG[req.target_role]["intention"],
        filename=out_path.name,
        size_bytes=out_path.stat().st_size,
        status="success",
        template=req.template,
        academic_layout=req.academic_layout,  # R3-M.3: 仅 template=academic 时附加到日志
    )

    return FileResponse(
        path=str(out_path),
        filename=out_path.name,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


# ----------------------------------------------------------------------
# R3-G: 外部简历上传解析
# ----------------------------------------------------------------------
@router.post("/parse-external")
async def parse_external(file: UploadFile = File(...)):
    """
    接收 .docx / .pdf / .txt 上传, 解析为段落 list 返回 (纯内存, 不落盘)。

    设计:
      - 不依赖 LLM, 纯格式解析 (python-docx / pymupdf / utf-8 decode)
      - 段落结构同构: [{idx, text, is_heading}] (PDF 多 page 字段)
      - 上限 5MB, 超限返 413
      - 不支持后缀返 415
      - 空文件 / 解析失败返 422

    Returns:
        dict:
          - filename:    str
          - size_bytes:  int
          - paragraphs:  list[dict]  (idx / text / is_heading / page?)

    Errors:
      - 415: 文件后缀不在 .docx / .pdf / .txt
      - 413: 文件 > 5MB
      - 422: 空文件 / 解析失败
    """
    filename = file.filename or "uploaded_resume"
    raw = await file.read()

    # 1) 大小检查
    if len(raw) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"文件超过 5MB (实际 {len(raw)} bytes)",
        )
    if len(raw) == 0:
        raise HTTPException(status_code=422, detail="空文件")

    # 2) 后缀 dispatch (parse_resume_bytes 内部抛 UnsupportedFormatError / EmptyResumeError / ParseError)
    try:
        parsed = parse_resume_bytes(filename, raw)
        # parse_resume_bytes 返回 dict {filename, size_bytes, paragraphs, page_count?, note}
        # API 层只暴露 paragraphs + page_count + note (filename 已在 endpoint 包装过)
        paragraphs = parsed["paragraphs"]
        extra = {
            k: v for k, v in parsed.items()
            if k in ("page_count", "note")
        }
    except UnsupportedFormatError as e:
        raise HTTPException(status_code=415, detail=str(e))
    except EmptyResumeError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        # ParseError 或其他未分类 → 422
        raise HTTPException(status_code=422, detail=f"解析失败: {e}")

    return {
        "filename": filename,
        "size_bytes": len(raw),
        "paragraphs": paragraphs,
        **extra,  # 透传 page_count (PDF) + note
    }