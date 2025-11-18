"""
라이브러리 에이전트 API 엔드포인트

공유 라이브러리에 등록된 워크플로우 에이전트를 조회하고 가져오는 기능을 제공합니다.
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional
import logging

from app.core.database import get_db
from app.core.auth.dependencies import get_current_user_from_jwt as get_current_user
from app.models.user import User
from app.schemas.workflow import (
    LibraryAgentResponse,
    LibraryAgentDetailResponse,
    LibraryImportRequest,
    WorkflowVersionResponse,
    WorkflowVersionStatus,
    WorkflowGraph
)
from app.services.library_service import LibraryService
from app.services.bot_service import BotService

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/library",
    tags=["library"]
)


@router.get(
    "/agents",
    response_model=dict,
    summary="라이브러리 에이전트 목록 조회",
    description="공유 라이브러리에 등록된 워크플로우 에이전트 목록을 조회합니다. 필터링 및 페이지네이션을 지원합니다."
)
async def list_library_agents(
    category: Optional[str] = Query(None, description="카테고리 필터"),
    visibility: Optional[str] = Query(None, description="공개 범위 필터 (private, team, public)"),
    search: Optional[str] = Query(None, description="검색어 (이름, 설명)"),
    tags: Optional[List[str]] = Query(None, description="태그 필터"),
    page: int = Query(1, ge=1, description="페이지 번호"),
    page_size: int = Query(20, ge=1, le=100, description="페이지 크기"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    라이브러리 에이전트 목록 조회

    - 카테고리, 공개 범위, 검색어, 태그로 필터링 가능
    - 페이지네이션 지원
    - 간소화된 정보 반환 (graph 제외)
    """
    try:
        service = LibraryService(db)
        agents, total_count = await service.get_library_agents(
            user_id=current_user.id,
            category=category,
            visibility=visibility,
            search=search,
            tags=tags,
            page=page,
            page_size=page_size
        )

        # 응답 데이터 구성
        agent_list = [
            LibraryAgentResponse(
                id=str(agent.id),
                bot_id=agent.bot_id,
                library_name=agent.library_name,
                library_description=agent.library_description,
                library_category=agent.library_category,
                library_tags=agent.library_tags or [],
                library_visibility=agent.library_visibility,
                version=agent.version,
                node_count=agent.node_count,
                edge_count=agent.edge_count,
                library_published_at=agent.library_published_at
            )
            for agent in agents
        ]

        return {
            "agents": agent_list,
            "total": total_count,
            "page": page,
            "page_size": page_size,
            "total_pages": (total_count + page_size - 1) // page_size
        }

    except Exception as e:
        logger.error(f"Failed to list library agents: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"라이브러리 에이전트 목록 조회 실패: {str(e)}"
        )


@router.get(
    "/agents/{version_id}",
    response_model=LibraryAgentDetailResponse,
    summary="라이브러리 에이전트 상세 조회",
    description="특정 라이브러리 에이전트의 상세 정보를 조회합니다. 워크플로우 그래프를 포함합니다."
)
async def get_library_agent(
    version_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> LibraryAgentDetailResponse:
    """
    라이브러리 에이전트 상세 조회

    - 워크플로우 그래프 포함
    - 스키마 정보 포함
    """
    try:
        service = LibraryService(db)
        agent = await service.get_library_agent_by_id(version_id, current_user.id)

        if not agent:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="라이브러리 에이전트를 찾을 수 없습니다"
            )

        return LibraryAgentDetailResponse(
            id=str(agent.id),
            bot_id=agent.bot_id,
            library_name=agent.library_name,
            library_description=agent.library_description,
            library_category=agent.library_category,
            library_tags=agent.library_tags or [],
            library_visibility=agent.library_visibility,
            version=agent.version,
            node_count=agent.node_count,
            edge_count=agent.edge_count,
            library_published_at=agent.library_published_at,
            graph=WorkflowGraph(**agent.graph) if agent.graph else None,
            environment_variables=agent.environment_variables,
            conversation_variables=agent.conversation_variables,
            input_schema=agent.input_schema,
            output_schema=agent.output_schema,
            port_definitions=agent.port_definitions
        )

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get library agent: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"라이브러리 에이전트 조회 실패: {str(e)}"
        )


# 봇 관련 라우터 (import 기능)
bot_router = APIRouter(
    prefix="/bots",
    tags=["bots"]
)


@bot_router.post(
    "/{bot_id}/import",
    response_model=WorkflowVersionResponse,
    summary="라이브러리 에이전트 가져오기",
    description="라이브러리에서 에이전트를 가져와 봇의 draft 워크플로우로 설정합니다."
)
async def import_library_agent(
    bot_id: str,
    request: LibraryImportRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> WorkflowVersionResponse:
    """
    라이브러리 에이전트 가져오기

    - 소스 에이전트의 그래프, 변수, 스키마를 복사
    - 대상 봇의 기존 draft는 덮어쓰기
    - 가져오기 기록을 agent_import_history에 저장
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

        # 라이브러리 에이전트 가져오기
        service = LibraryService(db)
        draft = await service.import_agent_to_bot(
            source_version_id=request.source_version_id,
            target_bot_id=bot_id,
            user_id=current_user.id,
            user_uuid=current_user.uuid
        )

        return WorkflowVersionResponse(
            id=str(draft.id),
            bot_id=draft.bot_id,
            version=draft.version,
            status=WorkflowVersionStatus(draft.status),
            created_at=draft.created_at,
            updated_at=draft.updated_at,
            published_at=draft.published_at
        )

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to import library agent: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"라이브러리 에이전트 가져오기 실패: {str(e)}"
        )
