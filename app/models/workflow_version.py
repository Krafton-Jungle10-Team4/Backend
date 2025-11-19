"""
워크플로우 V2 버전 관리 모델
"""
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Integer, Text, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func, text
from datetime import datetime
import uuid

from app.core.database import Base


class BotWorkflowVersion(Base):
    """봇 워크플로우 버전 테이블"""
    __tablename__ = "bot_workflow_versions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    bot_id = Column(String(50), ForeignKey('bots.bot_id', ondelete='CASCADE'), nullable=False, index=True)
    version = Column(String(50), nullable=False)
    status = Column(String(20), nullable=False)

    # 워크플로우 그래프 및 변수
    graph = Column(JSONB, nullable=False)
    environment_variables = Column(JSONB, default={})
    conversation_variables = Column(JSONB, default={})
    features = Column(JSONB, default={})

    # 메타데이터
    created_by = Column(String(36), ForeignKey('users.uuid'))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    published_at = Column(DateTime(timezone=True), nullable=True)

    # 라이브러리 관련 필드 (신규)
    library_name = Column(String(255), nullable=True)
    library_description = Column(Text, nullable=True)
    library_category = Column(String(100), nullable=True, index=True)
    library_tags = Column(JSONB, nullable=True)
    library_visibility = Column(String(20), nullable=True, index=True)
    is_in_library = Column(Boolean, default=False, nullable=False, index=True)
    library_published_at = Column(DateTime(timezone=True), nullable=True, index=True)

    # 통계 및 스키마 정보 (신규)
    input_schema = Column(JSONB, nullable=True)
    output_schema = Column(JSONB, nullable=True)
    node_count = Column(Integer, nullable=True)
    edge_count = Column(Integer, nullable=True)
    port_definitions = Column(JSONB, nullable=True)

    # API 배포 관련 필드
    api_endpoint_alias = Column(String(100), nullable=True, unique=True, index=True)
    api_default_response_mode = Column(String(20), nullable=False, server_default='blocking')

    # 관계
    bot = relationship("Bot", back_populates="workflow_versions")
    execution_runs = relationship("WorkflowExecutionRun", back_populates="workflow_version", cascade="all, delete-orphan")
    deployments = relationship("BotDeployment", back_populates="workflow_version")

    # 인덱스 및 제약
    __table_args__ = (
        Index('ix_bot_workflow_versions_bot_version', 'bot_id', 'version'),
        Index('ix_bot_workflow_versions_bot_status', 'bot_id', 'status'),
        Index('uq_bot_workflow_versions_draft', 'bot_id', unique=True,
              postgresql_where=text("status = 'draft'")),
        {"extend_existing": True},
    )


class WorkflowExecutionRun(Base):
    """워크플로우 실행 기록 테이블"""
    __tablename__ = "workflow_execution_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    bot_id = Column(String(50), ForeignKey('bots.bot_id', ondelete='CASCADE'), nullable=False, index=True)
    workflow_version_id = Column(UUID(as_uuid=True), ForeignKey('bot_workflow_versions.id'))
    session_id = Column(String(255), index=True)
    user_id = Column(String(36), ForeignKey('users.uuid'))

    # 실행 데이터
    graph_snapshot = Column(JSONB, nullable=False)
    inputs = Column(JSONB)
    outputs = Column(JSONB)

    # 상태 및 에러
    status = Column(String(20), nullable=False)
    error_message = Column(Text)

    # 실행 메트릭
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    finished_at = Column(DateTime(timezone=True))
    elapsed_time = Column(Integer)  # milliseconds
    total_tokens = Column(Integer, default=0)
    total_steps = Column(Integer, default=0)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    # 🆕 API 키 추적
    api_key_id = Column(UUID(as_uuid=True), ForeignKey('bot_api_keys.id', ondelete='SET NULL'), nullable=True, index=True)
    api_request_id = Column(String(64), nullable=True, index=True)  # 외부 추적용 (idempotency)

    # 관계
    workflow_version = relationship("BotWorkflowVersion", back_populates="execution_runs")
    node_executions = relationship("WorkflowNodeExecution", back_populates="run", cascade="all, delete-orphan")
    bot_api_key = relationship("BotAPIKey", back_populates="execution_runs")


class WorkflowNodeExecution(Base):
    """워크플로우 노드 실행 기록 테이블"""
    __tablename__ = "workflow_node_executions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_run_id = Column(UUID(as_uuid=True), ForeignKey('workflow_execution_runs.id', ondelete='CASCADE'), nullable=False, index=True)
    node_id = Column(String(255), nullable=False)
    node_type = Column(String(50), nullable=False)
    execution_order = Column(Integer)

    # 노드 데이터
    inputs = Column(JSONB)
    outputs = Column(JSONB)
    process_data = Column(JSONB)

    # 상태 및 에러
    status = Column(String(20), nullable=False)
    error_message = Column(Text)

    # 실행 메트릭
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    finished_at = Column(DateTime(timezone=True))
    elapsed_time = Column(Integer)  # milliseconds
    tokens_used = Column(Integer, default=0)

    # 데이터 truncation 정보
    is_truncated = Column(Boolean, default=False)
    truncated_fields = Column(JSONB)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # 관계
    run = relationship("WorkflowExecutionRun", back_populates="node_executions")
