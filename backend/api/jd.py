"""
JD 解析 / 匹配度评分 API — Round 2 #2

端点:
  - POST /api/jd/parse   -> 提取 JD 关键词/经验/学历
  - POST /api/jd/match   -> 对指定 role + 素材库算 0-100 匹配分

约束:
  - **不** import 前端任何东西
  - **不**依赖 LLM,纯规则化
  - 错误处理: 400 (target_role 不在 ENABLED_ROLES) / 422 (text 空 / 超长)
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from core.generator import ENABLED_ROLES
from core.jd_parser import match_score, parse_jd


router = APIRouter()


# 输入上限保护 (避免被恶意 / 手滑 灌入 100MB 文本)
_MAX_TEXT_LEN = 50_000


class ParseRequest(BaseModel):
    text: str = Field(..., description="JD 文本,任意长度,>10k 字符也行")


class MatchRequest(BaseModel):
    text: str = Field(..., description="JD 文本")
    target_role: str = Field(..., description="6 个 role id 之一")
    # R3-G 新增:外部简历全文 (由前端把上传文件的所有 paragraph.text 拼起来)
    # 可选, 不传则 match_score 不计算 resume_perspective 字段
    external_resume_text: str | None = Field(
        default=None,
        description="R3-G 新增: 外部简历全文 (可选, >50k 走不到这里, 由 _MAX_TEXT_LEN 兜底)",
    )


def _validate_text(text: str) -> None:
    """422 if text 为空或 >50k 字符。"""
    if not text or not text.strip():
        raise HTTPException(status_code=422, detail="text 不能为空")
    if len(text) > _MAX_TEXT_LEN:
        raise HTTPException(
            status_code=422,
            detail=f"text 长度 {len(text)} 超过上限 {_MAX_TEXT_LEN}",
        )


@router.post("/parse")
def jd_parse(req: ParseRequest):
    """
    解析 JD 文本,返回关键词 / 经验 / 学历。

    错误:
      - 422: text 为空或 > 50k 字符
    """
    _validate_text(req.text)
    return parse_jd(req.text)


@router.post("/match")
def jd_match(req: MatchRequest):
    """
    对指定 role + 当前素材库计算 0-100 匹配分。

    错误:
      - 400: target_role 不在 ENABLED_ROLES
      - 422: text 为空或 > 50k 字符
    """
    _validate_text(req.text)

    if req.target_role not in ENABLED_ROLES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"target_role {req.target_role!r} 未启用,"
                f"当前已启用: {ENABLED_ROLES}"
            ),
        )

    try:
        return match_score(
            req.text,
            req.target_role,
            external_resume_text=req.external_resume_text,
        )
    except ValueError as e:
        # match_score 内部也会校验,但防御性兜底
        raise HTTPException(status_code=400, detail=str(e))
