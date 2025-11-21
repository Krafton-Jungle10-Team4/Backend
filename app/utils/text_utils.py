"""
텍스트 처리 유틸리티
"""
from __future__ import annotations

import re

# 사전 컴파일된 정규식
HEADER_PATTERN = re.compile(r"(?m)^\s{0,3}#{1,6}\s*")
LINK_PATTERN = re.compile(r"\[(.*?)\]\((.*?)\)")
IMAGE_PATTERN = re.compile(r"!\[(.*?)\]\((.*?)\)")
MULTIPLE_SPACES_PATTERN = re.compile(r"[ \t]+")


def strip_markdown(text: str) -> str:
    """
    단순 마크다운 문법 제거

    Args:
        text: 원본 텍스트

    Returns:
        특수 포맷이 제거된 평문 문자열
    """
    if not text:
        return ""

    cleaned = HEADER_PATTERN.sub("", text)
    cleaned = IMAGE_PATTERN.sub(r"\1", cleaned)
    cleaned = LINK_PATTERN.sub(r"\1", cleaned)

    # 강조/기타 특수 문자 제거
    for token in ("**", "__", "*", "_", "`", ">"):
        cleaned = cleaned.replace(token, "")

    cleaned = MULTIPLE_SPACES_PATTERN.sub(" ", cleaned)
    cleaned = cleaned.replace("\r", "")

    # 불필요한 공백 정리
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def strip_markdown_preserve_whitespace(text: str) -> str:
    """
    스트리밍용 마크다운 문법 제거 (공백 보존)

    스트리밍 환경에서 각 청크마다 호출되므로 .strip()을 사용하지 않습니다.
    이렇게 하면 "안녕하세요! "와 같이 뒤에 공백이 있는 토큰이
    "안녕하세요!"로 변경되지 않고 "안녕하세요! "로 유지됩니다.

    Args:
        text: 원본 텍스트

    Returns:
        특수 포맷이 제거되었지만 공백은 보존된 문자열
    """
    if not text:
        return ""

    cleaned = text

    # 강조/기타 특수 문자만 제거 (헤더, 링크는 스트리밍 중에 부분적으로 나타날 수 있으므로 제외)
    for token in ("**", "__", "*", "_", "`"):
        cleaned = cleaned.replace(token, "")

    # 캐리지 리턴만 제거 (공백과 줄바꿈은 보존)
    cleaned = cleaned.replace("\r", "")

    return cleaned
