"""
스튜디오 통합 뷰 서비스
"""
import logging
from typing import List, Tuple, Optional, Dict
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, case, and_, or_, desc, asc
from sqlalchemy.orm import selectinload, joinedload

from app.models.bot import Bot, BotStatus, BotCategory
from app.models.workflow_version import BotWorkflowVersion
from app.models.deployment import BotDeployment
from app.models.marketplace import MarketplaceItem
from app.schemas.studio import (
    StudioWorkflowItem,
    WorkflowStatus,
    DeploymentState,
    MarketplaceState
)
from app.config import settings

logger = logging.getLogger(__name__)


def _convert_bot_status_to_workflow_status(bot_status: BotStatus) -> WorkflowStatus:
    """Bot 상태를 Workflow 상태로 변환"""
    mapping = {
        BotStatus.ACTIVE: "running",
        BotStatus.INACTIVE: "stopped",
        BotStatus.DRAFT: "pending",
        BotStatus.ERROR: "error"
    }
    return mapping.get(bot_status, "stopped")


def _convert_deployment_status(
    deployment: Optional['BotDeployment'],
    marketplace_active: bool = False
) -> DeploymentState:
    """
    Deployment 상태 변환 (개선된 로직)

    Args:
        deployment: BotDeployment 객체 (None이면 stopped)
        marketplace_active: 마켓플레이스에 게시 여부

    Returns:
        DeploymentState: deployed, stopped, error, deploying 중 하나
    """
    if not deployment:
        return "stopped"

    status = deployment.status

    if status == "published":
        return "deployed"
    elif status == "draft":
        return "deploying"
    elif status == "suspended":
        return "error"
    else:
        return "stopped"


def _build_deployment_url(widget_key: Optional[str]) -> Optional[str]:
    """
    Widget URL 동적 생성

    우선순위:
    1. settings.api_public_url (환경 변수 API_PUBLIC_URL)
    2. settings.backend_url (환경 변수 BACKEND_URL)
    3. fallback: localhost (개발용)
    """
    if not widget_key:
        return None

    base_url = settings.api_public_url or settings.backend_url

    if not base_url or base_url == "http://localhost:8001":
        logger.warning(
            "API_PUBLIC_URL이 설정되지 않았습니다. "
            "프로덕션 환경에서는 반드시 .env에 API_PUBLIC_URL을 설정하세요."
        )
        base_url = "http://localhost:8001"

    return f"{base_url}/widget/{widget_key}"


async def get_studio_workflows(
    user_id: int,
    db: AsyncSession,
    page: int = 1,
    limit: int = 12,
    search: Optional[str] = None,
    status: Optional[str] = None,
    category: Optional[str] = None,
    tags: Optional[List[str]] = None,
    sort: str = "updatedAt:desc",
    only_mine: bool = False
) -> Tuple[List[StudioWorkflowItem], int, Dict]:
    """
    스튜디오 워크플로우 목록 조회 (통합 뷰)

    Returns:
        Tuple[List[StudioWorkflowItem], int, Dict]: (워크플로우 목록, 전체 개수, 통계)
    """
    logger.info(f"스튜디오 워크플로우 조회: user_id={user_id}, page={page}, limit={limit}")

    # === 1. 기본 쿼리 작성 ===
    access_filters = []
    if only_mine:
        access_filters.append(Bot.user_id == user_id)
        shared_bot_ids: List[int] = []
    else:
        shared_bot_ids = await _get_shared_bot_ids(user_id, db)
        if shared_bot_ids:
            access_filters.append(
                or_(Bot.user_id == user_id, Bot.id.in_(shared_bot_ids))
            )
        else:
            access_filters.append(Bot.user_id == user_id)
            logger.debug("onlyMine=False: 공유 가능한 봇이 없어 소유한 봇만 반환")

    query = select(Bot)
    for condition in access_filters:
        query = query.where(condition)

    # === 2. 필터 적용 ===

    # 검색 (이름 또는 설명)
    if search:
        search_filter = or_(
            Bot.name.ilike(f"%{search}%"),
            Bot.description.ilike(f"%{search}%")
        )
        query = query.where(search_filter)

    # 상태 필터
    if status and status != "all":
        if status == "running":
            query = query.where(Bot.status == BotStatus.ACTIVE)
        elif status == "stopped":
            query = query.where(Bot.status == BotStatus.INACTIVE)
        elif status == "pending":
            query = query.where(Bot.status == BotStatus.DRAFT)
        elif status == "error":
            query = query.where(Bot.status == BotStatus.ERROR)

    # 카테고리 필터
    if category:
        try:
            category_enum = BotCategory(category)
            query = query.where(Bot.category == category_enum)
        except ValueError:
            logger.warning(f"Invalid category: {category}")

    # 태그 필터 (OR 조건: 태그 중 하나라도 포함하면 매칭)
    if tags:
        tag_conditions = [Bot.tags.contains([tag]) for tag in tags]
        query = query.where(or_(*tag_conditions))

    # === 3. 전체 개수 조회 (페이지네이션용) ===
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # === 4. 정렬 ===
    sort_field, sort_order = sort.split(":")

    if sort_field == "updatedAt":
        order_column = Bot.updated_at
    elif sort_field == "createdAt":
        order_column = Bot.created_at
    elif sort_field == "name":
        order_column = Bot.name
    else:
        order_column = Bot.updated_at

    if sort_order == "asc":
        query = query.order_by(asc(order_column))
    else:
        query = query.order_by(desc(order_column))

    # === 5. 페이지네이션 ===
    offset = (page - 1) * limit
    query = query.offset(offset).limit(limit)

    # === 6. 실행 ===
    result = await db.execute(query)
    bots = result.scalars().all()

    # === 7. 각 봇에 대한 추가 정보 조회 (N+1 문제 해결) ===

    bot_ids_str = [bot.bot_id for bot in bots]
    bot_ids_int = [bot.id for bot in bots]

    # 7.1. 최신 워크플로우 버전 조회 (각 봇별로 최신 published 버전)
    latest_versions_query = (
        select(BotWorkflowVersion)
        .where(
            and_(
                BotWorkflowVersion.bot_id.in_(bot_ids_str),
                BotWorkflowVersion.status == "published"
            )
        )
        .order_by(BotWorkflowVersion.created_at.desc())
    )
    latest_versions_result = await db.execute(latest_versions_query)
    all_versions = latest_versions_result.scalars().all()

    # 봇별 최신 버전 매핑
    latest_version_map = {}
    for version in all_versions:
        if version.bot_id not in latest_version_map:
            latest_version_map[version.bot_id] = version

    # 7.2. 이전 버전 개수 조회 (봇별 집계)
    version_count_query = (
        select(
            BotWorkflowVersion.bot_id,
            func.count(BotWorkflowVersion.id).label("version_count")
        )
        .where(BotWorkflowVersion.bot_id.in_(bot_ids_str))
        .group_by(BotWorkflowVersion.bot_id)
    )
    version_count_result = await db.execute(version_count_query)
    version_count_map = {row.bot_id: row.version_count for row in version_count_result}

    # 7.3. 활성 배포 조회
    deployments_query = (
        select(BotDeployment)
        .where(BotDeployment.bot_id.in_(bot_ids_int))
        .order_by(BotDeployment.created_at.desc())
    )
    deployments_result = await db.execute(deployments_query)
    all_deployments = deployments_result.scalars().all()

    # 봇별 최신 배포 매핑
    deployment_map = {}
    for deployment in all_deployments:
        if deployment.bot_id not in deployment_map:
            deployment_map[deployment.bot_id] = deployment

    # 7.4. 마켓플레이스 아이템 조회 (워크플로우 버전 ID 기반)
    version_ids = [v.id for v in all_versions]
    marketplace_query = (
        select(MarketplaceItem)
        .where(MarketplaceItem.workflow_version_id.in_(version_ids))
    )
    marketplace_result = await db.execute(marketplace_query)
    all_marketplace_items = marketplace_result.scalars().all()

    # 워크플로우 버전별 마켓플레이스 아이템 매핑
    marketplace_map = {item.workflow_version_id: item for item in all_marketplace_items}

    # === 8. StudioWorkflowItem 생성 ===
    studio_items = []

    for bot in bots:
        # 최신 버전 정보
        latest_version = latest_version_map.get(bot.bot_id)
        latest_version_str = latest_version.version if latest_version else None

        # 이전 버전 개수 (전체 버전 - 1)
        total_versions = version_count_map.get(bot.bot_id, 0)
        previous_version_count = max(0, total_versions - 1)

        # 마켓플레이스 정보 먼저 조회
        marketplace_item = None
        if latest_version:
            marketplace_item = marketplace_map.get(latest_version.id)

        marketplace_active = bool(marketplace_item and marketplace_item.is_active)
        marketplace_state: MarketplaceState = "published" if marketplace_active else "unpublished"
        last_published_at = marketplace_item.published_at.isoformat() + "Z" if marketplace_item and marketplace_item.published_at else None

        # 배포 정보 (마켓플레이스 상태 고려)
        deployment = deployment_map.get(bot.id)
        deployment_state = _convert_deployment_status(deployment, marketplace_active)
        deployment_url = _build_deployment_url(deployment.widget_key if deployment else None)
        last_deployed_at = deployment.updated_at.isoformat() + "Z" if deployment and deployment.updated_at else None

        # StudioWorkflowItem 생성
        item = StudioWorkflowItem(
            id=bot.bot_id,
            name=bot.name,
            description=bot.description,
            category=bot.category.value,
            tags=bot.tags if bot.tags else [],
            status=_convert_bot_status_to_workflow_status(bot.status),
            latestVersion=latest_version_str,
            latestVersionId=str(latest_version.id) if latest_version else None,
            previousVersionCount=previous_version_count,
            deploymentState=deployment_state,
            deploymentUrl=deployment_url,
            lastDeployedAt=last_deployed_at,
            marketplaceState=marketplace_state,
            lastPublishedAt=last_published_at,
            createdAt=bot.created_at.isoformat() + "Z",
            updatedAt=bot.updated_at.isoformat() + "Z" if bot.updated_at else bot.created_at.isoformat() + "Z"
        )
        studio_items.append(item)

    # === 9. 통계 정보 생성 ===
    stats_query = select(
        func.count(Bot.id).label("total"),
        func.sum(case((Bot.status == BotStatus.ACTIVE, 1), else_=0)).label("running"),
        func.sum(case((Bot.status == BotStatus.INACTIVE, 1), else_=0)).label("stopped"),
        func.sum(case((Bot.status == BotStatus.DRAFT, 1), else_=0)).label("pending"),
        func.sum(case((Bot.status == BotStatus.ERROR, 1), else_=0)).label("error")
    )

    for condition in access_filters:
        stats_query = stats_query.where(condition)

    stats_result = await db.execute(stats_query)
    stats_row = stats_result.first()

    stats = {
        "total": stats_row.total or 0,
        "running": stats_row.running or 0,
        "stopped": stats_row.stopped or 0,
        "pending": stats_row.pending or 0,
        "error": stats_row.error or 0
    }

    return studio_items, total, stats


async def get_available_tags(
    user_id: int,
    db: AsyncSession,
    only_mine: bool = False
) -> List[str]:
    """사용 가능한 태그 목록 조회 (접근 가능한 봇 기준)"""
    shared_bot_ids = []
    if not only_mine:
        shared_bot_ids = await _get_shared_bot_ids(user_id, db)

    if only_mine or not shared_bot_ids:
        access_condition = Bot.user_id == user_id
    else:
        access_condition = or_(Bot.user_id == user_id, Bot.id.in_(shared_bot_ids))

    query = select(Bot.tags).where(access_condition)
    result = await db.execute(query)
    all_tags_lists = result.scalars().all()

    # 중복 제거 및 정렬
    tags_set = set()
    for tags in all_tags_lists:
        if tags:
            tags_set.update(tags)

    return sorted(list(tags_set))


async def _get_shared_bot_ids(user_id: int, db: AsyncSession) -> List[int]:
    """공유 권한이 있는 봇 ID를 조회 (향후 Access Control 연동 예정)."""
    # 현재는 공유 기능이 없으므로 빈 리스트 반환
    return []
