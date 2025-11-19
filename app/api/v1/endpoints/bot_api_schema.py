"""
Bot API 스키마 관리 엔드포인트

Input/Output 스키마, Alias, 기본 응답 모드 관리 (JWT 인증)
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel, Field
from typing import Optional, List, Any

from app.core.database import get_db
from app.core.auth.dependencies import get_current_user_from_jwt
from app.models.user import User
from app.models.workflow_version import BotWorkflowVersion
from app.services.bot_api_key_service import BotAPIKeyService

router = APIRouter(prefix="/api/v1/bots", tags=["Bot API Schema"])


# ==========================================
# Pydantic 스키마
# ==========================================

class InputField(BaseModel):
    """입력 필드 정의"""
    key: str
    label: str
    type: str = "string"  # string | number | boolean | enum | file
    required: bool = True
    default: Optional[Any] = None
    options: Optional[List[str]] = None  # enum 타입일 때
    description: Optional[str] = None
    is_primary: bool = False  # input_value와 동기화

    class Config:
        json_schema_extra = {
            "example": {
                "key": "user_query",
                "label": "사용자 질문",
                "type": "string",
                "required": True,
                "description": "사용자가 입력한 질문",
                "is_primary": True
            }
        }


class OutputField(BaseModel):
    """출력 필드 정의"""
    node_id: str
    field: str
    label: str

    class Config:
        json_schema_extra = {
            "example": {
                "node_id": "answer_1",
                "field": "text",
                "label": "답변"
            }
        }


class APISchemaResponse(BaseModel):
    """API 스키마 응답"""
    alias: Optional[str] = None
    default_response_mode: str = "blocking"
    inputs: List[InputField]
    outputs: List[OutputField]


class UpdateAPISchemaRequest(BaseModel):
    """API 스키마 업데이트 요청"""
    alias: Optional[str] = Field(None, description="엔드포인트 별칭")
    default_response_mode: str = Field("blocking", description="blocking | streaming")
    inputs: List[InputField] = Field(default_factory=list, description="입력 스키마")
    outputs: List[OutputField] = Field(default_factory=list, description="출력 스키마")


# ==========================================
# API 스키마 관리 엔드포인트
# ==========================================

@router.get("/{bot_id}/api-schema", response_model=APISchemaResponse)
async def get_api_schema(
    bot_id: str,
    user: User = Depends(get_current_user_from_jwt),
    db: AsyncSession = Depends(get_db)
):
    """
    워크플로우의 API 입력/출력 스키마 조회
    
    - 최신 draft 또는 published 버전 스키마 반환
    - API Access 탭에서 편집용
    """
    # 소유자 확인
    await BotAPIKeyService.verify_bot_ownership(bot_id, user.id, db)
    
    # 최신 워크플로우 버전 조회 (draft 우선, 없으면 최신 published)
    result = await db.execute(
        select(BotWorkflowVersion)
        .where(BotWorkflowVersion.bot_id == bot_id)
        .order_by(BotWorkflowVersion.created_at.desc())
        .limit(1)
    )
    workflow_version = result.scalar_one_or_none()
    
    if not workflow_version:
        # 워크플로우 버전이 없으면 빈 스키마 반환
        return APISchemaResponse(
            alias=None,
            default_response_mode="blocking",
            inputs=[],
            outputs=[]
        )
    
    # input_schema를 InputField 리스트로 변환
    inputs = []
    if workflow_version.input_schema:
        for field in workflow_version.input_schema:
            inputs.append(InputField(**field))
    
    # output_schema를 OutputField 리스트로 변환
    outputs = []
    if workflow_version.output_schema:
        for field in workflow_version.output_schema:
            outputs.append(OutputField(**field))
    
    return APISchemaResponse(
        alias=workflow_version.api_endpoint_alias,
        default_response_mode=workflow_version.api_default_response_mode,
        inputs=inputs,
        outputs=outputs
    )


@router.put("/{bot_id}/api-schema")
async def save_api_schema(
    bot_id: str,
    schema: UpdateAPISchemaRequest,
    user: User = Depends(get_current_user_from_jwt),
    db: AsyncSession = Depends(get_db)
):
    """
    API 입력/출력 스키마 저장
    
    - bot_workflow_versions.input_schema에 저장
    - bot_workflow_versions.output_schema에 저장
    - api_endpoint_alias, api_default_response_mode 업데이트
    
    ⚠️ Draft 버전에만 저장 가능
    """
    # 소유자 확인
    await BotAPIKeyService.verify_bot_ownership(bot_id, user.id, db)
    
    # Draft 버전 조회
    result = await db.execute(
        select(BotWorkflowVersion)
        .where(
            BotWorkflowVersion.bot_id == bot_id,
            BotWorkflowVersion.status == "draft"
        )
    )
    workflow_version = result.scalar_one_or_none()
    
    if not workflow_version:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "NO_DRAFT_VERSION",
                "message": "No draft workflow version found. Create a draft first."
            }
        )
    
    # 스키마 업데이트
    workflow_version.input_schema = [field.model_dump() for field in schema.inputs]
    workflow_version.output_schema = [field.model_dump() for field in schema.outputs]
    workflow_version.api_endpoint_alias = schema.alias
    workflow_version.api_default_response_mode = schema.default_response_mode
    
    await db.commit()
    await db.refresh(workflow_version)
    
    return {
        "success": True,
        "message": "API schema saved successfully",
        "workflow_version_id": str(workflow_version.id)
    }

