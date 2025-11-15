"""
Tavily Search API 엔드포인트

검색 프리뷰 및 API 키 검증 기능을 제공합니다.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, List
from app.core.auth.dependencies import get_current_user_from_jwt as get_current_user
from app.models.user import User
from app.core.providers.tavily import TavilyClient, TavilySearchRequest
from app.config import settings
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


class TavilySearchRequestModel(BaseModel):
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
    api_key: Optional[str] = None  # 테스트용 (선택사항)


class TavilyValidateKeyRequest(BaseModel):
    """API 키 검증 요청 모델"""
    api_key: str = Field(..., description="Tavily API 키")


class TavilyValidateKeyResponse(BaseModel):
    """API 키 검증 응답 모델"""
    valid: bool
    message: str


@router.post("/search")
async def tavily_search(
    request: TavilySearchRequestModel,
    current_user: User = Depends(get_current_user)
):
    """
    Tavily 검색 (프리뷰 및 테스트용)

    노드 설정 패널에서 검색을 테스트할 때 사용합니다.
    """
    try:
        # API 키 결정 (테스트용 키 또는 시스템 기본 키)
        api_key = request.api_key or settings.tavily_api_key

        if not api_key:
            raise HTTPException(
                status_code=400,
                detail="Tavily API key is required"
            )

        # Tavily 클라이언트 생성 및 검색 수행
        async with TavilyClient(api_key=api_key) as tavily_client:
            # 검색 요청 생성
            search_request = TavilySearchRequest(
                query=request.query,
                search_depth=request.search_depth,
                topic=request.topic,
                max_results=request.max_results,
                include_domains=request.include_domains,
                exclude_domains=request.exclude_domains,
                time_range=request.time_range,
                start_date=request.start_date,
                end_date=request.end_date,
                include_answer=request.include_answer,
                include_raw_content=request.include_raw_content,
            )

            # 검색 수행
            result = await tavily_client.search(search_request)

            # 응답 변환
            return {
                "query": result.query,
                "answer": result.answer,
                "results": [
                    {
                        "title": r.title,
                        "url": r.url,
                        "content": r.content,
                        "score": r.score,
                        "raw_content": r.raw_content,
                        "favicon": r.favicon,
                    }
                    for r in result.results
                ],
                "response_time": result.response_time,
                "request_id": result.request_id,
            }

    except ValueError as e:
        error_message = str(e)
        if "Invalid Tavily API key" in error_message:
            raise HTTPException(status_code=401, detail=error_message)
        elif "Rate limit exceeded" in error_message:
            raise HTTPException(status_code=429, detail=error_message)
        elif "Plan usage exceeded" in error_message:
            raise HTTPException(status_code=432, detail=error_message)
        else:
            raise HTTPException(status_code=400, detail=error_message)
    except Exception as e:
        logger.error(f"Tavily search error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Search failed")


@router.post("/validate-key", response_model=TavilyValidateKeyResponse)
async def validate_tavily_key(
    request: TavilyValidateKeyRequest,
    current_user: User = Depends(get_current_user)
):
    """
    Tavily API 키 유효성 검증

    MCP 키 관리 페이지에서 API 키를 검증할 때 사용합니다.
    """
    try:
        api_key = request.api_key
        if not api_key:
            raise HTTPException(status_code=400, detail="API key is required")

        async with TavilyClient(api_key=api_key) as tavily_client:
            is_valid, error_message = await tavily_client.validate_key()
            if is_valid:
                return TavilyValidateKeyResponse(
                    valid=True,
                    message="API key is valid"
                )
            else:
                # validate_key()가 반환한 상세 오류 메시지 사용
                return TavilyValidateKeyResponse(
                    valid=False,
                    message=error_message or "API key validation failed"
                )
    except ValueError as e:
        # validate_key() 내부에서 처리되지 않은 ValueError (예: 클라이언트 초기화 실패)
        error_message = str(e)
        if "Invalid Tavily API key" in error_message:
            return TavilyValidateKeyResponse(
                valid=False,
                message="API key is invalid"
            )
        else:
            # Rate limit, 요금 한도 초과 등 다른 오류
            return TavilyValidateKeyResponse(
                valid=False,
                message=error_message
            )
    except Exception as e:
        logger.error(f"Tavily key validation error: {str(e)}", exc_info=True)
        return TavilyValidateKeyResponse(
            valid=False,
            message=f"Validation failed: {str(e)}"
        )
