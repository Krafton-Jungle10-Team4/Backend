"""
Slack OAuth Endpoints
Slack 워크스페이스 연동을 위한 OAuth 인증 엔드포인트
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import logging
import secrets
import hashlib
from datetime import datetime, timedelta

from app.core.database import get_db
from app.core.auth.dependencies import get_current_user_from_jwt
from app.models.user import User
from app.services.slack_service import SlackService
from app.config import settings
import os

router = APIRouter(prefix="/api/v1/slack", tags=["Slack OAuth"])
logger = logging.getLogger(__name__)

# OAuth state 저장소 (프로덕션에서는 Redis 사용 권장)
_oauth_states: Dict[str, Dict[str, Any]] = {}


def generate_oauth_state(user_id: int, bot_id: Optional[str] = None) -> str:
    """OAuth state 생성 및 저장"""
    state = secrets.token_urlsafe(32)
    _oauth_states[state] = {
        "user_id": user_id,
        "bot_id": bot_id,
        "created_at": datetime.utcnow(),
        "expires_at": datetime.utcnow() + timedelta(minutes=10)
    }
    return state


def verify_oauth_state(state: str) -> Dict[str, Any]:
    """OAuth state 검증"""
    state_data = _oauth_states.get(state)
    
    if not state_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired state"
        )
    
    # 만료 확인
    if datetime.utcnow() > state_data["expires_at"]:
        del _oauth_states[state]
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="State expired"
        )
    
    # 사용 후 삭제
    del _oauth_states[state]
    
    return state_data


# ==========================================
# Pydantic 스키마
# ==========================================

class SlackIntegrationResponse(BaseModel):
    """Slack 연동 정보 응답"""
    id: int
    workspace_id: str
    workspace_name: str
    workspace_icon: Optional[str]
    bot_user_id: Optional[str]
    scopes: List[str]
    is_active: bool
    created_at: datetime
    
    class Config:
        from_attributes = True


class SlackChannelResponse(BaseModel):
    """Slack 채널 정보"""
    id: str
    name: str
    is_private: bool
    is_member: bool
    num_members: int


# ==========================================
# OAuth Endpoints
# ==========================================

@router.get("/oauth/connect")
async def slack_oauth_connect(
    bot_id: Optional[str] = Query(None, description="봇 ID (선택)"),
    user: User = Depends(get_current_user_from_jwt)
):
    """
    Slack OAuth 인증 시작
    
    사용자를 Slack OAuth 페이지로 리다이렉트합니다.
    """
    # State 생성
    state = generate_oauth_state(user.id, bot_id)
    
    # Slack OAuth URL 생성
    slack_client_id = os.environ.get("SLACK_CLIENT_ID")
    slack_redirect_uri = os.environ.get("SLACK_REDIRECT_URI", 
                                         f"{settings.frontend_url}/slack/callback")
    
    if not slack_client_id:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Slack OAuth is not configured. Please set SLACK_CLIENT_ID."
        )
    
    # 필요한 권한 범위
    scopes = [
        "chat:write",           # 메시지 전송
        "channels:read",        # 채널 목록 조회
        "groups:read",          # 프라이빗 채널 목록 조회
        "channels:history",     # 채널 메시지 읽기 (선택)
    ]
    
    oauth_url = (
        f"https://slack.com/oauth/v2/authorize?"
        f"client_id={slack_client_id}&"
        f"scope={','.join(scopes)}&"
        f"state={state}&"
        f"redirect_uri={slack_redirect_uri}"
    )
    
    logger.info(f"Slack OAuth connect initiated: user_id={user.id}, bot_id={bot_id}")
    
    return {"oauth_url": oauth_url}


@router.get("/oauth/callback")
async def slack_oauth_callback(
    code: str = Query(..., description="Slack OAuth code"),
    state: str = Query(..., description="OAuth state"),
    db: AsyncSession = Depends(get_db)
):
    """
    Slack OAuth 콜백 처리
    
    Slack에서 리다이렉트된 후 Access Token을 교환하고 DB에 저장합니다.
    """
    # State 검증
    try:
        state_data = verify_oauth_state(state)
        user_id = state_data["user_id"]
        bot_id = state_data.get("bot_id")
    except HTTPException as e:
        # 프론트엔드로 에러 리다이렉트
        # 쉼표로 구분된 경우 첫 번째 URL 사용
        frontend_urls = settings.get_frontend_urls()
        frontend_url = frontend_urls[0] if frontend_urls else settings.frontend_url
        return RedirectResponse(
            url=f"{frontend_url}/slack/callback?error={e.detail}"
        )
    
    # Slack OAuth Client
    try:
        from slack_sdk.web import WebClient
        
        slack_client_id = os.environ.get("SLACK_CLIENT_ID")
        slack_client_secret = os.environ.get("SLACK_CLIENT_SECRET")
        slack_redirect_uri = os.environ.get("SLACK_REDIRECT_URI")
        
        if not slack_client_id or not slack_client_secret:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Slack OAuth credentials not configured"
            )
        
        # WebClient로 OAuth 토큰 교환
        client = WebClient()
        response = client.oauth_v2_access(
            client_id=slack_client_id,
            client_secret=slack_client_secret,
            code=code,
            redirect_uri=slack_redirect_uri
        )
        
        # 응답 파싱
        response_data = response.data if hasattr(response, 'data') else response
        access_token = response_data["access_token"]
        workspace_id = response_data["team"]["id"]
        workspace_name = response_data["team"]["name"]
        bot_user_id = response_data.get("bot_user_id")
        
        # scopes는 공백으로 구분됨
        scopes_str = response_data.get("scope", "")
        scopes = scopes_str.split(",") if scopes_str else []
        
        # Workspace icon 조회 (선택)
        workspace_icon = None
        if "team" in response_data and "icon" in response_data["team"]:
            workspace_icon = response_data["team"]["icon"].get("image_68")
        
        # DB에 저장
        integration = await SlackService.create_integration(
            user_id=user_id,
            bot_id=bot_id,
            access_token=access_token,
            workspace_id=workspace_id,
            workspace_name=workspace_name,
            workspace_icon=workspace_icon,
            bot_user_id=bot_user_id,
            scopes=scopes,
            db=db
        )
        
        logger.info(f"Slack OAuth completed: user_id={user_id}, workspace={workspace_name}")
        
        # 프론트엔드로 성공 리다이렉트
        # 배포 의존성 제거: 워크플로우 페이지로 돌아가기
        # 쉼표로 구분된 경우 첫 번째 URL 사용
        frontend_urls = settings.get_frontend_urls()
        frontend_url = frontend_urls[0] if frontend_urls else settings.frontend_url
        
        if bot_id:
            # 워크플로우 빌더로 돌아가기
            redirect_url = f"{frontend_url}/workspace/studio/{bot_id}?slack=success"
        else:
            # 사용자 레벨 연동 (봇 없이)
            redirect_url = f"{frontend_url}/settings/integrations?slack=success"
        
        return RedirectResponse(url=redirect_url)
        
    except Exception as e:
        logger.error(f"Slack OAuth callback failed: {e}")
        # 쉼표로 구분된 경우 첫 번째 URL 사용
        frontend_urls = settings.get_frontend_urls()
        frontend_url = frontend_urls[0] if frontend_urls else settings.frontend_url
        return RedirectResponse(
            url=f"{frontend_url}/slack/callback?error=oauth_failed"
        )


# ==========================================
# Integration Management Endpoints
# ==========================================

@router.get("/integrations", response_model=List[SlackIntegrationResponse])
async def list_slack_integrations(
    user: User = Depends(get_current_user_from_jwt),
    db: AsyncSession = Depends(get_db)
):
    """
    사용자의 모든 Slack 연동 조회
    """
    integrations = await SlackService.list_integrations(user.id, db)
    return integrations


@router.get("/integrations/{integration_id}", response_model=SlackIntegrationResponse)
async def get_slack_integration(
    integration_id: int,
    user: User = Depends(get_current_user_from_jwt),
    db: AsyncSession = Depends(get_db)
):
    """
    특정 Slack 연동 조회
    """
    integration = await SlackService.get_integration_by_id(integration_id, user.id, db)
    
    if not integration:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Slack integration not found"
        )
    
    return integration


@router.delete("/integrations/{integration_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_slack_integration(
    integration_id: int,
    user: User = Depends(get_current_user_from_jwt),
    db: AsyncSession = Depends(get_db)
):
    """
    Slack 연동 삭제
    """
    success = await SlackService.delete_integration(integration_id, user.id, db)
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Slack integration not found"
        )
    
    return None


@router.get("/integrations/{integration_id}/channels", response_model=List[SlackChannelResponse])
async def get_slack_channels(
    integration_id: int,
    user: User = Depends(get_current_user_from_jwt),
    db: AsyncSession = Depends(get_db)
):
    """
    Slack 채널 목록 조회
    
    연동된 Slack 워크스페이스의 채널 목록을 가져옵니다.
    """
    channels = await SlackService.get_channels(integration_id, user.id, db)
    return channels


@router.get("/bot/{bot_id}/integration", response_model=Optional[SlackIntegrationResponse])
async def get_bot_slack_integration(
    bot_id: str,
    user: User = Depends(get_current_user_from_jwt),
    db: AsyncSession = Depends(get_db)
):
    """
    특정 봇의 Slack 연동 조회
    """
    integration = await SlackService.get_integration(user.id, bot_id, db)
    return integration

