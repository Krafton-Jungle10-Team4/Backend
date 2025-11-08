from fastapi import APIRouter, Depends, HTTPException, Request, Header
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from app.core.database import get_db
from app.core.middleware.rate_limit import public_limiter
from app.schemas.widget import (
    WidgetConfigResponse,
    SessionCreateRequest,
    SessionCreateResponse,
    ChatMessageRequest,
    ChatMessageResponse,
    SessionRefreshRequest,
    SessionRefreshResponse,
    FeedbackRequest
)
from app.services.widget_service import WidgetService
from app.core.exceptions import NotFoundException, ForbiddenException, UnauthorizedException

router = APIRouter()


@router.get("/config/{widget_key}", response_model=WidgetConfigResponse)
@public_limiter.limit("1000 per hour")
async def get_widget_config(
    request: Request,
    widget_key: str,
    origin: Optional[str] = Header(None),
    referer: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db)
):
    """
    Widget 설정 조회 (공개 API, 인증 불필요)

    - **widget_key**: Widget Key
    - **origin**: 요청 출처 (헤더, 선택사항)
    - **referer**: Referer URL (헤더, 선택사항)
    """
    try:
        config = await WidgetService.get_widget_config(db, widget_key, origin, referer)
        return config
    except NotFoundException as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenException as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.post("/sessions", response_model=SessionCreateResponse)
@public_limiter.limit("100 per hour")
async def create_session(
    request: Request,
    session_data: SessionCreateRequest,
    origin: Optional[str] = Header(None),
    referer: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db)
):
    """
    Widget 세션 생성 (공개 API, 인증 불필요)

    - **session_data**: 세션 생성 데이터
    - **origin**: 요청 출처 (헤더, 선택사항)
    - **referer**: Referer URL (헤더, 선택사항)
    """
    try:
        session = await WidgetService.create_session(db, session_data, origin, referer)
        return session
    except NotFoundException as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenException as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.post("/chat", response_model=ChatMessageResponse)
@public_limiter.limit("20 per minute")
async def send_message(
    request: Request,
    message_data: ChatMessageRequest,
    authorization: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db)
):
    """
    메시지 전송 (세션 토큰 필요)

    - **message_data**: 메시지 데이터
    - **authorization**: Bearer {SESSION_TOKEN}
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authorization header required")

    session_token = authorization.replace("Bearer ", "")

    try:
        response = await WidgetService.send_message(db, message_data, session_token)
        return response
    except UnauthorizedException as e:
        raise HTTPException(status_code=401, detail=str(e))
    except NotFoundException as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/feedback")
@public_limiter.limit("50 per hour")
async def submit_feedback(
    request: Request,
    feedback_data: FeedbackRequest,
    authorization: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db)
):
    """
    피드백 제출

    - **feedback_data**: 피드백 데이터
    """
    # TODO: 구현
    return {"message": "Feedback submitted successfully"}


@router.post("/config/{widget_key}/track")
@public_limiter.limit("1000 per hour")
async def track_widget_usage(
    request: Request,
    widget_key: str,
    track_data: dict,
    db: AsyncSession = Depends(get_db)
):
    """
    Widget 사용 통계 수집 (선택적 구현)

    - **widget_key**: Widget Key
    - **track_data**: 추적 데이터 (event, metadata 등)
    """
    try:
        await WidgetService.track_usage(db, widget_key, track_data)
        return {"status": "tracked", "message": "Event recorded successfully"}
    except NotFoundException:
        # 404 에러를 반환하지 않고 성공으로 처리 (보안상)
        return {"status": "tracked"}
