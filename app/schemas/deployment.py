from pydantic import BaseModel, Field, validator
from typing import Optional, List, Dict, Any
from datetime import datetime
from uuid import UUID


class WidgetConfigBase(BaseModel):
    """Widget 설정 기본 스키마"""
    theme: str = Field(default="light", description="테마 (light, dark, auto)")
    position: str = Field(default="bottom-right", description="위치 (bottom-right, bottom-left, top-right, top-left)")
    auto_open: bool = Field(default=False, description="자동 열기 여부")
    auto_open_delay: int = Field(default=5000, description="자동 열기 지연 시간 (ms)")
    welcome_message: str = Field(default="안녕하세요! 무엇을 도와드릴까요?", description="환영 메시지")
    placeholder_text: str = Field(default="메시지를 입력하세요...", description="입력 플레이스홀더")
    primary_color: str = Field(default="#0066FF", description="주요 색상 (hex)")
    bot_name: str = Field(default="AI Assistant", description="봇 이름")
    avatar_url: Optional[str] = Field(default=None, description="아바타 이미지 URL")
    show_typing_indicator: bool = Field(default=True, description="타이핑 인디케이터 표시")
    enable_file_upload: bool = Field(default=False, description="파일 업로드 활성화")
    max_file_size_mb: int = Field(default=10, description="최대 파일 크기 (MB)")
    allowed_file_types: List[str] = Field(default=["pdf", "jpg", "png", "doc", "docx"], description="허용 파일 타입")
    enable_feedback: bool = Field(default=True, description="피드백 기능 활성화")
    enable_sound: bool = Field(default=True, description="사운드 알림 활성화")
    save_conversation: bool = Field(default=True, description="대화 저장 활성화")
    conversation_storage: str = Field(default="localStorage", description="대화 저장소 (localStorage, sessionStorage)")
    custom_css: str = Field(default="", description="커스텀 CSS")
    custom_js: str = Field(default="", description="커스텀 JavaScript")

    @validator('theme')
    def validate_theme(cls, v):
        if v not in ["light", "dark", "auto"]:
            raise ValueError("theme must be 'light', 'dark', or 'auto'")
        return v

    @validator('position')
    def validate_position(cls, v):
        if v not in ["bottom-right", "bottom-left", "top-right", "top-left"]:
            raise ValueError("position must be one of: bottom-right, bottom-left, top-right, top-left")
        return v


class DeploymentCreate(BaseModel):
    """봇 배포 생성 요청"""
    status: str = Field(default="published", description="배포 상태 (draft, published, suspended)")
    allowed_domains: Optional[List[str]] = Field(default=None, description="허용된 도메인 리스트")
    widget_config: WidgetConfigBase = Field(..., description="Widget 설정")

    @validator('status')
    def validate_status(cls, v):
        if v not in ["draft", "published", "suspended"]:
            raise ValueError("status must be 'draft', 'published', or 'suspended'")
        return v


class DeploymentUpdate(BaseModel):
    """봇 배포 업데이트 요청"""
    status: Optional[str] = None
    allowed_domains: Optional[List[str]] = None
    widget_config: Optional[WidgetConfigBase] = None


class DeploymentStatusUpdate(BaseModel):
    """봇 배포 상태 변경 요청"""
    status: str = Field(..., description="배포 상태")
    reason: Optional[str] = Field(None, description="상태 변경 사유")

    @validator('status')
    def validate_status(cls, v):
        if v not in ["draft", "published", "suspended"]:
            raise ValueError("status must be 'draft', 'published', or 'suspended'")
        return v


class DeploymentAnalytics(BaseModel):
    """배포 분석 데이터"""
    total_conversations: int
    active_users: int
    avg_response_time_seconds: float
    total_messages: int
    satisfaction_score: float


class DeploymentResponse(BaseModel):
    """봇 배포 응답"""
    deployment_id: UUID
    bot_id: str
    widget_key: str
    status: str
    embed_script: str
    widget_url: str
    allowed_domains: Optional[List[str]]
    widget_config: Dict[str, Any]
    version: int
    analytics: Optional[DeploymentAnalytics] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    last_active_at: Optional[datetime] = None

    class Config:
        from_attributes = True
