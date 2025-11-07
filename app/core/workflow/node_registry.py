"""
워크플로우 노드 레지스트리

동적으로 노드 타입을 등록하고 조회할 수 있는 레지스트리 시스템입니다.
플러그인 방식으로 새로운 노드 타입을 추가할 수 있습니다.
"""

from typing import Dict, Type, Optional, List
from app.core.workflow.base_node import BaseNode, NodeType, NodeSchema
import logging

logger = logging.getLogger(__name__)


class NodeRegistry:
    """
    노드 타입 레지스트리

    싱글톤 패턴으로 구현되어 애플리케이션 전체에서 하나의 인스턴스만 사용됩니다.
    """

    _instance: Optional['NodeRegistry'] = None
    _nodes: Dict[NodeType, Type[BaseNode]] = {}

    def __new__(cls) -> 'NodeRegistry':
        """싱글톤 인스턴스 생성"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._nodes = {}
        return cls._instance

    def register(self, node_type: NodeType, node_class: Type[BaseNode]) -> None:
        """
        노드 타입 등록

        Args:
            node_type: 노드 타입
            node_class: 노드 클래스

        Raises:
            ValueError: 이미 등록된 노드 타입인 경우
        """
        if node_type in self._nodes:
            raise ValueError(f"Node type {node_type} is already registered")

        if not issubclass(node_class, BaseNode):
            raise TypeError(f"Node class must inherit from BaseNode")

        self._nodes[node_type] = node_class
        logger.info(f"Registered node type: {node_type.value} -> {node_class.__name__}")

    def unregister(self, node_type: NodeType) -> None:
        """
        노드 타입 등록 해제

        Args:
            node_type: 노드 타입
        """
        if node_type in self._nodes:
            del self._nodes[node_type]
            logger.info(f"Unregistered node type: {node_type.value}")

    def get(self, node_type: NodeType) -> Optional[Type[BaseNode]]:
        """
        노드 클래스 조회

        Args:
            node_type: 노드 타입

        Returns:
            노드 클래스 또는 None
        """
        return self._nodes.get(node_type)

    def get_or_raise(self, node_type: NodeType) -> Type[BaseNode]:
        """
        노드 클래스 조회 (없으면 예외 발생)

        Args:
            node_type: 노드 타입

        Returns:
            노드 클래스

        Raises:
            KeyError: 등록되지 않은 노드 타입인 경우
        """
        if node_type not in self._nodes:
            raise KeyError(f"Node type {node_type} is not registered")
        return self._nodes[node_type]

    def create_node(
        self,
        node_type: NodeType,
        node_id: str,
        config: Optional[Dict] = None,
        position: Optional[Dict[str, float]] = None
    ) -> BaseNode:
        """
        노드 인스턴스 생성

        Args:
            node_type: 노드 타입
            node_id: 노드 ID
            config: 노드 설정
            position: 노드 위치

        Returns:
            생성된 노드 인스턴스

        Raises:
            KeyError: 등록되지 않은 노드 타입인 경우
        """
        node_class = self.get_or_raise(node_type)

        # 설정 객체 생성
        config_obj = None
        if config:
            config_class = node_class.get_config_class()
            config_obj = config_class(**config)

        return node_class(
            node_id=node_id,
            node_type=node_type,
            config=config_obj,
            position=position
        )

    def list_types(self) -> List[NodeType]:
        """
        등록된 모든 노드 타입 목록 반환

        Returns:
            노드 타입 목록
        """
        return list(self._nodes.keys())

    def list_schemas(self) -> List[NodeSchema]:
        """
        등록된 모든 노드의 스키마 목록 반환

        Returns:
            노드 스키마 목록
        """
        schemas = []
        for node_type, node_class in self._nodes.items():
            try:
                schema = node_class.get_schema()
                schemas.append(schema)
            except Exception as e:
                logger.error(f"Failed to get schema for {node_type}: {e}")
        return schemas

    def get_schema(self, node_type: NodeType) -> Optional[NodeSchema]:
        """
        특정 노드 타입의 스키마 반환

        Args:
            node_type: 노드 타입

        Returns:
            노드 스키마 또는 None
        """
        node_class = self.get(node_type)
        if node_class:
            try:
                return node_class.get_schema()
            except Exception as e:
                logger.error(f"Failed to get schema for {node_type}: {e}")
        return None

    def clear(self) -> None:
        """모든 등록된 노드 타입 제거"""
        self._nodes.clear()
        logger.info("Cleared all registered node types")

    def is_registered(self, node_type: NodeType) -> bool:
        """
        노드 타입 등록 여부 확인

        Args:
            node_type: 노드 타입

        Returns:
            등록 여부
        """
        return node_type in self._nodes

    def __contains__(self, node_type: NodeType) -> bool:
        """in 연산자 지원"""
        return node_type in self._nodes

    def __len__(self) -> int:
        """등록된 노드 타입 개수"""
        return len(self._nodes)

    def __repr__(self) -> str:
        types = [t.value for t in self._nodes.keys()]
        return f"NodeRegistry({', '.join(types)})"


# 전역 레지스트리 인스턴스
node_registry = NodeRegistry()


def register_node(node_type: NodeType):
    """
    노드 클래스 데코레이터

    사용 예:
        @register_node(NodeType.START)
        class StartNode(BaseNode):
            ...
    """
    def decorator(cls: Type[BaseNode]) -> Type[BaseNode]:
        node_registry.register(node_type, cls)
        return cls
    return decorator