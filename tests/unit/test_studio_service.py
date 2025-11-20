"""
스튜디오 서비스 단위 테스트
"""
import pytest
from unittest.mock import MagicMock, AsyncMock
from app.services.studio_service import (
    _convert_bot_status_to_workflow_status,
    _convert_deployment_status,
    _build_deployment_url
)
from app.models.bot import BotStatus


def test_convert_bot_status_to_workflow_status():
    """Bot 상태를 Workflow 상태로 변환 테스트"""
    assert _convert_bot_status_to_workflow_status(BotStatus.ACTIVE) == "running"
    assert _convert_bot_status_to_workflow_status(BotStatus.INACTIVE) == "stopped"
    assert _convert_bot_status_to_workflow_status(BotStatus.DRAFT) == "pending"
    assert _convert_bot_status_to_workflow_status(BotStatus.ERROR) == "error"


def test_convert_deployment_status():
    """Deployment 상태 변환 테스트"""
    assert _convert_deployment_status(None) == "not-deployed"
    assert _convert_deployment_status("draft") == "draft"
    assert _convert_deployment_status("published") == "published"
    assert _convert_deployment_status("suspended") == "disabled"
    assert _convert_deployment_status("unknown") == "not-deployed"


def test_build_deployment_url():
    """Deployment URL 생성 테스트"""
    assert _build_deployment_url(None) is None
    assert _build_deployment_url("abc123") == "http://localhost:8001/widget/abc123"
