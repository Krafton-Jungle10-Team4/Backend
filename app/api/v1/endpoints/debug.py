"""
디버깅 엔드포인트 (임시)
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, cast, String
from app.core.database import get_db
from app.models.document_embeddings import DocumentEmbedding

router = APIRouter()


@router.get("/check-embeddings/{document_id}")
async def check_embeddings(
    document_id: str,
    user_uuid: str = None,
    db: AsyncSession = Depends(get_db)
):
    """임베딩 데이터 확인"""
    
    # 1. 전체 임베딩 개수
    result = await db.execute(
        select(func.count(DocumentEmbedding.id))
        .where(DocumentEmbedding.document_id == document_id)
    )
    total_count = result.scalar()
    
    # 2. 첫 번째 임베딩 메타데이터
    result = await db.execute(
        select(DocumentEmbedding.doc_metadata, DocumentEmbedding.bot_id)
        .where(DocumentEmbedding.document_id == document_id)
        .limit(1)
    )
    row = result.first()
    
    metadata_info = None
    if row:
        metadata, bot_id = row
        metadata_info = {
            "bot_id": bot_id,
            "metadata_keys": list(metadata.keys()) if metadata else [],
            "user_uuid_in_metadata": metadata.get('user_uuid') if metadata else None,
            "document_id_in_metadata": metadata.get('document_id') if metadata else None,
        }
    
    # 3. user_uuid 필터 적용 시
    filtered_count = 0
    if user_uuid:
        result = await db.execute(
            select(func.count(DocumentEmbedding.id))
            .where(DocumentEmbedding.document_id == document_id)
            .where(cast(DocumentEmbedding.doc_metadata['user_uuid'], String) == user_uuid)
        )
        filtered_count = result.scalar()
    
    return {
        "document_id": document_id,
        "total_embeddings": total_count,
        "first_embedding": metadata_info,
        "filtered_by_user_uuid": {
            "user_uuid": user_uuid,
            "count": filtered_count
        } if user_uuid else None
    }

