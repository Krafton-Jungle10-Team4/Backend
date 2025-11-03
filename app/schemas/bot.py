"""봇 관련 스키마"""
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List, Literal
from datetime import datetime


class CreateBotRequest(BaseModel):
    """봇 생성 요청"""
    name: str = Field(..., min_length=1, max_length=100, description="봇 이름")
    goal: Optional[str] = Field(None, max_length=500, description="봇의 목표")
    personality: Optional[str] = Field(None, max_length=2000, description="봇의 성격/어조")
    knowledge: Optional[List[str]] = Field(default_factory=list, description="봇의 지식 항목")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "고객 지원 봇",
                "goal": "customer-support",
                "personality": "친절하고 전문적인 어조",
                "knowledge": ["제품 정보", "가격 정책"]
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
    def from_bot(cls, bot):
        """Bot 모델에서 BotResponse 생성"""
        return cls(
            id=bot.bot_id,
            name=bot.name,
            description=bot.description,
            avatar=bot.avatar,
            status=bot.status.value,
            messagesCount=bot.messages_count,
            errorsCount=bot.errors_count,
            createdAt=bot.created_at,
            updatedAt=bot.updated_at
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
