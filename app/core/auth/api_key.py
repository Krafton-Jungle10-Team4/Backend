"""API 키 생성 및 검증"""
import secrets
import hashlib


def generate_api_key() -> str:
    """
    안전한 랜덤 API 키 생성

    Returns:
        48자 hex 문자열 (예: "a3f2c8d9...") - bcrypt 72바이트 제한 고려
    """
    return secrets.token_hex(24)  # 24 bytes = 48 hex chars (< 72 bytes)


def hash_api_key(api_key: str) -> str:
    """
    API 키를 SHA-256으로 해싱

    Args:
        api_key: 원본 API 키

    Returns:
        SHA-256 해시 문자열
    """
    return hashlib.sha256(api_key.encode()).hexdigest()


def verify_api_key(plain_key: str, hashed_key: str) -> bool:
    """
    API 키 검증

    Args:
        plain_key: 사용자가 제공한 원본 키
        hashed_key: DB에 저장된 해시

    Returns:
        검증 성공 여부
    """
    return hashlib.sha256(plain_key.encode()).hexdigest() == hashed_key
