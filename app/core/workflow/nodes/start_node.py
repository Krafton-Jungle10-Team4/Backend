"""
시작 노드 구현

워크플로우의 시작점을 나타내는 노드입니다.
"""

from __future__ import annotations

from typing import Any, Dict, Optional
from app.core.workflow.base_node import (
    BaseNode,
    NodeType,
    NodeStatus,
    NodeConfig,
    NodeSchema,
    NodeExecutionResult
)
from app.core.workflow.node_registry import register_node
import logging

logger = logging.getLogger(__name__)


class StartNodeConfig(NodeConfig):
    """시작 노드 설정 (현재는 설정 없음)"""
    pass


@register_node(NodeType.START)
class StartNode(BaseNode[StartNodeConfig]):
    """
    워크플로우 시작 노드

    사용자 입력을 받아 다음 노드로 전달합니다.
    """

    def __init__(
        self,
        node_id: str,
        node_type: NodeType = NodeType.START,
        config: Optional[StartNodeConfig] = None,
        position: Optional[Dict[str, float]] = None
    ):
        super().__init__(node_id, node_type, config, position)

    async def execute(self, context: Dict[str, Any]) -> NodeExecutionResult:
        """
        시작 노드 실행

        Args:
            context: 실행 컨텍스트 (user_message 포함)

        Returns:
            NodeExecutionResult: 실행 결과
        """
        try:
            self.set_status(NodeStatus.RUNNING)

            # 사용자 메시지 확인
            user_message = context.get("user_message")
            if not user_message:
                raise ValueError("User message is required in context")

            # 세션 정보 확인
            session_id = context.get("session_id")

            logger.info(f"Starting workflow for session {session_id}")

            result = NodeExecutionResult(
                status=NodeStatus.COMPLETED,
                output={
                    "user_message": user_message,
                    "session_id": session_id
                },
                metadata={
                    "node_id": self.node_id,
                    "node_type": self.node_type.value
                }
            )

            self.set_status(NodeStatus.COMPLETED)
            return result

        except Exception as e:
            logger.error(f"Start node execution failed: {str(e)}")
            self.set_status(NodeStatus.FAILED)
            return NodeExecutionResult(
                status=NodeStatus.FAILED,
                error=str(e)
            )

    def validate(self) -> tuple[bool, Optional[str]]:
        """
        시작 노드 검증

        Returns:
            tuple: (유효 여부, 오류 메시지)
        """
        # 시작 노드는 정확히 하나의 출력만 가져야 함
        if len(self.outputs) == 0:
            return False, "Start node must have at least one output"

        return True, None

    @classmethod
    def get_schema(cls) -> NodeSchema:
        """
        시작 노드 스키마 반환

        Returns:
            NodeSchema: 노드 스키마
        """
        return NodeSchema(
            type=NodeType.START,
            label="시작",
            icon="play",
            max_instances=1,
            configurable=False,
            config_schema=None,
            input_required=False,
            output_provided=True
        )

    @classmethod
    def get_config_class(cls) -> type[NodeConfig]:
        """설정 클래스 반환"""
        return StartNodeConfig

    def get_required_context_keys(self) -> list[str]:
        """필요한 컨텍스트 키 목록"""
        return ["user_message", "session_id"]