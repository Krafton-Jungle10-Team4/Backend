"""
스튜디오 통합 뷰 API 엔드포인트
"""
import logging
from fastapi import APIRouter, Depends, HTTPException, Query, status as http_status
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List

from app.core.database import get_db
from app.core.auth.dependencies import get_current_user_from_jwt
from app.models.user import User
from app.schemas.studio import (
    StudioWorkflowListResponse,
    StudioWorkflowItem,
    PaginationInfo,
    StatsInfo,
    FiltersInfo
)
from app.services.studio_service import get_studio_workflows, get_available_tags

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get(
    "/workflows",
    response_model=StudioWorkflowListResponse,
    status_code=http_status.HTTP_200_OK,
    summary="워크플로우 카드 목록 조회 (통합 뷰)",
    description="""
    스튜디오 페이지에서 사용할 워크플로우 카드 목록을 조회합니다.

    Bot, WorkflowVersion, Deployment, Marketplace 정보를 통합하여 제공합니다.

    **인증:**
    - JWT Bearer 토큰 필요 (Authorization: Bearer {token})

    **Query Parameters:**
    - page: 페이지 번호 (기본값: 1)
    - limit: 페이지당 카드 수 (기본값: 12)
    - search: 이름/설명 검색
    - status: 워크플로우 상태 (all, running, stopped, pending, error)
    - category: 카테고리 필터 (workflow, chatflow, chatbot, agent)
    - tags: 태그 필터 (다중 선택 가능)
    - sort: 정렬 기준 (updatedAt:desc, updatedAt:asc, name:asc, name:desc)
    - onlyMine: 내가 만든 워크플로우만 (기본값: false)

    **응답:**
    - data: 워크플로우 카드 목록
    - pagination: 페이지네이션 정보
    - stats: 통계 정보 (total, running, stopped)
    - filters: 필터 정보 (availableTags)
    """
)
async def get_studio_workflow_list(
    page: int = Query(1, ge=1, description="페이지 번호"),
    limit: int = Query(12, ge=1, le=100, description="페이지당 카드 수"),
    search: Optional[str] = Query(None, description="검색어 (이름/설명)"),
    status: Optional[str] = Query("all", description="워크플로우 상태"),
    category: Optional[str] = Query(None, description="카테고리 필터"),
    tags: Optional[List[str]] = Query(None, description="태그 필터"),
    sort: str = Query("updatedAt:desc", description="정렬 기준"),
    onlyMine: bool = Query(False, description="내가 만든 워크플로우만"),
    user: User = Depends(get_current_user_from_jwt),
    db: AsyncSession = Depends(get_db)
):
    """스튜디오 워크플로우 목록 조회"""
    logger.info(
        f"스튜디오 워크플로우 목록 조회: user={user.email}, page={page}, limit={limit}, "
        f"search={search}, status={status}, category={category}, tags={tags}"
    )

    try:
        # 워크플로우 목록 및 통계 조회
        workflow_items, total, stats = await get_studio_workflows(
            user_id=user.id,
            db=db,
            page=page,
            limit=limit,
            search=search,
            status=status,
            category=category,
            tags=tags,
            sort=sort,
            only_mine=onlyMine
        )

        # 태그 목록 조회
        available_tags = await get_available_tags(user.id, db, onlyMine)

        # 페이지네이션 정보
        total_pages = (total + limit - 1) // limit if total > 0 else 1

        # 응답 생성
        return StudioWorkflowListResponse(
            data=workflow_items,
            pagination=PaginationInfo(
                page=page,
                limit=limit,
                total=total,
                totalPages=total_pages
            ),
            stats=StatsInfo(
                total=stats["total"],
                running=stats["running"],
                stopped=stats["stopped"]
            ),
            filters=FiltersInfo(
                availableTags=available_tags
            )
        )

    except Exception as e:
        logger.error(f"스튜디오 워크플로우 목록 조회 실패: {e}", exc_info=True)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": {
                    "code": "INTERNAL_SERVER_ERROR",
                    "message": "워크플로우 목록 조회 중 오류가 발생했습니다"
                }
            }
        )
