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

        return {
            "query": user_message,
            "session_id": session_id
        }

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

    def get_required_services(self) -> List[str]:
        """필요한 서비스 없음"""
        return []
