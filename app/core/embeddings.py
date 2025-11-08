"""
임베딩 서비스 - AWS Bedrock Titan Embeddings
"""
import logging
import asyncio
import threading
import json
from typing import List
from concurrent.futures import ThreadPoolExecutor
import boto3
from botocore.exceptions import ClientError
from app.config import settings

logger = logging.getLogger(__name__)


class EmbeddingService:
    """임베딩 생성 서비스 (AWS Bedrock Titan Embeddings 사용)"""

    def __init__(self):
        self.client = None
        self.model_id = settings.bedrock_model_id
        self.region_name = settings.aws_region
        self.dimensions = settings.bedrock_dimensions
        self.normalize = settings.bedrock_normalize
        self.batch_size = settings.batch_size
        # 임베딩 작업용 스레드 풀 (병렬 처리 최적화)
        self.executor = ThreadPoolExecutor(max_workers=4)
        self._lock = threading.Lock()  # 스레드 안전성을 위한 락

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

    def _invoke_bedrock(self, text: str) -> List[float]:
        """Bedrock API 호출 (단일 텍스트 임베딩)

        Args:
            text: 임베딩할 텍스트

        Returns:
            임베딩 벡터 (List[float])

        Raises:
            ClientError: Bedrock API 호출 실패
        """
        if self.client is None:
            with self._lock:  # 클라이언트 초기화 시 동시성 제어
                if self.client is None:
                    self._init_client()

        # Bedrock API 요청 본문 구성
        request_body = {
            "inputText": text,
            "dimensions": self.dimensions,
            "normalize": self.normalize
        }

        try:
            # Bedrock API 호출 (재시도 로직 포함)
            response = self.client.invoke_model(
                modelId=self.model_id,
                body=json.dumps(request_body)
            )

            # 응답 파싱
            result = json.loads(response['body'].read())
            embedding = result['embedding']

            return embedding

        except ClientError as e:
            error_code = e.response['Error']['Code']
            error_message = e.response['Error']['Message']

            # 에러 로깅 및 재시도 가능한 에러 처리
            logger.error(f"Bedrock API 호출 실패: {error_code} - {error_message}")

            # 재시도 가능한 에러 (throttling, temporary failure)
            if error_code in ['ThrottlingException', 'ServiceUnavailableException', 'TooManyRequestsException']:
                logger.warning(f"재시도 가능한 에러 발생: {error_code}, 1초 후 재시도")
                import time
                time.sleep(1)
                return self._invoke_bedrock(text)  # 재귀 호출 (1회 재시도)

            # 재시도 불가능한 에러 (권한, 잘못된 요청)
            raise

    def _encode_sync(self, texts: List[str], is_query: bool = False) -> List[List[float]]:
        """동기 방식 인코딩 (내부 사용)

        Args:
            texts: 임베딩할 텍스트 리스트
            is_query: 쿼리 모드 여부 (현재는 문서와 쿼리가 동일하게 처리됨)

        Returns:
            임베딩 벡터 리스트 (List[List[float]])
        """
        embeddings = []

        # Bedrock은 배치 API를 제공하지 않으므로 순차 처리
        # 향후 개선: 병렬 처리로 최적화 가능
        for text in texts:
            try:
                embedding = self._invoke_bedrock(text)
                embeddings.append(embedding)
            except Exception as e:
                logger.error(f"임베딩 생성 실패 (텍스트 길이: {len(text)}): {str(e)}")
                # 실패한 텍스트는 제로 벡터로 대체 (옵션: 에러 발생 시키기)
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
