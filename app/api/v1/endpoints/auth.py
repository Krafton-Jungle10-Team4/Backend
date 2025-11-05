"""인증 API 엔드포인트"""
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import timedelta
from passlib.context import CryptContext

from app.core.database import get_db
from app.core.auth.oauth import oauth, get_google_user_info
from app.core.auth.jwt import create_access_token
from app.core.auth.dependencies import get_current_user_from_jwt
from app.models.user import User, Team, TeamMember, UserRole, AuthType
from app.schemas.auth import TokenResponse, UserResponse, LoginRequest, RegisterRequest
from app.config import settings

router = APIRouter()

# 비밀번호 해싱
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


@router.get("/google/login")
async def google_login(request: Request):
    """
    Google OAuth 로그인 시작

    프론트엔드에서 이 URL로 리다이렉트하면 Google 로그인 페이지로 이동
    """
    # 요청 출처(프론트엔드) 저장 - 콜백 시 원래 프론트로 돌려보내기 위함
    referer = request.headers.get("referer", "")
    if referer:
        request.session["origin_url"] = referer

    redirect_uri = settings.google_redirect_uri
    return await oauth.google.authorize_redirect(request, redirect_uri)


@router.get("/google/callback")
async def google_callback(request: Request, db: AsyncSession = Depends(get_db)):
    """
    Google OAuth 콜백

    Google 로그인 후 여기로 돌아옴
    """
    try:
        # Google에서 토큰 받기
        token = await oauth.google.authorize_access_token(request)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to get access token: {str(e)}"
        )

    # 사용자 정보 가져오기
    user_info = await get_google_user_info(token)
    google_id = user_info.get("sub")
    email = user_info.get("email")
    name = user_info.get("name")
    profile_image = user_info.get("picture")

    if not google_id or not email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to get user info from Google"
        )

    # DB에서 사용자 찾기
    result = await db.execute(
        select(User).where(User.google_id == google_id)
    )
    user = result.scalar_one_or_none()

    # 신규 사용자면 생성
    if not user:
        user = User(
            google_id=google_id,
            email=email,
            name=name,
            profile_image=profile_image
        )
        db.add(user)
        await db.flush()  # user.id 생성

        # 신규 사용자는 자동으로 팀 생성 (팀장으로)
        team = Team(
            name=f"{name}'s Team" if name else f"Team {user.id}",
            description="기본 팀"
        )
        db.add(team)
        await db.flush()  # team.id 생성

        # 팀 멤버십 생성
        membership = TeamMember(
            user_id=user.id,
            team_id=team.id,
            role=UserRole.OWNER
        )
        db.add(membership)
        await db.commit()
        await db.refresh(user)

    # JWT 토큰 생성
    access_token = create_access_token(
        data={"user_id": user.id, "email": user.email}
    )

    # 원래 요청했던 프론트엔드로 리다이렉트
    origin_url = request.session.get("origin_url", "")
    frontend_urls = settings.get_frontend_urls()

    # 기본값: 첫 번째 프론트엔드 URL 사용
    target_url = frontend_urls[0] if frontend_urls else settings.frontend_url

    # origin_url과 매칭되는 프론트엔드 찾기
    if origin_url:
        for url in frontend_urls:
            if origin_url.startswith(url):
                target_url = url
                break

    # 프론트엔드로 리다이렉트 (토큰 포함)
    redirect_url = f"{target_url}/auth/callback?token={access_token}"
    return RedirectResponse(url=redirect_url)


@router.get("/me", response_model=UserResponse)
async def get_current_user(
    user: User = Depends(get_current_user_from_jwt)
):
    """
    현재 로그인한 사용자 정보 조회

    Headers:
        Authorization: Bearer {jwt_token}
    """
    return user


@router.post("/logout")
async def logout(user: User = Depends(get_current_user_from_jwt)):
    """
    로그아웃

    (실제로는 프론트엔드에서 토큰 삭제만 하면 됨)
    """
    return {"message": "Logged out successfully"}


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(
    request: RegisterRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    로컬 계정 회원가입 (테스트용)

    이메일이 이미 존재하면 실패
    """
    # 이메일 중복 체크
    result = await db.execute(
        select(User).where(User.email == request.email)
    )
    existing_user = result.scalar_one_or_none()

    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )

    # 비밀번호 해싱
    hashed_password = pwd_context.hash(request.password)

    # 사용자 생성
    user = User(
        email=request.email,
        name=request.name,
        auth_type=AuthType.LOCAL,
        password_hash=hashed_password
    )
    db.add(user)
    await db.flush()

    # 자동으로 팀 생성 (팀장으로)
    team = Team(
        name=f"{request.name}'s Team",
        description="기본 팀"
    )
    db.add(team)
    await db.flush()

    # 팀 멤버십 생성
    membership = TeamMember(
        user_id=user.id,
        team_id=team.id,
        role=UserRole.OWNER
    )
    db.add(membership)
    await db.commit()
    await db.refresh(user)

    # JWT 토큰 생성
    access_token = create_access_token(
        data={"user_id": user.id, "email": user.email}
    )

    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        user=UserResponse.model_validate(user)
    )


@router.post("/login", response_model=TokenResponse)
async def login(
    request: LoginRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    로컬 계정 로그인 (테스트용)

    이메일/비밀번호로 로그인
    """
    # 사용자 찾기
    result = await db.execute(
        select(User).where(
            User.email == request.email,
            User.auth_type == AuthType.LOCAL
        )
    )
    user = result.scalar_one_or_none()

    # 사용자가 없거나 비밀번호가 틀린 경우
    if not user or not pwd_context.verify(request.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password"
        )

    # JWT 토큰 생성
    access_token = create_access_token(
        data={"user_id": user.id, "email": user.email}
    )

    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        user=UserResponse.model_validate(user)
    )
