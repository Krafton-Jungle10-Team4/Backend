"""
LLM 비용 추적 래퍼
"""
import logging
from collections import defaultdict, deque
from typing import Optional, Callable, Awaitable, List, Dict, Deque, Any
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
        self._usage_snapshots: Dict[str, Deque[Any]] = defaultdict(deque)

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
        max_tokens: int = 4000,
        on_chunk: Optional[Callable[[str], Awaitable[Optional[str]]]] = None,
        system_prompt: Optional[str] = None
    ) -> str:
        """비용 추적이 포함된 스트리밍 응답 생성"""
        # 원본 generate_stream 호출
        response = await super().generate_stream(
            prompt=prompt,
            model=model,
            provider=provider,
            temperature=temperature,
            max_tokens=max_tokens,
            on_chunk=on_chunk,
            system_prompt=system_prompt
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
            resolved_model = self.last_used_model or model or getattr(client, "model", None) or "unknown"

            # last_usage 속성이 있는지 확인 (Bedrock에서 설정됨)
            if hasattr(client, 'last_usage') and client.last_usage:
                # last_usage를 읽은 후 복사본 사용
                usage = client.last_usage.copy() if isinstance(client.last_usage, dict) else client.last_usage
                self._store_usage_snapshot(provider_key, usage)
                
                # 모델 일치 확인 (추가 안전장치)
                usage_model = usage.get('model') if isinstance(usage, dict) else None
                if usage_model and usage_model != resolved_model:
                    logger.warning(
                        f"last_usage 모델 불일치 감지: usage_model={usage_model}, "
                        f"resolved_model={resolved_model}. usage_model을 사용합니다."
                    )
                    # usage_model을 사용하되, resolved_model도 로깅
                    final_model = usage_model
                else:
                    final_model = usage.get('model', resolved_model) if isinstance(usage, dict) else resolved_model
                
                # ⚠️ last_usage 초기화하지 않음 - llm_node_v2.py에서도 읽어야 함
                # 초기화는 llm_node_v2.py에서 사용 후에 수행

                await self.cost_service.log_usage(
                    bot_id=self.bot_id,
                    user_id=self.user_id,
                    provider=provider_key,
                    model_name=final_model,
                    input_tokens=usage.get('input_tokens', 0) if isinstance(usage, dict) else 0,
                    output_tokens=usage.get('output_tokens', 0) if isinstance(usage, dict) else 0,
                    cache_read_tokens=usage.get('cache_read_tokens', 0) if isinstance(usage, dict) else 0,
                    cache_write_tokens=usage.get('cache_write_tokens', 0) if isinstance(usage, dict) else 0
                )

                logger.info(
                    f"비용 추적 완료 - bot_id: {self.bot_id}, model: {final_model}, "
                    f"tokens: {usage.get('total_tokens', 0) if isinstance(usage, dict) else 0}"
                )
            else:
                logger.warning(
                    f"토큰 사용량 추적 실패 - Provider {provider_key}의 last_usage가 없습니다. "
                    f"bot_id={self.bot_id}, model={resolved_model}, "
                    f"has_last_usage_attr={hasattr(client, 'last_usage')}, "
                    f"last_usage_value={getattr(client, 'last_usage', None)}"
                )

        except Exception as e:
            # 비용 추적 실패는 서비스 전체를 막지 않음
            logger.error(f"비용 추적 중 오류 발생: {e}", exc_info=True)

    def consume_usage_snapshot(self, provider_key: Optional[str]) -> Optional[Any]:
        """워크플로우 노드가 사용할 수 있도록 토큰 사용량 스냅샷을 반환"""
        if not provider_key:
            return None

        queue = self._usage_snapshots.get(provider_key)
        if not queue:
            return None

        usage = queue.popleft()
        if not queue:
            self._usage_snapshots.pop(provider_key, None)

        return usage.copy() if isinstance(usage, dict) else usage

    def _store_usage_snapshot(self, provider_key: Optional[str], usage: Any) -> None:
        """비동기 소비를 위해 토큰 사용량을 큐에 저장"""
        if not provider_key or not usage:
            return

        snapshot = usage.copy() if isinstance(usage, dict) else usage
        self._usage_snapshots[provider_key].append(snapshot)


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
