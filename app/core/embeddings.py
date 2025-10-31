"""
임베딩 서비스
"""
import logging
from typing import List
from sentence_transformers import SentenceTransformer
from app.config import settings

logger = logging.getLogger(__name__)


class EmbeddingService:
    """임베딩 생성 서비스"""
    
    def __init__(self):
        self.model = None
        self.model_name = settings.embedding_model
        self.device = settings.embedding_device
        self.batch_size = settings.batch_size
        
    def load_model(self):
        """임베딩 모델 로드"""
        if self.model is None:
            logger.info(f"임베딩 모델 로딩 중: {self.model_name}")
            self.model = SentenceTransformer(self.model_name, device=self.device)
            logger.info("임베딩 모델 로딩 완료")
            
    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """문서 텍스트를 임베딩으로 변환"""
        if self.model is None:
            self.load_model()
            
        embeddings = self.model.encode(
            texts,
            batch_size=self.batch_size,
            show_progress_bar=True,
            convert_to_numpy=True
        )
        
        return embeddings.tolist()
    
    def embed_query(self, text: str) -> List[float]:
        """검색 쿼리를 임베딩으로 변환"""
        if self.model is None:
            self.load_model()
            
        embedding = self.model.encode(text, convert_to_numpy=True)
        return embedding.tolist()


# 싱글톤 인스턴스
_embedding_service = None

# 현재는 싱글톤이지만, 나중에 여러 요청을 처리할 때에는 비동기나 배치 처리 도입
def get_embedding_service() -> EmbeddingService:
    """임베딩 서비스 싱글톤 인스턴스 반환"""
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = EmbeddingService()
    return _embedding_service
