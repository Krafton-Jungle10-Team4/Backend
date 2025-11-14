"""
LLM 비용 추적 래퍼
"""
import logging
from typing import Optional, Callable, Awaitable, List
from functools import wraps
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.llm_service import LLMService
from app.services.cost_tracking_service import CostTrackingService

logger = logging.getLogger(__name__)


class LLMServiceWithCostTracking(LLMService):
    """비용 추적 기능이 포함된 LLM 서비스"""

    def __init__(
        self,
        db: AsyncSession,
        bot_id: Optional[str] = None,
        user_id: Optional[int] = None,
        *args,
        **kwargs
    ):
        super().__init__(*args, **kwargs)
        self.db = db
        self.bot_id = bot_id
        self.user_id = user_id
        self.cost_service = CostTrackingService(db)

    async def generate(
        self,
        prompt: str,
        model: Optional[str] = None,
        provider: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4000
    ) -> str:
        """비용 추적이 포함된 응답 생성"""
        # 원본 generate 호출
        response = await super().generate(
            prompt=prompt,
            model=model,
            provider=provider,
            temperature=temperature,
            max_tokens=max_tokens
        )

        # 비용 추적 (bot_id와 user_id가 설정된 경우에만)
        if self.bot_id and self.user_id:
            await self._track_usage(provider, model)

        return response

    async def generate_stream(
        self,
        prompt: str,
        model: Optional[str] = None,
        provider: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 1000,
        on_chunk: Optional[Callable[[str], Awaitable[Optional[str]]]] = None
    ) -> str:
        """비용 추적이 포함된 스트리밍 응답 생성"""
        # 원본 generate_stream 호출
        response = await super().generate_stream(
            prompt=prompt,
            model=model,
            provider=provider,
            temperature=temperature,
            max_tokens=max_tokens,
            on_chunk=on_chunk
        )

        # 비용 추적
        if self.bot_id and self.user_id:
            await self._track_usage(provider, model)

        return response

    async def generate_response(
        self,
        query: str,
        context: str,
        temperature: float = 0.7,
        max_tokens: int = 4000,
        provider: Optional[str] = None,
        model: Optional[str] = None
    ) -> str:
        """비용 추적이 포함된 RAG 응답 생성"""
        # 원본 generate_response 호출
        response = await super().generate_response(
            query=query,
            context=context,
            temperature=temperature,
            max_tokens=max_tokens,
            provider=provider,
            model=model
        )

        # 비용 추적
        if self.bot_id and self.user_id:
            await self._track_usage(provider, model)

        return response

    async def _track_usage(
        self,
        provider: Optional[str],
        model: Optional[str]
    ) -> None:
        """토큰 사용량 및 비용 추적"""
        try:
            # Provider 확인
            provider_key = self._resolve_provider(provider, model)
            client = self._get_client(provider_key)

            # last_usage 속성이 있는지 확인 (Bedrock에서 설정됨)
            if hasattr(client, 'last_usage') and client.last_usage:
                usage = client.last_usage

                await self.cost_service.log_usage(
                    bot_id=self.bot_id,
                    user_id=self.user_id,
                    provider=provider_key,
                    model_name=usage.get('model', model or 'unknown'),
                    input_tokens=usage.get('input_tokens', 0),
                    output_tokens=usage.get('output_tokens', 0),
                    cache_read_tokens=usage.get('cache_read_tokens', 0),
                    cache_write_tokens=usage.get('cache_write_tokens', 0)
                )

                logger.info(
                    f"비용 추적 완료 - bot_id: {self.bot_id}, "
                    f"tokens: {usage.get('total_tokens', 0)}"
                )
            else:
                logger.debug(
                    f"Provider {provider_key}는 토큰 사용량 추적을 지원하지 않습니다."
                )

        except Exception as e:
            # 비용 추적 실패는 서비스 전체를 막지 않음
            logger.error(f"비용 추적 중 오류 발생: {e}")


def get_llm_service_with_tracking(
    db: AsyncSession,
    bot_id: Optional[str] = None,
    user_id: Optional[int] = None
) -> LLMServiceWithCostTracking:
    """비용 추적이 포함된 LLM 서비스 인스턴스 생성"""
    return LLMServiceWithCostTracking(
        db=db,
        bot_id=bot_id,
        user_id=user_id
    )
