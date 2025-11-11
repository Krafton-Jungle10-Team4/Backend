"""
챗봇 API 엔드포인트
"""
import logging
import json
from typing import AsyncGenerator
from fastapi import APIRouter, HTTPException, Depends, status, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.chat_service import get_chat_service, ChatService
from app.models.chat import ChatRequest, ChatResponse
from app.core.auth.dependencies import get_current_user_from_jwt_or_apikey
from app.models.user import User
from app.core.database import get_db
from app.core.middleware.rate_limit import limiter

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("", response_model=ChatResponse, status_code=status.HTTP_200_OK)
@limiter.limit("20/minute")  # 분당 20회 제한 (LLM 비용 고려)
async def chat(
    request: Request,
    chat_request: ChatRequest,
    user: User = Depends(get_current_user_from_jwt_or_apikey),
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
    logger.info(f"[Chat] 요청: '{chat_request.message[:50]}...' (session: {chat_request.session_id}, user: {user.uuid}, bot_id: {chat_request.bot_id})")

    try:
        response = await chat_service.generate_response(chat_request, user_uuid=str(user.uuid), db=db)

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


@router.post("/stream")
@limiter.limit("20/minute")
async def chat_stream(
    request: Request,
    chat_request: ChatRequest,
    user: User = Depends(get_current_user_from_jwt_or_apikey),
    chat_service: ChatService = Depends(get_chat_service),
    db: AsyncSession = Depends(get_db)
):
    """
    RAG 기반 챗봇 대화 (SSE 스트리밍)

    Server-Sent Events 형식으로 응답을 실시간 스트리밍합니다.
    기존 `/chat` 엔드포인트와 동일한 인증 방식 지원 (JWT 또는 API 키)

    **SSE 이벤트 형식:**
    - `data: {"type":"content","data":"텍스트 청크"}\\n\\n`
    - `data: {"type":"sources","data":[...]}\\n\\n`
    - `data: {"type":"error","code":"...","message":"..."}\\n\\n`
    - `data: [DONE]\\n\\n`

    **처리 플로우:**
    1. 사용자 질문 임베딩 생성
    2. 벡터 유사도 검색 (비동기)
    3. 관련 문서 컨텍스트 구성
    4. LLM 스트리밍 API 호출
    5. 토큰 단위로 실시간 전송
    6. 출처 정보 전송 (선택적)
    7. 완료 신호 전송

    **에러 처리:**
    - 에러 발생 시 ErrorEvent를 SSE로 전송하고 연결 종료
    - DoneEvent 없이 종료됨

    **예시 curl 요청:**
    ```bash
    curl -N -X POST https://api.snapagent.shop/api/v1/chat/stream \\
      -H "Authorization: Bearer <jwt_token>" \\
      -H "Content-Type: application/json" \\
      -d '{
        "message": "FastAPI의 주요 특징은?",
        "bot_id": "bot_123",
        "temperature": 0.7,
        "max_tokens": 1000,
        "include_sources": true
      }'
    ```
    """
    logger.info(
        f"[ChatStream] 요청: '{chat_request.message[:50]}...' "
        f"(session: {chat_request.session_id}, user: {user.uuid}, bot_id: {chat_request.bot_id})"
    )

    async def event_generator() -> AsyncGenerator[str, None]:
        """SSE 이벤트 스트림 생성기"""
        def is_error_event(event_json: str) -> bool:
            try:
                payload = json.loads(event_json)
            except json.JSONDecodeError:
                return False
            return payload.get("type") == "error"

        error_sent = False

        try:
            # 스트리밍 응답 생성
            async for event_json in chat_service.generate_response_stream(
                request=chat_request,
                user_uuid=str(user.uuid),
                db=db
            ):
                # SSE 형식: "data: {json}\n\n"
                yield f"data: {event_json}\n\n"

                if is_error_event(event_json):
                    error_sent = True
                    break

        except Exception as e:
            # 예상치 못한 에러 (ChatService에서 처리하지 못한 경우)
            logger.error(f"[ChatStream] 스트리밍 실패: {e}", exc_info=True)

            from app.models.chat import ErrorEvent, ErrorCode
            error_event = ErrorEvent(
                code=ErrorCode.UNKNOWN_ERROR,
                message="응답 생성 중 오류가 발생했습니다"
            )
            yield f"data: {json.dumps(error_event.model_dump(), ensure_ascii=False)}\n\n"
            error_sent = True

        if not error_sent:
            # 완료 이벤트 (문자열 리터럴)
            yield "data: [DONE]\n\n"
            logger.info("[ChatStream] 스트리밍 완료")

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"  # Nginx 버퍼링 비활성화
        }
    )


@router.get("/health", status_code=status.HTTP_200_OK)
async def chat_health_check():
    """챗봇 서비스 헬스 체크"""
    return {
        "status": "healthy",
        "service": "chat",
        "message": "챗봇 서비스가 정상 작동 중입니다"
    }
