"""
워크플로우 V2 버전 관리 모델
"""
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
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
    published_at = Column(DateTime, nullable=True)

    # 관계
    bot = relationship("Bot", back_populates="workflow_versions")
    execution_runs = relationship("WorkflowExecutionRun", back_populates="workflow_version", cascade="all, delete-orphan")


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

    # 관계
    workflow_version = relationship("BotWorkflowVersion", back_populates="execution_runs")
    node_executions = relationship("WorkflowNodeExecution", back_populates="run", cascade="all, delete-orphan")
    annotations = relationship("WorkflowRunAnnotation", back_populates="workflow_run", cascade="all, delete-orphan")


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


class WorkflowRunAnnotation(Base):
    """워크플로우 실행 어노테이션"""

    __tablename__ = "workflow_run_annotations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_run_id = Column(
        UUID(as_uuid=True),
        ForeignKey('workflow_execution_runs.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )
    bot_id = Column(String(50), ForeignKey('bots.bot_id', ondelete='CASCADE'), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    annotation = Column(Text, nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # 관계
    workflow_run = relationship("WorkflowExecutionRun", back_populates="annotations")
