"""
라이브러리 에이전트 관리 서비스

라이브러리에 등록된 워크플로우 에이전트 조회, 가져오기 등의 기능을 제공합니다.
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, func
from sqlalchemy.orm import selectinload
from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime
import logging

from app.models.workflow_version import BotWorkflowVersion
from app.models.import_history import AgentImportHistory
from app.models.bot import Bot
from app.models.user import User
from app.models.deployment import BotDeployment
from app.schemas.workflow import WorkflowVersionStatus, LibraryAgentResponse

logger = logging.getLogger(__name__)


class LibraryService:
    """라이브러리 에이전트 관리 서비스"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_library_agents(
        self,
        user_id: int,
        category: Optional[str] = None,
        visibility: Optional[str] = None,
        search: Optional[str] = None,
        tags: Optional[List[str]] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Tuple[List[LibraryAgentResponse], int]:
        """
        라이브러리 에이전트 목록 조회 (필터링, 페이지네이션)

        Args:
            category: 카테고리 필터 (선택)
            visibility: 공개 범위 필터 (선택)
            search: 검색어 - 이름, 설명에서 검색 (선택)
            tags: 태그 필터 (선택)
            page: 페이지 번호 (기본: 1)
            page_size: 페이지 크기 (기본: 20)

        Returns:
            Tuple[List[LibraryAgentResponse], int]: (에이전트 목록, 전체 개수)
        """
        # 기본 쿼리: 라이브러리에 등록되고 발행된 버전만 + visibility 접근 제어
        # Bot 테이블을 경유하여 BotDeployment와 LEFT JOIN
        stmt = (
            select(
                BotWorkflowVersion,
                BotDeployment.status.label("deployment_status"),
                BotDeployment.widget_key,
                BotDeployment.created_at.label("deployed_at")
            )
            .join(Bot, BotWorkflowVersion.bot_id == Bot.bot_id)
            .outerjoin(
                BotDeployment,
                and_(
                    BotDeployment.bot_id == Bot.id,
                    BotDeployment.workflow_version_id == BotWorkflowVersion.id
                )
            )
            .where(
                and_(
                    BotWorkflowVersion.is_in_library == True,
                    BotWorkflowVersion.status == WorkflowVersionStatus.PUBLISHED.value,
                    # team 가시성을 팀 모델 없이 소유자 기반으로 허용 (추후 팀 권한 도입 시 교체)
                    or_(
                        BotWorkflowVersion.library_visibility == "public",
                        and_(
                            BotWorkflowVersion.library_visibility.in_(["private", "team"]),
                            Bot.user_id == user_id
                        )
                    )
                )
            )
        )

        # 카테고리 필터
        if category:
            stmt = stmt.where(BotWorkflowVersion.library_category == category)

        # 공개 범위 필터
        if visibility:
            stmt = stmt.where(BotWorkflowVersion.library_visibility == visibility)

        # 검색어 필터 (이름 또는 설명에 포함)
        if search:
            search_pattern = f"%{search}%"
            stmt = stmt.where(
                or_(
                    BotWorkflowVersion.library_name.ilike(search_pattern),
                    BotWorkflowVersion.library_description.ilike(search_pattern)
                )
            )

        # 태그 필터 (JSONB 배열 포함 여부)
        if tags:
            for tag in tags:
                stmt = stmt.where(
                    BotWorkflowVersion.library_tags.contains([tag])
                )

        # 전체 개수 조회 (deployment join 전 서브쿼리 사용)
        count_stmt = (
            select(func.count())
            .select_from(BotWorkflowVersion)
            .join(Bot, BotWorkflowVersion.bot_id == Bot.bot_id)
            .where(
                and_(
                    BotWorkflowVersion.is_in_library == True,
                    BotWorkflowVersion.status == WorkflowVersionStatus.PUBLISHED.value,
                    or_(
                        BotWorkflowVersion.library_visibility == "public",
                        and_(
                            BotWorkflowVersion.library_visibility.in_(["private", "team"]),
                            Bot.user_id == user_id
                        )
                    )
                )
            )
        )

        # 카운트 쿼리에도 동일한 필터 적용
        if category:
            count_stmt = count_stmt.where(BotWorkflowVersion.library_category == category)
        if visibility:
            count_stmt = count_stmt.where(BotWorkflowVersion.library_visibility == visibility)
        if search:
            search_pattern = f"%{search}%"
            count_stmt = count_stmt.where(
                or_(
                    BotWorkflowVersion.library_name.ilike(search_pattern),
                    BotWorkflowVersion.library_description.ilike(search_pattern)
                )
            )
        if tags:
            for tag in tags:
                count_stmt = count_stmt.where(
                    BotWorkflowVersion.library_tags.contains([tag])
                )

        count_result = await self.db.execute(count_stmt)
        total_count = count_result.scalar() or 0

        # 정렬: 최근 발행된 순
        stmt = stmt.order_by(BotWorkflowVersion.library_published_at.desc())

        # 페이지네이션
        offset = (page - 1) * page_size
        stmt = stmt.offset(offset).limit(page_size)

        # 실행
        result = await self.db.execute(stmt)
        rows = result.all()

        # 배포 정보 포함하여 응답 생성
        agents = [
            LibraryAgentResponse(
                id=str(row.BotWorkflowVersion.id),
                bot_id=row.BotWorkflowVersion.bot_id,
                version=row.BotWorkflowVersion.version,
                library_name=row.BotWorkflowVersion.library_name,
                library_description=row.BotWorkflowVersion.library_description,
                library_category=row.BotWorkflowVersion.library_category,
                library_tags=row.BotWorkflowVersion.library_tags,
                library_visibility=row.BotWorkflowVersion.library_visibility,
                library_published_at=row.BotWorkflowVersion.library_published_at,
                node_count=row.BotWorkflowVersion.node_count,
                edge_count=row.BotWorkflowVersion.edge_count,
                deployment_status=row.deployment_status,
                widget_key=row.widget_key,
                deployed_at=row.deployed_at
            )
            for row in rows
        ]

        logger.info(
            f"Retrieved {len(agents)} library agents "
            f"(page {page}/{(total_count + page_size - 1) // page_size}, total: {total_count})"
        )
        return agents, total_count

    async def get_library_agent_by_id(
        self,
        version_id: str,
        user_id: int
    ) -> Optional[Dict[str, Any]]:
        """
        특정 라이브러리 에이전트 상세 조회

        Args:
            version_id: 워크플로우 버전 ID (UUID)

        Returns:
            Optional[Dict[str, Any]]: 에이전트 정보 (배포 정보 포함) 또는 None

        Raises:
            ValueError: 라이브러리에 등록되지 않은 에이전트인 경우
        """
        stmt = (
            select(
                BotWorkflowVersion,
                BotDeployment.status.label("deployment_status"),
                BotDeployment.widget_key,
                BotDeployment.created_at.label("deployed_at")
            )
            .join(Bot, BotWorkflowVersion.bot_id == Bot.bot_id)
            .outerjoin(
                BotDeployment,
                and_(
                    BotDeployment.bot_id == Bot.id,
                    BotDeployment.workflow_version_id == BotWorkflowVersion.id
                )
            )
            .where(
                and_(
                    BotWorkflowVersion.id == version_id,
                    BotWorkflowVersion.is_in_library == True,
                    BotWorkflowVersion.status == WorkflowVersionStatus.PUBLISHED.value,
                    # team 가시성을 팀 모델 없이 소유자 기반으로 허용 (추후 팀 권한 도입 시 교체)
                    or_(
                        BotWorkflowVersion.library_visibility == "public",
                        and_(
                            BotWorkflowVersion.library_visibility.in_(["private", "team"]),
                            Bot.user_id == user_id
                        )
                    )
                )
            )
        )
        result = await self.db.execute(stmt)
        row = result.one_or_none()

        if not row:
            return None

        agent = row.BotWorkflowVersion
        logger.info(f"Retrieved library agent: {agent.library_name} (version: {agent.version})")

        # 에이전트 정보와 배포 정보를 딕셔너리로 반환
        return {
            "agent": agent,
            "deployment_status": row.deployment_status,
            "widget_key": row.widget_key,
            "deployed_at": row.deployed_at
        }

    async def import_agent_to_bot(
        self,
        source_version_id: str,
        target_bot_id: str,
        user_id: int,
        user_uuid: str
    ) -> BotWorkflowVersion:
        """
        라이브러리 에이전트를 특정 봇의 draft로 가져오기

        Args:
            source_version_id: 가져올 라이브러리 버전 ID (UUID)
            target_bot_id: 대상 봇 ID
            user_id: 가져오는 사용자 UUID

        Returns:
            BotWorkflowVersion: 생성된 draft 버전

        Raises:
            ValueError: 소스 에이전트가 없거나, 타겟 봇이 없거나, 권한이 없는 경우
        """
        # 1. 소스 에이전트 조회 및 검증
        stmt = (
            select(BotWorkflowVersion)
            .join(Bot, BotWorkflowVersion.bot_id == Bot.bot_id)
            .where(
                and_(
                    BotWorkflowVersion.id == source_version_id,
                    BotWorkflowVersion.is_in_library == True,
                    BotWorkflowVersion.status == WorkflowVersionStatus.PUBLISHED.value,
                    or_(
                        BotWorkflowVersion.library_visibility == "public",
                        and_(
                            BotWorkflowVersion.library_visibility.in_(["private", "team"]),
                            Bot.user_id == user_id
                        )
                    )
                )
            )
        )
        result = await self.db.execute(stmt)
        source_agent = result.scalar_one_or_none()

        if not source_agent:
            raise ValueError("소스 에이전트를 찾을 수 없습니다")

        # 2. 타겟 봇 조회 및 권한 검증
        stmt = select(Bot).where(
            and_(
                Bot.bot_id == target_bot_id,
                Bot.user_id == user_id
            )
        )
        result = await self.db.execute(stmt)
        target_bot = result.scalars().first()

        if not target_bot:
            raise ValueError(f"봇을 찾을 수 없거나 권한이 없습니다: {target_bot_id}")

        # 3. 사용자 UUID 검증
        stmt = select(User).where(User.uuid == user_uuid)
        result = await self.db.execute(stmt)
        user = result.scalar_one_or_none()

        if not user:
            raise ValueError(f"사용자를 찾을 수 없습니다: {user_uuid}")

        # 4. 기존 draft 확인 및 삭제 (덮어쓰기)
        stmt = select(BotWorkflowVersion).where(
            and_(
                BotWorkflowVersion.bot_id == target_bot_id,
                BotWorkflowVersion.status == WorkflowVersionStatus.DRAFT.value
            )
        )
        result = await self.db.execute(stmt)
        existing_draft = result.scalar_one_or_none()

        if existing_draft:
            logger.info(f"Overwriting existing draft for bot {target_bot_id}")
            await self.db.delete(existing_draft)

        # 5. 새 draft 생성 (소스 에이전트 복사)
        new_draft = BotWorkflowVersion(
            bot_id=target_bot_id,
            version="draft",
            status=WorkflowVersionStatus.DRAFT.value,
            graph=source_agent.graph,  # 그래프 복사
            environment_variables=source_agent.environment_variables,
            conversation_variables=source_agent.conversation_variables,
            features=source_agent.features,
            input_schema=source_agent.input_schema,
            output_schema=source_agent.output_schema,
            port_definitions=source_agent.port_definitions,
            node_count=source_agent.node_count,
            edge_count=source_agent.edge_count,
            created_by=user.uuid
        )
        self.db.add(new_draft)

        # 6. 가져오기 기록 저장
        import_record = AgentImportHistory(
            source_version_id=source_agent.id,
            target_bot_id=target_bot_id,
            imported_by=user.uuid,
            import_metadata={
                "source_library_name": source_agent.library_name,
                "source_version": source_agent.version,
                "source_category": source_agent.library_category,
                "node_count": source_agent.node_count,
                "edge_count": source_agent.edge_count
            }
        )
        self.db.add(import_record)

        await self.db.commit()
        await self.db.refresh(new_draft)

        logger.info(
            f"Imported library agent '{source_agent.library_name}' "
            f"to bot {target_bot_id} as draft by user {user_id}"
        )
        return new_draft
