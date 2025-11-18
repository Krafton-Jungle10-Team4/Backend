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
        실행 경로상의 노드들의 변수 셀렉터 목록 계산 (Answer 노드 전용)

        개선 사항:
        1. 실제 VariablePool에 존재하는 변수만 반환
        2. 실행 경로에 있는 노드의 실제 출력 포트만 허용
        3. 템플릿에서 실제로 사용되는 변수만 포함

        실행 플로우를 따라 도달한 모든 노드들의 출력 변수를 사용할 수 있도록 허용합니다.
        템플릿 내부에서 사용되는 변수도 자동으로 허용 목록에 추가합니다.
        """
        from app.core.workflow.nodes_v2.utils.variable_template_parser import VariableTemplateParser

        allowed = []

        # 1. 템플릿에서 실제로 사용되는 변수 추출 (우선순위 1)
        template_selectors = []
        if self.template:
            parser = VariableTemplateParser(self.template)
            template_selectors = parser.extract_variable_selectors()
            # 템플릿에서 사용된 변수는 무조건 허용 (실제 사용 중이므로)
            allowed.extend(template_selectors)

        # 2. 실행 경로상의 노드들의 실제 출력 포트만 허용
        if hasattr(context, 'executed_nodes') and context.executed_nodes:
            logger.debug(f"[AnswerNodeV2] 실행 경로상의 노드들: {context.executed_nodes}")

            for node_id in context.executed_nodes:
                # VariablePool에 실제로 존재하는 출력 포트만 허용
                if context.variable_pool.has_node_output(node_id):
                    node_outputs = context.variable_pool.get_all_node_outputs(node_id)
                    for port_name in node_outputs.keys():
                        selector = f"{node_id}.{port_name}"
                        if selector not in allowed:
                            allowed.append(selector)

        # 3. variable_mappings에 정의된 셀렉터들도 추가
        for port_name, selector in self.variable_mappings.items():
            if selector:
                if isinstance(selector, str):
                    if selector not in allowed:
                        allowed.append(selector)
                elif isinstance(selector, dict):
                    var_selector = selector.get("variable")
                    if var_selector and var_selector not in allowed:
                        allowed.append(var_selector)

        # 4. 자기 자신의 입력 포트도 허용 (self.port_name 형식)
        for port_name in self.get_input_port_names():
            self_selector = f"self.{port_name}"
            if self_selector not in allowed:
                allowed.append(self_selector)

        logger.info(
            f"🔍 AnswerNodeV2 {self.node_id} allowed selectors: "
            f"{len(allowed)}개 (템플릿 변수: {len(template_selectors)}개)"
        )
        if len(allowed) > 20:
            logger.debug(f"   처음 20개: {allowed[:20]}...")
        else:
            logger.debug(f"   전체: {allowed}")
        
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
        logger.debug(f"🔑 allowed_selectors ({len(allowed_selectors)}개): {allowed_selectors[:10]}..." if len(allowed_selectors) > 10 else f"🔑 allowed_selectors: {allowed_selectors}")

        # 템플릿에서 실제로 사용되는 변수만 확인 (디버그용)
        from app.core.workflow.nodes_v2.utils.variable_template_parser import VariableTemplateParser
        if self.template:
            parser = VariableTemplateParser(self.template)
            template_selectors = parser.extract_variable_selectors()
            for selector in template_selectors:
                if selector.startswith("self."):
                    continue
                try:
                    parts = selector.split(".")
                    if len(parts) == 2:
                        node_id, port_name = parts
                        if context.variable_pool.has_node_output(node_id, port_name):
                            value = context.variable_pool.get_node_output(node_id, port_name)
                            logger.debug(f"✅ 템플릿 변수 {selector} 존재: {str(value)[:50]}...")
                        else:
                            logger.warning(
                                f"⚠️ 템플릿 변수 '{selector}'가 VariablePool에 없습니다. "
                                f"실행 경로: {context.executed_nodes if hasattr(context, 'executed_nodes') else 'N/A'}"
                            )
                except Exception as e:
                    logger.error(f"❌ 템플릿 변수 '{selector}' 확인 중 에러: {e}")

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
