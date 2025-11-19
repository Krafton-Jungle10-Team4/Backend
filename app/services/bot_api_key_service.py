"""
Bot API 키 관리 서비스

API 키 CRUD 및 사용량 조회
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, desc, func
from fastapi import HTTPException, status
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone
import secrets
import logging

from app.models.bot_api_key import BotAPIKey, APIKeyUsage
from app.models.bot import Bot
from app.models.workflow_version import BotWorkflowVersion
from app.core.auth.api_key import hash_api_key

logger = logging.getLogger(__name__)


class BotAPIKeyService:
    """Bot API 키 관리 서비스"""
    
    @staticmethod
    def generate_api_key() -> str:
        """
        API 키 생성 (sk-proj- 접두사)
        
        Returns:
            API 키 문자열 (예: sk-proj-a3f2c8d9...)
        """
        # 48자 hex (24 bytes)
        random_part = secrets.token_hex(24)
        return f"sk-proj-{random_part}"
    
    @staticmethod
    async def verify_bot_ownership(bot_id: str, user_id: int, db: AsyncSession) -> Bot:
        """
        봇 소유자 확인
        
        Args:
            bot_id: 봇 ID
            user_id: 사용자 ID
            db: 데이터베이스 세션
        
        Returns:
            Bot: 봇 객체
        
        Raises:
            HTTPException: 권한 없음
        """
        result = await db.execute(
            select(Bot).where(
                Bot.bot_id == bot_id,
                Bot.user_id == user_id
            )
        )
        bot = result.scalar_one_or_none()
        
        if not bot:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "PERMISSION_DENIED",
                    "message": "You don't have permission to access this bot"
                }
            )
        
        return bot
    
    @staticmethod
    async def verify_workflow_published(
        workflow_version_id: str,
        db: AsyncSession
    ) -> BotWorkflowVersion:
        """
        워크플로우 버전 published 상태 확인
        
        Args:
            workflow_version_id: 워크플로우 버전 ID
            db: 데이터베이스 세션
        
        Returns:
            BotWorkflowVersion: 워크플로우 버전
        
        Raises:
            HTTPException: 버전이 published가 아님
        """
        result = await db.execute(
            select(BotWorkflowVersion).where(
                BotWorkflowVersion.id == workflow_version_id
            )
        )
        version = result.scalar_one_or_none()
        
        if not version:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "code": "VERSION_NOT_FOUND",
                    "message": "Workflow version not found"
                }
            )
        
        if not version.published_at:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "VERSION_NOT_PUBLISHED",
                    "message": "Workflow version must be published"
                }
            )
        
        return version
    
    @staticmethod
    async def list_api_keys(bot_id: str, db: AsyncSession) -> List[Dict[str, Any]]:
        """
        봇의 API 키 목록 조회
        
        Args:
            bot_id: 봇 ID
            db: 데이터베이스 세션
        
        Returns:
            API 키 목록
        """
        result = await db.execute(
            select(BotAPIKey)
            .where(BotAPIKey.bot_id == bot_id)
            .order_by(desc(BotAPIKey.created_at))
        )
        api_keys = result.scalars().all()
        
        # 사용량 요약 조회
        response_keys = []
        for key in api_keys:
            # 오늘 사용량
            today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
            today_usage = await db.execute(
                select(func.sum(APIKeyUsage.total_requests))
                .where(
                    APIKeyUsage.api_key_id == key.id,
                    APIKeyUsage.timestamp_hour >= today
                )
            )
            requests_today = today_usage.scalar() or 0
            
            # 이번 달 사용량
            month_start = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            month_usage = await db.execute(
                select(func.sum(APIKeyUsage.total_requests))
                .where(
                    APIKeyUsage.api_key_id == key.id,
                    APIKeyUsage.timestamp_hour >= month_start
                )
            )
            requests_month = month_usage.scalar() or 0
            
            response_keys.append({
                "id": str(key.id),
                "name": key.name,
                "description": key.description,
                "key_preview": f"{key.key_prefix}...{key.key_suffix}",
                "workflow_version_id": str(key.workflow_version_id) if key.workflow_version_id else None,
                "bind_to_latest_published": key.bind_to_latest_published,
                "permissions": key.permissions,
                "rate_limits": {
                    "per_minute": key.rate_limit_per_minute,
                    "per_hour": key.rate_limit_per_hour,
                    "per_day": key.rate_limit_per_day
                },
                "usage_summary": {
                    "requests_today": requests_today,
                    "requests_month": requests_month,
                    "last_used_at": key.last_used_at.isoformat() if key.last_used_at else None
                },
                "expires_at": key.expires_at.isoformat() if key.expires_at else None,
                "is_active": key.is_active,
                "created_at": key.created_at.isoformat()
            })
        
        return response_keys
    
    @staticmethod
    async def create_api_key(
        bot_id: str,
        user_id: int,
        name: str,
        description: Optional[str],
        workflow_version_id: Optional[str],
        bind_to_latest_published: bool,
        permissions: Dict[str, bool],
        rate_limits: Dict[str, int],
        monthly_request_quota: Optional[int],
        expires_at: Optional[datetime],
        allowed_ips: Optional[List[str]],
        db: AsyncSession
    ) -> Dict[str, Any]:
        """
        API 키 생성
        
        Returns:
            생성된 API 키 정보 (평문 키 포함, 한 번만 표시)
        """
        # API 키 생성
        api_key_plain = BotAPIKeyService.generate_api_key()
        key_hash = hash_api_key(api_key_plain)
        
        # prefix/suffix 추출
        key_prefix = api_key_plain[:12]  # sk-proj-a3f2
        key_suffix = api_key_plain[-4:]  # AbC1
        
        # BotAPIKey 생성
        bot_api_key = BotAPIKey(
            bot_id=bot_id,
            user_id=user_id,
            workflow_version_id=workflow_version_id,
            name=name,
            description=description,
            key_hash=key_hash,
            key_prefix=key_prefix,
            key_suffix=key_suffix,
            permissions=permissions,
            rate_limit_per_minute=rate_limits.get("per_minute", 60),
            rate_limit_per_hour=rate_limits.get("per_hour", 1000),
            rate_limit_per_day=rate_limits.get("per_day", 10000),
            monthly_request_quota=monthly_request_quota,
            expires_at=expires_at,
            bind_to_latest_published=bind_to_latest_published,
            allowed_ips=allowed_ips,
            is_active=True
        )
        
        db.add(bot_api_key)
        await db.commit()
        await db.refresh(bot_api_key)
        
        logger.info(f"API 키 생성 완료: {bot_api_key.id} (bot_id={bot_id})")
        
        return {
            "id": str(bot_api_key.id),
            "key": api_key_plain,  # ⚠️ 평문 키 (한 번만 표시)
            "name": bot_api_key.name,
            "description": bot_api_key.description,
            "key_preview": f"{key_prefix}...{key_suffix}",
            "workflow_version_id": str(bot_api_key.workflow_version_id) if bot_api_key.workflow_version_id else None,
            "bind_to_latest_published": bot_api_key.bind_to_latest_published,
            "permissions": bot_api_key.permissions,
            "rate_limits": {
                "per_minute": bot_api_key.rate_limit_per_minute,
                "per_hour": bot_api_key.rate_limit_per_hour,
                "per_day": bot_api_key.rate_limit_per_day
            },
            "expires_at": bot_api_key.expires_at.isoformat() if bot_api_key.expires_at else None,
            "is_active": bot_api_key.is_active,
            "created_at": bot_api_key.created_at.isoformat()
        }
    
    @staticmethod
    async def update_api_key(
        key_id: str,
        name: Optional[str],
        description: Optional[str],
        bind_to_latest_published: Optional[bool],
        workflow_version_id: Optional[str],
        permissions: Optional[Dict[str, bool]],
        rate_limits: Optional[Dict[str, int]],
        is_active: Optional[bool],
        db: AsyncSession
    ) -> Dict[str, Any]:
        """API 키 수정"""
        result = await db.execute(
            select(BotAPIKey).where(BotAPIKey.id == key_id)
        )
        api_key = result.scalar_one_or_none()
        
        if not api_key:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "code": "API_KEY_NOT_FOUND",
                    "message": "API key not found"
                }
            )
        
        # 업데이트
        if name is not None:
            api_key.name = name
        if description is not None:
            api_key.description = description
        if bind_to_latest_published is not None:
            api_key.bind_to_latest_published = bind_to_latest_published
        if workflow_version_id is not None:
            api_key.workflow_version_id = workflow_version_id
        if permissions is not None:
            api_key.permissions = permissions
        if rate_limits is not None:
            if "per_minute" in rate_limits:
                api_key.rate_limit_per_minute = rate_limits["per_minute"]
            if "per_hour" in rate_limits:
                api_key.rate_limit_per_hour = rate_limits["per_hour"]
            if "per_day" in rate_limits:
                api_key.rate_limit_per_day = rate_limits["per_day"]
        if is_active is not None:
            api_key.is_active = is_active
        
        api_key.updated_at = datetime.now(timezone.utc)
        
        await db.commit()
        await db.refresh(api_key)
        
        logger.info(f"API 키 수정 완료: {api_key.id}")
        
        return {
            "id": str(api_key.id),
            "name": api_key.name,
            "description": api_key.description,
            "is_active": api_key.is_active
        }
    
    @staticmethod
    async def delete_api_key(key_id: str, db: AsyncSession) -> None:
        """API 키 삭제"""
        result = await db.execute(
            select(BotAPIKey).where(BotAPIKey.id == key_id)
        )
        api_key = result.scalar_one_or_none()
        
        if not api_key:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "code": "API_KEY_NOT_FOUND",
                    "message": "API key not found"
                }
            )
        
        await db.delete(api_key)
        await db.commit()
        
        logger.info(f"API 키 삭제 완료: {key_id}")

