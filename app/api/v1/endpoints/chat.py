"""
챗봇 API 엔드포인트
"""
import logging
from fastapi import APIRouter, HTTPException, Depends, status, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.chat_service import get_chat_service, ChatService
from app.models.chat import ChatRequest, ChatResponse
from app.core.auth.dependencies import get_current_user_or_team_from_jwt_or_apikey
from app.core.database import get_db
from app.core.middleware.rate_limit import limiter

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("", response_model=ChatResponse, status_code=status.HTTP_200_OK)
@limiter.limit("20/minute")  # 분당 20회 제한 (LLM 비용 고려)
async def chat(
    request: Request,
    chat_request: ChatRequest,
    user_team: tuple = Depends(get_current_user_or_team_from_jwt_or_apikey),
    chat_service: ChatService = Depends(get_chat_service),
    db: AsyncSession = Depends(get_db)
):
    """
    RAG 기반 챗봇 대화

    사용자 질문을 받아 관련 문서를 검색하고 LLM으로 자연스러운 응답 생성

    **인증 방식:**
    - JWT 토큰: 로그인한 사용자 (Authorization: Bearer <token>)
    - API 키: 미로그인 사용자 (X-API-Key: <key>)

    **처리 흐름:**
    1. 사용자 질문 임베딩 생성
    2. 벡터 유사도 검색
    3. 관련 문서 컨텍스트 구성
    4. LLM API 호출
    5. 응답 및 출처 정보 반환

    **에러 코드:**
    - 401: 인증 실패 (JWT 또는 API 키 누락/유효하지 않음)
    - 400: 잘못된 요청 (메시지 길이 초과 등)
    - 500: 서버 오류 (LLM API 실패, 검색 실패 등)
    """
    user, team = user_team
    auth_method = "JWT" if user else "API_KEY"
    logger.info(f"[Chat] 요청: '{chat_request.message[:50]}...' (session: {chat_request.session_id}, team: {team.uuid}, auth: {auth_method}, bot_id: {chat_request.bot_id})")

    try:
        response = await chat_service.generate_response(chat_request, team_uuid=team.uuid, db=db)

        logger.info(
            f"[Chat] 응답 생성 완료: {response.retrieved_chunks}개 청크 참조, "
            f"{len(response.response)}자 응답"
        )

        return response

    except ValueError as e:
        # 비즈니스 로직 에러
        logger.error(f"[Chat] 검증 실패: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )

    except Exception as e:
        # 시스템 에러 (상세 정보는 로그에만 기록, 클라이언트에는 일반 메시지)
        logger.error(f"[Chat] 응답 생성 실패: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="응답 생성 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요."
        )


@router.get("/health", status_code=status.HTTP_200_OK)
async def chat_health_check():
    """챗봇 서비스 헬스 체크"""
    return {
        "status": "healthy",
        "service": "chat",
        "message": "챗봇 서비스가 정상 작동 중입니다"
    }
