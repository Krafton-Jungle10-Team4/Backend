"""
Anthropic Claude API 클라이언트 구현
"""
from typing import List, Dict, AsyncGenerator, Optional, Any
import logging
import httpx
from anthropic import AsyncAnthropic
from anthropic import APIError, RateLimitError, APITimeoutError

from app.core.llm_base import BaseLLMClient
from app.core.llm_registry import register_provider
from app.core.providers.config import AnthropicConfig
from app.core.exceptions import (
    LLMAPIError,
    LLMRateLimitError,
)

logger = logging.getLogger(__name__)


@register_provider("anthropic")
class AnthropicClient(BaseLLMClient):
    """Anthropic Claude API 클라이언트"""

    def __init__(self, config: AnthropicConfig):
        http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(60.0, connect=10.0),
            limits=httpx.Limits(max_keepalive_connections=5, max_connections=10)
        )
        self.config = config
        self.client = AsyncAnthropic(api_key=config.api_key, http_client=http_client)
        self.model = config.default_model
        self.system_prompt = (
            config.system_prompt
            or "당신은 유능한 AI 어시스턴트입니다. 사용자에게 친절하고 명확하게 답변해야 합니다."
        )
        logger.info("Anthropic Client 초기화: 모델=%s", self.model)
        self.last_usage: Optional[Dict[str, Any]] = None

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
        max_tokens: int = 4000,
        **kwargs
    ) -> str:
        """비동기 완료 생성"""
        try:
            # 메시지 형식 변환
            system_message, converted_messages = self._convert_messages(messages)

            # 런타임 모델 오버라이드 지원
            model_name = kwargs.pop("model", None) or self.model

            self.last_usage = None

            # Anthropic API 호출
            response = await self.client.messages.create(
                model=model_name,
                system=system_message,
                messages=converted_messages,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs
            )

            self._capture_usage(getattr(response, "usage", None), model_name)

            # 응답 텍스트 추출
            return response.content[0].text

        except RateLimitError as e:
            logger.error(f"Anthropic API 사용량 제한: {e}")
            raise LLMRateLimitError(
                message="Anthropic API 사용량 제한에 도달했습니다",
                details={"model": self.model, "error": str(e)}
            )
        except APITimeoutError as e:
            logger.error(f"Anthropic API 타임아웃: {e}")
            raise LLMAPIError(
                message="Anthropic API 요청 시간이 초과되었습니다",
                details={"model": self.model, "error": str(e)}
            )
        except APIError as e:
            logger.error(f"Anthropic API 오류: {e}")
            raise LLMAPIError(
                message=f"Anthropic API 호출 중 오류가 발생했습니다: {str(e)}",
                details={"model": self.model, "error": str(e)}
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
        max_tokens: int = 4000,
        **kwargs
    ) -> AsyncGenerator[str, None]:
        """스트리밍 응답"""
        try:
            # 메시지 형식 변환
            system_message, converted_messages = self._convert_messages(messages)

            # 런타임 모델 오버라이드 지원
            model_name = kwargs.pop("model", None) or self.model

            self.last_usage = None

            # Anthropic 스트리밍 API 호출
            chunk_count = 0
            total_text_length = 0
            
            async with self.client.messages.stream(
                model=model_name,
                system=system_message,
                messages=converted_messages,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs
            ) as stream:
                async for text in stream.text_stream:
                    if text:
                        chunk_count += 1
                        total_text_length += len(text)
                        yield text

                logger.info(f"[AnthropicClient] 스트리밍 완료: {chunk_count} chunks, {total_text_length} chars")
                
                # 사용량 추적 시도 (SDK 버전에 따라 다를 수 있음)
                try:
                    # 최신 Anthropic SDK에서는 get_final_response() 대신 다른 방법 사용
                    if hasattr(stream, 'get_final_response'):
                        final_response = await stream.get_final_response()
                        self._capture_usage(getattr(final_response, "usage", None), model_name)
                    elif hasattr(stream, 'final_message'):
                        # 대안: final_message 속성 사용
                        final_message = stream.final_message
                        self._capture_usage(getattr(final_message, "usage", None), model_name)
                    else:
                        logger.debug("[AnthropicClient] 스트리밍 사용량 추적 방법을 찾을 수 없음")
                except AttributeError as e:
                    logger.warning(f"Anthropic 스트리밍 사용량 추적 실패 (AttributeError): {e}")
                except Exception as capture_exc:
                    logger.warning(f"Anthropic 스트리밍 사용량 추적 실패: {capture_exc}")
                
                # 스트리밍이 비어있는 경우 경고
                if chunk_count == 0:
                    logger.warning(f"[AnthropicClient] 스트리밍 응답이 비어있습니다! model={model_name}, max_tokens={max_tokens}")

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

    def _capture_usage(self, usage: Optional[Any], model_name: str) -> None:
        """토큰 사용량 메타데이터 저장"""
        if not usage:
            self.last_usage = None
            return

        def _safe_get(field: str) -> int:
            if isinstance(usage, dict):
                return int(usage.get(field, 0) or 0)
            return int(getattr(usage, field, 0) or 0)

        input_tokens = _safe_get("input_tokens")
        output_tokens = _safe_get("output_tokens")
        cache_creation = _safe_get("cache_creation_input_tokens")
        cache_read = _safe_get("cache_read_input_tokens")

        self.last_usage = {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
            "cache_write_tokens": cache_creation,
            "cache_read_tokens": cache_read,
            "model": model_name
        }
