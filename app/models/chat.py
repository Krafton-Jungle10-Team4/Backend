"""
챗봇 관련 Pydantic 모델
"""
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional, Dict, Any


class ChatRequest(BaseModel):
    """챗봇 요청 모델"""
    message: str = Field(..., description="사용자 질문", min_length=1, max_length=2000)
    session_id: Optional[str] = Field(None, description="대화 세션 ID")
    top_k: int = Field(5, description="검색할 문서 개수", ge=1, le=20)
    include_sources: bool = Field(True, description="출처 정보 포함 여부")

    # Pydantic 모델 설정
    # ConfigDict: 타입 안정성을 가진 설정 객체(딕셔너리)
    model_config = ConfigDict(
        # OpenAPI/JSON Schema에 포함될 예시를 추가하는 설정
        # FastAPI 문서에서 요청/응답 예시로 표시
        json_schema_extra={
            "example": {
                "message": "FastAPI의 주요 특징은 무엇인가요?",
                "session_id": "user_123",
                "top_k": 5,
                "include_sources": True
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
