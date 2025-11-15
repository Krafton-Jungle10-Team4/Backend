"""
워크플로우 V2 변수 풀

노드 간 데이터 전달을 위한 중앙 집중식 변수 관리 시스템입니다.
포트 기반 데이터 흐름을 지원하며, ValueSelector를 통해 다른 노드의 출력을 참조할 수 있습니다.
"""

from typing import Any, Dict, Optional, List, Set, Tuple, TYPE_CHECKING
from app.schemas.workflow import PortType
import logging

if TYPE_CHECKING:
    from app.core.workflow.nodes_v2.utils.template_renderer import SegmentGroup

logger = logging.getLogger(__name__)


class VariablePool:
    """
    워크플로우 실행 중 변수를 관리하는 중앙 저장소

    노드 출력, 환경 변수, 대화 변수, 시스템 변수를 관리합니다.
    ValueSelector 형식 ({node_id}.{port_name})으로 값을 참조할 수 있습니다.

    Example:
        >>> pool = VariablePool()
        >>> pool.set_node_output("start-1", "query", "사용자 질문")
        >>> pool.resolve_value_selector("start-1.query")
        "사용자 질문"
    """

    def __init__(
        self,
        environment_variables: Optional[Dict[str, Any]] = None,
        conversation_variables: Optional[Dict[str, Any]] = None,
        system_variables: Optional[Dict[str, Any]] = None
    ):
        """
        변수 풀 초기화

        Args:
            environment_variables: 환경 변수 (봇 설정에서 정의)
            conversation_variables: 대화 변수 (세션별 상태)
            system_variables: 시스템 변수 (실행 메타데이터)
        """
        # 노드 출력: {node_id: {port_name: value}}
        self._node_outputs: Dict[str, Dict[str, Any]] = {}

        # 각종 변수들
        self._environment_variables = environment_variables or {}
        self._conversation_variables = conversation_variables or {}
        self._conversation_dirty: Set[str] = set()
        self._system_variables = system_variables or {}

        logger.debug("VariablePool initialized")

    # ========== 노드 출력 관리 ==========

    def set_node_output(self, node_id: str, port_name: str, value: Any) -> None:
        """
        노드의 출력 포트 값을 설정

        Args:
            node_id: 노드 ID
            port_name: 출력 포트 이름
            value: 포트 값

        Example:
            >>> pool.set_node_output("llm-1", "response", "안녕하세요!")
        """
        if node_id not in self._node_outputs:
            self._node_outputs[node_id] = {}

        self._node_outputs[node_id][port_name] = value
        logger.debug(f"Set node output: {node_id}.{port_name}")

    def get_node_output(self, node_id: str, port_name: str) -> Optional[Any]:
        """
        노드의 출력 포트 값을 조회

        Args:
            node_id: 노드 ID
            port_name: 출력 포트 이름

        Returns:
            포트 값 또는 None

        Example:
            >>> pool.get_node_output("llm-1", "response")
            "안녕하세요!"
        """
        node_data = self._node_outputs.get(node_id)
        if node_data is None:
            logger.warning(f"Node {node_id} not found in outputs")
            return None

        value = node_data.get(port_name)
        if value is None:
            logger.warning(f"Port {port_name} not found in node {node_id}")

        return value

    def has_node_output(self, node_id: str, port_name: Optional[str] = None) -> bool:
        """
        노드 출력 존재 여부 확인

        Args:
            node_id: 노드 ID
            port_name: 포트 이름 (None이면 노드 자체의 존재 여부만 확인)

        Returns:
            존재 여부

        Example:
            >>> pool.has_node_output("llm-1")  # 노드 존재 여부
            True
            >>> pool.has_node_output("llm-1", "response")  # 특정 포트 존재 여부
            True
        """
        if node_id not in self._node_outputs:
            return False

        if port_name is None:
            return True

        return port_name in self._node_outputs[node_id]

    def get_all_node_outputs(self, node_id: str) -> Dict[str, Any]:
        """
        노드의 모든 출력 포트 값을 조회

        Args:
            node_id: 노드 ID

        Returns:
            {port_name: value} 딕셔너리

        Example:
            >>> pool.get_all_node_outputs("llm-1")
            {"response": "안녕하세요!", "tokens": 10}
        """
        return self._node_outputs.get(node_id, {}).copy()

    # ========== ValueSelector 처리 ==========

    def resolve_value_selector(self, selector: str) -> Optional[Any]:
        """
        ValueSelector를 해석하여 실제 값을 반환

        ValueSelector 형식:
        - {node_id}.{port_name}: 노드 출력 참조
        - env/environment.{var_name}: 환경 변수 참조
        - conv/conversation.{var_name}: 대화 변수 참조
        - sys/system.{var_name}: 시스템 변수 참조
        - node_id.port.attr: 중첩 속성/배열 접근

        Args:
            selector: ValueSelector 문자열

        Returns:
            해석된 값 또는 None

        Example:
            >>> pool.resolve_value_selector("start-1.query")
            "사용자 질문"
            >>> pool.resolve_value_selector("env.api_key")
            "sk-xxxxx"
        """
        if not selector or not isinstance(selector, str):
            logger.warning(f"Invalid selector: {selector}")
            return None

        cleaned = selector.strip()
        if not cleaned:
            logger.warning(f"Invalid selector format: {selector}")
            return None

        parts = [part for part in cleaned.split(".") if part]
        if not parts:
            logger.warning(f"Invalid selector format: {selector}")
            return None

        prefix = parts[0]
        remainder = parts[1:]

        # 환경/대화/시스템 변수 별칭
        special_prefix_map = {
            ("env", "environment"): self.get_environment_variable,
            ("conv", "conversation"): self.get_conversation_variable,
            ("sys", "system"): self.get_system_variable,
        }

        for aliases, getter in special_prefix_map.items():
            if prefix in aliases:
                if not remainder:
                    logger.warning(f"Missing key for selector: {selector}")
                    return None
                key = ".".join(remainder)
                return getter(key)

        if len(parts) < 2:
            logger.warning(f"Invalid selector format: {selector}")
            return None

        node_id = prefix
        port_name = parts[1]
        value = self.get_node_output(node_id, port_name)

        if value is None or len(parts) == 2:
            return value

        for attr in parts[2:]:
            value = self._resolve_nested_value(value, attr)
            if value is None:
                break

        return value

    @staticmethod
    def _resolve_nested_value(value: Any, attr: str) -> Optional[Any]:
        """
        dict/list/객체의 중첩 속성과 배열 인덱스를 순회
        """
        if value is None:
            return None

        if isinstance(value, dict):
            return value.get(attr)

        if isinstance(value, list):
            try:
                index = int(attr)
            except (TypeError, ValueError):
                logger.warning(f"List index must be integer, got '{attr}'")
                return None
            if index < 0 or index >= len(value):
                logger.warning(f"List index out of range: {index}")
                return None
            return value[index]

        if hasattr(value, attr):
            return getattr(value, attr)

        return None

    def resolve_value_selectors(self, selectors: List[str]) -> List[Any]:
        """
        여러 ValueSelector를 한 번에 해석

        Args:
            selectors: ValueSelector 문자열 리스트

        Returns:
            해석된 값 리스트

        Example:
            >>> pool.resolve_value_selectors(["start-1.query", "knowledge-1.context"])
            ["사용자 질문", "검색된 문서"]
        """
        return [self.resolve_value_selector(s) for s in selectors]

    # ========== 환경 변수 관리 ==========

    def get_environment_variable(self, key: str) -> Optional[Any]:
        """
        환경 변수 조회

        Args:
            key: 변수 키

        Returns:
            변수 값 또는 None
        """
        return self._environment_variables.get(key)

    def set_environment_variable(self, key: str, value: Any) -> None:
        """
        환경 변수 설정

        Args:
            key: 변수 키
            value: 변수 값
        """
        self._environment_variables[key] = value
        logger.debug(f"Set environment variable: {key}")

    def get_all_environment_variables(self) -> Dict[str, Any]:
        """모든 환경 변수 조회"""
        return self._environment_variables.copy()

    # ========== 대화 변수 관리 ==========

    def get_conversation_variable(self, key: str) -> Optional[Any]:
        """
        대화 변수 조회

        Args:
            key: 변수 키

        Returns:
            변수 값 또는 None
        """
        return self._conversation_variables.get(key)

    def set_conversation_variable(self, key: str, value: Any) -> None:
        """
        대화 변수 설정

        Args:
            key: 변수 키
            value: 변수 값
        """
        self._conversation_variables[key] = value
        self._conversation_dirty.add(key)
        logger.debug(f"Set conversation variable: {key}")

    def get_all_conversation_variables(self) -> Dict[str, Any]:
        """모든 대화 변수 조회"""
        return self._conversation_variables.copy()

    def get_dirty_conversation_variables(self) -> Dict[str, Any]:
        """
        최근 변경된 대화 변수 조회
        """
        return {
            key: self._conversation_variables[key]
            for key in self._conversation_dirty
            if key in self._conversation_variables
        }

    def clear_conversation_variable_dirty(self) -> None:
        """대화 변수 변경 플래그 초기화"""
        self._conversation_dirty.clear()

    # ========== 시스템 변수 관리 ==========

    def get_system_variable(self, key: str) -> Optional[Any]:
        """
        시스템 변수 조회

        Args:
            key: 변수 키

        Returns:
            변수 값 또는 None
        """
        return self._system_variables.get(key)

    def set_system_variable(self, key: str, value: Any) -> None:
        """
        시스템 변수 설정

        Args:
            key: 변수 키
            value: 변수 값
        """
        self._system_variables[key] = value
        logger.debug(f"Set system variable: {key}")

    def get_all_system_variables(self) -> Dict[str, Any]:
        """모든 시스템 변수 조회"""
        return self._system_variables.copy()

    # ========== 템플릿 렌더링 ==========

    def convert_template(self, template: str) -> Tuple["SegmentGroup", Dict[str, Any]]:
        """
        템플릿 문자열을 렌더링하여 변수를 실제 값으로 치환 (Dify 호환 API)

        템플릿 문법:
        - {{ node_id.port_name }}: 노드 출력 참조
        - {{#node_id.port_name#}}: Dify 스타일 변수 참조
        - {{ conv.variable_name }}: 대화 변수 참조
        - {{ env.variable_name }}: 환경 변수 참조
        - {{ sys.variable_name }}: 시스템 변수 참조

        Args:
            template: 렌더링할 템플릿 문자열

        Returns:
            Tuple[SegmentGroup, Dict[str, Any]]:
                - SegmentGroup: 렌더링된 결과 (text/markdown 속성 제공)
                - Dict: 렌더링 메타데이터 (used_variables, output_length 등)

        Raises:
            TemplateRenderError: 템플릿이 비어있거나 변수를 찾을 수 없는 경우

        Example:
            >>> pool = VariablePool()
            >>> pool.set_node_output("llm-1", "response", "안녕하세요")
            >>> result, metadata = pool.convert_template("답변: {{ llm-1.response }}")
            >>> result.text
            "답변: 안녕하세요"
            >>> metadata["variable_count"]
            1
        """
        from app.core.workflow.nodes_v2.utils.template_renderer import TemplateRenderer

        return TemplateRenderer.render(template, self)

    # ========== 유틸리티 ==========

    def clear_node_outputs(self) -> None:
        """모든 노드 출력 초기화"""
        self._node_outputs.clear()
        logger.debug("Cleared all node outputs")

    def to_dict(self) -> Dict[str, Any]:
        """
        변수 풀을 딕셔너리로 변환

        Returns:
            전체 변수 상태
        """
        return {
            "node_outputs": self._node_outputs,
            "environment_variables": self._environment_variables,
            "conversation_variables": self._conversation_variables,
            "system_variables": self._system_variables
        }

    def __repr__(self) -> str:
        return (
            f"VariablePool("
            f"nodes={len(self._node_outputs)}, "
            f"env={len(self._environment_variables)}, "
            f"conv={len(self._conversation_variables)}, "
            f"sys={len(self._system_variables)})"
        )
