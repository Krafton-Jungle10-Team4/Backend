"""
AWS Bedrock (Anthropic Claude) API 클라이언트 구현
"""
from typing import List, Dict, AsyncGenerator, Optional
import logging
import json
import asyncio
from concurrent.futures import ThreadPoolExecutor
import boto3
from botocore.exceptions import ClientError, BotoCoreError

from app.core.llm_base import BaseLLMClient
from app.core.llm_registry import register_provider
from app.core.providers.config import BedrockConfig
from app.core.exceptions import (
    LLMAPIError,
    LLMRateLimitError,
)
from app.core.llm_rate_limiter import LLMRateLimiter

logger = logging.getLogger(__name__)


@register_provider("bedrock")
class BedrockClient(BaseLLMClient):
    """
    AWS Bedrock (Claude) API 클라이언트
    
    동시성 처리:
    - 비동기/논블로킹: FastAPI의 async/await 사용
    - ThreadPoolExecutor: boto3 동기 호출을 스레드 풀에서 실행
    - Semaphore: 동시 요청 수 제한 (프로비저닝된 용량 보호)
    """

    # 클래스 레벨 ThreadPoolExecutor (모든 인스턴스 공유)
    # 프로비저닝된 용량 1 MU 기준: 동시 요청 10-20개 정도 처리 가능
    _executor: Optional[ThreadPoolExecutor] = None
    _executor_lock = asyncio.Lock()
    
    # 동시성 제한: Rate Limit 보호 및 비용 관리
    # ON_DEMAND 모드: 10개 동시 요청 (Rate Limit 보호)
    # 프로비저닝 모드: 1 MU = 약 15개 동시 요청 처리 가능
    _semaphore: Optional[asyncio.Semaphore] = None
    _max_concurrent_requests: Optional[int] = None  # 동적으로 계산됨
    _provisioned_model_units: int = 0  # 프로비저닝된 용량 (Model Units)

    def __init__(self, config: BedrockConfig):
        self.config = config
        self.client = boto3.client(
            'bedrock-runtime',
            region_name=config.region_name
        )
        self.model = config.default_model
        self.system_prompt = (
            config.system_prompt
            or "당신은 유능한 AI 어시스턴트입니다. 사용자에게 친절하고 명확하게 답변해야 합니다."
        )
        
        # 프로비저닝된 용량 확인 및 동시성 제한 계산
        from app.config import settings
        provisioned_units = getattr(settings, 'bedrock_provisioned_model_units', 0) or 0
        
        # 동시성 제한 계산: 1 MU = 15개 동시 요청
        # 프로비저닝된 용량이 없으면 (0) ON_DEMAND 모델 사용
        if provisioned_units > 0:
            max_concurrent = provisioned_units * 15
            logger.info(
                f"📊 프로비저닝된 용량: {provisioned_units} MU → "
                f"동시성 제한: {max_concurrent}개 동시 요청"
            )
        else:
            # ON_DEMAND 모델: 10개 동시 요청 제한
            # - Rate Limit 보호
            # - $300/월 예산 기준 안정적 운영 (일평균 950회 요청 처리 가능)
            # - 100명 동시 접속 가능 (요청은 10개씩 순차 처리)
            max_concurrent = 10
            logger.info(
                f"📊 ON_DEMAND 모델 사용 → 동시성 제한: {max_concurrent}개 동시 요청 "
                f"(Rate Limit 보호, 예산: $300/월 기준)"
            )
        
        # ThreadPoolExecutor 초기화 (최초 1회만)
        if BedrockClient._executor is None:
            # 스레드 풀 크기: 동시성 제한의 1.5배 (여유분 확보)
            thread_pool_size = max(max_concurrent * 2, 20)
            BedrockClient._executor = ThreadPoolExecutor(
                max_workers=thread_pool_size,
                thread_name_prefix="bedrock-llm"
            )
            logger.info(f"✅ Bedrock ThreadPoolExecutor 초기화 완료 (max_workers={thread_pool_size})")
        
        # Semaphore 초기화 (최초 1회만 또는 프로비저닝된 용량 변경 시)
        if BedrockClient._semaphore is None or BedrockClient._max_concurrent_requests != max_concurrent:
            BedrockClient._max_concurrent_requests = max_concurrent
            BedrockClient._provisioned_model_units = provisioned_units
            BedrockClient._semaphore = asyncio.Semaphore(max_concurrent)
            logger.info(
                f"✅ Bedrock 동시성 제한 설정 완료 "
                f"(프로비저닝: {provisioned_units} MU, "
                f"동시 요청: {max_concurrent}개)"
            )
        
        logger.info(f"Bedrock Client 초기화: 모델={self.model}, 리전={config.region_name}")

    def _convert_messages(
        self, messages: List[Dict[str, str]]
    ) -> tuple[Optional[str], List[Dict[str, str]]]:
        """
        OpenAI 형식 메시지를 Bedrock (Anthropic) 형식으로 변환
        """
        system_message = None
        converted_messages = []

        for msg in messages:
            if msg.get("role") == "system":
                system_message = msg.get("content")
            else:
                converted_messages.append(msg)

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
            model_id = kwargs.pop("model", None) or self.model

            # Bedrock API 요청 본문
            body = {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": max_tokens,
                "temperature": temperature,
                "messages": converted_messages
            }

            # system 프롬프트 추가
            if system_message:
                body["system"] = system_message

            # 동시성 제한: Semaphore로 동시 요청 수 제어
            await LLMRateLimiter.acquire("bedrock")
            async with BedrockClient._semaphore:
                # Bedrock API 호출 (동기 방식 - boto3는 async 미지원)
                # ThreadPoolExecutor를 사용하여 논블로킹 처리
                loop = asyncio.get_event_loop()
                response = await loop.run_in_executor(
                    BedrockClient._executor,
                    lambda: self.client.invoke_model(
                        modelId=model_id,
                        body=json.dumps(body)
                    )
                )

            # 응답 파싱
            response_body = json.loads(response['body'].read())

            # 토큰 사용량 추출 및 저장
            usage = response_body.get('usage', {})
            input_tokens = usage.get('input_tokens', 0)
            output_tokens = usage.get('output_tokens', 0)

            # 토큰 사용량 메타데이터 저장 (middleware에서 접근 가능)
            self.last_usage = {
                'input_tokens': input_tokens,
                'output_tokens': output_tokens,
                'total_tokens': input_tokens + output_tokens,
                'cache_read_tokens': usage.get('cache_read_input_token_count', 0),
                'cache_write_tokens': usage.get('cache_creation_input_token_count', 0),
                'model': model_id
            }

            logger.info(
                f"Bedrock 토큰 사용량 - 입력: {input_tokens}, 출력: {output_tokens}, 총: {input_tokens + output_tokens}"
            )

            return response_body['content'][0]['text']

        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', '')
            error_message = e.response.get('Error', {}).get('Message', str(e))

            if error_code == 'ThrottlingException':
                logger.error(f"Bedrock API 사용량 제한: {error_message}")
                raise LLMRateLimitError(
                    message="Bedrock API 사용량 제한에 도달했습니다",
                    details={"model": model_id, "error": error_message}
                )
            elif "on-demand throughput isn't supported" in error_message.lower():
                # ON_DEMAND를 지원하지 않는 모델 (INFERENCE_PROFILE만 지원)
                logger.error(
                    f"Bedrock 모델이 ON_DEMAND를 지원하지 않음: {model_id}. "
                    f"이 모델은 프로비저닝된 용량(Provisioned Throughput)이 필요합니다."
                )
                raise LLMAPIError(
                    message=(
                        f"선택한 모델 '{model_id}'은(는) ON_DEMAND 모드를 지원하지 않습니다. "
                        f"이 모델은 프로비저닝된 용량(Provisioned Throughput)이 필요합니다. "
                        f"ON_DEMAND를 지원하는 모델(예: Claude 3 Haiku, Claude 3.5 Sonnet)을 선택해주세요."
                    ),
                    details={
                        "model": model_id,
                        "error_code": error_code,
                        "error": error_message,
                        "requires_provisioned_throughput": True
                    }
                )
            elif error_code == "INVALID_PAYMENT_INSTRUMENT" or "payment instrument" in error_message.lower():
                # 결제수단/모델 구독 미완료 → 기본 모델로 자동 폴백 시도
                if model_id != self.model:
                    logger.warning(
                        "Bedrock 모델 %s 접근 거부(INVALID_PAYMENT_INSTRUMENT). 기본 모델(%s)로 폴백 시도.",
                        model_id,
                        self.model
                    )
                    return await self.generate(
                        messages=messages,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        **kwargs
                    )

                logger.error(
                    "Bedrock 모델 접근 거부(INVALID_PAYMENT_INSTRUMENT): %s. "
                    "결제 수단/모델 액세스 승인 필요.",
                    error_message
                )
                raise LLMAPIError(
                    message=(
                        "Bedrock 모델 결제/접근이 활성화되어 있지 않습니다. "
                        "AWS 콘솔에서 결제 수단 등록 또는 해당 모델 액세스 승인이 필요합니다."
                    ),
                    details={"model": model_id, "error_code": error_code, "error": error_message}
                )
            else:
                logger.error(f"Bedrock API 오류: {error_message}")
                raise LLMAPIError(
                    message=f"Bedrock API 호출 실패: {error_message}",
                    details={"model": model_id, "error_code": error_code}
                )

        except BotoCoreError as e:
            logger.error(f"Bedrock 연결 오류: {e}")
            raise LLMAPIError(
                message=f"Bedrock 연결 실패: {str(e)}",
                details={"model": self.model}
            )

        except Exception as e:
            logger.error(f"예상치 못한 오류: {e}")
            raise LLMAPIError(
                message=f"LLM 생성 실패: {str(e)}",
                details={"model": self.model}
            )

    async def generate_stream(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 4000,
        **kwargs
    ) -> AsyncGenerator[str, None]:
        """스트리밍 응답 생성"""
        try:
            # 메시지 형식 변환
            system_message, converted_messages = self._convert_messages(messages)

            # 런타임 모델 오버라이드 지원
            model_id = kwargs.pop("model", None) or self.model

            # Bedrock API 요청 본문
            body = {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": max_tokens,
                "temperature": temperature,
                "messages": converted_messages
            }

            if system_message:
                body["system"] = system_message

            # 동시성 제한: Semaphore로 동시 요청 수 제어
            await LLMRateLimiter.acquire("bedrock")
            async with BedrockClient._semaphore:
                # Bedrock 스트리밍 호출 (동기 방식 - boto3는 async 미지원)
                # ThreadPoolExecutor를 사용하여 논블로킹 처리
                loop = asyncio.get_event_loop()
                response = await loop.run_in_executor(
                    BedrockClient._executor,
                    lambda: self.client.invoke_model_with_response_stream(
                        modelId=model_id,
                        body=json.dumps(body)
                    )
                )

            # 스트림 처리
            stream = response.get('body')
            total_input_tokens = 0
            total_output_tokens = 0
            cache_read_tokens = 0
            cache_write_tokens = 0

            def _update_cache_usage(usage_data: Optional[Dict[str, int]]) -> None:
                """Bedrock 스트리밍 이벤트에서 캐시 토큰 수치를 추출"""
                nonlocal cache_read_tokens, cache_write_tokens
                if not usage_data:
                    return

                def _extract_value(*keys: str) -> int:
                    for key in keys:
                        if key in usage_data and usage_data[key] is not None:
                            return int(usage_data[key])
                    return 0

                read_tokens = _extract_value(
                    'cache_read_input_token_count',
                    'cache_read_input_tokens',
                    'cache_read_tokens'
                )
                write_tokens = _extract_value(
                    'cache_creation_input_token_count',
                    'cache_creation_input_tokens',
                    'cache_write_tokens'
                )

                # Bedrock은 누적 수치를 보내므로 가장 큰 값을 유지
                if read_tokens > cache_read_tokens:
                    cache_read_tokens = read_tokens
                if write_tokens > cache_write_tokens:
                    cache_write_tokens = write_tokens

            if stream:
                for event in stream:
                    chunk = event.get('chunk')
                    if chunk:
                        chunk_data = json.loads(chunk.get('bytes').decode())

                        # content_block_delta 이벤트에서 텍스트 추출
                        if chunk_data.get('type') == 'content_block_delta':
                            delta = chunk_data.get('delta', {})
                            if delta.get('type') == 'text_delta':
                                text = delta.get('text', '')
                                if text:
                                    yield text

                        # message_delta에서 토큰 사용량 추출
                        elif chunk_data.get('type') == 'message_delta':
                            usage = chunk_data.get('usage', {})
                            total_output_tokens = usage.get('output_tokens', total_output_tokens)
                            _update_cache_usage(usage)

                        # message_start에서 입력 토큰 추출
                        elif chunk_data.get('type') == 'message_start':
                            usage = chunk_data.get('message', {}).get('usage', {})
                            total_input_tokens = usage.get('input_tokens', 0)
                            _update_cache_usage(usage)

                        elif chunk_data.get('type') == 'message_stop':
                            usage = chunk_data.get('usage', {})
                            total_output_tokens = usage.get('output_tokens', total_output_tokens)
                            _update_cache_usage(usage)

            # 스트리밍 완료 후 토큰 사용량 저장
            self.last_usage = {
                'input_tokens': total_input_tokens,
                'output_tokens': total_output_tokens,
                'total_tokens': total_input_tokens + total_output_tokens,
                'cache_read_tokens': cache_read_tokens,
                'cache_write_tokens': cache_write_tokens,
                'model': model_id
            }

            logger.info(
                f"Bedrock 스트리밍 토큰 사용량 - 입력: {total_input_tokens}, 출력: {total_output_tokens}"
            )

        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', '')
            error_message = e.response.get('Error', {}).get('Message', str(e))

            if error_code == 'ThrottlingException':
                logger.error(f"Bedrock API 사용량 제한: {error_message}")
                raise LLMRateLimitError(
                    message="Bedrock API 사용량 제한에 도달했습니다",
                    details={"model": model_id, "error": error_message}
                )
            elif "on-demand throughput isn't supported" in error_message.lower():
                # ON_DEMAND를 지원하지 않는 모델 (INFERENCE_PROFILE만 지원)
                logger.error(
                    f"Bedrock 모델이 ON_DEMAND를 지원하지 않음: {model_id}. "
                    f"이 모델은 프로비저닝된 용량(Provisioned Throughput)이 필요합니다."
                )
                raise LLMAPIError(
                    message=(
                        f"선택한 모델 '{model_id}'은(는) ON_DEMAND 모드를 지원하지 않습니다. "
                        f"이 모델은 프로비저닝된 용량(Provisioned Throughput)이 필요합니다. "
                        f"ON_DEMAND를 지원하는 모델(예: Claude 3 Haiku, Claude 3.5 Sonnet)을 선택해주세요."
                    ),
                    details={
                        "model": model_id,
                        "error_code": error_code,
                        "error": error_message,
                        "requires_provisioned_throughput": True
                    }
                )
            elif error_code == "INVALID_PAYMENT_INSTRUMENT" or "payment instrument" in error_message.lower():
                if model_id != self.model:
                    logger.warning(
                        "Bedrock 모델 %s 접근 거부(INVALID_PAYMENT_INSTRUMENT). 기본 모델(%s)로 스트리밍 폴백 시도.",
                        model_id,
                        self.model
                    )
                    async for chunk in self.generate_stream(
                        messages=messages,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        model=self.model,
                        **kwargs
                    ):
                        yield chunk
                    return

                logger.error(
                    "Bedrock 모델 접근 거부(INVALID_PAYMENT_INSTRUMENT): %s. "
                    "결제 수단/모델 액세스 승인 필요.",
                    error_message
                )
                raise LLMAPIError(
                    message=(
                        "Bedrock 모델 결제/접근이 활성화되어 있지 않습니다. "
                        "AWS 콘솔에서 결제 수단 등록 또는 해당 모델 액세스 승인이 필요합니다."
                    ),
                    details={"model": model_id, "error_code": error_code, "error": error_message}
                )
            else:
                logger.error(f"Bedrock API 오류: {error_message}")
                raise LLMAPIError(
                    message=f"Bedrock API 호출 실패: {error_message}",
                    details={"model": model_id, "error_code": error_code}
                )

        except Exception as e:
            logger.error(f"스트리밍 오류: {e}")
            raise LLMAPIError(
                message=f"스트리밍 생성 실패: {str(e)}",
                details={"model": self.model}
            )
