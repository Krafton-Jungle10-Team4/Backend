"""
챗봇 API 엔드포인트 통합 테스트
"""
import pytest
from unittest.mock import Mock, AsyncMock
from fastapi import HTTPException
from app.models.chat import ChatRequest, ChatResponse, Source
from app.api.v1.endpoints.chat import chat, chat_health_check


@pytest.fixture
def mock_chat_service():
    """Mock ChatService"""
    service = Mock()
    service.generate_response = AsyncMock()
    return service


@pytest.fixture
def sample_chat_response():
    """샘플 ChatResponse"""
    return ChatResponse(
        response="FastAPI는 빠르고 현대적인 웹 프레임워크입니다.",
        sources=[
            Source(
                document_id="doc_123",
                chunk_id="doc_123_chunk_0",
                content="FastAPI 관련 내용...",
                similarity_score=0.89,
                metadata={"filename": "fastapi_guide.pdf"}
            )
        ],
        session_id="user_123",
        retrieved_chunks=3
    )


class TestChatHealthEndpoint:
    """챗봇 헬스 체크 엔드포인트 테스트"""

    @pytest.mark.asyncio
    async def test_chat_health_check(self):
        """헬스 체크 엔드포인트 정상 응답"""
        response = await chat_health_check()

        assert response["status"] == "healthy"
        assert response["service"] == "chat"
        assert "message" in response


class TestChatEndpoint:
    """챗봇 대화 엔드포인트 테스트"""

    @pytest.mark.asyncio
    async def test_chat_success(self, mock_chat_service, sample_chat_response):
        """정상적인 챗봇 대화 테스트"""
        request = ChatRequest(
            message="FastAPI의 장점은 무엇인가요?",
            session_id="user_123",
            top_k=5,
            include_sources=True
        )

        mock_chat_service.generate_response.return_value = sample_chat_response

        response = await chat(request, chat_service=mock_chat_service)

        assert response.response == "FastAPI는 빠르고 현대적인 웹 프레임워크입니다."
        assert len(response.sources) == 1
        assert response.session_id == "user_123"
        assert response.retrieved_chunks == 3

        # ChatService가 호출되었는지 확인
        mock_chat_service.generate_response.assert_called_once()
        call_args = mock_chat_service.generate_response.call_args[0][0]
        assert call_args.message == "FastAPI의 장점은 무엇인가요?"
        assert call_args.top_k == 5

    @pytest.mark.asyncio
    async def test_chat_with_defaults(self, mock_chat_service, sample_chat_response):
        """기본값을 사용하는 챗봇 대화 테스트"""
        request = ChatRequest(message="테스트 질문입니다")

        mock_chat_service.generate_response.return_value = sample_chat_response

        response = await chat(request, chat_service=mock_chat_service)

        assert response.response is not None
        assert response.sources is not None
        assert response.session_id is not None
        assert response.retrieved_chunks >= 0

    @pytest.mark.asyncio
    async def test_chat_no_documents_found(self, mock_chat_service):
        """관련 문서를 찾지 못한 경우"""
        request = ChatRequest(
            message="존재하지 않는 주제에 대한 질문",
            top_k=5
        )

        no_docs_response = ChatResponse(
            response="죄송합니다. 관련 문서를 찾을 수 없습니다. 다른 질문을 해주세요.",
            sources=[],
            session_id="default",
            retrieved_chunks=0
        )
        mock_chat_service.generate_response.return_value = no_docs_response

        response = await chat(request, chat_service=mock_chat_service)

        assert "관련 문서를 찾을 수 없습니다" in response.response
        assert len(response.sources) == 0
        assert response.retrieved_chunks == 0

    @pytest.mark.asyncio
    async def test_chat_value_error_handling(self, mock_chat_service):
        """ValueError 발생 시 400 에러 반환"""
        request = ChatRequest(message="테스트 질문", top_k=5)

        mock_chat_service.generate_response.side_effect = ValueError("잘못된 요청입니다")

        with pytest.raises(HTTPException) as exc_info:
            await chat(request, chat_service=mock_chat_service)

        assert exc_info.value.status_code == 400
        assert "잘못된 요청입니다" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_chat_server_error_handling(self, mock_chat_service):
        """서버 에러 발생 시 500 에러 반환"""
        request = ChatRequest(message="테스트 질문", top_k=5)

        mock_chat_service.generate_response.side_effect = Exception("LLM API 호출 실패")

        with pytest.raises(HTTPException) as exc_info:
            await chat(request, chat_service=mock_chat_service)

        assert exc_info.value.status_code == 500
        assert "응답 생성 중 오류가 발생했습니다" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_chat_with_include_sources_false(self, mock_chat_service):
        """include_sources=False 시 출처 정보 미포함"""
        request = ChatRequest(
            message="테스트 질문",
            include_sources=False
        )

        response_without_sources = ChatResponse(
            response="FastAPI 응답",
            sources=[],  # 출처 정보 없음
            session_id="default",
            retrieved_chunks=3
        )
        mock_chat_service.generate_response.return_value = response_without_sources

        response = await chat(request, chat_service=mock_chat_service)

        assert len(response.sources) == 0
