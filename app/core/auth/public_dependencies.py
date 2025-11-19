"""
공개 API용 인증 의존성

RESTful API 배포 기능을 위한 API 키 인증 및 컨텍스트
"""
from fastapi import Depends, HTTPException, Header, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional, NamedTuple
from datetime import datetime, timezone

from app.core.database import get_db
from app.core.auth.api_key import hash_api_key
from app.models.bot_api_key import BotAPIKey
from app.models.user import User


class APIKeyContext(NamedTuple):
    """API 키 컨텍스트 (사용자 + API 키 정보)"""
    user: User
    api_key: BotAPIKey


async def get_api_key_context(
    x_api_key: str = Header(..., alias="X-API-Key"),
    db: AsyncSession = Depends(get_db)
) -> APIKeyContext:
    """
    API 키로부터 인증 컨텍스트 가져오기
    
    공개 API (/api/v1/public/*) 엔드포인트에서 사용
    
    Args:
        x_api_key: X-API-Key 헤더
        db: 데이터베이스 세션
    
    Returns:
        APIKeyContext: 사용자 및 API 키 정보
    
    Raises:
        HTTPException: 인증 실패 시
    
    Usage:
        @router.post("/workflows/run")
        async def run_workflow(ctx: APIKeyContext = Depends(get_api_key_context)):
            user = ctx.user
            api_key = ctx.api_key
    """
    if not x_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "MISSING_API_KEY",
                "message": "X-API-Key header is required"
            }
        )
    
    # API 키 형식 검증 (sk-proj-로 시작)
    if not x_api_key.startswith("sk-proj-"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "INVALID_API_KEY_FORMAT",
                "message": "API key must start with 'sk-proj-'"
            }
        )
    
    # SHA-256 해싱
    key_hash = hash_api_key(x_api_key)
    
    # BotAPIKey 조회 (eager loading으로 user, bot 함께 로드)
    result = await db.execute(
        select(BotAPIKey)
        .where(
            BotAPIKey.key_hash == key_hash,
            BotAPIKey.is_active == True
        )
    )
    bot_api_key = result.scalar_one_or_none()
    
    if not bot_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "INVALID_API_KEY",
                "message": "API key is invalid or inactive"
            }
        )
    
    # 만료 시간 검증
    if bot_api_key.expires_at and bot_api_key.expires_at <= datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "API_KEY_EXPIRED",
                "message": "API key has expired"
            }
        )
    
    # 사용자 조회
    result = await db.execute(
        select(User).where(User.id == bot_api_key.user_id)
    )
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "USER_NOT_FOUND",
                "message": "User associated with API key not found"
            }
        )
    
    # 마지막 사용 시간 업데이트 (비동기로 처리, 실패해도 무시)
    try:
        bot_api_key.last_used_at = datetime.now(timezone.utc)
        await db.commit()
    except Exception:
        await db.rollback()
        # 로깅은 하되 에러는 무시 (인증 성공은 유지)
        pass
    
    return APIKeyContext(user=user, api_key=bot_api_key)


async def get_workflow_version_for_api_key(
    api_key: BotAPIKey,
    db: AsyncSession
):
    """
    API 키에 바인딩된 워크플로우 버전 조회
    
    Args:
        api_key: BotAPIKey 모델
        db: 데이터베이스 세션
    
    Returns:
        BotWorkflowVersion: 실행할 워크플로우 버전
    
    Raises:
        HTTPException: 버전을 찾을 수 없거나 published가 아닐 때
    """
    from app.models.workflow_version import BotWorkflowVersion
    
    if api_key.bind_to_latest_published:
        # 최신 published 버전 조회
        result = await db.execute(
            select(BotWorkflowVersion)
            .where(
                BotWorkflowVersion.bot_id == api_key.bot_id,
                BotWorkflowVersion.published_at.isnot(None)
            )
            .order_by(BotWorkflowVersion.published_at.desc())
            .limit(1)
        )
        workflow_version = result.scalar_one_or_none()
        
        if not workflow_version:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "NO_PUBLISHED_VERSION",
                    "message": "No published workflow version available for this API key"
                }
            )
        
        return workflow_version
    else:
        # 고정 버전 사용
        if not api_key.workflow_version_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "NO_VERSION_BOUND",
                    "message": "API key is not bound to any workflow version"
                }
            )
        
        result = await db.execute(
            select(BotWorkflowVersion)
            .where(BotWorkflowVersion.id == api_key.workflow_version_id)
        )
        workflow_version = result.scalar_one_or_none()
        
        if not workflow_version:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "code": "VERSION_NOT_FOUND",
                    "message": "Workflow version not found"
                }
            )
        
        # Published 상태 확인
        if not workflow_version.published_at:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "VERSION_NOT_PUBLISHED",
                    "message": "Workflow version is not published"
                }
            )
        
        return workflow_version

