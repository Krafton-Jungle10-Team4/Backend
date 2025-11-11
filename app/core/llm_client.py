"""
LLM API 클라이언트 추상화 및 팩토리
"""
import logging
from importlib import import_module

from app.config import settings
from app.core.llm_base import BaseLLMClient
from app.core.llm_registry import LLMProviderRegistry
from app.core.providers.config import OpenAIConfig, AnthropicConfig

logger = logging.getLogger(__name__)


# Provider 모듈을 동적으로 import하여 Registry에 등록
import_module("app.core.providers")


def _build_provider_config(provider: str):
    """환경설정에서 Provider 설정 생성"""
    provider_key = (provider or "").lower()

    if provider_key == "openai":
        if not settings.openai_api_key:
            raise ValueError(
                "OPENAI_API_KEY가 설정되지 않았습니다. .env.local 파일을 확인하세요."
            )
        return OpenAIConfig(
            api_key=settings.openai_api_key,
            organization=settings.openai_organization,
            default_model=settings.openai_model,
            system_prompt=None
        )

    if provider_key == "anthropic":
        if not settings.anthropic_api_key:
            raise ValueError(
                "ANTHROPIC_API_KEY가 설정되지 않았습니다. .env.local 파일을 확인하세요."
            )
        return AnthropicConfig(
            api_key=settings.anthropic_api_key,
            default_model=settings.anthropic_model,
            system_prompt=None
        )

    raise ValueError(f"지원하지 않는 LLM 제공자: {provider}")


def get_llm_client(provider: str = None) -> BaseLLMClient:
    """
    LLM 클라이언트 팩토리

    Args:
        provider: 명시적 Provider (없으면 settings.llm_provider 사용)
    """
    provider_key = (provider or settings.llm_provider or "openai").lower()
    config = _build_provider_config(provider_key)
    return LLMProviderRegistry.get_client(provider_key, config=config)
