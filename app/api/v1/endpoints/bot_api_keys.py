"""
Bot API 키 관리 엔드포인트

API 키 CRUD 및 사용량 조회 (JWT 인증)
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field
from typing import Optional, Dict, List, Any
from datetime import datetime

from app.core.database import get_db
from app.core.auth.dependencies import get_current_user_from_jwt
from app.models.user import User
from app.services.bot_api_key_service import BotAPIKeyService

router = APIRouter(prefix="/api/v1/bots", tags=["Bot API Keys"])


# ==========================================
# Pydantic 스키마
# ==========================================

class CreateAPIKeyRequest(BaseModel):
    """API 키 생성 요청"""
    name: str = Field(..., min_length=1, max_length=100, description="API 키 이름")
    description: Optional[str] = Field(None, description="설명")
    workflow_version_id: Optional[str] = Field(None, description="특정 버전 고정 (None = 최신 버전)")
    bind_to_latest_published: bool = Field(True, description="최신 published 버전 자동 바인딩")
    permissions: Dict[str, bool] = Field(
        default_factory=lambda: {"run": True, "read": True, "stop": True},
        description="권한"
    )
    rate_limits: Dict[str, int] = Field(
        default_factory=lambda: {
            "per_minute": 60,
            "per_hour": 1000,
            "per_day": 10000
        },
        description="Rate Limit"
    )
    monthly_request_quota: Optional[int] = Field(None, description="월간 요청 할당량")
    expires_at: Optional[datetime] = Field(None, description="만료 시간")
    allowed_ips: Optional[List[str]] = Field(None, description="허용 IP 대역")

    class Config:
        json_schema_extra = {
            "example": {
                "name": "Production API Key",
                "description": "프로덕션 환경용",
                "bind_to_latest_published": True,
                "permissions": {
                    "run": True,
                    "read": True,
                    "stop": True
                },
                "rate_limits": {
                    "per_minute": 60,
                    "per_hour": 1000,
                    "per_day": 10000
                },
                "monthly_request_quota": 100000
            }
        }


class UpdateAPIKeyRequest(BaseModel):
    """API 키 수정 요청"""
    name: Optional[str] = None
    description: Optional[str] = None
    bind_to_latest_published: Optional[bool] = None
    workflow_version_id: Optional[str] = None
    permissions: Optional[Dict[str, bool]] = None
    rate_limits: Optional[Dict[str, int]] = None
    is_active: Optional[bool] = None


# ==========================================
# API 키 관리 엔드포인트
# ==========================================

@router.get("/{bot_id}/api-keys")
async def list_api_keys(
    bot_id: str,
    user: User = Depends(get_current_user_from_jwt),
    db: AsyncSession = Depends(get_db)
):
    """
    봇의 API 키 목록 조회
    
    - 로그인 사용자만 접근 가능
    - 소유자 확인
    """
    # 소유자 확인
    await BotAPIKeyService.verify_bot_ownership(bot_id, user.id, db)
    
    # API 키 목록 조회
    keys = await BotAPIKeyService.list_api_keys(bot_id, db)
    
    return {
        "object": "list",
        "data": keys,
        "has_more": False
    }


@router.post("/{bot_id}/api-keys", status_code=status.HTTP_201_CREATED)
async def create_api_key(
    bot_id: str,
    request: CreateAPIKeyRequest,
    user: User = Depends(get_current_user_from_jwt),
    db: AsyncSession = Depends(get_db)
):
    """
    새 API 키 생성
    
    - 워크플로우별 API 키 발급
    - 생성 시에만 전체 키 반환 (이후 조회 불가)
    """
    # 소유자 확인
    await BotAPIKeyService.verify_bot_ownership(bot_id, user.id, db)
    
    # 워크플로우 published 여부 확인
    if request.workflow_version_id:
        await BotAPIKeyService.verify_workflow_published(request.workflow_version_id, db)
    
    # API 키 생성
    api_key = await BotAPIKeyService.create_api_key(
        bot_id=bot_id,
        user_id=user.id,
        name=request.name,
        description=request.description,
        workflow_version_id=request.workflow_version_id,
        bind_to_latest_published=request.bind_to_latest_published,
        permissions=request.permissions,
        rate_limits=request.rate_limits,
        monthly_request_quota=request.monthly_request_quota,
        expires_at=request.expires_at,
        allowed_ips=request.allowed_ips,
        db=db
    )
    
    return api_key


@router.patch("/{bot_id}/api-keys/{key_id}")
async def update_api_key(
    bot_id: str,
    key_id: str,
    request: UpdateAPIKeyRequest,
    user: User = Depends(get_current_user_from_jwt),
    db: AsyncSession = Depends(get_db)
):
    """
    API 키 수정
    
    - 이름, 권한, Rate Limit, 버전 바인딩 변경 가능
    - 키 자체는 변경 불가 (삭제 후 재생성)
    """
    # 소유자 확인
    await BotAPIKeyService.verify_bot_ownership(bot_id, user.id, db)
    
    # API 키 수정
    updated_key = await BotAPIKeyService.update_api_key(
        key_id=key_id,
        name=request.name,
        description=request.description,
        bind_to_latest_published=request.bind_to_latest_published,
        workflow_version_id=request.workflow_version_id,
        permissions=request.permissions,
        rate_limits=request.rate_limits,
        is_active=request.is_active,
        db=db
    )
    
    return updated_key


@router.delete("/{bot_id}/api-keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_api_key(
    bot_id: str,
    key_id: str,
    user: User = Depends(get_current_user_from_jwt),
    db: AsyncSession = Depends(get_db)
):
    """
    API 키 삭제
    
    - 즉시 비활성화
    - CASCADE로 연결된 실행 기록은 유지 (api_key_id = NULL)
    """
    # 소유자 확인
    await BotAPIKeyService.verify_bot_ownership(bot_id, user.id, db)
    
    # API 키 삭제
    await BotAPIKeyService.delete_api_key(key_id, db)
    
    return None


@router.get("/{bot_id}/api-keys/{key_id}/usage")
async def get_api_key_usage(
    bot_id: str,
    key_id: str,
    period: str = "day",  # hour | day | week | month
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    user: User = Depends(get_current_user_from_jwt),
    db: AsyncSession = Depends(get_db)
):
    """
    API 키 사용량 통계
    
    - 시간별/일별/주별/월별 집계
    - 요청 수, 토큰 사용량, 레이턴시
    """
    # 소유자 확인
    await BotAPIKeyService.verify_bot_ownership(bot_id, user.id, db)
    
    # 사용량 조회 (TODO: 집계 로직 구현)
    from app.models.bot_api_key import APIKeyUsage
    from sqlalchemy import select, func
    
    query = select(APIKeyUsage).where(APIKeyUsage.api_key_id == key_id)
    
    if start_date:
        query = query.where(APIKeyUsage.timestamp_hour >= start_date)
    if end_date:
        query = query.where(APIKeyUsage.timestamp_hour <= end_date)
    
    result = await db.execute(query.order_by(APIKeyUsage.timestamp_hour.desc()).limit(100))
    usage_records = result.scalars().all()
    
    # 요약 통계
    summary_query = select(
        func.sum(APIKeyUsage.total_requests).label("total_requests"),
        func.sum(APIKeyUsage.total_tokens).label("total_tokens"),
        func.avg(APIKeyUsage.avg_latency_ms).label("avg_latency")
    ).where(APIKeyUsage.api_key_id == key_id)
    
    if start_date:
        summary_query = summary_query.where(APIKeyUsage.timestamp_hour >= start_date)
    if end_date:
        summary_query = summary_query.where(APIKeyUsage.timestamp_hour <= end_date)
    
    summary_result = await db.execute(summary_query)
    summary = summary_result.one()
    
    return {
        "api_key_id": key_id,
        "period": {
            "start": start_date.isoformat() if start_date else None,
            "end": end_date.isoformat() if end_date else None
        },
        "summary": {
            "total_requests": summary.total_requests or 0,
            "total_tokens": summary.total_tokens or 0,
            "avg_latency_ms": summary.avg_latency or 0
        },
        "time_series": [
            {
                "timestamp": record.timestamp_hour.isoformat(),
                "requests": record.total_requests,
                "tokens": record.total_tokens,
                "latency_ms": record.avg_latency_ms
            }
            for record in usage_records
        ]
    }

