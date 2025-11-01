"""
ChromaDB 벡터 스토어 관리
"""
import logging
import time
from typing import List, Dict, Optional
import chromadb
# Settings 임포트 제거 - 0.5.x에서는 필요없음
from app.config import settings

logger = logging.getLogger(__name__)


class VectorStore:
    """ChromaDB 벡터 스토어 클래스"""

    def __init__(self):
        self.client = None
        self.collection = None

    def connect(self, max_retries: int = 5, retry_delay: int = 5):
        """
        ChromaDB 연결 (재시도 로직 포함)

        Args:
            max_retries: 최대 재시도 횟수
            retry_delay: 재시도 간 대기 시간(초)
        """
        if self.client is None:
            logger.info(f"ChromaDB 연결 중: {settings.chroma_host}:{settings.chroma_port}")

            last_error = None
            for attempt in range(1, max_retries + 1):
                try:
                    # 0.5.x에서는 Settings 객체 없이 직접 파라미터 전달
                    self.client = chromadb.HttpClient(
                        host=settings.chroma_host,
                        port=settings.chroma_port,
                        # 0.5.x에서는 settings 파라미터가 없음
                        # 대신 필요한 설정을 직접 파라미터로 전달
                    )

                    # 연결 테스트 (heartbeat)
                    self.client.heartbeat()

                    # 0.5.x에서는 tenant/database 관리가 더 명확해짐
                    # 기본적으로 "default_tenant"와 "default_database"를 사용
                    # 명시적으로 생성하지 않아도 자동으로 처리됨
                    
                    # 컬렉션 생성 또는 가져오기
                    # 0.5.x에서도 이 메서드는 동일하게 작동
                    self.collection = self.client.get_or_create_collection(
                        name=settings.chroma_collection_name,
                        metadata={"description": "Document embeddings for RAG"}
                    )

                    logger.info(f"ChromaDB 초기화 완료 (시도 {attempt}/{max_retries})")
                    return

                except Exception as e:
                    last_error = e
                    logger.warning(
                        f"ChromaDB 연결 실패 (시도 {attempt}/{max_retries}): {str(e)}"
                    )

                    if attempt < max_retries:
                        logger.info(f"{retry_delay}초 후 재시도...")
                        time.sleep(retry_delay)
                    else:
                        logger.error(
                            f"ChromaDB 연결 최종 실패 ({max_retries}회 시도). "
                            f"ChromaDB 서비스가 실행 중인지 확인하세요: "
                            f"{settings.chroma_host}:{settings.chroma_port}"
                        )
                        raise last_error
    
    def add_documents(
        self,
        ids: List[str],
        embeddings: List[List[float]],
        documents: List[str],
        metadatas: List[Dict]
    ):
        """
        문서와 임베딩을 벡터 스토어에 추가
        
        0.5.x에서도 동일한 방식으로 작동하지만,
        내부적으로 더 효율적인 배치 처리가 이루어집니다.
        """
        if self.collection is None:
            self.connect()
            
        self.collection.add(
            ids=ids,
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas
        )
        
        logger.info(f"벡터 스토어에 {len(ids)}개 문서 추가 완료")
    
    def search(
        self,
        query_embedding: List[float],
        top_k: int = 5,
        filter_dict: Optional[Dict] = None
    ) -> Dict:
        """
        유사도 검색
        
        0.5.x에서는 query 메서드의 반환 형식이 조금 더 명확해졌습니다.
        """
        if self.collection is None:
            self.connect()
            
        # 0.5.x에서도 동일하게 작동
        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            where=filter_dict
        )
        
        return results
    
    def get_document(self, document_id: str) -> Optional[Dict]:
        """
        문서 ID로 문서 조회
        
        0.5.x에서도 get 메서드는 동일하게 작동합니다.
        """
        if self.collection is None:
            self.connect()
            
        try:
            results = self.collection.get(
                ids=[document_id],
                include=["documents", "metadatas", "embeddings"]
            )
            
            if results and results["ids"]:
                return {
                    "id": results["ids"][0],
                    "document": results["documents"][0],
                    "metadata": results["metadatas"][0]
                }
            return None
        except Exception as e:
            logger.error(f"문서 조회 실패: {e}")
            return None
    
    def delete_document(self, document_id: str):
        """
        문서 삭제
        
        0.5.x에서도 동일한 방식으로 작동합니다.
        """
        if self.collection is None:
            self.connect()
            
        # document_id로 시작하는 모든 청크 삭제
        try:
            results = self.collection.get(
                where={"document_id": document_id}
            )
            
            if results and results["ids"]:
                self.collection.delete(ids=results["ids"])
                logger.info(f"문서 삭제 완료: {document_id} ({len(results['ids'])}개 청크)")
        except Exception as e:
            logger.error(f"문서 삭제 실패: {e}")
            raise
    
    def count_documents(self) -> int:
        """
        컬렉션 내 문서 개수 반환
        
        0.5.x에서도 동일하게 작동합니다.
        """
        if self.collection is None:
            self.connect()
            
        return self.collection.count()


# 싱글톤 인스턴스
_vector_store = None


def get_vector_store() -> VectorStore:
    """벡터 스토어 싱글톤 인스턴스 반환"""
    global _vector_store
    if _vector_store is None:
        _vector_store = VectorStore()
    return _vector_store