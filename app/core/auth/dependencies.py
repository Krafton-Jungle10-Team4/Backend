"""FastAPI 인증 의존성"""
from fastapi import Depends, HTTPException, Header, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional

from app.core.database import get_db
from app.core.auth.jwt import verify_token
from app.core.auth.api_key import verify_api_key
from app.models.user import User, Team, TeamMember, APIKey, UserRole


async def get_current_user_from_jwt(
    authorization: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db)
) -> User:
    """
    JWT 토큰으로 현재 사용자 가져오기

    Spring Security의 @AuthenticationPrincipal과 유사

    Usage:
        @router.get("/me")
        async def get_me(user: User = Depends(get_current_user_from_jwt)):
            return {"email": user.email}
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid authorization header"
        )

    token = authorization.replace("Bearer ", "")
    payload = verify_token(token)

    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token"
        )

    user_id = payload.get("user_id")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload"
        )

    # DB에서 사용자 조회
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found"
        )

    return user


async def get_current_user_from_api_key(
    x_api_key: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db)
) -> tuple[User, Team]:
    """
    API 키로 현재 사용자 및 팀 가져오기

    Usage:
        @router.post("/upload")
        async def upload(user_team: tuple = Depends(get_current_user_from_api_key)):
            user, team = user_team
            return {"team_id": team.id}
    """
    if not x_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API key header (X-API-Key)"
        )

    # DB에서 활성화된 API 키 조회
    result = await db.execute(
        select(APIKey)
        .where(APIKey.is_active == True)
    )
    api_keys = result.scalars().all()

    # 제공된 키와 매칭되는 해시 찾기
    matched_key = None
    for key in api_keys:
        if verify_api_key(x_api_key, key.key_hash):
            matched_key = key
            break

    if not matched_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key"
        )

    # 마지막 사용 시간 업데이트
    from datetime import datetime
    matched_key.last_used_at = datetime.utcnow()
    await db.commit()

    # 팀 정보 가져오기
    result = await db.execute(
        select(Team).where(Team.id == matched_key.team_id)
    )
    team = result.scalar_one()

    # 팀 오너 정보 가져오기
    result = await db.execute(
        select(User)
        .join(TeamMember)
        .where(
            TeamMember.team_id == team.id,
            TeamMember.role == UserRole.OWNER
        )
    )
    owner = result.scalar_one()

    return owner, team


async def require_team_owner(
    user: User = Depends(get_current_user_from_jwt),
    db: AsyncSession = Depends(get_db)
) -> tuple[User, Team]:
    """
    팀 오너 권한 확인

    Usage:
        @router.post("/teams/{team_id}/api-keys")
        async def create_key(user_team: tuple = Depends(require_team_owner)):
            user, team = user_team
            # 팀 오너만 API 키 생성 가능
    """
    # 사용자의 팀 멤버십 조회
    result = await db.execute(
        select(TeamMember, Team)
        .join(Team)
        .where(
            TeamMember.user_id == user.id,
            TeamMember.role == UserRole.OWNER
        )
    )
    row = result.first()

    if not row:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only team owner can perform this action"
        )

    membership, team = row
    return user, team


async def get_user_team(
    user: User = Depends(get_current_user_from_jwt),
    db: AsyncSession = Depends(get_db)
) -> Team:
    """
    현재 사용자의 팀 가져오기

    Usage:
        @router.get("/teams/me")
        async def get_my_team(team: Team = Depends(get_user_team)):
            return {"team_name": team.name}
    """
    result = await db.execute(
        select(Team)
        .join(TeamMember)
        .where(TeamMember.user_id == user.id)
    )
    team = result.scalar_one_or_none()

    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User is not a member of any team"
        )

    return team
