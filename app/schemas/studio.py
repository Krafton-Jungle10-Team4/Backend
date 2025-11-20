"""
스튜디오 통합 뷰 스키마
"""
from typing import List, Optional, Literal
from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime

# Enums
WorkflowStatus = Literal["running", "stopped", "pending", "error"]
DeploymentState = Literal["deployed", "stopped", "error", "deploying"]
MarketplaceState = Literal["unpublished", "published", "pending"]


class StudioWorkflowItem(BaseModel):
    """스튜디오 워크플로우 카드 아이템 (통합 뷰)"""
    id: str = Field(..., description="봇 ID")
    name: str = Field(..., description="봇 이름")
    description: Optional[str] = Field(None, description="봇 설명")
    category: str = Field(..., description="봇 카테고리")
    tags: List[str] = Field(default_factory=list, description="태그 배열")

    # 워크플로우 상태
    status: WorkflowStatus = Field(..., description="워크플로우 상태")
    latestVersion: Optional[str] = Field(None, description="최신 버전 번호")
    latestVersionId: Optional[str] = Field(
        None, description="최신 버전 UUID (배포/게시용)"
    )
    previousVersionCount: int = Field(0, description="이전 버전 개수")

    # 배포 정보
    deploymentState: DeploymentState = Field("stopped", description="배포 상태")
    deploymentUrl: Optional[str] = Field(None, description="배포 URL")
    lastDeployedAt: Optional[str] = Field(None, description="마지막 배포 시간 (ISO 8601)")

    # 마켓플레이스 정보
    marketplaceState: MarketplaceState = Field("unpublished", description="마켓플레이스 상태")
    lastPublishedAt: Optional[str] = Field(None, description="마지막 게시 시간 (ISO 8601)")

    # 타임스탬프
    createdAt: str = Field(..., description="생성 시간 (ISO 8601)")
    updatedAt: str = Field(..., description="수정 시간 (ISO 8601)")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": "bot_1730718000_a8b9c3d4e",
                "name": "고객 지원 챗봇",
                "description": "24/7 고객 문의 자동 응답 시스템",
                "category": "chatbot",
                "tags": ["Production", "Customer Support", "AI"],
                "status": "running",
                "latestVersion": "v1.2",
                "latestVersionId": "0e7a6c06-9d17-4a0d-8b51-7b6b8cbb2f27",
                "previousVersionCount": 3,
                "deploymentState": "deployed",
                "deploymentUrl": "https://widget.snapagent.shop/app/abc123",
                "lastDeployedAt": "2024-11-15T10:30:00Z",
                "marketplaceState": "published",
                "lastPublishedAt": "2024-11-10T08:00:00Z",
                "createdAt": "2024-10-01T09:00:00Z",
                "updatedAt": "2024-11-15T10:30:00Z"
            }
        }
    )


class StatsInfo(BaseModel):
    """통계 정보"""
    total: int = Field(..., description="전체 워크플로우 수")
    running: int = Field(..., description="실행 중인 워크플로우 수")
    stopped: int = Field(..., description="중지된 워크플로우 수")
    pending: int = Field(0, description="대기 중인 워크플로우 수")
    error: int = Field(0, description="오류 상태 워크플로우 수")


class FiltersInfo(BaseModel):
    """필터 정보"""
    availableTags: List[str] = Field(..., description="사용 가능한 태그 목록")


class PaginationInfo(BaseModel):
    """페이지네이션 정보"""
    page: int = Field(..., description="현재 페이지 (1부터 시작)")
    limit: int = Field(..., description="페이지당 항목 수")
    total: int = Field(..., description="전체 항목 수")
    totalPages: int = Field(..., description="전체 페이지 수")


class StudioWorkflowListResponse(BaseModel):
    """스튜디오 워크플로우 목록 응답"""
    data: List[StudioWorkflowItem] = Field(..., description="워크플로우 카드 목록")
    pagination: PaginationInfo = Field(..., description="페이지네이션 정보")
    stats: StatsInfo = Field(..., description="통계 정보")
    filters: FiltersInfo = Field(..., description="필터 정보")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "data": [
                    {
                        "id": "bot_1730718000_a8b9c3d4e",
                        "name": "고객 지원 챗봇",
                        "description": "24/7 고객 문의 자동 응답 시스템",
                        "category": "chatbot",
                        "tags": ["Production", "Customer Support", "AI"],
                        "status": "running",
                        "latestVersion": "v1.2",
                        "previousVersionCount": 3,
                        "deploymentState": "deployed",
                        "deploymentUrl": "https://widget.snapagent.shop/app/abc123",
                        "lastDeployedAt": "2024-11-15T10:30:00Z",
                        "marketplaceState": "published",
                        "lastPublishedAt": "2024-11-10T08:00:00Z",
                        "createdAt": "2024-10-01T09:00:00Z",
                        "updatedAt": "2024-11-15T10:30:00Z"
                    }
                ],
                "pagination": {
                    "page": 1,
                    "limit": 12,
                    "total": 24,
                    "totalPages": 2
                },
                "stats": {
                    "total": 24,
                    "running": 16,
                    "stopped": 6,
                    "pending": 1,
                    "error": 1
                },
                "filters": {
                    "availableTags": ["Production", "Customer Support", "AI"]
                }
            }
        }
    )
