"""
OpenAI API 클라이언트 구현
"""
from typing import List, Dict, AsyncGenerator, Any, Optional
import logging
import httpx
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

    @staticmethod
    def _requires_responses_endpoint(model_name: str) -> bool:
        """모델이 v1/responses 엔드포인트를 사용해야 하는지 확인"""
        normalized = (model_name or "").lower()
        return (
            normalized.startswith("o1-") or
            normalized.startswith("o3-") or
            "codex" in normalized
        )

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
            
            # v1/responses 엔드포인트가 필요한 모델인지 확인
            if self._requires_responses_endpoint(model_name):
                # v1/responses 엔드포인트 사용 (o1, o3, codex 모델)
                return await self._generate_with_responses_endpoint(
                    model_name=model_name,
                    messages=final_messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    **kwargs
                )
            
            # 일반 chat/completions 엔드포인트 사용
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

            # choices가 비어있지 않은지 확인
            if not response.choices or len(response.choices) == 0:
                logger.error("OpenAI API 응답에 choices가 없습니다")
                raise LLMAPIError(
                    message="OpenAI API 응답이 비어있습니다",
                    details={"model": model_name, "response": str(response)}
                )

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
            error_str = str(e)
            # codex, o1, o3 모델은 v1/chat/completions를 지원하지 않음
            if "only supported in v1/responses" in error_str.lower() or "not in v1/chat/completions" in error_str.lower():
                logger.error(
                    f"OpenAI 모델이 chat/completions를 지원하지 않음: {model_name}. "
                    f"이 모델은 v1/responses 엔드포인트만 지원합니다."
                )
                raise LLMAPIError(
                    message=(
                        f"선택한 모델 '{model_name}'은(는) chat/completions 엔드포인트를 지원하지 않습니다. "
                        f"이 모델은 v1/responses 엔드포인트만 지원합니다. "
                        f"chat/completions를 지원하는 모델(예: GPT-4, GPT-3.5)을 선택해주세요."
                    ),
                    details={
                        "model": model_name,
                        "error": error_str,
                        "requires_responses_endpoint": True
                    }
                )
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

            # v1/responses 엔드포인트가 필요한 모델인지 확인
            if self._requires_responses_endpoint(model_name):
                # v1/responses 엔드포인트는 스트리밍을 지원하지 않으므로 일반 생성으로 폴백
                logger.warning(
                    f"Model {model_name} does not support streaming with responses endpoint; "
                    "falling back to non-streamed response"
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
                # choices가 비어있지 않은지 확인
                if chunk.choices and len(chunk.choices) > 0:
                    delta_content = chunk.choices[0].delta.content
                    if delta_content:
                        yield delta_content
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
            error_str = str(e)
            # codex, o1, o3 모델은 v1/chat/completions를 지원하지 않음
            if "only supported in v1/responses" in error_str.lower() or "not in v1/chat/completions" in error_str.lower():
                logger.error(
                    f"OpenAI 모델이 chat/completions를 지원하지 않음: {model_name}. "
                    f"이 모델은 v1/responses 엔드포인트만 지원합니다."
                )
                raise LLMAPIError(
                    message=(
                        f"선택한 모델 '{model_name}'은(는) chat/completions 엔드포인트를 지원하지 않습니다. "
                        f"이 모델은 v1/responses 엔드포인트만 지원합니다. "
                        f"chat/completions를 지원하는 모델(예: GPT-4, GPT-3.5)을 선택해주세요."
                    ),
                    details={
                        "model": model_name,
                        "stream": True,
                        "error": error_str,
                        "requires_responses_endpoint": True
                    }
                )
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

    async def _generate_with_responses_endpoint(
        self,
        model_name: str,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 4000,
        **kwargs
    ) -> str:
        """
        v1/responses 엔드포인트를 사용한 생성 (o1, o3, codex 모델)
        
        ⚠️ 주의: 이 메서드는 실제 OpenAI API의 v1/responses 엔드포인트 형식에 맞춰 구현되었으나,
        실제 API 문서가 공개되지 않아 추정에 기반한 구현입니다.
        실제 사용 시 응답 형식이 다를 수 있으므로 로그를 확인하고 필요시 수정이 필요합니다.
        """
        try:
            # messages를 단일 프롬프트로 변환
            # o1, o3 모델은 일반적으로 단일 프롬프트를 받습니다
            prompt_parts = []
            for msg in messages:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                if role == "system":
                    prompt_parts.append(f"System: {content}")
                elif role == "user":
                    prompt_parts.append(f"User: {content}")
                elif role == "assistant":
                    prompt_parts.append(f"Assistant: {content}")
            
            prompt = "\n\n".join(prompt_parts)
            
            # v1/responses 엔드포인트 호출
            # ⚠️ 실제 API 형식이 다를 수 있으므로, 에러 발생 시 자동 폴백 처리됨
            api_key = self.config.api_key
            base_url = str(self.client.base_url) if self.client.base_url else "https://api.openai.com/v1"
            # base_url이 이미 /v1을 포함하는지 확인
            if not base_url.endswith("/v1"):
                base_url = base_url.rstrip("/") + "/v1"
            
            logger.info(f"[OpenAI] v1/responses 엔드포인트 호출 시도: model={model_name}")
            
            async with httpx.AsyncClient(timeout=60.0) as http_client:
                # 실제 API 형식은 확인 필요 - 여러 가능한 형식 시도
                request_body = {
                    "model": model_name,
                    "prompt": prompt,
                    "max_tokens": max_tokens,
                }
                
                # temperature는 일부 모델에서 지원하지 않을 수 있음
                if temperature != 1.0:
                    request_body["temperature"] = temperature
                
                response = await http_client.post(
                    f"{base_url}/responses",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json=request_body,
                )
                
                logger.info(f"[OpenAI] v1/responses 응답: status={response.status_code}")
                
                if response.status_code != 200:
                    error_data = {}
                    try:
                        if response.headers.get("content-type", "").startswith("application/json"):
                            error_data = response.json()
                    except:
                        pass
                    
                    error_msg = error_data.get("error", {}).get("message", response.text) if error_data else response.text
                    logger.error(f"[OpenAI] v1/responses API 호출 실패: {response.status_code}, {error_msg}")
                    
                    raise LLMAPIError(
                        message=f"OpenAI responses API 호출 실패: {error_msg}",
                        details={
                            "model": model_name,
                            "status_code": response.status_code,
                            "error": error_data if error_data else response.text,
                            "requires_responses_endpoint": True
                        }
                    )
                
                result = response.json()
                logger.debug(f"[OpenAI] v1/responses 응답 형식: {list(result.keys())}")
                
                # responses 엔드포인트 응답 형식 처리 (여러 가능한 형식 시도)
                text = None
                if "output" in result:
                    text = result["output"]
                elif "text" in result:
                    text = result["text"]
                elif "response" in result:
                    text = result["response"]
                elif "content" in result:
                    text = result["content"]
                elif "choices" in result and len(result["choices"]) > 0:
                    # chat/completions와 유사한 형식일 수도 있음
                    text = result["choices"][0].get("text") or result["choices"][0].get("message", {}).get("content", "")
                else:
                    # 응답 형식이 예상과 다를 경우 전체 응답 로깅
                    logger.warning(f"[OpenAI] 예상치 못한 responses API 응답 형식: {result}")
                    # 일단 전체 응답을 문자열로 변환 (디버깅용)
                    text = str(result)
                
                if not text:
                    raise LLMAPIError(
                        message="OpenAI responses API 응답에서 텍스트를 추출할 수 없습니다",
                        details={"model": model_name, "response": result}
                    )
                
                # 토큰 사용량 추출 (가능한 경우)
                if "usage" in result:
                    self._capture_usage(result["usage"], model_name)
                else:
                    self.last_usage = None
                
                logger.info(f"[OpenAI] v1/responses 성공: {len(text)} chars")
                return text
                
        except LLMAPIError:
            raise
        except httpx.HTTPError as e:
            logger.error(f"[OpenAI] responses API HTTP 오류: {e}", exc_info=True)
            raise LLMAPIError(
                message=f"OpenAI responses API 호출 중 네트워크 오류가 발생했습니다: {str(e)}",
                details={"model": model_name, "error": str(e), "requires_responses_endpoint": True}
            )
        except Exception as e:
            logger.error(f"[OpenAI] responses API 호출 실패: {e}", exc_info=True)
            raise LLMAPIError(
                message=f"OpenAI responses API 호출 중 오류가 발생했습니다: {str(e)}",
                details={"model": model_name, "error": str(e), "requires_responses_endpoint": True}
            )

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
