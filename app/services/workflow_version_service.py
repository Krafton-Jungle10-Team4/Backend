"""
워크플로우 버전 관리 서비스

워크플로우 draft 생성/수정, 발행, 버전 목록 조회 등의 기능을 제공합니다.
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from typing import List, Optional, Dict, Any
from datetime import datetime
import logging

from app.models.workflow_version import BotWorkflowVersion
from app.models.bot import Bot
from app.schemas.workflow import WorkflowVersionStatus, WorkflowGraph

logger = logging.getLogger(__name__)


class WorkflowVersionService:
    """워크플로우 버전 관리 서비스"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_or_update_draft(
        self,
        bot_id: str,
        graph: Dict[str, Any],
        environment_variables: Dict[str, Any],
        conversation_variables: Dict[str, Any],
        user_id: str
    ) -> BotWorkflowVersion:
        """
        Draft 워크플로우 생성 또는 업데이트

        Args:
            bot_id: 봇 ID
            graph: 워크플로우 그래프
            environment_variables: 환경 변수
            conversation_variables: 대화 변수
            user_id: 사용자 ID

        Returns:
            BotWorkflowVersion: 생성/업데이트된 draft 버전
        """
        # 기존 draft 찾기
        stmt = select(BotWorkflowVersion).where(
            and_(
                BotWorkflowVersion.bot_id == bot_id,
                BotWorkflowVersion.status == WorkflowVersionStatus.DRAFT.value
            )
        )
        result = await self.db.execute(stmt)
        existing_draft = result.scalar_one_or_none()

        if existing_draft:
            # 업데이트
            existing_draft.graph = graph
            existing_draft.environment_variables = environment_variables
            existing_draft.conversation_variables = conversation_variables
            existing_draft.updated_at = datetime.now()

            await self.db.commit()
            await self.db.refresh(existing_draft)

            logger.info(f"Updated draft workflow for bot {bot_id}")
            return existing_draft
        else:
            # 신규 생성
            draft = BotWorkflowVersion(
                bot_id=bot_id,
                version="draft",
                status=WorkflowVersionStatus.DRAFT.value,
                graph=graph,
                environment_variables=environment_variables,
                conversation_variables=conversation_variables,
                created_by=user_id
            )
            self.db.add(draft)
            await self.db.commit()
            await self.db.refresh(draft)

            logger.info(f"Created new draft workflow for bot {bot_id}")
            return draft

    async def publish_draft(
        self,
        bot_id: str,
        version_id: str,
        user_id: str
    ) -> BotWorkflowVersion:
        """
        Draft를 발행하여 published 버전으로 전환

        Args:
            bot_id: 봇 ID
            version_id: 버전 ID
            user_id: 사용자 ID

        Returns:
            BotWorkflowVersion: 발행된 버전

        Raises:
            ValueError: Draft를 찾을 수 없는 경우
        """
        # Draft 조회
        stmt = select(BotWorkflowVersion).where(
            and_(
                BotWorkflowVersion.id == version_id,
                BotWorkflowVersion.bot_id == bot_id,
                BotWorkflowVersion.status == WorkflowVersionStatus.DRAFT.value
            )
        )
        result = await self.db.execute(stmt)
        draft = result.scalar_one_or_none()

        if not draft:
            raise ValueError("Draft를 찾을 수 없습니다")

        # 마지막 published 버전 찾기
        stmt = select(BotWorkflowVersion).where(
            and_(
                BotWorkflowVersion.bot_id == bot_id,
                BotWorkflowVersion.status == WorkflowVersionStatus.PUBLISHED.value
            )
        ).order_by(BotWorkflowVersion.created_at.desc())
        result = await self.db.execute(stmt)
        last_version = result.scalar_one_or_none()

        # 새 버전 번호 생성
        if last_version:
            # v1.1 → v1.2
            version_parts = last_version.version.lstrip('v').split('.')
            new_version = f"v{version_parts[0]}.{int(version_parts[1]) + 1}"
        else:
            new_version = "v1.0"

        # Draft를 Published로 변경
        draft.version = new_version
        draft.status = WorkflowVersionStatus.PUBLISHED.value
        draft.published_at = datetime.now()

        # Bot의 use_workflow_v2 활성화
        stmt = select(Bot).where(Bot.bot_id == bot_id)
        result = await self.db.execute(stmt)
        bot = result.scalar_one_or_none()

        if bot:
            bot.use_workflow_v2 = True
            logger.info(f"Enabled workflow V2 for bot {bot_id}")

        await self.db.commit()
        await self.db.refresh(draft)

        # 새 빈 draft 생성
        new_draft = BotWorkflowVersion(
            bot_id=bot_id,
            version="draft",
            status=WorkflowVersionStatus.DRAFT.value,
            graph=draft.graph,  # 기존 그래프 복사
            environment_variables=draft.environment_variables,
            conversation_variables=draft.conversation_variables,
            created_by=user_id
        )
        self.db.add(new_draft)
        await self.db.commit()

        logger.info(f"Published workflow version {new_version} for bot {bot_id}")
        return draft

    async def list_versions(
        self,
        bot_id: str,
        status: Optional[str] = None
    ) -> List[BotWorkflowVersion]:
        """
        워크플로우 버전 목록 조회

        Args:
            bot_id: 봇 ID
            status: 필터링할 상태 (선택사항)

        Returns:
            List[BotWorkflowVersion]: 버전 목록
        """
        stmt = select(BotWorkflowVersion).where(
            BotWorkflowVersion.bot_id == bot_id
        )

        if status:
            stmt = stmt.where(BotWorkflowVersion.status == status)

        stmt = stmt.order_by(BotWorkflowVersion.created_at.desc())

        result = await self.db.execute(stmt)
        versions = result.scalars().all()

        return list(versions)

    async def get_version(
        self,
        version_id: str
    ) -> Optional[BotWorkflowVersion]:
        """
        특정 버전 조회

        Args:
            version_id: 버전 ID

        Returns:
            Optional[BotWorkflowVersion]: 버전 정보 또는 None
        """
        stmt = select(BotWorkflowVersion).where(
            BotWorkflowVersion.id == version_id
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_published_version(
        self,
        bot_id: str
    ) -> Optional[BotWorkflowVersion]:
        """
        발행된 워크플로우 버전 조회 (가장 최근)

        Args:
            bot_id: 봇 ID

        Returns:
            Optional[BotWorkflowVersion]: 발행된 버전 또는 None
        """
        stmt = select(BotWorkflowVersion).where(
            and_(
                BotWorkflowVersion.bot_id == bot_id,
                BotWorkflowVersion.status == WorkflowVersionStatus.PUBLISHED.value
            )
        ).order_by(BotWorkflowVersion.published_at.desc())

        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def archive_version(
        self,
        version_id: str
    ) -> BotWorkflowVersion:
        """
        버전을 archived 상태로 변경

        Args:
            version_id: 버전 ID

        Returns:
            BotWorkflowVersion: 아카이브된 버전

        Raises:
            ValueError: 버전을 찾을 수 없거나 이미 archived인 경우
        """
        stmt = select(BotWorkflowVersion).where(
            BotWorkflowVersion.id == version_id
        )
        result = await self.db.execute(stmt)
        version = result.scalar_one_or_none()

        if not version:
            raise ValueError("버전을 찾을 수 없습니다")

        if version.status == WorkflowVersionStatus.ARCHIVED.value:
            raise ValueError("이미 아카이브된 버전입니다")

        version.status = WorkflowVersionStatus.ARCHIVED.value
        version.updated_at = datetime.now()

        await self.db.commit()
        await self.db.refresh(version)

        logger.info(f"Archived workflow version {version.version} (id: {version_id})")
        return version
