"""
简历生成 API

Round 1 流程(带人工确认):
  1. POST /api/resume/preview  -> 返回结构化 sections,前端渲染预览
  2. 用户 review 后点"确认下载"
  3. POST /api/resume/generate -> 真正生成 .docx
  4. GET  /api/resume/download/{filename} -> 下载文件

Round 3 J: 5 套排版模板(template: classic/single_column/two_column/minimal/technical)
"""
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from core.generator import (
    preview_resume,
    generate_resume_docx,
    ENABLED_ROLES,
    ROLE_CONFIG,
    LAYOUT_CONFIG,
)
from core.logger import log_generation

router = APIRouter()

# 生成文件输出目录
OUTPUT_DIR = Path(__file__).parent.parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)


class PreviewRequest(BaseModel):
    target_role: str
    intention: str | None = None
    custom_project_ids: list[str] | None = None
    template: str = "classic"  # Round 3 J


class GenerateRequest(BaseModel):
    target_role: str
    intention: str | None = None
    custom_project_ids: list[str] | None = None
    template: str = "classic"  # Round 3 J


# 每个 role 的展示名 + 风格描述(前端 listRoles 用)
ROLE_DISPLAY = {
    "tech_metric": ("大模型技术度量", "评测严谨 / 方法论导向"),
    "product":     ("AI 产品经理",   "用户视角 / 场景驱动"),
    "algorithm":   ("医疗 AI 算法",   "模型复现 / 架构对比"),
    "data_annot":  ("大模型数据标注", "准确率导向 / SOP 严谨"),
    "test_qa":     ("AI 测试 / QA",  "指标体系 / Badcase 归因"),
    "general":     ("日常实习(通用)", "全面展示 / 不偏科"),
}


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
    try:
        data = preview_resume(
            target_role=req.target_role,
            intention=req.intention,
            custom_project_ids=req.custom_project_ids,
            template=req.template,
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
    try:
        out_path = generate_resume_docx(
            target_role=req.target_role,
            intention=req.intention,
            custom_project_ids=req.custom_project_ids,
            output_dir=OUTPUT_DIR,
            template=req.template,
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
    )

    return FileResponse(
        path=str(out_path),
        filename=out_path.name,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )