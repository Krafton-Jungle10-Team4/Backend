"""
벡터 검색 서비스
"""
import logging
from typing import List, Dict, Any, Optional
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
        bot_id: str,
        query: str,
        top_k: int,
        db: Optional[AsyncSession] = None
    ) -> List[Dict[str, Any]]:
        """
        유사 문서 검색

        Args:
            bot_id: 봇 ID
            query: 검색 쿼리
            top_k: 검색할 문서 개수
            db: 데이터베이스 세션

        Returns:
            검색 결과 리스트
        """
        logger.info(f"[VectorService] 벡터 검색: bot_id={bot_id}, query='{query[:50]}...', top_k={top_k}")

        # 1. 쿼리 임베딩 생성
        query_embedding = await self.embedding_service.embed_query(query)

        # 2. 벡터 스토어에서 검색
        vector_store = get_vector_store(bot_id=bot_id, db=db)
        search_results = await vector_store.search(
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

    async def search(
        self,
        query: str,
        dataset_id: str,
        top_k: int = 5,
        search_mode: str = "semantic"
    ) -> List[Dict[str, Any]]:
        """
        Workflow에서 사용하는 검색 메서드

        내부적으로 search_similar_chunks를 재사용합니다.

        Args:
            query: 검색 쿼리
            dataset_id: 데이터셋 ID (user_uuid와 동일)
            top_k: 검색할 문서 개수
            search_mode: 검색 모드 (semantic, keyword) - 현재는 semantic만 지원

        Returns:
            검색 결과 리스트
        """
        logger.info(f"[VectorService.search] Workflow 검색 호출: dataset_id={dataset_id}, mode={search_mode}")

        # search_similar_chunks 재사용 (db는 Optional이므로 None 전달)
        return await self.search_similar_chunks(
            user_uuid=dataset_id,
            query=query,
            top_k=top_k,
            db=None
        )


def get_vector_service() -> VectorService:
    """벡터 서비스 인스턴스 생성"""
    return VectorService()
