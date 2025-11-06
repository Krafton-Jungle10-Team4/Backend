"""JWT 토큰 생성 및 검증"""
from datetime import datetime, timedelta, timezone
from typing import Optional
import secrets
from jose import JWTError, jwt
from app.config import settings


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    JWT 액세스 토큰 생성 (15분 만료)

    Args:
        data: 토큰에 담을 데이터 (user_id, email 등)
        expires_delta: 만료 시간 (기본: 15분)

    Returns:
        JWT 토큰 문자열
    """
    to_encode = data.copy()

    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)

    to_encode.update({"exp": expire, "type": "access"})

    encoded_jwt = jwt.encode(
        to_encode,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm
    )

    return encoded_jwt


def create_refresh_token() -> str:
    """
    Refresh Token 생성 (랜덤 문자열)

    Returns:
        URL-safe 랜덤 토큰 문자열 (32바이트 = 43자)
    """
    return secrets.token_urlsafe(32)


def create_token_pair(user_id: int, email: str) -> dict:
    """
    Access Token + Refresh Token 쌍 생성

    Args:
        user_id: 사용자 ID
        email: 사용자 이메일

    Returns:
        {
            "access_token": "eyJ...",
            "refresh_token": "random_string"
        }
    """
    access_token = create_access_token({"user_id": user_id, "email": email})
    refresh_token = create_refresh_token()

    return {
        "access_token": access_token,
        "refresh_token": refresh_token
    }


def verify_token(token: str) -> Optional[dict]:
    """
    JWT 토큰 검증 및 페이로드 추출

    Args:
        token: JWT 토큰 문자열

    Returns:
        토큰 페이로드 또는 None (검증 실패 시)
    """
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm]
        )
        return payload
    except JWTError:
        return None
