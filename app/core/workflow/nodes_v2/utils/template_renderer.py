"""
템플릿 렌더링 엔진

Dify 호환 템플릿 문법을 지원하는 렌더링 엔진입니다.
변수 치환, 타입 변환, 에러 처리를 수행합니다.
"""

import json
from typing import Any, Dict, List, Tuple
import logging

from app.core.workflow.variable_pool import VariablePool
from app.core.workflow.nodes_v2.utils.variable_template_parser import (
    VariableTemplateParser,
    VariableMatch,
)

logger = logging.getLogger(__name__)


class TemplateRenderError(Exception):
    """템플릿 렌더링 중 발생하는 예외"""


class Segment:
    """템플릿을 구성하는 단일 조각."""

    def __init__(self, raw_value: Any, value_type: str, literal: bool = False):
        self.raw_value = raw_value
        self.value_type = value_type
        self.literal = literal

    @classmethod
    def literal(cls, text: str) -> "Segment":
        return cls(text, "text", literal=True)

    @classmethod
    def from_value(cls, value: Any) -> "Segment":
        value_type = cls._infer_value_type(value)
        return cls(value, value_type, literal=False)

    @property
    def text(self) -> str:
        if self.literal:
            return str(self.raw_value)
        return TemplateRenderer._convert_to_string(self.raw_value)

    @property
    def markdown(self) -> str:
        if self.literal:
            return str(self.raw_value)
        if self.value_type == "array" and isinstance(self.raw_value, list):
            if not self.raw_value:
                return ""
            lines = [f"- {TemplateRenderer._convert_to_string(item)}" for item in self.raw_value]
            return "\n".join(lines)
        if self.value_type == "object" and isinstance(self.raw_value, dict):
            return json.dumps(self.raw_value, ensure_ascii=False, indent=2)
        return self.text

    def to_metadata(self) -> Dict[str, Any]:
        return {
            "type": self.value_type,
            "length": len(self.text),
        }

    @staticmethod
    def _infer_value_type(value: Any) -> str:
        if value is None:
            return "none"
        if isinstance(value, str):
            return "string"
        if isinstance(value, bool):
            return "boolean"
        if isinstance(value, (int, float)):
            return "number"
        if isinstance(value, list):
            return "array"
        if isinstance(value, dict):
            return "object"
        if getattr(value, "name", None):
            return "file"
        return "string"


class SegmentGroup:
    """여러 Segment를 묶은 그룹."""

    def __init__(self, segments: List[Segment]):
        self.segments = segments

    @property
    def text(self) -> str:
        return "".join(segment.text for segment in self.segments)

    @property
    def markdown(self) -> str:
        return "".join(segment.markdown for segment in self.segments)

    def to_metadata(self) -> Dict[str, Any]:
        return {
            "segment_count": len(self.segments),
            "text_length": len(self.text),
        }


class TemplateRenderer:
    """
    Dify 호환 템플릿 렌더러
    - {{node.port}} / {{ sys.var }} / {{#node.port#}} 문법 지원
    - 공백 포함 패턴 허용
    """

    MAX_TEMPLATE_LENGTH = 20 * 1024  # 20KB
    MAX_VARIABLES = 100

    @staticmethod
    def parse_template(template: str) -> List[str]:
        """
        템플릿에서 모든 변수 참조를 추출
        """
        TemplateRenderer._validate_template_length(template)
        parser = VariableTemplateParser(template)
        selectors = parser.extract_variable_selectors()
        if len(selectors) > TemplateRenderer.MAX_VARIABLES:
            raise TemplateRenderError(
                f"템플릿의 변수 수가 최대 {TemplateRenderer.MAX_VARIABLES}개를 초과했습니다"
            )
        return selectors

    @staticmethod
    def render(template: str, variable_pool: VariablePool) -> Tuple[SegmentGroup, Dict[str, Any]]:
        """
        템플릿을 렌더링하여 변수를 실제 값으로 치환
        """
        if not template or template.strip() == "":
            raise TemplateRenderError("템플릿이 비어있습니다")

        TemplateRenderer._validate_template_length(template)
        parser = VariableTemplateParser(template)
        matches = parser.parse()
        if len(matches) > TemplateRenderer.MAX_VARIABLES:
            raise TemplateRenderError(
                f"템플릿의 변수 수가 최대 {TemplateRenderer.MAX_VARIABLES}개를 초과했습니다"
            )

        segments: List[Segment] = []
        used_variables: Dict[str, str] = {}
        last_index = 0

        for match in matches:
            if match.start > last_index:
                literal_text = template[last_index:match.start]
                if literal_text:
                    segments.append(Segment.literal(literal_text))

            value = variable_pool.resolve_value_selector(match.selector)
            if value is None:
                raise TemplateRenderError(f"변수 '{match.selector}'를 찾을 수 없습니다")

            segment = Segment.from_value(value)
            segments.append(segment)
            used_variables[match.selector] = type(value).__name__
            last_index = match.end

        if last_index < len(template):
            tail_text = template[last_index:]
            if tail_text:
                segments.append(Segment.literal(tail_text))

        segment_group = SegmentGroup(segments)

        metadata = {
            "used_variables": used_variables,
            "template_length": len(template),
            "output_length": len(segment_group.text),
            "variable_count": len(used_variables),
            "segments": [segment.to_metadata() for segment in segments],
        }

        logger.debug(
            "Template rendered: %s variables, %s -> %s chars",
            len(used_variables),
            len(template),
            len(segment_group.text),
        )

        return segment_group, metadata

    @staticmethod
    def _validate_template_length(template: str) -> None:
        if template and len(template) > TemplateRenderer.MAX_TEMPLATE_LENGTH:
            raise TemplateRenderError(
                f"템플릿 길이가 최대 {TemplateRenderer.MAX_TEMPLATE_LENGTH}자를 초과했습니다"
            )

    @staticmethod
    def _convert_to_string(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        if isinstance(value, (int, float, bool)):
            return str(value)
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False, indent=2)

        name = getattr(value, "name", None)
        size = getattr(value, "size", None)
        if name:
            suffix = f", size={size} bytes" if size is not None else ""
            return f"File(name={name}{suffix})"
        return repr(value)
