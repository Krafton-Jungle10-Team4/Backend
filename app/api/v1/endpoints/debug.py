"""
디버깅 엔드포인트 (임시)
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, cast, String
from app.core.database import get_db
from app.models.document_embeddings import DocumentEmbedding
from app.core.redis_client import redis_client
import logging

logger = logging.getLogger(__name__)
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


@router.post("/flush-redis-cache")
async def flush_redis_cache(db: AsyncSession = Depends(get_db)):
    """Redis 캐시 전체 비우기 (관리용)"""
    try:
        # Redis 연결 확인
        if not redis_client.redis:
            await redis_client.connect()
        
        # 현재 키 개수 확인
        all_keys = await redis_client.keys("*")
        key_count = len(all_keys)
        
        if key_count == 0:
            return {
                "status": "success",
                "message": "캐시가 이미 비어있습니다.",
                "keys_before": 0,
                "keys_after": 0
            }
        
        # FLUSHDB 실행
        await redis_client.redis.flushdb()
        logger.warning(f"Redis 캐시 전체 삭제: {key_count}개 키 삭제됨")
        
        # 확인
        remaining_keys = await redis_client.keys("*")
        
        return {
            "status": "success",
            "message": "Redis 캐시가 성공적으로 비워졌습니다.",
            "keys_before": key_count,
            "keys_after": len(remaining_keys)
        }
        
    except Exception as e:
        logger.error(f"Redis 캐시 비우기 실패: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Redis 캐시 비우기 실패: {str(e)}"
        )

