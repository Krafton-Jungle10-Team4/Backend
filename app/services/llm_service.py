"""
LLM 서비스
"""
import logging
from typing import Optional, Callable, Awaitable, List

from app.config import settings
from app.core.llm_registry import LLMProviderRegistry
from app.core.providers.config import (
    LLMConfig,
    OpenAIConfig,
    AnthropicConfig,
    GoogleConfig,
    BedrockConfig,
    ProviderConfig,
)
from app.core.exceptions import LLMServiceError

logger = logging.getLogger(__name__)


class LLMService:
    """여러 Provider를 동시에 지원하는 LLM 서비스"""

    def __init__(self, config: Optional[LLMConfig] = None):
        self.registry = LLMProviderRegistry
        self.config = config or self._build_config_from_settings()
        self._initialize_providers()

    async def generate(
        self,
        prompt: str,
        model: Optional[str] = None,
        provider: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4000
    ) -> str:
        """단일 응답 생성"""
        provider_key = self._resolve_provider(provider, model)
        client = self._get_client(provider_key)

        logger.info(
            "[LLMService] generate 호출: provider=%s model=%s temp=%.2f",
            provider_key,
            model or "default",
            temperature,
        )

        messages = [{"role": "user", "content": prompt}]
        response = await client.generate(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            model=model
        )

        logger.info("[LLMService] LLM 응답 생성 완료 (%d chars)", len(response))
        return response

    async def generate_stream(
        self,
        prompt: str,
        model: Optional[str] = None,
        provider: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4000,
        on_chunk: Optional[Callable[[str], Awaitable[Optional[str]]]] = None
    ) -> str:
        """스트리밍 응답 생성"""
        provider_key = self._resolve_provider(provider, model)
        client = self._get_client(provider_key)

        messages = [{"role": "user", "content": prompt}]
        buffer: List[str] = []

        async for chunk in client.generate_stream(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            model=model
        ):
            processed = chunk
            if on_chunk:
                processed = await on_chunk(chunk)
            if processed:
                buffer.append(processed)

        return "".join(buffer)

    async def generate_response(
        self,
        query: str,
        context: str,
        temperature: float = 0.7,
        max_tokens: int = 4000,
        provider: Optional[str] = None,
        model: Optional[str] = None
    ) -> str:
        """RAG 파이프라인용 응답 생성"""
        provider_key = self._resolve_provider(provider, model)
        client = self._get_client(provider_key)

        logger.info(
            "[LLMService] RAG 응답 생성: provider=%s model=%s",
            provider_key,
            model or "default",
        )

        system_message = (
            "당신은 제공된 문서를 기반으로 사용자의 질문에 답변하는 AI 어시스턴트입니다. "
            "문서에 있는 정보만을 사용하여 정확하고 명확하게 답변하세요. "
            "문서에 정보가 없으면 모른다고 솔직하게 답변하세요."
        )

        user_message = f"""**컨텍스트:**
{context}

**질문:**
{query}

위 컨텍스트를 기반으로 질문에 답변해주세요."""

        messages = [
            {"role": "system", "content": system_message},
            {"role": "user", "content": user_message}
        ]

        response = await client.generate(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            model=model
        )

        logger.info("[LLMService] RAG 응답 생성 완료 (%d chars)", len(response))
        return response

    def _build_config_from_settings(self) -> LLMConfig:
        """환경 설정으로부터 LLMConfig 구성"""
        openai_cfg = None
        if settings.openai_api_key:
            openai_cfg = OpenAIConfig(
                api_key=settings.openai_api_key,
                organization=settings.openai_organization,
                default_model=settings.openai_model,
                system_prompt=None
            )

        anthropic_cfg = None
        if settings.anthropic_api_key:
            anthropic_cfg = AnthropicConfig(
                api_key=settings.anthropic_api_key,
                default_model=settings.anthropic_model,
                system_prompt=None
            )

        google_cfg = None
        if settings.google_api_key:
            google_cfg = GoogleConfig(
                api_key=settings.google_api_key,
                default_model=settings.google_default_model
            )

        bedrock_cfg = None
        if settings.llm_provider and settings.llm_provider.lower() == "bedrock":
            bedrock_cfg = BedrockConfig(
                region_name=settings.bedrock_region,
                default_model=settings.bedrock_model,
                system_prompt=None
            )

        return LLMConfig(
            default_provider=(settings.llm_provider or "openai").lower(),
            openai=openai_cfg,
            anthropic=anthropic_cfg,
            google=google_cfg,
            bedrock=bedrock_cfg
        )

    def _initialize_providers(self) -> None:
        """사용 가능한 Provider 선 초기화"""
        for provider_key in ("openai", "anthropic", "google", "bedrock"):
            config = self.config.get_provider_config(provider_key)
            if config and config.enabled:
                try:
                    self.registry.get_client(provider_key, config=config)
                except Exception as exc:  # pragma: no cover - 로깅용
                    logger.warning(
                        "LLM Provider %s 초기화 실패: %s",
                        provider_key,
                        exc
                    )

    def _resolve_provider(self, provider: Optional[str], model: Optional[str]) -> str:
        provider_key = (provider or "").lower()
        if not provider_key:
            provider_key = self._detect_provider(model)
        return provider_key or (self.config.default_provider or "openai")

    def _detect_provider(self, model: Optional[str]) -> str:
        if not model:
            return self.config.default_provider or "openai"

        lowered = model.lower()
        if lowered.startswith("gpt") or lowered.startswith("o1") or "openai" in lowered:
            return "openai"
        if lowered.startswith("claude") or "anthropic" in lowered:
            return "anthropic"
        if lowered.startswith("gemini"):
            return "google"
        return self.config.default_provider or "openai"

    def _get_provider_config(self, provider: str) -> ProviderConfig:
        config = self.config.get_provider_config(provider)
        if not config or not config.enabled:
            raise LLMServiceError(
                message=f"Provider '{provider}' 설정을 찾을 수 없습니다",
                details={"provider": provider}
            )
        return config

    def _get_client(self, provider: str):
        config = self._get_provider_config(provider)
        return self.registry.get_client(provider, config=config)


def get_llm_service() -> LLMService:
    """LLM 서비스 인스턴스 생성"""
    return LLMService()
