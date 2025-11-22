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
        user_uuid: str,
        query: str,
        top_k: int,
        db: Optional[AsyncSession] = None,
        document_ids: Optional[List[str]] = None,
        bot_id: Optional[str] = None  # 레거시 호환용, 사용하지 않음
    ) -> List[Dict[str, Any]]:
        """
        유사 문서 검색 (user_uuid 기반, 같은 유저의 모든 문서 검색)

        Args:
            user_uuid: 사용자 UUID
            query: 검색 쿼리
            top_k: 검색할 문서 개수
            db: 데이터베이스 세션
            document_ids: 특정 문서만 검색 (document_id 리스트)
            bot_id: 레거시 호환용 (더 이상 사용하지 않음)

        Returns:
            검색 결과 리스트
        """
        if not user_uuid:
            raise ValueError("user_uuid는 필수입니다")

        if document_ids:
            logger.info(
                "[VectorService] 벡터 검색: user_uuid=%s, query='%s...', top_k=%s, document_ids=%s",
                user_uuid,
                query[:50],
                top_k,
                document_ids
            )
        else:
            logger.info(
                "[VectorService] 벡터 검색: user_uuid=%s, query='%s...', top_k=%s",
                user_uuid,
                query[:50],
                top_k
            )

        # 1. 쿼리 임베딩 생성
        query_embedding = await self.embedding_service.embed_query(query)

        # 2. 벡터 스토어에서 검색 (user_uuid 기반)
        vector_store = get_vector_store(user_uuid=user_uuid, db=db)
        search_results = await vector_store.search(
            query_embedding=query_embedding,
            top_k=top_k,
            document_ids=document_ids
        )

        # 3. 결과 변환
        results = []
        if search_results.get("documents"):
            documents = search_results["documents"][0]
            metadatas = search_results.get("metadatas", [[]])[0]
            distances = search_results.get("distances", [[]])[0]

            for i, (doc, meta) in enumerate(zip(documents, metadatas)):
                distance = distances[i] if i < len(distances) else 2.0
                similarity = 1.0 / (1.0 + distance)

                results.append({
                    "content": doc,
                    "metadata": meta,
                    "similarity": round(similarity, 3),
                    "distance": round(distance, 4)  # 거리 값도 포함
                })

            # 유사도 점수 상세 로깅
            if len(results) > 0:
                similarity_scores = [r["similarity"] for r in results]
                distance_scores = [r["distance"] for r in results]
                avg_similarity = sum(similarity_scores) / len(similarity_scores)
                min_similarity = min(similarity_scores)
                max_similarity = max(similarity_scores)
                logger.info(
                    f"[VectorService] 검색 완료: {len(results)}개 문서 | "
                    f"유사도 범위: {min_similarity:.3f} ~ {max_similarity:.3f} (평균: {avg_similarity:.3f}) | "
                    f"거리 범위: {min(distance_scores):.4f} ~ {max(distance_scores):.4f}"
                )
            else:
                logger.info(f"[VectorService] 검색 완료: {len(results)}개 문서")
        return results

    async def search(
        self,
        query: str,
        user_uuid: str,
        top_k: int = 5,
        search_mode: str = "semantic",
        db: Optional[AsyncSession] = None,
        bot_id: Optional[str] = None  # 레거시 호환용
    ) -> List[Dict[str, Any]]:
        """
        Workflow에서 사용하는 검색 메서드

        내부적으로 search_similar_chunks를 재사용합니다.

        Args:
            query: 검색 쿼리
            user_uuid: 사용자 UUID
            top_k: 검색할 문서 개수
            search_mode: 검색 모드 (semantic, keyword) - 현재는 semantic만 지원
            db: 데이터베이스 세션
            bot_id: 레거시 호환용 (더 이상 사용하지 않음)

        Returns:
            검색 결과 리스트
        """
        logger.info(
            "[VectorService.search] Workflow 검색 호출: user_uuid=%s, mode=%s",
            user_uuid,
            search_mode
        )

        return await self.search_similar_chunks(
            user_uuid=user_uuid,
            query=query,
            top_k=top_k,
            db=db
        )


def get_vector_service() -> VectorService:
    """벡터 서비스 인스턴스 생성"""
    return VectorService()
