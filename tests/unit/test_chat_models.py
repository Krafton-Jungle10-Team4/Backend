"""
챗봇 Pydantic 모델 단위 테스트
"""
import pytest
from pydantic import ValidationError
from app.models.chat import ChatRequest, ChatResponse, Source


class TestChatRequest:
    """ChatRequest 모델 테스트"""

    def test_valid_chat_request(self):
        """유효한 ChatRequest 생성 테스트"""
        request = ChatRequest(
            message="FastAPI의 장점은 무엇인가요?",
            session_id="user_123",
            top_k=5,
            include_sources=True
        )

        assert request.message == "FastAPI의 장점은 무엇인가요?"
        assert request.session_id == "user_123"
        assert request.top_k == 5
        assert request.include_sources is True

    def test_chat_request_with_defaults(self):
        """기본값을 사용하는 ChatRequest 생성 테스트"""
        request = ChatRequest(message="테스트 질문입니다")

        assert request.message == "테스트 질문입니다"
        assert request.session_id is None
        assert request.top_k == 5  # 기본값
        assert request.include_sources is True  # 기본값

    def test_chat_request_empty_message(self):
        """빈 메시지는 검증 실패"""
        with pytest.raises(ValidationError) as exc_info:
            ChatRequest(message="")

        errors = exc_info.value.errors()
        assert any(error["type"] == "string_too_short" for error in errors)

    def test_chat_request_message_too_long(self):
        """메시지가 2000자를 초과하면 검증 실패"""
        long_message = "a" * 2001

        with pytest.raises(ValidationError) as exc_info:
            ChatRequest(message=long_message)

        errors = exc_info.value.errors()
        assert any(error["type"] == "string_too_long" for error in errors)

    def test_chat_request_top_k_validation(self):
        """top_k 값 범위 검증 (1-20)"""
        # top_k = 0 (너무 작음)
        with pytest.raises(ValidationError) as exc_info:
            ChatRequest(message="테스트", top_k=0)

        errors = exc_info.value.errors()
        assert any(error["type"] == "greater_than_equal" for error in errors)

        # top_k = 21 (너무 큼)
        with pytest.raises(ValidationError) as exc_info:
            ChatRequest(message="테스트", top_k=21)

        errors = exc_info.value.errors()
        assert any(error["type"] == "less_than_equal" for error in errors)

        # top_k = 10 (유효)
        request = ChatRequest(message="테스트", top_k=10)
        assert request.top_k == 10

    def test_chat_request_json_schema_example(self):
        """JSON Schema 예시가 올바르게 설정되었는지 확인"""
        schema = ChatRequest.model_json_schema()

        # Pydantic v2에서는 최상위 레벨에 "example" 필드가 추가됨
        assert "example" in schema or "examples" in schema


class TestSource:
    """Source 모델 테스트"""

    def test_valid_source(self):
        """유효한 Source 생성 테스트"""
        source = Source(
            document_id="doc_123",
            chunk_id="doc_123_chunk_0",
            content="FastAPI는 현대적인 웹 프레임워크입니다.",
            similarity_score=0.89,
            metadata={"filename": "fastapi_guide.pdf", "chunk_index": 0}
        )

        assert source.document_id == "doc_123"
        assert source.chunk_id == "doc_123_chunk_0"
        assert source.similarity_score == 0.89
        assert source.metadata["filename"] == "fastapi_guide.pdf"

    def test_source_with_empty_metadata(self):
        """메타데이터 없는 Source 생성 (기본값)"""
        source = Source(
            document_id="doc_123",
            chunk_id="chunk_0",
            content="테스트 내용",
            similarity_score=0.5
        )

        assert source.metadata == {}

    def test_source_similarity_score_validation(self):
        """similarity_score 범위 검증 (0.0-1.0)"""
        # 음수
        with pytest.raises(ValidationError) as exc_info:
            Source(
                document_id="doc_123",
                chunk_id="chunk_0",
                content="테스트",
                similarity_score=-0.1
            )

        errors = exc_info.value.errors()
        assert any(error["type"] == "greater_than_equal" for error in errors)

        # 1.0 초과
        with pytest.raises(ValidationError) as exc_info:
            Source(
                document_id="doc_123",
                chunk_id="chunk_0",
                content="테스트",
                similarity_score=1.5
            )

        errors = exc_info.value.errors()
        assert any(error["type"] == "less_than_equal" for error in errors)

    def test_source_content_max_length(self):
        """content 최대 길이 검증 (500자)"""
        long_content = "a" * 501

        with pytest.raises(ValidationError) as exc_info:
            Source(
                document_id="doc_123",
                chunk_id="chunk_0",
                content=long_content,
                similarity_score=0.5
            )

        errors = exc_info.value.errors()
        assert any(error["type"] == "string_too_long" for error in errors)


class TestChatResponse:
    """ChatResponse 모델 테스트"""

    def test_valid_chat_response(self):
        """유효한 ChatResponse 생성 테스트"""
        sources = [
            Source(
                document_id="doc_123",
                chunk_id="chunk_0",
                content="FastAPI 내용",
                similarity_score=0.89,
                metadata={"filename": "test.pdf"}
            )
        ]

        response = ChatResponse(
            response="FastAPI의 주요 특징은...",
            sources=sources,
            session_id="user_123",
            retrieved_chunks=3
        )

        assert response.response == "FastAPI의 주요 특징은..."
        assert len(response.sources) == 1
        assert response.session_id == "user_123"
        assert response.retrieved_chunks == 3

    def test_chat_response_with_empty_sources(self):
        """출처가 없는 ChatResponse (기본값)"""
        response = ChatResponse(
            response="관련 문서를 찾을 수 없습니다.",
            session_id="user_123",
            retrieved_chunks=0
        )

        assert response.sources == []
        assert response.retrieved_chunks == 0

    def test_chat_response_retrieved_chunks_validation(self):
        """retrieved_chunks 음수 불가"""
        with pytest.raises(ValidationError) as exc_info:
            ChatResponse(
                response="테스트 응답",
                session_id="user_123",
                retrieved_chunks=-1
            )

        errors = exc_info.value.errors()
        assert any(error["type"] == "greater_than_equal" for error in errors)

    def test_chat_response_serialization(self):
        """ChatResponse JSON 직렬화 테스트"""
        response = ChatResponse(
            response="테스트 응답",
            sources=[],
            session_id="user_123",
            retrieved_chunks=0
        )

        json_data = response.model_dump()

        assert json_data["response"] == "테스트 응답"
        assert json_data["sources"] == []
        assert json_data["session_id"] == "user_123"
        assert json_data["retrieved_chunks"] == 0

    def test_chat_response_json_schema_example(self):
        """JSON Schema 예시가 올바르게 설정되었는지 확인"""
        schema = ChatResponse.model_json_schema()

        # Pydantic v2에서는 최상위 레벨에 "example" 필드가 추가됨
        assert "example" in schema or "examples" in schema
