"""
워크플로우 V2 노드 기본 인터페이스

포트 기반 데이터 흐름을 지원하는 V2 노드의 추상 클래스입니다.
모든 V2 노드는 이 클래스를 상속받아 구현해야 합니다.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Iterable, Union
from pydantic import BaseModel
from app.schemas.workflow import NodePortSchema, PortDefinition, PortType
from app.core.workflow.variable_pool import VariablePool
from app.core.workflow.service_container import ServiceContainer
from app.core.workflow.base_node import NodeStatus, NodeExecutionResult
import logging

logger = logging.getLogger(__name__)


class NodeExecutionContext:
    """
    노드 실행 컨텍스트 (V2)

    V2 노드가 실행될 때 필요한 모든 정보를 담고 있습니다.
    """

    def __init__(
        self,
        node_id: str,
        variable_pool: VariablePool,
        service_container: ServiceContainer,
        metadata: Optional[Dict[str, Any]] = None,
        executed_nodes: Optional[List[str]] = None
    ):
        """
        실행 컨텍스트 초기화

        Args:
            node_id: 현재 실행 중인 노드 ID
            variable_pool: 변수 풀
            service_container: 서비스 컨테이너
            metadata: 메타데이터
            executed_nodes: 현재까지 실행된 노드 ID 목록 (실행 경로)
        """
        self.node_id = node_id
        self.variable_pool = variable_pool
        self.service_container = service_container
        self.metadata = metadata or {}
        self._edge_handles: List[str] = []
        self.executed_nodes = executed_nodes or []  # 실행 경로 추적

    def get_input(self, port_name: str) -> Optional[Any]:
        """
        입력 포트 값 조회 (자동으로 variable_pool에서 해석)

        Args:
            port_name: 입력 포트 이름

        Returns:
            입력 값 또는 None
        """
        # 노드의 variable_mappings에서 해당 포트의 소스를 찾아 해석
        # 실제로는 executor가 미리 준비해준 inputs를 사용
        return self.metadata.get("prepared_inputs", {}).get(port_name)

    def set_output(self, port_name: str, value: Any) -> None:
        """
        출력 포트 값 설정

        Args:
            port_name: 출력 포트 이름
            value: 출력 값
        """
        self.variable_pool.set_node_output(self.node_id, port_name, value)

    def get_service(self, service_name: str) -> Optional[Any]:
        """
        서비스 조회

        Args:
            service_name: 서비스 이름

        Returns:
            서비스 인스턴스 또는 None
        """
        return self.service_container.get(service_name)

    def set_next_edge_handle(self, handle: Union[Optional[str], Iterable[str]]) -> None:
        """다음에 실행할 엣지 핸들 기록"""
        if handle is None:
            return
        if isinstance(handle, str):
            values = [handle]
        else:
            values = [item for item in handle if item]
        self._edge_handles.extend(values)

    def consume_edge_handles(self) -> List[str]:
        """저장된 엣지 핸들을 반환하고 초기화"""
        handles = self._edge_handles.copy()
        self._edge_handles.clear()
        return handles


class BaseNodeV2(ABC):
    """
    워크플로우 V2 노드 추상 클래스

    모든 V2 노드는 이 클래스를 상속받아 구현합니다.
    포트 기반 데이터 흐름과 변수 풀을 사용합니다.

    Example:
        >>> class MyNodeV2(BaseNodeV2):
        ...     def get_port_schema(self) -> NodePortSchema:
        ...         return NodePortSchema(
        ...             inputs=[PortDefinition(name="query", type=PortType.STRING)],
        ...             outputs=[PortDefinition(name="result", type=PortType.STRING)]
        ...         )
        ...
        ...     async def execute_v2(self, context: NodeExecutionContext) -> Dict[str, Any]:
        ...         query = context.get_input("query")
        ...         result = f"Processed: {query}"
        ...         return {"result": result}
    """

    def __init__(
        self,
        node_id: str,
        config: Optional[Dict[str, Any]] = None,
        variable_mappings: Optional[Dict[str, Any]] = None
    ):
        """
        노드 초기화

        Args:
            node_id: 노드 고유 ID
            config: 노드 설정 (data 필드)
            variable_mappings: 입력 포트와 변수 매핑
        """
        self.node_id = node_id
        self.config = config or {}
        self.variable_mappings = variable_mappings or {}
        self._status = NodeStatus.PENDING

        logger.debug(f"Initialized V2 node: {node_id}")

    @property
    def status(self) -> NodeStatus:
        """노드 상태"""
        return self._status

    def set_status(self, status: NodeStatus) -> None:
        """노드 상태 설정"""
        self._status = status
        logger.info(f"Node {self.node_id} status: {status.value}")

    # ========== 추상 메서드 (구현 필수) ==========

    @abstractmethod
    def get_port_schema(self) -> NodePortSchema:
        """
        노드의 입출력 포트 스키마 반환

        Returns:
            NodePortSchema: 입출력 포트 정의

        Example:
            >>> def get_port_schema(self) -> NodePortSchema:
            ...     return NodePortSchema(
            ...         inputs=[
            ...             PortDefinition(name="query", type=PortType.STRING, required=True),
            ...             PortDefinition(name="context", type=PortType.STRING, required=False)
            ...         ],
            ...         outputs=[
            ...             PortDefinition(name="response", type=PortType.STRING)
            ...         ]
            ...     )
        """
        pass

    @abstractmethod
    async def execute_v2(
        self,
        context: NodeExecutionContext
    ) -> Dict[str, Any]:
        """
        노드 실행 로직 (V2)

        Args:
            context: 실행 컨텍스트 (변수 풀, 서비스 컨테이너 포함)

        Returns:
            Dict[str, Any]: {port_name: value} 형식의 출력

        Example:
            >>> async def execute_v2(self, context: NodeExecutionContext) -> Dict[str, Any]:
            ...     # 입력 조회
            ...     query = context.get_input("query")
            ...
            ...     # 서비스 사용
            ...     llm_service = context.get_service("llm_service")
            ...
            ...     # 처리
            ...     response = await llm_service.generate(query)
            ...
            ...     # 출력 반환
            ...     return {"response": response}
        """
        pass

    # ========== 선택적 메서드 ==========

    def validate(self) -> tuple[bool, Optional[str]]:
        """
        노드 설정 검증

        Returns:
            tuple: (유효 여부, 오류 메시지)
        """
        # 기본 검증: 포트 스키마 확인
        try:
            schema = self.get_port_schema()

            # 필수 입력 포트가 variable_mappings에 있는지 확인
            for input_port in schema.inputs:
                if input_port.required and input_port.name not in self.variable_mappings:
                    return False, f"Required input port '{input_port.name}' not mapped"

            return True, None

        except Exception as e:
            return False, f"Port schema validation failed: {str(e)}"

    def get_required_services(self) -> List[str]:
        """
        노드 실행에 필요한 서비스 목록

        Returns:
            List[str]: 서비스 이름 리스트

        Example:
            >>> def get_required_services(self) -> List[str]:
            ...     return ["llm_service", "vector_service"]
        """
        return []

    # ========== 래퍼 메서드 (기존 시스템과 호환) ==========

    async def execute(
        self,
        context: NodeExecutionContext
    ) -> NodeExecutionResult:
        """
        노드 실행 (래퍼)

        execute_v2()를 호출하고 결과를 NodeExecutionResult로 변환합니다.

        Args:
            context: 실행 컨텍스트

        Returns:
            NodeExecutionResult: 실행 결과
        """
        try:
            self.set_status(NodeStatus.RUNNING)

            # V2 실행
            outputs = await self.execute_v2(context)
            edge_handles = context.consume_edge_handles()

            # 출력을 variable_pool에 저장
            for port_name, value in outputs.items():
                context.set_output(port_name, value)

            self.set_status(NodeStatus.COMPLETED)

            metadata = {"node_id": self.node_id}
            if edge_handles:
                metadata["edge_handles"] = edge_handles

            return NodeExecutionResult(
                status=NodeStatus.COMPLETED,
                output=outputs,
                metadata=metadata
            )

        except Exception as e:
            logger.error(f"Node {self.node_id} execution failed: {str(e)}")
            self.set_status(NodeStatus.FAILED)

            return NodeExecutionResult(
                status=NodeStatus.FAILED,
                output=None,
                error=str(e),
                metadata={"node_id": self.node_id}
            )

    # ========== 유틸리티 ==========

    def get_input_port_names(self) -> List[str]:
        """입력 포트 이름 목록"""
        schema = self.get_port_schema()
        return [port.name for port in schema.inputs]

    def get_output_port_names(self) -> List[str]:
        """출력 포트 이름 목록"""
        schema = self.get_port_schema()
        return [port.name for port in schema.outputs]

    def has_input_port(self, port_name: str) -> bool:
        """입력 포트 존재 여부"""
        return port_name in self.get_input_port_names()

    def has_output_port(self, port_name: str) -> bool:
        """출력 포트 존재 여부"""
        return port_name in self.get_output_port_names()

    def _compute_allowed_selectors(self, context: NodeExecutionContext) -> List[str]:
        """
        연결된 노드의 변수 셀렉터 목록을 계산

        variable_mappings에서 모든 소스 셀렉터를 추출하여
        이 노드가 접근 가능한 변수 목록을 반환합니다.

        Args:
            context: 실행 컨텍스트

        Returns:
            List[str]: 허용된 변수 셀렉터 목록 (예: ["start.query", "llm_1.response"])
        """
        allowed = []

        for port_name, selector in self.variable_mappings.items():
            if selector:
                # selector는 "node_id.port_name" 형식의 문자열 또는 딕셔너리일 수 있음
                if isinstance(selector, str):
                    allowed.append(selector)
                elif isinstance(selector, dict):
                    # 딕셔너리 형식인 경우 (예: {"variable": "node_id.port_name"})
                    var_selector = selector.get("variable")
                    if var_selector:
                        allowed.append(var_selector)

        # 자기 자신의 입력 포트도 허용 (self.port_name 형식)
        for port_name in self.get_input_port_names():
            allowed.append(f"self.{port_name}")

        logger.debug(f"Node {self.node_id} allowed selectors: {allowed}")
        return allowed

    def to_dict(self) -> Dict[str, Any]:
        """
        노드를 딕셔너리로 변환

        Returns:
            Dict: 노드 정보
        """
        schema = self.get_port_schema()

        return {
            "id": self.node_id,
            "config": self.config,
            "variable_mappings": self.variable_mappings,
            "status": self.status.value,
            "ports": {
                "inputs": [port.dict() for port in schema.inputs],
                "outputs": [port.dict() for port in schema.outputs]
            }
        }

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(id={self.node_id}, status={self.status.value})"


class SimpleNodeV2(BaseNodeV2):
    """
    간단한 V2 노드 구현 예제

    포트 스키마와 실행 로직을 함수로 주입받아 동적으로 노드를 생성합니다.
    테스트나 간단한 변환 로직에 유용합니다.
    """

    def __init__(
        self,
        node_id: str,
        port_schema: NodePortSchema,
        execute_fn: Any,  # Callable
        config: Optional[Dict[str, Any]] = None,
        variable_mappings: Optional[Dict[str, Any]] = None
    ):
        """
        간단한 노드 초기화

        Args:
            node_id: 노드 ID
            port_schema: 포트 스키마
            execute_fn: 실행 함수 async def fn(context) -> Dict[str, Any]
            config: 노드 설정
            variable_mappings: 변수 매핑
        """
        super().__init__(node_id, config, variable_mappings)
        self._port_schema = port_schema
        self._execute_fn = execute_fn

    def get_port_schema(self) -> NodePortSchema:
        return self._port_schema

    async def execute_v2(self, context: NodeExecutionContext) -> Dict[str, Any]:
        return await self._execute_fn(context)
