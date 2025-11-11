"""
LLM 클라이언트 베이스 클래스
"""
from abc import ABC, abstractmethod
from typing import List, Dict, AsyncGenerator


class BaseLLMClient(ABC):
    """LLM 클라이언트 추상 베이스 클래스"""

    @abstractmethod
    async def generate(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 4000,
        **kwargs
    ) -> str:
        """LLM 응답 생성"""
        pass

    @abstractmethod
    async def generate_stream(
        self,
        messages: List[Dict[str, str]],
        **kwargs
    ) -> AsyncGenerator[str, None]:
        """스트리밍 응답 생성"""
        pass
