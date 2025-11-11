"""
Anthropic Claude API 클라이언트 구현
"""
from typing import List, Dict, Optional, AsyncGenerator
import logging
import httpx
from anthropic import AsyncAnthropic
from anthropic import APIError, RateLimitError, APITimeoutError
from app.core.llm_client import BaseLLMClient
from app.core.exceptions import (
    LLMAPIError,
    LLMRateLimitError,
    LLMInvalidResponseError
)

logger = logging.getLogger(__name__)


class AnthropicClient(BaseLLMClient):
    """Anthropic Claude API 클라이언트"""

    def __init__(
        self,
        api_key: str,
        model: str = "claude-sonnet-4-5-20250929",
        system_prompt: Optional[str] = None,
    ):
        # httpx 클라이언트를 명시적으로 생성 (proxies 파라미터 제거)
        http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(60.0, connect=10.0),
            limits=httpx.Limits(max_keepalive_connections=5, max_connections=10)
        )
        self.client = AsyncAnthropic(api_key=api_key, http_client=http_client)
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

            # 런타임 모델 오버라이드 지원
            model_name = kwargs.pop("model", None) or self.model

            # Anthropic API 호출
            response = await self.client.messages.create(
                model=model_name,
                system=system_message,
                messages=converted_messages,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs
            )

            # 응답 텍스트 추출
            return response.content[0].text

        except RateLimitError as e:
            logger.error(f"Anthropic API 사용량 제한: {e}")
            raise LLMRateLimitError(
                message="Anthropic API 사용량 제한에 도달했습니다",
                details={
                    "model": self.model,
                    "error": str(e)
                }
            )
        except APITimeoutError as e:
            logger.error(f"Anthropic API 타임아웃: {e}")
            raise LLMAPIError(
                message="Anthropic API 요청 시간이 초과되었습니다",
                details={
                    "model": self.model,
                    "error": str(e)
                }
            )
        except APIError as e:
            logger.error(f"Anthropic API 오류: {e}")
            raise LLMAPIError(
                message=f"Anthropic API 호출 중 오류가 발생했습니다: {str(e)}",
                details={
                    "model": self.model,
                    "error": str(e)
                }
            )
        except Exception as e:
            logger.error(f"Anthropic API 호출 실패 (예기치 않은 오류): {e}", exc_info=True)
            raise LLMAPIError(
                message="Anthropic API 호출 중 예기치 않은 오류가 발생했습니다",
                details={
                    "model": self.model,
                    "error_type": type(e).__name__,
                    "error": str(e)
                }
            )

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

            # 런타임 모델 오버라이드 지원
            model_name = kwargs.pop("model", None) or self.model

            # Anthropic 스트리밍 API 호출
            async with self.client.messages.stream(
                model=model_name,
                system=system_message,
                messages=converted_messages,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs
            ) as stream:
                async for text in stream.text_stream:
                    yield text

        except RateLimitError as e:
            logger.error(f"Anthropic API 사용량 제한 (스트리밍): {e}")
            raise LLMRateLimitError(
                message="Anthropic API 사용량 제한에 도달했습니다",
                details={
                    "model": self.model,
                    "stream": True,
                    "error": str(e)
                }
            )
        except APIError as e:
            logger.error(f"Anthropic 스트리밍 오류: {e}")
            raise LLMAPIError(
                message=f"Anthropic 스트리밍 중 오류가 발생했습니다: {str(e)}",
                details={
                    "model": self.model,
                    "stream": True,
                    "error": str(e)
                }
            )
        except Exception as e:
            logger.error(f"Anthropic 스트리밍 실패 (예기치 않은 오류): {e}", exc_info=True)
            raise LLMAPIError(
                message="Anthropic 스트리밍 중 예기치 않은 오류가 발생했습니다",
                details={
                    "model": self.model,
                    "stream": True,
                    "error_type": type(e).__name__,
                    "error": str(e)
                }
            )
