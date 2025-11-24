"""
LLM 전용 Rate Limiter
--------------------
Bedrock 및 MCP 커넥터 호출을 토큰 버킷으로 제어해 Rate Limit과 비용 한도를 보호한다.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Dict, Optional

from app.config import settings

logger = logging.getLogger(__name__)


class AsyncTokenBucket:
    """비동기 토큰 버킷 구현 (초당 rate, 최대 capacity)."""

    def __init__(self, rate: float, capacity: Optional[float] = None):
        if rate <= 0:
            raise ValueError("rate must be positive")
        self.rate = rate
        self.capacity = capacity or rate
        self.tokens = self.capacity
        self.updated_at = time.monotonic()
        self._lock = asyncio.Lock()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self.updated_at
        if elapsed <= 0:
            return
        self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
        self.updated_at = now

    async def acquire(self, tokens: float = 1.0) -> None:
        """필요 토큰을 확보할 때까지 대기."""
        if tokens <= 0:
            return

        while True:
            async with self._lock:
                self._refill()
                if self.tokens >= tokens:
                    self.tokens -= tokens
                    return

                deficit = tokens - self.tokens
                wait_time = deficit / self.rate if self.rate else 0.1

            await asyncio.sleep(min(max(wait_time, 0.01), 1.0))


class LLMRateLimiter:
    """LLM Provider 전역 Rate Limiter."""

    _buckets: Dict[str, AsyncTokenBucket] = {}
    _bootstrap_done: bool = False

    @classmethod
    def bootstrap_from_settings(cls) -> None:
        """환경 설정을 기반으로 기본 버킷 초기화."""
        if cls._bootstrap_done:
            return

        if settings.bedrock_qps_limit > 0:
            cls._buckets["bedrock"] = AsyncTokenBucket(
                rate=settings.bedrock_qps_limit,
                capacity=settings.bedrock_rate_limit_burst or settings.bedrock_qps_limit,
            )
            logger.info(
                "Bedrock RateLimiter 초기화 (qps=%.2f, burst=%.2f)",
                settings.bedrock_qps_limit,
                settings.bedrock_rate_limit_burst or settings.bedrock_qps_limit,
            )

        cls._register_mcp_bucket("default", settings.mcp_rate_limit_per_minute)

        # 커넥터별 오버라이드
        for connector, rpm in (settings.mcp_connector_rate_limits or {}).items():
            cls._register_mcp_bucket(connector, rpm)

        cls._bootstrap_done = True

    @classmethod
    def _register_mcp_bucket(cls, connector: str, rpm: Optional[int]) -> None:
        if not rpm or rpm <= 0:
            return

        key = f"mcp:{connector}"
        per_second = rpm / 60.0
        burst = (settings.mcp_rate_limit_burst or rpm) / 60.0
        cls._buckets[key] = AsyncTokenBucket(rate=per_second, capacity=burst)
        logger.info(
            "MCP RateLimiter 등록 (%s, rpm=%s, burst=%.2f req/sec)",
            key,
            rpm,
            burst,
        )

    @classmethod
    def register_connector(cls, connector: str, rpm: Optional[int] = None) -> None:
        """런타임에 새로운 MCP 커넥터 버킷 등록."""
        rpm = rpm or settings.mcp_rate_limit_per_minute
        cls._register_mcp_bucket(connector, rpm)

    @classmethod
    async def acquire(cls, bucket_name: str, tokens: float = 1.0) -> None:
        """지정된 버킷에서 토큰을 확보 (미정의 버킷이면 no-op)."""
        if not cls._bootstrap_done:
            cls.bootstrap_from_settings()

        bucket = cls._buckets.get(bucket_name)
        if not bucket:
            return
        await bucket.acquire(tokens=tokens)


# 모듈 import 시 기본 버킷 세팅
LLMRateLimiter.bootstrap_from_settings()

