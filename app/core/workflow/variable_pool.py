"""
워크플로우 V2 변수 풀

노드 간 데이터 전달을 위한 중앙 집중식 변수 관리 시스템입니다.
포트 기반 데이터 흐름을 지원하며, ValueSelector를 통해 다른 노드의 출력을 참조할 수 있습니다.
"""

from typing import Any, Dict, Optional, List
from app.schemas.workflow import PortType
import logging

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
        - env.{var_name}: 환경 변수 참조
        - conv.{var_name}: 대화 변수 참조
        - sys.{var_name}: 시스템 변수 참조

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

        parts = selector.split(".", 1)
        if len(parts) != 2:
            logger.warning(f"Invalid selector format: {selector}")
            return None

        prefix, name = parts

        # 환경 변수
        if prefix == "env":
            return self.get_environment_variable(name)

        # 대화 변수
        if prefix == "conv":
            return self.get_conversation_variable(name)

        # 시스템 변수
        if prefix == "sys":
            return self.get_system_variable(name)

        # 노드 출력 (prefix가 node_id)
        return self.get_node_output(prefix, name)

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
        logger.debug(f"Set conversation variable: {key}")

    def get_all_conversation_variables(self) -> Dict[str, Any]:
        """모든 대화 변수 조회"""
        return self._conversation_variables.copy()

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
