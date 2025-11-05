"""인증 관련 스키마"""
from __future__ import annotations
from pydantic import BaseModel, EmailStr, Field
from datetime import datetime
from typing import Optional


class LoginRequest(BaseModel):
    """로컬 로그인 요청"""
    email: EmailStr
    password: str = Field(..., min_length=6)


class RegisterRequest(BaseModel):
    """로컬 회원가입 요청"""
    email: EmailStr
    password: str = Field(..., min_length=6)
    name: str = Field(..., min_length=1, max_length=100)


class UserResponse(BaseModel):
    """사용자 정보 응답"""
    id: int
    email: EmailStr
    name: Optional[str]
    profile_image: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True  # ORM 모델 변환 허용


class TokenResponse(BaseModel):
    """JWT 토큰 응답"""
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


class TeamResponse(BaseModel):
    """팀 정보 응답"""
    id: int
    uuid: str
    name: str
    description: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class APIKeyCreate(BaseModel):
    """API 키 생성 요청"""
    key_name: str  # 사용자가 지정하는 키 이름


class APIKeyResponse(BaseModel):
    """API 키 생성 응답"""
    id: int
    key_name: str
    api_key: str  # 평문 키 (생성 시 한 번만 반환)
    created_at: datetime
    expires_at: Optional[datetime]

    class Config:
        from_attributes = True


class APIKeyListItem(BaseModel):
    """API 키 목록 아이템"""
    id: int
    key_name: str
    is_active: bool
    created_at: datetime
    last_used_at: Optional[datetime]
    expires_at: Optional[datetime]

    class Config:
        from_attributes = True


class InviteTokenCreate(BaseModel):
    """초대 토큰 생성 요청"""
    pass  # 필요한 필드 없음 (팀 ID는 URL에서, 만료시간은 자동)


class InviteTokenResponse(BaseModel):
    """초대 토큰 생성 응답"""
    invite_url: str  # 프론트엔드 URL (예: http://localhost:3000/invite/{token})
    expires_at: datetime

    class Config:
        from_attributes = True
