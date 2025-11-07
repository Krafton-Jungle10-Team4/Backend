from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional
from uuid import UUID

from app.models.deployment import BotDeployment
from app.models.bot import Bot
from app.schemas.deployment import DeploymentCreate, DeploymentUpdate
from app.core.widget.security import widget_security
from app.core.exceptions import NotFoundException, ForbiddenException
from app.config import settings


class DeploymentService:
    """봇 배포 서비스"""

    @staticmethod
    async def create_or_update_deployment(
        db: AsyncSession,
        bot_id: str,
        deployment_data: DeploymentCreate,
        user_id: int
    ) -> BotDeployment:
        """
        봇 배포 생성 또는 업데이트

        Args:
            db: DB 세션
            bot_id: 봇 ID
            deployment_data: 배포 데이터
            user_id: 사용자 ID (권한 확인용)

        Returns:
            배포 객체
        """
        # 봇 조회 및 권한 확인
        stmt = select(Bot).where(Bot.bot_id == bot_id)
        result = await db.execute(stmt)
        bot = result.scalar_one_or_none()

        if not bot:
            raise NotFoundException("Bot not found")

        # 팀 멤버십 확인 (생략: dependencies.py에서 처리)

        # 기존 배포 확인
        stmt = select(BotDeployment).where(BotDeployment.bot_id == bot.id)
        result = await db.execute(stmt)
        existing_deployment = result.scalar_one_or_none()

        if existing_deployment:
            # 업데이트
            existing_deployment.status = deployment_data.status
            existing_deployment.allowed_domains = deployment_data.allowed_domains
            existing_deployment.widget_config = deployment_data.widget_config.dict()
            existing_deployment.version += 1
            existing_deployment.embed_script = DeploymentService._generate_embed_script(
                existing_deployment.widget_key
            )
            await db.commit()
            await db.refresh(existing_deployment)
            return existing_deployment
        else:
            # 생성
            widget_key = widget_security.generate_widget_key()
            embed_script = DeploymentService._generate_embed_script(widget_key)

            deployment = BotDeployment(
                bot_id=bot.id,
                widget_key=widget_key,
                status=deployment_data.status,
                allowed_domains=deployment_data.allowed_domains,
                widget_config=deployment_data.widget_config.dict(),
                embed_script=embed_script,
                version=1
            )
            db.add(deployment)
            await db.commit()
            await db.refresh(deployment)
            return deployment

    @staticmethod
    def _generate_embed_script(widget_key: str) -> str:
        """
        임베드 스크립트 생성

        Args:
            widget_key: Widget Key

        Returns:
            임베드 스크립트 HTML
        """
        widget_url = settings.frontend_url.split(",")[0]  # 첫 번째 프론트엔드 URL
        return (
            f'<script src="{widget_url}/widget/inject.js"></script>\n'
            f'<script src="{widget_url}/widget/config/{widget_key}.js" defer></script>'
        )

    @staticmethod
    async def get_deployment(
        db: AsyncSession,
        bot_id: str,
        user_id: int
    ) -> Optional[BotDeployment]:
        """
        봇 배포 조회

        Args:
            db: DB 세션
            bot_id: 봇 ID
            user_id: 사용자 ID

        Returns:
            배포 객체 또는 None
        """
        stmt = (
            select(BotDeployment)
            .join(Bot)
            .where(Bot.bot_id == bot_id)
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def update_deployment_status(
        db: AsyncSession,
        bot_id: str,
        status: str,
        user_id: int
    ) -> BotDeployment:
        """
        배포 상태 변경

        Args:
            db: DB 세션
            bot_id: 봇 ID
            status: 새 상태
            user_id: 사용자 ID

        Returns:
            업데이트된 배포 객체
        """
        deployment = await DeploymentService.get_deployment(db, bot_id, user_id)
        if not deployment:
            raise NotFoundException("Deployment not found")

        deployment.status = status
        await db.commit()
        await db.refresh(deployment)
        return deployment

    @staticmethod
    async def delete_deployment(
        db: AsyncSession,
        bot_id: str,
        user_id: int
    ):
        """
        배포 삭제

        Args:
            db: DB 세션
            bot_id: 봇 ID
            user_id: 사용자 ID
        """
        deployment = await DeploymentService.get_deployment(db, bot_id, user_id)
        if not deployment:
            raise NotFoundException("Deployment not found")

        await db.delete(deployment)
        await db.commit()
