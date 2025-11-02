"""
AnthropicClient 유닛 테스트
"""
import pytest
from unittest.mock import AsyncMock, Mock, patch
from app.core.providers.anthropic import AnthropicClient


@pytest.fixture
def anthropic_client():
    """테스트용 AnthropicClient 인스턴스"""
    return AnthropicClient(
        api_key="test-anthropic-key",
        model="claude-sonnet-4-5-20250929"
    )


@pytest.fixture
def openai_format_messages():
    """OpenAI 형식 테스트 메시지"""
    return [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "What is FastAPI?"}
    ]


@pytest.fixture
def anthropic_format_messages():
    """Anthropic 형식 테스트 메시지 (system 분리)"""
    return [
        {"role": "user", "content": "What is FastAPI?"}
    ]


class TestAnthropicClient:
    """AnthropicClient 테스트 클래스"""

    def test_initialization(self, anthropic_client):
        """클라이언트 초기화 테스트"""
        assert anthropic_client.model == "claude-sonnet-4-5-20250929"
        assert anthropic_client.system_prompt is not None
        assert anthropic_client.client is not None

    def test_convert_messages_with_system(self, anthropic_client, openai_format_messages):
        """system 메시지 포함 변환 테스트"""
        system_msg, converted = anthropic_client._convert_messages(openai_format_messages)

        assert system_msg == "You are a helpful assistant."
        assert len(converted) == 1
        assert converted[0]["role"] == "user"
        assert converted[0]["content"] == "What is FastAPI?"

    def test_convert_messages_without_system(self, anthropic_client, anthropic_format_messages):
        """system 메시지 없는 변환 테스트"""
        system_msg, converted = anthropic_client._convert_messages(anthropic_format_messages)

        # 기본 system_prompt 사용
        assert system_msg == anthropic_client.system_prompt
        assert len(converted) == 1
        assert converted[0]["role"] == "user"

    def test_convert_messages_preserves_user_assistant(self, anthropic_client):
        """user/assistant 메시지 보존 테스트"""
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
            {"role": "user", "content": "How are you?"}
        ]

        system_msg, converted = anthropic_client._convert_messages(messages)

        assert len(converted) == 3
        assert converted[0]["role"] == "user"
        assert converted[1]["role"] == "assistant"
        assert converted[2]["role"] == "user"

    @pytest.mark.asyncio
    async def test_generate_success(self, anthropic_client, openai_format_messages):
        """정상 응답 생성 테스트"""
        # Mock 응답 설정
        mock_response = Mock()
        mock_response.content = [Mock(text="FastAPI is a modern Python web framework.")]

        with patch.object(anthropic_client.client.messages, 'create', new=AsyncMock(return_value=mock_response)):
            result = await anthropic_client.generate(
                messages=openai_format_messages,
                temperature=0.7,
                max_tokens=1000
            )

            assert result == "FastAPI is a modern Python web framework."
            anthropic_client.client.messages.create.assert_called_once()

            # 호출 인자 검증
            call_kwargs = anthropic_client.client.messages.create.call_args.kwargs
            assert call_kwargs["model"] == "claude-sonnet-4-5-20250929"
            assert call_kwargs["system"] == "You are a helpful assistant."
            assert call_kwargs["temperature"] == 0.7
            assert call_kwargs["max_tokens"] == 1000

    @pytest.mark.asyncio
    async def test_generate_with_custom_params(self, anthropic_client, openai_format_messages):
        """커스텀 파라미터 테스트"""
        mock_response = Mock()
        mock_response.content = [Mock(text="Custom response")]

        with patch.object(anthropic_client.client.messages, 'create', new=AsyncMock(return_value=mock_response)):
            result = await anthropic_client.generate(
                messages=openai_format_messages,
                temperature=0.3,
                max_tokens=500,
                top_p=0.9
            )

            assert result == "Custom response"
            call_kwargs = anthropic_client.client.messages.create.call_args.kwargs
            assert call_kwargs["temperature"] == 0.3
            assert call_kwargs["max_tokens"] == 500
            assert call_kwargs["top_p"] == 0.9

    @pytest.mark.asyncio
    async def test_generate_api_error(self, anthropic_client, openai_format_messages):
        """API 오류 처리 테스트"""
        with patch.object(
            anthropic_client.client.messages,
            'create',
            new=AsyncMock(side_effect=Exception("API Error"))
        ):
            with pytest.raises(Exception) as exc_info:
                await anthropic_client.generate(messages=openai_format_messages)

            assert "API Error" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_generate_stream_success(self, anthropic_client, openai_format_messages):
        """스트리밍 응답 테스트"""
        # Mock 스트림 설정
        async def mock_text_stream():
            for chunk in ["Fast", "API ", "is ", "great"]:
                yield chunk

        mock_stream = AsyncMock()
        mock_stream.__aenter__ = AsyncMock(return_value=mock_stream)
        mock_stream.__aexit__ = AsyncMock(return_value=None)
        mock_stream.text_stream = mock_text_stream()

        with patch.object(anthropic_client.client.messages, 'stream', return_value=mock_stream):
            chunks = []
            async for chunk in anthropic_client.generate_stream(
                messages=openai_format_messages,
                temperature=0.7,
                max_tokens=1000
            ):
                chunks.append(chunk)

            assert chunks == ["Fast", "API ", "is ", "great"]
            assert "".join(chunks) == "FastAPI is great"

    @pytest.mark.asyncio
    async def test_generate_stream_with_system_conversion(self, anthropic_client, openai_format_messages):
        """스트리밍 시 메시지 변환 테스트"""
        async def mock_text_stream():
            yield "test"

        mock_stream = AsyncMock()
        mock_stream.__aenter__ = AsyncMock(return_value=mock_stream)
        mock_stream.__aexit__ = AsyncMock(return_value=None)
        mock_stream.text_stream = mock_text_stream()

        with patch.object(anthropic_client.client.messages, 'stream', return_value=mock_stream):
            async for _ in anthropic_client.generate_stream(messages=openai_format_messages):
                pass

            # stream 호출 확인
            anthropic_client.client.messages.stream.assert_called_once()
            call_kwargs = anthropic_client.client.messages.stream.call_args.kwargs

            # system 메시지가 별도 파라미터로 분리되었는지 확인
            assert call_kwargs["system"] == "You are a helpful assistant."
            # messages에는 user 메시지만 있어야 함
            assert len(call_kwargs["messages"]) == 1
            assert call_kwargs["messages"][0]["role"] == "user"

    @pytest.mark.asyncio
    async def test_generate_stream_error(self, anthropic_client, openai_format_messages):
        """스트리밍 오류 처리 테스트"""
        with patch.object(
            anthropic_client.client.messages,
            'stream',
            side_effect=Exception("Stream Error")
        ):
            with pytest.raises(Exception) as exc_info:
                async for _ in anthropic_client.generate_stream(messages=openai_format_messages):
                    pass

            assert "Stream Error" in str(exc_info.value)

    def test_custom_system_prompt(self):
        """커스텀 시스템 프롬프트 테스트"""
        custom_prompt = "You are a coding assistant."
        client = AnthropicClient(
            api_key="test-key",
            model="claude-sonnet-4-5-20250929",
            system_prompt=custom_prompt
        )

        assert client.system_prompt == custom_prompt

        # 메시지 변환 시 커스텀 프롬프트 사용 확인
        messages = [{"role": "user", "content": "Hello"}]
        system_msg, _ = client._convert_messages(messages)
        assert system_msg == custom_prompt
