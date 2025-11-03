"""Google OAuth2 인증"""
from authlib.integrations.starlette_client import OAuth
from app.config import settings

# OAuth 클라이언트 초기화
oauth = OAuth()

oauth.register(
    name='google',
    client_id=settings.google_client_id,
    client_secret=settings.google_client_secret,
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={
        'scope': 'openid email profile'
    }
)


async def get_google_user_info(token: dict) -> dict:
    """
    Google OAuth 토큰으로 사용자 정보 가져오기

    Args:
        token: Google OAuth 토큰

    Returns:
        사용자 정보 (email, name, picture, sub)
    """
    resp = await oauth.google.get(
        'https://www.googleapis.com/oauth2/v3/userinfo',
        token=token
    )
    return resp.json()
