"""
API Rate Limiting

API 키별 요청 제한 (분/시간/일 단위)
"""
from fastapi import Request, HTTPException, status
from fastapi.responses import JSONResponse
from datetime import datetime, timedelta
from typing import Tuple, Dict, Optional
import logging

from app.core.redis_client import redis_client
from app.core.auth.api_key import hash_api_key

logger = logging.getLogger(__name__)


class APIKeyRateLimiter:
    """API 키별 Rate Limiting (Redis 기반)"""
    
    @staticmethod
    async def check_rate_limit(
        api_key_id: str,
        rate_limit_per_minute: int,
        rate_limit_per_hour: int,
        rate_limit_per_day: int
    ) -> Tuple[bool, Dict[str, str]]:
        """
        Rate limit 체크 및 헤더 정보 반환
        
        Args:
            api_key_id: API 키 UUID
            rate_limit_per_minute: 분당 제한
            rate_limit_per_hour: 시간당 제한
            rate_limit_per_day: 일당 제한
        
        Returns:
            (allowed: bool, headers: dict)
        """
        now = datetime.now()
        
        # ==========================================
        # 1. 분 단위 체크
        # ==========================================
        minute_key = f"rate_limit:{api_key_id}:minute:{now.strftime('%Y%m%d%H%M')}"
        minute_count = await redis_client.incr(minute_key)
        
        if minute_count == 1:
            # 첫 요청일 때 TTL 설정 (60초)
            await redis_client.expire(minute_key, 60)
        
        if minute_count > rate_limit_per_minute:
            # 분당 제한 초과
            reset_at = (now + timedelta(minutes=1)).replace(second=0, microsecond=0)
            return False, {
                "X-RateLimit-Limit": str(rate_limit_per_minute),
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": str(int(reset_at.timestamp())),
                "X-RateLimit-Period": "minute"
            }
        
        # ==========================================
        # 2. 시간 단위 체크
        # ==========================================
        hour_key = f"rate_limit:{api_key_id}:hour:{now.strftime('%Y%m%d%H')}"
        hour_count = await redis_client.incr(hour_key)
        
        if hour_count == 1:
            # 첫 요청일 때 TTL 설정 (3600초)
            await redis_client.expire(hour_key, 3600)
        
        if hour_count > rate_limit_per_hour:
            # 시간당 제한 초과
            reset_at = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
            return False, {
                "X-RateLimit-Limit": str(rate_limit_per_hour),
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": str(int(reset_at.timestamp())),
                "X-RateLimit-Period": "hour"
            }
        
        # ==========================================
        # 3. 일 단위 체크
        # ==========================================
        day_key = f"rate_limit:{api_key_id}:day:{now.strftime('%Y%m%d')}"
        day_count = await redis_client.incr(day_key)
        
        if day_count == 1:
            # 첫 요청일 때 TTL 설정 (86400초)
            await redis_client.expire(day_key, 86400)
        
        if day_count > rate_limit_per_day:
            # 일당 제한 초과
            reset_at = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            return False, {
                "X-RateLimit-Limit": str(rate_limit_per_day),
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": str(int(reset_at.timestamp())),
                "X-RateLimit-Period": "day"
            }
        
        # ==========================================
        # 4. 성공 헤더 생성 (가장 제한적인 분 단위 기준)
        # ==========================================
        headers = {
            "X-RateLimit-Limit": str(rate_limit_per_minute),
            "X-RateLimit-Remaining": str(max(0, rate_limit_per_minute - minute_count)),
            "X-RateLimit-Reset": str(int((now + timedelta(minutes=1)).replace(second=0, microsecond=0).timestamp())),
            "X-RateLimit-Period": "minute"
        }
        
        return True, headers


# Rate Limiting 미들웨어 (FastAPI 미들웨어로 등록)
async def rate_limit_middleware(request: Request, call_next):
    """
    공개 API 경로에 대한 Rate Limiting 미들웨어
    
    /api/v1/public/* 경로에만 적용
    """
    # 공개 API 경로 체크
    if not request.url.path.startswith("/api/v1/public/"):
        # 공개 API가 아니면 Rate Limiting 하지 않음
        return await call_next(request)
    
    # X-API-Key 헤더 확인
    api_key_header = request.headers.get("X-API-Key")
    
    if not api_key_header:
        # API 키가 없으면 다음 핸들러에서 401 처리
        return await call_next(request)
    
    try:
        # API 키 해시
        key_hash = hash_api_key(api_key_header)
        
        # Redis에서 API 키 정보 캐싱 조회 (5분 TTL)
        cache_key = f"api_key:cache:{key_hash}"
        cached_api_key = await redis_client.get(cache_key)
        
        if not cached_api_key:
            # 캐시 미스: DB 조회 (다음 핸들러에서 처리)
            return await call_next(request)
        
        # 캐시 히트: Rate Limiting 체크
        api_key_id = cached_api_key.get("id")
        rate_limit_per_minute = cached_api_key.get("rate_limit_per_minute", 60)
        rate_limit_per_hour = cached_api_key.get("rate_limit_per_hour", 1000)
        rate_limit_per_day = cached_api_key.get("rate_limit_per_day", 10000)
        
        # Rate Limiting 체크
        allowed, headers = await APIKeyRateLimiter.check_rate_limit(
            api_key_id=api_key_id,
            rate_limit_per_minute=rate_limit_per_minute,
            rate_limit_per_hour=rate_limit_per_hour,
            rate_limit_per_day=rate_limit_per_day
        )
        
        if not allowed:
            # Rate Limit 초과
            logger.warning(f"Rate limit exceeded for API key: {api_key_id}")
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={
                    "error": {
                        "code": "RATE_LIMIT_EXCEEDED",
                        "message": f"Rate limit exceeded: {headers['X-RateLimit-Period']}"
                    },
                    "request_id": request.state.__dict__.get("request_id", "unknown"),
                    "timestamp": datetime.now().isoformat()
                },
                headers=headers
            )
        
        # Rate Limit 통과: 요청 처리
        response = await call_next(request)
        
        # 응답 헤더에 Rate Limit 정보 추가
        for key, value in headers.items():
            response.headers[key] = value
        
        return response
    
    except Exception as e:
        logger.error(f"Rate limiting 미들웨어 오류: {e}")
        # 에러 발생 시 Rate Limiting 없이 통과 (서비스 장애 방지)
        return await call_next(request)


async def cache_api_key_info(api_key_id: str, api_key_data: dict, ttl: int = 300):
    """
    API 키 정보를 Redis에 캐싱 (Rate Limiting 성능 향상)
    
    Args:
        api_key_id: API 키 UUID
        api_key_data: API 키 정보 (rate_limit_per_minute, rate_limit_per_hour, rate_limit_per_day 포함)
        ttl: 캐시 TTL (초, 기본 5분)
    """
    from app.core.auth.api_key import hash_api_key
    
    key_hash = api_key_data.get("key_hash")
    if not key_hash:
        return
    
    cache_key = f"api_key:cache:{key_hash}"
    cache_data = {
        "id": api_key_id,
        "bot_id": api_key_data.get("bot_id"),
        "rate_limit_per_minute": api_key_data.get("rate_limit_per_minute", 60),
        "rate_limit_per_hour": api_key_data.get("rate_limit_per_hour", 1000),
        "rate_limit_per_day": api_key_data.get("rate_limit_per_day", 10000)
    }
    
    await redis_client.set(cache_key, cache_data, expire=ttl)
    logger.debug(f"API 키 캐싱 완료: {api_key_id}")

