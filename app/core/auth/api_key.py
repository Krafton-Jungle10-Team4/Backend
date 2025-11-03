"""API 키 생성 및 검증"""
import secrets
from passlib.context import CryptContext

# bcrypt 해싱 컨텍스트
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def generate_api_key() -> str:
    """
    안전한 랜덤 API 키 생성

    Returns:
        64자 hex 문자열 (예: "a3f2c8d9...")
    """
    return secrets.token_hex(32)  # 32 bytes = 64 hex chars


def hash_api_key(api_key: str) -> str:
    """
    API 키를 bcrypt로 해싱

    Args:
        api_key: 원본 API 키

    Returns:
        bcrypt 해시 문자열
    """
    return pwd_context.hash(api_key)


def verify_api_key(plain_key: str, hashed_key: str) -> bool:
    """
    API 키 검증

    Args:
        plain_key: 사용자가 제공한 원본 키
        hashed_key: DB에 저장된 해시

    Returns:
        검증 성공 여부
    """
    return pwd_context.verify(plain_key, hashed_key)
