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
