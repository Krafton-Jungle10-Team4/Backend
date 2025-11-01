"""
pytest 공통 픽스처 및 설정
"""
import pytest
import os
from unittest.mock import Mock, AsyncMock, patch


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
