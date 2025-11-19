"""
봇 API 키 관련 데이터베이스 모델

RESTful API 배포 기능을 위한 API 키 관리 모델
"""
from sqlalchemy import Column, String, Integer, Boolean, DateTime, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from datetime import datetime
import uuid

from app.core.database import Base


class BotAPIKey(Base):
    """봇 워크플로우 API 키 테이블"""
    __tablename__ = "bot_api_keys"

    # Primary Key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Foreign Keys
    bot_id = Column(String(50), ForeignKey('bots.bot_id', ondelete='CASCADE'), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    workflow_version_id = Column(
        UUID(as_uuid=True),
        ForeignKey('bot_workflow_versions.id', ondelete='SET NULL'),
        nullable=True
    )

    # API Key Information (SHA-256)
    name = Column(String(100), nullable=False)
    description = Column(String(500), nullable=True)
    key_hash = Column(String(64), unique=True, nullable=False, index=True)  # SHA-256 (64 chars)
    key_prefix = Column(String(12), nullable=False)  # 처음 12자 (표시용)
    key_suffix = Column(String(4), nullable=False)   # 마지막 4자 (표시용)

    # Permissions
    permissions = Column(JSONB, nullable=False, server_default='{"run": true, "read": true, "stop": true}')

    # Rate Limits (API 키별)
    rate_limit_per_minute = Column(Integer, default=60, nullable=False)
    rate_limit_per_hour = Column(Integer, default=1000, nullable=False)
    rate_limit_per_day = Column(Integer, default=10000, nullable=False)

    # Quotas
    monthly_request_quota = Column(Integer, nullable=True)  # NULL = unlimited
    monthly_token_quota = Column(Integer, nullable=True)

    # Lifecycle
    expires_at = Column(DateTime(timezone=True), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    last_used_at = Column(DateTime(timezone=True), nullable=True)

    # Binding (워크플로우 버전 바인딩)
    bind_to_latest_published = Column(Boolean, default=True, nullable=False)

    # Metadata
    allowed_ips = Column(JSONB, nullable=True)  # ["192.168.1.0/24"]
    metadata = Column(JSONB, nullable=False, server_default='{}')

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # 관계
    bot = relationship("Bot", foreign_keys=[bot_id])
    user = relationship("User")
    workflow_version = relationship("BotWorkflowVersion", foreign_keys=[workflow_version_id])
    execution_runs = relationship("WorkflowExecutionRun", back_populates="bot_api_key")
    usage_records = relationship("APIKeyUsage", back_populates="api_key", cascade="all, delete-orphan")

    # 인덱스
    __table_args__ = (
        Index('idx_bot_api_key_hash', 'key_hash'),
        Index('idx_bot_api_key_bot_active', 'bot_id', 'is_active'),
        Index('idx_bot_api_key_user', 'user_id'),
    )

    def __repr__(self):
        return f"<BotAPIKey(id={self.id}, name={self.name}, bot_id={self.bot_id})>"


class APIKeyUsage(Base):
    """API 키 사용량 집계 테이블"""
    __tablename__ = "api_key_usage"

    # Primary Key
    id = Column(Integer, primary_key=True, autoincrement=True)
    api_key_id = Column(
        UUID(as_uuid=True),
        ForeignKey('bot_api_keys.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )

    # Time Window (시간 단위 집계)
    timestamp_hour = Column(DateTime(timezone=True), nullable=False, index=True)

    # Request Metrics
    total_requests = Column(Integer, default=0, nullable=False)
    successful_requests = Column(Integer, default=0, nullable=False)
    failed_requests = Column(Integer, default=0, nullable=False)

    # Workflow Execution Metrics
    workflow_runs_created = Column(Integer, default=0, nullable=False)
    workflow_runs_completed = Column(Integer, default=0, nullable=False)
    workflow_runs_failed = Column(Integer, default=0, nullable=False)

    # Token Usage
    prompt_tokens = Column(Integer, default=0, nullable=False)
    completion_tokens = Column(Integer, default=0, nullable=False)
    total_tokens = Column(Integer, default=0, nullable=False)

    # Performance
    avg_latency_ms = Column(Integer, nullable=True)
    p95_latency_ms = Column(Integer, nullable=True)

    # 관계
    api_key = relationship("BotAPIKey", back_populates="usage_records")

    # 제약 및 인덱스
    __table_args__ = (
        Index('idx_usage_key_time', 'api_key_id', 'timestamp_hour'),
        # 시간별 중복 방지
        Index('uq_usage_key_hour', 'api_key_id', 'timestamp_hour', unique=True),
    )

    def __repr__(self):
        return f"<APIKeyUsage(api_key_id={self.api_key_id}, timestamp_hour={self.timestamp_hour})>"

