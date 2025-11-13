"""
AWS Bedrock (Anthropic Claude) API 클라이언트 구현
"""
from typing import List, Dict, AsyncGenerator, Optional
import logging
import json
import boto3
from botocore.exceptions import ClientError, BotoCoreError

from app.core.llm_base import BaseLLMClient
from app.core.llm_registry import register_provider
from app.core.providers.config import BedrockConfig
from app.core.exceptions import (
    LLMAPIError,
    LLMRateLimitError,
)

logger = logging.getLogger(__name__)


@register_provider("bedrock")
class BedrockClient(BaseLLMClient):
    """AWS Bedrock (Claude) API 클라이언트"""

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

            # Bedrock API 호출 (동기 방식 - boto3는 async 미지원)
            # 실제 프로덕션에서는 ThreadPoolExecutor 사용 권장
            import asyncio
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self.client.invoke_model(
                    modelId=model_id,
                    body=json.dumps(body)
                )
            )

            # 응답 파싱
            response_body = json.loads(response['body'].read())
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

            # Bedrock 스트리밍 호출
            import asyncio
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self.client.invoke_model_with_response_stream(
                    modelId=model_id,
                    body=json.dumps(body)
                )
            )

            # 스트림 처리
            stream = response.get('body')
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

        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', '')
            error_message = e.response.get('Error', {}).get('Message', str(e))

            if error_code == 'ThrottlingException':
                logger.error(f"Bedrock API 사용량 제한: {error_message}")
                raise LLMRateLimitError(
                    message="Bedrock API 사용량 제한에 도달했습니다",
                    details={"model": model_id, "error": error_message}
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
