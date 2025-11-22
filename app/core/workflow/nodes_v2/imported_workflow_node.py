"""Imported Workflow 노드 구현"""
import logging
import json
import re
from typing import Dict, Any, Optional, List
from datetime import datetime

from app.core.workflow.base_node_v2 import BaseNodeV2, NodeExecutionContext
from app.schemas.workflow import NodePortSchema, PortDefinition, PortType
from app.services.library_service import LibraryService
from app.core.workflow.executor_v2 import WorkflowExecutorV2
from app.core.workflow.variable_pool import VariablePool

logger = logging.getLogger(__name__)


class ImportedWorkflowNode(BaseNodeV2):
    """Imported Workflow 노드 - 라이브러리 에이전트를 실행

    라이브러리에 저장된 워크플로우를 현재 워크플로우 내에서 실행합니다.
    입력 변수를 라이브러리 에이전트의 입력 포트에 매핑하고, 실행 결과를 출력 포트로 반환합니다.
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
                description="라이브러리 에이전트 입력 데이터",
                display_name="입력"
            )
        ]

        default_outputs = [
            PortDefinition(
                name="output",
                type=PortType.ANY,
                required=False,
                description="라이브러리 에이전트 출력 데이터",
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
            ValueError: source_version_id가 설정되지 않은 경우
            RuntimeError: 라이브러리 에이전트 실행 실패 시
        """
        config = self.config
        source_version_id = config.get("source_version_id") or config.get("template_id")

        if not source_version_id:
            inferred_id = self._infer_version_id_from_node_id()
            if inferred_id:
                logger.warning(
                    "source_version_id missing for imported node %s, inferred %s from node_id",
                    self.node_id,
                    inferred_id
                )
                source_version_id = inferred_id
                self.config["source_version_id"] = inferred_id

        # 수정: self.variable_mappings 사용
        variable_mappings = self.variable_mappings or {}

        if not source_version_id:
            raise ValueError("source_version_id가 설정되지 않았습니다")

        logger.info(f"Imported Workflow 실행 시작: {source_version_id}")

        try:
            # 라이브러리 에이전트 로드
            agent_data = await self._load_library_agent(source_version_id, context)

            # 입력 변수 매핑
            internal_inputs = self._map_input_variables(
                context.variable_pool,
                variable_mappings,
                agent_data.get("input_schema", [])
            )

            logger.info(f"Mapped internal inputs: {list(internal_inputs.keys())}")

            start_node_id = agent_data.get("start_node_id")
            if not start_node_id:
                raise ValueError("라이브러리 에이전트에서 Start 노드를 찾을 수 없습니다")

            # 템플릿 워크플로우 실행을 위한 파라미터 준비
            db = context.get_service("db_session")
            vector_service = context.get_service("vector_service")
            llm_service = context.get_service("llm_service")
            bot_id = context.get_service("bot_id")
            session_id = context.get_service("session_id")

            # 라이브러리 에이전트의 워크플로우 데이터 구성
            initial_node_outputs = {
                start_node_id: internal_inputs
            }

            workflow_data = {
                "nodes": agent_data["graph"]["nodes"],
                "edges": agent_data["graph"]["edges"],
                "environment_variables": {},
                "conversation_variables": {}
            }

            # user_message는 sys.user_message에서 가져오거나 기본값
            user_message = context.variable_pool.get_system_variable("user_message") or ""

            # Child executor 생성
            child_executor = WorkflowExecutorV2()

            # ServiceContainer에서 user_uuid, API 메타데이터, 스트리밍 관련 조회
            user_uuid = context.service_container.get("user_uuid") if context.service_container else None
            api_key_id = context.service_container.get("api_key_id") if context.service_container else None
            user_id_from_parent = context.service_container.get("user_id") if context.service_container else None
            api_request_id = context.service_container.get("api_request_id") if context.service_container else None

            # 스트리밍 관련 서비스 조회 (부모로부터 전달받음)
            stream_handler = context.service_container.get("stream_handler") if context.service_container else None
            text_normalizer = context.service_container.get("text_normalizer") if context.service_container else None

            # user_uuid가 없으면 기본값 설정 (Widget 실행 등)
            if not user_uuid:
                logger.warning(f"user_uuid가 ServiceContainer에 없습니다. 빈 문자열로 설정합니다.")
                user_uuid = ""

            logger.debug(
                f"Nested workflow execution: user_uuid={user_uuid}, api_key_id={api_key_id}, user_id={user_id_from_parent}, stream_handler={stream_handler is not None}"
            )

            result = await child_executor.execute(
                workflow_data=workflow_data,
                session_id=session_id or f"nested_{self.node_id}",
                user_message=user_message,
                bot_id=bot_id or "",
                user_uuid=user_uuid,  # 필수 위치 인자 추가
                db=db,
                vector_service=vector_service,
                llm_service=llm_service,
                stream_handler=stream_handler,  # 부모의 stream_handler 전달
                text_normalizer=text_normalizer,  # 부모의 text_normalizer 전달
                initial_node_outputs=initial_node_outputs,
                # 중첩 워크플로우도 API 파라미터 전달 (부모로부터 상속)
                api_key_id=api_key_id,
                user_id=user_id_from_parent,
                api_request_id=api_request_id
            )

            # 출력 값 수집 및 매핑
            output_schema = agent_data.get("output_schema", [])
            output_mappings = agent_data.get("output_mappings", {})

            logger.info(f"Output schema: {output_schema}")
            logger.info(f"Output mappings: {output_mappings}")

            output_values = self._collect_output_values(
                agent_data=agent_data,
                child_executor=child_executor,
                output_schema=output_schema,
                default_value=result,
                output_mappings=output_mappings
            )

            logger.info(f"Collected output values: {output_values}")

            outputs = self._map_output_variables(output_values, output_schema)

            logger.info(f"Mapped outputs: {outputs}")

            # 실행 기록
            await self._record_execution(source_version_id, context)

            logger.info(f"Imported Workflow 실행 완료: {source_version_id}")
            logger.info(f"Final return value keys: {list(outputs.keys())}")

            # 하위 호환성을 위해 일반적인 포트 이름도 추가
            # 프론트엔드에서 text 포트로 연결할 수 있도록
            if outputs:
                # output_schema의 첫 번째 포트 값을 text로도 제공
                first_port_value = next(iter(outputs.values()), None)
                if first_port_value is not None and "text" not in outputs:
                    outputs["text"] = first_port_value
                    logger.info(f"하위 호환성을 위해 'text' 포트 추가")

            # status와 output은 내부 메타데이터이므로 VariablePool에 등록하지 않음
            # output_schema에 정의된 포트만 반환
            return outputs

        except Exception as e:
            logger.error(f"Imported Workflow 실행 실패: {e}", exc_info=True)
            raise RuntimeError(f"Imported Workflow 실행 실패: {e}") from e

    def _infer_version_id_from_node_id(self) -> Optional[str]:
        """노드 ID에서 버전 ID 추론 (레거시 데이터용)"""
        if not self.node_id:
            return None

        # 레거시 템플릿 ID 패턴 지원
        match = re.match(r"^imported_(tpl_[a-zA-Z0-9]+)_\d+", self.node_id)
        if match:
            return match.group(1)

        # 새 버전 ID 패턴 지원 (UUID)
        match = re.match(r"^imported_([a-f0-9-]{36})_\d+", self.node_id)
        if match:
            return match.group(1)

        return None

    async def _load_library_agent(
        self,
        source_version_id: str,
        context: NodeExecutionContext
    ) -> Dict[str, Any]:
        """라이브러리 에이전트 로드

        Args:
            source_version_id: 라이브러리 버전 ID (UUID)
            context: 실행 컨텍스트

        Returns:
            Dict[str, Any]: 라이브러리 에이전트 데이터

        Raises:
            ValueError: 라이브러리 에이전트를 찾을 수 없는 경우
        """
        # DB에서 라이브러리 에이전트 조회
        db = context.get_service("db_session")

        if not db:
            raise RuntimeError("DB 세션을 찾을 수 없습니다")

        # user는 service_container에 없을 수 있으므로 기본값 처리
        user = context.get_service("user")

        # LibraryService를 통해 라이브러리 에이전트 조회
        library_service = LibraryService(db)

        if user and hasattr(user, 'id'):
            # 권한 검증 포함 조회
            source_version = await library_service.get_library_agent_by_id(
                version_id=source_version_id,
                user_id=user.id
            )
        else:
            # 권한 검증 없이 조회 (봇 실행 컨텍스트)
            from sqlalchemy import select
            from app.models.workflow_version import BotWorkflowVersion

            result = await db.execute(
                select(BotWorkflowVersion).where(
                    BotWorkflowVersion.id == source_version_id
                )
            )
            source_version = result.scalar_one_or_none()

        if not source_version:
            raise ValueError(f"라이브러리 에이전트를 찾을 수 없습니다: {source_version_id}")

        graph = source_version.graph or {}
        nodes = graph.get("nodes", [])

        start_node_id = None
        output_mappings: Dict[str, Any] = {}

        for node in nodes:
            node_id = node.get("id")
            data = node.get("data", {}) or {}
            node_type = data.get("type") or node.get("type")

            if node_type == "start" and not start_node_id:
                start_node_id = node_id
            elif node_type in ["answer", "end"]:
                inputs = data.get("inputs")
                var_mappings = node.get("variable_mappings", {}) or {}

                if isinstance(inputs, dict):
                    iter_ports = inputs.keys()
                elif isinstance(inputs, list):
                    iter_ports = [inp.get("name") for inp in inputs if inp.get("name")]
                else:
                    iter_ports = []

                for port_name in iter_ports:
                    selector = self._extract_selector(var_mappings.get(port_name))
                    if selector:
                        output_mappings[port_name] = selector

                # 입력 정보가 없더라도 variable_mappings에 정의되어 있으면 활용
                if not iter_ports and var_mappings:
                    for port_name, mapping in var_mappings.items():
                        selector = self._extract_selector(mapping)
                        if selector:
                            output_mappings.setdefault(port_name, selector)

        return {
            "id": str(source_version.id),
            "name": source_version.library_name or f"Version {source_version.version}",
            "graph": graph,
            "input_schema": source_version.input_schema or [],
            "output_schema": source_version.output_schema or [],
            "start_node_id": start_node_id,
            "output_mappings": output_mappings
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

    def _collect_output_values(
        self,
        agent_data: Dict[str, Any],
        child_executor: WorkflowExecutorV2,
        output_schema: List[Dict],
        default_value: Any,
        output_mappings: Dict[str, Any]
    ) -> Dict[str, Any]:
        """라이브러리 에이전트 내부 노드 출력 수집"""
        values: Dict[str, Any] = {}
        pool = getattr(child_executor, "variable_pool", None)

        logger.debug(f"_collect_output_values: output_schema has {len(output_schema)} ports")
        logger.debug(f"_collect_output_values: output_mappings={output_mappings}")
        logger.debug(f"_collect_output_values: pool exists={pool is not None}")

        for port_def in output_schema:
            port_name = port_def.get("name")
            if not port_name:
                logger.warning(f"Port definition without name: {port_def}")
                continue

            value = None

            selector = output_mappings.get(port_name)
            logger.debug(f"Port '{port_name}': selector={selector}")

            if selector and pool:
                value = pool.resolve_value_selector(selector)
                logger.debug(f"Port '{port_name}': resolved value={value is not None} (type={type(value).__name__ if value is not None else 'None'})")

            if value is None:
                value = default_value
                logger.debug(f"Port '{port_name}': using default_value")

            values[port_name] = value

        if not values and default_value is not None:
            values["output"] = default_value
            logger.debug("No schema values, added 'output' with default_value")

        logger.info(f"_collect_output_values result: {list(values.keys())}")
        return values

    def _map_output_variables(
        self,
        output_values: Dict[str, Any],
        output_schema: List[Dict]
    ) -> Dict[str, Any]:
        """출력 변수 매핑

        output_schema에 정의된 모든 포트를 반환합니다.
        값이 없는 포트는 None으로 설정됩니다.
        """
        external_outputs = {}

        for port_def in output_schema:
            port_name = port_def.get("name")
            if not port_name:
                continue

            # output_schema에 정의된 포트는 반드시 포함
            value = output_values.get(port_name)
            external_outputs[port_name] = value

            logger.debug(f"Mapped output port '{port_name}': {value is not None}")

        # 스키마가 없고 output_values에 "output"이 있으면 사용
        if not external_outputs and "output" in output_values:
            external_outputs["output"] = output_values["output"]
            logger.debug("No schema, using 'output' port as fallback")

        logger.info(f"_map_output_variables result: {list(external_outputs.keys())}")
        return external_outputs

    async def _record_execution(
        self,
        source_version_id: str,
        context: NodeExecutionContext
    ):
        """실행 기록

        Args:
            source_version_id: 라이브러리 버전 ID
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
            if not user or not hasattr(user, 'uuid'):
                logger.debug("사용자 정보가 없어 라이브러리 사용 기록을 생략합니다")
                return

            # AgentImportHistory에 실행 기록 저장
            from app.models.import_history import AgentImportHistory
            import uuid as uuid_lib
            from datetime import datetime, timezone

            # 실행 기록 생성 (메타데이터에 실행 정보 포함)
            import_record = AgentImportHistory(
                id=uuid_lib.uuid4(),
                source_version_id=uuid_lib.UUID(source_version_id),
                target_bot_id=bot_id or "",
                imported_by=user.uuid,
                imported_at=datetime.now(timezone.utc),
                metadata={
                    "event_type": "execution",
                    "node_id": self.node_id,
                    "note": f"Nested execution in node {self.node_id}"
                }
            )

            db.add(import_record)
            await db.commit()

            logger.info(f"라이브러리 에이전트 실행 기록 저장: {source_version_id} (event_type=execution)")

        except Exception as e:
            logger.error(f"실행 기록 실패: {e}")

    def validate(self) -> tuple[bool, Optional[str]]:
        """
        노드 설정 검증

        Returns:
            tuple: (유효 여부, 오류 메시지)
        """
        # source_version_id 또는 template_id(레거시) 필수 체크
        source_version_id = self.config.get("source_version_id") or self.config.get("template_id")
        if not source_version_id:
            return False, "source_version_id가 설정되지 않았습니다"

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
