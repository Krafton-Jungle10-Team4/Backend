"""
챗봇 API 엔드포인트
"""
import logging
from fastapi import APIRouter, HTTPException, Depends, status
from fastapi.responses import StreamingResponse
from app.services.chat_service import get_chat_service, ChatService
from app.models.chat import ChatRequest, ChatResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=ChatResponse, status_code=status.HTTP_200_OK)
async def chat(
    request: ChatRequest,
    chat_service: ChatService = Depends(get_chat_service)
):
    """
    RAG 기반 챗봇 대화

    사용자 질문을 받아 관련 문서를 검색하고 LLM으로 자연스러운 응답 생성

    **처리 흐름:**
    1. 사용자 질문 임베딩 생성
    2. 벡터 유사도 검색
    3. 관련 문서 컨텍스트 구성
    4. LLM API 호출
    5. 응답 및 출처 정보 반환

    **에러 코드:**
    - 400: 잘못된 요청 (메시지 길이 초과 등)
    - 500: 서버 오류 (LLM API 실패, 검색 실패 등)
    """
    logger.info(f"[Chat] 요청: '{request.message[:50]}...' (session: {request.session_id})")

    try:
        response = await chat_service.generate_response(request)

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
        # 시스템 에러
        logger.error(f"[Chat] 응답 생성 실패: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"응답 생성 중 오류가 발생했습니다: {str(e)}"
        )


@router.get("/health", status_code=status.HTTP_200_OK)
async def chat_health_check():
    """챗봇 서비스 헬스 체크"""
    return {
        "status": "healthy",
        "service": "chat",
        "message": "챗봇 서비스가 정상 작동 중입니다"
    }
