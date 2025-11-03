"""
사용자 및 팀 관련 데이터베이스 모델
"""
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Boolean, Text, Enum as SQLEnum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from datetime import datetime
import uuid
import enum

from app.core.database import Base


class UserRole(str, enum.Enum):
    """팀 내 사용자 역할"""
    OWNER = "owner"  # 팀장
    MEMBER = "member"  # 팀원


class User(Base):
    """사용자 테이블 (Google OAuth)"""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    name = Column(String(100))
    profile_image = Column(String(500))
    google_id = Column(String(100), unique=True, index=True, nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # 관계
    team_memberships = relationship("TeamMember", back_populates="user", cascade="all, delete-orphan")


class Team(Base):
    """팀 테이블"""
    __tablename__ = "teams"

    id = Column(Integer, primary_key=True, index=True)
    uuid = Column(String(36), unique=True, index=True, nullable=False, default=lambda: str(uuid.uuid4()))
    name = Column(String(100), nullable=False)
    description = Column(Text)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # 관계
    members = relationship("TeamMember", back_populates="team", cascade="all, delete-orphan")
    api_keys = relationship("APIKey", back_populates="team", cascade="all, delete-orphan")
    invites = relationship("InviteToken", back_populates="team", cascade="all, delete-orphan")
    bots = relationship("Bot", back_populates="team", cascade="all, delete-orphan")


class TeamMember(Base):
    """팀 멤버십 테이블 (User-Team 다대다 관계)"""
    __tablename__ = "team_members"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    team_id = Column(Integer, ForeignKey("teams.id", ondelete="CASCADE"), nullable=False)
    role = Column(SQLEnum(UserRole), nullable=False, default=UserRole.MEMBER)

    joined_at = Column(DateTime(timezone=True), server_default=func.now())

    # 관계
    user = relationship("User", back_populates="team_memberships")
    team = relationship("Team", back_populates="members")

    # 복합 유니크 제약 (한 사용자는 한 팀에 한 번만 속함)
    __table_args__ = (
        {"extend_existing": True},
    )


class APIKey(Base):
    """API 키 테이블"""
    __tablename__ = "api_keys"

    id = Column(Integer, primary_key=True, index=True)
    team_id = Column(Integer, ForeignKey("teams.id", ondelete="CASCADE"), nullable=False)
    key_name = Column(String(100), nullable=False)  # 사용자가 지정하는 키 이름
    key_hash = Column(String(255), unique=True, index=True, nullable=False)  # bcrypt 해시

    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=True)  # None이면 만료 없음
    last_used_at = Column(DateTime(timezone=True), nullable=True)

    # 관계
    team = relationship("Team", back_populates="api_keys")


class InviteToken(Base):
    """팀 초대 토큰 테이블"""
    __tablename__ = "invite_tokens"

    id = Column(Integer, primary_key=True, index=True)
    team_id = Column(Integer, ForeignKey("teams.id", ondelete="CASCADE"), nullable=False)
    token = Column(String(64), unique=True, index=True, nullable=False)  # 랜덤 토큰

    created_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=False)  # 24시간 후 만료
    is_used = Column(Boolean, default=False)
    used_at = Column(DateTime(timezone=True), nullable=True)
    used_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    # 관계
    team = relationship("Team", back_populates="invites")
