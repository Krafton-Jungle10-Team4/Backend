from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from uuid import UUID


class WidgetConfigRequest(BaseModel):
    """Widget 설정 요청"""
    widget_key: str = Field(..., description="Widget Key")


class WidgetConfigResponse(BaseModel):
    """Widget 설정 응답"""
    config: Dict[str, Any]
    signature: str
    expires_at: str
    nonce: str


class WidgetSignatureData(BaseModel):
    """Widget 서명 데이터"""
    signature: str
    expires_at: str
    nonce: str
    widget_key: str


class UserInfo(BaseModel):
    """사용자 정보"""
    id: Optional[str] = None
    name: Optional[str] = None
    email: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class Fingerprint(BaseModel):
    """브라우저 지문"""
    user_agent: str
    screen_resolution: str
    timezone: str
    language: str
    platform: str


class SessionContext(BaseModel):
    """세션 컨텍스트"""
    page_url: str
    page_title: str
    referrer: Optional[str] = None
    utm_source: Optional[str] = None
    utm_medium: Optional[str] = None


class SessionCreateRequest(BaseModel):
    """Widget 세션 생성 요청"""
    widget_key: str
    widget_signature: WidgetSignatureData
    user_info: Optional[UserInfo] = None
    fingerprint: Fingerprint
    context: SessionContext


class SessionCreateResponse(BaseModel):
    """Widget 세션 생성 응답"""
    session_id: UUID
    session_token: str
    refresh_token: str
    expires_at: datetime
    ws_url: str
    ws_protocols: List[str]
    features_enabled: Dict[str, bool]


class MessageAttachment(BaseModel):
    """메시지 첨부파일"""
    filename: str
    size: int
    mime_type: str
    url: str


class ChatMessageRequest(BaseModel):
    """채팅 메시지 요청"""
    session_id: UUID
    message: Dict[str, Any] = Field(..., description="메시지 객체 (content, type, attachments)")
    context: Optional[Dict[str, Any]] = None


class Source(BaseModel):
    """RAG 출처"""
    document_id: str
    title: str
    snippet: str
    relevance_score: float


class SuggestedAction(BaseModel):
    """추천 액션"""
    label: str
    action: str
    payload: Dict[str, Any]


class ChatMessageResponse(BaseModel):
    """채팅 메시지 응답"""
    message_id: UUID
    response: Dict[str, Any]
    sources: Optional[List[Source]] = None
    suggested_actions: Optional[List[SuggestedAction]] = None
    timestamp: datetime


class SessionRefreshRequest(BaseModel):
    """세션 갱신 요청"""
    refresh_token: str


class SessionRefreshResponse(BaseModel):
    """세션 갱신 응답"""
    session_token: str
    refresh_token: str
    expires_at: datetime


class FeedbackRequest(BaseModel):
    """피드백 제출 요청"""
    message_id: UUID
    rating: int = Field(..., ge=1, le=5, description="평점 (1-5)")
    comment: Optional[str] = None
    tags: Optional[List[str]] = None
