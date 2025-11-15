"""
OpenAI API 클라이언트 구현
"""
from typing import List, Dict, AsyncGenerator, Any, Optional
import logging
from openai import AsyncOpenAI
from openai import APIError, RateLimitError, APITimeoutError

from app.core.llm_base import BaseLLMClient
from app.core.llm_registry import register_provider
from app.core.providers.config import OpenAIConfig
from app.core.exceptions import (
    LLMAPIError,
    LLMRateLimitError,
)

logger = logging.getLogger(__name__)


@register_provider("openai")
class OpenAIClient(BaseLLMClient):
    """OpenAI API 클라이언트"""

    def __init__(self, config: OpenAIConfig):
        self.config = config
        self.client = AsyncOpenAI(
            api_key=config.api_key,
            organization=config.organization
        )
        self.model = config.default_model
        self.system_prompt = (
            config.system_prompt
            or "당신은 유능한 AI 어시스턴트입니다. 사용자에게 친절하고 명확하게 답변해야 합니다."
        )
        logger.info("OpenAI Client 초기화: 모델=%s", self.model)
        self.last_usage: Optional[Dict[str, Any]] = None

    async def generate(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 4000,
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
            request_kwargs = self._build_request_kwargs(
                model_name=model_name,
                temperature=temperature,
                max_tokens=max_tokens,
                extra_kwargs=kwargs,
                stream=False
            )

            self.last_usage = None
            response = await self.client.chat.completions.create(
                model=model_name,
                messages=final_messages,
                **request_kwargs
            )
            self._capture_usage(getattr(response, "usage", None), model_name)
            return response.choices[0].message.content
        except RateLimitError as e:
            logger.error(f"OpenAI API 사용량 제한: {e}")
            raise LLMRateLimitError(
                message="OpenAI API 사용량 제한에 도달했습니다",
                details={"model": self.model, "error": str(e)}
            )
        except APITimeoutError as e:
            logger.error(f"OpenAI API 타임아웃: {e}")
            raise LLMAPIError(
                message="OpenAI API 요청 시간이 초과되었습니다",
                details={"model": self.model, "error": str(e)}
            )
        except APIError as e:
            logger.error(f"OpenAI API 오류: {e}")
            raise LLMAPIError(
                message=f"OpenAI API 호출 중 오류가 발생했습니다: {str(e)}",
                details={"model": self.model, "error": str(e)}
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
        temperature: float = 0.7,
        max_tokens: int = 4000,
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

            if not self._supports_stream(model_name):
                logger.warning(
                    "Model %s does not support streaming; falling back to non-streamed response",
                    model_name
                )
                text = await self.generate(
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    model=model_name,
                    **kwargs
                )
                yield text
                return

            request_kwargs = self._build_request_kwargs(
                model_name=model_name,
                temperature=temperature,
                max_tokens=max_tokens,
                extra_kwargs=kwargs,
                stream=True
            )

            self.last_usage = None
            stream = await self.client.chat.completions.create(
                model=model_name,
                messages=final_messages,
                **request_kwargs
            )
            async for chunk in stream:
                if chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
                usage_payload = getattr(chunk, "usage", None)
                if usage_payload:
                    self._capture_usage(usage_payload, model_name)
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

    @staticmethod
    def _token_param_for_model(model_name: str) -> str:
        """모델에 맞는 토큰 파라미터명 반환"""
        normalized = (model_name or "").lower()
        omni_prefixes = ("gpt-4o", "gpt-4.1", "gpt-5")
        if any(normalized.startswith(prefix) for prefix in omni_prefixes):
            return "max_completion_tokens"
        return "max_tokens"

    @staticmethod
    def _supports_temperature(model_name: str) -> bool:
        """모델이 temperature 파라미터를 지원하는지"""
        normalized = (model_name or "").lower()
        restricted_prefixes = ("gpt-5",)
        return not any(normalized.startswith(prefix) for prefix in restricted_prefixes)

    def _normalize_temperature(
        self,
        supports_temperature: bool,
        requested_temperature: float,
        model_name: str
    ) -> float:
        """모델 정책에 맞는 temperature 값 반환"""
        if supports_temperature:
            return requested_temperature

        if requested_temperature != 1:
            logger.warning(
                "Model %s ignores temperature %.2f; forcing 1.0",
                model_name,
                requested_temperature
            )
        return 1.0

    @staticmethod
    def _supports_stream(model_name: str) -> bool:
        """모델이 스트리밍을 지원하는지"""
        normalized = (model_name or "").lower()
        restricted_prefixes = ("gpt-5",)
        return not any(normalized.startswith(prefix) for prefix in restricted_prefixes)

    def _build_request_kwargs(
        self,
        model_name: str,
        temperature: float,
        max_tokens: int,
        extra_kwargs: Dict,
        stream: bool
    ) -> Dict:
        """모델 종류에 따라 적절한 파라미터를 구성"""
        request_kwargs = dict(extra_kwargs or {})

        supports_temperature = self._supports_temperature(model_name)
        normalized_temperature = self._normalize_temperature(
            supports_temperature,
            temperature,
            model_name
        )
        if supports_temperature or normalized_temperature != 1:
            request_kwargs.setdefault("temperature", normalized_temperature)

        desired_key = self._token_param_for_model(model_name)
        alt_key = "max_completion_tokens" if desired_key == "max_tokens" else "max_tokens"

        if desired_key not in request_kwargs:
            if alt_key in request_kwargs:
                request_kwargs[desired_key] = request_kwargs.pop(alt_key)
            else:
                request_kwargs[desired_key] = max_tokens
        elif alt_key in request_kwargs:
            # 혼재되어 있으면 필요한 키만 유지
            request_kwargs.pop(alt_key, None)

        if stream:
            request_kwargs["stream"] = True
            request_kwargs.setdefault("stream_options", {"include_usage": True})

        return request_kwargs

    def _capture_usage(self, usage: Optional[Any], model_name: str) -> None:
        """토큰 사용량 메타데이터 저장"""
        if not usage:
            self.last_usage = None
            return

        if isinstance(usage, dict):
            prompt_tokens = int(usage.get("prompt_tokens", 0) or 0)
            completion_tokens = int(usage.get("completion_tokens", 0) or 0)
            total_tokens = int(usage.get("total_tokens", prompt_tokens + completion_tokens) or 0)
        else:
            prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
            completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
            reported_total = getattr(usage, "total_tokens", None)
            total_tokens = int(reported_total or (prompt_tokens + completion_tokens))

        self.last_usage = {
            "input_tokens": prompt_tokens,
            "output_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "cache_write_tokens": 0,
            "cache_read_tokens": 0,
            "model": model_name
        }
