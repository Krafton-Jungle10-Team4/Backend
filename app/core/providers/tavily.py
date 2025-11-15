"""
Tavily Search API 클라이언트

Tavily API를 사용하여 실시간 웹 검색을 수행합니다.
"""

from __future__ import annotations

import httpx
import logging
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class TavilySearchRequest(BaseModel):
    """Tavily 검색 요청 모델"""
    query: str = Field(..., description="검색 쿼리")
    search_depth: str = Field(default="basic", pattern="^(basic|advanced)$")
    topic: str = Field(default="general", pattern="^(general|news|finance)$")
    max_results: int = Field(default=5, ge=0, le=20)
    include_domains: Optional[List[str]] = None
    exclude_domains: Optional[List[str]] = None
    time_range: Optional[str] = Field(default=None, pattern="^(day|week|month|year)$")
    start_date: Optional[str] = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    end_date: Optional[str] = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    include_answer: bool = False
    include_raw_content: bool = False


class TavilySearchResult(BaseModel):
    """Tavily 검색 결과 모델"""
    title: str
    url: str
    content: str
    score: float
    raw_content: Optional[str] = None
    favicon: Optional[str] = None


class TavilySearchResponse(BaseModel):
    """Tavily 검색 응답 모델"""
    query: str
    answer: Optional[str] = None
    results: List[TavilySearchResult] = Field(default_factory=list)
    response_time: float
    request_id: Optional[str] = None


class TavilyClient:
    """
    Tavily API 클라이언트

    Tavily Search API를 호출하여 웹 검색을 수행합니다.
    """

    BASE_URL = "https://api.tavily.com"

    def __init__(self, api_key: str):
        """
        TavilyClient 초기화

        Args:
            api_key: Tavily API 키
        """
        self.api_key = api_key
        self.client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self):
        """비동기 컨텍스트 매니저 진입"""
        self.client = httpx.AsyncClient(
            base_url=self.BASE_URL,
            timeout=30.0,
            headers={
                "Content-Type": "application/json",
            }
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """비동기 컨텍스트 매니저 종료"""
        if self.client:
            await self.client.aclose()

    async def search(self, request: TavilySearchRequest) -> TavilySearchResponse:
        """
        Tavily 검색 수행

        Args:
            request: 검색 요청 파라미터

        Returns:
            TavilySearchResponse: 검색 결과

        Raises:
            ValueError: API 키가 유효하지 않거나 요청이 실패한 경우
            httpx.HTTPStatusError: HTTP 에러 발생 시
        """
        if not self.client:
            raise RuntimeError("Client not initialized. Use async context manager.")

        payload = {
            "api_key": self.api_key,
            "query": request.query,
            "search_depth": request.search_depth,
            "topic": request.topic,
            "max_results": request.max_results,
            "include_answer": request.include_answer,
            "include_raw_content": request.include_raw_content,
        }

        # Optional 필드 추가
        if request.include_domains:
            payload["include_domains"] = request.include_domains
        if request.exclude_domains:
            payload["exclude_domains"] = request.exclude_domains
        if request.time_range:
            payload["time_range"] = request.time_range
        if request.start_date:
            payload["start_date"] = request.start_date
        if request.end_date:
            payload["end_date"] = request.end_date

        try:
            response = await self.client.post(
                "/search",
                json=payload
            )
            response.raise_for_status()

            data = response.json()

            return TavilySearchResponse(
                query=data.get("query", request.query),
                answer=data.get("answer"),
                results=[
                    TavilySearchResult(
                        title=result.get("title", ""),
                        url=result.get("url", ""),
                        content=result.get("content", ""),
                        score=result.get("score", 0.0),
                        raw_content=result.get("raw_content"),
                        favicon=result.get("favicon"),
                    )
                    for result in data.get("results", [])
                ],
                response_time=data.get("response_time", 0.0),
                request_id=data.get("request_id"),
            )

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                raise ValueError("Invalid Tavily API key")
            elif e.response.status_code == 429:
                raise ValueError("Rate limit exceeded. Please try again later.")
            elif e.response.status_code == 432:
                raise ValueError("Plan usage exceeded. Please upgrade your plan.")
            else:
                logger.error(f"Tavily API error: {e.response.status_code} - {e.response.text}")
                raise ValueError(f"Tavily API error: {e.response.status_code}")
        except Exception as e:
            logger.error(f"Tavily search error: {str(e)}", exc_info=True)
            raise ValueError(f"Search failed: {str(e)}")

    async def validate_key(self) -> tuple[bool, Optional[str]]:
        """
        API 키 유효성 검증

        Returns:
            tuple[bool, Optional[str]]: (유효 여부, 오류 메시지)
                - (True, None): API 키가 유효함
                - (False, "error message"): API 키가 유효하지 않거나 오류 발생
        """
        try:
            # 간단한 검색으로 키 검증
            test_request = TavilySearchRequest(
                query="test",
                max_results=1
            )
            await self.search(test_request)
            return (True, None)
        except ValueError as e:
            error_message = str(e)
            # 인증 실패인 경우
            if "Invalid Tavily API key" in error_message:
                return (False, "API key is invalid")
            # Rate limit이나 요금 한도 초과 등 다른 오류인 경우
            # 키는 유효하지만 사용할 수 없는 상태이므로 False 반환
            return (False, error_message)
        except Exception as e:
            # 예상치 못한 오류
            return (False, f"Validation failed: {str(e)}")

    async def close(self):
        """클라이언트 종료"""
        if self.client:
            await self.client.aclose()
            self.client = None
