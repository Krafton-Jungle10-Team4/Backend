"""
Rate Limiting 미들웨어

slowapi를 사용한 API 호출 제한
"""
from fastapi import Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from app.config import settings
import logging

logger = logging.getLogger(__name__)


def get_redis_uri() -> str:
    """Rate Limiting용 Redis URI 반환"""
    return settings.get_redis_url()


# 일반 API용 Limiter (인증된 사용자)
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[f"{settings.rate_limit_per_minute} per minute"],
    storage_uri=get_redis_uri() if settings.rate_limit_enabled else None,
    enabled=settings.rate_limit_enabled,
)

# 공개 Widget API용 Limiter (미인증 사용자)
public_limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[f"{settings.rate_limit_public_per_hour} per hour"],
    storage_uri=get_redis_uri() if settings.rate_limit_enabled else None,
    enabled=settings.rate_limit_enabled,
)


# Rate Limit 초과 시 커스텀 응답
def custom_rate_limit_handler(request: Request, exc: RateLimitExceeded):
    """Rate Limit 초과 시 JSON 응답 반환"""
    logger.warning(
        f"Rate limit exceeded: {request.client.host} - {request.url.path}"
    )
    return JSONResponse(
        status_code=429,
        content={
            "error": "rate_limit_exceeded",
            "message": "너무 많은 요청을 보냈습니다. 잠시 후 다시 시도해주세요.",
            "detail": str(exc.detail)
        }
    )
