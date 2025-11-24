"""
워크플로우 V2 노드 레지스트리

V2 노드들을 관리하는 레지스트리입니다.
"""

from typing import Dict, Type, Optional, List
from app.core.workflow.base_node_v2 import BaseNodeV2
from app.schemas.workflow import NodePortSchema
import logging

logger = logging.getLogger(__name__)


class NodeRegistryV2:
    """
    V2 노드 타입 레지스트리

    V2 노드들을 등록하고 관리합니다.
    """

    _instance: Optional['NodeRegistryV2'] = None
    _nodes: Dict[str, Type[BaseNodeV2]] = {}

    def __new__(cls) -> 'NodeRegistryV2':
        """싱글톤 인스턴스 생성"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._nodes = {}
        return cls._instance

    def register(self, node_type: str, node_class: Type[BaseNodeV2]) -> None:
        """
        V2 노드 타입 등록

        Args:
            node_type: 노드 타입 문자열 ("start", "knowledge-retrieval", etc.)
            node_class: V2 노드 클래스

        Raises:
            ValueError: 이미 등록된 노드 타입인 경우
        """
        if node_type in self._nodes:
            raise ValueError(f"Node type {node_type} is already registered")

        if not issubclass(node_class, BaseNodeV2):
            raise TypeError(f"Node class must inherit from BaseNodeV2")

        self._nodes[node_type] = node_class
        logger.info(f"Registered V2 node type: {node_type} -> {node_class.__name__}")

    def unregister(self, node_type: str) -> None:
        """
        노드 타입 등록 해제

        Args:
            node_type: 노드 타입
        """
        if node_type in self._nodes:
            del self._nodes[node_type]
            logger.info(f"Unregistered V2 node type: {node_type}")

    def get(self, node_type: str) -> Optional[Type[BaseNodeV2]]:
        """
        노드 클래스 조회

        Args:
            node_type: 노드 타입

        Returns:
            V2 노드 클래스 또는 None
        """
        return self._nodes.get(node_type)

    def get_or_raise(self, node_type: str) -> Type[BaseNodeV2]:
        """
        노드 클래스 조회 (없으면 예외 발생)

        Args:
            node_type: 노드 타입

        Returns:
            V2 노드 클래스

        Raises:
            KeyError: 등록되지 않은 노드 타입인 경우
        """
        if node_type not in self._nodes:
            raise KeyError(f"V2 node type {node_type} is not registered")
        return self._nodes[node_type]

    def create_node(
        self,
        node_type: str,
        node_id: str,
        config: Optional[Dict] = None,
        variable_mappings: Optional[Dict] = None
    ) -> BaseNodeV2:
        """
        V2 노드 인스턴스 생성

        Args:
            node_type: 노드 타입
            node_id: 노드 ID
            config: 노드 설정 (data 필드)
            variable_mappings: 변수 매핑

        Returns:
            생성된 V2 노드 인스턴스

        Raises:
            KeyError: 등록되지 않은 노드 타입인 경우
        """
        node_class = self.get_or_raise(node_type)

        return node_class(
            node_id=node_id,
            config=config,
            variable_mappings=variable_mappings
        )

    def list_types(self) -> List[str]:
        """
        등록된 모든 노드 타입 목록 반환

        Returns:
            노드 타입 문자열 목록
        """
        return list(self._nodes.keys())

    def list_schemas(self) -> Dict[str, NodePortSchema]:
        """
        등록된 모든 노드의 포트 스키마 목록 반환

        Returns:
            {node_type: NodePortSchema} 딕셔너리
        """
        schemas = {}
        for node_type, node_class in self._nodes.items():
            try:
                # 임시 인스턴스 생성해서 스키마 조회
                temp_node = node_class(node_id="temp", config={})
                schemas[node_type] = temp_node.get_port_schema()
            except Exception as e:
                logger.error(f"Failed to get schema for {node_type}: {e}")
        return schemas

    def get_schema(self, node_type: str) -> Optional[NodePortSchema]:
        """
        특정 노드 타입의 포트 스키마 반환

        Args:
            node_type: 노드 타입

        Returns:
            NodePortSchema 또는 None
        """
        node_class = self.get(node_type)
        if node_class:
            try:
                temp_node = node_class(node_id="temp", config={})
                return temp_node.get_port_schema()
            except Exception as e:
                logger.error(f"Failed to get schema for {node_type}: {e}")
        return None

    def clear(self) -> None:
        """모든 등록된 노드 타입 제거"""
        self._nodes.clear()
        logger.info("Cleared all registered V2 node types")

    def is_registered(self, node_type: str) -> bool:
        """
        노드 타입 등록 여부 확인

        Args:
            node_type: 노드 타입

        Returns:
            등록 여부
        """
        return node_type in self._nodes

    def __contains__(self, node_type: str) -> bool:
        """in 연산자 지원"""
        return node_type in self._nodes

    def __len__(self) -> int:
        """등록된 노드 타입 개수"""
        return len(self._nodes)

    def __repr__(self) -> str:
        types = list(self._nodes.keys())
        return f"NodeRegistryV2({', '.join(types)})"


# 전역 V2 레지스트리 인스턴스
node_registry_v2 = NodeRegistryV2()


def register_node_v2(node_type: str):
    """
    V2 노드 클래스 데코레이터

    사용 예:
        @register_node_v2("start")
        class StartNodeV2(BaseNodeV2):
            ...
    """
    def decorator(cls: Type[BaseNodeV2]) -> Type[BaseNodeV2]:
        node_registry_v2.register(node_type, cls)
        return cls
    return decorator


# V2 노드들은 executor_v2.py에서 필요할 때 자동으로 import되고 등록됩니다.
# 순환 import 방지를 위해 여기서는 기본 노드만 직접 등록합니다.

def _register_default_nodes():
    """기본 V2 노드들을 등록합니다."""
    from app.core.workflow.nodes_v2.start_node_v2 import StartNodeV2
    from app.core.workflow.nodes_v2.knowledge_node_v2 import KnowledgeNodeV2
    from app.core.workflow.nodes_v2.llm_node_v2 import LLMNodeV2
    from app.core.workflow.nodes_v2.end_node_v2 import EndNodeV2
    from app.core.workflow.nodes_v2.if_else_node_v2 import IfElseNodeV2
    from app.core.workflow.nodes_v2.question_classifier_node_v2 import QuestionClassifierNodeV2
    from app.core.workflow.nodes_v2.tavily_search_node_v2 import TavilySearchNodeV2
    from app.core.workflow.nodes_v2.assigner_node_v2 import AssignerNodeV2
    from app.core.workflow.nodes_v2.answer_node_v2 import AnswerNodeV2
    from app.core.workflow.nodes_v2.imported_workflow_node import ImportedWorkflowNode
    from app.core.workflow.nodes_v2.slack_node_v2 import SlackNodeV2
    from app.core.workflow.nodes_v2.http_node_v2 import HTTPNodeV2
    from app.core.workflow.nodes_v2.template_transform_node_v2 import TemplateTransformNodeV2

    node_registry_v2.register("start", StartNodeV2)
    node_registry_v2.register("knowledge-retrieval", KnowledgeNodeV2)
    node_registry_v2.register("llm", LLMNodeV2)
    node_registry_v2.register("end", EndNodeV2)
    node_registry_v2.register("if-else", IfElseNodeV2)
    node_registry_v2.register("question-classifier", QuestionClassifierNodeV2)
    node_registry_v2.register("tavily-search", TavilySearchNodeV2)
    node_registry_v2.register("assigner", AssignerNodeV2)
    node_registry_v2.register("answer", AnswerNodeV2)
    node_registry_v2.register("imported-workflow", ImportedWorkflowNode)
    node_registry_v2.register("slack", SlackNodeV2)
    node_registry_v2.register("http", HTTPNodeV2)
    node_registry_v2.register("template-transform", TemplateTransformNodeV2)

# 기본 노드 등록
_register_default_nodes()

logger.info(f"V2 node registry initialized with {len(node_registry_v2)} node types")
