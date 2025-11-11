"""
문서 처리 API 스키마 (Pydantic)
"""
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from enum import Enum


class DocumentStatusEnum(str, Enum):
    """문서 처리 상태"""
    UPLOADED = "uploaded"
    QUEUED = "queued"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"


# ============================================
# 비동기 업로드 API 스키마
# ============================================

class AsyncDocumentUploadResponse(BaseModel):
    """
    비동기 문서 업로드 응답
    POST /api/v1/documents/upload
    """
    job_id: str = Field(..., description="문서 ID (document_id)")
    status: str = Field(..., description="초기 상태 (queued)")
    message: str = Field(..., description="처리 대기 메시지")
    estimated_time: Optional[int] = Field(None, description="예상 처리 시간 (초)")

    class Config:
        json_schema_extra = {
            "example": {
                "job_id": "doc_abc123def456",
                "status": "queued",
                "message": "문서가 처리 대기열에 추가되었습니다",
                "estimated_time": 30
            }
        }


# ============================================
# 문서 상태 조회 API 스키마
# ============================================

class DocumentStatusResponse(BaseModel):
    """
    문서 상태 조회 응답
    GET /api/v1/documents/status/{document_id}
    """
    document_id: str = Field(..., description="문서 ID")
    filename: str = Field(..., description="파일명")
    status: DocumentStatusEnum = Field(..., description="처리 상태")
    error_message: Optional[str] = Field(None, description="에러 메시지 (실패 시)")
    chunk_count: Optional[int] = Field(None, description="생성된 청크 개수")
    processing_time: Optional[int] = Field(None, description="처리 시간 (초)")
    created_at: datetime = Field(..., description="생성 시간")
    updated_at: Optional[datetime] = Field(None, description="수정 시간")
    completed_at: Optional[datetime] = Field(None, description="완료 시간")

    class Config:
        json_schema_extra = {
            "example": {
                "document_id": "doc_abc123def456",
                "filename": "문서.pdf",
                "status": "processing",
                "error_message": None,
                "chunk_count": None,
                "processing_time": None,
                "created_at": "2025-11-11T10:00:00Z",
                "updated_at": "2025-11-11T10:01:00Z",
                "completed_at": None
            }
        }


# ============================================
# 문서 목록 조회 API 스키마
# ============================================

class DocumentListRequest(BaseModel):
    """
    문서 목록 조회 요청 (Query Parameters)
    GET /api/v1/documents/list
    """
    bot_id: Optional[str] = Field(None, description="봇 ID 필터")
    status: Optional[DocumentStatusEnum] = Field(None, description="상태 필터")
    limit: int = Field(50, description="페이지 크기", ge=1, le=100)
    offset: int = Field(0, description="오프셋", ge=0)


class DocumentInfo(BaseModel):
    """문서 정보"""
    document_id: str
    bot_id: str
    original_filename: str
    file_extension: str
    file_size: int
    status: DocumentStatusEnum
    chunk_count: Optional[int] = None
    processing_time: Optional[int] = None
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


class DocumentListResponse(BaseModel):
    """
    문서 목록 조회 응답
    GET /api/v1/documents/list
    """
    documents: List[DocumentInfo] = Field(..., description="문서 목록")
    total: int = Field(..., description="전체 문서 개수")
    limit: int = Field(..., description="페이지 크기")
    offset: int = Field(..., description="오프셋")

    class Config:
        json_schema_extra = {
            "example": {
                "documents": [
                    {
                        "document_id": "doc_abc123",
                        "bot_id": "bot_123",
                        "original_filename": "문서.pdf",
                        "file_extension": "pdf",
                        "file_size": 2621440,
                        "status": "processing",
                        "chunk_count": None,
                        "processing_time": None,
                        "error_message": None,
                        "created_at": "2025-11-11T10:00:00Z",
                        "updated_at": "2025-11-11T10:01:00Z"
                    }
                ],
                "total": 234,
                "limit": 50,
                "offset": 0
            }
        }


# ============================================
# 문서 재처리 API 스키마
# ============================================

class DocumentRetryResponse(BaseModel):
    """
    문서 재처리 응답
    POST /api/v1/documents/retry/{document_id}
    """
    job_id: str = Field(..., description="문서 ID")
    status: str = Field(..., description="재처리 상태 (queued)")
    message: str = Field(..., description="재처리 메시지")

    class Config:
        json_schema_extra = {
            "example": {
                "job_id": "doc_abc123",
                "status": "queued",
                "message": "문서가 재처리 대기열에 추가되었습니다"
            }
        }
