"""
OpenAI API 클라이언트 구현
"""
from typing import List, Dict, Optional, AsyncGenerator
import logging
from openai import AsyncOpenAI
from openai import APIError, RateLimitError, APITimeoutError
from app.core.llm_client import BaseLLMClient
from app.core.exceptions import (
    LLMAPIError,
    LLMRateLimitError,
    LLMInvalidResponseError
)

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

            # 런타임 모델 오버라이드 지원
            model_name = kwargs.pop("model", None) or self.model

            response = await self.client.chat.completions.create(
                model=model_name,
                messages=final_messages,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs
            )
            return response.choices[0].message.content
        except RateLimitError as e:
            logger.error(f"OpenAI API 사용량 제한: {e}")
            raise LLMRateLimitError(
                message="OpenAI API 사용량 제한에 도달했습니다",
                details={
                    "model": self.model,
                    "error": str(e)
                }
            )
        except APITimeoutError as e:
            logger.error(f"OpenAI API 타임아웃: {e}")
            raise LLMAPIError(
                message="OpenAI API 요청 시간이 초과되었습니다",
                details={
                    "model": self.model,
                    "error": str(e)
                }
            )
        except APIError as e:
            logger.error(f"OpenAI API 오류: {e}")
            raise LLMAPIError(
                message=f"OpenAI API 호출 중 오류가 발생했습니다: {str(e)}",
                details={
                    "model": self.model,
                    "error": str(e)
                }
            )
        except Exception as e:
            logger.error(f"OpenAI API 호출 실패 (예기치 않은 오류): {e}", exc_info=True)
            raise LLMAPIError(
                message="OpenAI API 호출 중 예기치 않은 오류가 발생했습니다",
                details={
                    "model": self.model,
                    "error_type": type(e).__name__,
                    "error": str(e)
                }
            )

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

            # 런타임 모델 오버라이드 지원
            model_name = kwargs.pop("model", None) or self.model

            stream = await self.client.chat.completions.create(
                model=model_name,
                messages=final_messages,
                stream=True,
                **kwargs
            )
            async for chunk in stream:
                if chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except RateLimitError as e:
            logger.error(f"OpenAI API 사용량 제한 (스트리밍): {e}")
            raise LLMRateLimitError(
                message="OpenAI API 사용량 제한에 도달했습니다",
                details={
                    "model": self.model,
                    "stream": True,
                    "error": str(e)
                }
            )
        except APIError as e:
            logger.error(f"OpenAI 스트리밍 오류: {e}")
            raise LLMAPIError(
                message=f"OpenAI 스트리밍 중 오류가 발생했습니다: {str(e)}",
                details={
                    "model": self.model,
                    "stream": True,
                    "error": str(e)
                }
            )
        except Exception as e:
            logger.error(f"OpenAI 스트리밍 실패 (예기치 않은 오류): {e}", exc_info=True)
            raise LLMAPIError(
                message="OpenAI 스트리밍 중 예기치 않은 오류가 발생했습니다",
                details={
                    "model": self.model,
                    "stream": True,
                    "error_type": type(e).__name__,
                    "error": str(e)
                }
            )
