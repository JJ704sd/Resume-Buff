"""
素材库 API - 读取 / 更新 结构化简历事实
"""
import json
from pathlib import Path

from fastapi import APIRouter, HTTPException

router = APIRouter()

# 素材库 JSON 文件路径
MATERIALS_PATH = Path(__file__).parent.parent / "data" / "materials.json"


def _load() -> dict:
    if not MATERIALS_PATH.exists():
        raise HTTPException(status_code=500, detail="素材库文件不存在")
    with open(MATERIALS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _save(data: dict) -> None:
    with open(MATERIALS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


@router.get("")
def get_materials():
    """读取全部素材库"""
    return _load()


@router.get("/summary")
def get_summary():
    """返回素材库摘要(用于前端快速展示)"""
    data = _load()
    return {
        "name": data["basics"]["name"],
        "school": data["education"]["school"],
        "major": data["education"]["major"],
        "project_count": len(data["projects"]),
        "projects": [{"id": p["id"], "name": p["name"], "period": p["period"]} for p in data["projects"]],
        "skill_groups": list(data["skills"].keys()),
        "honor_count": len(data["honors"]),
    }


@router.get("/projects/{project_id}")
def get_project(project_id: str):
    """按 ID 读取单个项目详情"""
    data = _load()
    for p in data["projects"]:
        if p["id"] == project_id:
            return p
    raise HTTPException(status_code=404, detail=f"项目 {project_id} 不存在")


@router.put("")
def update_materials(payload: dict):
    """整体替换素材库(JSON 整体提交)"""
    required = ["basics", "education", "projects", "skills", "honors"]
    missing = [k for k in required if k not in payload]
    if missing:
        raise HTTPException(status_code=400, detail=f"缺少必填字段: {missing}")
    _save(payload)
    return {"ok": True, "updated_at": payload.get("_meta", {}).get("last_updated")}
