"""
문서 관련 Pydantic 모델
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Any
from datetime import datetime


class DocumentUploadResponse(BaseModel):
    """문서 업로드 응답 모델"""
    document_id: str = Field(..., description="문서 고유 ID")
    filename: str = Field(..., description="파일명")
    file_size: int = Field(..., description="파일 크기 (bytes)")
    chunk_count: int = Field(..., description="생성된 청크 개수")
    processing_time: float = Field(..., description="처리 시간 (초)")
    status: str = Field(..., description="처리 상태")
    message: str = Field(..., description="처리 결과 메시지")


class DocumentMetadata(BaseModel):
    """문서 메타데이터 모델"""
    document_id: str
    filename: str
    file_type: str
    file_size: int
    chunk_count: int
    created_at: str


class SearchRequest(BaseModel):
    """검색 요청 모델"""
    query: str = Field(..., description="검색할 텍스트", min_length=1)
    top_k: int = Field(5, description="반환할 결과 개수", ge=1, le=50)


class SearchResponse(BaseModel):
    """검색 응답 모델"""
    query: str = Field(..., description="검색 쿼리")
    results: Any = Field(..., description="검색 결과")
    count: int = Field(..., description="반환된 결과 개수")
