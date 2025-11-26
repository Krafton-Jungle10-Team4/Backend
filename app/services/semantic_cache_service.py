"""
시맨틱 LLM 캐시 서비스
"""
import logging
import math
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from app.config import settings
from app.core.embeddings import get_embedding_service
from app.core.redis_client import redis_client

logger = logging.getLogger(__name__)


class SemanticCacheService:
    """프롬프트 의미 유사도로 응답을 재사용하는 캐시"""

    def __init__(self) -> None:
        self.enabled = settings.semantic_cache_enabled
        self.cache_key = f"{settings.semantic_cache_prefix}:entries"
        self.threshold = settings.semantic_cache_similarity_threshold
        self.ttl = settings.semantic_cache_ttl_sec
        self.max_entries = max(1, settings.semantic_cache_max_entries)
        self.min_chars = max(1, settings.semantic_cache_min_chars)
        self.embedding_service = get_embedding_service()

    def _available(self) -> bool:
        return self.enabled and bool(redis_client.redis)

    async def lookup(
        self,
        prompt: str,
        meta: Dict[str, Any]
    ) -> Tuple[Optional[str], Optional[List[float]]]:
        """
        시맨틱 캐시 조회

        Returns:
            (캐시된 응답, 요청 프롬프트 임베딩)
        """
        if not self._available():
            return None, None

        normalized = (prompt or "").strip()
        if len(normalized) < self.min_chars:
            return None, None

        embedding = await self.embedding_service.embed_query(normalized)
        entries = await self._load_entries()
        if not entries:
            return None, embedding

        match = self._select_best_match(entries, embedding, meta)
        if match:
            logger.info(
                "[SemanticCache] hit score=%.3f provider=%s model=%s",
                match["score"],
                meta.get("provider"),
                meta.get("model")
            )
            return match["response"], embedding

        logger.debug(
            "[SemanticCache] miss provider=%s model=%s entries=%d",
            meta.get("provider"),
            meta.get("model"),
            len(entries)
        )
        return None, embedding

    async def store(
        self,
        prompt: str,
        response: str,
        meta: Dict[str, Any],
        embedding: Optional[List[float]] = None
    ) -> None:
        """시맨틱 캐시에 응답 저장"""
        if not self._available():
            return

        normalized = (prompt or "").strip()
        if len(normalized) < self.min_chars:
            return
        if not response or not response.strip():
            return

        if embedding is None:
            embedding = await self.embedding_service.embed_query(normalized)

        entries = await self._load_entries()
        entries.append({
            "embedding": embedding,
            "response": response,
            "meta": meta,
            "prompt_preview": normalized[:120],
            "created_at": datetime.utcnow().isoformat()
        })

        if len(entries) > self.max_entries:
            entries = entries[-self.max_entries:]

        expire = self.ttl if self.ttl and self.ttl > 0 else None
        await redis_client.set(self.cache_key, entries, expire=expire)
        logger.info(
            "[SemanticCache] store provider=%s model=%s size=%d",
            meta.get("provider"),
            meta.get("model"),
            len(entries)
        )

    async def _load_entries(self) -> List[Dict[str, Any]]:
        data = await redis_client.get(self.cache_key)
        if isinstance(data, list):
            return data
        return []

    def _select_best_match(
        self,
        entries: List[Dict[str, Any]],
        embedding: List[float],
        meta: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        best_response: Optional[str] = None
        best_score = 0.0

        for entry in entries:
            entry_meta = entry.get("meta") or {}
            if not self._meta_matches(entry_meta, meta):
                continue

            entry_embedding = entry.get("embedding")
            if not entry_embedding:
                continue

            score = self._cosine_similarity(embedding, entry_embedding)
            if score > best_score:
                best_score = score
                best_response = entry.get("response")

        if best_response and best_score >= self.threshold:
            return {
                "response": best_response,
                "score": best_score
            }
        return None

    def _meta_matches(self, cached_meta: Dict[str, Any], request_meta: Dict[str, Any]) -> bool:
        required_keys = ("provider", "model", "system_prompt_hash", "temperature", "max_tokens")
        for key in required_keys:
            if cached_meta.get(key) != request_meta.get(key):
                return False

        # context_hash나 기타 메타데이터는 있을 때만 비교
        optional_keys = ("context_hash",)
        for key in optional_keys:
            cached_value = cached_meta.get(key)
            request_value = request_meta.get(key)
            if cached_value or request_value:
                if cached_value != request_value:
                    return False

        return True

    def _cosine_similarity(self, vec_a: List[float], vec_b: List[float]) -> float:
        if not vec_a or not vec_b or len(vec_a) != len(vec_b):
            return 0.0

        dot = 0.0
        norm_a = 0.0
        norm_b = 0.0

        for a, b in zip(vec_a, vec_b):
            dot += a * b
            norm_a += a * a
            norm_b += b * b

        if norm_a == 0 or norm_b == 0:
            return 0.0

        return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))
