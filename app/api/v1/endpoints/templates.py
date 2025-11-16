"""템플릿 관리 API 엔드포인트"""
import logging
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_
from typing import Optional, List

from app.core.database import get_db
from app.core.auth.dependencies import get_current_user_from_jwt
from app.models.user import User
from app.models.template import Template
from app.schemas.template import Template as TemplateSchema, TemplateCreate

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get(
    "",
    response_model=List[TemplateSchema],
    summary="템플릿 목록 조회",
    description="템플릿 목록을 카테고리 및 검색어로 필터링하여 조회합니다."
)
async def get_templates(
    category: Optional[str] = Query(None, description="카테고리 필터"),
    search: Optional[str] = Query(None, description="검색 쿼리"),
    skip: int = Query(0, ge=0, description="건너뛸 개수"),
    limit: int = Query(50, le=100, description="조회 개수"),
    db: AsyncSession = Depends(get_db),
):
    """
    템플릿 목록 조회

    - category: 카테고리 필터 (all, agent, workflow, chatbot 등)
    - search: 검색 쿼리
    - skip, limit: 페이지네이션
    """
    logger.info(f"템플릿 목록 조회: category={category}, search={search}")

    query = select(Template)

    if category and category != 'all':
        query = query.where(Template.category == category)

    if search:
        search_pattern = f"%{search}%"
        query = query.where(
            or_(
                Template.name.ilike(search_pattern),
                Template.description.ilike(search_pattern)
            )
        )

    query = query.offset(skip).limit(limit)

    result = await db.execute(query)
    templates = result.scalars().all()

    return templates


@router.get(
    "/{template_id}",
    response_model=TemplateSchema,
    summary="템플릿 상세 조회",
    description="특정 템플릿의 상세 정보를 조회합니다."
)
async def get_template(
    template_id: str,
    db: AsyncSession = Depends(get_db),
):
    """템플릿 상세 조회"""
    logger.info(f"템플릿 상세 조회: template_id={template_id}")

    result = await db.execute(
        select(Template).where(Template.id == template_id)
    )
    template = result.scalar_one_or_none()

    if not template:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"템플릿을 찾을 수 없습니다: {template_id}"
        )

    return template


@router.post(
    "/{template_id}/use",
    summary="템플릿으로 봇 생성",
    description="템플릿을 기반으로 새로운 봇을 생성합니다."
)
async def use_template(
    template_id: str,
    bot_name: str = Query(..., description="생성할 봇 이름"),
    user: User = Depends(get_current_user_from_jwt),
    db: AsyncSession = Depends(get_db),
):
    """
    템플릿으로부터 봇 생성

    - template_id: 사용할 템플릿 ID
    - bot_name: 생성할 봇 이름
    """
    logger.info(f"템플릿 사용: template_id={template_id}, bot_name={bot_name}, user={user.email}")

    result = await db.execute(
        select(Template).where(Template.id == template_id)
    )
    template = result.scalar_one_or_none()

    if not template:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"템플릿을 찾을 수 없습니다: {template_id}"
        )

    return {
        "message": "템플릿 기반 봇 생성 기능",
        "template_id": template_id,
        "bot_name": bot_name,
        "user_id": user.id
    }
