"""
LLM 비용 모니터링 API 엔드포인트
"""
import logging
from typing import List, Optional
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from pydantic import BaseModel, Field

from app.core.database import get_db
from app.models.llm_usage import LLMUsageLog, ModelPricing
from app.models.user import User
from app.core.auth.dependencies import get_current_user_from_jwt_only

logger = logging.getLogger(__name__)
router = APIRouter()


# Response Models
class UsageStatsResponse(BaseModel):
    """사용량 통계 응답"""
    bot_id: str
    total_requests: int
    total_input_tokens: int
    total_output_tokens: int
    total_tokens: int
    total_cost: float
    period_start: Optional[datetime] = None
    period_end: Optional[datetime] = None


class ModelUsageBreakdown(BaseModel):
    """모델별 사용량 분해"""
    provider: str
    model_name: str
    request_count: int
    total_input_tokens: int
    total_output_tokens: int
    total_cost: float


class DailyCostSummary(BaseModel):
    """일별 비용 요약"""
    date: str
    request_count: int
    total_tokens: int
    total_cost: float


class PricingInfo(BaseModel):
    """모델 가격 정보"""
    provider: str
    model_name: str
    input_price_per_1k: float
    output_price_per_1k: float
    cache_write_price_per_1k: Optional[float] = None
    cache_read_price_per_1k: Optional[float] = None
    region: Optional[str] = None


@router.get("/usage/{bot_id}", response_model=UsageStatsResponse)
async def get_bot_usage_stats(
    bot_id: str,
    start_date: Optional[datetime] = Query(None, description="시작 날짜 (YYYY-MM-DD)"),
    end_date: Optional[datetime] = Query(None, description="종료 날짜 (YYYY-MM-DD)"),
    current_user: User = Depends(get_current_user_from_jwt_only),
    db: AsyncSession = Depends(get_db)
):
    """
    특정 봇의 LLM 사용량 및 비용 통계 조회
    """
    # 날짜 범위 설정 (기본값: 최근 30일)
    if not end_date:
        end_date = datetime.utcnow()
    if not start_date:
        start_date = end_date - timedelta(days=30)

    # 쿼리 조건
    conditions = [
        LLMUsageLog.bot_id == bot_id,
        LLMUsageLog.created_at >= start_date,
        LLMUsageLog.created_at <= end_date
    ]

    # 사용자 필터 (자신의 봇만 조회 가능)
    conditions.append(LLMUsageLog.user_id == current_user.id)

    # 집계 쿼리
    query = select(
        func.count(LLMUsageLog.id).label('total_requests'),
        func.sum(LLMUsageLog.input_tokens).label('total_input_tokens'),
        func.sum(LLMUsageLog.output_tokens).label('total_output_tokens'),
        func.sum(LLMUsageLog.total_tokens).label('total_tokens'),
        func.sum(LLMUsageLog.total_cost).label('total_cost')
    ).where(and_(*conditions))

    result = await db.execute(query)
    row = result.first()

    if not row or row.total_requests == 0:
        raise HTTPException(
            status_code=404,
            detail=f"봇 {bot_id}의 사용 기록을 찾을 수 없습니다."
        )

    return UsageStatsResponse(
        bot_id=bot_id,
        total_requests=row.total_requests or 0,
        total_input_tokens=row.total_input_tokens or 0,
        total_output_tokens=row.total_output_tokens or 0,
        total_tokens=row.total_tokens or 0,
        total_cost=float(row.total_cost or 0.0),
        period_start=start_date,
        period_end=end_date
    )


@router.get("/usage/{bot_id}/breakdown", response_model=List[ModelUsageBreakdown])
async def get_bot_usage_breakdown(
    bot_id: str,
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    current_user: User = Depends(get_current_user_from_jwt_only),
    db: AsyncSession = Depends(get_db)
):
    """
    특정 봇의 모델별 사용량 분해
    """
    if not end_date: 
        end_date = datetime.utcnow()
    if not start_date:
        start_date = end_date - timedelta(days=30)

    conditions = [
        LLMUsageLog.bot_id == bot_id,
        LLMUsageLog.user_id == current_user.id,
        LLMUsageLog.created_at >= start_date,
        LLMUsageLog.created_at <= end_date
    ]

    query = select(
        LLMUsageLog.provider,
        LLMUsageLog.model_name,
        func.count(LLMUsageLog.id).label('request_count'),
        func.sum(LLMUsageLog.input_tokens).label('total_input_tokens'),
        func.sum(LLMUsageLog.output_tokens).label('total_output_tokens'),
        func.sum(LLMUsageLog.total_cost).label('total_cost')
    ).where(
        and_(*conditions)
    ).group_by(
        LLMUsageLog.provider,
        LLMUsageLog.model_name
    ).order_by(
        func.sum(LLMUsageLog.total_cost).desc()
    )

    result = await db.execute(query)
    rows = result.all()

    return [
        ModelUsageBreakdown(
            provider=row.provider,
            model_name=row.model_name,
            request_count=row.request_count,
            total_input_tokens=row.total_input_tokens or 0,
            total_output_tokens=row.total_output_tokens or 0,
            total_cost=float(row.total_cost or 0.0)
        )
        for row in rows
    ]


@router.get("/usage/{bot_id}/daily", response_model=List[DailyCostSummary])
async def get_bot_daily_costs(
    bot_id: str,
    days: int = Query(30, ge=1, le=365, description="조회 일수 (최대 365일)"),
    current_user: User = Depends(get_current_user_from_jwt_only),
    db: AsyncSession = Depends(get_db)
):
    """
    특정 봇의 일별 비용 요약
    """
    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=days)

    conditions = [
        LLMUsageLog.bot_id == bot_id,
        LLMUsageLog.user_id == current_user.id,
        LLMUsageLog.created_at >= start_date
    ]

    # 일별 집계 (DATE 함수 사용)
    query = select(
        func.date(LLMUsageLog.created_at).label('date'),
        func.count(LLMUsageLog.id).label('request_count'),
        func.sum(LLMUsageLog.total_tokens).label('total_tokens'),
        func.sum(LLMUsageLog.total_cost).label('total_cost')
    ).where(
        and_(*conditions)
    ).group_by(
        func.date(LLMUsageLog.created_at)
    ).order_by(
        func.date(LLMUsageLog.created_at).asc()
    )

    result = await db.execute(query)
    rows = result.all()

    return [
        DailyCostSummary(
            date=str(row.date),
            request_count=row.request_count,
            total_tokens=row.total_tokens or 0,
            total_cost=float(row.total_cost or 0.0)
        )
        for row in rows
    ]


@router.get("/pricing", response_model=List[PricingInfo])
async def get_model_pricing(
    provider: Optional[str] = Query(None, description="Provider 필터"),
    db: AsyncSession = Depends(get_db)
):
    """
    모든 모델의 가격 정보 조회
    """
    query = select(ModelPricing).where(ModelPricing.is_active == 1)

    if provider:
        query = query.where(ModelPricing.provider == provider)

    result = await db.execute(query)
    pricing_list = result.scalars().all()

    return [
        PricingInfo(
            provider=p.provider,
            model_name=p.model_name,
            input_price_per_1k=p.input_price_per_1k,
            output_price_per_1k=p.output_price_per_1k,
            cache_write_price_per_1k=p.cache_write_price_per_1k,
            cache_read_price_per_1k=p.cache_read_price_per_1k,
            region=p.region
        )
        for p in pricing_list
    ]
