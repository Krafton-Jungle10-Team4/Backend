"""
마켓플레이스 Pydantic 스키마
"""
from pydantic import BaseModel, Field, validator
from typing import Optional, List
from datetime import datetime
from uuid import UUID


class MarketplaceItemCreate(BaseModel):
    """마켓플레이스 아이템 생성 요청"""
    workflow_version_id: UUID = Field(..., description="워크플로우 버전 ID")
    display_name: Optional[str] = Field(None, max_length=255, description="표시 이름 (비어있으면 워크플로우 버전의 library_name 사용)")
    description: Optional[str] = Field(None, description="설명 (비어있으면 워크플로우 버전의 library_description 사용)")
    category: Optional[str] = Field(None, max_length=100, description="카테고리")
    tags: Optional[List[str]] = Field(None, description="태그 목록")
    thumbnail_url: Optional[str] = Field(None, max_length=500, description="썸네일 URL")
    screenshots: Optional[List[str]] = Field(None, description="스크린샷 URL 목록")
    readme: Optional[str] = Field(None, description="마크다운 형식 상세 설명")
    use_cases: Optional[List[str]] = Field(None, description="사용 사례 목록")


class MarketplaceItemUpdate(BaseModel):
    """마켓플레이스 아이템 수정 요청"""
    display_name: Optional[str] = Field(None, max_length=255, description="표시 이름")
    description: Optional[str] = Field(None, description="설명")
    category: Optional[str] = Field(None, max_length=100, description="카테고리")
    tags: Optional[List[str]] = Field(None, description="태그 목록")
    thumbnail_url: Optional[str] = Field(None, max_length=500, description="썸네일 URL")
    screenshots: Optional[List[str]] = Field(None, description="스크린샷 URL 목록")
    readme: Optional[str] = Field(None, description="마크다운 형식 상세 설명")
    use_cases: Optional[List[str]] = Field(None, description="사용 사례 목록")
    is_active: Optional[bool] = Field(None, description="활성 상태")
    status: Optional[str] = Field(None, description="상태 (published, suspended, draft)")


class PublisherInfo(BaseModel):
    """게시자 정보"""
    team_id: Optional[str] = None
    team_name: Optional[str] = None
    user_id: Optional[str] = None
    username: Optional[str] = None


class WorkflowVersionInfo(BaseModel):
    """워크플로우 버전 정보"""
    id: UUID
    bot_id: str
    version: str
    node_count: Optional[int] = None
    edge_count: Optional[int] = None
    input_schema: Optional[List[dict]] = None
    output_schema: Optional[List[dict]] = None


class MarketplaceItemResponse(BaseModel):
    """마켓플레이스 아이템 응답"""
    id: UUID
    workflow_version_id: UUID

    # 메타데이터
    display_name: str
    description: Optional[str] = None
    category: Optional[str] = None
    tags: Optional[List[str]] = None

    # 이미지
    thumbnail_url: Optional[str] = None
    screenshots: Optional[List[str]] = None

    # 상태
    is_active: bool
    status: str

    # 통계
    download_count: int
    view_count: int
    rating_average: float
    rating_count: int

    # 추가 정보
    readme: Optional[str] = None
    use_cases: Optional[List[str]] = None

    # 타임스탬프
    published_at: datetime
    updated_at: datetime

    # 관계 정보
    publisher: Optional[PublisherInfo] = None
    workflow_version: Optional[WorkflowVersionInfo] = None

    class Config:
        from_attributes = True


class MarketplaceItemListResponse(BaseModel):
    """마켓플레이스 아이템 목록 응답"""
    items: List[MarketplaceItemResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class MarketplaceReviewCreate(BaseModel):
    """마켓플레이스 리뷰 생성 요청"""
    marketplace_item_id: UUID
    rating: int = Field(..., ge=1, le=5, description="평점 (1-5)")
    comment: Optional[str] = Field(None, description="리뷰 코멘트")


class MarketplaceReviewResponse(BaseModel):
    """마켓플레이스 리뷰 응답"""
    id: UUID
    marketplace_item_id: UUID
    user_id: str
    username: Optional[str] = None
    rating: int
    comment: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
