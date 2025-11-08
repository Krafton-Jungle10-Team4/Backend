"""
봇 관련 데이터베이스 모델
"""
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, Enum as SQLEnum, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from datetime import datetime
import enum

from app.core.database import Base


class BotStatus(str, enum.Enum):
    """봇 상태"""
    ACTIVE = "active"
    INACTIVE = "inactive"
    ERROR = "error"


class Bot(Base):
    """봇 테이블"""
    __tablename__ = "bots"

    id = Column(Integer, primary_key=True, index=True)
    bot_id = Column(String(50), unique=True, index=True, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    name = Column(String(100), nullable=False)
    goal = Column(String(500), nullable=True)
    personality = Column(Text, nullable=True)
    description = Column(Text, nullable=True)
    avatar = Column(String(500), nullable=True)

    status = Column(SQLEnum(BotStatus), nullable=False, default=BotStatus.ACTIVE)
    messages_count = Column(Integer, default=0, nullable=False)
    errors_count = Column(Integer, default=0, nullable=False)

    # Workflow 정의 (JSON 형식)
    workflow = Column(JSON, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # 관계
    user = relationship("User", back_populates="bots")
    knowledge_items = relationship("BotKnowledge", back_populates="bot", cascade="all, delete-orphan")
    deployments = relationship("BotDeployment", back_populates="bot", cascade="all, delete-orphan")
    document_embeddings = relationship("DocumentEmbedding", back_populates="bot", cascade="all, delete-orphan")


class BotKnowledge(Base):
    """봇 지식 항목 테이블"""
    __tablename__ = "bot_knowledge"

    id = Column(Integer, primary_key=True, index=True)
    bot_id = Column(Integer, ForeignKey("bots.id", ondelete="CASCADE"), nullable=False)
    knowledge_item = Column(Text, nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # 관계
    bot = relationship("Bot", back_populates="knowledge_items")
