"""
템플릿 렌더링 엔진

Dify 호환 템플릿 문법을 지원하는 렌더링 엔진입니다.
변수 치환, 타입 변환, 에러 처리를 수행합니다.
"""

import json
import re
from typing import Any, Dict, List, Tuple
import logging

from app.core.workflow.variable_pool import VariablePool

logger = logging.getLogger(__name__)


class TemplateRenderError(Exception):
    """템플릿 렌더링 중 발생하는 예외"""
    pass


class TemplateRenderer:
    """
    Dify 호환 템플릿 렌더러
    - {{node.port}} / {{ sys.var }} / {{#node.port#}} 문법 지원
    - 공백 포함 패턴 허용
    """

    # {{...}} 또는 {{#...#}} 패턴 매칭 (공백 허용)
    PATTERN_GENERIC = re.compile(r"\{\{\s*(#?)([^{}\n]+?)\s*(#?)\}\}")
    MAX_TEMPLATE_LENGTH = 20 * 1024  # 20KB
    MAX_VARIABLES = 100

    @staticmethod
    def parse_template(template: str) -> List[str]:
        """
        템플릿에서 모든 변수 참조를 추출

        Args:
            template: 템플릿 문자열

        Returns:
            변수 참조 리스트 (중복 제거, 순서 유지)

        Raises:
            TemplateRenderError: 템플릿이 너무 길거나 변수가 너무 많은 경우

        Example:
            >>> TemplateRenderer.parse_template("Hello {{name}}, you have {{count}} messages")
            ["name", "count"]
        """
        if len(template) > TemplateRenderer.MAX_TEMPLATE_LENGTH:
            raise TemplateRenderError(
                f"템플릿 길이가 최대 {TemplateRenderer.MAX_TEMPLATE_LENGTH}자를 초과했습니다"
            )

        variables: List[str] = []
        for match in TemplateRenderer.PATTERN_GENERIC.finditer(template):
            # match.group(2)는 실제 변수명 (중간 그룹)
            candidate = match.group(2).strip()
            if candidate:
                variables.append(candidate)

        if len(variables) > TemplateRenderer.MAX_VARIABLES:
            raise TemplateRenderError(
                f"템플릿의 변수 수가 최대 {TemplateRenderer.MAX_VARIABLES}개를 초과했습니다"
            )

        # 입력 순서를 유지하면서 중복 제거 (dict.fromkeys 사용)
        return list(dict.fromkeys(variables))

    @staticmethod
    def render(template: str, variable_pool: VariablePool) -> Tuple[str, Dict[str, Any]]:
        """
        템플릿을 렌더링하여 변수를 실제 값으로 치환

        Args:
            template: 템플릿 문자열
            variable_pool: 변수 풀 객체

        Returns:
            (렌더링된 문자열, 메타데이터)

        Raises:
            TemplateRenderError: 템플릿이 비어있거나 변수를 찾을 수 없는 경우

        Example:
            >>> pool = VariablePool()
            >>> pool.set_node_output("start", "query", "Hello")
            >>> rendered, meta = TemplateRenderer.render("Query: {{start.query}}", pool)
            >>> print(rendered)
            "Query: Hello"
        """
        if not template or template.strip() == "":
            raise TemplateRenderError("템플릿이 비어있습니다")

        rendered = template
        used_variables: Dict[str, str] = {}

        # 템플릿에서 변수 추출
        variable_refs = TemplateRenderer.parse_template(template)

        for var_ref in variable_refs:
            # VariablePool에서 값 해결
            value = variable_pool.resolve_value_selector(var_ref)

            if value is None:
                raise TemplateRenderError(f"변수 '{var_ref}'를 찾을 수 없습니다")

            # 타입별 문자열 변환
            str_value = TemplateRenderer._convert_to_string(value)

            # 정규식으로 모든 패턴 치환
            # {{var_ref}}, {{ var_ref }}, {{#var_ref#}}, {{# var_ref #}} 모두 처리
            pattern = r"\{\{\s*#?\s*" + re.escape(var_ref) + r"\s*#?\s*\}\}"
            rendered = re.sub(pattern, str_value, rendered)

            # 메타데이터에 사용된 변수 기록
            used_variables[var_ref] = type(value).__name__

        # 렌더링 메타데이터
        metadata = {
            "used_variables": used_variables,
            "template_length": len(template),
            "output_length": len(rendered),
            "variable_count": len(used_variables),
        }

        logger.debug(
            f"Template rendered: {len(used_variables)} variables, "
            f"{len(template)} -> {len(rendered)} chars"
        )

        return rendered, metadata

    @staticmethod
    def _convert_to_string(value: Any) -> str:
        """
        다양한 타입을 문자열로 변환

        Args:
            value: 변환할 값

        Returns:
            문자열로 변환된 값

        Conversion Rules:
            - None -> ""
            - str -> 그대로 반환
            - int, float, bool -> str() 변환
            - dict, list -> JSON 문자열 (indent=2, ensure_ascii=False)
            - File 객체 -> "File(name=..., size=...)"
            - 기타 -> repr() 사용

        Example:
            >>> TemplateRenderer._convert_to_string({"key": "value"})
            '{\\n  "key": "value"\\n}'
        """
        if value is None:
            return ""

        if isinstance(value, str):
            return value

        if isinstance(value, (int, float, bool)):
            return str(value)

        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False, indent=2)

        # 파일/바이너리 객체 등
        # File 객체는 일반적으로 name, size 속성을 가짐
        name = getattr(value, "name", None)
        size = getattr(value, "size", None)

        if name:
            suffix = f", size={size} bytes" if size is not None else ""
            return f"File(name={name}{suffix})"

        # 기타 객체는 repr() 사용
        return repr(value)
