"""
벡터 검색 서비스
"""
import logging
from typing import List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.embeddings import get_embedding_service
from app.core.vector_store import get_vector_store

logger = logging.getLogger(__name__)


class VectorService:
    """벡터 검색 서비스"""

    def __init__(self):
        self.embedding_service = get_embedding_service()

    async def search_similar_chunks(
        self,
        team_uuid: str,
        query: str,
        top_k: int,
        db: AsyncSession
    ) -> List[Dict[str, Any]]:
        """
        유사 문서 검색

        Args:
            team_uuid: 팀 UUID
            query: 검색 쿼리
            top_k: 검색할 문서 개수
            db: 데이터베이스 세션

        Returns:
            검색 결과 리스트
        """
        logger.info(f"[VectorService] 벡터 검색: query='{query[:50]}...', top_k={top_k}")

        # 1. 쿼리 임베딩 생성
        query_embedding = self.embedding_service.embed_query(query)

        # 2. 벡터 스토어에서 검색
        vector_store = get_vector_store(team_uuid=team_uuid)
        search_results = vector_store.search(
            query_embedding=query_embedding,
            top_k=top_k
        )

        # 3. 결과 변환
        results = []
        if search_results.get("documents"):
            documents = search_results["documents"][0]
            metadatas = search_results.get("metadatas", [[]])[0]
            distances = search_results.get("distances", [[]])[0]

            for i, (doc, meta) in enumerate(zip(documents, metadatas)):
                similarity = 1.0 / (1.0 + distances[i]) if i < len(distances) else 0.0

                results.append({
                    "content": doc,
                    "metadata": meta,
                    "similarity": round(similarity, 3)
                })

        logger.info(f"[VectorService] 검색 완료: {len(results)}개 문서")
        return results


def get_vector_service() -> VectorService:
    """벡터 서비스 인스턴스 생성"""
    return VectorService()
