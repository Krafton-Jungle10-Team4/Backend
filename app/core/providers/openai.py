"""
OpenAI API 클라이언트 구현
"""
from typing import List, Dict, Optional, AsyncGenerator
import logging
from openai import AsyncOpenAI
from app.core.llm_client import BaseLLMClient

logger = logging.getLogger(__name__)


class OpenAIClient(BaseLLMClient):
    """OpenAI API 클라이언트"""

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-3.5-turbo",
        organization: Optional[str] = None,
        system_prompt: Optional[str] = None,
    ):
        self.client = AsyncOpenAI(
            api_key=api_key,
            organization=organization
        )
        self.model = model
        self.system_prompt = system_prompt if system_prompt else "당신은 유능한 AI 어시스턴트입니다. 사용자에게 친절하고 명확하게 답변해야 합니다."
        logger.info(f"OpenAI Client 초기화: 모델={model}")

    async def generate(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 1000,
        **kwargs
    ) -> str:
        """비동기 완료 생성"""
        try:
            # 시스템 한국어 지시문을 선행 주입 (이미 system 메시지가 있으면 중복 주입하지 않음)
            if any(m.get("role") == "system" for m in messages):
                final_messages = list(messages)
            else:
                final_messages = [{"role": "system", "content": self.system_prompt}, *messages]
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=final_messages,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"OpenAI API 호출 실패: {e}")
            raise

    async def generate_stream(
        self,
        messages: List[Dict[str, str]],
        **kwargs
    ) -> AsyncGenerator[str, None]:
        """스트리밍 응답"""
        try:
            # 시스템 한국어 지시문을 선행 주입 (이미 system 메시지가 있으면 중복 주입하지 않음)
            if any(m.get("role") == "system" for m in messages):
                final_messages = list(messages)
            else:
                final_messages = [{"role": "system", "content": self.system_prompt}, *messages]
            stream = await self.client.chat.completions.create(
                model=self.model,
                messages=final_messages,
                stream=True,
                **kwargs
            )
            async for chunk in stream:
                if chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except Exception as e:
            logger.error(f"OpenAI 스트리밍 실패: {e}")
            raise
