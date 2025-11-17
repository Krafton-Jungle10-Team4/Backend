from sqlalchemy import Column, String, DateTime, Integer, JSON, Text, ForeignKey
from sqlalchemy.sql import func
from app.core.database import Base


class Knowledge(Base):
    __tablename__ = "knowledge"

    id = Column(String, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    tags = Column(JSON, nullable=False, default=list)
    document_count = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
