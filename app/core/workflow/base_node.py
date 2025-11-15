"""
워크플로우 노드 추상 클래스 정의

이 모듈은 모든 워크플로우 노드가 상속받아야 하는 추상 클래스를 정의합니다.
각 노드는 실행, 검증, 스키마 제공 기능을 구현해야 합니다.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, TypeVar, Generic
from pydantic import BaseModel, Field
from enum import Enum
import logging

logger = logging.getLogger(__name__)

T = TypeVar('T', bound=BaseModel)


class NodeType(str, Enum):
    """노드 타입 열거형"""
    START = "start"
    KNOWLEDGE_RETRIEVAL = "knowledge-retrieval"
    LLM = "llm"
    END = "end"
    # 향후 확장 가능한 노드 타입
    CONDITION = "condition"
    LOOP = "loop"
    HTTP_REQUEST = "http-request"
    DATA_TRANSFORM = "data-transform"
    TAVILY_SEARCH = "tavily-search"


class NodeStatus(str, Enum):
    """노드 실행 상태"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class NodeConfig(BaseModel):
    """노드 설정 기본 클래스"""
    pass


class NodeSchema(BaseModel):
    """노드 스키마 정의"""
    type: NodeType
    label: str
    icon: str
    max_instances: int = Field(default=-1, description="-1은 무제한")
    configurable: bool = Field(default=False)
    config_schema: Optional[Dict[str, Any]] = Field(default=None)
    input_required: bool = Field(default=True)
    output_provided: bool = Field(default=True)


class NodeExecutionResult(BaseModel):
    """노드 실행 결과"""
    status: NodeStatus
    output: Optional[Any] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class BaseNode(ABC, Generic[T]):
    """
    모든 워크플로우 노드의 기본 추상 클래스

    각 노드는 다음 기능을 구현해야 합니다:
    - execute: 노드 실행 로직
    - validate: 노드 설정 검증
    - get_schema: 노드 스키마 정보 반환
    """

    def __init__(
        self,
        node_id: str,
        node_type: NodeType,
        config: Optional[T] = None,
        position: Optional[Dict[str, float]] = None
    ):
        """
        노드 초기화

        Args:
            node_id: 노드 고유 ID
            node_type: 노드 타입
            config: 노드 설정
            position: 노드 위치 (x, y 좌표)
        """
        self.node_id = node_id
        self.node_type = node_type
        self.config = config
        self.position = position or {"x": 0, "y": 0}
        self._inputs: List[str] = []
        self._outputs: List[str] = []
        self._status = NodeStatus.PENDING

    @property
    def inputs(self) -> List[str]:
        """입력 노드 ID 목록"""
        return self._inputs

    @inputs.setter
    def inputs(self, value: List[str]):
        self._inputs = value

    @property
    def outputs(self) -> List[str]:
        """출력 노드 ID 목록"""
        return self._outputs

    @outputs.setter
    def outputs(self, value: List[str]):
        self._outputs = value

    @property
    def status(self) -> NodeStatus:
        """노드 상태"""
        return self._status

    @abstractmethod
    async def execute(self, context: Dict[str, Any]) -> NodeExecutionResult:
        """
        노드 실행 로직

        Args:
            context: 실행 컨텍스트 (이전 노드들의 출력 포함)

        Returns:
            NodeExecutionResult: 실행 결과
        """
        pass

    @abstractmethod
    def validate(self) -> tuple[bool, Optional[str]]:
        """
        노드 설정 검증

        Returns:
            tuple: (유효 여부, 오류 메시지)
        """
        pass

    @classmethod
    @abstractmethod
    def get_schema(cls) -> NodeSchema:
        """
        노드 스키마 정보 반환

        Returns:
            NodeSchema: 노드 스키마
        """
        pass

    @classmethod
    @abstractmethod
    def get_config_class(cls) -> type[NodeConfig]:
        """
        노드 설정 클래스 반환

        Returns:
            NodeConfig의 서브클래스
        """
        pass

    def set_status(self, status: NodeStatus):
        """노드 상태 설정"""
        self._status = status
        logger.info(f"Node {self.node_id} status changed to {status}")

    def add_input(self, node_id: str):
        """입력 노드 추가"""
        if node_id not in self._inputs:
            self._inputs.append(node_id)

    def add_output(self, node_id: str):
        """출력 노드 추가"""
        if node_id not in self._outputs:
            self._outputs.append(node_id)

    def remove_input(self, node_id: str):
        """입력 노드 제거"""
        if node_id in self._inputs:
            self._inputs.remove(node_id)

    def remove_output(self, node_id: str):
        """출력 노드 제거"""
        if node_id in self._outputs:
            self._outputs.remove(node_id)

    def get_required_context_keys(self) -> List[str]:
        """
        실행에 필요한 컨텍스트 키 목록 반환

        Returns:
            List[str]: 필요한 컨텍스트 키 목록
        """
        return []

    def to_dict(self) -> Dict[str, Any]:
        """
        노드를 딕셔너리로 변환

        Returns:
            Dict: 노드 정보
        """
        return {
            "id": self.node_id,
            "type": self.node_type.value,
            "position": self.position,
            "data": self.config.dict() if self.config else {},
            "inputs": self.inputs,
            "outputs": self.outputs,
            "status": self.status.value
        }

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(id={self.node_id}, type={self.node_type})"