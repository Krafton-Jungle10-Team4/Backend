"""
LLM 서비스
"""
import hashlib
import json
import logging
from typing import Optional, Callable, Awaitable, List, Dict, Tuple, Any

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
from app.core.redis_client import redis_client
from app.services.semantic_cache_service import SemanticCacheService

logger = logging.getLogger(__name__)


class LLMService:
    """여러 Provider를 동시에 지원하는 LLM 서비스"""

    def __init__(self, config: Optional[LLMConfig] = None):
        self.registry = LLMProviderRegistry
        self.config = config or self._build_config_from_settings()
        self._last_used_model: Optional[str] = None
        self._initialize_providers()
        self.semantic_cache = SemanticCacheService()

    @property
    def last_used_model(self) -> Optional[str]:
        """가장 최근 호출에 사용된 모델명 (스트리밍 강제 교체 포함)"""
        return self._last_used_model

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
        resolved_model = model or getattr(client, "model", None)

        logger.info(
            "[LLMService] generate 호출: provider=%s model=%s temp=%.2f",
            provider_key,
            resolved_model or "default",
            temperature,
        )

        messages = [{"role": "user", "content": prompt}]
        semantic_meta = self._build_semantic_meta(
            provider_key=provider_key,
            model=resolved_model or "default",
            temperature=temperature,
            max_tokens=max_tokens
        )
        semantic_embedding = None

        cache_key = await self._build_cache_key(
            tag="prompt",
            payload={
                "provider": provider_key,
                "model": resolved_model or "default",
                "prompt": prompt,
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
        )
        cached = await self._try_get_cached(cache_key)
        if cached is not None:
            self._record_last_used_model(resolved_model)
            return cached.get("response", "")

        semantic_response, semantic_embedding = await self.semantic_cache.lookup(
            prompt,
            semantic_meta
        )
        if semantic_response:
            self._record_last_used_model(resolved_model)
            return semantic_response

        response = await client.generate(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            model=resolved_model
        )

        logger.info("[LLMService] LLM 응답 생성 완료 (%d chars)", len(response))
        self._record_last_used_model(resolved_model)
        await self._store_cache(
            cache_key,
            response,
            meta={
                "provider": provider_key,
                "model": resolved_model or "default",
                "type": "generate",
            },
        )
        await self.semantic_cache.store(
            prompt=prompt,
            response=response,
            meta=semantic_meta,
            embedding=semantic_embedding
        )
        return response

    async def generate_stream(
        self,
        prompt: str,
        model: Optional[str] = None,
        provider: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4000,
        on_chunk: Optional[Callable[[str], Awaitable[Optional[str]]]] = None,
        system_prompt: Optional[str] = None
    ) -> str:
        """스트리밍 응답 생성"""
        provider_key = self._resolve_provider(provider, model)
        client = self._get_client(provider_key)

        requested_model = model or getattr(client, "model", None)
        model_to_use = requested_model
        
        # 모든 provider가 SSE 스트리밍을 지원하지만, OpenAI의 일부 모델(o1, o3 등)은 특별 처리 필요
        if provider_key == "openai":
            streaming_model, replaced_from = self.get_streaming_safe_model(
                provider_key,
                requested_model
            )
            if streaming_model:
                model_to_use = streaming_model
            if replaced_from and replaced_from != streaming_model:
                logger.warning(
                    "[LLMService] Streaming requested with non-SSE model '%s'; using '%s' instead.",
                    replaced_from,
                    streaming_model
                )
        # 다른 provider들(bedrock, anthropic, google)은 모두 SSE 스트리밍을 지원하므로
        # 요청한 모델을 그대로 사용

        # 시스템 프롬프트 추가 (제공된 경우)
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        semantic_meta = self._build_semantic_meta(
            provider_key=provider_key,
            model=model_to_use or "default",
            temperature=temperature,
            max_tokens=max_tokens,
            system_prompt=system_prompt
        )
        semantic_embedding = None

        # 캐시 조회: 이미 동일 질의가 캐싱되어 있으면 스트리밍 없이 즉시 반환
        cache_key = None
        if self._cache_enabled():
            cache_key = await self._build_cache_key(
                tag="prompt",
                payload={
                    "provider": provider_key,
                    "model": model_to_use or "default",
                    "prompt": prompt,
                    "system_prompt": system_prompt,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                },
            )
            cached = await self._try_get_cached(cache_key)
            if cached is not None:
                cached_response = cached.get("response", "")
                self._record_last_used_model(model_to_use)
                if on_chunk and cached_response:
                    processed = await on_chunk(cached_response)
                    return processed if processed is not None else cached_response
                return cached_response

        semantic_response, semantic_embedding = await self.semantic_cache.lookup(
            prompt,
            semantic_meta
        )
        if semantic_response:
            self._record_last_used_model(model_to_use)
            if on_chunk and semantic_response:
                processed = await on_chunk(semantic_response)
                return processed if processed is not None else semantic_response
            return semantic_response

        buffer: List[str] = []

        async for chunk in client.generate_stream(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            model=model_to_use
        ):
            processed = chunk
            if on_chunk:
                processed = await on_chunk(chunk)
            if processed:
                buffer.append(processed)

        self._record_last_used_model(model_to_use)
        full_response = "".join(buffer)

        # 스트리밍 완료 후 캐시 저장 (스트리밍 시에도 동일 키 재사용)
        if cache_key:
            await self._store_cache(
                cache_key,
                full_response,
                meta={
                    "provider": provider_key,
                    "model": model_to_use or "default",
                    "type": "generate_stream",
                },
            )

        await self.semantic_cache.store(
            prompt=prompt,
            response=full_response,
            meta=semantic_meta,
            embedding=semantic_embedding
        )

        return full_response

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
        resolved_model = model or getattr(client, "model", None)

        logger.info(
            "[LLMService] RAG 응답 생성: provider=%s model=%s",
            provider_key,
            resolved_model or "default",
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
        semantic_meta = self._build_semantic_meta(
            provider_key=provider_key,
            model=resolved_model or "default",
            temperature=temperature,
            max_tokens=max_tokens,
            system_prompt=system_message,
            extra={"context_hash": self._hash_text(context)}
        )
        semantic_embedding = None

        cache_key = await self._build_cache_key(
            tag="rag",
            payload={
                "provider": provider_key,
                "model": resolved_model or "default",
                "query": query,
                "context": context,
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
        )
        cached = await self._try_get_cached(cache_key)
        if cached is not None:
            self._record_last_used_model(resolved_model)
            return cached.get("response", "")

        semantic_response, semantic_embedding = await self.semantic_cache.lookup(
            user_message,
            semantic_meta
        )
        if semantic_response:
            self._record_last_used_model(resolved_model)
            return semantic_response

        response = await client.generate(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            model=model
        )

        logger.info("[LLMService] RAG 응답 생성 완료 (%d chars)", len(response))
        self._record_last_used_model(resolved_model)
        await self._store_cache(
            cache_key,
            response,
            meta={
                "provider": provider_key,
                "model": model or "default",
                "type": "rag_generate",
            },
        )
        await self.semantic_cache.store(
            prompt=user_message,
            response=response,
            meta=semantic_meta,
            embedding=semantic_embedding
        )
        return response

    async def _build_cache_key(self, tag: str, payload: Dict) -> str:
        """프롬프트/컨텍스트를 해시하여 캐시 키 생성"""
        try:
            raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        except Exception:
            raw = str(payload)
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        prefix = settings.llm_cache_prefix or "llm:cache"
        return f"{prefix}:{tag}:{digest}"

    def _cache_enabled(self) -> bool:
        """Redis 및 설정이 활성화되었는지 여부"""
        return settings.llm_cache_enabled and bool(redis_client.redis)

    @staticmethod
    def _hash_text(value: Optional[str]) -> str:
        if not value:
            return "none"
        return hashlib.sha256(value.strip().encode("utf-8")).hexdigest()

    def _build_semantic_meta(
        self,
        provider_key: str,
        model: Optional[str],
        temperature: float,
        max_tokens: int,
        system_prompt: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        meta: Dict[str, Any] = {
            "provider": provider_key,
            "model": model or "default",
            "temperature": round(float(temperature), 4),
            "max_tokens": int(max_tokens),
            "system_prompt_hash": self._hash_text(system_prompt),
        }
        if extra:
            meta.update(extra)
        return meta

    def get_streaming_safe_model(
        self,
        provider_key: str,
        requested_model: Optional[str]
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        SSE 스트리밍이 가능한 모델을 반환. 지원하지 않는 모델이면 안전한 공식 모델로 교체.

        Returns:
            (선택된 모델, 교체 이전 모델명)
        """
        normalized_provider = (provider_key or "").lower()
        if normalized_provider != "openai":
            return requested_model, None

        target_model = requested_model or self.config.get_provider_config("openai").default_model
        if self._is_openai_streaming_model(target_model):
            return target_model, None

        # SSE 지원 공식 모델 우선순위
        candidates = [
            settings.openai_model,
            "gpt-4o",
            "gpt-4.1",
            "gpt-4o-mini",
            "gpt-4.1-mini",
            "gpt-3.5-turbo",
        ]
        for candidate in candidates:
            if candidate and self._is_openai_streaming_model(candidate):
                return candidate, target_model

        return target_model, target_model

    @staticmethod
    def _is_openai_streaming_model(model_name: Optional[str]) -> bool:
        """OpenAI chat/completions SSE가 가능한 모델인지 간단히 판별"""
        lowered = (model_name or "").lower()
        if not lowered:
            return False

        blocked_prefixes = ("gpt-5", "o1-", "o3-")
        blocked_fragments = ("codex", "instruct")
        if any(lowered.startswith(prefix) for prefix in blocked_prefixes):
            return False
        if any(fragment in lowered for fragment in blocked_fragments):
            return False
        return True

    async def _try_get_cached(self, cache_key: str) -> Optional[Dict]:
        """캐시 조회 + 로깅 (히트/미스)"""
        if not self._cache_enabled():
            return None
        cached = await redis_client.get(cache_key)
        if not cached:
            logger.info("[LLMService] cache_miss key=%s", cache_key)
            return None

        if isinstance(cached, dict) and cached.get("response") is not None:
            logger.info("[LLMService] cache_hit key=%s", cache_key)
            return cached

        logger.info("[LLMService] cache_miss key=%s reason=invalid_payload", cache_key)
        return None

    async def _store_cache(self, cache_key: str, response: str, meta: Optional[Dict] = None) -> None:
        """캐시 저장 + 로깅"""
        if not self._cache_enabled():
            return
        payload: Dict = {"response": response}
        if meta:
            payload["meta"] = meta
        ttl = settings.llm_cache_ttl_sec or 0
        await redis_client.set(cache_key, payload, expire=ttl)
        logger.info("[LLMService] cache_store key=%s ttl=%s", cache_key, ttl)

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

        # Bedrock은 IAM 기반 인증이므로 API Key가 필요 없음
        # 항상 사용 가능하도록 설정 생성 (프론트엔드에서 선택 가능하도록)
        bedrock_cfg = BedrockConfig(
            region_name=settings.bedrock_region or "ap-northeast-2",
            default_model=settings.bedrock_model or "anthropic.claude-3-haiku-20240307-v1:0",
            system_prompt=None,
            enabled=True  # 명시적으로 활성화
        )
        logger.info(
            f"Bedrock 설정 생성 완료: region={bedrock_cfg.region_name}, "
            f"model={bedrock_cfg.default_model}, enabled={bedrock_cfg.enabled}"
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
        if not config:
            # 디버깅: 설정이 None인 경우 상세 로깅
            logger.error(
                f"Provider '{provider}' 설정이 None입니다. "
                f"LLMConfig 상태: bedrock={self.config.bedrock}, "
                f"openai={self.config.openai is not None}, "
                f"anthropic={self.config.anthropic is not None}, "
                f"google={self.config.google is not None}"
            )
            raise LLMServiceError(
                message=f"Provider '{provider}' 설정을 찾을 수 없습니다",
                details={"provider": provider}
            )
        if not config.enabled:
            logger.error(
                f"Provider '{provider}' 설정이 비활성화되어 있습니다. "
                f"config.enabled={config.enabled}"
            )
            raise LLMServiceError(
                message=f"Provider '{provider}' 설정을 찾을 수 없습니다",
                details={"provider": provider}
            )
        return config

    def _get_client(self, provider: str):
        config = self._get_provider_config(provider)
        return self.registry.get_client(provider, config=config)

    def _record_last_used_model(self, model_name: Optional[str]) -> None:
        """최근에 실제 호출에 사용된 모델명을 기록"""
        self._last_used_model = model_name


def get_llm_service() -> LLMService:
    """LLM 서비스 인스턴스 생성"""
    return LLMService()
