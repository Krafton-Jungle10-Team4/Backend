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
from app.models.bot import Bot
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
    
    사용 기록이 없어도 0 값으로 정상 응답합니다.
    봇이 존재하지 않거나 권한이 없는 경우에만 404를 반환합니다.
    """
    # 봇 존재 여부 및 소유권 확인
    bot_query = select(Bot).where(
        Bot.bot_id == bot_id,
        Bot.user_id == current_user.id
    )
    bot_result = await db.execute(bot_query)
    bot = bot_result.scalar_one_or_none()
    
    if not bot:
        logger.warning(
            f"봇을 찾을 수 없음: bot_id={bot_id}, user_id={current_user.id}"
        )
        raise HTTPException(
            status_code=404,
            detail=f"봇 {bot_id}을(를) 찾을 수 없거나 접근 권한이 없습니다."
        )
    
    logger.info(
        f"봇 사용량 조회: bot_id={bot_id}, user_id={current_user.id}"
    )

    # 날짜 범위 설정 (기본값: 최근 30일)
    if not end_date:
        end_date = datetime.utcnow()
    if not start_date:
        start_date = end_date - timedelta(days=30)

    # 쿼리 조건
    conditions = [
        LLMUsageLog.bot_id == bot_id,
        LLMUsageLog.created_at >= start_date,
        LLMUsageLog.created_at <= end_date,
        LLMUsageLog.user_id == current_user.id
    ]

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

    # 사용 기록이 없어도 0 값으로 정상 응답
    total_requests = row.total_requests or 0 if row else 0
    total_cost = float(row.total_cost or 0.0) if row else 0.0
    
    logger.info(
        f"봇 사용량 조회 결과: bot_id={bot_id}, "
        f"total_requests={total_requests}, total_cost={total_cost}, "
        f"period={start_date} ~ {end_date}"
    )
    
    return UsageStatsResponse(
        bot_id=bot_id,
        total_requests=total_requests,
        total_input_tokens=row.total_input_tokens or 0 if row else 0,
        total_output_tokens=row.total_output_tokens or 0 if row else 0,
        total_tokens=row.total_tokens or 0 if row else 0,
        total_cost=total_cost,
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


@router.post("/pricing/seed", response_model=dict)
async def seed_model_pricing(
    current_user: User = Depends(get_current_user_from_jwt_only),
    db: AsyncSession = Depends(get_db)
):
    """
    모델 가격 정보 초기화 (실제 사용 중인 모델 추가)
    """
    from app.services.cost_tracking_service import CostTrackingService
    cost_service = CostTrackingService(db)
    
    models_to_add = [
        {
            "provider": "anthropic",
            "model_name": "claude-sonnet-4-5-20250929",
            "input_price_per_1k": 0.003,
            "output_price_per_1k": 0.015,
            "cache_write_price_per_1k": 0.00375,
            "cache_read_price_per_1k": 0.0003,
        },
        {
            "provider": "openai",
            "model_name": "gpt-5-chat-latest",
            "input_price_per_1k": 0.03,
            "output_price_per_1k": 0.06,
        },
    ]
    
    added = []
    skipped = []
    
    for model_data in models_to_add:
        existing = await cost_service.get_model_pricing(
            model_data["provider"],
            model_data["model_name"]
        )
        if existing:
            skipped.append(f"{model_data['provider']}/{model_data['model_name']}")
            continue
        
        await cost_service.add_model_pricing(**model_data)
        added.append(f"{model_data['provider']}/{model_data['model_name']}")
    
    return {
        "message": "모델 가격 정보 추가 완료",
        "added": added,
        "skipped": skipped
    }


class UserUsageStatsResponse(BaseModel):
    """유저 전체 사용량 통계 응답"""
    user_id: int
    total_requests: int
    total_input_tokens: int
    total_output_tokens: int
    total_tokens: int
    total_cost: float
    period_start: Optional[datetime] = None
    period_end: Optional[datetime] = None


class BotUsageBreakdown(BaseModel):
    """봇별 사용량 분해"""
    bot_id: str
    bot_name: Optional[str] = None
    request_count: int
    total_input_tokens: int
    total_output_tokens: int
    total_tokens: int
    total_cost: float


@router.get("/user/stats", response_model=UserUsageStatsResponse)
async def get_user_usage_stats(
    start_date: Optional[datetime] = Query(None, description="시작 날짜 (YYYY-MM-DD)"),
    end_date: Optional[datetime] = Query(None, description="종료 날짜 (YYYY-MM-DD)"),
    current_user: User = Depends(get_current_user_from_jwt_only),
    db: AsyncSession = Depends(get_db)
):
    """
    현재 유저의 전체 LLM 사용량 및 비용 통계 조회
    
    사용 기록이 없어도 0 값으로 정상 응답합니다.
    """
    logger.info(
        f"[DEBUG] get_user_usage_stats 호출됨: user_id={current_user.id}, "
        f"start_date={start_date}, end_date={end_date}"
    )

    # 날짜 범위 설정 (기본값: 최근 30일)
    if not end_date:
        end_date = datetime.utcnow()
    if not start_date:
        start_date = end_date - timedelta(days=30)

    # 쿼리 조건
    conditions = [
        LLMUsageLog.user_id == current_user.id,
        LLMUsageLog.created_at >= start_date,
        LLMUsageLog.created_at <= end_date
    ]

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

    # 사용 기록이 없어도 0 값으로 정상 응답
    total_requests = row.total_requests or 0 if row else 0
    total_cost = float(row.total_cost or 0.0) if row else 0.0
    
    logger.info(
        f"유저 사용량 조회 결과: user_id={current_user.id}, "
        f"total_requests={total_requests}, total_cost={total_cost}, "
        f"period={start_date} ~ {end_date}"
    )
    
    return UserUsageStatsResponse(
        user_id=current_user.id,
        total_requests=total_requests,
        total_input_tokens=row.total_input_tokens or 0 if row else 0,
        total_output_tokens=row.total_output_tokens or 0 if row else 0,
        total_tokens=row.total_tokens or 0 if row else 0,
        total_cost=total_cost,
        period_start=start_date,
        period_end=end_date
    )


@router.get("/user/breakdown", response_model=List[BotUsageBreakdown])
async def get_user_bot_breakdown(
    start_date: Optional[datetime] = Query(None, description="시작 날짜 (YYYY-MM-DD)"),
    end_date: Optional[datetime] = Query(None, description="종료 날짜 (YYYY-MM-DD)"),
    current_user: User = Depends(get_current_user_from_jwt_only),
    db: AsyncSession = Depends(get_db)
):
    """
    현재 유저의 봇별 사용량 분해
    
    각 봇이 얼마나 LLM을 사용했는지 비용과 함께 조회합니다.
    """
    logger.info(
        f"[DEBUG] get_user_bot_breakdown 호출됨: user_id={current_user.id}, "
        f"start_date={start_date}, end_date={end_date}"
    )
    
    if not end_date: 
        end_date = datetime.utcnow()
    if not start_date:
        start_date = end_date - timedelta(days=30)

    conditions = [
        LLMUsageLog.user_id == current_user.id,
        LLMUsageLog.created_at >= start_date,
        LLMUsageLog.created_at <= end_date
    ]

    # 봇별 집계 (봇 이름도 함께 조회)
    query = select(
        LLMUsageLog.bot_id,
        Bot.name.label('bot_name'),
        func.count(LLMUsageLog.id).label('request_count'),
        func.sum(LLMUsageLog.input_tokens).label('total_input_tokens'),
        func.sum(LLMUsageLog.output_tokens).label('total_output_tokens'),
        func.sum(LLMUsageLog.total_tokens).label('total_tokens'),
        func.sum(LLMUsageLog.total_cost).label('total_cost')
    ).join(
        Bot, LLMUsageLog.bot_id == Bot.bot_id, isouter=True
    ).where(
        and_(*conditions)
    ).group_by(
        LLMUsageLog.bot_id,
        Bot.name
    ).order_by(
        func.sum(LLMUsageLog.total_cost).desc()
    )

    result = await db.execute(query)
    rows = result.all()

    return [
        BotUsageBreakdown(
            bot_id=row.bot_id,
            bot_name=row.bot_name,
            request_count=row.request_count,
            total_input_tokens=row.total_input_tokens or 0,
            total_output_tokens=row.total_output_tokens or 0,
            total_tokens=row.total_tokens or 0,
            total_cost=float(row.total_cost or 0.0)
        )
        for row in rows
    ]


@router.get("/user/model-breakdown", response_model=List[ModelUsageBreakdown])
async def get_user_model_breakdown(
    start_date: Optional[datetime] = Query(None, description="시작 날짜 (YYYY-MM-DD)"),
    end_date: Optional[datetime] = Query(None, description="종료 날짜 (YYYY-MM-DD)"),
    current_user: User = Depends(get_current_user_from_jwt_only),
    db: AsyncSession = Depends(get_db)
):
    """
    현재 유저의 모델별 사용량 분해
    
    어떤 모델을 얼마나 사용했는지 비용과 함께 조회합니다.
    """
    logger.info(
        f"[DEBUG] get_user_model_breakdown 호출됨: user_id={current_user.id}, "
        f"start_date={start_date}, end_date={end_date}"
    )
    
    if not end_date: 
        end_date = datetime.utcnow()
    if not start_date:
        start_date = end_date - timedelta(days=30)

    conditions = [
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

    logger.info(
        f"[DEBUG] get_user_model_breakdown 결과: user_id={current_user.id}, "
        f"row_count={len(rows)}"
    )

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


@router.get("/user/daily", response_model=List[DailyCostSummary])
async def get_user_daily_costs(
    days: int = Query(30, ge=1, le=365, description="조회 일수 (최대 365일)"),
    current_user: User = Depends(get_current_user_from_jwt_only),
    db: AsyncSession = Depends(get_db)
):
    """
    현재 유저의 일별 비용 요약
    
    날짜별로 LLM 사용 비용을 조회합니다.
    """
    logger.info(
        f"[DEBUG] get_user_daily_costs 호출됨: user_id={current_user.id}, days={days}"
    )
    
    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=days)

    conditions = [
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
