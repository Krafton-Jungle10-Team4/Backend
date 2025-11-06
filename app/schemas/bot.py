"""봇 관련 스키마"""
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List, Literal
from datetime import datetime
from enum import Enum

from app.schemas.workflow import Workflow


class BotGoal(str, Enum):
    """봇 목표 ENUM"""
    CUSTOMER_SUPPORT = "customer-support"
    AI_ASSISTANT = "ai-assistant"
    SALES = "sales"
    OTHER = "other"


class CreateBotRequest(BaseModel):
    """봇 생성 요청"""
    name: str = Field(..., min_length=1, max_length=100, description="봇 이름")
    goal: Optional[BotGoal] = Field(None, description="봇의 목표")
    personality: Optional[str] = Field(None, max_length=2000, description="봇의 성격/어조")
    knowledge: Optional[List[str]] = Field(default_factory=list, description="문서 ID 배열")
    workflow: Optional[Workflow] = Field(None, description="Workflow 정의")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "고객 지원 봇",
                "goal": "customer-support",
                "personality": "친절하고 전문적인 어조",
                "knowledge": ["doc_abc123", "doc_def456"],
                "workflow": {
                    "nodes": [
                        {
                            "id": "1",
                            "type": "start",
                            "position": {"x": 100, "y": 150},
                            "data": {"title": "Start", "desc": "시작 노드", "type": "start"}
                        }
                    ],
                    "edges": []
                }
            }
        }
    )


class BotResponse(BaseModel):
    """봇 응답"""
    id: str = Field(..., description="봇 ID", serialization_alias="id")
    name: str = Field(..., description="봇 이름")
    description: Optional[str] = Field(None, description="봇 설명")
    avatar: Optional[str] = Field(None, description="봇 아바타 URL")
    status: Literal["active", "inactive", "error"] = Field(..., description="봇 상태")
    messagesCount: int = Field(..., description="메시지 개수", serialization_alias="messagesCount")
    errorsCount: int = Field(..., description="오류 개수", serialization_alias="errorsCount")
    createdAt: datetime = Field(..., description="생성 시간", serialization_alias="createdAt")
    updatedAt: Optional[datetime] = Field(None, description="수정 시간", serialization_alias="updatedAt")
    workflow: Optional[Workflow] = Field(None, description="Workflow 정의 (상세 조회에만 포함)")

    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
        json_schema_extra={
            "example": {
                "id": "bot_1730718000_a8b9c3d4e",
                "name": "고객 지원 봇",
                "description": "customer-support",
                "avatar": None,
                "status": "active",
                "messagesCount": 0,
                "errorsCount": 0,
                "createdAt": "2024-11-04T12:00:00Z",
                "updatedAt": None
            }
        }
    )

    @classmethod
    def from_bot(cls, bot, include_workflow: bool = False):
        """Bot 모델에서 BotResponse 생성

        Args:
            bot: Bot 모델 인스턴스
            include_workflow: workflow 포함 여부 (상세 조회에만 True)
        """
        return cls(
            id=bot.bot_id,
            name=bot.name,
            description=bot.description,
            avatar=bot.avatar,
            status=bot.status.value,
            messagesCount=bot.messages_count,
            errorsCount=bot.errors_count,
            createdAt=bot.created_at,
            updatedAt=bot.updated_at,
            workflow=bot.workflow if include_workflow else None
        )


class BotListResponse(BaseModel):
    """봇 목록 응답"""
    bots: List[BotResponse] = Field(..., description="봇 목록")
    total: int = Field(..., description="전체 봇 개수")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "bots": [
                    {
                        "id": "bot_1730718000_a8b9c3d4e",
                        "name": "고객 지원 봇",
                        "description": "customer-support",
                        "avatar": None,
                        "status": "active",
                        "messagesCount": 0,
                        "errorsCount": 0,
                        "createdAt": "2024-11-04T12:00:00Z",
                        "updatedAt": None
                    }
                ],
                "total": 1
            }
        }
    )


class UpdateBotRequest(BaseModel):
    """봇 수정 요청"""
    name: Optional[str] = Field(None, min_length=1, max_length=100, description="봇 이름")
    goal: Optional[BotGoal] = Field(None, description="봇의 목표")
    personality: Optional[str] = Field(None, max_length=2000, description="봇의 성격/어조")
    avatar: Optional[str] = Field(None, max_length=500, description="봇 아바타 URL")
    status: Optional[Literal["active", "inactive", "error"]] = Field(None, description="봇 상태")
    workflow: Optional[Workflow] = Field(None, description="Workflow 정의")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "수정된 봇 이름",
                "goal": "ai-assistant",
                "personality": "더욱 친절한 어조",
                "status": "active"
            }
        }
    )


class ErrorResponse(BaseModel):
    """에러 응답"""
    error: str = Field(..., description="에러 메시지")
    detail: Optional[str] = Field(None, description="상세 정보")
    code: Optional[str] = Field(None, description="에러 코드")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "error": "Invalid request",
                "detail": "name field is required",
                "code": "VALIDATION_ERROR"
            }
        }
    )
