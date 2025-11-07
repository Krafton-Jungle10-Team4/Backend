"""
Widget 배포 관련 데이터베이스 모델
"""
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, JSON, ARRAY, Boolean, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from datetime import datetime
import uuid

from app.core.database import Base


class BotDeployment(Base):
    """봇 배포 테이블"""
    __tablename__ = "bot_deployments"

    deployment_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    bot_id = Column(Integer, ForeignKey("bots.id", ondelete="CASCADE"), nullable=False)

    # Widget Key (외부 노출용, 64자)
    widget_key = Column(String(64), unique=True, nullable=False, index=True)

    # 배포 상태: draft, published, suspended
    status = Column(String(20), default="draft", nullable=False)

    # 허용된 도메인 리스트 (와일드카드 지원: *.example.com)
    allowed_domains = Column(ARRAY(String), nullable=True)

    # Widget 설정 (JSON)
    widget_config = Column(JSON, nullable=False)

    # 임베드 스크립트 (캐시용)
    embed_script = Column(Text, nullable=True)

    # 버전 관리
    version = Column(Integer, default=1, nullable=False)

    # 통계 (캐시)
    total_conversations = Column(Integer, default=0)
    total_messages = Column(Integer, default=0)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    last_active_at = Column(DateTime(timezone=True), nullable=True)

    # 관계
    bot = relationship("Bot", back_populates="deployments")
    sessions = relationship("WidgetSession", back_populates="deployment", cascade="all, delete-orphan")

    # 인덱스
    __table_args__ = (
        Index('idx_deployment_bot_status', 'bot_id', 'status'),
        Index('idx_deployment_widget_key', 'widget_key'),
        {"extend_existing": True},
    )


class WidgetSession(Base):
    """Widget 세션 테이블"""
    __tablename__ = "widget_sessions"

    session_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    deployment_id = Column(UUID(as_uuid=True), ForeignKey("bot_deployments.deployment_id", ondelete="CASCADE"))

    # 세션 토큰 (JWT)
    session_token_hash = Column(String(256), unique=True, index=True, nullable=False)
    refresh_token_hash = Column(String(256), unique=True, index=True, nullable=True)

    # 사용자 정보 (선택적)
    user_info = Column(JSON, nullable=True)

    # 브라우저 지문 (중복 방지)
    fingerprint = Column(JSON, nullable=True)
    fingerprint_hash = Column(String(64), index=True, nullable=True)

    # 출처 정보
    origin = Column(String(255), nullable=False)

    # 세션 상태
    is_active = Column(Boolean, default=True)

    # 시간 정보
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    last_activity = Column(DateTime(timezone=True), default=func.now(), onupdate=func.now())
    ended_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)

    # 메타데이터
    session_metadata = Column(JSON, nullable=True)

    # 관계
    deployment = relationship("BotDeployment", back_populates="sessions")
    messages = relationship("WidgetMessage", back_populates="session", cascade="all, delete-orphan")
    events = relationship("WidgetEvent", back_populates="session", cascade="all, delete-orphan")

    # 인덱스
    __table_args__ = (
        Index('idx_session_deployment', 'deployment_id'),
        Index('idx_session_token_hash', 'session_token_hash'),
        Index('idx_session_fingerprint', 'fingerprint_hash'),
        {"extend_existing": True},
    )


class WidgetMessage(Base):
    """Widget 메시지 테이블"""
    __tablename__ = "widget_messages"

    message_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("widget_sessions.session_id", ondelete="CASCADE"))

    # 메시지 역할: user, assistant, system
    role = Column(String(20), nullable=False)

    # 메시지 내용
    content = Column(Text, nullable=False)

    # 메시지 타입: text, file, voice
    message_type = Column(String(20), default="text")

    # 첨부파일 정보
    attachments = Column(JSON, nullable=True)

    # RAG 출처 정보
    sources = Column(JSON, nullable=True)

    # 메타데이터 (컨텍스트, 의도 등)
    message_metadata = Column(JSON, nullable=True)

    # 피드백
    feedback_rating = Column(Integer, nullable=True)
    feedback_comment = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # 관계
    session = relationship("WidgetSession", back_populates="messages")

    # 인덱스
    __table_args__ = (
        Index('idx_message_session', 'session_id'),
        Index('idx_message_created', 'created_at'),
        {"extend_existing": True},
    )


class WidgetEvent(Base):
    """Widget 이벤트 테이블 (분석용)"""
    __tablename__ = "widget_events"

    event_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("widget_sessions.session_id", ondelete="CASCADE"))

    # 이벤트 타입: opened, closed, message_sent, feedback_submitted 등
    event_type = Column(String(50), nullable=False)

    # 이벤트 데이터
    event_data = Column(JSON, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # 관계
    session = relationship("WidgetSession", back_populates="events")

    # 인덱스
    __table_args__ = (
        Index('idx_event_session', 'session_id'),
        Index('idx_event_type', 'event_type'),
        Index('idx_event_created', 'created_at'),
        {"extend_existing": True},
    )
