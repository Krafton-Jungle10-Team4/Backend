"""
문서 업로드 API 엔드포인트
"""
import logging
import uuid
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, func
from app.services.document_service import get_document_service, DocumentService
from app.models.documents import DocumentUploadResponse, SearchResponse
from app.core.auth.dependencies import get_current_user_from_jwt_only
from app.core.database import get_db
from app.models.user import User
from app.config import settings
from app.core.middleware.rate_limit import limiter
from app.core.aws_clients import get_s3_client, get_sqs_client
from app.models.document import Document, DocumentStatus
from app.schemas.document import (
    AsyncDocumentUploadResponse,
    DocumentStatusResponse,
    DocumentListResponse,
    DocumentInfo,
    DocumentRetryResponse,
    DocumentStatusEnum
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/upload", response_model=DocumentUploadResponse)
@limiter.limit("10/minute")  # 분당 10회 제한 (파일 업로드는 비용 큼)
async def upload_document(
    request: Request,
    file: UploadFile = File(..., description="업로드할 문서 파일"),
    bot_id: str = Query(..., description="봇 ID (필수, 형식: bot_{timestamp}_{random})"),
    user: User = Depends(get_current_user_from_jwt_only),
    doc_service: DocumentService = Depends(get_document_service),
    db: AsyncSession = Depends(get_db)
):
    """
    문서 업로드 및 처리

    **인증 방식:** JWT 토큰 (로그인 필수)

    Headers:
        Authorization: Bearer <token>

    Query Parameters:
        bot_id: 문서를 저장할 봇 ID
    """
    logger.info(f"파일 업로드 요청: {file.filename} (User: {user.email}, UUID: {user.uuid}, Bot ID: {bot_id})")

    # 파일 크기 검증
    file.file.seek(0, 2)
    file_size = file.file.tell()
    file.file.seek(0)

    if file_size > settings.max_file_size:
        raise HTTPException(
            status_code=413,
            detail=f"파일 크기가 너무 큽니다. 최대 {settings.max_file_size / 1024 / 1024:.0f}MB"
        )

    if file_size == 0:
        raise HTTPException(status_code=400, detail="빈 파일은 업로드할 수 없습니다")

    # 파일 확장자 검증
    file_extension = file.filename.split('.')[-1].lower()

    if file_extension not in settings.allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"지원하지 않는 파일 형식입니다. 지원 형식: {', '.join(settings.allowed_extensions)}"
        )

    # 문서 처리 (bot_id 전달)
    try:
        result = await doc_service.process_and_store_document(file, bot_id=bot_id, db=db)
        return result
    except ValueError as e:
        logger.error(f"문서 처리 검증 실패: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        # 시스템 에러 (상세 정보는 로그에만 기록)
        logger.error(f"문서 처리 중 오류 발생: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="문서 처리 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.")


@router.get("/search", response_model=SearchResponse)
async def search_documents(
    query: str = Query(..., description="검색할 텍스트", min_length=1),
    bot_id: str = Query(..., description="봇 ID (필수, 형식: bot_{timestamp}_{random})"),
    top_k: int = Query(5, description="반환할 결과 개수", ge=1, le=50),
    user: User = Depends(get_current_user_from_jwt_only),
    doc_service: DocumentService = Depends(get_document_service),
    db: AsyncSession = Depends(get_db)
):
    """
    문서 검색 (RAG 유사도 검색)

    **인증 방식:** JWT 토큰 (로그인 필수)

    Headers:
        Authorization: Bearer <token>

    Query Parameters:
        query: 검색 쿼리
        bot_id: 검색할 봇 ID
        top_k: 반환할 결과 개수
    """
    logger.info(f"검색 요청: query='{query}', bot_id={bot_id}, top_k={top_k} (User: {user.email})")

    try:
        results = await doc_service.search_documents(query=query, top_k=top_k, bot_id=bot_id, db=db)

        # 결과 개수 계산
        count = len(results.get("ids", [[]])[0]) if results.get("ids") else 0

        return SearchResponse(
            query=query,
            results=results,
            count=count
        )
    except Exception as e:
        logger.error(f"검색 실패: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="검색 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.")


@router.get("/{document_id}")
async def get_document_info(
    document_id: str,
    bot_id: str = Query(..., description="봇 ID (필수, 형식: bot_{timestamp}_{random})"),
    user: User = Depends(get_current_user_from_jwt_only),
    doc_service: DocumentService = Depends(get_document_service),
    db: AsyncSession = Depends(get_db)
):
    """
    문서 정보 조회

    **인증 방식:** JWT 토큰 (로그인 필수)

    Headers:
        Authorization: Bearer <token>

    Query Parameters:
        bot_id: 봇 ID
    """
    try:
        info = await doc_service.get_document_info(document_id, bot_id=bot_id, db=db)
        return info
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"문서 정보 조회 실패: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="문서 정보 조회 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.")


@router.delete("/{document_id}")
async def delete_document(
    document_id: str,
    bot_id: str = Query(..., description="봇 ID (필수, 형식: bot_{timestamp}_{random})"),
    user: User = Depends(get_current_user_from_jwt_only),
    doc_service: DocumentService = Depends(get_document_service),
    db: AsyncSession = Depends(get_db)
):
    """
    문서 삭제

    **인증 방식:** JWT 토큰 (로그인 필수)

    Headers:
        Authorization: Bearer <token>

    Query Parameters:
        bot_id: 봇 ID
    """
    try:
        await doc_service.delete_document(document_id, bot_id=bot_id, db=db)
        return {"status": "success", "message": f"문서가 삭제되었습니다: {document_id}"}
    except Exception as e:
        logger.error(f"문서 삭제 실패: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="문서 삭제 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.")


# ============================================
# 비동기 문서 처리 API 엔드포인트 (Phase 0)
# ============================================
# Setup 단계에서는 /upload-async 사용 (S3 업로드 + Worker가 임베딩)


@router.post("/upload-async", response_model=AsyncDocumentUploadResponse)
@limiter.limit("10/minute")
async def upload_document_async(
    request: Request,
    file: UploadFile = File(..., description="업로드할 문서 파일"),
    bot_id: str = Query(..., description="봇 ID (필수, 형식: bot_{timestamp}_{random})"),
    user: User = Depends(get_current_user_from_jwt_only),
    db: AsyncSession = Depends(get_db)
):
    """
    비동기 문서 업로드 (Phase 0)

    파일을 S3에 업로드하고 SQS 큐에 메시지를 전송한 후 즉시 응답합니다.
    실제 임베딩 처리는 백그라운드 워커가 수행합니다.

    **인증 방식:** JWT 토큰 (로그인 필수)

    Headers:
        Authorization: Bearer <token>

    Query Parameters:
        bot_id: 문서를 저장할 봇 ID

    Returns:
        job_id: 문서 ID (상태 조회에 사용)
        status: "queued" (처리 대기 중)
        message: 안내 메시지
        estimated_time: 예상 처리 시간 (초)
    """
    logger.info(f"[비동기] 파일 업로드 요청: {file.filename} (User: {user.email}, Bot ID: {bot_id})")

    # 1. 파일 검증 (크기)
    file.file.seek(0, 2)
    file_size = file.file.tell()
    file.file.seek(0)

    if file_size > settings.max_file_size:
        raise HTTPException(
            status_code=413,
            detail=f"파일 크기가 너무 큽니다. 최대 {settings.max_file_size / 1024 / 1024:.0f}MB"
        )

    if file_size == 0:
        raise HTTPException(status_code=400, detail="빈 파일은 업로드할 수 없습니다")

    # 2. 파일 확장자 검증
    file_extension = file.filename.split('.')[-1].lower()
    if file_extension not in settings.allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"지원하지 않는 파일 형식입니다. 지원 형식: {', '.join(settings.allowed_extensions)}"
        )

    # 3. document_id 생성
    document_id = f"doc_{uuid.uuid4().hex[:12]}"

    try:
        # 4. S3에 파일 업로드
        s3_client = get_s3_client()
        file_content = await file.read()
        s3_key = s3_client.generate_s3_key(bot_id, document_id, file.filename)
        s3_uri = await s3_client.upload_file(
            file_content=file_content,
            key=s3_key,
            content_type=file.content_type or "application/octet-stream"
        )

        # 5. DB에 문서 레코드 생성
        now = datetime.utcnow()
        document = Document(
            document_id=document_id,
            bot_id=bot_id,
            user_uuid=user.uuid,
            original_filename=file.filename,
            file_extension=file_extension,
            file_size=file_size,
            s3_uri=s3_uri,
            status=DocumentStatus.QUEUED,
            queued_at=now,
            created_at=now
        )
        db.add(document)
        await db.commit()

        # 6. SQS 큐에 메시지 전송
        sqs_client = get_sqs_client()
        message_body = {
            "document_id": document_id,
            "bot_id": bot_id,
            "user_uuid": user.uuid,
            "s3_uri": s3_uri,
            "original_filename": file.filename,
            "file_extension": file_extension,
            "file_size": file_size
        }
        message_id = await sqs_client.send_message(message_body)

        logger.info(f"[비동기] 문서 업로드 완료: document_id={document_id}, message_id={message_id}")

        # 7. 예상 처리 시간 계산 (간단한 추정)
        estimated_time = min(30, max(10, file_size // (100 * 1024)))  # 10-30초

        return AsyncDocumentUploadResponse(
            job_id=document_id,
            status="queued",
            message="문서가 처리 대기열에 추가되었습니다",
            estimated_time=estimated_time
        )

    except Exception as e:
        logger.error(f"[비동기] 문서 업로드 실패: {e}", exc_info=True)
        # 롤백은 자동으로 처리됨
        raise HTTPException(
            status_code=500,
            detail="문서 업로드 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요."
        )


@router.get("/status/{document_id}", response_model=DocumentStatusResponse)
async def get_document_status(
    document_id: str,
    user: User = Depends(get_current_user_from_jwt_only),
    db: AsyncSession = Depends(get_db)
):
    """
    문서 처리 상태 조회 (Phase 0)

    **인증 방식:** JWT 토큰 (로그인 필수)

    Headers:
        Authorization: Bearer <token>

    Path Parameters:
        document_id: 문서 ID (upload-async에서 반환된 job_id)

    Returns:
        document_id: 문서 ID
        filename: 파일명
        status: 처리 상태 (queued/processing/done/failed)
        error_message: 에러 메시지 (실패 시)
        chunk_count: 생성된 청크 개수 (완료 시)
        processing_time: 처리 시간 (초)
        created_at: 생성 시간
        updated_at: 수정 시간
        completed_at: 완료 시간
    """
    logger.info(f"문서 상태 조회: document_id={document_id} (User: {user.email})")

    # Document 조회
    result = await db.execute(
        select(Document).where(
            Document.document_id == document_id,
            Document.user_uuid == user.uuid  # 본인 문서만 조회 가능
        )
    )
    document = result.scalar_one_or_none()

    if not document:
        raise HTTPException(
            status_code=404,
            detail="문서를 찾을 수 없습니다"
        )

    return DocumentStatusResponse(
        document_id=document.document_id,
        filename=document.original_filename,
        status=DocumentStatusEnum(document.status.value),
        error_message=document.error_message,
        chunk_count=document.chunk_count,
        processing_time=document.processing_time,
        created_at=document.created_at,
        updated_at=document.updated_at,
        completed_at=document.completed_at
    )


@router.get("/list", response_model=DocumentListResponse)
async def list_documents(
    bot_id: Optional[str] = Query(None, description="봇 ID 필터"),
    status: Optional[DocumentStatusEnum] = Query(None, description="상태 필터"),
    limit: int = Query(50, description="페이지 크기", ge=1, le=100),
    offset: int = Query(0, description="오프셋", ge=0),
    user: User = Depends(get_current_user_from_jwt_only),
    db: AsyncSession = Depends(get_db)
):
    """
    문서 목록 조회 (Phase 0)

    **인증 방식:** JWT 토큰 (로그인 필수)

    Headers:
        Authorization: Bearer <token>

    Query Parameters:
        bot_id: 봇 ID 필터 (선택)
        status: 상태 필터 (선택: queued/processing/done/failed)
        limit: 페이지 크기 (기본: 50, 최대: 100)
        offset: 오프셋 (기본: 0)

    Returns:
        documents: 문서 목록
        total: 전체 문서 개수
        limit: 페이지 크기
        offset: 오프셋
    """
    logger.info(f"문서 목록 조회: bot_id={bot_id}, status={status}, limit={limit}, offset={offset} (User: {user.email})")

    # 쿼리 작성
    query = select(Document).where(Document.user_uuid == user.uuid)

    if bot_id:
        query = query.where(Document.bot_id == bot_id)

    if status:
        query = query.where(Document.status == DocumentStatus(status.value))

    # 전체 개수 조회
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar()

    # 문서 목록 조회 (최신순 정렬, 페이지네이션)
    query = query.order_by(Document.created_at.desc()).limit(limit).offset(offset)
    result = await db.execute(query)
    documents = result.scalars().all()

    # DocumentInfo 리스트 생성
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

    return DocumentListResponse(
        documents=document_list,
        total=total,
        limit=limit,
        offset=offset
    )


@router.post("/retry/{document_id}", response_model=DocumentRetryResponse)
async def retry_document_processing(
    document_id: str,
    user: User = Depends(get_current_user_from_jwt_only),
    db: AsyncSession = Depends(get_db)
):
    """
    실패한 문서 재처리 (Phase 0)

    **인증 방식:** JWT 토큰 (로그인 필수)

    Headers:
        Authorization: Bearer <token>

    Path Parameters:
        document_id: 문서 ID

    Returns:
        job_id: 문서 ID
        status: "queued" (재처리 대기 중)
        message: 안내 메시지
    """
    logger.info(f"문서 재처리 요청: document_id={document_id} (User: {user.email})")

    # Document 조회
    result = await db.execute(
        select(Document).where(
            Document.document_id == document_id,
            Document.user_uuid == user.uuid  # 본인 문서만 재처리 가능
        )
    )
    document = result.scalar_one_or_none()

    if not document:
        raise HTTPException(
            status_code=404,
            detail="문서를 찾을 수 없습니다"
        )

    # FAILED 상태만 재처리 가능
    if document.status != DocumentStatus.FAILED:
        raise HTTPException(
            status_code=400,
            detail=f"재처리할 수 없는 상태입니다. 현재 상태: {document.status.value}"
        )

    try:
        # 상태를 QUEUED로 변경
        document.status = DocumentStatus.QUEUED
        document.queued_at = datetime.utcnow()
        document.error_message = None
        document.retry_count += 1
        await db.commit()

        # SQS 큐에 메시지 재전송
        sqs_client = get_sqs_client()
        message_body = {
            "document_id": document.document_id,
            "bot_id": document.bot_id,
            "user_uuid": document.user_uuid,
            "s3_uri": document.s3_uri,
            "original_filename": document.original_filename,
            "file_extension": document.file_extension,
            "file_size": document.file_size,
            "retry_count": document.retry_count
        }
        message_id = await sqs_client.send_message(message_body)

        logger.info(f"문서 재처리 큐 추가: document_id={document_id}, retry_count={document.retry_count}, message_id={message_id}")

        return DocumentRetryResponse(
            job_id=document_id,
            status="queued",
            message="문서가 재처리 대기열에 추가되었습니다"
        )

    except Exception as e:
        logger.error(f"문서 재처리 실패: {e}", exc_info=True)
        await db.rollback()
        raise HTTPException(
            status_code=500,
            detail="문서 재처리 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요."
        )
