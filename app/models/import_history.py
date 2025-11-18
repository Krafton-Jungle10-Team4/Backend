"""
에이전트 가져오기 이력 모델
"""
from sqlalchemy import Column, String, DateTime, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
import uuid

from app.core.database import Base


class AgentImportHistory(Base):
    """에이전트 가져오기 이력 테이블"""
    __tablename__ = "agent_import_history"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_version_id = Column(
        UUID(as_uuid=True),
        ForeignKey("bot_workflow_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    target_bot_id = Column(
        String(255),
        ForeignKey("bots.bot_id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    imported_by = Column(
        String(36),
        ForeignKey("users.uuid", ondelete="SET NULL"),
        nullable=True
    )
    imported_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True
    )
    import_metadata = Column(JSONB, nullable=True)

    # 관계
    source_version = relationship("BotWorkflowVersion", foreign_keys=[source_version_id])
    target_bot = relationship("Bot", foreign_keys=[target_bot_id])
    importer = relationship("User", foreign_keys=[imported_by])

    __table_args__ = (
        {"extend_existing": True},
    )
