"""지식 관리 API 엔드포인트"""
import logging
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, func
from typing import Optional, List
import uuid

from app.core.database import get_db
from app.core.auth.dependencies import get_current_user_from_jwt
from app.models.user import User
from app.models.knowledge import Knowledge as KnowledgeModel
from app.models.document import Document, DocumentStatus
from app.schemas.knowledge import Knowledge, KnowledgeCreate, KnowledgeUpdate
from app.schemas.document import DocumentInfo, DocumentStatusEnum

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get(
    "",
    response_model=List[Knowledge],
    summary="지식 목록 조회",
    description="사용자의 지식 목록을 태그 및 검색어로 필터링하여 조회합니다. 문서 목록도 함께 반환됩니다."
)
async def get_knowledge(
    tags: Optional[List[str]] = Query(None, description="태그 필터"),
    search: Optional[str] = Query(None, description="검색 쿼리"),
    skip: int = Query(0, ge=0, description="건너뛸 개수"),
    limit: int = Query(50, le=100, description="조회 개수"),
    include_documents: bool = Query(True, description="문서 목록 포함 여부"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_from_jwt),
):
    """
    지식 목록 조회

    - tags: 태그 필터
    - search: 이름 검색
    - include_documents: 문서 목록 포함 여부 (기본: True)
    """
    logger.info(f"지식 목록 조회: user_id={current_user.id}, tags={tags}, search={search}, include_documents={include_documents}")

    query = select(KnowledgeModel).where(KnowledgeModel.user_id == current_user.id)

    if search:
        search_pattern = f"%{search}%"
        query = query.where(
            or_(
                KnowledgeModel.name.ilike(search_pattern),
                KnowledgeModel.description.ilike(search_pattern)
            )
        )

    query = query.offset(skip).limit(limit).order_by(KnowledgeModel.created_at.desc())

    result = await db.execute(query)
    knowledge_list = result.scalars().all()

    if tags:
        knowledge_list = [
            k for k in knowledge_list
            if any(tag in k.tags for tag in tags)
        ]

    # 문서 목록 조회 (사용자의 모든 문서)
    if include_documents:
        documents_query = select(Document).where(
            Document.user_uuid == current_user.uuid,
            Document.status == DocumentStatus.DONE
        ).order_by(Document.created_at.desc())
        
        documents_result = await db.execute(documents_query)
        documents = documents_result.scalars().all()
        
        # DocumentInfo로 변환
        document_list = [
            DocumentInfo(
                document_id=doc.document_id,
                bot_id=doc.bot_id,
                original_filename=doc.original_filename,
                file_extension=doc.file_extension,
                file_size=doc.file_size,
                status=DocumentStatusEnum(doc.status.value),
                chunk_count=doc.chunk_count,
                processing_time=doc.processing_time,
                error_message=doc.error_message,
                created_at=doc.created_at,
                updated_at=doc.updated_at
            )
            for doc in documents
        ]
        
        # Knowledge 객체에 문서 목록 추가
        knowledge_response = []
        for k in knowledge_list:
            knowledge_dict = {
                "id": k.id,
                "user_id": k.user_id,
                "name": k.name,
                "description": k.description,
                "tags": k.tags,
                "document_count": len(document_list),  # 사용자의 전체 문서 개수
                "documents": document_list,  # 사용자의 모든 문서
                "created_at": k.created_at,
                "updated_at": k.updated_at
            }
            knowledge_response.append(Knowledge(**knowledge_dict))
        
        logger.info(f"지식 목록 조회 완료: {len(knowledge_list)}개, 문서 {len(document_list)}개 포함")
        return knowledge_response
    else:
        logger.info(f"지식 목록 조회 완료: {len(knowledge_list)}개")
        return knowledge_list


@router.post(
    "",
    response_model=Knowledge,
    status_code=status.HTTP_201_CREATED,
    summary="지식 생성",
    description="새로운 지식을 생성합니다."
)
async def create_knowledge(
    knowledge: KnowledgeCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_from_jwt),
):
    """지식 생성"""
    logger.info(f"지식 생성: user_id={current_user.id}, name={knowledge.name}")

    new_knowledge = KnowledgeModel(
        id=str(uuid.uuid4()),
        user_id=current_user.id,
        name=knowledge.name,
        description=knowledge.description,
        tags=knowledge.tags,
        document_count=0,
    )

    db.add(new_knowledge)
    await db.commit()
    await db.refresh(new_knowledge)

    logger.info(f"지식 생성 완료: id={new_knowledge.id}")
    return new_knowledge


@router.get(
    "/{knowledge_id}",
    response_model=Knowledge,
    summary="지식 상세 조회",
    description="특정 지식의 상세 정보를 조회합니다. 문서 목록도 함께 반환됩니다."
)
async def get_knowledge_detail(
    knowledge_id: str,
    include_documents: bool = Query(True, description="문서 목록 포함 여부"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_from_jwt),
):
    """지식 상세 조회"""
    logger.info(f"지식 상세 조회: knowledge_id={knowledge_id}, include_documents={include_documents}")

    result = await db.execute(
        select(KnowledgeModel).where(
            KnowledgeModel.id == knowledge_id,
            KnowledgeModel.user_id == current_user.id
        )
    )
    knowledge = result.scalar_one_or_none()

    if not knowledge:
        logger.warning(f"지식을 찾을 수 없음: knowledge_id={knowledge_id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="지식을 찾을 수 없습니다."
        )

    # 문서 목록 조회 (사용자의 모든 문서)
    if include_documents:
        documents_query = select(Document).where(
            Document.user_uuid == current_user.uuid,
            Document.status == DocumentStatus.DONE
        ).order_by(Document.created_at.desc())
        
        documents_result = await db.execute(documents_query)
        documents = documents_result.scalars().all()
        
        # DocumentInfo로 변환
        document_list = [
            DocumentInfo(
                document_id=doc.document_id,
                bot_id=doc.bot_id,
                original_filename=doc.original_filename,
                file_extension=doc.file_extension,
                file_size=doc.file_size,
                status=DocumentStatusEnum(doc.status.value),
                chunk_count=doc.chunk_count,
                processing_time=doc.processing_time,
                error_message=doc.error_message,
                created_at=doc.created_at,
                updated_at=doc.updated_at
            )
            for doc in documents
        ]
        
        # Knowledge 객체에 문서 목록 추가
        knowledge_dict = {
            "id": knowledge.id,
            "user_id": knowledge.user_id,
            "name": knowledge.name,
            "description": knowledge.description,
            "tags": knowledge.tags,
            "document_count": len(document_list),  # 사용자의 전체 문서 개수
            "documents": document_list,  # 사용자의 모든 문서
            "created_at": knowledge.created_at,
            "updated_at": knowledge.updated_at
        }
        
        logger.info(f"지식 상세 조회 완료: knowledge_id={knowledge_id}, 문서 {len(document_list)}개 포함")
        return Knowledge(**knowledge_dict)
    else:
        return knowledge


@router.put(
    "/{knowledge_id}",
    response_model=Knowledge,
    summary="지식 수정",
    description="지식 정보를 수정합니다."
)
async def update_knowledge(
    knowledge_id: str,
    knowledge_update: KnowledgeUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_from_jwt),
):
    """지식 수정"""
    logger.info(f"지식 수정: knowledge_id={knowledge_id}")

    result = await db.execute(
        select(KnowledgeModel).where(
            KnowledgeModel.id == knowledge_id,
            KnowledgeModel.user_id == current_user.id
        )
    )
    knowledge = result.scalar_one_or_none()

    if not knowledge:
        logger.warning(f"지식을 찾을 수 없음: knowledge_id={knowledge_id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="지식을 찾을 수 없습니다."
        )

    if knowledge_update.name is not None:
        knowledge.name = knowledge_update.name
    if knowledge_update.description is not None:
        knowledge.description = knowledge_update.description
    if knowledge_update.tags is not None:
        knowledge.tags = knowledge_update.tags

    await db.commit()
    await db.refresh(knowledge)

    logger.info(f"지식 수정 완료: id={knowledge.id}")
    return knowledge


@router.delete(
    "/{knowledge_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="지식 삭제",
    description="지식을 삭제합니다."
)
async def delete_knowledge(
    knowledge_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_from_jwt),
):
    """지식 삭제"""
    logger.info(f"지식 삭제: knowledge_id={knowledge_id}")

    result = await db.execute(
        select(KnowledgeModel).where(
            KnowledgeModel.id == knowledge_id,
            KnowledgeModel.user_id == current_user.id
        )
    )
    knowledge = result.scalar_one_or_none()

    if not knowledge:
        logger.warning(f"지식을 찾을 수 없음: knowledge_id={knowledge_id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="지식을 찾을 수 없습니다."
        )

    await db.delete(knowledge)
    await db.commit()

    logger.info(f"지식 삭제 완료: id={knowledge_id}")
    return None


@router.get(
    "/tags",
    response_model=List[str],
    summary="사용 가능한 태그 조회",
    description="사용자의 지식에서 사용된 모든 태그를 조회합니다."
)
async def get_available_tags(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_from_jwt),
):
    """사용 가능한 태그 목록 조회"""
    logger.info(f"태그 목록 조회: user_id={current_user.id}")

    result = await db.execute(
        select(KnowledgeModel.tags).where(KnowledgeModel.user_id == current_user.id)
    )
    knowledge_list = result.scalars().all()

    tags_set = set()
    for tags in knowledge_list:
        if tags:
            tags_set.update(tags)

    tags_list = sorted(list(tags_set))
    logger.info(f"태그 목록 조회 완료: {len(tags_list)}개")
    return tags_list
