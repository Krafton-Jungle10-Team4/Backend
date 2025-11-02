"""
LLM API 클라이언트 추상화 및 팩토리
"""
from abc import ABC, abstractmethod
from typing import List, Dict, Optional, AsyncGenerator
import logging
from app.config import settings

logger = logging.getLogger(__name__)


class BaseLLMClient(ABC):
    """LLM 클라이언트 추상 베이스 클래스"""

    # generate: 한 번에 완성된 전체 응답 문자열을 반환
    # 간단한 Q&A, 짧은 요약/분류 등 결과가 짧고 빠르게 끝나는 작업 (비스트리밍)
    @abstractmethod
    async def generate(
        # 메서드 안에서 self를 통해 그 객체의 속성에 접근 (self.api_key)
        self,
        # [{"role": "user", "content": "안녕"},
        #  {"role": "assistant", "content": "안녕하세요"}] 같은 형식
        messages: List[Dict[str, str]],
        # 창의성 기본값
        temperature: float = 0.7,
        # 생성 답변 기본값
        max_tokens: int = 1000,
        # 추가 옵션들을 “이름=값” 형태로 무한히 더 받을 수 있는 가변 인자
        **kwargs
    ) -> str:
        """LLM 응답 생성"""
        pass

    # generate_stream: 응답을 토큰/문장 단위로 잘라 여러 번에 걸쳐 내보냄
    # 긴 생성(리포트/코드/설명)으로 사용자가 기다리기 어려울 때
    @abstractmethod
    async def generate_stream(
        self,
        messages: List[Dict[str, str]],
        **kwargs
        # 비동기 제너레이터를 반환
        # 값을 한 번에 다 주지 않고, 비동기적으로 여러 번에 나눠 전달하는 객체.
        # 네트워크 스트리밍처럼 도착하는 대로 조금씩 처리할 때 사용
        # str: 한 덩어리씩 내보내는 값의 타입(여기서는 문자열 청크)
        # None: 외부에서 제너레이터로 "보낼 수 있는 값"의 타입.
        # - 보통 스트리밍 소비만 하니 보낼 값이 없어 None
    ) -> AsyncGenerator[str, None]:
        """스트리밍 응답 생성"""
        pass


# 싱글톤 인스턴스
_llm_client: Optional[BaseLLMClient] = None


def get_llm_client(provider: str = None) -> BaseLLMClient:
    """LLM 클라이언트 팩토리 (싱글톤)"""
    global _llm_client

    if _llm_client is not None:
        return _llm_client

    provider = provider or settings.llm_provider

    if provider == "openai":
        from app.core.providers.openai import OpenAIClient

        if not settings.openai_api_key:
            raise ValueError(
                "OPENAI_API_KEY가 설정되지 않았습니다. "
                ".env.local 파일을 확인하세요."
            )
        _llm_client = OpenAIClient(
            api_key=settings.openai_api_key,
            model=settings.openai_model,
            organization=settings.openai_organization
        )
    elif provider == "anthropic":
        from app.core.providers.anthropic import AnthropicClient

        if not settings.anthropic_api_key:
            raise ValueError(
                "ANTHROPIC_API_KEY가 설정되지 않았습니다. "
                ".env.local 파일을 확인하세요."
            )
        _llm_client = AnthropicClient(
            api_key=settings.anthropic_api_key,
            model=settings.anthropic_model
        )
    else:
        raise ValueError(f"지원하지 않는 LLM 제공자: {provider}")

    return _llm_client
