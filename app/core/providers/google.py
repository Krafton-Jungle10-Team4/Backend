"""
Google Gemini API 클라이언트 구현
"""
from __future__ import annotations

import asyncio
import logging
import threading
from typing import List, Dict, AsyncGenerator, Any

import google.generativeai as genai

from app.core.llm_base import BaseLLMClient
from app.core.llm_registry import register_provider
from app.core.providers.config import GoogleConfig
from app.core.exceptions import LLMAPIError

logger = logging.getLogger(__name__)


@register_provider("google")
class GoogleClient(BaseLLMClient):
    """Google Gemini API 클라이언트"""

    def __init__(self, config: GoogleConfig):
        self.config = config
        genai.configure(api_key=config.api_key)
        self.default_model = config.default_model
        logger.info("Google Gemini Client 초기화: 모델=%s", self.default_model)

    async def generate(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 2048,
        **kwargs
    ) -> str:
        """Gemini 비스트리밍 응답 생성"""
        try:
            model_name = kwargs.pop("model", None) or self.default_model
            contents = self._format_messages(messages)
            generation_config = {
                "temperature": temperature,
                "max_output_tokens": max_tokens
            }

            text = await asyncio.to_thread(
                self._sync_generate,
                model_name,
                contents,
                generation_config
            )
            return text
        except Exception as e:
            logger.error(f"Gemini generate 호출 실패: {e}", exc_info=True)
            raise LLMAPIError(
                message="Gemini API 호출 중 오류가 발생했습니다",
                details={"error_type": type(e).__name__, "error": str(e)}
            )

    async def generate_stream(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 2048,
        **kwargs
    ) -> AsyncGenerator[str, None]:
        """Gemini 스트리밍 응답"""
        model_name = kwargs.pop("model", None) or self.default_model
        contents = self._format_messages(messages)
        generation_config = {
            "temperature": temperature,
            "max_output_tokens": max_tokens
        }

        queue: asyncio.Queue[Any] = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def producer():
            try:
                model = genai.GenerativeModel(model_name=model_name)
                stream = model.generate_content(
                    contents,
                    generation_config=generation_config,
                    stream=True
                )
                for chunk in stream:
                    text = self._extract_text(chunk)
                    if text:
                        loop.call_soon_threadsafe(queue.put_nowait, text)
            except Exception as exc:  # noqa: BLE001
                loop.call_soon_threadsafe(queue.put_nowait, exc)
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)

        threading.Thread(target=producer, daemon=True).start()

        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                if isinstance(item, Exception):
                    raise item
                yield item
        except Exception as e:
            logger.error(f"Gemini 스트리밍 실패: {e}", exc_info=True)
            raise LLMAPIError(
                message="Gemini 스트리밍 중 오류가 발생했습니다",
                details={"error_type": type(e).__name__, "error": str(e)}
            )

    @staticmethod
    def _format_messages(messages: List[Dict[str, str]]) -> List[Dict[str, Any]]:
        """OpenAI 스타일 메시지를 Gemini 포맷으로 변환"""
        formatted = []
        for message in messages:
            role = message.get("role", "user")
            content = message.get("content")
            if not content:
                continue

            if role == "assistant":
                mapped_role = "model"
            else:
                mapped_role = "user"

            formatted.append(
                {
                    "role": mapped_role,
                    "parts": [content]
                }
            )

        if not formatted:
            formatted.append({"role": "user", "parts": [""]})
        return formatted

    def _sync_generate(
        self,
        model_name: str,
        contents: List[Dict[str, Any]],
        generation_config: Dict[str, Any]
    ) -> str:
        model = genai.GenerativeModel(model_name=model_name)
        response = model.generate_content(
            contents,
            generation_config=generation_config
        )
        return self._extract_text(response)

    @staticmethod
    def _extract_text(response: Any) -> str:
        """Gemini 응답 객체에서 텍스트 추출"""
        if not response:
            return ""
        if getattr(response, "text", None):
            return response.text
        parts = []
        for candidate in getattr(response, "candidates", []) or []:
            content = getattr(candidate, "content", None)
            if not content:
                continue
            for part in getattr(content, "parts", []) or []:
                text = getattr(part, "text", None)
                if text:
                    parts.append(text)
        return "".join(parts)
