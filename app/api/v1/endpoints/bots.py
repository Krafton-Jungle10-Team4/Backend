"""봇 관리 API 엔드포인트"""
import logging
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.auth.dependencies import get_current_user_from_jwt
from app.models.user import User, TeamMember
from app.models.bot import Bot
from app.schemas.bot import CreateBotRequest, BotResponse, BotListResponse, UpdateBotRequest, ErrorResponse
from app.services.bot_service import get_bot_service, BotService

logger = logging.getLogger(__name__)

router = APIRouter()


async def get_user_team(user: User, db: AsyncSession):
    """
    사용자의 팀 조회

    Args:
        user: 현재 사용자
        db: 데이터베이스 세션

    Returns:
        사용자가 속한 팀

    Raises:
        HTTPException: 팀을 찾을 수 없는 경우
    """
    result = await db.execute(
        select(TeamMember).where(TeamMember.user_id == user.id)
    )
    membership = result.scalar_one_or_none()

    if not membership:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="사용자가 속한 팀을 찾을 수 없습니다"
        )

    result = await db.execute(
        select(TeamMember.team_id).where(TeamMember.id == membership.id)
    )
    team_id = result.scalar_one()

    return team_id


@router.post(
    "",
    response_model=BotResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        201: {"description": "봇 생성 성공"},
        400: {
            "description": "잘못된 요청",
            "model": ErrorResponse
        },
        401: {"description": "인증 실패"},
        500: {"description": "서버 오류"}
    },
    summary="봇 생성",
    description="""
    새로운 봇을 생성합니다.

    **요청 필드:**
    - `name` (필수): 봇 이름 (1-100자)
    - `goal` (선택): 봇의 목표 (최대 500자)
    - `personality` (선택): 봇의 성격/어조 (최대 2000자)
    - `knowledge` (선택): 봇의 지식 항목 배열

    **인증:**
    - JWT Bearer 토큰 필요 (Authorization: Bearer {token})

    **성공 응답:**
    - 생성된 봇의 정보를 반환합니다
    - bot_id는 "bot_{timestamp}_{random}" 형식으로 자동 생성됩니다
    """
)
async def create_bot(
    request: CreateBotRequest,
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
        # 1. 사용자의 팀 ID 조회
        team_id = await get_user_team(user, db)

        # 2. 봇 생성
        bot = await bot_service.create_bot(request, team_id, db)

        # 3. 응답 변환
        response = BotResponse.from_bot(bot)

        logger.info(f"봇 생성 성공: bot_id={bot.bot_id}, user={user.email}")

        return response

    except ValueError as e:
        logger.error(f"봇 생성 검증 실패: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )

    except Exception as e:
        logger.error(f"봇 생성 중 오류 발생: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="봇 생성 중 오류가 발생했습니다"
        )


@router.get(
    "",
    response_model=BotListResponse,
    status_code=status.HTTP_200_OK,
    summary="봇 목록 조회",
    description="""
    팀의 모든 봇 목록을 조회합니다.

    **인증:**
    - JWT Bearer 토큰 필요 (Authorization: Bearer {token})

    **응답:**
    - 팀에 속한 모든 봇 목록
    - 생성일 기준 내림차순 정렬
    """
)
async def get_bots(
    user: User = Depends(get_current_user_from_jwt),
    db: AsyncSession = Depends(get_db),
    bot_service: BotService = Depends(get_bot_service)
):
    """팀의 모든 봇 목록 조회"""
    logger.info(f"봇 목록 조회: user={user.email}")

    try:
        # 1. 사용자의 팀 ID 조회
        team_id = await get_user_team(user, db)

        # 2. 봇 목록 조회
        bots = await bot_service.get_bots_by_team(team_id, db)

        # 3. 응답 변환
        bot_responses = [BotResponse.from_bot(bot) for bot in bots]

        return BotListResponse(bots=bot_responses, total=len(bot_responses))

    except Exception as e:
        logger.error(f"봇 목록 조회 실패: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="봇 목록 조회 중 오류가 발생했습니다"
        )


@router.get(
    "/{bot_id}",
    response_model=BotResponse,
    status_code=status.HTTP_200_OK,
    summary="봇 상세 조회",
    description="""
    특정 봇의 상세 정보를 조회합니다.

    **인증:**
    - JWT Bearer 토큰 필요 (Authorization: Bearer {token})

    **응답:**
    - 봇의 상세 정보
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
        # 1. 사용자의 팀 ID 조회
        team_id = await get_user_team(user, db)

        # 2. 봇 조회
        bot = await bot_service.get_bot_by_id(bot_id, team_id, db)

        if not bot:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"봇을 찾을 수 없습니다: {bot_id}"
            )

        # 3. 응답 변환
        return BotResponse.from_bot(bot)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"봇 조회 실패: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="봇 조회 중 오류가 발생했습니다"
        )


@router.patch(
    "/{bot_id}",
    response_model=BotResponse,
    status_code=status.HTTP_200_OK,
    summary="봇 정보 수정",
    description="""
    봇의 정보를 수정합니다.

    **인증:**
    - JWT Bearer 토큰 필요 (Authorization: Bearer {token})

    **요청 필드 (모두 선택):**
    - `name`: 봇 이름
    - `goal`: 봇의 목표
    - `personality`: 봇의 성격/어조
    - `avatar`: 봇 아바타 URL
    - `status`: 봇 상태

    **응답:**
    - 수정된 봇의 정보
    """
)
async def update_bot(
    bot_id: str,
    request: UpdateBotRequest,
    user: User = Depends(get_current_user_from_jwt),
    db: AsyncSession = Depends(get_db),
    bot_service: BotService = Depends(get_bot_service)
):
    """봇 정보 수정"""
    logger.info(f"봇 수정: bot_id={bot_id}, user={user.email}")

    try:
        # 1. 사용자의 팀 ID 조회
        team_id = await get_user_team(user, db)

        # 2. 봇 수정
        bot = await bot_service.update_bot(bot_id, team_id, request, db)

        # 3. 응답 변환
        return BotResponse.from_bot(bot)

    except ValueError as e:
        logger.error(f"봇 수정 검증 실패: {e}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"봇 수정 실패: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="봇 수정 중 오류가 발생했습니다"
        )


@router.delete(
    "/{bot_id}",
    status_code=status.HTTP_200_OK,
    summary="봇 삭제",
    description="""
    봇을 삭제합니다.

    **인증:**
    - JWT Bearer 토큰 필요 (Authorization: Bearer {token})

    **응답:**
    - 삭제 성공 메시지
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
        # 1. 사용자의 팀 ID 조회
        team_id = await get_user_team(user, db)

        # 2. 봇 삭제
        await bot_service.delete_bot(bot_id, team_id, db)

        return {
            "status": "success",
            "message": f"봇이 삭제되었습니다: {bot_id}"
        }

    except ValueError as e:
        logger.error(f"봇 삭제 검증 실패: {e}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
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
