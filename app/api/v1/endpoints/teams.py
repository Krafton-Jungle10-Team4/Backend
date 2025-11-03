"""팀 관리 API 엔드포인트"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timedelta
import secrets

from app.core.database import get_db
from app.core.auth.dependencies import (
    get_current_user_from_jwt,
    require_team_owner,
    get_user_team
)
from app.core.auth.api_key import generate_api_key, hash_api_key
from app.models.user import User, Team, APIKey, InviteToken, TeamMember, UserRole
from app.schemas.auth import (
    TeamResponse,
    APIKeyCreate,
    APIKeyResponse,
    APIKeyListItem,
    InviteTokenCreate,
    InviteTokenResponse
)
from app.config import settings

router = APIRouter()


@router.get("/me", response_model=TeamResponse)
async def get_my_team(
    team: Team = Depends(get_user_team)
):
    """현재 사용자의 팀 정보 조회"""
    return team


@router.post("/{team_id}/api-keys", response_model=APIKeyResponse)
async def create_api_key(
    team_id: int,
    key_data: APIKeyCreate,
    user_team: tuple = Depends(require_team_owner),
    db: AsyncSession = Depends(get_db)
):
    """
    API 키 생성 (팀 오너만 가능)

    생성된 평문 키는 이 응답에서만 확인 가능하므로 반드시 저장해야 합니다.
    """
    user, team = user_team

    if team.id != team_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized for this team"
        )

    # 평문 API 키 생성
    plain_key = generate_api_key()

    # 해시하여 저장
    key_hash = hash_api_key(plain_key)

    api_key = APIKey(
        team_id=team.id,
        key_name=key_data.key_name,
        key_hash=key_hash,
        is_active=True
    )
    db.add(api_key)
    await db.commit()
    await db.refresh(api_key)

    # 응답에 평문 키 포함 (한 번만!)
    return APIKeyResponse(
        id=api_key.id,
        key_name=api_key.key_name,
        api_key=plain_key,  # 평문 키
        created_at=api_key.created_at,
        expires_at=api_key.expires_at
    )


@router.get("/{team_id}/api-keys", response_model=list[APIKeyListItem])
async def list_api_keys(
    team_id: int,
    user_team: tuple = Depends(require_team_owner),
    db: AsyncSession = Depends(get_db)
):
    """API 키 목록 조회 (팀 오너만 가능)"""
    user, team = user_team

    if team.id != team_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized for this team"
        )

    result = await db.execute(
        select(APIKey).where(APIKey.team_id == team.id)
    )
    api_keys = result.scalars().all()

    return api_keys


@router.delete("/{team_id}/api-keys/{key_id}")
async def revoke_api_key(
    team_id: int,
    key_id: int,
    user_team: tuple = Depends(require_team_owner),
    db: AsyncSession = Depends(get_db)
):
    """API 키 비활성화 (팀 오너만 가능)"""
    user, team = user_team

    if team.id != team_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized for this team"
        )

    result = await db.execute(
        select(APIKey).where(
            APIKey.id == key_id,
            APIKey.team_id == team.id
        )
    )
    api_key = result.scalar_one_or_none()

    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API key not found"
        )

    api_key.is_active = False
    await db.commit()

    return {"message": "API key revoked successfully"}


@router.post("/{team_id}/invites", response_model=InviteTokenResponse)
async def create_invite_token(
    team_id: int,
    user_team: tuple = Depends(require_team_owner),
    db: AsyncSession = Depends(get_db)
):
    """
    초대 토큰 생성 (팀 오너만 가능)

    24시간 유효한 일회용 초대 링크 생성
    """
    user, team = user_team

    if team.id != team_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized for this team"
        )

    # 랜덤 토큰 생성
    token = secrets.token_urlsafe(32)

    invite = InviteToken(
        team_id=team.id,
        token=token,
        created_by_user_id=user.id,
        expires_at=datetime.utcnow() + timedelta(hours=24),
        is_used=False
    )
    db.add(invite)
    await db.commit()

    # 프론트엔드 초대 URL 생성
    invite_url = f"{settings.frontend_url}/invite/{token}"

    return InviteTokenResponse(
        invite_url=invite_url,
        expires_at=invite.expires_at
    )


@router.post("/join/{token}")
async def join_team_by_invite(
    token: str,
    user: User = Depends(get_current_user_from_jwt),
    db: AsyncSession = Depends(get_db)
):
    """
    초대 토큰으로 팀 가입

    이미 다른 팀에 속한 경우 오류 반환
    """
    # 초대 토큰 조회
    result = await db.execute(
        select(InviteToken).where(InviteToken.token == token)
    )
    invite = result.scalar_one_or_none()

    if not invite:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invalid invite token"
        )

    # 토큰 검증
    if invite.is_used:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invite token already used"
        )

    if datetime.utcnow() > invite.expires_at:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invite token expired"
        )

    # 사용자가 이미 팀에 속해있는지 확인
    result = await db.execute(
        select(TeamMember).where(TeamMember.user_id == user.id)
    )
    existing_membership = result.scalar_one_or_none()

    if existing_membership:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User already belongs to a team"
        )

    # 팀 멤버십 생성
    membership = TeamMember(
        user_id=user.id,
        team_id=invite.team_id,
        role=UserRole.MEMBER
    )
    db.add(membership)

    # 초대 토큰 사용 처리
    invite.is_used = True
    invite.used_at = datetime.utcnow()
    invite.used_by_user_id = user.id

    await db.commit()

    return {"message": "Successfully joined team"}
