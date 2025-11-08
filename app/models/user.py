"""
사용자 관련 데이터베이스 모델
"""
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Boolean, Text, Enum as SQLEnum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from datetime import datetime
import uuid
import enum

from app.core.database import Base


class AuthType(str, enum.Enum):
    """인증 타입"""
    GOOGLE = "GOOGLE"  # Google OAuth
    LOCAL = "LOCAL"    # 로컬 인증 (테스트용)


class User(Base):
    """사용자 테이블 (Google OAuth / Local Auth)"""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    uuid = Column(String(36), unique=True, index=True, nullable=False, default=lambda: str(uuid.uuid4()))
    email = Column(String(255), unique=True, index=True, nullable=False)
    name = Column(String(100))
    profile_image = Column(String(500))

    # 인증 타입별 필드
    auth_type = Column(SQLEnum(AuthType), nullable=False, default=AuthType.GOOGLE)
    google_id = Column(String(100), unique=True, index=True, nullable=True)  # Google OAuth용
    password_hash = Column(String(255), nullable=True)  # 로컬 인증용

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # 관계
    refresh_tokens = relationship("RefreshToken", back_populates="user", cascade="all, delete-orphan")
    bots = relationship("Bot", back_populates="user", cascade="all, delete-orphan")
    api_keys = relationship("APIKey", back_populates="user", cascade="all, delete-orphan")


class RefreshToken(Base):
    """Refresh Token 테이블 (JWT 갱신용)"""
    __tablename__ = "refresh_tokens"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token = Column(String(255), unique=True, index=True, nullable=False)  # 랜덤 토큰

    expires_at = Column(DateTime(timezone=True), nullable=False)  # 7일 후 만료
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    revoked = Column(Boolean, default=False)  # 로그아웃 또는 보안상 무효화

    # 관계
    user = relationship("User", back_populates="refresh_tokens")


class APIKey(Base):
    """API 키 테이블"""
    __tablename__ = "api_keys"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    key_name = Column(String(100), nullable=False)  # 사용자가 지정하는 키 이름
    key_hash = Column(String(255), unique=True, index=True, nullable=False)  # bcrypt 해시

    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=True)  # None이면 만료 없음
    last_used_at = Column(DateTime(timezone=True), nullable=True)

    # 관계
    user = relationship("User", back_populates="api_keys")
