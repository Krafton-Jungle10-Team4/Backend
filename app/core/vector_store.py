"""
PostgreSQL + pgvector 벡터 스토어 관리
"""
import logging
from typing import List, Dict, Optional
from sqlalchemy.orm import Session
from sqlalchemy import select, delete as sql_delete, func

from app.core.database import get_db
from app.models.document_embeddings import DocumentEmbedding
from app.core.exceptions import (
    VectorStoreConnectionError,
    VectorStoreQueryError,
    VectorStoreDocumentError
)

logger = logging.getLogger(__name__)


class VectorStore:
    """PostgreSQL + pgvector 벡터 스토어 클래스"""

    def __init__(
        self,
        bot_id: Optional[int] = None,
        user_uuid: Optional[str] = None,
        db: Optional[Session] = None
    ):
        """
        Args:
            bot_id: 봇 ID (봇별 임베딩 분리용, 우선순위 높음)
            user_uuid: 사용자 UUID (ChromaDB 호환성 유지, 레거시)
            db: 데이터베이스 세션 (외부 주입)

        Note:
            - bot_id가 제공되면 해당 봇의 임베딩 사용
            - bot_id가 없고 user_uuid만 있으면 해당 사용자의 첫 번째 봇 사용
            - db 세션은 외부에서 주입받음 (의존성 주입 패턴)
        """
        if not bot_id and not user_uuid:
            raise ValueError("bot_id 또는 user_uuid 중 하나는 필수입니다")

        self.bot_id = bot_id
        self.user_uuid = user_uuid
        self.db = db

        # user_uuid만 제공된 경우 경고
        if not self.bot_id and self.user_uuid:
            logger.warning(
                f"user_uuid만 제공됨 ({self.user_uuid}). "
                f"bot_id를 제공하는 것을 권장합니다. "
                f"임시로 user_uuid 기반 bot_id를 사용합니다."
            )
            # 임시: user_uuid를 해시해서 임시 bot_id 생성
            import hashlib
            hash_value = int(hashlib.md5(user_uuid.encode()).hexdigest()[:8], 16)
            self.bot_id = hash_value % 1000000

    def _get_session(self) -> Session:
        """세션 확보 (없으면 새로 생성)"""
        if self.db is None:
            # 세션이 없으면 get_db()에서 생성
            self.db = next(get_db())
            logger.debug(f"새 데이터베이스 세션 생성 (bot_id={self.bot_id})")
        return self.db

    def add_documents(
        self,
        ids: List[str],
        embeddings: List[List[float]],
        documents: List[str],
        metadatas: List[Dict]
    ):
        """
        문서와 임베딩을 벡터 스토어에 추가

        Args:
            ids: 문서 ID 리스트 (ChromaDB 호환성)
            embeddings: 임베딩 벡터 리스트
            documents: 문서 텍스트 리스트
            metadatas: 메타데이터 리스트
        """
        db = self._get_session()

        try:
            for idx, (doc_id, embedding, document, metadata) in enumerate(
                zip(ids, embeddings, documents, metadatas)
            ):
                metadata_copy = metadata.copy()
                metadata_copy["document_id"] = doc_id

                doc_embedding = DocumentEmbedding(
                    bot_id=self.bot_id,
                    chunk_text=document,
                    chunk_index=idx,
                    embedding=embedding,
                    metadata=metadata_copy
                )
                db.add(doc_embedding)

            db.commit()
            logger.info(f"벡터 스토어에 {len(ids)}개 문서 추가 완료 (bot_id={self.bot_id})")

        except Exception as e:
            db.rollback()
            logger.error(f"문서 추가 실패: {e}")
            raise VectorStoreDocumentError(
                message="문서 추가 중 오류가 발생했습니다",
                details={
                    "bot_id": self.bot_id,
                    "document_count": len(ids),
                    "error": str(e)
                }
            )

    def search(
        self,
        query_embedding: List[float],
        top_k: int = 5,
        filter_dict: Optional[Dict] = None
    ) -> Dict:
        """
        pgvector 코사인 유사도 검색

        Args:
            query_embedding: 쿼리 임베딩 벡터
            top_k: 반환할 결과 개수
            filter_dict: 메타데이터 필터

        Returns:
            ChromaDB 호환 형식의 결과
        """
        db = self._get_session()

        try:
            # 코사인 거리를 직접 계산하는 쿼리 구성
            # <=> 연산자: 코사인 거리 (0에 가까울수록 유사)
            distance_expr = DocumentEmbedding.embedding.cosine_distance(query_embedding)

            query = select(
                DocumentEmbedding,
                distance_expr.label('distance')
            ).where(
                DocumentEmbedding.bot_id == self.bot_id
            )

            # 메타데이터 필터 적용
            if filter_dict:
                for key, value in filter_dict.items():
                    query = query.where(
                        DocumentEmbedding.metadata[key].astext == str(value)
                    )

            # 거리순 정렬 및 top_k 제한
            query = query.order_by(distance_expr).limit(top_k)

            # 쿼리 실행
            results = db.execute(query).all()

            # ChromaDB 호환 형식으로 변환
            ids = []
            documents = []
            metadatas = []
            distances = []

            for result, distance in results:
                doc_id = result.metadata.get("document_id", str(result.id))
                ids.append(doc_id)
                documents.append(result.chunk_text)
                metadatas.append(result.metadata)
                distances.append(float(distance))

            return {
                "ids": [ids],
                "documents": [documents],
                "metadatas": [metadatas],
                "distances": [distances]
            }

        except Exception as e:
            logger.error(f"벡터 검색 실패: {e}")
            raise VectorStoreQueryError(
                message="벡터 검색 중 오류가 발생했습니다",
                details={
                    "bot_id": self.bot_id,
                    "top_k": top_k,
                    "error": str(e)
                }
            )

    def get_document(self, document_id: str) -> Optional[Dict]:
        """
        문서 ID로 문서 조회

        Args:
            document_id: 조회할 문서 ID (metadata.document_id)

        Returns:
            문서 정보 딕셔너리 또는 None
        """
        db = self._get_session()

        try:
            result = db.execute(
                select(DocumentEmbedding).where(
                    DocumentEmbedding.bot_id == self.bot_id,
                    DocumentEmbedding.metadata["document_id"].astext == document_id
                )
            ).scalars().first()

            if result:
                return {
                    "id": result.metadata.get("document_id", str(result.id)),
                    "document": result.chunk_text,
                    "metadata": result.metadata
                }
            return None

        except Exception as e:
            logger.error(f"문서 조회 실패: {e}")
            raise VectorStoreQueryError(
                message="문서 조회 중 오류가 발생했습니다",
                details={
                    "bot_id": self.bot_id,
                    "document_id": document_id,
                    "error": str(e)
                }
            )

    def delete_document(self, document_id: str):
        """
        문서 삭제 (해당 document_id의 모든 청크 삭제)

        Args:
            document_id: 삭제할 문서 ID (metadata.document_id)
        """
        db = self._get_session()

        try:
            result = db.execute(
                sql_delete(DocumentEmbedding).where(
                    DocumentEmbedding.bot_id == self.bot_id,
                    DocumentEmbedding.metadata["document_id"].astext == document_id
                )
            )

            deleted_count = result.rowcount
            db.commit()

            logger.info(f"문서 삭제 완료: {document_id} ({deleted_count}개 청크)")

        except Exception as e:
            db.rollback()
            logger.error(f"문서 삭제 실패: {e}")
            raise VectorStoreDocumentError(
                message="문서 삭제 중 오류가 발생했습니다",
                details={
                    "bot_id": self.bot_id,
                    "document_id": document_id,
                    "error": str(e)
                }
            )

    def count_documents(self) -> int:
        """
        봇의 임베딩 개수 반환

        Returns:
            임베딩 개수
        """
        db = self._get_session()

        try:
            count = db.query(func.count(DocumentEmbedding.id)).filter(
                DocumentEmbedding.bot_id == self.bot_id
            ).scalar()

            return count or 0

        except Exception as e:
            logger.error(f"문서 개수 조회 실패: {e}")
            raise VectorStoreQueryError(
                message="문서 개수 조회 중 오류가 발생했습니다",
                details={
                    "bot_id": self.bot_id,
                    "error": str(e)
                }
            )


# 봇별/사용자별 벡터 스토어 캐시
_vector_stores: Dict[str, VectorStore] = {}


def get_vector_store(
    bot_id: Optional[int] = None,
    user_uuid: Optional[str] = None,
    db: Optional[Session] = None
) -> VectorStore:
    """
    봇별 또는 사용자별 벡터 스토어 인스턴스 반환

    Args:
        bot_id: 봇 ID (우선순위 높음)
        user_uuid: 사용자 UUID (ChromaDB 호환성, 레거시)
        db: 데이터베이스 세션 (선택적)

    Returns:
        VectorStore 인스턴스

    Note:
        - 세션을 제공하면 캐싱하지 않고 새 인스턴스 생성
        - 세션 없이 호출하면 캐싱된 인스턴스 반환
    """
    # 세션이 제공되면 캐싱 없이 새 인스턴스 생성
    if db is not None:
        return VectorStore(bot_id=bot_id, user_uuid=user_uuid, db=db)

    # 캐시 키 생성
    cache_key = f"bot_{bot_id}" if bot_id else f"user_{user_uuid}"

    if cache_key not in _vector_stores:
        _vector_stores[cache_key] = VectorStore(bot_id=bot_id, user_uuid=user_uuid, db=None)

    return _vector_stores[cache_key]
