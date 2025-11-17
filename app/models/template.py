"""
템플릿 관련 데이터베이스 모델
"""
from sqlalchemy import Column, String, DateTime, JSON, Text, Boolean, Integer, Float, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
import uuid

from app.core.database import Base


class Template(Base):
    """확장된 템플릿 테이블"""
    __tablename__ = "templates"

    # 기존 필드
    id = Column(String(50), primary_key=True, index=True)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=False)
    category = Column(String(50), nullable=False, index=True)
    icon = Column(String(500), nullable=True)
    type = Column(String(50), nullable=False, index=True)
    tags = Column(JSON, nullable=False, default=list)

    # 새로 추가할 필드
    version = Column(String(50), nullable=False, default="1.0.0")
    visibility = Column(String(20), nullable=False, default="private", index=True)

    # 작성자 정보 (관계형으로 변경)
    author_id = Column(String(36), ForeignKey("users.uuid"), nullable=False, index=True)
    author_name = Column(String(200), nullable=False)
    author_email = Column(String(255), nullable=True)

    # 출처 정보
    source_workflow_id = Column(String(50), ForeignKey("bots.bot_id"), nullable=True)
    source_version_id = Column(UUID(as_uuid=True), ForeignKey("bot_workflow_versions.id"), nullable=True)

    # 메타데이터
    node_count = Column(Integer, nullable=False, default=0)
    edge_count = Column(Integer, nullable=False, default=0)
    estimated_tokens = Column(Integer, nullable=True)
    estimated_cost = Column(Float, nullable=True)

    # 워크플로우 정의
    graph = Column(JSON, nullable=False, default=dict)
    input_schema = Column(JSON, nullable=False, default=list)
    output_schema = Column(JSON, nullable=False, default=list)

    # 미디어
    thumbnail_url = Column(String(500), nullable=True)

    # 타임스탬프
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # 관계
    author = relationship("User", foreign_keys=[author_id])
    source_workflow = relationship("Bot", foreign_keys=[source_workflow_id])
    source_version = relationship("BotWorkflowVersion", foreign_keys=[source_version_id])
    usages = relationship("TemplateUsage", back_populates="template", cascade="all, delete-orphan")


class TemplateUsage(Base):
    """템플릿 사용 추적 테이블

    주의: workflow_id는 'workflows' 테이블이 아닌 'bots' 테이블의 bot_id를 참조합니다.
    실제 백엔드 구조에서는 별도의 workflows 테이블이 존재하지 않으며,
    Bot 모델이 워크플로우를 대표합니다.
    """
    __tablename__ = "template_usages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    template_id = Column(String(50), ForeignKey("templates.id", ondelete="CASCADE"), nullable=False, index=True)
    workflow_id = Column(String(50), ForeignKey("bots.bot_id", ondelete="CASCADE"), nullable=False, index=True)  # bots 테이블 참조
    workflow_version_id = Column(UUID(as_uuid=True), ForeignKey("bot_workflow_versions.id"), nullable=True)
    node_id = Column(String(255), nullable=False)
    user_id = Column(String(36), ForeignKey("users.uuid", ondelete="CASCADE"), nullable=False, index=True)
    event_type = Column(String(50), nullable=False, default="imported")  # imported, executed
    note = Column(Text, nullable=True)
    occurred_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    # 관계
    template = relationship("Template", back_populates="usages")
    workflow = relationship("Bot")
    workflow_version = relationship("BotWorkflowVersion")
    user = relationship("User")
