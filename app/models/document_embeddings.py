"""
문서 임베딩 데이터베이스 모델 (pgvector 사용)
"""
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from pgvector.sqlalchemy import Vector

from app.core.database import Base


class DocumentEmbedding(Base):
    """문서 임베딩 테이블 (pgvector)"""
    __tablename__ = "document_embeddings"

    id = Column(Integer, primary_key=True, index=True)

    # 봇 연결 (bot_id 문자열로 변경: "bot_xxx" 또는 "session_xxx" 형식 지원)
    bot_id = Column(String(100), ForeignKey("bots.bot_id", ondelete="CASCADE"), nullable=False, index=True)

    # 문서 청크
    chunk_text = Column(Text, nullable=False, comment="분할된 텍스트 청크")
    chunk_index = Column(Integer, nullable=False, comment="청크 인덱스 (순서)")

    # 벡터 임베딩 (Bedrock Titan: 1024차원)
    embedding = Column(Vector(1024), nullable=False, comment="1024차원 임베딩 벡터")

    # 메타데이터
    doc_metadata = Column(JSON, nullable=True, comment="소스 파일명, 페이지 번호 등")

    # 타임스탬프
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    bot = relationship("Bot", back_populates="document_embeddings")

    def __repr__(self):
        return f"<DocumentEmbedding(id={self.id}, bot_id={self.bot_id}, chunk_index={self.chunk_index})>"
