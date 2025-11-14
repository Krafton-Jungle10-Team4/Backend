"""
LLM 비용 추적 서비스
"""
import logging
from typing import Optional, Dict, Any
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.llm_usage import LLMUsageLog, ModelPricing

logger = logging.getLogger(__name__)


class CostTrackingService:
    """LLM 사용량 및 비용 추적 서비스"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_model_pricing(
        self, provider: str, model_name: str
    ) -> Optional[ModelPricing]:
        """모델 가격 정보 조회"""
        query = select(ModelPricing).where(
            ModelPricing.provider == provider,
            ModelPricing.model_name == model_name,
            ModelPricing.is_active == 1
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    def calculate_cost(
        self,
        input_tokens: int,
        output_tokens: int,
        cache_read_tokens: int,
        cache_write_tokens: int,
        pricing: ModelPricing
    ) -> Dict[str, float]:
        """토큰 사용량을 기반으로 비용 계산"""
        # 입력 토큰 비용
        input_cost = (input_tokens / 1000) * pricing.input_price_per_1k

        # 출력 토큰 비용
        output_cost = (output_tokens / 1000) * pricing.output_price_per_1k

        # 캐시 비용 (선택적)
        cache_cost = 0.0
        if pricing.cache_write_price_per_1k and cache_write_tokens > 0:
            cache_cost += (cache_write_tokens / 1000) * pricing.cache_write_price_per_1k

        if pricing.cache_read_price_per_1k and cache_read_tokens > 0:
            cache_cost += (cache_read_tokens / 1000) * pricing.cache_read_price_per_1k

        total_cost = input_cost + output_cost + cache_cost

        return {
            'input_cost': round(input_cost, 6),
            'output_cost': round(output_cost, 6),
            'cache_cost': round(cache_cost, 6),
            'total_cost': round(total_cost, 6)
        }

    async def log_usage(
        self,
        bot_id: str,
        user_id: int,
        provider: str,
        model_name: str,
        input_tokens: int,
        output_tokens: int,
        cache_read_tokens: int = 0,
        cache_write_tokens: int = 0,
        request_id: Optional[str] = None,
        session_id: Optional[str] = None
    ) -> Optional[LLMUsageLog]:
        """LLM 사용량 로깅"""
        try:
            # 모델 가격 정보 조회
            pricing = await self.get_model_pricing(provider, model_name)

            if not pricing:
                logger.warning(
                    f"모델 가격 정보 없음: provider={provider}, model={model_name}. "
                    "비용 계산 없이 사용량만 기록합니다."
                )
                # 가격 정보 없어도 사용량은 기록 (비용은 0으로)
                input_cost = 0.0
                output_cost = 0.0
                total_cost = 0.0
            else:
                # 비용 계산
                costs = self.calculate_cost(
                    input_tokens,
                    output_tokens,
                    cache_read_tokens,
                    cache_write_tokens,
                    pricing
                )
                input_cost = costs['input_cost']
                output_cost = costs['output_cost']
                total_cost = costs['total_cost']

            # 사용 로그 생성
            usage_log = LLMUsageLog(
                bot_id=bot_id,
                user_id=user_id,
                provider=provider,
                model_name=model_name,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=input_tokens + output_tokens,
                cache_read_tokens=cache_read_tokens,
                cache_write_tokens=cache_write_tokens,
                input_cost=input_cost,
                output_cost=output_cost,
                total_cost=total_cost,
                request_id=request_id,
                session_id=session_id
            )

            self.db.add(usage_log)
            await self.db.commit()
            await self.db.refresh(usage_log)

            logger.info(
                f"LLM 사용량 로깅 완료 - bot_id: {bot_id}, model: {model_name}, "
                f"tokens: {input_tokens + output_tokens}, cost: ${total_cost:.6f}"
            )

            return usage_log

        except Exception as e:
            logger.error(f"LLM 사용량 로깅 실패: {e}")
            await self.db.rollback()
            return None

    async def add_model_pricing(
        self,
        provider: str,
        model_name: str,
        input_price_per_1k: float,
        output_price_per_1k: float,
        cache_write_price_per_1k: Optional[float] = None,
        cache_read_price_per_1k: Optional[float] = None,
        region: Optional[str] = None
    ) -> ModelPricing:
        """새로운 모델 가격 정보 추가"""
        pricing = ModelPricing(
            provider=provider,
            model_name=model_name,
            input_price_per_1k=input_price_per_1k,
            output_price_per_1k=output_price_per_1k,
            cache_write_price_per_1k=cache_write_price_per_1k,
            cache_read_price_per_1k=cache_read_price_per_1k,
            region=region,
            is_active=1
        )

        self.db.add(pricing)
        await self.db.commit()
        await self.db.refresh(pricing)

        logger.info(f"모델 가격 정보 추가: {provider}/{model_name}")
        return pricing


def get_cost_tracking_service(db: AsyncSession) -> CostTrackingService:
    """비용 추적 서비스 인스턴스 생성"""
    return CostTrackingService(db)
