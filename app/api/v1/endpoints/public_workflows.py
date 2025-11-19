"""
공개 워크플로우 API 엔드포인트

RESTful API 배포 기능 - 외부 개발자용 API
"""
from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from datetime import datetime

from app.core.database import get_db
from app.core.auth.public_dependencies import APIKeyContext, get_api_key_context
from app.services.workflow_api_service import WorkflowAPIService

router = APIRouter(prefix="/api/v1/public", tags=["Public Workflows"])


# ==========================================
# Pydantic 스키마
# ==========================================

class WorkflowRunRequest(BaseModel):
    """워크플로우 실행 요청"""
    input_value: Optional[str] = Field(None, description="대표 입력 (Input Schema의 primary 필드)")
    inputs: Dict[str, Any] = Field(default_factory=dict, description="노출된 변수 매핑")
    response_mode: str = Field("blocking", description="blocking | streaming")
    stream: bool = Field(False, description="스트리밍 여부")
    session_id: Optional[str] = Field(None, description="세션 ID (대화 연속성)")
    user: Optional[str] = Field(None, description="최종 사용자 ID")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="메타데이터")

    class Config:
        json_schema_extra = {
            "example": {
                "input_value": "안녕하세요",
                "inputs": {
                    "user_query": "안녕하세요",
                    "language": "ko"
                },
                "response_mode": "blocking",
                "stream": False,
                "session_id": "sess_abc123",
                "user": "user-123",
                "metadata": {
                    "source": "mobile_app"
                }
            }
        }


class WorkflowRunResponse(BaseModel):
    """워크플로우 실행 응답"""
    workflow_run_id: str
    bot_id: str
    workflow_version_id: str
    status: str  # running | completed | failed | stopped
    outputs: Dict[str, Any]
    usage: Dict[str, int]
    created_at: str
    finished_at: Optional[str]
    elapsed_time: Optional[float]  # seconds
    session_id: str


# ==========================================
# 공개 API 엔드포인트
# ==========================================

@router.post("/workflows/run", response_model=WorkflowRunResponse)
async def run_workflow_simple(
    request: Request,
    run_request: WorkflowRunRequest,
    ctx: APIKeyContext = Depends(get_api_key_context),
    db: AsyncSession = Depends(get_db)
):
    """
    워크플로우 간단 실행 (Simple Run)
    
    - API 키에 바인딩된 워크플로우 자동 실행
    - Input Schema에 맞춰 입력 검증
    - blocking 또는 streaming 응답
    
    **인증**: X-API-Key 헤더 필요
    
    **예시**:
    ```bash
    curl -X POST https://api.snapagent.com/api/v1/public/workflows/run \\
      -H "X-API-Key: sk-proj-xxxxx" \\
      -H "Content-Type: application/json" \\
      -d '{
        "inputs": {"user_query": "엔비디아 소식을 알고싶어"},
        "response_mode": "blocking"
      }'
    ```
    """
    # 1. 워크플로우 버전 결정
    workflow_version = await WorkflowAPIService.get_workflow_version_for_api_key(
        api_key=ctx.api_key,
        db=db
    )
    
    # 2. Input Schema 검증
    await WorkflowAPIService.validate_inputs_against_schema(
        inputs=run_request.inputs,
        input_value=run_request.input_value,
        schema=workflow_version.input_schema
    )
    
    # 3. 워크플로우 실행
    result = await WorkflowAPIService.execute_workflow_via_api(
        workflow_version=workflow_version,
        inputs=run_request.inputs,
        input_value=run_request.input_value,
        session_id=run_request.session_id,
        user_id=run_request.user,
        api_key=ctx.api_key,
        metadata=run_request.metadata,
        response_mode=run_request.response_mode,
        db=db
    )
    
    return result


@router.post("/workflows/run/{alias}", response_model=WorkflowRunResponse)
async def run_workflow_with_alias(
    alias: str,
    run_request: WorkflowRunRequest,
    ctx: APIKeyContext = Depends(get_api_key_context),
    db: AsyncSession = Depends(get_db)
):
    """
    Alias를 사용한 워크플로우 실행
    
    - api_endpoint_alias로 워크플로우 버전 조회
    - API 키와 워크플로우 소유자 일치 확인
    
    **예시**:
    ```bash
    curl -X POST https://api.snapagent.com/api/v1/public/workflows/run/customer-support \\
      -H "X-API-Key: sk-proj-xxxxx" \\
      -H "Content-Type: application/json" \\
      -d '{"inputs": {"query": "환불 문의"}}'
    ```
    """
    from app.models.workflow_version import BotWorkflowVersion
    from sqlalchemy import select
    
    # 1. Alias → WorkflowVersion 매핑
    result = await db.execute(
        select(BotWorkflowVersion)
        .where(
            BotWorkflowVersion.api_endpoint_alias == alias,
            BotWorkflowVersion.published_at.isnot(None)
        )
        .order_by(BotWorkflowVersion.published_at.desc())
        .limit(1)
    )
    workflow_version = result.scalar_one_or_none()
    
    if not workflow_version:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "ALIAS_NOT_FOUND",
                "message": f"Workflow alias '{alias}' not found"
            }
        )
    
    # 2. API 키 소유자 검증
    if workflow_version.bot_id != ctx.api_key.bot_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "PERMISSION_DENIED",
                "message": "API key is not authorized for this workflow"
            }
        )
    
    # 3. 실행 (Simple Run과 동일)
    await WorkflowAPIService.validate_inputs_against_schema(
        inputs=run_request.inputs,
        input_value=run_request.input_value,
        schema=workflow_version.input_schema
    )
    
    result = await WorkflowAPIService.execute_workflow_via_api(
        workflow_version=workflow_version,
        inputs=run_request.inputs,
        input_value=run_request.input_value,
        session_id=run_request.session_id,
        user_id=run_request.user,
        api_key=ctx.api_key,
        metadata=run_request.metadata,
        response_mode=run_request.response_mode,
        db=db
    )
    
    return result


@router.get("/workflows/runs/{run_id}")
async def get_workflow_run_detail(
    run_id: str,
    ctx: APIKeyContext = Depends(get_api_key_context),
    db: AsyncSession = Depends(get_db)
):
    """
    워크플로우 실행 상세 조회
    
    - 실행 상태, 입력/출력, 노드별 실행 기록
    - API 키 소유자만 조회 가능
    """
    from app.models.workflow_version import WorkflowExecutionRun
    from sqlalchemy import select
    
    result = await db.execute(
        select(WorkflowExecutionRun).where(
            WorkflowExecutionRun.id == run_id
        )
    )
    run = result.scalar_one_or_none()
    
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "RUN_NOT_FOUND",
                "message": "Workflow run not found"
            }
        )
    
    # API 키 소유자 검증
    if run.bot_id != ctx.api_key.bot_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "PERMISSION_DENIED",
                "message": "You don't have permission to access this run"
            }
        )
    
    return {
        "workflow_run_id": str(run.id),
        "bot_id": run.bot_id,
        "workflow_version_id": str(run.workflow_version_id),
        "status": run.status,
        "inputs": run.inputs,
        "outputs": run.outputs,
        "usage": {
            "total_tokens": run.total_tokens
        },
        "created_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "elapsed_time": run.elapsed_time / 1000.0 if run.elapsed_time else None,
        "error_message": run.error_message
    }


@router.post("/workflows/runs/{run_id}/stop")
async def stop_workflow_run(
    run_id: str,
    ctx: APIKeyContext = Depends(get_api_key_context),
    db: AsyncSession = Depends(get_db)
):
    """
    워크플로우 실행 중지
    
    - streaming 모드에서만 지원
    - API 키 권한 확인
    """
    # 권한 확인
    if not ctx.api_key.permissions.get("stop", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "PERMISSION_DENIED",
                "message": "API key does not have 'stop' permission"
            }
        )
    
    from app.models.workflow_version import WorkflowExecutionRun
    from sqlalchemy import select
    
    result = await db.execute(
        select(WorkflowExecutionRun).where(
            WorkflowExecutionRun.id == run_id
        )
    )
    run = result.scalar_one_or_none()
    
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "RUN_NOT_FOUND",
                "message": "Workflow run not found"
            }
        )
    
    # 소유자 검증
    if run.bot_id != ctx.api_key.bot_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "PERMISSION_DENIED",
                "message": "You don't have permission to stop this run"
            }
        )
    
    # 실행 중지 (상태 업데이트)
    if run.status == "running":
        run.status = "stopped"
        run.finished_at = datetime.now()
        run.elapsed_time = int((run.finished_at - run.started_at).total_seconds() * 1000)
        
        await db.commit()
        await db.refresh(run)
    
    return {
        "workflow_run_id": str(run.id),
        "status": run.status,
        "stopped_at": run.finished_at.isoformat() if run.finished_at else None,
        "stopped_by": "api_key"
    }

