"""
종료 노드 구현

워크플로우의 종료점을 나타내는 노드입니다.
"""

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


class EndNodeConfig(NodeConfig):
    """종료 노드 설정 (현재는 설정 없음)"""
    pass


@register_node(NodeType.END)
class EndNode(BaseNode[EndNodeConfig]):
    """
    워크플로우 종료 노드

    이전 노드들의 결과를 수집하여 최종 출력을 생성합니다.
    """

    def __init__(
        self,
        node_id: str,
        node_type: NodeType = NodeType.END,
        config: Optional[EndNodeConfig] = None,
        position: Optional[Dict[str, float]] = None
    ):
        super().__init__(node_id, node_type, config, position)

    async def execute(self, context: Dict[str, Any]) -> NodeExecutionResult:
        """
        종료 노드 실행

        Args:
            context: 실행 컨텍스트 (이전 노드 출력 포함)

        Returns:
            NodeExecutionResult: 최종 결과
        """
        try:
            self.set_status(NodeStatus.RUNNING)

            # 이전 노드 출력 수집
            node_outputs = context.get("node_outputs", {})

            # LLM 응답 확인 (일반적으로 LLM 노드의 출력)
            llm_response = None
            for node_id, output in node_outputs.items():
                if isinstance(output, dict) and "llm_response" in output:
                    llm_response = output["llm_response"]
                    break

            if not llm_response:
                # 다른 노드의 출력을 대체 응답으로 사용
                for node_id, output in node_outputs.items():
                    if isinstance(output, dict) and "response" in output:
                        llm_response = output["response"]
                        break

            if not llm_response:
                llm_response = "워크플로우가 완료되었지만 응답을 생성할 수 없습니다."

            result = NodeExecutionResult(
                status=NodeStatus.COMPLETED,
                output={
                    "response": llm_response,
                    "session_id": context.get("session_id"),
                    "metadata": {
                        "total_nodes": len(node_outputs),
                        "workflow_completed": True
                    }
                },
                metadata={
                    "node_id": self.node_id,
                    "node_type": self.node_type.value
                }
            )

            self.set_status(NodeStatus.COMPLETED)
            logger.info(f"Workflow completed for session {context.get('session_id')}")

            return result

        except Exception as e:
            logger.error(f"End node execution failed: {str(e)}")
            self.set_status(NodeStatus.FAILED)
            return NodeExecutionResult(
                status=NodeStatus.FAILED,
                error=str(e)
            )

    def validate(self) -> tuple[bool, Optional[str]]:
        """
        종료 노드 검증

        Returns:
            tuple: (유효 여부, 오류 메시지)
        """
        # 종료 노드는 적어도 하나의 입력이 필요
        if len(self.inputs) == 0:
            return False, "End node must have at least one input"

        # 종료 노드는 출력을 가질 수 없음
        if len(self.outputs) > 0:
            return False, "End node cannot have outputs"

        return True, None

    @classmethod
    def get_schema(cls) -> NodeSchema:
        """
        종료 노드 스키마 반환

        Returns:
            NodeSchema: 노드 스키마
        """
        return NodeSchema(
            type=NodeType.END,
            label="종료",
            icon="stop",
            max_instances=1,
            configurable=False,
            config_schema=None,
            input_required=True,
            output_provided=False
        )

    @classmethod
    def get_config_class(cls) -> type[NodeConfig]:
        """설정 클래스 반환"""
        return EndNodeConfig

    def get_required_context_keys(self) -> list[str]:
        """필요한 컨텍스트 키 목록"""
        return ["node_outputs"]