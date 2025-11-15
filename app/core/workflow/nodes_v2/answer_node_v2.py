"""
워크플로우 V2 Answer 노드

워크플로우의 최종 응답을 생성하는 노드입니다.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Literal
from app.core.workflow.base_node_v2 import BaseNodeV2, NodeExecutionContext
from app.schemas.workflow import NodePortSchema, PortDefinition, PortType
import logging

logger = logging.getLogger(__name__)


class AnswerNodeV2(BaseNodeV2):
    """
    포트 기반 V2 Answer 노드.
    입력 포트는 없으며 final_output 문자열을 출력한다.
    """

    def __init__(
        self,
        node_id: str,
        config: Optional[Dict[str, Any]] = None,
        variable_mappings: Optional[Dict[str, Any]] = None
    ):
        super().__init__(node_id=node_id, config=config, variable_mappings=variable_mappings)
        self.template: str = (config or {}).get("template", "")
        self.description: Optional[str] = (config or {}).get("description")
        self.output_format: Literal["text", "json"] = (config or {}).get("output_format", "text")

    def get_port_schema(self) -> NodePortSchema:
        """입출력 포트 스키마 정의"""
        return NodePortSchema(
            inputs=[],
            outputs=[
                PortDefinition(
                    name="final_output",
                    type=PortType.STRING,
                    required=True,
                    description="최종 렌더링된 응답 문자열",
                    display_name="최종 출력"
                )
            ]
        )

    async def execute_v2(self, context: NodeExecutionContext) -> Dict[str, Any]:
        """
        Phase 2의 템플릿 렌더링 로직을 호출해 문자열을 생성한다.
        BaseNodeV2.execute가 NodeExecutionResult로 감쌈을 처리하므로
        여기서는 dict만 반환한다.
        """
        # Phase 2에서 TemplateRenderer 적용 예정 (stub)
        rendered = self.template or ""
        return {"final_output": rendered}
