"""
Template Transform Node V2
Jinja2 템플릿을 사용하여 데이터 변환하는 워크플로우 노드
"""
import logging
from typing import Any, Dict, Optional

from jinja2 import Environment, TemplateError, select_autoescape, StrictUndefined

from app.core.workflow.base_node_v2 import (
    BaseNodeV2,
    NodeExecutionContext,
    NodePortSchema,
    PortDefinition,
    PortType,
)

logger = logging.getLogger(__name__)


class TemplateTransformNodeV2(BaseNodeV2):
    """
    템플릿 변환 노드

    Jinja2 템플릿을 사용하여 데이터를 원하는 형식으로 변환합니다.
    워크플로우의 변수들을 템플릿에 전달하여 동적으로 텍스트를 생성할 수 있습니다.
    """

    def get_port_schema(self) -> NodePortSchema:
        """포트 스키마 정의"""
        return NodePortSchema(
            inputs=[
                PortDefinition(
                    name="template",
                    type=PortType.STRING,
                    required=False,
                    description="Jinja2 템플릿 문자열 (예: Hello {{name}}!)"
                ),
                PortDefinition(
                    name="variables",
                    type=PortType.OBJECT,
                    required=False,
                    description="템플릿에 전달할 추가 변수 (JSON 객체)"
                ),
            ],
            outputs=[
                PortDefinition(
                    name="output",
                    type=PortType.STRING,
                    description="렌더링된 결과 텍스트"
                ),
                PortDefinition(
                    name="length",
                    type=PortType.NUMBER,
                    description="출력 텍스트 길이"
                ),
                PortDefinition(
                    name="success",
                    type=PortType.BOOLEAN,
                    description="렌더링 성공 여부"
                ),
                PortDefinition(
                    name="error",
                    type=PortType.STRING,
                    description="에러 메시지 (실패 시)"
                ),
            ]
        )

    async def execute_v2(self, context: NodeExecutionContext) -> Dict[str, Any]:
        """
        템플릿 렌더링 실행

        Args:
            context: 노드 실행 컨텍스트

        Returns:
            렌더링된 결과 딕셔너리
        """
        # 입력 수집 (config 우선, 없으면 포트 입력 사용)
        template_str = self.config.get("template") or context.get_input("template")
        additional_vars = self.config.get("variables") or context.get_input("variables") or {}

        # 타입 검증 및 변환
        if template_str is not None and not isinstance(template_str, str):
            template_str = str(template_str)

        if not template_str:
            error_msg = "템플릿 문자열이 비어있습니다"
            logger.error(f"[TemplateTransformNode] {error_msg}")
            return {
                "output": "",
                "length": 0,
                "success": False,
                "error": error_msg,
            }

        logger.info(
            f"[TemplateTransformNode] 템플릿 렌더링 시작 "
            f"(템플릿 길이: {len(template_str)}자, 추가 변수: {len(additional_vars) if isinstance(additional_vars, dict) else 0}개)"
        )

        # Jinja2 환경 설정
        env = Environment(
            autoescape=select_autoescape(['html', 'xml']),
            trim_blocks=True,
            lstrip_blocks=True,
            undefined=StrictUndefined  # 정의되지 않은 변수 사용 시 에러 발생
        )

        # 커스텀 필터 추가
        def from_json_filter(value):
            """JSON 문자열을 Python 객체로 변환"""
            if isinstance(value, str):
                import json
                return json.loads(value)
            return value

        env.filters['from_json'] = from_json_filter

        try:
            # 템플릿 컴파일
            template = env.from_string(template_str)

            # 렌더링 컨텍스트 구성
            # NodeExecutionContext의 모든 변수 + 추가 변수
            render_context = {}

            # 컨텍스트에서 사용 가능한 모든 변수 추가
            # (이전 노드들의 출력 등)
            if hasattr(context, 'variable_pool'):
                # Variable pool에서 모든 변수 가져오기
                try:
                    all_vars_dict = context.variable_pool.to_dict()
                    # node_outputs를 최상위로 병합 (Jinja2 템플릿에서 node.port 형식으로 접근)
                    render_context.update(all_vars_dict.get("node_outputs", {}))
                    render_context.update(all_vars_dict.get("environment_variables", {}))
                    render_context.update(all_vars_dict.get("system_variables", {}))
                    render_context.update(all_vars_dict.get("conversation_variables", {}))
                except Exception as e:
                    logger.warning(f"[TemplateTransformNode] Variable pool 접근 실패: {e}")

            # 추가 변수 병합 (우선순위 높음)
            if additional_vars:
                render_context.update(additional_vars)

            # 렌더링 실행
            result = template.render(**render_context)

            logger.info(
                f"[TemplateTransformNode] 렌더링 성공 "
                f"(결과 길이: {len(result)}자)"
            )

            return {
                "output": result,
                "length": len(result),
                "success": True,
                "error": "",
            }

        except TemplateError as e:
            error_msg = f"템플릿 렌더링 실패: {str(e)}"
            logger.error(f"[TemplateTransformNode] {error_msg}")
            return {
                "output": "",
                "length": 0,
                "success": False,
                "error": error_msg,
            }

        except Exception as e:
            error_msg = f"예상치 못한 오류: {str(e)}"
            logger.error(f"[TemplateTransformNode] {error_msg}", exc_info=True)
            return {
                "output": "",
                "length": 0,
                "success": False,
                "error": error_msg,
            }

    def validate(self) -> tuple[bool, Optional[str]]:
        """노드 설정 검증"""
        # 템플릿은 config 또는 variable_mappings 중 하나에 있어야 함
        has_template_in_config = bool(self.config.get("template"))
        has_template_in_mappings = "template" in self.variable_mappings

        if not (has_template_in_config or has_template_in_mappings):
            return False, "템플릿은 config 또는 variable_mappings에 설정되어야 합니다"

        # 템플릿이 config에 있는 경우 문자열인지 확인
        if has_template_in_config:
            template = self.config.get("template")
            if not isinstance(template, str):
                return False, "템플릿은 문자열이어야 합니다"

        return True, None
