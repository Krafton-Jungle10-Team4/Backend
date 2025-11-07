"""
문서 업로드 API 엔드포인트
"""
import logging
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, Query, Request
from app.services.document_service import get_document_service, DocumentService
from app.models.documents import DocumentUploadResponse, SearchResponse
from app.core.auth.dependencies import get_current_user_from_jwt_only, get_user_team
from app.models.user import User, Team
from app.config import settings
from app.core.middleware.rate_limit import limiter

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/upload", response_model=DocumentUploadResponse)
@limiter.limit("10/minute")  # 분당 10회 제한 (파일 업로드는 비용 큼)
async def upload_document(
    request: Request,
    file: UploadFile = File(..., description="업로드할 문서 파일"),
    user: User = Depends(get_current_user_from_jwt_only),
    team: Team = Depends(get_user_team),
    doc_service: DocumentService = Depends(get_document_service)
):
    """
    문서 업로드 및 처리

    **인증 방식:** JWT 토큰 (로그인 필수)

    Headers:
        Authorization: Bearer <token>
    """
    logger.info(f"파일 업로드 요청: {file.filename} (User: {user.email}, Team: {team.uuid})")
    
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
    
    # 문서 처리 (팀 UUID 전달)
    try:
        result = await doc_service.process_and_store_document(file, team_uuid=team.uuid)
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
    top_k: int = Query(5, description="반환할 결과 개수", ge=1, le=50),
    user: User = Depends(get_current_user_from_jwt_only),
    team: Team = Depends(get_user_team),
    doc_service: DocumentService = Depends(get_document_service)
):
    """
    문서 검색 (RAG 유사도 검색)

    **인증 방식:** JWT 토큰 (로그인 필수)

    Headers:
        Authorization: Bearer <token>
    """
    logger.info(f"검색 요청: query='{query}', top_k={top_k} (User: {user.email}, Team: {team.uuid})")

    try:
        results = doc_service.search_documents(query=query, top_k=top_k, team_uuid=team.uuid)

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
    user: User = Depends(get_current_user_from_jwt_only),
    team: Team = Depends(get_user_team),
    doc_service: DocumentService = Depends(get_document_service)
):
    """
    문서 정보 조회

    **인증 방식:** JWT 토큰 (로그인 필수)

    Headers:
        Authorization: Bearer <token>
    """
    try:
        info = doc_service.get_document_info(document_id, team_uuid=team.uuid)
        return info
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"문서 정보 조회 실패: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="문서 정보 조회 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.")


@router.delete("/{document_id}")
async def delete_document(
    document_id: str,
    user: User = Depends(get_current_user_from_jwt_only),
    team: Team = Depends(get_user_team),
    doc_service: DocumentService = Depends(get_document_service)
):
    """
    문서 삭제

    **인증 방식:** JWT 토큰 (로그인 필수)

    Headers:
        Authorization: Bearer <token>
    """
    try:
        doc_service.delete_document(document_id, team_uuid=team.uuid)
        return {"status": "success", "message": f"문서가 삭제되었습니다: {document_id}"}
    except Exception as e:
        logger.error(f"문서 삭제 실패: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="문서 삭제 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.")
