"""
마켓플레이스 API 엔드포인트
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc, or_, and_
from typing import List, Optional
from uuid import UUID

from app.core.database import get_db
from app.core.auth.dependencies import get_current_user_from_jwt
from app.models.user import User
from app.models.marketplace import MarketplaceItem, MarketplaceReview
from app.models.workflow_version import BotWorkflowVersion
from app.models.bot import Bot
from app.schemas.marketplace import (
    MarketplaceItemCreate,
    MarketplaceItemUpdate,
    MarketplaceItemResponse,
    MarketplaceItemListResponse,
    MarketplaceReviewCreate,
    MarketplaceReviewResponse,
    PublisherInfo,
    WorkflowVersionInfo,
)

router = APIRouter()


@router.post("/publish", response_model=MarketplaceItemResponse, summary="마켓플레이스에 게시")
async def publish_to_marketplace(
    data: MarketplaceItemCreate,
    current_user: User = Depends(get_current_user_from_jwt),
    db: AsyncSession = Depends(get_db),
):
    """
    워크플로우 버전을 마켓플레이스에 게시합니다.

    - 해당 워크플로우 버전의 소유자만 게시할 수 있습니다.
    - 이미 게시된 워크플로우 버전은 다시 게시할 수 없습니다.
    """
    # 워크플로우 버전 조회
    stmt = select(BotWorkflowVersion).where(BotWorkflowVersion.id == data.workflow_version_id)
    result = await db.execute(stmt)
    workflow_version = result.scalar_one_or_none()

    if not workflow_version:
        raise HTTPException(status_code=404, detail="워크플로우 버전을 찾을 수 없습니다.")

    # 봇 조회 및 권한 확인
    stmt = select(Bot).where(Bot.bot_id == workflow_version.bot_id)
    result = await db.execute(stmt)
    bot = result.scalar_one_or_none()

    if not bot:
        raise HTTPException(status_code=404, detail="봇을 찾을 수 없습니다.")

    if bot.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="권한이 없습니다.")

    # 이미 게시되었는지 확인
    stmt = select(MarketplaceItem).where(MarketplaceItem.workflow_version_id == data.workflow_version_id)
    result = await db.execute(stmt)
    existing_item = result.scalar_one_or_none()

    if existing_item:
        raise HTTPException(status_code=400, detail="이미 마켓플레이스에 게시된 워크플로우 버전입니다.")

    # 마켓플레이스 아이템 생성
    marketplace_item = MarketplaceItem(
        workflow_version_id=data.workflow_version_id,
        publisher_team_id=None,  # 팀 기능이 없으므로 None
        publisher_user_id=current_user.uuid,
        display_name=data.display_name or workflow_version.library_name or bot.name,
        description=data.description or workflow_version.library_description,
        category=data.category or workflow_version.library_category,
        tags=data.tags or workflow_version.library_tags,
        thumbnail_url=data.thumbnail_url,
        screenshots=data.screenshots,
        readme=data.readme,
        use_cases=data.use_cases,
        is_active=True,
        status="published",
    )

    db.add(marketplace_item)
    await db.commit()
    await db.refresh(marketplace_item)

    return await _build_marketplace_item_response(marketplace_item, db)


@router.get("", response_model=MarketplaceItemListResponse, summary="마켓플레이스 목록 조회")
async def get_marketplace_items(
    page: int = Query(1, ge=1, description="페이지 번호"),
    page_size: int = Query(20, ge=1, le=100, description="페이지 크기"),
    category: Optional[str] = Query(None, description="카테고리 필터"),
    tags: Optional[str] = Query(None, description="태그 필터 (쉼표로 구분)"),
    search: Optional[str] = Query(None, description="검색어 (이름, 설명)"),
    sort_by: str = Query("latest", description="정렬 기준 (latest, popular, rating)"),
    db: AsyncSession = Depends(get_db),
):
    """
    마켓플레이스 아이템 목록을 조회합니다.

    - 모든 사용자가 조회할 수 있습니다 (인증 불필요).
    - 카테고리, 태그, 검색어로 필터링할 수 있습니다.
    - 최신순, 인기순, 평점순으로 정렬할 수 있습니다.
    """
    # 기본 쿼리
    query = select(MarketplaceItem).where(
        and_(
            MarketplaceItem.is_active == True,
            MarketplaceItem.status == "published"
        )
    )

    # 카테고리 필터
    if category:
        query = query.where(MarketplaceItem.category == category)

    # 태그 필터
    if tags:
        tag_list = [tag.strip() for tag in tags.split(",")]
        query = query.where(MarketplaceItem.tags.op("&&")(tag_list))

    # 검색어 필터
    if search:
        query = query.where(
            or_(
                MarketplaceItem.display_name.ilike(f"%{search}%"),
                MarketplaceItem.description.ilike(f"%{search}%"),
            )
        )

    # 정렬
    if sort_by == "popular":
        query = query.order_by(desc(MarketplaceItem.download_count))
    elif sort_by == "rating":
        query = query.order_by(desc(MarketplaceItem.rating_average))
    else:  # latest
        query = query.order_by(desc(MarketplaceItem.published_at))

    # 총 개수 조회
    count_stmt = select(func.count()).select_from(query.subquery())
    result = await db.execute(count_stmt)
    total = result.scalar()

    # 페이지네이션
    offset = (page - 1) * page_size
    query = query.offset(offset).limit(page_size)

    result = await db.execute(query)
    items = result.scalars().all()

    # 응답 생성
    item_responses = []
    for item in items:
        item_response = await _build_marketplace_item_response(item, db)
        item_responses.append(item_response)

    total_pages = (total + page_size - 1) // page_size

    return MarketplaceItemListResponse(
        items=item_responses,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.get("/{item_id}", response_model=MarketplaceItemResponse, summary="마켓플레이스 아이템 상세 조회")
async def get_marketplace_item(
    item_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """
    마켓플레이스 아이템 상세 정보를 조회합니다.

    - 조회 시 view_count가 1 증가합니다.
    """
    stmt = select(MarketplaceItem).where(MarketplaceItem.id == item_id)
    result = await db.execute(stmt)
    item = result.scalar_one_or_none()

    if not item:
        raise HTTPException(status_code=404, detail="마켓플레이스 아이템을 찾을 수 없습니다.")

    # 조회수 증가
    item.view_count += 1
    await db.commit()
    await db.refresh(item)

    return await _build_marketplace_item_response(item, db)


@router.put("/{item_id}", response_model=MarketplaceItemResponse, summary="마켓플레이스 아이템 수정")
async def update_marketplace_item(
    item_id: UUID,
    data: MarketplaceItemUpdate,
    current_user: User = Depends(get_current_user_from_jwt),
    db: AsyncSession = Depends(get_db),
):
    """
    마켓플레이스 아이템을 수정합니다.

    - 게시자만 수정할 수 있습니다.
    """
    stmt = select(MarketplaceItem).where(MarketplaceItem.id == item_id)
    result = await db.execute(stmt)
    item = result.scalar_one_or_none()

    if not item:
        raise HTTPException(status_code=404, detail="마켓플레이스 아이템을 찾을 수 없습니다.")

    if item.publisher_user_id != current_user.uuid:
        raise HTTPException(status_code=403, detail="권한이 없습니다.")

    # 수정
    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(item, field, value)

    await db.commit()
    await db.refresh(item)

    return await _build_marketplace_item_response(item, db)


@router.delete("/{item_id}", summary="마켓플레이스 아이템 삭제")
async def delete_marketplace_item(
    item_id: UUID,
    current_user: User = Depends(get_current_user_from_jwt),
    db: AsyncSession = Depends(get_db),
):
    """
    마켓플레이스 아이템을 삭제합니다.

    - 게시자만 삭제할 수 있습니다.
    """
    stmt = select(MarketplaceItem).where(MarketplaceItem.id == item_id)
    result = await db.execute(stmt)
    item = result.scalar_one_or_none()

    if not item:
        raise HTTPException(status_code=404, detail="마켓플레이스 아이템을 찾을 수 없습니다.")

    if item.publisher_user_id != current_user.uuid:
        raise HTTPException(status_code=403, detail="권한이 없습니다.")

    await db.delete(item)
    await db.commit()

    return {"message": "마켓플레이스 아이템이 삭제되었습니다."}


@router.post("/{item_id}/download", summary="마켓플레이스 아이템 다운로드 카운트 증가")
async def increment_download_count(
    item_id: UUID,
    current_user: User = Depends(get_current_user_from_jwt),
    db: AsyncSession = Depends(get_db),
):
    """
    마켓플레이스 아이템의 다운로드 카운트를 증가시킵니다.

    - 실제로 워크플로우를 가져갈 때 호출됩니다.
    """
    stmt = select(MarketplaceItem).where(MarketplaceItem.id == item_id)
    result = await db.execute(stmt)
    item = result.scalar_one_or_none()

    if not item:
        raise HTTPException(status_code=404, detail="마켓플레이스 아이템을 찾을 수 없습니다.")

    item.download_count += 1
    await db.commit()

    return {"message": "다운로드 카운트가 증가되었습니다.", "download_count": item.download_count}


async def _build_marketplace_item_response(
    item: MarketplaceItem,
    db: AsyncSession,
) -> MarketplaceItemResponse:
    """마켓플레이스 아이템 응답 생성"""
    # 워크플로우 버전 정보 조회
    stmt = select(BotWorkflowVersion).where(BotWorkflowVersion.id == item.workflow_version_id)
    result = await db.execute(stmt)
    workflow_version = result.scalar_one_or_none()

    workflow_info = None
    if workflow_version:
        workflow_info = WorkflowVersionInfo(
            id=workflow_version.id,
            bot_id=workflow_version.bot_id,
            version=workflow_version.version,
            node_count=workflow_version.node_count,
            edge_count=workflow_version.edge_count,
            input_schema=workflow_version.input_schema,
            output_schema=workflow_version.output_schema,
        )

    # 게시자 정보 (추후 추가 가능)
    publisher_info = PublisherInfo(
        team_id=item.publisher_team_id,
        user_id=item.publisher_user_id,
    )

    return MarketplaceItemResponse(
        id=item.id,
        workflow_version_id=item.workflow_version_id,
        display_name=item.display_name,
        description=item.description,
        category=item.category,
        tags=item.tags,
        thumbnail_url=item.thumbnail_url,
        screenshots=item.screenshots,
        is_active=item.is_active,
        status=item.status,
        download_count=item.download_count,
        view_count=item.view_count,
        rating_average=item.rating_average,
        rating_count=item.rating_count,
        readme=item.readme,
        use_cases=item.use_cases,
        published_at=item.published_at,
        updated_at=item.updated_at,
        publisher=publisher_info,
        workflow_version=workflow_info,
    )
