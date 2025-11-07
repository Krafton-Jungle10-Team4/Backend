"""
임베딩 서비스
"""
import logging
import asyncio
import threading
from typing import List
from concurrent.futures import ThreadPoolExecutor
from sentence_transformers import SentenceTransformer
from app.config import settings

logger = logging.getLogger(__name__)


class EmbeddingService:
    """임베딩 생성 서비스 (비동기 지원)"""

    def __init__(self):
        self.model = None
        self.model_name = settings.embedding_model
        self.device = settings.embedding_device
        self.batch_size = settings.batch_size
        # 임베딩 작업용 스레드 풀 (병렬 처리 최적화)
        self.executor = ThreadPoolExecutor(max_workers=4)
        self._lock = threading.Lock()  # 스레드 안전성을 위한 락

    def load_model(self):
        """임베딩 모델 로드"""
        if self.model is None:
            logger.info(f"임베딩 모델 로딩 중: {self.model_name}")
            self.model = SentenceTransformer(self.model_name, device=self.device)
            logger.info("임베딩 모델 로딩 완료")

    def _encode_sync(self, texts: List[str], is_query: bool = False) -> List[List[float]]:
        """동기 방식 인코딩 (내부 사용)"""
        if self.model is None:
            with self._lock:  # 모델 로딩 시 동시성 제어
                if self.model is None:
                    self.load_model()

        if is_query:
            # 단일 쿼리 인코딩
            embedding = self.model.encode(texts[0], convert_to_numpy=True)
            return [embedding.tolist()]
        else:
            # 배치 문서 인코딩 (서브배치로 분할하여 처리)
            embeddings = self.model.encode(
                texts,
                batch_size=self.batch_size,
                show_progress_bar=False,  # 비동기 실행 시 progress bar 비활성화
                convert_to_numpy=True,
                normalize_embeddings=True  # 정규화로 검색 성능 향상
            )
            return embeddings.tolist()

    async def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """문서 텍스트를 임베딩으로 변환 (비동기, 서브배치 최적화)"""
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
        """검색 쿼리를 임베딩으로 변환 (비동기)"""
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
        """문서 텍스트를 임베딩으로 변환 (동기)"""
        return self._encode_sync(texts, False)

    def embed_query_sync(self, text: str) -> List[float]:
        """검색 쿼리를 임베딩으로 변환 (동기)"""
        return self._encode_sync([text], True)[0]

    def shutdown(self):
        """리소스 정리"""
        self.executor.shutdown(wait=True)


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
