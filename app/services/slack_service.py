"""
Slack Integration Service
Slack OAuth 연동 및 토큰 관리 서비스
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi import HTTPException, status
from typing import Optional, Dict, Any, List
import logging
from cryptography.fernet import Fernet
import base64
import os

from app.models.slack_integration import SlackIntegration
from app.config import settings

logger = logging.getLogger(__name__)


class SlackService:
    """Slack 연동 서비스"""
    
    @staticmethod
    def _get_encryption_key() -> bytes:
        """암호화 키 가져오기"""
        # 환경 변수에서 키 가져오기 (없으면 생성)
        key = os.environ.get("SLACK_ENCRYPTION_KEY")
        if not key:
            # 개발 환경용 기본 키 (프로덕션에서는 반드시 환경 변수 설정)
            logger.warning("SLACK_ENCRYPTION_KEY not set, using default key (development only)")
            key = Fernet.generate_key().decode()
        
        return key.encode()
    
    @staticmethod
    def encrypt_token(token: str) -> str:
        """토큰 암호화"""
        try:
            f = Fernet(SlackService._get_encryption_key())
            encrypted = f.encrypt(token.encode())
            return base64.urlsafe_b64encode(encrypted).decode()
        except Exception as e:
            logger.error(f"Token encryption failed: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to encrypt token"
            )
    
    @staticmethod
    def decrypt_token(encrypted_token: str) -> str:
        """토큰 복호화"""
        try:
            f = Fernet(SlackService._get_encryption_key())
            decoded = base64.urlsafe_b64decode(encrypted_token.encode())
            decrypted = f.decrypt(decoded)
            return decrypted.decode()
        except Exception as e:
            logger.error(f"Token decryption failed: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to decrypt token"
            )
    
    @staticmethod
    async def create_integration(
        user_id: int,
        bot_id: Optional[str],
        access_token: str,
        workspace_id: str,
        workspace_name: str,
        workspace_icon: Optional[str],
        bot_user_id: Optional[str],
        scopes: List[str],
        db: AsyncSession
    ) -> SlackIntegration:
        """
        Slack 연동 생성
        
        Args:
            user_id: 사용자 ID
            bot_id: 봇 ID (선택)
            access_token: Slack access token
            workspace_id: Slack workspace ID
            workspace_name: Slack workspace name
            workspace_icon: Slack workspace icon URL
            bot_user_id: Slack bot user ID
            scopes: OAuth scopes
            db: DB session
            
        Returns:
            생성된 SlackIntegration
        """
        # 기존 연동 확인 (같은 workspace면 업데이트)
        stmt = select(SlackIntegration).where(
            SlackIntegration.user_id == user_id,
            SlackIntegration.workspace_id == workspace_id
        )
        if bot_id:
            stmt = stmt.where(SlackIntegration.bot_id == bot_id)
        
        result = await db.execute(stmt)
        existing = result.scalar_one_or_none()
        
        # 토큰 암호화
        encrypted_token = SlackService.encrypt_token(access_token)
        
        if existing:
            # 업데이트
            existing.access_token = encrypted_token
            existing.workspace_name = workspace_name
            existing.workspace_icon = workspace_icon
            existing.bot_user_id = bot_user_id
            existing.scopes = scopes
            existing.is_active = True
            
            await db.commit()
            await db.refresh(existing)
            
            logger.info(f"Updated Slack integration: user_id={user_id}, workspace={workspace_name}")
            return existing
        else:
            # 새로 생성
            integration = SlackIntegration(
                user_id=user_id,
                bot_id=bot_id,
                access_token=encrypted_token,
                workspace_id=workspace_id,
                workspace_name=workspace_name,
                workspace_icon=workspace_icon,
                bot_user_id=bot_user_id,
                scopes=scopes,
                is_active=True
            )
            
            db.add(integration)
            await db.commit()
            await db.refresh(integration)
            
            logger.info(f"Created Slack integration: user_id={user_id}, workspace={workspace_name}")
            return integration
    
    @staticmethod
    async def get_integration(
        user_id: int,
        bot_id: Optional[str],
        db: AsyncSession
    ) -> Optional[SlackIntegration]:
        """
        Slack 연동 조회
        
        Args:
            user_id: 사용자 ID
            bot_id: 봇 ID (선택)
            db: DB session
            
        Returns:
            SlackIntegration 또는 None
        """
        stmt = select(SlackIntegration).where(
            SlackIntegration.user_id == user_id,
            SlackIntegration.is_active == True
        )
        
        if bot_id:
            stmt = stmt.where(SlackIntegration.bot_id == bot_id)
        
        result = await db.execute(stmt)
        return result.scalar_one_or_none()
    
    @staticmethod
    async def get_integration_by_id(
        integration_id: int,
        user_id: int,
        db: AsyncSession
    ) -> Optional[SlackIntegration]:
        """
        ID로 Slack 연동 조회 (소유권 확인 포함)
        
        Args:
            integration_id: 연동 ID
            user_id: 사용자 ID
            db: DB session
            
        Returns:
            SlackIntegration 또는 None
        """
        result = await db.execute(
            select(SlackIntegration).where(
                SlackIntegration.id == integration_id,
                SlackIntegration.user_id == user_id
            )
        )
        return result.scalar_one_or_none()
    
    @staticmethod
    async def list_integrations(
        user_id: int,
        db: AsyncSession
    ) -> List[SlackIntegration]:
        """
        사용자의 모든 Slack 연동 조회
        
        Args:
            user_id: 사용자 ID
            db: DB session
            
        Returns:
            SlackIntegration 리스트
        """
        result = await db.execute(
            select(SlackIntegration)
            .where(SlackIntegration.user_id == user_id)
            .order_by(SlackIntegration.created_at.desc())
        )
        return list(result.scalars().all())
    
    @staticmethod
    async def delete_integration(
        integration_id: int,
        user_id: int,
        db: AsyncSession
    ) -> bool:
        """
        Slack 연동 삭제
        
        Args:
            integration_id: 연동 ID
            user_id: 사용자 ID
            db: DB session
            
        Returns:
            삭제 성공 여부
        """
        integration = await SlackService.get_integration_by_id(integration_id, user_id, db)
        
        if not integration:
            return False
        
        await db.delete(integration)
        await db.commit()
        
        logger.info(f"Deleted Slack integration: id={integration_id}, user_id={user_id}")
        return True
    
    @staticmethod
    async def get_channels(
        integration_id: int,
        user_id: int,
        db: AsyncSession
    ) -> List[Dict[str, Any]]:
        """
        Slack 채널 목록 조회
        
        Args:
            integration_id: 연동 ID
            user_id: 사용자 ID
            db: DB session
            
        Returns:
            채널 목록
        """
        integration = await SlackService.get_integration_by_id(integration_id, user_id, db)
        
        if not integration:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Slack integration not found"
            )
        
        # 토큰 복호화
        access_token = SlackService.decrypt_token(integration.access_token)
        
        # Slack API 호출
        try:
            from slack_sdk import WebClient
            from slack_sdk.errors import SlackApiError
            
            client = WebClient(token=access_token)
            
            # Public 채널 조회
            response = client.conversations_list(
                types="public_channel,private_channel",
                limit=200
            )
            
            channels = [
                {
                    "id": ch["id"],
                    "name": ch["name"],
                    "is_private": ch.get("is_private", False),
                    "is_member": ch.get("is_member", False),
                    "num_members": ch.get("num_members", 0)
                }
                for ch in response["channels"]
            ]
            
            return channels
            
        except SlackApiError as e:
            logger.error(f"Slack API error: {e.response['error']}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Slack API error: {e.response['error']}"
            )
        except Exception as e:
            logger.error(f"Failed to get Slack channels: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to get Slack channels"
            )

