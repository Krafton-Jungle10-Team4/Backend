"""Imported Workflow 노드 구현"""
import logging
import json
from typing import Dict, Any, Optional, List
from datetime import datetime

from app.core.workflow.base_node_v2 import BaseNodeV2, NodeExecutionContext
from app.schemas.workflow import NodePortSchema, PortDefinition, PortType
from app.services.template_service import TemplateService
from app.core.workflow.executor_v2 import WorkflowExecutorV2
from app.core.workflow.variable_pool import VariablePool
from app.schemas.template import TemplateUsageCreate

logger = logging.getLogger(__name__)


class ImportedWorkflowNode(BaseNodeV2):
    """Imported Workflow 노드 - 템플릿을 실행

    템플릿으로 저장된 워크플로우를 현재 워크플로우 내에서 실행합니다.
    입력 변수를 템플릿의 입력 포트에 매핑하고, 템플릿 실행 결과를 출력 포트로 반환합니다.
    """

    def get_port_schema(self) -> NodePortSchema:
        """
        포트 스키마 정의

        템플릿의 input_schema와 output_schema를 기반으로 동적으로 생성됩니다.
        config에 ports가 있으면 사용하고, 없으면 기본 스키마를 반환합니다.

        Returns:
            NodePortSchema: 입력/출력 포트 스키마
        """
        # 기본 스키마 (fallback)
        default_inputs = [
            PortDefinition(
                name="input",
                type=PortType.ANY,
                required=False,
                description="템플릿 입력 데이터",
                display_name="입력"
            )
        ]

        default_outputs = [
            PortDefinition(
                name="output",
                type=PortType.ANY,
                required=False,
                description="템플릿 출력 데이터",
                display_name="출력"
            )
        ]

        def _safe_parse_ports(port_list):
            parsed = []
            for port in port_list or []:
                try:
                    parsed.append(PortDefinition.model_validate(port))
                except Exception as e:
                    logger.warning(f"Failed to parse port definition {port}: {e}")
                    name = port.get("name") if isinstance(port, dict) else None
                    if name:
                        parsed.append(PortDefinition(
                            name=name,
                            type=PortType.ANY,
                            required=port.get("required", False) if isinstance(port, dict) else False,
                            description=port.get("description", "") if isinstance(port, dict) else "",
                            display_name=port.get("display_name", name) if isinstance(port, dict) else name
                        ))
            return parsed

        try:
            # config에서 ports 또는 input_schema/output_schema 읽기
            ports = self.config.get("ports")

            if ports:
                # ports 형태: {"inputs": [...], "outputs": [...]}
                input_defs = _safe_parse_ports(ports.get("inputs"))
                output_defs = _safe_parse_ports(ports.get("outputs"))

                if input_defs or output_defs:
                    return NodePortSchema(
                        inputs=input_defs or default_inputs,
                        outputs=output_defs or default_outputs
                    )

            # input_schema/output_schema 직접 읽기
            input_schema = _safe_parse_ports(self.config.get("input_schema", []))
            output_schema = _safe_parse_ports(self.config.get("output_schema", []))

            if input_schema or output_schema:
                return NodePortSchema(
                    inputs=input_schema or default_inputs,
                    outputs=output_schema or default_outputs
                )

        except Exception as e:
            logger.error(f"Error parsing port schema from config: {e}")

        # Fallback: 기본 스키마 반환
        return NodePortSchema(
            inputs=default_inputs,
            outputs=default_outputs
        )

    async def execute_v2(self, context: NodeExecutionContext) -> Dict[str, Any]:
        """노드 실행

        Args:
            context: 실행 컨텍스트

        Returns:
            Dict[str, Any]: 출력 포트 값들

        Raises:
            ValueError: template_id가 설정되지 않은 경우
            RuntimeError: 템플릿 실행 실패 시
        """
        config = self.config
        template_id = config.get("template_id")

        # 수정: self.variable_mappings 사용
        variable_mappings = self.variable_mappings or {}

        if not template_id:
            raise ValueError("template_id가 설정되지 않았습니다")

        logger.info(f"Imported Workflow 실행 시작: {template_id}")

        try:
            # 템플릿 로드
            template = await self._load_template(template_id, context)

            # 입력 변수 매핑
            internal_inputs = self._map_input_variables(
                context.variable_pool,
                variable_mappings,
                template.get("input_schema", [])
            )

            logger.info(f"Mapped internal inputs: {list(internal_inputs.keys())}")

            # 템플릿 워크플로우 실행을 위한 파라미터 준비
            db = context.get_service("db_session")
            vector_service = context.get_service("vector_service")
            llm_service = context.get_service("llm_service")
            bot_id = context.get_service("bot_id")
            session_id = context.get_service("session_id")

            # 템플릿의 워크플로우 데이터 구성
            # 수정: internal_inputs를 environment_variables로 전달
            initial_node_outputs = {
                "template_input": internal_inputs
            }

            workflow_data = {
                "nodes": template["graph"]["nodes"],
                "edges": template["graph"]["edges"],
                "environment_variables": {},
                "conversation_variables": {}
            }

            # user_message는 sys.user_message에서 가져오거나 기본값
            user_message = context.variable_pool.get_system_variable("user_message") or ""

            # Child executor 생성
            child_executor = WorkflowExecutorV2()

            result = await child_executor.execute(
                workflow_data=workflow_data,
                session_id=session_id or f"nested_{self.node_id}",
                user_message=user_message,
                bot_id=bot_id or "",
                db=db,
                vector_service=vector_service,
                llm_service=llm_service,
                stream_handler=None,
                text_normalizer=None,
                initial_node_outputs=initial_node_outputs
            )

            # 출력 변수 매핑
            output_schema = template.get("output_schema", [])
            outputs = self._map_output_variables(
                {"result": result},  # 실행 결과를 result로 래핑
                output_schema,
                variable_mappings
            )

            # 실행 기록
            await self._record_execution(template_id, context)

            logger.info(f"Imported Workflow 실행 완료: {template_id}")

            return {
                "status": "success",
                "output": result,
                **outputs
            }

        except Exception as e:
            logger.error(f"Imported Workflow 실행 실패: {e}", exc_info=True)
            raise RuntimeError(f"Imported Workflow 실행 실패: {e}") from e

    async def _load_template(
        self,
        template_id: str,
        context: NodeExecutionContext
    ) -> Dict[str, Any]:
        """템플릿 로드

        Args:
            template_id: 템플릿 ID
            context: 실행 컨텍스트

        Returns:
            Dict[str, Any]: 템플릿 데이터

        Raises:
            NotFoundException: 템플릿을 찾을 수 없는 경우
        """
        # DB에서 템플릿 조회
        db = context.get_service("db_session")

        if not db:
            raise RuntimeError("DB 세션을 찾을 수 없습니다")

        # user는 service_container에 없을 수 있으므로 기본값 처리
        user = context.get_service("user")

        # TemplateService를 통해 템플릿 조회
        template_service = TemplateService()

        if user:
            template = await template_service.get_template(db, template_id, user)
        else:
            # 권한 검증 없이 템플릿 조회 (봇 실행 컨텍스트)
            from sqlalchemy import select
            from app.models.template import Template

            result = await db.execute(
                select(Template).where(Template.id == template_id)
            )
            template = result.scalar_one_or_none()

            if not template:
                raise ValueError(f"템플릿을 찾을 수 없습니다: {template_id}")

        return {
            "id": template.id,
            "name": template.name,
            "graph": template.graph,
            "input_schema": template.input_schema,
            "output_schema": template.output_schema
        }

    @staticmethod
    def _extract_selector(mapping: Any) -> Optional[str]:
        """
        매핑에서 selector 문자열 추출

        Args:
            mapping: 매핑 데이터 (문자열 또는 dict)

        Returns:
            Optional[str]: selector 문자열 또는 None

        Examples:
            >>> _extract_selector("start-1.query")
            "start-1.query"
            >>> _extract_selector({"variable": "start-1.query"})
            "start-1.query"
            >>> _extract_selector({"source": {"variable": "start-1.query"}})
            "start-1.query"
        """
        if isinstance(mapping, str):
            return mapping
        elif isinstance(mapping, dict):
            # {"variable": "..."} 형태
            if "variable" in mapping:
                return mapping["variable"]
            # {"source": {"variable": "..."}} 형태
            if "source" in mapping and isinstance(mapping["source"], dict):
                return mapping["source"].get("variable")
        return None

    def _map_input_variables(
        self,
        parent_pool: VariablePool,
        mappings: Dict[str, Any],
        input_schema: List[Dict]
    ) -> Dict[str, Any]:
        """입력 변수 매핑

        Args:
            parent_pool: 부모 변수 풀
            mappings: 변수 매핑 설정 (self.variable_mappings)
            input_schema: 입력 포트 스키마

        Returns:
            Dict[str, Any]: 매핑된 입력 변수들
        """
        internal_inputs = {}

        # 스키마에 정의된 입력 포트별로 매핑
        for port_def in input_schema:
            port_name = port_def.get("name")

            # mappings에서 이 포트의 매핑 정보 찾기
            mapping = mappings.get(port_name)

            if mapping:
                # selector 추출
                selector = self._extract_selector(mapping)

                if selector:
                    # 부모 컨텍스트에서 변수 가져오기
                    value = parent_pool.resolve_value_selector(selector)

                    # 기본값 처리
                    if value is None and "default_value" in port_def:
                        value = port_def["default_value"]

                    # Required 체크
                    if value is None and port_def.get("required", True):
                        logger.warning(f"필수 입력 변수 누락: {port_name}")

                    internal_inputs[port_name] = value
                    logger.debug(f"Mapped input {port_name}: {selector} -> {type(value).__name__}")
                else:
                    logger.warning(f"Could not extract selector from mapping for port {port_name}")
            else:
                # 매핑이 없으면 기본값 사용
                if "default_value" in port_def:
                    internal_inputs[port_name] = port_def["default_value"]
                    logger.debug(f"Using default value for port {port_name}")

        return internal_inputs

    def _map_output_variables(
        self,
        internal_outputs: Dict[str, Any],
        output_schema: List[Dict],
        mappings: Dict[str, Any]
    ) -> Dict[str, Any]:
        """출력 변수 매핑

        Args:
            internal_outputs: 템플릿 실행 결과
            output_schema: 출력 포트 정의
            mappings: 변수 매핑 설정

        Returns:
            Dict[str, Any]: 매핑된 출력 변수들
        """
        external_outputs = {}

        for port_def in output_schema:
            port_name = port_def.get("name")

            # internal_outputs에서 값 찾기
            value = None

            # 여러 키 형태 시도
            for key in [port_name, f"template_{port_name}", "result"]:
                if key in internal_outputs:
                    value = internal_outputs[key]
                    break

            if value is not None:
                # mappings에서 외부 이름 찾기 (있으면 사용, 없으면 port_name 그대로)
                mapping = mappings.get(port_name)
                external_name = port_name

                if mapping:
                    # 출력 매핑은 보통 간단한 문자열
                    if isinstance(mapping, str):
                        external_name = mapping
                    elif isinstance(mapping, dict):
                        external_name = mapping.get("target", port_name)

                external_outputs[external_name] = value
                logger.debug(f"Mapped output {port_name} -> {external_name}")

        return external_outputs

    async def _record_execution(
        self,
        template_id: str,
        context: NodeExecutionContext
    ):
        """실행 기록

        Args:
            template_id: 템플릿 ID
            context: 실행 컨텍스트
        """
        try:
            db = context.get_service("db_session")
            user = context.get_service("user")
            bot_id = context.get_service("bot_id")

            if not db:
                logger.warning("DB 세션이 없어 실행 기록을 저장하지 않습니다")
                return

            # user가 없으면 실행 기록 생략 (봇 실행 컨텍스트)
            if not user:
                logger.debug("사용자 정보가 없어 템플릿 사용 기록을 생략합니다")
                return

            template_service = TemplateService()

            # 수정: event_type="execution" (API 명세 준수)
            usage = TemplateUsageCreate(
                workflow_id=bot_id or "",
                workflow_version_id=None,
                node_id=self.node_id,
                event_type="execution",  # imported | execution
                note=f"Nested execution in node {self.node_id}"
            )

            await template_service.create_usage_record(
                db=db,
                template_id=template_id,
                usage=usage,
                user=user
            )

            logger.info(f"템플릿 사용 기록 저장: {template_id} (event_type=execution)")

        except Exception as e:
            logger.error(f"실행 기록 실패: {e}")

    def validate(self) -> tuple[bool, Optional[str]]:
        """
        노드 설정 검증

        Returns:
            tuple: (유효 여부, 오류 메시지)
        """
        # template_id 필수 체크
        template_id = self.config.get("template_id")
        if not template_id:
            return False, "template_id가 설정되지 않았습니다"

        # 기본 포트 스키마 검증
        return super().validate()

    def get_required_services(self) -> List[str]:
        """
        노드 실행에 필요한 서비스 목록

        Returns:
            List[str]: 서비스 이름 리스트
        """
        return [
            "db_session",
            "vector_service",
            "llm_service",
            "bot_id",
            "session_id"
        ]
