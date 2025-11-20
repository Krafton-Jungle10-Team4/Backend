"""
스튜디오 API 통합 테스트
"""
import pytest
from httpx import AsyncClient
from app.main import app


@pytest.mark.asyncio
async def test_get_studio_workflows(async_client: AsyncClient, auth_headers: dict):
    """스튜디오 워크플로우 목록 조회 테스트"""

    response = await async_client.get(
        "/api/v1/studio/workflows?page=1&limit=12",
        headers=auth_headers
    )

    assert response.status_code == 200
    data = response.json()

    # 응답 구조 검증
    assert "data" in data
    assert "pagination" in data
    assert "stats" in data
    assert "filters" in data

    # Pagination 검증
    assert data["pagination"]["page"] == 1
    assert data["pagination"]["limit"] == 12
    assert "total" in data["pagination"]
    assert "totalPages" in data["pagination"]

    # Stats 검증
    assert "total" in data["stats"]
    assert "running" in data["stats"]
    assert "stopped" in data["stats"]

    # Filters 검증
    assert "availableTags" in data["filters"]
    assert isinstance(data["filters"]["availableTags"], list)

    # Data 검증 (최소 1개 이상의 워크플로우가 있다고 가정)
    if len(data["data"]) > 0:
        item = data["data"][0]
        assert "id" in item
        assert "name" in item
        assert "status" in item
        assert "deploymentState" in item
        assert "marketplaceState" in item
        assert "latestVersionId" in item
