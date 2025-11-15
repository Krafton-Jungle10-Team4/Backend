"""
Variable template parser

LLM/Answer/HTTP 노드 등의 템플릿에서 사용된 변수 selector를 추출한다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, List


_VARIABLE_PATTERN = re.compile(r"\{\{\s*(#?)([^{}\n]+?)\s*(#?)\}\}")


@dataclass(frozen=True)
class VariableMatch:
    """단일 템플릿 변수 매치."""

    selector: str
    start: int
    end: int


class VariableTemplateParser:
    """
    템플릿 문자열에서 `{{ selector }}` / `{{#selector#}}` 형태의 변수를 추출하는 파서.
    """

    def __init__(self, template: str) -> None:
        self.template = template or ""

    def parse(self) -> List[VariableMatch]:
        """
        템플릿을 순회하며 변수 매치를 반환한다.
        """
        matches: List[VariableMatch] = []
        for match in _VARIABLE_PATTERN.finditer(self.template):
            selector = (match.group(2) or "").strip()
            if not selector:
                continue
            matches.append(
                VariableMatch(
                    selector=selector,
                    start=match.start(),
                    end=match.end(),
                )
            )
        return matches

    def extract_variable_selectors(self) -> List[str]:
        """
        템플릿에 등장하는 변수 selector 목록을 반환한다. (중복 제거, 순서 유지)
        """
        selectors: List[str] = []
        seen = set()
        for match in self.parse():
            if match.selector not in seen:
                seen.add(match.selector)
                selectors.append(match.selector)
        return selectors

    def iter_matches(self) -> Iterable[VariableMatch]:
        """
        generator 형태로 matcher를 순회하고 싶을 때 사용.
        """
        yield from self.parse()
