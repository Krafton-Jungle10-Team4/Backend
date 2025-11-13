"""
Redis 클라이언트 모듈

Widget 세션, 캐싱, Rate Limiting을 위한 Redis 연결 관리
"""
from redis import asyncio as aioredis
from typing import Optional, Any, List
import json
import logging
from app.config import settings

logger = logging.getLogger(__name__)


class RedisClient:
    """비동기 Redis 클라이언트"""

    def __init__(self):
        # Redis 연결 객체 초기화
        self.redis: Optional[aioredis.Redis] = None
        # 연결 문자열 생성 규칙을 한 곳에 모아 일관성 있게 관리하려는 목적
        # 비밀번호 포함/미포함, 기본값 처리 등을 캡슐화
        self._url = settings.get_redis_url()

    async def connect(self):
        """Redis 연결 초기화 (환경별 TLS/SSL 설정)"""
        try:
            # 기본 클라이언트 옵션
            client_kwargs = {
                "encoding": "utf-8",
                "decode_responses": True,
                "socket_connect_timeout": 5,
                "socket_keepalive": True,
            }

            # 프로덕션 환경: SSL/TLS 설정 추가
            if settings.is_production or settings.redis_use_ssl:
                import ssl
                # redis-py는 ssl_cert_reqs를 직접 받음 (dict가 아닌 ssl 객체)
                client_kwargs["ssl_cert_reqs"] = ssl.CERT_NONE
                logger.info("Redis: Production mode with TLS enabled")
            else:
                logger.info("Redis: Development mode without TLS")

            # Redis 클라이언트 생성
            self.redis = await aioredis.from_url(
                self._url,
                **client_kwargs
            )

            # 연결 테스트
            await self.redis.ping()
            logger.info(f"Redis 연결 성공: {self._url.split('@')[-1].split('?')[0]}")  # 비밀번호 및 쿼리 파라미터 숨김
        except Exception as e:
            logger.error(f"Redis 연결 실패: {e}")
            raise

    async def close(self):
        """Redis 연결 종료"""
        if self.redis:
            await self.redis.aclose()
            logger.info("Redis 연결 종료")

    # 값 조회 후 JSON이면 자동 파싱, 아니면 원문 반환
    async def get(self, key: str) -> Optional[Any]:
        """키로 값 조회 (JSON 자동 디코딩)"""
        try:
            value = await self.redis.get(key)
            if value is None:
                return None
            # JSON 문자열이면 파싱
            try:
                return json.loads(value)
            except (json.JSONDecodeError, TypeError):
                return value
        except Exception as e:
            logger.error(f"Redis GET 실패 [{key}]: {e}")
            return None

    async def set(
        self,
        key: str,
        value: Any,
        expire: Optional[int] = None,
        nx: bool = False,
        xx: bool = False
    ) -> bool:
        """
        키에 값 저장 (JSON 자동 인코딩)

        Args:
            key: 저장할 키
            value: 저장할 값 (dict는 JSON으로 변환)
            expire: 만료 시간 (초)
            nx: True면 키가 없을 때만 설정 (SET NX)
            xx: True면 키가 있을 때만 설정 (SET XX)
        """
        try:
            # dict는 JSON으로 변환
            if isinstance(value, (dict, list)):
                value = json.dumps(value, ensure_ascii=False)

            result = await self.redis.set(
                key,
                value,
                ex=expire,
                nx=nx,
                xx=xx
            )
            return result
        except Exception as e:
            logger.error(f"Redis SET 실패 [{key}]: {e}")
            return False

    async def delete(self, *keys: str) -> int:
        """키 삭제 (여러 키 동시 삭제 가능)"""
        try:
            return await self.redis.delete(*keys)
        except Exception as e:
            logger.error(f"Redis DELETE 실패 [{keys}]: {e}")
            return 0

    async def exists(self, *keys: str) -> int:
        """키 존재 여부 확인 (존재하는 키 개수 반환)"""
        try:
            return await self.redis.exists(*keys)
        except Exception as e:
            logger.error(f"Redis EXISTS 실패 [{keys}]: {e}")
            return 0

    async def expire(self, key: str, seconds: int) -> bool:
        """키에 만료 시간 설정"""
        try:
            return await self.redis.expire(key, seconds)
        except Exception as e:
            logger.error(f"Redis EXPIRE 실패 [{key}]: {e}")
            return False

    async def ttl(self, key: str) -> int:
        """키의 남은 TTL 조회 (초)"""
        try:
            return await self.redis.ttl(key)
        except Exception as e:
            logger.error(f"Redis TTL 실패 [{key}]: {e}")
            return -2

    async def incr(self, key: str) -> int:
        """키 값 1 증가 (카운터)"""
        try:
            return await self.redis.incr(key)
        except Exception as e:
            logger.error(f"Redis INCR 실패 [{key}]: {e}")
            return 0

    async def decr(self, key: str) -> int:
        """키 값 1 감소"""
        try:
            return await self.redis.decr(key)
        except Exception as e:
            logger.error(f"Redis DECR 실패 [{key}]: {e}")
            return 0

    async def keys(self, pattern: str, batch_size: int = 500) -> List[str]:
        """패턴으로 키 검색 (SCAN 기반, 대량 키에서도 안전)"""
        cursor = 0 # 시작점은 0
        collected: List[str] = [] # 결과 수집
        try:
            # 커서가 끝(0)으로 돌아올 때까지 계속 반복
            while True:
                # Redis의 SCAN 명령을 비동기로 호출
                # 다음 커서 값과 이번에 찾은 키 묶음(batch)을 반환
                cursor, batch = await self.redis.scan(
                    # 이전 반복에서 받은 커서를 다음 호출에 넘기며 순회
                    cursor=cursor,
                    # 이 패턴(pattern)에 매칭되는 키만 찾도록 제한
                    match=pattern,
                    # 한 번에 최대 몇 개의 키를 찾을지 제한
                    count=batch_size
                )
                # 이번에 찾은 키들(batch)을 결과 리스트(collected)에 추가
                collected.extend(batch)
                # 커서가 끝(0)으로 돌아오면 모든 키를 찾은 것이므로 종료
                if cursor == 0:
                    break
            return collected
        except Exception as e:
            logger.error(f"Redis SCAN 실패 [{pattern}]: {e}")
            return []

    async def flushdb(self):
        """현재 DB의 모든 키 삭제 (개발/테스트 전용)"""
        if not settings.is_production:
            await self.redis.flushdb()
            logger.warning("Redis DB 전체 삭제 (flushdb)")
        else:
            logger.error("프로덕션 환경에서는 flushdb 사용 불가")


# 싱글톤 인스턴스
redis_client = RedisClient()
