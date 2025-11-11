"""
문서 처리 상태 추적 데이터베이스 모델
"""
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, Enum as SQLEnum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from datetime import datetime
import enum

from app.core.database import Base


class DocumentStatus(str, enum.Enum):
    """문서 처리 상태"""
    UPLOADED = "uploaded"      # 업로드 완료
    QUEUED = "queued"          # 큐에 추가됨
    PROCESSING = "processing"  # 임베딩 처리 중
    DONE = "done"              # 처리 완료
    FAILED = "failed"          # 처리 실패


class Document(Base):
    """
    문서 처리 상태 추적 테이블

    비동기 문서 처리를 위한 상태 추적 및 모니터링
    """
    __tablename__ = "documents"

    # 식별자
    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(String(36), unique=True, index=True, nullable=False)  # UUID
    bot_id = Column(String(50), index=True, nullable=False)
    user_uuid = Column(String(36), index=True, nullable=False)

    # 파일 정보
    original_filename = Column(String(255), nullable=False)
    file_extension = Column(String(10), nullable=False)
    file_size = Column(Integer, nullable=False)  # bytes
    s3_uri = Column(Text, nullable=True)

    # 처리 상태
    status = Column(
        SQLEnum(DocumentStatus, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=DocumentStatus.QUEUED.value,
        index=True  # 상태별 필터링을 위한 인덱스
    )
    error_message = Column(Text, nullable=True)
    retry_count = Column(Integer, default=0, nullable=False)

    # 처리 결과
    chunk_count = Column(Integer, nullable=True)  # 생성된 청크 개수
    processing_time = Column(Integer, nullable=True)  # 처리 시간 (초)

    # 타임스탬프
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    queued_at = Column(DateTime(timezone=True), nullable=True)
    processing_started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    embedded_at = Column(DateTime(timezone=True), nullable=True, comment="임베딩 완료 시간 (Workflow에서 실행)")

    def __repr__(self):
        return f"<Document(document_id={self.document_id}, status={self.status}, filename={self.original_filename})>"
