"""
워크플로우 V2 종료 노드

워크플로우의 최종 결과를 반환하는 노드입니다.
"""

from typing import Any, Dict, List, Optional
from app.core.workflow.base_node_v2 import BaseNodeV2, NodeExecutionContext
from app.schemas.workflow import NodePortSchema, PortDefinition, PortType
import logging

logger = logging.getLogger(__name__)


class EndNodeV2(BaseNodeV2):
    """
    워크플로우 V2 종료 노드

    워크플로우의 최종 결과를 수집하고 반환합니다.

    입력 포트:
        - response (STRING): 최종 응답 텍스트

    출력 포트:
        - final_output (OBJECT): 최종 결과 객체
    """

    def get_port_schema(self) -> NodePortSchema:
        """
        포트 스키마 정의

        Returns:
            NodePortSchema: 입력 1개 (response), 출력 1개 (final_output)
        """
        return NodePortSchema(
            inputs=[
                PortDefinition(
                    name="response",
                    type=PortType.STRING,
                    required=True,
                    description="최종 응답 텍스트",
                    display_name="응답"
                )
            ],
            outputs=[
                PortDefinition(
                    name="final_output",
                    type=PortType.OBJECT,
                    required=True,
                    description="최종 결과 객체",
                    display_name="최종 결과"
                )
            ]
        )

    async def execute_v2(self, context: NodeExecutionContext) -> Dict[str, Any]:
        """
        종료 노드 실행

        Args:
            context: 실행 컨텍스트

        Returns:
            Dict[str, Any]: {final_output: 최종결과객체}

        Raises:
            ValueError: 필수 입력이 없을 때
        """
        # 입력 조회
        response = context.get_input("response")
        if response is None:
            raise ValueError("response input is required")

        # 추가 메타데이터 수집 (선택적)
        session_id = context.variable_pool.get_system_variable("session_id")

        # 실행 통계 수집 (옵션)
        all_outputs = {}
        for node_id in context.variable_pool._node_outputs.keys():
            node_outputs = context.variable_pool.get_all_node_outputs(node_id)
            if node_outputs:
                all_outputs[node_id] = node_outputs

        logger.info(f"EndNodeV2: Workflow completed for session {session_id}")

        # 최종 결과 구성
        final_output = {
            "response": response,
            "session_id": session_id,
            "metadata": {
                "node_count": len(all_outputs),
                "execution_complete": True
            }
        }

        return {
            "final_output": final_output
        }

    def validate(self) -> tuple[bool, Optional[str]]:
        """
        종료 노드 검증

        Returns:
            tuple: (유효 여부, 오류 메시지)
        """
        # response 입력이 매핑되어 있는지 확인
        if "response" not in self.variable_mappings:
            return False, "response input must be mapped"

        return True, None

    def get_required_services(self) -> List[str]:
        """필요한 서비스 없음"""
        return []
