"""
LLM Client 단위 테스트
"""
import pytest
from unittest.mock import Mock, AsyncMock, patch
from app.core.llm_client import BaseLLMClient, get_llm_client
from app.core.providers.openai import OpenAIClient


class TestBaseLLMClient:
    """BaseLLMClient 추상 클래스 테스트"""

    def test_cannot_instantiate_abstract_class(self):
        """추상 클래스는 직접 인스턴스화할 수 없음"""
        with pytest.raises(TypeError):
            BaseLLMClient()


class TestOpenAIClient:
    """OpenAIClient 테스트"""

    def test_init(self):
        """OpenAIClient 초기화 테스트"""
        client = OpenAIClient(
            api_key="test-key",
            model="gpt-3.5-turbo",
            organization="test-org"
        )

        assert client.model == "gpt-3.5-turbo"
        assert client.client is not None

    @pytest.mark.asyncio
    async def test_generate_success(self, sample_messages):
        """OpenAI API 호출 성공 테스트"""
        client = OpenAIClient(api_key="test-key")

        # Mock response
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message.content = "안녕하세요! 무엇을 도와드릴까요?"

        with patch.object(client.client.chat.completions, 'create', new_callable=AsyncMock) as mock_create:
            mock_create.return_value = mock_response

            result = await client.generate(
                messages=sample_messages,
                temperature=0.7,
                max_tokens=100
            )

            assert result == "안녕하세요! 무엇을 도와드릴까요?"
            mock_create.assert_called_once()

    @pytest.mark.asyncio
    async def test_generate_api_error(self, sample_messages):
        """OpenAI API 호출 실패 테스트"""
        client = OpenAIClient(api_key="test-key")

        with patch.object(client.client.chat.completions, 'create', new_callable=AsyncMock) as mock_create:
            mock_create.side_effect = Exception("API Error")

            with pytest.raises(Exception) as exc_info:
                await client.generate(messages=sample_messages)

            assert "API Error" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_generate_stream(self, sample_messages):
        """스트리밍 응답 테스트"""
        client = OpenAIClient(api_key="test-key")

        # Mock stream chunks
        mock_chunks = [
            Mock(choices=[Mock(delta=Mock(content="안녕"))]),
            Mock(choices=[Mock(delta=Mock(content="하세요"))]),
            Mock(choices=[Mock(delta=Mock(content="!"))])
        ]

        async def mock_stream():
            for chunk in mock_chunks:
                yield chunk

        with patch.object(client.client.chat.completions, 'create', new_callable=AsyncMock) as mock_create:
            mock_create.return_value = mock_stream()

            result = []
            async for chunk in client.generate_stream(messages=sample_messages):
                result.append(chunk)

            assert result == ["안녕", "하세요", "!"]


class TestLLMClientFactory:
    """LLM Client 팩토리 함수 테스트"""

    def test_get_llm_client_openai_success(self, mock_settings):
        """OpenAI 클라이언트 생성 성공"""
        with patch('app.core.llm_client.settings', mock_settings):
            with patch('app.core.llm_client._llm_client', None):
                client = get_llm_client(provider="openai")

                assert isinstance(client, OpenAIClient)
                assert client.model == "gpt-3.5-turbo"

    def test_get_llm_client_missing_api_key(self, mock_settings):
        """API 키 누락 시 에러 발생"""
        mock_settings.openai_api_key = ""

        with patch('app.core.llm_client.settings', mock_settings):
            with patch('app.core.llm_client._llm_client', None):
                with pytest.raises(ValueError) as exc_info:
                    get_llm_client(provider="openai")

                assert "OPENAI_API_KEY가 설정되지 않았습니다" in str(exc_info.value)

    def test_get_llm_client_unsupported_provider(self, mock_settings):
        """지원하지 않는 제공자 에러"""
        with patch('app.core.llm_client.settings', mock_settings):
            with patch('app.core.llm_client._llm_client', None):
                with pytest.raises(ValueError) as exc_info:
                    get_llm_client(provider="unsupported")

                assert "지원하지 않는 LLM 제공자" in str(exc_info.value)

    def test_get_llm_client_singleton(self, mock_settings):
        """싱글톤 패턴 확인"""
        import app.core.llm_client as llm_module

        with patch('app.core.llm_client.settings', mock_settings):
            # 전역 변수 직접 초기화
            llm_module._llm_client = None

            # 첫 번째 호출에서 인스턴스 생성
            client1 = get_llm_client()

            # 두 번째 호출에서는 같은 인스턴스 반환 (싱글톤)
            client2 = get_llm_client()

            assert client1 is client2

            # 테스트 후 정리
            llm_module._llm_client = None
