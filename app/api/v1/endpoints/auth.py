"""인증 API 엔드포인트"""
from fastapi import APIRouter, Depends, HTTPException, Request, status, Response
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timedelta, timezone
from passlib.context import CryptContext
import json
import base64

from app.core.database import get_db
from app.core.auth.oauth import oauth, get_google_user_info
from app.core.auth.jwt import create_access_token, create_token_pair
from app.core.auth.dependencies import get_current_user_from_jwt
from app.models.user import User, Team, TeamMember, UserRole, AuthType, RefreshToken
from app.schemas.auth import TokenResponse, UserResponse, LoginRequest, RegisterRequest
from app.config import settings

router = APIRouter()

# 비밀번호 해싱
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


@router.get("/google/login")
async def google_login(request: Request, redirect_uri: str = None):
    """
    Google OAuth 로그인 시작

    프론트엔드에서 이 URL로 리다이렉트하면 Google 로그인 페이지로 이동

    Args:
        redirect_uri: 프론트엔드에서 전달한 콜백 URL (선택)
                      예: http://localhost:5173/auth/callback
    """
    # state 파라미터에 redirect_uri 정보 저장 (Google을 거쳐도 유지됨)
    if redirect_uri:
        origin_url = redirect_uri
    else:
        # fallback: referer 헤더에서 도메인 추출
        referer = request.headers.get("referer", "")
        if referer:
            # referer에서 도메인만 추출 (예: http://localhost:5173 → /auth/callback 추가)
            from urllib.parse import urlparse
            parsed = urlparse(referer)
            origin_url = f"{parsed.scheme}://{parsed.netloc}/auth/callback"
        else:
            # 기본값
            origin_url = f"{settings.get_frontend_urls()[0]}/auth/callback"

    # state에 origin_url 인코딩
    state_data = {"redirect_uri": origin_url}
    state = base64.urlsafe_b64encode(json.dumps(state_data).encode()).decode()

    google_redirect_uri = settings.google_redirect_uri
    return await oauth.google.authorize_redirect(request, google_redirect_uri, state=state)


@router.get("/google/callback")
async def google_callback(request: Request, state: str = None, db: AsyncSession = Depends(get_db)):
    """
    Google OAuth 콜백

    Google 로그인 후 여기로 돌아옴

    **보안 강화**:
    - Access Token: URL 파라미터로 프론트엔드 전달 (일회성)
    - Refresh Token: httpOnly 쿠키로 전달 (XSS 방어)

    Args:
        state: Google에서 돌려받은 state 파라미터 (redirect_uri 포함)
    """
    # state에서 redirect_uri 복원
    redirect_uri = None
    if state:
        try:
            state_data = json.loads(base64.urlsafe_b64decode(state.encode()).decode())
            redirect_uri = state_data.get("redirect_uri")
        except Exception:
            pass  # state 파싱 실패 시 기본값 사용

    # 기본값
    if not redirect_uri:
        redirect_uri = f"{settings.get_frontend_urls()[0]}/auth/callback"

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

    # Access Token + Refresh Token 생성
    tokens = create_token_pair(user.id, user.email)

    # Refresh Token DB에 저장
    refresh_token_obj = RefreshToken(
        user_id=user.id,
        token=tokens["refresh_token"],
        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days)
    )
    db.add(refresh_token_obj)
    await db.commit()
    await db.refresh(user)

    # redirect_uri로 직접 리다이렉트 (이미 /auth/callback 포함됨)
    redirect_url = f"{redirect_uri}?token={tokens['access_token']}"
    response = RedirectResponse(url=redirect_url)

    # httpOnly 쿠키로 Refresh Token 전달
    response.set_cookie(
        key="refresh_token",
        value=tokens["refresh_token"],
        httponly=True,              # JavaScript 접근 차단 (XSS 방어)
        secure=settings.is_production,  # HTTPS에서만 전송
        samesite="lax",             # CSRF 방어
        max_age=60 * 60 * 24 * 7,   # 7일
        path="/api/v1/auth/refresh"
    )

    return response


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


@router.post("/refresh", response_model=TokenResponse)
async def refresh_access_token(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Refresh Token으로 Access Token 갱신

    - httpOnly 쿠키에서 refresh_token 추출
    - DB에서 유효성 검증 (만료, 무효화 여부)
    - 새로운 Access Token 발급
    
    **보안**:
    - Refresh Token은 httpOnly 쿠키에 저장되어 JavaScript 접근 불가 (XSS 방어)
    - HTTPS 환경에서만 전송 (Secure 플래그)
    """
    from datetime import datetime, timezone
    from app.models.user import RefreshToken
    from app.core.auth.jwt import create_access_token

    # httpOnly 쿠키에서 Refresh Token 추출
    refresh_token = request.cookies.get("refresh_token")

    if not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token not found in cookies"
        )

    # DB에서 토큰 검증
    result = await db.execute(
        select(RefreshToken)
        .where(RefreshToken.token == refresh_token)
        .where(RefreshToken.revoked == False)
        .where(RefreshToken.expires_at > datetime.now(timezone.utc))
    )
    db_token = result.scalar_one_or_none()

    if not db_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token"
        )

    # 사용자 정보 가져오기
    user = await db.get(User, db_token.user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    # 새로운 Access Token 생성
    access_token = create_access_token(
        data={"user_id": user.id, "email": user.email}
    )

    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        user=UserResponse.model_validate(user)
    )


@router.post("/logout")
async def logout(
    request: Request,
    user: User = Depends(get_current_user_from_jwt),
    db: AsyncSession = Depends(get_db)
):
    """
    로그아웃
    
    - Refresh Token 무효화 (DB에서 revoked = True)
    - httpOnly 쿠키 삭제
    
    **보안**:
    - 로그아웃 후 Refresh Token 재사용 불가
    - 쿠키 완전 삭제로 XSS 공격 차단
    """
    from sqlalchemy import update
    
    refresh_token = request.cookies.get("refresh_token")

    if refresh_token:
        # DB에서 토큰 무효화
        await db.execute(
            update(RefreshToken)
            .where(RefreshToken.token == refresh_token)
            .values(revoked=True)
        )
        await db.commit()

    # 쿠키 삭제
    response = JSONResponse(content={"message": "Logged out successfully"})
    response.delete_cookie(key="refresh_token", path="/api/v1/auth/refresh")

    return response


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(
    request: RegisterRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    로컬 계정 회원가입 (테스트용)

    이메일이 이미 존재하면 실패
    
    **보안 강화**:
    - Access Token (15분): 응답 body에 포함
    - Refresh Token (7일): httpOnly 쿠키로 전달 (XSS 방어)
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
    
    # Access Token + Refresh Token 생성
    tokens = create_token_pair(user.id, user.email)

    # Refresh Token DB에 저장
    refresh_token_obj = RefreshToken(
        user_id=user.id,
        token=tokens["refresh_token"],
        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days)
    )
    db.add(refresh_token_obj)
    await db.commit()
    await db.refresh(user)

    # httpOnly 쿠키로 Refresh Token 전달
    response = JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content={
            "access_token": tokens["access_token"],
            "token_type": "bearer",
            "user": UserResponse.model_validate(user).model_dump()
        }
    )

    response.set_cookie(
        key="refresh_token",
        value=tokens["refresh_token"],
        httponly=True,              # JavaScript 접근 차단 (XSS 방어)
        secure=settings.is_production,  # HTTPS에서만 전송 (중간자 공격 방어)
        samesite="lax",             # CSRF 방어
        max_age=60 * 60 * 24 * 7,   # 7일
        path="/api/v1/auth/refresh" # refresh 엔드포인트에만 전송
    )

    return response


@router.post("/login", response_model=TokenResponse)
async def login(
    request: LoginRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    로컬 계정 로그인 (테스트용)

    이메일/비밀번호로 로그인
    
    **보안 강화**:
    - Access Token (15분): 응답 body에 포함
    - Refresh Token (7일): httpOnly 쿠키로 전달 (XSS 방어)
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

    # Access Token + Refresh Token 생성
    tokens = create_token_pair(user.id, user.email)

    # Refresh Token DB에 저장
    refresh_token_obj = RefreshToken(
        user_id=user.id,
        token=tokens["refresh_token"],
        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days)
    )
    db.add(refresh_token_obj)
    await db.commit()

    # httpOnly 쿠키로 Refresh Token 전달
    response = JSONResponse(
        content={
            "access_token": tokens["access_token"],
            "token_type": "bearer",
            "user": UserResponse.model_validate(user).model_dump()
        }
    )

    response.set_cookie(
        key="refresh_token",
        value=tokens["refresh_token"],
        httponly=True,              # JavaScript 접근 차단 (XSS 방어)
        secure=settings.is_production,  # HTTPS에서만 전송 (중간자 공격 방어)
        samesite="lax",             # CSRF 방어
        max_age=60 * 60 * 24 * 7,   # 7일
        path="/api/v1/auth/refresh" # refresh 엔드포인트에만 전송
    )

    return response
