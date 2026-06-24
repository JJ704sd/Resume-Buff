"""
简历生成 API

Round 1 流程(带人工确认):
  1. POST /api/resume/preview  -> 返回结构化 sections,前端渲染预览
  2. 用户 review 后点"确认下载"
  3. POST /api/resume/generate -> 真正生成 .docx
  4. GET  /api/resume/download/{filename} -> 下载文件
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


class GenerateRequest(BaseModel):
    target_role: str
    intention: str | None = None
    custom_project_ids: list[str] | None = None


@router.get("/roles")
def list_roles():
    """返回当前启用的岗位方向"""
    return {
        "enabled": ENABLED_ROLES,
        "roles": [
            {
                "id": rid,
                "name": "大模型技术度量",
                "intention": ROLE_CONFIG[rid]["intention"],
                "tone": "评测严谨 / 方法论导向",
            }
            for rid in ENABLED_ROLES
        ],
        "note": "Round 1 仅启用大模型技术度量,其他 5 个方向 Round 2 解锁",
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
    )

    return FileResponse(
        path=str(out_path),
        filename=out_path.name,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
