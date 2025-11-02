"""
Anthropic Claude API 클라이언트 구현
"""
from typing import List, Dict, Optional, AsyncGenerator
import logging
from anthropic import AsyncAnthropic
from app.core.llm_client import BaseLLMClient

logger = logging.getLogger(__name__)


class AnthropicClient(BaseLLMClient):
    """Anthropic Claude API 클라이언트"""

    def __init__(
        self,
        api_key: str,
        model: str = "claude-sonnet-4-5-20250929",
        system_prompt: Optional[str] = None,
    ):
        self.client = AsyncAnthropic(api_key=api_key)
        self.model = model
        self.system_prompt = system_prompt if system_prompt else "당신은 유능한 AI 어시스턴트입니다. 사용자에게 친절하고 명확하게 답변해야 합니다."
        logger.info(f"Anthropic Client 초기화: 모델={model}")

    def _convert_messages(
        self, messages: List[Dict[str, str]]
    ) -> tuple[Optional[str], List[Dict[str, str]]]:
        """
        OpenAI 형식 메시지를 Anthropic 형식으로 변환

        OpenAI: [{"role": "system", ...}, {"role": "user", ...}]
        Anthropic: system 파라미터 분리 + messages는 user/assistant만
        """
        system_message = None
        converted_messages = []

        for msg in messages:
            if msg.get("role") == "system":
                # system 메시지는 별도 파라미터로 분리
                system_message = msg.get("content")
            else:
                # user, assistant 메시지는 그대로 유지
                converted_messages.append(msg)

        # system 메시지가 없으면 기본 프롬프트 사용
        if system_message is None:
            system_message = self.system_prompt

        return system_message, converted_messages

    async def generate(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 1000,
        **kwargs
    ) -> str:
        """비동기 완료 생성"""
        try:
            # 메시지 형식 변환
            system_message, converted_messages = self._convert_messages(messages)

            # Anthropic API 호출
            response = await self.client.messages.create(
                model=self.model,
                system=system_message,
                messages=converted_messages,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs
            )

            # 응답 텍스트 추출
            return response.content[0].text

        except Exception as e:
            logger.error(f"Anthropic API 호출 실패: {e}")
            raise

    async def generate_stream(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 1000,
        **kwargs
    ) -> AsyncGenerator[str, None]:
        """스트리밍 응답"""
        try:
            # 메시지 형식 변환
            system_message, converted_messages = self._convert_messages(messages)

            # Anthropic 스트리밍 API 호출
            async with self.client.messages.stream(
                model=self.model,
                system=system_message,
                messages=converted_messages,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs
            ) as stream:
                async for text in stream.text_stream:
                    yield text

        except Exception as e:
            logger.error(f"Anthropic 스트리밍 실패: {e}")
            raise
