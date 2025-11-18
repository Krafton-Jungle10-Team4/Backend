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
        user: User,
        graph_data: Optional[Dict[str, Any]] = None
    ) -> ExportValidation:
        """Export 검증

        Args:
            db: 데이터베이스 세션
            workflow_id: 워크플로우 ID
            version_id: 워크플로우 버전 ID
            user: 현재 사용자
            graph_data: 검증할 그래프 데이터 (없으면 DB에서 조회)

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

        # 그래프 검증 (전달받은 graph_data 우선 사용, 없으면 DB 조회)
        if graph_data:
            logger.info(f"[validate_export] Using provided graph_data from client: nodes={len(graph_data.get('nodes', []))}, edges={len(graph_data.get('edges', []))}")
            graph = graph_data
        else:
            logger.info("[validate_export] No graph_data provided, using DB version")
            graph = version.graph or {}

        nodes = graph.get("nodes", [])
        edges = graph.get("edges", [])

        validation.node_count = len(nodes)
        validation.edge_count = len(edges)

        logger.info(f"[validate_export] Validating workflow graph: workflow_id={workflow_id}, version_id={version_id}, node_count={len(nodes)}, edge_count={len(edges)}")

        # 1. 각 노드의 구조 검증 (NEW!)
        logger.info("[validate_export] Validating node structures...")
        for idx, node in enumerate(nodes):
            node_id = node.get("id")
            node_errors = []

            # 필수 필드 확인
            if not node_id:
                node_errors.append("ID 누락")
                validation.errors.append(f"노드 #{idx}에 ID가 없습니다")

            position = node.get("position")
            if not position or not isinstance(position, dict):
                node_errors.append("position 누락 또는 잘못된 형식")
                validation.errors.append(f"노드 {node_id or f'#{idx}'}에 position이 없거나 잘못되었습니다")
            else:
                if not isinstance(position.get("x"), (int, float)):
                    node_errors.append("position.x가 숫자가 아님")
                    validation.errors.append(f"노드 {node_id}의 position.x가 숫자가 아닙니다")
                if not isinstance(position.get("y"), (int, float)):
                    node_errors.append("position.y가 숫자가 아님")
                    validation.errors.append(f"노드 {node_id}의 position.y가 숫자가 아닙니다")

            data = node.get("data")
            if not data or not isinstance(data, dict):
                node_errors.append("data 누락 또는 잘못된 형식")
                validation.errors.append(f"노드 {node_id or f'#{idx}'}에 data가 없거나 잘못되었습니다")
            elif not data.get("type"):
                node_errors.append("data.type 누락")
                validation.errors.append(f"노드 {node_id}의 data.type이 없습니다")

            if node_errors:
                logger.error(f"[validate_export] Invalid node structure: node_id={node_id or f'#{idx}'}, errors={node_errors}, node={node}")

        # 2. 중복 노드 ID 검증 (NEW!)
        node_ids = [n.get("id") for n in nodes if n.get("id")]
        if len(node_ids) != len(set(node_ids)):
            duplicates = [nid for nid in node_ids if node_ids.count(nid) > 1]
            validation.errors.append("중복된 노드 ID가 존재합니다")
            logger.error(f"[validate_export] Duplicate node IDs detected: total={len(node_ids)}, unique={len(set(node_ids))}, duplicates={set(duplicates)}")

        # 3. 엣지의 source/target 유효성 검증 (NEW!)
        logger.info("[validate_export] Validating edge references...")
        node_id_set = set(node_ids)
        for idx, edge in enumerate(edges):
            edge_id = edge.get("id", f"#{idx}")
            source = edge.get("source")
            target = edge.get("target")

            if not source:
                validation.errors.append(f"엣지 {edge_id}에 source가 없습니다")
                logger.error(f"[validate_export] Edge missing source: edge={edge}")
            elif source not in node_id_set:
                validation.errors.append(f"엣지 {edge_id}의 source '{source}'가 존재하지 않습니다")
                logger.error(f"[validate_export] Edge source not found: edge_id={edge_id}, source={source}, available_nodes={list(node_id_set)[:10]}")

            if not target:
                validation.errors.append(f"엣지 {edge_id}에 target이 없습니다")
                logger.error(f"[validate_export] Edge missing target: edge={edge}")
            elif target not in node_id_set:
                validation.errors.append(f"엣지 {edge_id}의 target '{target}'가 존재하지 않습니다")
                logger.error(f"[validate_export] Edge target not found: edge_id={edge_id}, target={target}, available_nodes={list(node_id_set)[:10]}")

        # 4. imported-workflow 노드 거부 (중첩 방지) (NEW!)
        imported_workflow_nodes = [
            n for n in nodes
            if n.get("data", {}).get("type") == "imported-workflow"
        ]
        if imported_workflow_nodes:
            validation.errors.append(
                "템플릿은 다른 템플릿(ImportedWorkflow)을 포함할 수 없습니다. "
                "템플릿을 중첩하려면 먼저 내부 워크플로우를 별도의 템플릿으로 만들어주세요."
            )
            logger.error(f"[validate_export] Nested template detected: workflow_id={workflow_id}, imported_nodes={[{'id': n.get('id'), 'template_id': n.get('data', {}).get('template_id')} for n in imported_workflow_nodes]}")

        def _extract_ports(node_data: Dict[str, Any], key: str) -> List[Dict[str, Any]]:
            """노드 딕셔너리에서 포트 목록 추출 (신규/레거시 구조 모두 지원)"""
            ports: List[Dict[str, Any]] = []

            def _extend(raw_ports):
                if not raw_ports:
                    return
                if isinstance(raw_ports, list):
                    for port in raw_ports:
                        if isinstance(port, dict):
                            ports.append(port)
                elif isinstance(raw_ports, dict):
                    for name, port in raw_ports.items():
                        if isinstance(port, dict):
                            normalized = dict(port)
                            normalized.setdefault("name", name)
                            ports.append(normalized)

            node_ports = node_data.get("ports")
            if isinstance(node_ports, dict):
                _extend(node_ports.get(key))

            data_section = node_data.get("data")
            if isinstance(data_section, dict):
                data_ports = data_section.get("ports")
                if isinstance(data_ports, dict):
                    _extend(data_ports.get(key))
                _extend(data_section.get(key))

            return ports

        def _append_port_definitions(
            target_list: List[PortDefinition],
            ports: List[Dict[str, Any]]
        ) -> None:
            """추출된 포트 정보로 PortDefinition 생성"""
            for port in ports:
                name = port.get("name") or port.get("id")
                if not name:
                    continue

                display_name = port.get("display_name") or port.get("label") or name
                description = port.get("description") or port.get("desc") or ""
                required = port.get("required")
                if required is None:
                    required = True

                try:
                    target_list.append(
                        PortDefinition(
                            name=name,
                            type=str(port.get("type") or "any"),
                            required=bool(required),
                            description=description,
                            display_name=display_name
                        )
                    )
                except Exception as port_error:
                    logger.warning(
                        "[validate_export] Failed to parse port definition %s: %s",
                        port,
                        port_error
                    )

        # 5. Start/End 노드 확인 (기존 로직)
        for node in nodes:
            node_type = node.get("data", {}).get("type")
            if node_type == "start":
                validation.has_start_node = True
                # Start 노드의 출력 포트 추출
                start_outputs = _extract_ports(node, "outputs")
                if start_outputs:
                    _append_port_definitions(validation.detected_input_ports, start_outputs)
                else:
                    logger.warning(
                        "[validate_export] Start node %s has no output ports",
                        node.get("id")
                    )
            elif node_type in ["end", "answer"]:
                validation.has_end_node = True
                # End/Answer 노드의 입력 포트 추출
                end_inputs = _extract_ports(node, "inputs")
                if end_inputs:
                    _append_port_definitions(validation.detected_output_ports, end_inputs)
                else:
                    logger.warning(
                        "[validate_export] %s node %s has no input ports",
                        node_type,
                        node.get("id")
                    )

        # 검증 결과
        if not validation.has_start_node:
            validation.errors.append("Start 노드가 없습니다")
            logger.error("[validate_export] Missing start node")
        if not validation.has_end_node:
            validation.errors.append("End 또는 Answer 노드가 없습니다")
            logger.error("[validate_export] Missing end/answer node")

        # 노드 개수 제한
        if len(nodes) > 100:
            validation.errors.append("노드 개수가 100개를 초과합니다")
            logger.error(f"[validate_export] Too many nodes: current={len(nodes)}, max=100")
        if len(nodes) == 0:
            validation.errors.append("노드가 하나도 없습니다")
            logger.error("[validate_export] No nodes found")

        validation.is_valid = len(validation.errors) == 0

        logger.info(f"[validate_export] Validation completed: is_valid={validation.is_valid}, error_count={len(validation.errors)}, warning_count={len(validation.warnings)}")
        if not validation.is_valid:
            logger.error(f"[validate_export] Validation failed: errors={validation.errors}")
        if validation.warnings:
            logger.warning(f"[validate_export] Validation warnings: warnings={validation.warnings}")

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
