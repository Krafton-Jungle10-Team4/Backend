"""확장된 템플릿 API 엔드포인트"""
import logging
import json
import uuid
from fastapi import APIRouter, Depends, HTTPException, status, Query, UploadFile, File
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List
import tempfile

from app.core.database import get_db
from app.core.auth.dependencies import get_current_user_from_jwt
from app.models.user import User
from app.models.template import Template
from app.schemas.template import (
    WorkflowTemplate, TemplateSummary, TemplateListResponse, ExportConfig,
    ExportValidation, ImportValidation, TemplateUsageCreate,
    TemplateUsageResponse
)
from app.services.template_service import TemplateService
from app.core.exceptions import (
    NotFoundException, ValidationException,
    PermissionDeniedException, DuplicateException
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get(
    "",
    response_model=TemplateListResponse,
    summary="템플릿 목록 조회 (확장)",
    description="템플릿 목록을 다양한 필터와 함께 조회합니다."
)
async def get_templates(
    visibility: Optional[str] = Query(None, description="가시성 필터 (private, team, public)"),
    category: Optional[str] = Query(None, description="카테고리 필터"),
    search: Optional[str] = Query(None, description="검색 쿼리"),
    tags: Optional[List[str]] = Query(None, description="태그 필터 (OR 조건)"),
    author_id: Optional[str] = Query(None, description="작성자 ID"),
    sort_by: str = Query("created_at", description="정렬 기준"),
    sort_order: str = Query("desc", description="정렬 순서 (asc, desc)"),
    skip: int = Query(0, ge=0, description="건너뛸 개수"),
    limit: int = Query(20, le=100, description="조회 개수"),
    user: User = Depends(get_current_user_from_jwt),
    db: AsyncSession = Depends(get_db),
):
    """확장된 템플릿 목록 조회"""

    templates, total = await TemplateService.list_templates(
        db=db,
        user=user,
        visibility=visibility,
        category=category,
        search=search,
        tags=tags,
        author_id=author_id,
        sort_by=sort_by,
        sort_order=sort_order,
        skip=skip,
        limit=limit
    )

    # WorkflowTemplate 형식으로 변환
    template_responses = []
    for template in templates:
        template_responses.append(TemplateSummary(
            id=template.id,
            name=template.name,
            description=template.description,
            version=template.version,
            created_at=template.created_at,
            updated_at=template.updated_at,
            author={
                "id": template.author_id,
                "name": template.author_name,
                "email": template.author_email
            },
            metadata={
                "tags": template.tags,
                "category": template.category,
                "visibility": template.visibility,
                "source_workflow_id": template.source_workflow_id,
                "source_version_id": str(template.source_version_id) if template.source_version_id else None,
                "node_count": template.node_count,
                "edge_count": template.edge_count,
                "estimated_tokens": template.estimated_tokens,
                "estimated_cost": template.estimated_cost
            },
            input_schema=template.input_schema,
            output_schema=template.output_schema,
            thumbnail_url=template.thumbnail_url
        ))

    return TemplateListResponse(
        templates=template_responses,
        pagination={
            "total": total,
            "skip": skip,
            "limit": limit
        }
    )


@router.get(
    "/{template_id}",
    response_model=WorkflowTemplate,
    summary="템플릿 상세 조회 (확장)",
    description="특정 템플릿의 전체 정보를 조회합니다."
)
async def get_template(
    template_id: str,
    user: User = Depends(get_current_user_from_jwt),
    db: AsyncSession = Depends(get_db),
):
    """템플릿 상세 조회 (graph 포함)"""

    template = await TemplateService.get_template(db, template_id, user)

    return WorkflowTemplate(
        id=template.id,
        name=template.name,
        description=template.description,
        version=template.version,
        created_at=template.created_at,
        updated_at=template.updated_at,
        author={
            "id": template.author_id,
            "name": template.author_name,
            "email": template.author_email
        },
        metadata={
            "tags": template.tags,
            "category": template.category,
            "visibility": template.visibility,
            "source_workflow_id": template.source_workflow_id,
            "source_version_id": str(template.source_version_id) if template.source_version_id else None,
            "node_count": template.node_count,
            "edge_count": template.edge_count,
            "estimated_tokens": template.estimated_tokens,
            "estimated_cost": template.estimated_cost
        },
        graph=template.graph,
        input_schema=template.input_schema,
        output_schema=template.output_schema,
        thumbnail_url=template.thumbnail_url
    )


@router.post(
    "/validate-export",
    response_model=ExportValidation,
    summary="Export 검증",
    description="워크플로우를 템플릿으로 내보내기 전 검증합니다."
)
async def validate_export(
    workflow_id: str = Query(..., description="워크플로우 ID"),
    version_id: str = Query(..., description="워크플로우 버전 ID"),
    user: User = Depends(get_current_user_from_jwt),
    db: AsyncSession = Depends(get_db),
):
    """Export 검증"""

    validation = await TemplateService.validate_export(
        db=db,
        workflow_id=workflow_id,
        version_id=version_id,
        user=user
    )

    return validation


@router.post(
    "/export",
    response_model=WorkflowTemplate,
    status_code=status.HTTP_201_CREATED,
    summary="워크플로우 Export",
    description="워크플로우를 템플릿으로 내보냅니다."
)
async def export_template(
    config: ExportConfig,
    user: User = Depends(get_current_user_from_jwt),
    db: AsyncSession = Depends(get_db),
):
    """워크플로우를 템플릿으로 Export"""

    try:
        template = await TemplateService.export_template(db, config, user)

        return WorkflowTemplate(
            id=template.id,
            name=template.name,
            description=template.description,
            version=template.version,
            created_at=template.created_at,
            updated_at=template.updated_at,
            author={
                "id": template.author_id,
                "name": template.author_name,
                "email": template.author_email
            },
            metadata={
                "tags": template.tags,
                "category": template.category,
                "visibility": template.visibility,
                "source_workflow_id": template.source_workflow_id,
                "source_version_id": str(template.source_version_id) if template.source_version_id else None,
                "node_count": template.node_count,
                "edge_count": template.edge_count,
                "estimated_tokens": template.estimated_tokens,
                "estimated_cost": template.estimated_cost
            },
            graph=template.graph,
            input_schema=template.input_schema,
            output_schema=template.output_schema,
            thumbnail_url=template.thumbnail_url
        )

    except ValidationException as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "VALIDATION_ERROR", "message": str(e), "details": e.details}
        )
    except DuplicateException as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "DUPLICATE_TEMPLATE_NAME", "message": str(e)}
        )
    except Exception as e:
        logger.error(f"Export 실패: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "EXPORT_FAILED", "message": "템플릿 export에 실패했습니다"}
        )


@router.post(
    "/{template_id}/validate-import",
    response_model=ImportValidation,
    summary="Import 검증",
    description="템플릿을 가져오기 전 호환성을 검증합니다."
)
async def validate_import(
    template_id: str,
    user: User = Depends(get_current_user_from_jwt),
    db: AsyncSession = Depends(get_db),
):
    """Import 검증"""

    validation = await TemplateService.validate_import(
        db=db,
        template_id=template_id,
        user=user
    )

    return validation


async def _create_usage_response(
    template_id: str,
    usage: TemplateUsageCreate,
    user: User,
    db: AsyncSession
) -> TemplateUsageResponse:
    """템플릿 사용 기록 생성 공통 구현"""
    try:
        usage_record = await TemplateService.create_usage_record(
            db=db,
            template_id=template_id,
            usage=usage,
            user=user
        )

        return TemplateUsageResponse(
            id=str(usage_record.id),
            template_id=usage_record.template_id,
            workflow_id=usage_record.workflow_id,
            workflow_version_id=str(usage_record.workflow_version_id) if usage_record.workflow_version_id else None,
            node_id=usage_record.node_id,
            user_id=usage_record.user_id,
            event_type=usage_record.event_type,
            note=usage_record.note,
            occurred_at=usage_record.occurred_at
        )

    except NotFoundException as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "TEMPLATE_NOT_FOUND", "message": str(e)}
        )
    except PermissionDeniedException as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "PERMISSION_DENIED", "message": str(e)}
        )


@router.post(
    "/{template_id}/use",
    response_model=TemplateUsageResponse,
    status_code=status.HTTP_201_CREATED,
    summary="템플릿 사용 기록",
    description="템플릿 사용을 기록합니다."
)
async def record_usage(
    template_id: str,
    usage: TemplateUsageCreate,
    user: User = Depends(get_current_user_from_jwt),
    db: AsyncSession = Depends(get_db),
):
    """템플릿 사용 기록"""
    return await _create_usage_response(template_id, usage, user, db)


@router.post(
    "/{template_id}/usage",
    response_model=TemplateUsageResponse,
    status_code=status.HTTP_201_CREATED,
    summary="템플릿 사용 기록 (구 버전)",
    description="기존 클라이언트 호환을 위한 엔드포인트입니다.",
    include_in_schema=False
)
async def record_usage_legacy(
    template_id: str,
    usage: TemplateUsageCreate,
    user: User = Depends(get_current_user_from_jwt),
    db: AsyncSession = Depends(get_db),
):
    """구 버전 호환용 템플릿 사용 기록"""
    return await _create_usage_response(template_id, usage, user, db)


@router.post(
    "/upload",
    response_model=WorkflowTemplate,
    status_code=status.HTTP_201_CREATED,
    summary="템플릿 파일 업로드",
    description="JSON 파일로 템플릿을 업로드합니다."
)
async def upload_template(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user_from_jwt),
    db: AsyncSession = Depends(get_db),
):
    """템플릿 파일 업로드"""

    # 파일 타입 확인
    if not file.filename.endswith('.json'):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "INVALID_FILE", "message": "JSON 파일만 업로드 가능합니다"}
        )

    try:
        # 파일 내용 읽기
        content = await file.read()
        template_data = json.loads(content)

        # 필수 필드 확인
        required_fields = ["name", "graph", "input_schema", "output_schema"]
        for field in required_fields:
            if field not in template_data:
                raise ValidationException(f"필수 필드 누락: {field}")

        # 템플릿 ID 생성
        template_id = f"tpl_{uuid.uuid4().hex[:8]}"

        # 템플릿 생성
        template = Template(
            id=template_id,
            name=template_data["name"],
            description=template_data.get("description", ""),
            category=template_data.get("metadata", {}).get("category", "imported"),
            type="workflow",
            tags=template_data.get("metadata", {}).get("tags", []),
            version=template_data.get("version", "1.0.0"),
            visibility="private",  # 업로드된 템플릿은 기본적으로 private
            author_id=user.uuid,
            author_name=user.name or user.email,
            author_email=user.email,
            node_count=len(template_data["graph"].get("nodes", [])),
            edge_count=len(template_data["graph"].get("edges", [])),
            estimated_tokens=template_data.get("metadata", {}).get("estimated_tokens"),
            estimated_cost=template_data.get("metadata", {}).get("estimated_cost"),
            graph=template_data["graph"],
            input_schema=template_data["input_schema"],
            output_schema=template_data["output_schema"],
            thumbnail_url=template_data.get("thumbnail_url")
        )

        db.add(template)
        await db.commit()
        await db.refresh(template)

        logger.info(f"템플릿 업로드됨: {template_id} by {user.email}")

        # 응답 생성
        return WorkflowTemplate(
            id=template.id,
            name=template.name,
            description=template.description,
            version=template.version,
            created_at=template.created_at,
            updated_at=template.updated_at,
            author={
                "id": template.author_id,
                "name": template.author_name,
                "email": template.author_email
            },
            metadata={
                "tags": template.tags,
                "category": template.category,
                "visibility": template.visibility,
                "node_count": template.node_count,
                "edge_count": template.edge_count
            },
            graph=template.graph,
            input_schema=template.input_schema,
            output_schema=template.output_schema,
            thumbnail_url=template.thumbnail_url
        )

    except json.JSONDecodeError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "INVALID_JSON", "message": "유효하지 않은 JSON 파일입니다"}
        )
    except ValidationException as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "VALIDATION_ERROR", "message": str(e)}
        )
    except Exception as e:
        logger.error(f"업로드 실패: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "UPLOAD_FAILED", "message": "템플릿 업로드에 실패했습니다"}
        )


@router.delete(
    "/{template_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="템플릿 삭제",
    description="템플릿을 삭제합니다."
)
async def delete_template(
    template_id: str,
    user: User = Depends(get_current_user_from_jwt),
    db: AsyncSession = Depends(get_db),
):
    """템플릿 삭제"""

    try:
        await TemplateService.delete_template(db, template_id, user)

    except NotFoundException as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "TEMPLATE_NOT_FOUND", "message": str(e)}
        )
    except PermissionDeniedException as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "FORBIDDEN", "message": str(e)}
        )


@router.patch(
    "/{template_id}",
    response_model=dict,
    summary="템플릿 업데이트",
    description="템플릿 메타데이터를 업데이트합니다."
)
async def update_template(
    template_id: str,
    updates: dict,
    user: User = Depends(get_current_user_from_jwt),
    db: AsyncSession = Depends(get_db),
):
    """템플릿 메타데이터 업데이트"""

    try:
        template = await TemplateService.update_template(
            db=db,
            template_id=template_id,
            updates=updates,
            user=user
        )

        return {
            "id": template.id,
            "name": template.name,
            "updated_at": template.updated_at,
            "message": "템플릿이 성공적으로 업데이트되었습니다"
        }

    except NotFoundException as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "TEMPLATE_NOT_FOUND", "message": str(e)}
        )
    except PermissionDeniedException as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "FORBIDDEN", "message": str(e)}
        )


@router.get(
    "/{template_id}/download",
    summary="템플릿 다운로드",
    description="템플릿을 JSON 파일로 다운로드합니다."
)
async def download_template(
    template_id: str,
    user: User = Depends(get_current_user_from_jwt),
    db: AsyncSession = Depends(get_db),
):
    """템플릿 다운로드"""

    try:
        template = await TemplateService.get_template(db, template_id, user)

        # WorkflowTemplate 형식으로 변환
        template_data = {
            "id": template.id,
            "name": template.name,
            "description": template.description,
            "version": template.version,
            "created_at": template.created_at.isoformat(),
            "author": {
                "id": template.author_id,
                "name": template.author_name,
                "email": template.author_email
            },
            "metadata": {
                "tags": template.tags,
                "category": template.category,
                "visibility": template.visibility,
                "node_count": template.node_count,
                "edge_count": template.edge_count,
                "estimated_tokens": template.estimated_tokens,
                "estimated_cost": template.estimated_cost
            },
            "graph": template.graph,
            "input_schema": template.input_schema,
            "output_schema": template.output_schema,
            "thumbnail_url": template.thumbnail_url
        }

        # 임시 파일 생성
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(template_data, f, indent=2, ensure_ascii=False)
            temp_path = f.name

        # 파일 응답
        return FileResponse(
            path=temp_path,
            filename=f"template_{template.name}_{template.version}.json",
            media_type="application/json"
        )

    except NotFoundException as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "TEMPLATE_NOT_FOUND", "message": str(e)}
        )
    except PermissionDeniedException as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "PERMISSION_DENIED", "message": str(e)}
        )
