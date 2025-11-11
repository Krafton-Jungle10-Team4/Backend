"""
챗봇 관련 Pydantic 모델
"""
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional, Dict, Any, Literal
from enum import Enum


class ChatRequest(BaseModel):
    """챗봇 요청 모델"""
    bot_id: Optional[str] = Field(None, description="봇 ID (workflow 실행용)")
    message: str = Field(..., description="사용자 질문", min_length=1, max_length=2000)
    session_id: Optional[str] = Field(None, description="대화 세션 ID")
    top_k: int = Field(5, description="검색할 문서 개수", ge=1, le=20)
    include_sources: bool = Field(True, description="출처 정보 포함 여부 (기본 True, 명세/테스트와 일치)")
    model: Optional[str] = Field(None, description="사용할 LLM 모델 (런타임 오버라이드)")

    # 스트리밍 API용 추가 필드
    document_ids: Optional[List[str]] = Field(None, description="검색할 문서 ID 필터 (선택)")
    temperature: Optional[float] = Field(None, description="LLM 창의성 (0.0-1.0)", ge=0.0, le=1.0)
    max_tokens: Optional[int] = Field(None, description="최대 토큰 수 (100-4000)", ge=100, le=4000)

    # Pydantic 모델 설정
    # ConfigDict: 타입 안정성을 가진 설정 객체(딕셔너리)
    model_config = ConfigDict(
        # OpenAPI/JSON Schema에 포함될 예시를 추가하는 설정
        # FastAPI 문서에서 요청/응답 예시로 표시
        json_schema_extra={
            "example": {
                "bot_id": "bot_1234567890_abc123",
                "message": "FastAPI의 주요 특징은 무엇인가요?",
                "session_id": "user_123",
                "top_k": 5,
                "include_sources": True,
                "model": "gpt-4"
            }
        }
    )


class Source(BaseModel):
    """출처 정보 모델"""
    document_id: str = Field(..., description="문서 ID")
    chunk_id: str = Field(..., description="청크 ID")
    content: str = Field(..., description="청크 내용 (요약)", max_length=500)
    similarity_score: float = Field(..., description="유사도 점수", ge=0.0, le=1.0)
    metadata: Dict[str, Any] = Field(default_factory=dict, description="메타데이터")


class ChatResponse(BaseModel):
    """챗봇 응답 모델"""
    response: str = Field(..., description="챗봇 응답 텍스트")
    sources: List[Source] = Field(default_factory=list, description="참조 문서")
    session_id: str = Field(..., description="세션 ID")
    retrieved_chunks: int = Field(..., description="검색된 청크 수", ge=0)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "response": "FastAPI의 주요 특징은 빠른 성능, 타입 힌팅 지원, 자동 문서 생성입니다.",
                "sources": [
                    {
                        "document_id": "doc_123",
                        "chunk_id": "doc_123_chunk_0",
                        "content": "FastAPI는 현대적이고 빠른 Python 웹 프레임워크입니다...",
                        "similarity_score": 0.89,
                        "metadata": {"filename": "fastapi_guide.pdf"}
                    }
                ],
                "session_id": "user_123",
                "retrieved_chunks": 3
            }
        }
    )


# ============================================================================
# SSE 스트리밍 이벤트 모델
# ============================================================================

class ErrorCode(str, Enum):
    """SSE 에러 코드"""
    RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"
    TIMEOUT = "TIMEOUT"
    INVALID_REQUEST = "INVALID_REQUEST"
    STREAM_ERROR = "STREAM_ERROR"
    UNKNOWN_ERROR = "UNKNOWN_ERROR"


class ContentEvent(BaseModel):
    """콘텐츠 청크 이벤트"""
    type: Literal["content"] = "content"
    data: str = Field(..., description="스트리밍 텍스트 조각")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "type": "content",
                "data": "FastAPI의 주요 특징은 "
            }
        }
    )


class SourcesEvent(BaseModel):
    """출처 정보 이벤트"""
    type: Literal["sources"] = "sources"
    data: List[Source] = Field(..., description="검색된 문서 출처")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "type": "sources",
                "data": [
                    {
                        "document_id": "doc_123",
                        "chunk_id": "chunk_456",
                        "content": "FastAPI는 현대적이고 빠른...",
                        "similarity_score": 0.892,
                        "metadata": {"filename": "fastapi.pdf"}
                    }
                ]
            }
        }
    )


class ErrorEvent(BaseModel):
    """에러 이벤트"""
    type: Literal["error"] = "error"
    code: ErrorCode = Field(..., description="에러 코드")
    message: str = Field(..., description="에러 메시지")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "type": "error",
                "code": "RATE_LIMIT_EXCEEDED",
                "message": "API 사용량 제한을 초과했습니다"
            }
        }
    )


# SSE 이벤트 유니온 타입 (타입 힌팅용)
SSEEvent = ContentEvent | SourcesEvent | ErrorEvent
