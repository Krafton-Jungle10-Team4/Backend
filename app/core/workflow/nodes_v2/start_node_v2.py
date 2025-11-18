"""
워크플로우 V2 시작 노드

사용자 입력을 받아 워크플로우를 시작하는 노드입니다.
"""

from __future__ import annotations

from typing import Any, Dict, List
from app.core.workflow.base_node_v2 import BaseNodeV2, NodeExecutionContext
from app.schemas.workflow import NodePortSchema, PortDefinition, PortType
import logging

logger = logging.getLogger(__name__)


class StartNodeV2(BaseNodeV2):
    """
    워크플로우 V2 시작 노드

    사용자 메시지를 입력으로 받아 query 포트로 출력합니다.
    워크플로우의 진입점 역할을 합니다.

    출력 포트:
        - query (STRING): 사용자 질문/메시지
        - session_id (STRING): 세션 ID
    """

    def get_port_schema(self) -> NodePortSchema:
        """
        포트 스키마 정의

        Returns:
            NodePortSchema: 입력 없음, 출력 2개 (query, session_id)
        """
        custom_ports = self.config.get("ports") or {}

        def _safe_parse_ports(port_list):
            parsed: List[PortDefinition] = []
            for port in port_list or []:
                try:
                    parsed.append(PortDefinition.model_validate(port))
                except Exception:
                    name = port.get("name") if isinstance(port, dict) else None
                    if not name:
                        continue
                    parsed.append(
                        PortDefinition(
                            name=name,
                            type=PortType(port.get("type", PortType.ANY.value))
                            if isinstance(port, dict) and port.get("type")
                            else PortType.ANY,
                            required=bool(port.get("required", False)) if isinstance(port, dict) else False,
                            description=port.get("description", "") if isinstance(port, dict) else "",
                            display_name=port.get("display_name", name) if isinstance(port, dict) else name,
                        )
                    )
            return parsed

        custom_outputs = _safe_parse_ports(custom_ports.get("outputs"))
        if custom_outputs:
            return NodePortSchema(inputs=[], outputs=custom_outputs)

        custom_output_schema = _safe_parse_ports(self.config.get("output_schema"))
        if custom_output_schema:
            return NodePortSchema(inputs=[], outputs=custom_output_schema)

        return NodePortSchema(
            inputs=[],  # 시작 노드는 입력 없음
            outputs=[
                PortDefinition(
                    name="query",
                    type=PortType.STRING,
                    required=True,
                    description="사용자 질문 또는 메시지",
                    display_name="사용자 질문"
                ),
                PortDefinition(
                    name="session_id",
                    type=PortType.STRING,
                    required=False,
                    description="세션 식별자",
                    display_name="세션 ID"
                )
            ]
        )

    async def execute_v2(self, context: NodeExecutionContext) -> Dict[str, Any]:
        """
        시작 노드 실행

        Args:
            context: 실행 컨텍스트

        Returns:
            Dict[str, Any]: {query: 사용자메시지, session_id: 세션ID}

        Raises:
            ValueError: user_message가 없을 때
        """
        # Pre-seeded outputs (nested workflow input)
        preseeded = context.variable_pool.get_all_node_outputs(self.node_id)
        if preseeded:
            session_id = context.variable_pool.get_system_variable("session_id")
            if session_id is not None:
                preseeded.setdefault("session_id", session_id)
            logger.info(f"StartNodeV2 {self.node_id} uses pre-seeded outputs")
            return preseeded

        # 시스템 변수에서 user_message 조회
        user_message = context.variable_pool.get_system_variable("user_message")
        if not user_message:
            raise ValueError("user_message not found in system variables")

        session_id = context.variable_pool.get_system_variable("session_id")

        logger.info(f"StartNodeV2 executed: session={session_id}")

        port_schema = self.get_port_schema()
        port_bindings = self.config.get("port_bindings", {}) or {}

        resolved_outputs: Dict[str, Any] = {}
        for port in port_schema.outputs:
            name = port.name
            if not name:
                continue
            binding = port_bindings.get(name)
            value = self._resolve_port_binding(binding, user_message, session_id)

            if value is None:
                if name == "query":
                    value = user_message
                elif name == "session_id":
                    value = session_id

            resolved_outputs[name] = value

        return resolved_outputs

    def validate(self) -> tuple[bool, Optional[str]]:
        """
        시작 노드 검증

        Returns:
            tuple: (유효 여부, 오류 메시지)
        """
        # 시작 노드는 입력이 없어야 함
        if self.variable_mappings:
            return False, "Start node should not have input mappings"

        return True, None

    @staticmethod
    def _resolve_port_binding(binding: Optional[Dict[str, Any]], user_message: Optional[str], session_id: Optional[str]) -> Any:
        if not binding or not isinstance(binding, dict):
            return None

        binding_type = binding.get("type")
        if binding_type == "user_message":
            return user_message
        if binding_type == "session_id":
            return session_id
        if binding_type == "literal":
            return binding.get("value")

        # 향후 확장을 위한 기본 동작: 인라인 value 우선
        if "value" in binding:
            return binding.get("value")
        return None

    def get_required_services(self) -> List[str]:
        """필요한 서비스 없음"""
        return []
