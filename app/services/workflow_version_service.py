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
from app.models.user import User
from app.schemas.workflow import WorkflowVersionStatus, WorkflowGraph, PortDefinition

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
            user_id: 사용자 UUID

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
            # 스키마 추출
            input_schema, output_schema = self._extract_schemas_from_graph(graph)

            # 업데이트
            existing_draft.graph = graph
            existing_draft.environment_variables = environment_variables
            existing_draft.conversation_variables = conversation_variables
            existing_draft.input_schema = input_schema
            existing_draft.output_schema = output_schema
            existing_draft.updated_at = datetime.now()

            await self.db.commit()
            await self.db.refresh(existing_draft)

            logger.info(f"Updated draft workflow for bot {bot_id}")
            return existing_draft
        else:
            # user_id 검증 및 fallback 처리
            creator_uuid = await self._get_valid_creator_uuid(bot_id, user_id)

            # 스키마 추출
            input_schema, output_schema = self._extract_schemas_from_graph(graph)

            # 신규 생성
            draft = BotWorkflowVersion(
                bot_id=bot_id,
                version="draft",
                status=WorkflowVersionStatus.DRAFT.value,
                graph=graph,
                environment_variables=environment_variables,
                conversation_variables=conversation_variables,
                input_schema=input_schema,
                output_schema=output_schema,
                created_by=creator_uuid
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
        user_id: str,
        library_metadata: Optional[Dict[str, Any]] = None
    ) -> BotWorkflowVersion:
        """
        Draft를 발행하여 published 버전으로 전환

        Args:
            bot_id: 봇 ID
            version_id: 버전 ID
            user_id: 사용자 ID
            library_metadata: 라이브러리 메타데이터 (선택)

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
        last_version = result.scalars().first()

        # 새 버전 번호 생성
        if last_version:
            # v1.1 → v1.2
            version_parts = last_version.version.lstrip('v').split('.')
            new_version = f"v{version_parts[0]}.{int(version_parts[1]) + 1}"
        else:
            new_version = "v1.0"

        # Bot 조회 (이름 가져오기 및 use_workflow_v2 활성화)
        stmt = select(Bot).where(Bot.bot_id == bot_id)
        result = await self.db.execute(stmt)
        bot = result.scalars().first()

        if not bot:
            raise ValueError("봇을 찾을 수 없습니다")

        # Draft를 Published로 변경
        draft.version = new_version
        draft.status = WorkflowVersionStatus.PUBLISHED.value
        draft.published_at = datetime.now()

        # 라이브러리 메타데이터 설정 (제공된 경우)
        if library_metadata:
            # library_name이 제공되지 않으면 봇 이름 사용
            draft.library_name = library_metadata.get("library_name") or bot.name
            draft.library_description = library_metadata.get("library_description")
            draft.library_category = library_metadata.get("library_category")
            draft.library_tags = library_metadata.get("library_tags")
            # library_visibility는 더 이상 사용하지 않음 (기본값 "private"로 설정)
            draft.library_visibility = "private"
            draft.is_in_library = True
            draft.library_published_at = datetime.now()
            logger.info(f"Added workflow {new_version} to library: {draft.library_name}")

        # 그래프 통계 및 스키마 계산
        if draft.graph:
            nodes = draft.graph.get("nodes", [])
            edges = draft.graph.get("edges", [])
            draft.node_count = len(nodes)
            draft.edge_count = len(edges)

            # 스키마 추출 (draft 생성 시 누락되었을 경우를 위해)
            if not draft.input_schema or not draft.output_schema:
                input_schema, output_schema = self._extract_schemas_from_graph(draft.graph)
                draft.input_schema = input_schema
                draft.output_schema = output_schema
                logger.info(f"Extracted schemas during publish: input={len(input_schema or [])}, output={len(output_schema or [])}")

            logger.info(f"Workflow statistics: {draft.node_count} nodes, {draft.edge_count} edges")

        # Bot의 use_workflow_v2 활성화
        bot.use_workflow_v2 = True
        logger.info(f"Enabled workflow V2 for bot {bot_id}")

        await self.db.commit()
        await self.db.refresh(draft)

        # user_id 검증 및 fallback 처리
        creator_uuid = await self._get_valid_creator_uuid(bot_id, user_id)

        # 새 빈 draft 생성
        new_draft = BotWorkflowVersion(
            bot_id=bot_id,
            version="draft",
            status=WorkflowVersionStatus.DRAFT.value,
            graph=draft.graph,  # 기존 그래프 복사
            environment_variables=draft.environment_variables,
            conversation_variables=draft.conversation_variables,
            features=draft.features,  # features 필드도 복사
            input_schema=draft.input_schema,  # 스키마 복사
            output_schema=draft.output_schema,
            created_by=creator_uuid
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
        stmt = (
            select(BotWorkflowVersion)
            .where(
                and_(
                    BotWorkflowVersion.bot_id == bot_id,
                    BotWorkflowVersion.status == WorkflowVersionStatus.PUBLISHED.value
                )
            )
            .order_by(BotWorkflowVersion.published_at.desc())
            .limit(1)
        )

        result = await self.db.execute(stmt)
        return result.scalars().first()

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

    async def _get_valid_creator_uuid(self, bot_id: str, user_id: str) -> str:
        """
        유효한 creator UUID 반환 (fallback 포함)
        
        Args:
            bot_id: 봇 ID
            user_id: 사용자 UUID (검증 필요)
            
        Returns:
            str: 유효한 사용자 UUID
            
        Raises:
            ValueError: 유효한 creator를 찾을 수 없는 경우
        """
        # 1. 제공된 user_id가 유효한 UUID인지 확인
        stmt = select(User).where(User.uuid == user_id)
        result = await self.db.execute(stmt)
        user = result.scalar_one_or_none()
        
        if user:
            return user.uuid
        
        # 2. fallback: 봇의 creator UUID 사용
        logger.warning(f"User UUID {user_id} not found, falling back to bot creator")
        stmt = select(Bot).where(Bot.bot_id == bot_id)
        result = await self.db.execute(stmt)
        bot = result.scalars().first()
        
        if not bot:
            raise ValueError(f"Bot {bot_id} not found")
        
        # Bot의 user 관계를 통해 creator UUID 가져오기
        stmt = select(User).where(User.id == bot.user_id)
        result = await self.db.execute(stmt)
        bot_creator = result.scalar_one_or_none()
        
        if not bot_creator:
            raise ValueError(f"Bot creator not found for bot {bot_id}")
        
        logger.info(f"Using bot creator UUID {bot_creator.uuid} for workflow version")
        return bot_creator.uuid

    def _extract_schemas_from_graph(
        self,
        graph: Dict[str, Any]
    ) -> tuple[Optional[List[Dict[str, Any]]], Optional[List[Dict[str, Any]]]]:
        """
        워크플로우 그래프에서 입출력 스키마 추출

        Start 노드의 출력 포트를 input_schema로 사용
        End 노드의 입력 포트를 output_schema로 사용

        Args:
            graph: 워크플로우 그래프 (nodes, edges)

        Returns:
            tuple: (input_schema, output_schema) - 각각 PortDefinition 딕셔너리 리스트
        """
        if not graph or "nodes" not in graph:
            logger.warning("Graph is empty or missing 'nodes' field, cannot extract schemas")
            return None, None

        nodes = graph.get("nodes", [])
        if not nodes:
            logger.warning("Graph has no nodes, cannot extract schemas")
            return None, None

        input_schema = None
        output_schema = None
        has_start_node = False
        has_end_node = False

        for node in nodes:
            node_type = node.get("type")
            node_ports = node.get("ports", {})  # V2 구조: node.ports

            # Start 노드: 출력 포트를 input_schema로 사용
            if node_type == "start":
                has_start_node = True
                outputs = node_ports.get("outputs", [])
                if outputs:
                    input_schema = [self._port_to_dict(port) for port in outputs]
                    logger.debug(f"Extracted input_schema from Start node: {len(outputs)} ports")
                else:
                    logger.warning("Start node found but has no output ports")

            # End 노드: 입력 포트를 output_schema로 사용
            elif node_type == "end":
                has_end_node = True
                inputs = node_ports.get("inputs", [])
                if inputs:
                    output_schema = [self._port_to_dict(port) for port in inputs]
                    logger.debug(f"Extracted output_schema from End node: {len(inputs)} ports")
                else:
                    logger.warning("End node found but has no input ports")

        # Start/End 노드 누락 경고
        if not has_start_node:
            logger.warning("Workflow graph missing Start node, input_schema will be None")
        if not has_end_node:
            logger.warning("Workflow graph missing End node, output_schema will be None")

        return input_schema, output_schema

    def _port_to_dict(self, port: Any) -> Dict[str, Any]:
        """
        포트 정의를 딕셔너리로 변환

        Args:
            port: PortDefinition 객체 또는 딕셔너리

        Returns:
            Dict[str, Any]: 포트 정의 딕셔너리
        """
        if isinstance(port, dict):
            return port
        elif hasattr(port, "dict"):
            return port.dict()
        elif hasattr(port, "model_dump"):
            return port.model_dump()
        else:
            # 기본적인 속성만 추출
            return {
                "name": getattr(port, "name", ""),
                "type": getattr(port, "type", "any"),
                "required": getattr(port, "required", False),
                "description": getattr(port, "description", ""),
                "display_name": getattr(port, "display_name", getattr(port, "name", ""))
            }

    async def migrate_legacy_schemas(
        self,
        bot_id: Optional[str] = None,
        dry_run: bool = True
    ) -> Dict[str, Any]:
        """
        레거시 워크플로우 버전의 스키마 마이그레이션

        기존 published 버전의 NULL 또는 dict 스키마를 그래프에서 재추출하여 업데이트합니다.

        Args:
            bot_id: 특정 봇의 버전만 마이그레이션 (None이면 전체)
            dry_run: True이면 실제 업데이트 없이 결과만 반환

        Returns:
            Dict[str, Any]: 마이그레이션 결과 통계
        """
        logger.info(f"Starting schema migration (dry_run={dry_run}, bot_id={bot_id})")

        # 마이그레이션 대상 조회
        stmt = select(BotWorkflowVersion).where(
            BotWorkflowVersion.status == WorkflowVersionStatus.PUBLISHED.value
        )
        if bot_id:
            stmt = stmt.where(BotWorkflowVersion.bot_id == bot_id)

        result = await self.db.execute(stmt)
        versions = result.scalars().all()

        stats = {
            "total_versions": len(versions),
            "migrated": 0,
            "skipped": 0,
            "errors": 0,
            "details": []
        }

        for version in versions:
            try:
                # 스키마가 이미 배열이면 스킵
                if (isinstance(version.input_schema, list) and
                    isinstance(version.output_schema, list)):
                    stats["skipped"] += 1
                    stats["details"].append({
                        "version_id": str(version.id),
                        "bot_id": version.bot_id,
                        "version": version.version,
                        "status": "skipped",
                        "reason": "schemas already migrated"
                    })
                    continue

                # 그래프에서 스키마 재추출
                input_schema, output_schema = self._extract_schemas_from_graph(version.graph)

                if not dry_run:
                    version.input_schema = input_schema
                    version.output_schema = output_schema
                    version.updated_at = datetime.now()

                stats["migrated"] += 1
                stats["details"].append({
                    "version_id": str(version.id),
                    "bot_id": version.bot_id,
                    "version": version.version,
                    "status": "migrated",
                    "input_ports": len(input_schema) if input_schema else 0,
                    "output_ports": len(output_schema) if output_schema else 0
                })

                logger.info(f"Migrated schemas for version {version.version} (bot: {version.bot_id})")

            except Exception as e:
                stats["errors"] += 1
                stats["details"].append({
                    "version_id": str(version.id),
                    "bot_id": version.bot_id,
                    "version": version.version,
                    "status": "error",
                    "error": str(e)
                })
                logger.error(f"Failed to migrate version {version.id}: {e}")

        if not dry_run:
            await self.db.commit()
            logger.info(f"Schema migration completed: {stats['migrated']} migrated, {stats['errors']} errors")
        else:
            logger.info(f"Schema migration dry-run completed: {stats['migrated']} would be migrated")

        return stats
