"""
ConversationVariable 모델

봇/세션별 대화 변수를 영속화하기 위한 테이블 정의.
"""

from __future__ import annotations

from datetime import datetime
import uuid

from sqlalchemy import Column, String, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.sql import func

from app.core.database import Base


class ConversationVariable(Base):
    """세션별 대화 변수 값."""

    __tablename__ = "conversation_variables"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id = Column(String(255), nullable=False, index=True)
    bot_id = Column(String(50), ForeignKey("bots.bot_id", ondelete="CASCADE"), nullable=False, index=True)
    key = Column(String(255), nullable=False)
    value = Column(JSONB, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint(
            "conversation_id",
            "bot_id",
            "key",
            name="uq_conversation_variable_key",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"ConversationVariable(id={self.id}, conversation_id={self.conversation_id}, "
            f"bot_id={self.bot_id}, key={self.key})"
        )
