"""
LLM Provider Registry
"""
from __future__ import annotations

from typing import Dict, Type, Optional, TYPE_CHECKING
import threading
import logging

if TYPE_CHECKING:
    from app.core.llm_base import BaseLLMClient

logger = logging.getLogger(__name__)


class LLMProviderRegistry:
    """LLM Provider 등록/인스턴스 관리"""

    _providers: Dict[str, Type["BaseLLMClient"]] = {}
    _instances: Dict[str, "BaseLLMClient"] = {}
    _lock = threading.Lock()

    @classmethod
    def register(cls, provider_name: str, client_class: Type["BaseLLMClient"]) -> None:
        """Provider 클래스 등록"""
        provider_key = provider_name.lower()
        if provider_key in cls._providers:
            logger.warning("Provider %s already registered, overriding", provider_key)
        cls._providers[provider_key] = client_class
        logger.info("Registered LLM provider '%s' -> %s", provider_key, client_class.__name__)

    @classmethod
    def get_client(
        cls,
        provider: str,
        *,
        config = None,
        force_refresh: bool = False
    ) -> BaseLLMClient:
        """
        Provider 이름으로 Client 인스턴스 반환

        Args:
            provider: provider 식별자
            config: 초기화에 사용할 설정 객체 (신규 생성 시 필수)
            force_refresh: True면 기존 인스턴스를 재생성
        """
        provider_key = provider.lower()

        with cls._lock:
            if not force_refresh and provider_key in cls._instances:
                return cls._instances[provider_key]

            if provider_key not in cls._providers:
                raise ValueError(f"지원하지 않는 LLM 제공자: {provider}")

            if config is None:
                raise ValueError(f"{provider} Provider 초기화를 위한 설정이 필요합니다")

            client_class = cls._providers[provider_key]
            cls._instances[provider_key] = client_class(config=config)
            return cls._instances[provider_key]

    @classmethod
    def list_providers(cls) -> Dict[str, Type["BaseLLMClient"]]:
        """등록된 Provider 목록"""
        return dict(cls._providers)

    @classmethod
    def clear_instances(cls) -> None:
        """테스트용: 생성된 인스턴스 캐시 제거"""
        with cls._lock:
            cls._instances.clear()


def register_provider(provider_name: str):
    """Provider 자동 등록 데코레이터"""

    def decorator(cls: Type["BaseLLMClient"]):
        LLMProviderRegistry.register(provider_name, cls)
        return cls

    return decorator
