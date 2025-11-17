"""템플릿 관련 서비스 로직"""
import uuid
import json
import logging
from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, func
from sqlalchemy.orm import selectinload

from app.models.template import Template, TemplateUsage
from app.models.bot import Bot
from app.models.workflow_version import BotWorkflowVersion
from app.models.user import User
from app.schemas.template import (
    WorkflowTemplate, ExportConfig, ExportValidation,
    ImportValidation, PortDefinition, TemplateGraph,
    Author, TemplateMetadata, TemplateUsageCreate
)
from app.core.exceptions import (
    NotFoundException, ValidationException,
    PermissionDeniedException, DuplicateException
)

logger = logging.getLogger(__name__)


class TemplateService:
    """템플릿 서비스"""

    @staticmethod
    async def list_templates(
        db: AsyncSession,
        user: User,
        visibility: Optional[str] = None,
        category: Optional[str] = None,
        search: Optional[str] = None,
        tags: Optional[List[str]] = None,
        author_id: Optional[str] = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
        skip: int = 0,
        limit: int = 20
    ) -> Tuple[List[Template], int]:
        """템플릿 목록 조회

        Args:
            db: 데이터베이스 세션
            user: 현재 사용자
            visibility: 가시성 필터 (private, team, public)
            category: 카테고리 필터
            search: 검색 쿼리
            tags: 태그 필터 (OR 조건)
            author_id: 작성자 ID
            sort_by: 정렬 기준
            sort_order: 정렬 순서 (asc, desc)
            skip: 건너뛸 개수
            limit: 조회 개수

        Returns:
            템플릿 목록과 전체 개수
        """
        query = select(Template).options(
            selectinload(Template.author)
        )

        # Visibility 필터
        if visibility:
            if visibility == "private":
                query = query.where(
                    and_(
                        Template.visibility == "private",
                        Template.author_id == user.uuid
                    )
                )
            elif visibility == "team":
                # 현재는 public 템플릿도 포함
                query = query.where(
                    or_(
                        Template.visibility == "public",
                        Template.author_id == user.uuid
                    )
                )
            else:  # public
                query = query.where(Template.visibility == "public")
        else:
            # 기본: 자신의 템플릿 + public 템플릿
            query = query.where(
                or_(
                    Template.author_id == user.uuid,
                    Template.visibility == "public"
                )
            )

        # 카테고리 필터
        if category:
            query = query.where(Template.category == category)

        # 검색
        if search:
            search_pattern = f"%{search}%"
            query = query.where(
                or_(
                    Template.name.ilike(search_pattern),
                    Template.description.ilike(search_pattern)
                )
            )

        # 태그 필터 (OR 조건)
        if tags:
            tag_conditions = []
            for tag in tags:
                # PostgreSQL JSON 연산자 사용
                tag_conditions.append(
                    Template.tags.op('@>')([tag])
                )
            query = query.where(or_(*tag_conditions))

        # 작성자 필터
        if author_id:
            query = query.where(Template.author_id == author_id)

        # 정렬
        order_column = getattr(Template, sort_by, Template.created_at)
        if sort_order == "desc":
            query = query.order_by(order_column.desc())
        else:
            query = query.order_by(order_column)

        # 전체 개수
        count_query = select(func.count()).select_from(query.subquery())
        total = await db.scalar(count_query)

        # 페이지네이션
        query = query.offset(skip).limit(limit)

        result = await db.execute(query)
        templates = result.scalars().all()

        return templates, total or 0

    @staticmethod
    async def get_template(
        db: AsyncSession,
        template_id: str,
        user: User
    ) -> Template:
        """템플릿 상세 조회

        Args:
            db: 데이터베이스 세션
            template_id: 템플릿 ID
            user: 현재 사용자

        Returns:
            템플릿 객체

        Raises:
            NotFoundException: 템플릿을 찾을 수 없음
            PermissionDeniedException: 접근 권한 없음
        """
        result = await db.execute(
            select(Template)
            .options(
                selectinload(Template.author),
                selectinload(Template.source_workflow),
                selectinload(Template.source_version)
            )
            .where(Template.id == template_id)
        )
        template = result.scalar_one_or_none()

        if not template:
            raise NotFoundException(f"템플릿을 찾을 수 없습니다: {template_id}")

        # 권한 확인
        if template.visibility == "private" and template.author_id != user.uuid:
            raise PermissionDeniedException("이 템플릿에 접근할 권한이 없습니다")

        return template

    @staticmethod
    async def validate_export(
        db: AsyncSession,
        workflow_id: str,
        version_id: str,
        user: User
    ) -> ExportValidation:
        """Export 검증

        Args:
            db: 데이터베이스 세션
            workflow_id: 워크플로우 ID
            version_id: 워크플로우 버전 ID
            user: 현재 사용자

        Returns:
            검증 결과
        """
        validation = ExportValidation(
            is_valid=False,
            has_published_version=False,
            has_start_node=False,
            has_end_node=False,
            detected_input_ports=[],
            detected_output_ports=[],
            errors=[],
            warnings=[]
        )

        # 워크플로우 조회
        result = await db.execute(
            select(Bot).where(Bot.bot_id == workflow_id)
        )
        bot = result.scalar_one_or_none()

        if not bot:
            validation.errors.append(f"워크플로우를 찾을 수 없습니다: {workflow_id}")
            return validation

        # 권한 확인
        if bot.user_id != user.id:
            validation.errors.append("이 워크플로우를 export할 권한이 없습니다")
            return validation

        # 버전 조회
        result = await db.execute(
            select(BotWorkflowVersion).where(
                and_(
                    BotWorkflowVersion.id == version_id,
                    BotWorkflowVersion.bot_id == workflow_id
                )
            )
        )
        version = result.scalar_one_or_none()

        if not version:
            validation.errors.append(f"워크플로우 버전을 찾을 수 없습니다: {version_id}")
            return validation

        # 발행 여부 확인
        if version.published_at:
            validation.has_published_version = True
        else:
            validation.warnings.append("발행되지 않은 버전입니다")

        # 그래프 검증
        graph = version.graph or {}
        nodes = graph.get("nodes", [])
        edges = graph.get("edges", [])

        validation.node_count = len(nodes)
        validation.edge_count = len(edges)

        # Start/End 노드 확인
        for node in nodes:
            node_type = node.get("data", {}).get("type")
            if node_type == "start":
                validation.has_start_node = True
                # Start 노드의 출력 포트 추출
                outputs = node.get("data", {}).get("outputs", {})
                for port_name, port_data in outputs.items():
                    validation.detected_input_ports.append(
                        PortDefinition(
                            name=port_name,
                            type=port_data.get("type", "any"),
                            required=True,
                            description=port_data.get("description"),
                            display_name=port_data.get("label", port_name)
                        )
                    )
            elif node_type in ["end", "answer"]:
                validation.has_end_node = True
                # End 노드의 입력 포트 추출
                inputs = node.get("data", {}).get("inputs", {})
                for port_name, port_data in inputs.items():
                    validation.detected_output_ports.append(
                        PortDefinition(
                            name=port_name,
                            type=port_data.get("type", "any"),
                            required=True,
                            description=port_data.get("description"),
                            display_name=port_data.get("label", port_name)
                        )
                    )

        # 검증 결과
        if not validation.has_start_node:
            validation.errors.append("Start 노드가 없습니다")
        if not validation.has_end_node:
            validation.errors.append("End 또는 Answer 노드가 없습니다")

        # 노드 개수 제한
        if len(nodes) > 100:
            validation.errors.append("노드 개수가 100개를 초과합니다")
        if len(nodes) == 0:
            validation.errors.append("노드가 하나도 없습니다")

        validation.is_valid = len(validation.errors) == 0

        return validation

    @staticmethod
    async def export_template(
        db: AsyncSession,
        config: ExportConfig,
        user: User
    ) -> Template:
        """워크플로우를 템플릿으로 Export

        Args:
            db: 데이터베이스 세션
            config: Export 설정
            user: 현재 사용자

        Returns:
            생성된 템플릿

        Raises:
            ValidationException: 검증 실패
            DuplicateException: 중복된 템플릿 이름
        """
        # 검증
        validation = await TemplateService.validate_export(
            db, config.workflow_id, config.version_id, user
        )

        if not validation.is_valid:
            raise ValidationException(
                "Export 검증 실패",
                details={"errors": validation.errors}
            )

        # 중복 확인
        existing = await db.execute(
            select(Template).where(
                and_(
                    Template.name == config.name,
                    Template.author_id == user.uuid
                )
            )
        )
        if existing.scalar_one_or_none():
            raise DuplicateException(f"동일한 이름의 템플릿이 이미 존재합니다: {config.name}")

        # 워크플로우 버전 조회
        result = await db.execute(
            select(BotWorkflowVersion).where(
                BotWorkflowVersion.id == config.version_id
            )
        )
        version = result.scalar_one_or_none()

        # 템플릿 ID 생성
        template_id = f"tpl_{uuid.uuid4().hex[:8]}"

        # 포트 스키마 결정
        input_schema = config.custom_input_schema or validation.detected_input_ports
        output_schema = config.custom_output_schema or validation.detected_output_ports

        # 템플릿 생성
        template = Template(
            id=template_id,
            name=config.name,
            description=config.description or "",
            category=config.category or "workflow",
            type="workflow",
            tags=config.tags,
            version="1.0.0",
            visibility=config.visibility,
            author_id=user.uuid,
            author_name=user.name or user.email,
            author_email=user.email,
            source_workflow_id=config.workflow_id,
            source_version_id=config.version_id,
            node_count=validation.node_count,
            edge_count=validation.edge_count,
            estimated_tokens=config.estimated_tokens,
            estimated_cost=config.estimated_cost,
            graph=version.graph,
            input_schema=[port.model_dump() for port in input_schema],
            output_schema=[port.model_dump() for port in output_schema],
            thumbnail_url=config.thumbnail_url
        )

        db.add(template)
        await db.commit()
        await db.refresh(template)

        logger.info(f"템플릿 생성됨: {template_id} by {user.email}")

        return template

    @staticmethod
    async def validate_import(
        db: AsyncSession,
        template_id: str,
        user: User
    ) -> ImportValidation:
        """Import 검증

        Args:
            db: 데이터베이스 세션
            template_id: 템플릿 ID
            user: 현재 사용자

        Returns:
            검증 결과
        """
        validation = ImportValidation(
            is_valid=False,
            is_compatible=True,
            missing_node_types=[],
            version_mismatch=False,
            can_upgrade=False,
            warnings=[],
            errors=[]
        )

        # 템플릿 조회
        template = await TemplateService.get_template(db, template_id, user)

        # 노드 타입 호환성 확인
        supported_node_types = [
            "start", "end", "answer", "llm", "knowledge",
            "knowledge-retrieval", "if-else", "code",
            "http-request", "template-transform"
        ]

        nodes = template.graph.get("nodes", [])
        for node in nodes:
            node_type = node.get("data", {}).get("type")
            if node_type and node_type not in supported_node_types:
                if node_type != "imported-workflow":  # imported-workflow는 특별 처리
                    validation.missing_node_types.append(node_type)

        if validation.missing_node_types:
            validation.is_compatible = False
            validation.errors.append(
                f"지원하지 않는 노드 타입: {', '.join(validation.missing_node_types)}"
            )

        # 버전 호환성 확인 (향후 구현)
        # ...

        validation.is_valid = len(validation.errors) == 0

        return validation

    @staticmethod
    async def create_usage_record(
        db: AsyncSession,
        template_id: str,
        usage: TemplateUsageCreate,
        user: User
    ) -> TemplateUsage:
        """템플릿 사용 기록 생성

        Args:
            db: 데이터베이스 세션
            template_id: 템플릿 ID
            usage: 사용 기록 데이터
            user: 현재 사용자

        Returns:
            생성된 사용 기록
        """
        # 템플릿 존재 확인
        template = await TemplateService.get_template(db, template_id, user)

        # 사용 기록 생성
        usage_record = TemplateUsage(
            template_id=template_id,
            workflow_id=usage.workflow_id,
            workflow_version_id=usage.workflow_version_id,
            node_id=usage.node_id,
            user_id=user.uuid,
            event_type=usage.event_type,
            note=usage.note
        )

        db.add(usage_record)
        await db.commit()
        await db.refresh(usage_record)

        logger.info(f"템플릿 사용 기록: {template_id} in {usage.workflow_id}")

        return usage_record

    @staticmethod
    async def delete_template(
        db: AsyncSession,
        template_id: str,
        user: User
    ) -> bool:
        """템플릿 삭제

        Args:
            db: 데이터베이스 세션
            template_id: 템플릿 ID
            user: 현재 사용자

        Returns:
            삭제 성공 여부

        Raises:
            NotFoundException: 템플릿을 찾을 수 없음
            PermissionDeniedException: 삭제 권한 없음
        """
        # 템플릿 조회
        result = await db.execute(
            select(Template).where(Template.id == template_id)
        )
        template = result.scalar_one_or_none()

        if not template:
            raise NotFoundException(f"템플릿을 찾을 수 없습니다: {template_id}")

        # 권한 확인
        if template.author_id != user.uuid:
            raise PermissionDeniedException("이 템플릿을 삭제할 권한이 없습니다")

        # 삭제
        await db.delete(template)
        await db.commit()

        logger.info(f"템플릿 삭제됨: {template_id} by {user.email}")

        return True

    @staticmethod
    async def update_template(
        db: AsyncSession,
        template_id: str,
        updates: Dict[str, Any],
        user: User
    ) -> Template:
        """템플릿 메타데이터 업데이트

        Args:
            db: 데이터베이스 세션
            template_id: 템플릿 ID
            updates: 업데이트할 필드
            user: 현재 사용자

        Returns:
            업데이트된 템플릿

        Raises:
            NotFoundException: 템플릿을 찾을 수 없음
            PermissionDeniedException: 수정 권한 없음
        """
        # 템플릿 조회
        result = await db.execute(
            select(Template).where(Template.id == template_id)
        )
        template = result.scalar_one_or_none()

        if not template:
            raise NotFoundException(f"템플릿을 찾을 수 없습니다: {template_id}")

        # 권한 확인
        if template.author_id != user.uuid:
            raise PermissionDeniedException("이 템플릿을 수정할 권한이 없습니다")

        # 수정 가능한 필드만 업데이트
        allowed_fields = ["name", "description", "category", "tags", "visibility", "thumbnail_url"]
        for field, value in updates.items():
            if field in allowed_fields:
                setattr(template, field, value)

        template.updated_at = datetime.now()

        await db.commit()
        await db.refresh(template)

        logger.info(f"템플릿 업데이트됨: {template_id} by {user.email}")

        return template
