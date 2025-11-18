from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.auth.dependencies import get_current_user_from_jwt
from app.models.user import User
from app.config import settings
from app.schemas.deployment import (
    DeploymentCreate,
    DeploymentUpdate,
    DeploymentStatusUpdate,
    DeploymentResponse
)
from app.services.deployment_service import DeploymentService
from app.core.exceptions import NotFoundException, ForbiddenException

router = APIRouter()


@router.post("/{bot_id}/deploy", response_model=DeploymentResponse)
async def create_or_update_deployment(
    bot_id: str,
    deployment_data: DeploymentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_from_jwt)
):
    """
    봇 배포 생성 또는 업데이트

    - **bot_id**: 봇 ID
    - **deployment_data**: 배포 설정
    """
    try:
        deployment = await DeploymentService.create_or_update_deployment(
            db, bot_id, deployment_data, current_user.id
        )

        # Bot 정보 로드
        await db.refresh(deployment, ["bot"])

        # 응답 구성
        widget_url = settings.frontend_url.split(",")[0] if settings.frontend_url else "http://localhost:5173"
        return DeploymentResponse(
            deployment_id=deployment.deployment_id,
            bot_id=deployment.bot.bot_id,
            widget_key=deployment.widget_key,
            status=deployment.status,
            workflow_version_id=deployment.workflow_version_id,
            embed_script=deployment.embed_script,
            widget_url=widget_url,
            allowed_domains=deployment.allowed_domains,
            widget_config=deployment.widget_config,
            version=deployment.version,
            created_at=deployment.created_at,
            updated_at=deployment.updated_at,
            last_active_at=deployment.last_active_at
        )
    except NotFoundException as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenException as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.get("/{bot_id}/deployment", response_model=DeploymentResponse)
async def get_deployment(
    bot_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_from_jwt)
):
    """
    봇 배포 정보 조회

    - **bot_id**: 봇 ID
    """
    deployment = await DeploymentService.get_deployment(db, bot_id, current_user.id)
    if not deployment:
        raise HTTPException(status_code=404, detail="Deployment not found")

    # Bot 정보 로드
    await db.refresh(deployment, ["bot"])

    widget_url = settings.frontend_url.split(",")[0] if settings.frontend_url else "http://localhost:5173"
    return DeploymentResponse(
        deployment_id=deployment.deployment_id,
        bot_id=deployment.bot.bot_id,
        widget_key=deployment.widget_key,
        status=deployment.status,
        workflow_version_id=deployment.workflow_version_id,
        embed_script=deployment.embed_script,
        widget_url=widget_url,
        allowed_domains=deployment.allowed_domains,
        widget_config=deployment.widget_config,
        version=deployment.version,
        created_at=deployment.created_at,
        updated_at=deployment.updated_at,
        last_active_at=deployment.last_active_at
    )


@router.patch("/{bot_id}/deployment/status")
async def update_deployment_status(
    bot_id: str,
    status_update: DeploymentStatusUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_from_jwt)
):
    """
    봇 배포 상태 변경

    - **bot_id**: 봇 ID
    - **status_update**: 상태 업데이트 데이터
    """
    try:
        deployment = await DeploymentService.update_deployment_status(
            db, bot_id, status_update.status, current_user.id
        )
        return {"message": "Deployment status updated", "status": deployment.status}
    except NotFoundException as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/{bot_id}/deployment")
async def delete_deployment(
    bot_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_from_jwt)
):
    """
    봇 배포 삭제

    - **bot_id**: 봇 ID
    """
    try:
        await DeploymentService.delete_deployment(db, bot_id, current_user.id)
        return {"message": "Deployment deleted successfully"}
    except NotFoundException as e:
        raise HTTPException(status_code=404, detail=str(e))
