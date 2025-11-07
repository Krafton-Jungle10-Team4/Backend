"""
LLM 서비스
"""
import logging
from typing import Optional

from app.core.llm_client import get_llm_client
from app.config import settings

logger = logging.getLogger(__name__)


class LLMService:
    """LLM 서비스"""

    def __init__(self):
        self.llm_client = get_llm_client()

    async def generate(
        self,
        prompt: str,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 1000
    ) -> str:
        """
        워크플로우용 LLM 생성 (단순 프롬프트 전달)

        Args:
            prompt: 프롬프트 텍스트
            model: 모델 이름 (현재는 사용되지 않음, 향후 동적 모델 선택 지원)
            temperature: Temperature 설정
            max_tokens: 최대 토큰 수

        Returns:
            LLM 응답
        """
        logger.info(f"[LLMService] LLM generate 호출: model={model}, temp={temperature}")

        messages = [
            {"role": "user", "content": prompt}
        ]

        # LLM 호출
        response = await self.llm_client.generate(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens
        )

        logger.info(f"[LLMService] LLM 응답 생성 완료: {len(response)}자")
        return response

    async def generate_response(
        self,
        query: str,
        context: str,
        temperature: float = 0.7,
        max_tokens: int = 2000
    ) -> str:
        """
        LLM 응답 생성 (RAG 파이프라인용)

        Args:
            query: 사용자 질문
            context: 컨텍스트 (검색된 문서)
            temperature: Temperature 설정
            max_tokens: 최대 토큰 수

        Returns:
            LLM 응답
        """
        logger.info(f"[LLMService] LLM 호출: query='{query[:50]}...', temp={temperature}")

        # 프롬프트 메시지 구성
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

        # LLM 호출
        response = await self.llm_client.generate(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens
        )

        logger.info(f"[LLMService] LLM 응답 생성 완료: {len(response)}자")
        return response


def get_llm_service() -> LLMService:
    """LLM 서비스 인스턴스 생성"""
    return LLMService()
