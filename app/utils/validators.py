"""
입력 검증 유틸리티
"""
import re
from typing import Optional


def sanitize_user_input(text: str, max_length: int = 2000) -> str:
    """
    사용자 입력 텍스트 검증 및 정제

    프롬프트 인젝션 공격 방지를 위한 기본적인 검증:
    - 제어 문자 제거
    - 과도한 공백 정규화
    - 길이 제한

    Args:
        text: 검증할 텍스트
        max_length: 최대 길이 (기본: 2000자)

    Returns:
        정제된 텍스트

    Raises:
        ValueError: 입력이 비어있거나 너무 긴 경우
    """
    if not text or not text.strip():
        raise ValueError("입력 텍스트가 비어있습니다")

    # 제어 문자 제거 (탭, 줄바꿈은 유지)
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]', '', text)

    # 과도한 공백 정규화 (여러 공백 → 단일 공백)
    text = re.sub(r'\s+', ' ', text).strip()

    # 길이 제한
    if len(text) > max_length:
        text = text[:max_length].rsplit(' ', 1)[0] + '...'

    return text


def sanitize_chat_query(query: str) -> str:
    """
    채팅 쿼리 전용 검증

    Args:
        query: 사용자 채팅 쿼리

    Returns:
        정제된 쿼리

    Raises:
        ValueError: 쿼리가 유효하지 않은 경우
    """
    # 기본 검증
    sanitized = sanitize_user_input(query, max_length=1000)

    # 최소 길이 검증
    if len(sanitized) < 2:
        raise ValueError("쿼리가 너무 짧습니다 (최소 2자 이상)")

    return sanitized


def sanitize_filename(filename: str) -> str:
    """
    파일명 검증 및 정제

    Args:
        filename: 원본 파일명

    Returns:
        안전한 파일명

    Raises:
        ValueError: 파일명이 유효하지 않은 경우
    """
    if not filename:
        raise ValueError("파일명이 비어있습니다")

    # 경로 구분자 제거
    filename = filename.replace('/', '_').replace('\\', '_')

    # 위험한 문자 제거
    filename = re.sub(r'[<>:"|?*\x00-\x1f]', '', filename)

    # 길이 제한
    if len(filename) > 255:
        name, ext = filename.rsplit('.', 1) if '.' in filename else (filename, '')
        filename = name[:250] + ('.' + ext if ext else '')

    if not filename:
        raise ValueError("유효하지 않은 파일명입니다")

    return filename
