"""
워크플로우 V1-V2 노드 어댑터

기존 V1 노드를 V2 인터페이스로 래핑하여 하위 호환성을 제공합니다.
이를 통해 V1과 V2 노드를 같은 워크플로우에서 혼용할 수 있습니다.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from app.core.workflow.base_node import BaseNode, NodeExecutionResult, NodeStatus
from app.core.workflow.base_node_v2 import BaseNodeV2, NodeExecutionContext
from app.schemas.workflow import NodePortSchema, PortDefinition, PortType
import logging

logger = logging.getLogger(__name__)


class NodeAdapter(BaseNodeV2):
    """
    V1 노드를 V2 인터페이스로 래핑하는 어댑터

    기존 BaseNode를 받아서 BaseNodeV2 인터페이스로 변환합니다.
    V1 노드의 입출력을 자동으로 포트 형식으로 변환합니다.

    Example:
        >>> # V1 노드 생성
        >>> v1_node = StartNode(node_id="start-1")
        >>>
        >>> # V2 어댑터로 래핑
        >>> v2_node = NodeAdapter(
        ...     node_id="start-1",
        ...     v1_node=v1_node,
        ...     output_port_mappings={"user_message": "query"}
        ... )
    """

    def __init__(
        self,
        node_id: str,
        v1_node: BaseNode,
        input_port_mappings: Optional[Dict[str, str]] = None,
        output_port_mappings: Optional[Dict[str, str]] = None,
        config: Optional[Dict[str, Any]] = None,
        variable_mappings: Optional[Dict[str, Any]] = None
    ):
        """
        어댑터 초기화

        Args:
            node_id: 노드 ID
            v1_node: 래핑할 V1 노드
            input_port_mappings: V1 context key → V2 port name 매핑
            output_port_mappings: V1 output key → V2 port name 매핑
            config: 노드 설정
            variable_mappings: 변수 매핑
        """
        super().__init__(node_id, config, variable_mappings)
        self.v1_node = v1_node
        self.input_port_mappings = input_port_mappings or {}
        self.output_port_mappings = output_port_mappings or {}

        logger.debug(f"NodeAdapter created for V1 node: {v1_node.node_type}")

    def get_port_schema(self) -> NodePortSchema:
        """
        V1 노드에서 포트 스키마 추론

        Returns:
            NodePortSchema: 입출력 포트 정의
        """
        # V1 노드의 required_context_keys에서 입력 포트 생성
        input_ports = []
        required_keys = self.v1_node.get_required_context_keys()

        for key in required_keys:
            port_name = self.input_port_mappings.get(key, key)
            input_ports.append(
                PortDefinition(
                    name=port_name,
                    type=PortType.ANY,
                    required=True,
                    description=f"Input from V1 node: {key}"
                )
            )

        # V1 노드의 출력을 기반으로 출력 포트 생성
        output_ports = []
        for v1_key, v2_port_name in self.output_port_mappings.items():
            output_ports.append(
                PortDefinition(
                    name=v2_port_name,
                    type=PortType.ANY,
                    required=False,
                    description=f"Output from V1 node: {v1_key}"
                )
            )

        # 매핑이 없으면 기본 출력 포트 생성
        if not output_ports:
            output_ports.append(
                PortDefinition(
                    name="output",
                    type=PortType.ANY,
                    required=False,
                    description="Raw V1 node output"
                )
            )

        return NodePortSchema(
            inputs=input_ports,
            outputs=output_ports
        )

    async def execute_v2(self, context: NodeExecutionContext) -> Dict[str, Any]:
        """
        V1 노드 실행을 V2 방식으로 래핑

        Args:
            context: V2 실행 컨텍스트

        Returns:
            Dict[str, Any]: V2 출력 포트 매핑

        Raises:
            Exception: V1 노드 실행 실패 시
        """
        # V2 컨텍스트를 V1 컨텍스트로 변환
        v1_context = self._convert_context_to_v1(context)

        logger.debug(f"Executing V1 node {self.v1_node.node_id} via adapter")

        # V1 노드 실행
        try:
            result: NodeExecutionResult = await self.v1_node.execute(v1_context)

            if result.status == NodeStatus.FAILED:
                raise Exception(result.error or "V1 node execution failed")

            # V1 출력을 V2 포트 형식으로 변환
            v2_outputs = self._convert_output_to_v2(result.output)

            logger.debug(f"V1 node {self.v1_node.node_id} completed successfully")

            return v2_outputs

        except Exception as e:
            logger.error(f"V1 node execution failed: {str(e)}")
            raise

    def _convert_context_to_v1(self, v2_context: NodeExecutionContext) -> Dict[str, Any]:
        """
        V2 컨텍스트를 V1 컨텍스트 딕셔너리로 변환

        Args:
            v2_context: V2 실행 컨텍스트

        Returns:
            Dict[str, Any]: V1 컨텍스트
        """
        v1_context = {
            "node_outputs": {},
            "session_id": v2_context.service_container.get_session_id(),
            "user_message": v2_context.variable_pool.get_system_variable("user_message"),
        }

        # 서비스들 추가
        v1_context["vector_service"] = v2_context.service_container.get_vector_service()
        v1_context["llm_service"] = v2_context.service_container.get_llm_service()
        v1_context["bot_id"] = v2_context.service_container.get_bot_id()
        v1_context["db"] = v2_context.service_container.get_db_session()
        v1_context["stream_handler"] = v2_context.service_container.get_stream_handler()

        # 입력 포트 데이터를 V1 형식으로 변환
        for v1_key, v2_port_name in self.input_port_mappings.items():
            value = v2_context.get_input(v2_port_name)
            if value is not None:
                v1_context[v1_key] = value

        # variable_pool의 모든 노드 출력을 node_outputs에 추가
        for node_id in v2_context.variable_pool._node_outputs.keys():
            node_outputs = v2_context.variable_pool.get_all_node_outputs(node_id)
            if node_outputs:
                v1_context["node_outputs"][node_id] = node_outputs

        return v1_context

    def _convert_output_to_v2(self, v1_output: Any) -> Dict[str, Any]:
        """
        V1 출력을 V2 포트 형식으로 변환

        Args:
            v1_output: V1 노드의 출력

        Returns:
            Dict[str, Any]: V2 포트 매핑
        """
        v2_outputs = {}

        # V1 출력이 딕셔너리인 경우
        if isinstance(v1_output, dict):
            # 출력 매핑에 따라 변환
            for v1_key, v2_port_name in self.output_port_mappings.items():
                if v1_key in v1_output:
                    v2_outputs[v2_port_name] = v1_output[v1_key]

            # 매핑되지 않은 출력은 raw output으로
            if not v2_outputs:
                v2_outputs["output"] = v1_output
        else:
            # 단순 값인 경우
            if self.output_port_mappings:
                # 첫 번째 매핑에 할당
                first_port = list(self.output_port_mappings.values())[0]
                v2_outputs[first_port] = v1_output
            else:
                v2_outputs["output"] = v1_output

        return v2_outputs

    def validate(self) -> tuple[bool, Optional[str]]:
        """
        V1 노드의 검증 메서드 호출

        Returns:
            tuple: (유효 여부, 오류 메시지)
        """
        return self.v1_node.validate()

    def get_required_services(self) -> List[str]:
        """
        V1 노드가 필요로 하는 서비스 추론

        Returns:
            List[str]: 서비스 이름 리스트
        """
        # V1 노드 타입에 따라 필요한 서비스 반환
        services = []

        node_type = self.v1_node.node_type.value

        if node_type == "knowledge-retrieval":
            services.extend(["vector_service", "bot_id", "db_session"])
        elif node_type == "llm":
            services.extend(["llm_service", "stream_handler"])
        elif node_type == "start":
            pass  # 서비스 불필요
        elif node_type == "end":
            pass  # 서비스 불필요

        return services


class NodeAdapterFactory:
    """
    NodeAdapter 생성을 위한 팩토리 클래스

    노드 타입에 따라 적절한 입출력 매핑을 자동으로 생성합니다.
    """

    # 노드 타입별 기본 매핑
    DEFAULT_MAPPINGS = {
        "start": {
            "input_mappings": {},
            "output_mappings": {
                "user_message": "query",
                "session_id": "session_id"
            }
        },
        "knowledge-retrieval": {
            "input_mappings": {
                "user_message": "query"
            },
            "output_mappings": {
                "context": "context",
                "retrieved_documents": "documents"
            }
        },
        "llm": {
            "input_mappings": {
                "user_message": "query",
                "context": "context"
            },
            "output_mappings": {
                "llm_response": "response"
            }
        },
        "end": {
            "input_mappings": {
                "llm_response": "response"
            },
            "output_mappings": {
                "response": "final_output"
            }
        }
    }

    @classmethod
    def create_adapter(
        cls,
        node_id: str,
        v1_node: BaseNode,
        config: Optional[Dict[str, Any]] = None,
        variable_mappings: Optional[Dict[str, Any]] = None
    ) -> NodeAdapter:
        """
        V1 노드에 대한 어댑터 생성

        Args:
            node_id: 노드 ID
            v1_node: V1 노드
            config: 노드 설정
            variable_mappings: 변수 매핑

        Returns:
            NodeAdapter: 생성된 어댑터
        """
        node_type = v1_node.node_type.value

        # 기본 매핑 가져오기
        mappings = cls.DEFAULT_MAPPINGS.get(node_type, {})

        input_mappings = mappings.get("input_mappings", {})
        output_mappings = mappings.get("output_mappings", {})

        logger.debug(f"Creating adapter for {node_type} with mappings: in={input_mappings}, out={output_mappings}")

        return NodeAdapter(
            node_id=node_id,
            v1_node=v1_node,
            input_port_mappings=input_mappings,
            output_port_mappings=output_mappings,
            config=config,
            variable_mappings=variable_mappings
        )
