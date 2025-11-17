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
            inputs=[
                PortDefinition(
                    name="target",
                    type=PortType.ANY,
                    required=False,
                    description="이전 노드로부터의 연결 (실행 순서 보장용)",
                    display_name="입력"
                )
            ],
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

    def _compute_allowed_selectors(self, context: NodeExecutionContext) -> list[str]:
        """
        연결된 노드의 변수 셀렉터 목록 계산 (Answer 노드 전용)

        템플릿 내부에서 사용되는 변수도 자동으로 허용 목록에 추가합니다.
        """
        from app.core.workflow.nodes_v2.utils.variable_template_parser import VariableTemplateParser

        # 기본 allowed_selectors (variable_mappings 기반)
        allowed = super()._compute_allowed_selectors(context)

        # 템플릿에서 사용된 변수 추출하여 추가
        if self.template:
            parser = VariableTemplateParser(self.template)
            template_selectors = parser.extract_variable_selectors()
            allowed.extend(template_selectors)

        logger.info(f"🔍 AnswerNodeV2 {self.node_id} allowed selectors: {allowed}")
        return allowed

    async def execute_v2(self, context: NodeExecutionContext) -> Dict[str, Any]:
        """
        템플릿을 렌더링하여 최종 응답 생성.
        BaseNodeV2.execute가 status/metadata를 래핑하므로 Dict만 반환한다.
        """
        import time
        from app.core.workflow.nodes_v2.utils.template_renderer import TemplateRenderer

        start_time = time.time()

        # 연결된 노드의 변수만 허용하도록 셀렉터 목록 계산
        # 템플릿 내부 변수도 자동으로 포함됨
        allowed_selectors = self._compute_allowed_selectors(context)

        logger.info(f"🎨 AnswerNodeV2 템플릿: {self.template[:100]}...")
        logger.info(f"🔑 allowed_selectors: {allowed_selectors}")

        # VariablePool에 실제로 값이 있는지 확인
        for selector in allowed_selectors:
            if selector.startswith("self."):
                continue
            try:
                parts = selector.split(".")
                if len(parts) == 2:
                    node_id, port_name = parts
                    if context.variable_pool.has_node_output(node_id, port_name):
                        value = context.variable_pool.get_node_output(node_id, port_name)
                        logger.info(f"✅ VariablePool에 {selector} 존재: {str(value)[:100]}...")
                    else:
                        logger.warning(f"❌ VariablePool에 {selector} 없음!")
            except Exception as e:
                logger.error(f"❌ {selector} 확인 중 에러: {e}")

        # 템플릿 렌더링 (연결 검증 포함)
        rendered_group, metadata = TemplateRenderer.render(
            self.template,
            context.variable_pool,
            allowed_selectors=allowed_selectors
        )

        # 실행 시간 메타데이터는 context.metadata에 저장하여
        # executor가 NodeExecutionResult(metadata=...)에 병합하도록 한다.
        if not hasattr(context, 'metadata'):
            context.metadata = {}

        context.metadata.setdefault("answer", {})[self.node_id] = {
            **metadata,
            "rendering_time_ms": int((time.time() - start_time) * 1000),
        }

        logger.info(
            f"Answer node {self.node_id} rendered: "
            f"{metadata['variable_count']} variables, "
            f"{metadata['output_length']} chars"
        )

        return {"final_output": rendered_group.text}
