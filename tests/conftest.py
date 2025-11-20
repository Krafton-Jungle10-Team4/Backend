"""
pytest 공통 픽스처 및 설정
"""
import pytest
import pytest_asyncio
import os
from unittest.mock import Mock, AsyncMock, patch
from httpx import AsyncClient
from app.main import app
from app.models.user import User, AuthType
from app.core.auth.dependencies import get_current_user_from_jwt


# 통합 테스트를 위한 환경 변수 설정
@pytest.fixture(scope="session", autouse=True)
def setup_test_env():
    """테스트 환경 변수 자동 설정"""
    os.environ.setdefault("OPENAI_API_KEY", "test-key-for-testing")
    os.environ.setdefault("LLM_PROVIDER", "openai")
    os.environ.setdefault("OPENAI_MODEL", "gpt-3.5-turbo")


@pytest.fixture
def mock_settings():
    """테스트용 설정 mock"""
    settings = Mock()
    settings.llm_provider = "openai"
    settings.openai_api_key = "test-api-key"
    settings.openai_model = "gpt-3.5-turbo"
    settings.openai_organization = None
    settings.chat_temperature = 0.7
    settings.chat_max_tokens = 1000
    settings.chat_default_top_k = 5
    return settings


@pytest.fixture
def sample_messages():
    """테스트용 샘플 메시지"""
    return [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Hello!"}
    ]


@pytest.fixture
def sample_chunks():
    """테스트용 샘플 문서 청크"""
    return [
        {
            "document": "FastAPI는 빠르고 현대적인 Python 웹 프레임워크입니다.",
            "metadata": {
                "filename": "fastapi_guide.pdf",
                "chunk_index": 0,
                "document_id": "doc_123"
            }
        },
        {
            "document": "비동기 프로그래밍을 지원하며 타입 힌팅을 활용합니다.",
            "metadata": {
                "filename": "fastapi_guide.pdf",
                "chunk_index": 1,
                "document_id": "doc_123"
            }
        }
    ]


# ===== 스튜디오 API 통합 테스트용 픽스처 =====

@pytest_asyncio.fixture
async def async_client():
    """FastAPI AsyncClient 픽스처"""
    async with AsyncClient(app=app, base_url="http://test") as client:
        yield client


@pytest.fixture
def test_user():
    """테스트용 사용자 객체"""
    return User(
        id=1,
        uuid="test-user-uuid",
        email="test@example.com",
        name="Studio Test User",
        auth_type=AuthType.LOCAL
    )


@pytest.fixture
def test_user_token():
    """테스트용 JWT 토큰 생성"""
    from app.core.auth.jwt import create_access_token
    return create_access_token({"user_id": 1, "email": "test@example.com"})


@pytest.fixture
def auth_headers(test_user_token):
    """인증 헤더 픽스처"""
    return {"Authorization": f"Bearer {test_user_token}"}


@pytest.fixture(autouse=True)
def override_current_user_dependency(test_user):
    """
    인증 의존성을 테스트 유저로 오버라이드

    get_current_user_from_jwt가 실제 JWT/DB 검증을 수행하지 않도록 막고,
    모든 테스트 요청이 동일한 테스트 유저로 실행되게 합니다.
    """
    async def _override():
        return test_user

    app.dependency_overrides[get_current_user_from_jwt] = _override
    yield
    app.dependency_overrides.pop(get_current_user_from_jwt, None)
