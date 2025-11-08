"""봇 관리 API 엔드포인트"""
import logging
from fastapi import APIRouter, Depends, HTTPException, status, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional

from app.core.database import get_db
from app.core.auth.dependencies import get_current_user_from_jwt
from app.models.user import User
from app.models.bot import Bot, BotStatus
from app.schemas.bot import (
    CreateBotRequest, BotResponse, BotListResponse, ErrorResponse,
    # 새로운 명세서 준수 스키마
    BotListItemResponse, BotListResponseV2, PaginationInfo,
    BotDetailResponse, CreateBotRequestV2,
    UpdateBotRequestPut, UpdateBotRequestPatch,
    StatusToggleRequest, StatusToggleResponse
)
from app.services.bot_service import get_bot_service, BotService

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post(
    "",
    response_model=BotDetailResponse,  # 명세서 준수: data 객체로 감싸기
    status_code=status.HTTP_201_CREATED,
    responses={
        201: {"description": "봇 생성 성공"},
        400: {
            "description": "잘못된 요청",
            "model": ErrorResponse
        },
        401: {"description": "인증 실패"},
        422: {"description": "Workflow 구조 검증 실패"},
        500: {"description": "서버 오류"}
    },
    summary="봇 생성 (명세서 준수)",
    description="""
    새로운 봇을 생성합니다.

    **요청 필드:**
    - `name` (필수): 봇 이름 (1-100자)
    - `description` (선택): 봇 설명
    - `workflow` (필수): Workflow 정의

    **인증:**
    - JWT Bearer 토큰 필요 (Authorization: Bearer {token})

    **성공 응답:**
    - data 객체 내에 생성된 봇 정보와 workflow 포함
    - bot_id는 "bot_{timestamp}_{random}" 형식으로 자동 생성됩니다
    """
)
async def create_bot(
    request: CreateBotRequest,  # 기존 스키마도 호환성 유지
    user: User = Depends(get_current_user_from_jwt),
    db: AsyncSession = Depends(get_db),
    bot_service: BotService = Depends(get_bot_service)
):
    """
    봇 생성 API

    프론트엔드 Setup 플로우에서 수집한 데이터로 봇을 생성합니다.
    """
    logger.info(f"봇 생성 API 호출: user={user.email}, name={request.name}")

    try:
        # 봇 생성 (사용자 ID로 소유권 설정)
        bot = await bot_service.create_bot(request, user.id, db)

        # 명세서 준수 응답 변환
        return BotDetailResponse.from_bot(bot)

    except ValueError as e:
        logger.error(f"봇 생성 검증 실패: {e}")
        # Workflow 검증 실패인 경우
        if "workflow" in str(e).lower():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "error": {
                        "code": "WORKFLOW_VALIDATION_ERROR",
                        "message": "Workflow 구조 검증 실패",
                        "details": str(e)
                    }
                }
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error": {
                        "code": "VALIDATION_ERROR",
                        "message": "스키마 검증 실패",
                        "details": str(e)
                    }
                }
            )

    except Exception as e:
        logger.error(f"봇 생성 중 오류 발생: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": {
                    "code": "INTERNAL_SERVER_ERROR",
                    "message": "봇 생성 중 오류가 발생했습니다"
                }
            }
        )


@router.get(
    "",
    response_model=BotListResponseV2,  # 새로운 스키마 사용
    status_code=status.HTTP_200_OK,
    summary="봇 목록 조회 (명세서 준수)",
    description="""
    사용자의 봇 목록을 페이지네이션과 함께 조회합니다.

    **인증:**
    - JWT Bearer 토큰 필요 (Authorization: Bearer {token})

    **Query Parameters:**
    - page: 페이지 번호 (기본값: 1)
    - limit: 페이지당 항목 수 (기본값: 10)
    - sort: 정렬 기준 (기본값: updatedAt:desc)
    - search: 검색어 (봇 이름/설명에서 검색)

    **응답:**
    - data: 봇 목록 (nodeCount, edgeCount 포함)
    - pagination: 페이지네이션 정보
    """
)
async def get_bots(
    page: int = Query(1, ge=1, description="페이지 번호"),
    limit: int = Query(10, ge=1, le=100, description="페이지당 항목 수"),
    sort: str = Query("updatedAt:desc", description="정렬 기준 (field:asc/desc)"),
    search: Optional[str] = Query(None, description="검색어"),
    user: User = Depends(get_current_user_from_jwt),
    db: AsyncSession = Depends(get_db),
    bot_service: BotService = Depends(get_bot_service)
):
    """사용자의 봇 목록 조회 (페이지네이션 지원)"""
    logger.info(f"봇 목록 조회: user={user.email}, page={page}, limit={limit}, search={search}")

    try:
        # 페이지네이션과 검색을 적용한 봇 목록 조회
        bots, total = await bot_service.get_bots_with_pagination(
            user_id=user.id,
            db=db,
            page=page,
            limit=limit,
            sort=sort,
            search=search
        )

        # 응답 생성
        bot_items = [BotListItemResponse.from_bot(bot) for bot in bots]

        # 총 페이지 수 계산
        total_pages = (total + limit - 1) // limit if total > 0 else 1

        return BotListResponseV2(
            data=bot_items,
            pagination=PaginationInfo(
                page=page,
                limit=limit,
                total=total,
                totalPages=total_pages
            )
        )

    except Exception as e:
        logger.error(f"봇 목록 조회 실패: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="봇 목록 조회 중 오류가 발생했습니다"
        )


@router.get(
    "/{bot_id}",
    response_model=BotDetailResponse,  # 새로운 스키마 사용
    status_code=status.HTTP_200_OK,
    summary="봇 상세 조회 (명세서 준수)",
    description="""
    특정 봇의 상세 정보와 workflow를 조회합니다.

    **인증:**
    - JWT Bearer 토큰 필요 (Authorization: Bearer {token})

    **응답:**
    - data 객체 내에 봇의 상세 정보와 workflow 포함
    """
)
async def get_bot(
    bot_id: str,
    user: User = Depends(get_current_user_from_jwt),
    db: AsyncSession = Depends(get_db),
    bot_service: BotService = Depends(get_bot_service)
):
    """특정 봇 상세 정보 조회"""
    logger.info(f"봇 조회: bot_id={bot_id}, user={user.email}")

    try:
        # 봇 조회 (workflow 포함)
        bot = await bot_service.get_bot_by_id(bot_id, user.id, db, include_workflow=True)

        if not bot:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "error": {
                        "code": "NOT_FOUND",
                        "message": f"Bot이 존재하지 않음: {bot_id}"
                    }
                }
            )

        # 명세서 준수 응답 변환
        return BotDetailResponse.from_bot(bot)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"봇 조회 실패: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="봇 조회 중 오류가 발생했습니다"
        )


@router.put(
    "/{bot_id}",
    response_model=BotDetailResponse,  # 명세서 준수: workflow 포함
    status_code=status.HTTP_200_OK,
    summary="봇 정보 수정 (PUT - 명세서 준수)",
    description="""
    봇의 정보를 수정합니다 (전체 업데이트).

    **인증:**
    - JWT Bearer 토큰 필요 (Authorization: Bearer {token})

    **요청 필드 (모두 필수):**
    - `name`: 봇 이름 (필수)
    - `description`: 봇 설명 (선택)
    - `workflow`: Workflow 정의 (필수, workflowRevision 포함)

    **응답:**
    - data 객체 내에 수정된 봇 정보와 workflow 포함
    """
)
async def update_bot_put(
    bot_id: str,
    request: UpdateBotRequestPut,  # PUT용 필수 필드 스키마
    user: User = Depends(get_current_user_from_jwt),
    db: AsyncSession = Depends(get_db),
    bot_service: BotService = Depends(get_bot_service)
):
    """봇 정보 수정 (PUT)"""
    logger.info(f"봇 수정 (PUT): bot_id={bot_id}, user={user.email}")

    try:
        # workflow revision 체크 (있는 경우)
        if request.workflow:
            bot = await bot_service.get_bot_by_id(bot_id, user.id, db)
            if not bot:
                raise ValueError(f"봇을 찾을 수 없습니다: {bot_id}")

            # Revision 충돌 체크 (간단한 구현)
            if hasattr(request.workflow, 'workflowRevision'):
                current_workflow = bot.workflow if isinstance(bot.workflow, dict) else {}
                current_revision = current_workflow.get('workflowRevision', 0)
                requested_revision = getattr(request.workflow, 'workflowRevision', 0)

                if current_revision != requested_revision:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail={
                            "error": {
                                "code": "REVISION_CONFLICT",
                                "message": "Workflow revision이 최신이 아닙니다. 다시 불러온 후 수정해주세요.",
                                "currentRevision": current_revision,
                                "requestedRevision": requested_revision
                            }
                        }
                    )

        # 봇 수정
        bot = await bot_service.update_bot(bot_id, user.id, request, db)

        # 명세서 준수 응답 변환 (workflow 포함)
        return BotDetailResponse.from_bot(bot)

    except HTTPException:
        raise
    except ValueError as e:
        logger.error(f"봇 수정 검증 실패: {e}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": {
                    "code": "NOT_FOUND",
                    "message": str(e)
                }
            }
        )
    except Exception as e:
        logger.error(f"봇 수정 실패: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="봇 수정 중 오류가 발생했습니다"
        )


@router.patch(
    "/{bot_id}",
    response_model=BotDetailResponse,  # 명세서 준수
    status_code=status.HTTP_200_OK,
    summary="봇 정보 수정 (PATCH - 부분 수정)",
    description="""
    봇의 정보를 부분적으로 수정합니다.

    **인증:**
    - JWT Bearer 토큰 필요 (Authorization: Bearer {token})

    **요청 필드 (모두 선택):**
    - `name`: 봇 이름
    - `description`: 봇 설명
    - `workflow`: Workflow 정의

    **응답:**
    - data 객체 내에 수정된 봇 정보와 workflow 포함
    """
)
async def update_bot_patch(
    bot_id: str,
    request: UpdateBotRequestPatch,  # PATCH용 선택 필드 스키마
    user: User = Depends(get_current_user_from_jwt),
    db: AsyncSession = Depends(get_db),
    bot_service: BotService = Depends(get_bot_service)
):
    """봇 정보 수정 (PATCH)"""
    logger.info(f"봇 수정 (PATCH): bot_id={bot_id}, user={user.email}")

    try:
        # 봇 수정
        bot = await bot_service.update_bot(bot_id, user.id, request, db)

        # 명세서 준수 응답 변환 (workflow 포함)
        return BotDetailResponse.from_bot(bot)

    except ValueError as e:
        logger.error(f"봇 수정 검증 실패: {e}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": {
                    "code": "NOT_FOUND",
                    "message": str(e)
                }
            }
        )
    except Exception as e:
        logger.error(f"봇 수정 실패: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="봇 수정 중 오류가 발생했습니다"
        )


@router.patch(
    "/{bot_id}/status",
    response_model=StatusToggleResponse,
    status_code=status.HTTP_200_OK,
    summary="봇 상태 토글",
    description="""
    봇의 활성화 상태를 변경합니다.

    **인증:**
    - JWT Bearer 토큰 필요 (Authorization: Bearer {token})

    **요청:**
    - isActive: boolean (활성화 여부)

    **응답:**
    - data 객체 내에 id, isActive, updatedAt 포함
    """
)
async def toggle_bot_status(
    bot_id: str,
    request: StatusToggleRequest,
    user: User = Depends(get_current_user_from_jwt),
    db: AsyncSession = Depends(get_db),
    bot_service: BotService = Depends(get_bot_service)
):
    """봇 상태 토글"""
    logger.info(f"봇 상태 토글: bot_id={bot_id}, is_active={request.isActive}, user={user.email}")

    try:
        # 봇 상태 토글
        bot = await bot_service.toggle_bot_status(
            bot_id=bot_id,
            user_id=user.id,
            is_active=request.isActive,
            db=db
        )

        # 응답 생성
        return StatusToggleResponse.from_bot(bot)

    except ValueError as e:
        logger.error(f"봇 상태 토글 실패: {e}")
        # Workflow 검증 실패 등
        if "Workflow 검증 실패" in str(e):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "error": {
                        "code": "WORKFLOW_INVALID",
                        "message": "Workflow 검증 실패로 활성화할 수 없습니다.",
                        "details": str(e)
                    }
                }
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "error": {
                        "code": "NOT_FOUND",
                        "message": str(e)
                    }
                }
            )
    except Exception as e:
        logger.error(f"봇 상태 토글 오류: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="봇 상태 변경 중 오류가 발생했습니다"
        )


@router.delete(
    "/{bot_id}",
    status_code=status.HTTP_204_NO_CONTENT,  # 명세서 준수: 204 No Content
    summary="봇 삭제",
    description="""
    봇을 삭제합니다.

    **인증:**
    - JWT Bearer 토큰 필요 (Authorization: Bearer {token})

    **응답:**
    - 204 No Content (빈 응답)
    """
)
async def delete_bot(
    bot_id: str,
    user: User = Depends(get_current_user_from_jwt),
    db: AsyncSession = Depends(get_db),
    bot_service: BotService = Depends(get_bot_service)
):
    """봇 삭제"""
    logger.info(f"봇 삭제: bot_id={bot_id}, user={user.email}")

    try:
        # 봇 조회 (활성화 상태 확인용)
        bot = await bot_service.get_bot_by_id(bot_id, user.id, db)

        if not bot:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "error": {
                        "code": "NOT_FOUND",
                        "message": f"Bot이 존재하지 않음: {bot_id}"
                    }
                }
            )

        # 3. 봇 삭제 (활성화 상태와 무관하게 삭제 허용)
        await bot_service.delete_bot(bot_id, user.id, db)

        # 204 No Content는 응답 본문이 없어야 함
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    except HTTPException:
        raise
    except ValueError as e:
        logger.error(f"봇 삭제 검증 실패: {e}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": {
                    "code": "NOT_FOUND",
                    "message": str(e)
                }
            }
        )
    except Exception as e:
        logger.error(f"봇 삭제 실패: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="봇 삭제 중 오류가 발생했습니다"
        )


@router.get(
    "/health",
    status_code=status.HTTP_200_OK,
    summary="봇 서비스 헬스 체크"
)
async def bots_health_check():
    """봇 서비스 헬스 체크"""
    return {
        "status": "healthy",
        "service": "bots",
        "message": "봇 서비스가 정상 작동 중입니다"
    }
