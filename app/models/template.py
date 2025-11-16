"""
템플릿 관련 데이터베이스 모델
"""
from sqlalchemy import Column, String, DateTime, JSON, Text
from sqlalchemy.sql import func

from app.core.database import Base


class Template(Base):
    """템플릿 테이블"""
    __tablename__ = "templates"

    id = Column(String(50), primary_key=True, index=True)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=False)
    category = Column(String(50), nullable=False, index=True)
    icon = Column(String(500), nullable=True)
    type = Column(String(50), nullable=False, index=True)
    author = Column(String(200), nullable=False)
    tags = Column(JSON, nullable=False, default=list)
    workflow_config = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
