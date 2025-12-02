"""
임베딩 서비스 - AWS Bedrock Titan Embeddings
"""
import logging
import asyncio
import threading
import json
import time
from typing import List
from concurrent.futures import ThreadPoolExecutor
import boto3
from botocore.exceptions import ClientError
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
    after_log
)
from app.config import settings

logger = logging.getLogger(__name__)


class CircuitBreakerOpenError(Exception):
    """Circuit Breaker가 열린 상태에서 요청 시도 시 발생하는 예외"""
    pass


class EmbeddingService:
    """임베딩 생성 서비스 (AWS Bedrock Titan Embeddings 또는 Mock)"""

    def __init__(self):
        self.client = None
        self.model_id = settings.bedrock_model_id
        self.region_name = settings.aws_region
        self.dimensions = settings.bedrock_dimensions
        self.normalize = settings.bedrock_normalize
        self.batch_size = settings.batch_size

        # 임베딩 작업용 스레드 풀 (병렬 처리 최적화)
        # Rate limit 보호를 위해 workers 감소: 4 → 2
        self.executor = ThreadPoolExecutor(max_workers=2)
        self._lock = threading.Lock()  # 스레드 안전성을 위한 락

        # Rate Limiting: Bedrock API 동시 요청 제한
        self._semaphore = asyncio.Semaphore(settings.bedrock_max_concurrent_requests)
        self._last_request_time = 0.0  # 마지막 요청 시간 (rate limit 제어)

        # Circuit Breaker: 연속 실패 시 일시적으로 요청 차단
        self._circuit_failures = 0  # 연속 실패 횟수
        self._circuit_opened_at = 0.0  # Circuit 열린 시간
        self._circuit_is_open = False  # Circuit 상태

        # Mock 임베딩 모드 설정
        self.use_mock = False
        if settings.should_use_mock_embeddings:
            self.use_mock = True
            logger.info("Using Mock embeddings for local development")
        else:
            # Bedrock 초기화 시도
            try:
                self._init_client()
            except Exception as e:
                if settings.is_development:
                    # 개발 환경에서는 Mock으로 폴백
                    self.use_mock = True
                    logger.warning(f"Bedrock initialization failed, falling back to Mock: {e}")
                else:
                    # 프로덕션에서는 에러 발생
                    logger.error(f"Failed to initialize Bedrock client: {e}")
                    raise

    def _init_client(self):
        """Bedrock 클라이언트 초기화"""
        if self.client is None:
            logger.info(f"Bedrock 클라이언트 초기화 중: {self.model_id} (Region: {self.region_name})")

            # AWS credentials 설정 (ECS Task Role 사용 시 자동으로 인식)
            if settings.aws_access_key_id and settings.aws_secret_access_key:
                # 로컬 개발 환경: 명시적 credentials 사용
                self.client = boto3.client(
                    service_name='bedrock-runtime',
                    region_name=self.region_name,
                    aws_access_key_id=settings.aws_access_key_id,
                    aws_secret_access_key=settings.aws_secret_access_key
                )
            else:
                # 프로덕션 환경: ECS Task Role 자동 인식
                self.client = boto3.client(
                    service_name='bedrock-runtime',
                    region_name=self.region_name
                )

            logger.info("Bedrock 클라이언트 초기화 완료")

    def _should_retry_error(self, exception: Exception) -> bool:
        """재시도 가능한 에러인지 판단

        Args:
            exception: 발생한 예외

        Returns:
            재시도 가능 여부
        """
        if not isinstance(exception, ClientError):
            return False

        error_code = exception.response.get('Error', {}).get('Code', '')
        # Throttling 및 일시적 실패는 재시도 가능
        return error_code in [
            'ThrottlingException',
            'ServiceUnavailableException',
            'TooManyRequestsException',
            'RequestLimitExceeded'
        ]

    def _check_circuit_breaker(self):
        """Circuit Breaker 상태 확인

        Raises:
            CircuitBreakerOpenError: Circuit이 열린 상태인 경우
        """
        if not self._circuit_is_open:
            return

        # Circuit 복구 시간 확인
        elapsed = time.time() - self._circuit_opened_at
        if elapsed >= settings.bedrock_circuit_recovery_timeout:
            # Circuit 복구 (Half-Open 상태)
            logger.info(f"Circuit Breaker 복구 시도 (대기 시간: {elapsed:.1f}초)")
            self._circuit_is_open = False
            self._circuit_failures = 0
        else:
            # Circuit 여전히 열림
            remaining = settings.bedrock_circuit_recovery_timeout - elapsed
            raise CircuitBreakerOpenError(
                f"Circuit Breaker가 열려있습니다. {remaining:.1f}초 후 복구됩니다."
            )

    def _record_success(self):
        """성공 기록: Circuit Breaker 초기화"""
        self._circuit_failures = 0
        self._circuit_is_open = False

    def _record_failure(self):
        """실패 기록: Circuit Breaker 임계값 확인"""
        self._circuit_failures += 1

        if self._circuit_failures >= settings.bedrock_circuit_failure_threshold:
            # Circuit Open
            self._circuit_is_open = True
            self._circuit_opened_at = time.time()
            logger.error(
                f"Circuit Breaker 작동: 연속 {self._circuit_failures}회 실패 "
                f"({settings.bedrock_circuit_recovery_timeout}초 대기)"
            )

    def _enforce_rate_limit(self):
        """Rate limit 제어: 요청 간 최소 간격 보장"""
        current_time = time.time()
        elapsed = current_time - self._last_request_time

        if elapsed < settings.bedrock_request_interval:
            sleep_time = settings.bedrock_request_interval - elapsed
            time.sleep(sleep_time)

        self._last_request_time = time.time()

    @retry(
        stop=stop_after_attempt(settings.bedrock_max_retries),
        wait=wait_exponential(
            multiplier=settings.bedrock_retry_multiplier,
            min=settings.bedrock_retry_min_wait,
            max=settings.bedrock_retry_max_wait
        ),
        retry=retry_if_exception_type(ClientError),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        after=after_log(logger, logging.DEBUG),
        reraise=True
    )
    def _invoke_bedrock(self, text: str) -> List[float]:
        """Bedrock API 호출 (단일 텍스트 임베딩) - Exponential Backoff 적용

        Args:
            text: 임베딩할 텍스트

        Returns:
            임베딩 벡터 (List[float])

        Raises:
            ClientError: Bedrock API 호출 실패 (최종)
            CircuitBreakerOpenError: Circuit Breaker가 열린 상태
        """
        # Circuit Breaker 상태 확인
        self._check_circuit_breaker()

        if self.client is None:
            with self._lock:  # 클라이언트 초기화 시 동시성 제어
                if self.client is None:
                    self._init_client()

        # Rate Limiting: 요청 간 최소 간격 보장
        self._enforce_rate_limit()

        # 텍스트가 JSON 배열인 경우 처리
        # Bedrock API는 문자열만 받으므로 JSON 배열을 문자열로 변환
        if isinstance(text, (list, dict)):
            text = json.dumps(text, ensure_ascii=False)
        elif isinstance(text, str):
            # 문자열이 JSON 배열로 시작하는 경우 파싱 후 재직렬화
            text = text.strip()
            if text.startswith('[') or text.startswith('{'):
                try:
                    parsed = json.loads(text)
                    # 파싱 성공 시 문자열로 변환 (배열/객체인 경우)
                    if isinstance(parsed, (list, dict)):
                        text = json.dumps(parsed, ensure_ascii=False)
                except (json.JSONDecodeError, ValueError):
                    # JSON 파싱 실패 시 원본 텍스트 사용
                    pass

        # Bedrock API 요청 본문 구성
        request_body = {
            "inputText": text,
            "dimensions": self.dimensions,
            "normalize": self.normalize
        }

        try:
            # Bedrock API 호출
            response = self.client.invoke_model(
                modelId=self.model_id,
                body=json.dumps(request_body)
            )

            # 응답 파싱
            result = json.loads(response['body'].read())
            embedding = result['embedding']

            # 성공 기록
            self._record_success()

            return embedding

        except ClientError as e:
            error_code = e.response['Error']['Code']
            error_message = e.response['Error']['Message']

            # 에러 로깅
            logger.error(f"Bedrock API 호출 실패: {error_code} - {error_message}")

            # 실패 기록 (Circuit Breaker)
            if self._should_retry_error(e):
                self._record_failure()

            # 재시도 가능한 에러인 경우 tenacity가 자동 재시도
            if self._should_retry_error(e):
                logger.warning(f"재시도 가능한 에러: {error_code}")
                raise  # tenacity가 재시도 처리

            # 재시도 불가능한 에러 (권한, 잘못된 요청)
            logger.error(f"재시도 불가능한 에러: {error_code}")
            raise

    def _get_mock_embedding_sync(self, text: str) -> List[float]:
        """로컬 개발용 Mock 임베딩 (동기 메서드)

        텍스트 해시를 기반으로 일관된 임베딩 생성
        """
        import hashlib
        import math

        # 텍스트를 해시하여 일관된 시드 생성
        hash_obj = hashlib.sha256(text.encode())
        hash_hex = hash_obj.hexdigest()

        # 해시를 기반으로 고정된 차원의 임베딩 생성
        embedding = []
        for i in range(0, self.dimensions * 2, 2):
            # 해시의 각 2문자를 0-1 사이 값으로 변환
            hex_pair = hash_hex[i % len(hash_hex):i % len(hash_hex) + 2]
            value = int(hex_pair, 16) / 255.0
            embedding.append(value)
            if len(embedding) >= self.dimensions:
                break

        # 차원이 부족한 경우 패딩
        while len(embedding) < self.dimensions:
            embedding.append(0.5)

        # 정규화 (옵션)
        if self.normalize:
            norm = math.sqrt(sum(x**2 for x in embedding))
            if norm > 0:
                embedding = [x / norm for x in embedding]

        return embedding[:self.dimensions]

    def _encode_sync(self, texts: List[str], is_query: bool = False) -> List[List[float]]:
        """동기 방식 인코딩 (내부 사용)

        Args:
            texts: 임베딩할 텍스트 리스트
            is_query: 쿼리 모드 여부 (현재는 문서와 쿼리가 동일하게 처리됨)

        Returns:
            임베딩 벡터 리스트 (List[List[float]])
        """
        # Mock 모드: 해시 기반 임베딩 생성
        if self.use_mock:
            return [self._get_mock_embedding_sync(text) for text in texts]

        # Bedrock 모드
        embeddings = []

        # Bedrock은 배치 API를 제공하지 않으므로 순차 처리
        # 향후 개선: 병렬 처리로 최적화 가능
        for text in texts:
            try:
                embedding = self._invoke_bedrock(text)
                embeddings.append(embedding)
            except Exception as e:
                logger.error(f"임베딩 생성 실패 (텍스트 길이: {len(text)}): {str(e)}")

                # 개발 환경: Mock으로 폴백
                if settings.is_development:
                    logger.warning("Falling back to mock embedding")
                    embeddings.append(self._get_mock_embedding_sync(text))
                else:
                    # 프로덕션: 제로 벡터로 대체
                    embeddings.append([0.0] * self.dimensions)

        return embeddings

    async def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """문서 텍스트를 임베딩으로 변환 (비동기, 서브배치 최적화)

        Args:
            texts: 임베딩할 문서 텍스트 리스트

        Returns:
            임베딩 벡터 리스트
        """
        # 큰 배치는 서브배치로 분할하여 병렬 처리
        if len(texts) <= self.batch_size:
            # 작은 배치는 한 번에 처리
            loop = asyncio.get_event_loop()
            embeddings = await loop.run_in_executor(
                self.executor,
                self._encode_sync,
                texts,
                False  # is_query=False
            )
            return embeddings
        else:
            # 큰 배치는 서브배치로 분할하여 병렬 처리
            sub_batches = [
                texts[i:i + self.batch_size]
                for i in range(0, len(texts), self.batch_size)
            ]

            loop = asyncio.get_event_loop()
            tasks = [
                loop.run_in_executor(
                    self.executor,
                    self._encode_sync,
                    batch,
                    False
                )
                for batch in sub_batches
            ]

            # 모든 서브배치를 병렬로 처리
            results = await asyncio.gather(*tasks)

            # 결과 병합
            all_embeddings = []
            for batch_embeddings in results:
                all_embeddings.extend(batch_embeddings)

            return all_embeddings

    async def embed_query(self, text: str) -> List[float]:
        """검색 쿼리를 임베딩으로 변환 (비동기)

        Args:
            text: 검색 쿼리 텍스트

        Returns:
            임베딩 벡터
        """
        loop = asyncio.get_event_loop()
        embeddings = await loop.run_in_executor(
            self.executor,
            self._encode_sync,
            [text],  # 리스트로 래핑
            True  # is_query=True
        )
        return embeddings[0]  # 첫 번째 결과 반환

    # 기존 동기 메서드 유지 (하위 호환성)
    def embed_documents_sync(self, texts: List[str]) -> List[List[float]]:
        """문서 텍스트를 임베딩으로 변환 (동기)

        Args:
            texts: 임베딩할 문서 텍스트 리스트

        Returns:
            임베딩 벡터 리스트
        """
        return self._encode_sync(texts, False)

    def embed_query_sync(self, text: str) -> List[float]:
        """검색 쿼리를 임베딩으로 변환 (동기)

        Args:
            text: 검색 쿼리 텍스트

        Returns:
            임베딩 벡터
        """
        return self._encode_sync([text], True)[0]

    def shutdown(self):
        """리소스 정리"""
        self.executor.shutdown(wait=True)
        logger.info("임베딩 서비스 종료")


# 싱글톤 인스턴스
_embedding_service = None
_service_lock = threading.Lock()


def get_embedding_service() -> EmbeddingService:
    """임베딩 서비스 싱글톤 인스턴스 반환 (스레드 안전)"""
    global _embedding_service

    # Fast path: 이미 생성된 경우
    if _embedding_service is not None:
        return _embedding_service

    # Slow path: Lock 획득 후 생성 (Double-checked locking)
    with _service_lock:
        if _embedding_service is None:
            _embedding_service = EmbeddingService()
        return _embedding_service
