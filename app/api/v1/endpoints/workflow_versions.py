"""
워크플로우 버전 관리 API 엔드포인트

워크플로우 버전의 생성, 수정, 발행, 조회 등의 기능을 제공합니다.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Optional
from uuid import UUID
import logging

from app.core.database import get_db
from app.core.auth.dependencies import get_current_user_from_jwt as get_current_user
from app.models.user import User
from app.schemas.workflow import (
    WorkflowVersionCreate,
    WorkflowVersionResponse,
    WorkflowVersionDetail,
    WorkflowVersionStatus,
    PublishWorkflowRequest,
    WorkflowVersionResponseWithLibrary
)
from app.services.workflow_version_service import WorkflowVersionService
from app.services.bot_service import BotService
from app.core.workflow.validator import WorkflowValidator

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/bots/{bot_id}/workflow-versions",
    tags=["workflow-versions"]
)

# 레거시 호환: 기존 프론트엔드가 /workflows/versions 경로를 호출하므로
# 동일한 핸들러를 재사용하는 별도 라우터를 제공한다.
legacy_router = APIRouter(
    prefix="/bots/{bot_id}/workflows/versions",
    tags=["workflow-versions (legacy)"]
)


@router.post(
    "/draft",
    response_model=WorkflowVersionResponse,
    summary="Draft 워크플로우 생성/수정",
    description="Bot의 draft 워크플로우를 생성하거나 기존 draft를 수정합니다."
)
async def create_or_update_draft(
    bot_id: str,
    request: WorkflowVersionCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> WorkflowVersionResponse:
    """
    Draft 워크플로우 생성/수정

    - Bot당 하나의 draft만 존재
    - 기존 draft가 있으면 업데이트
    """
    try:
        # 봇 접근 권한 확인
        bot_service = BotService()
        bot = await bot_service.get_bot_by_id(bot_id, current_user.id, db)
        if not bot:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="봇을 찾을 수 없거나 접근 권한이 없습니다"
            )

        # Draft 생성/수정
        logger.info(f"[DEBUG] request.graph type: {type(request.graph)}, value: {request.graph}")
        logger.info(f"[DEBUG] request.environment_variables: {request.environment_variables}")
        logger.info(f"[DEBUG] request.conversation_variables: {request.conversation_variables}")

        if not request.graph:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="워크플로우 그래프가 필요합니다"
            )

        graph_payload = request.graph.dict() if hasattr(request.graph, 'dict') else request.graph
        logger.info(f"[DEBUG] graph_payload type: {type(graph_payload)}, keys: {graph_payload.keys() if graph_payload else None}")

        # DEBUG: Slack 노드 데이터 로깅
        nodes = graph_payload.get("nodes", []) if graph_payload else []
        for node in nodes:
            if node.get("type") == "slack" or node.get("data", {}).get("type") == "slack":
                logger.info(f"[DEBUG] Saving Slack node: id={node.get('id')}, data keys={list(node.get('data', {}).keys())}, data={node.get('data', {})}")

        validator = WorkflowValidator()
        edges = graph_payload.get("edges", []) if graph_payload else []
        is_valid, errors, warnings = validator.validate(nodes, edges)

        if not is_valid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "message": "워크플로우 검증 실패",
                    "errors": errors,
                    "warnings": warnings
                }
            )

        service = WorkflowVersionService(db)
        version = await service.create_or_update_draft(
            bot_id=bot_id,
            graph=graph_payload,
            environment_variables=request.environment_variables,
            conversation_variables=request.conversation_variables,
            user_id=current_user.uuid
        )

        return WorkflowVersionResponse(
            id=str(version.id),
            bot_id=version.bot_id,
            version=version.version,
            status=WorkflowVersionStatus(version.status),
            created_at=version.created_at,
            updated_at=version.updated_at,
            published_at=version.published_at
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create/update draft workflow: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Draft 워크플로우 생성/수정 실패: {str(e)}"
        )


legacy_router.add_api_route(
    "/draft",
    create_or_update_draft,
    methods=["POST"],
    response_model=WorkflowVersionResponse,
    summary="Draft 워크플로우 생성/수정",
    description="(레거시 경로) Bot의 draft 워크플로우를 생성하거나 기존 draft를 수정합니다."
)


@router.post(
    "/{version_id}/publish",
    response_model=WorkflowVersionResponse,
    summary="워크플로우 발행",
    description="Draft 워크플로우를 발행하여 실제 사용 가능한 버전으로 만듭니다. 선택적으로 라이브러리에 등록할 수 있습니다."
)
async def publish_workflow(
    bot_id: str,
    version_id: str,
    request: PublishWorkflowRequest = PublishWorkflowRequest(),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> WorkflowVersionResponse:
    """
    Draft 발행

    - 새 버전 번호 생성 (v1.0, v1.1 등)
    - 해당 버전을 활성 워크플로우로 설정
    - 새로운 빈 draft 자동 생성
    - 선택적으로 라이브러리에 등록 (library_metadata 제공 시)
    """
    try:
        # 봇 접근 권한 확인
        bot_service = BotService()
        bot = await bot_service.get_bot_by_id(bot_id, current_user.id, db)
        if not bot:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="봇을 찾을 수 없거나 접근 권한이 없습니다"
            )

        # library_metadata를 딕셔너리로 변환
        library_metadata_dict = None
        if request.library_metadata:
            library_metadata_dict = request.library_metadata.dict()

        # Draft 발행
        service = WorkflowVersionService(db)
        version = await service.publish_draft(
            bot_id=bot_id,
            version_id=version_id,
            user_id=current_user.uuid,
            library_metadata=library_metadata_dict
        )

        return WorkflowVersionResponse(
            id=str(version.id),
            bot_id=version.bot_id,
            version=version.version,
            status=WorkflowVersionStatus(version.status),
            created_at=version.created_at,
            updated_at=version.updated_at,
            published_at=version.published_at
        )

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to publish workflow: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"워크플로우 발행 실패: {str(e)}"
        )


legacy_router.add_api_route(
    "/{version_id}/publish",
    publish_workflow,
    methods=["POST"],
    response_model=WorkflowVersionResponse,
    summary="워크플로우 발행",
    description="(레거시 경로) Draft 워크플로우를 발행하여 실제 사용 가능한 버전으로 만듭니다."
)


@router.get(
    "",
    response_model=List[WorkflowVersionResponseWithLibrary],
    summary="워크플로우 버전 목록 조회",
    description="Bot의 모든 워크플로우 버전을 조회합니다."
)
async def list_workflow_versions(
    bot_id: str,
    version_status: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> List[WorkflowVersionResponseWithLibrary]:
    """
    워크플로우 버전 목록 조회

    - version_status 파라미터로 필터링 가능 (draft, published, archived)
    - 라이브러리 필드 포함
    """
    try:
        # 봇 접근 권한 확인
        bot_service = BotService()
        bot = await bot_service.get_bot_by_id(bot_id, current_user.id, db)
        if not bot:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="봇을 찾을 수 없거나 접근 권한이 없습니다"
            )

        # 버전 목록 조회
        service = WorkflowVersionService(db)
        versions = await service.list_versions(
            bot_id=bot_id,
            status=version_status
        )

        return [
            WorkflowVersionResponseWithLibrary(
                id=str(v.id),
                bot_id=v.bot_id,
                version=v.version,
                status=WorkflowVersionStatus(v.status),
                created_at=v.created_at,
                updated_at=v.updated_at,
                published_at=v.published_at,
                library_name=v.library_name,
                library_description=v.library_description,
                library_category=v.library_category,
                library_tags=v.library_tags,
                library_visibility=v.library_visibility,
                is_in_library=v.is_in_library,
                library_published_at=v.library_published_at,
                input_schema=v.input_schema,
                output_schema=v.output_schema,
                node_count=v.node_count,
                edge_count=v.edge_count,
                port_definitions=v.port_definitions
            )
            for v in versions
        ]

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to list workflow versions: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"워크플로우 버전 목록 조회 실패: {str(e)}"
        )


legacy_router.add_api_route(
    "",
    list_workflow_versions,
    methods=["GET"],
    response_model=List[WorkflowVersionResponseWithLibrary],
    summary="워크플로우 버전 목록 조회",
    description="(레거시 경로) Bot의 모든 워크플로우 버전을 조회합니다."
)


@router.get(
    "/{version_id}",
    response_model=WorkflowVersionDetail,
    summary="워크플로우 버전 상세 조회",
    description="특정 워크플로우 버전의 상세 정보를 조회합니다."
)
async def get_workflow_version(
    bot_id: str,
    version_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> WorkflowVersionDetail:
    """
    특정 버전 상세 조회

    - 워크플로우 그래프, 환경 변수 등 모든 정보 포함
    - 마켓플레이스에 게시된 버전은 readonly 접근 허용
    """
    try:
        # 먼저 버전 조회
        service = WorkflowVersionService(db)
        version = await service.get_version(version_id)

        if not version or version.bot_id != bot_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="워크플로우 버전을 찾을 수 없습니다"
            )

        # 마켓플레이스에 게시된 버전인지 확인
        from app.models.marketplace import MarketplaceItem
        # version.id를 UUID로 변환 (이미 UUID일 수도 있지만 안전하게 처리)
        version_uuid = version.id if isinstance(version.id, UUID) else UUID(str(version.id))
        stmt = select(MarketplaceItem).where(
            MarketplaceItem.workflow_version_id == version_uuid,
            MarketplaceItem.is_active == True
        )
        result = await db.execute(stmt)
        marketplace_item = result.scalar_one_or_none()

        # 마켓플레이스에 게시된 버전이면 접근 허용
        if marketplace_item:
            # 마켓플레이스에 게시된 버전은 readonly 접근 허용
            pass
        else:
            # 마켓플레이스에 게시되지 않은 버전은 봇 소유권 확인 필요
            bot_service = BotService()
            bot = await bot_service.get_bot_by_id(bot_id, current_user.id, db)
            if not bot:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="봇을 찾을 수 없거나 접근 권한이 없습니다"
                )

        from app.schemas.workflow import WorkflowGraph
        return WorkflowVersionDetail(
            id=str(version.id),
            bot_id=version.bot_id,
            version=version.version,
            status=WorkflowVersionStatus(version.status),
            created_at=version.created_at,
            updated_at=version.updated_at,
            published_at=version.published_at,
            graph=WorkflowGraph(**version.graph),
            environment_variables=version.environment_variables,
            conversation_variables=version.conversation_variables
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get workflow version: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"워크플로우 버전 조회 실패: {str(e)}"
        )


legacy_router.add_api_route(
    "/{version_id}",
    get_workflow_version,
    methods=["GET"],
    response_model=WorkflowVersionDetail,
    summary="워크플로우 버전 상세 조회",
    description="(레거시 경로) 특정 워크플로우 버전의 상세 정보를 조회합니다."
)


@router.post(
    "/{version_id}/archive",
    response_model=WorkflowVersionResponse,
    summary="워크플로우 버전 아카이브",
    description="특정 워크플로우 버전을 아카이브 상태로 변경합니다."
)
async def archive_workflow_version(
    bot_id: str,
    version_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> WorkflowVersionResponse:
    """
    버전 아카이브

    - 사용하지 않는 버전을 아카이브 처리
    """
    try:
        # 봇 접근 권한 확인
        bot_service = BotService()
        bot = await bot_service.get_bot_by_id(bot_id, current_user.id, db)
        if not bot:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="봇을 찾을 수 없거나 접근 권한이 없습니다"
            )

        # 버전 아카이브
        service = WorkflowVersionService(db)
        version = await service.archive_version(version_id)

        if version.bot_id != bot_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="이 워크플로우 버전에 접근할 권한이 없습니다"
            )

        return WorkflowVersionResponse(
            id=str(version.id),
            bot_id=version.bot_id,
            version=version.version,
            status=WorkflowVersionStatus(version.status),
            created_at=version.created_at,
            updated_at=version.updated_at,
            published_at=version.published_at
        )

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to archive workflow version: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"워크플로우 버전 아카이브 실패: {str(e)}"
        )


legacy_router.add_api_route(
    "/{version_id}/archive",
    archive_workflow_version,
    methods=["POST"],
    response_model=WorkflowVersionResponse,
    summary="워크플로우 버전 아카이브",
    description="(레거시 경로) 특정 워크플로우 버전을 아카이브 상태로 변경합니다."
)


# 마이그레이션 라우터 (관리자용)
migration_router = APIRouter(
    prefix="/admin/workflow-versions",
    tags=["workflow-versions-admin"]
)


@migration_router.post(
    "/migrate-schemas",
    response_model=dict,
    summary="레거시 스키마 마이그레이션 (관리자)",
    description="기존 워크플로우 버전의 NULL/dict 스키마를 배열로 마이그레이션합니다."
)
async def migrate_workflow_schemas(
    bot_id: Optional[str] = None,
    dry_run: bool = True,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> dict:
    """
    레거시 스키마 마이그레이션

    - 모든 published 버전의 스키마를 재추출
    - dry_run=True이면 결과만 반환하고 실제 업데이트는 하지 않음
    - bot_id를 지정하면 해당 봇의 버전만 마이그레이션
    """
    try:
        service = WorkflowVersionService(db)
        stats = await service.migrate_legacy_schemas(
            bot_id=bot_id,
            dry_run=dry_run
        )

        return {
            "success": True,
            "dry_run": dry_run,
            "statistics": stats
        }

    except Exception as e:
        logger.error(f"Failed to migrate schemas: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"스키마 마이그레이션 실패: {str(e)}"
        )
