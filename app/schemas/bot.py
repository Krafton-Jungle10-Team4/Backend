"""봇 관련 스키마"""
from typing import Optional, List, Literal, Dict, Any, Union, Annotated

from pydantic import BaseModel, Field, ConfigDict, field_validator
from datetime import datetime
from enum import Enum
import json

from app.schemas.workflow import Workflow
from app.models.bot import BotCategory

# 사용자 정의 Goal 입력 타입 (자유 텍스트 허용)
GoalText = Annotated[str, Field(min_length=1, max_length=500)]


def _normalize_goal_value(value: Optional[Union["BotGoal", str]]) -> Optional[Union["BotGoal", str]]:
    """goal 입력값 공통 정규화"""
    if value is None:
        return None

    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            raise ValueError("goal must not be empty")
        return stripped

    return value


class BotGoal(str, Enum):
    """봇 목표 ENUM"""
    CUSTOMER_SUPPORT = "customer-support"
    AI_ASSISTANT = "ai-assistant"
    SALES = "sales"
    OTHER = "other"


class CreateBotRequest(BaseModel):
    """봇 생성 요청"""
    name: str = Field(..., min_length=1, max_length=100, description="봇 이름")
    goal: Optional[Union[BotGoal, GoalText]] = Field(
        None,
        description="봇의 목표 (사전 정의된 유형 또는 사용자 정의 텍스트)"
    )
    personality: Optional[str] = Field(None, max_length=2000, description="봇의 성격/어조")
    knowledge: Optional[List[str]] = Field(default_factory=list, description="문서 ID 배열")
    session_id: Optional[str] = Field(
        default=None,
        description="Setup 단계에서 사용한 임시 봇/세션 ID (session_... 형식)"
    )
    workflow: Optional[Workflow] = Field(None, description="Workflow 정의")
    category: Optional[BotCategory] = Field(default=BotCategory.WORKFLOW, description="봇 카테고리")
    tags: List[str] = Field(default_factory=list, max_items=10, description="봇 태그 배열")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "고객 지원 봇",
                "goal": "customer-support",
                "personality": "친절하고 전문적인 어조",
                "knowledge": ["doc_abc123", "doc_def456"],
                "session_id": "session_1730718000_ab12cd3",
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

    @field_validator("goal")
    @classmethod
    def validate_goal(cls, value):
        return _normalize_goal_value(value)


class BotResponse(BaseModel):
    """봇 응답"""
    id: str = Field(..., description="봇 ID", serialization_alias="id")
    name: str = Field(..., description="봇 이름")
    description: Optional[str] = Field(None, description="봇 설명")
    avatar: Optional[str] = Field(None, description="봇 아바타 URL")
    status: Literal["draft", "active", "inactive", "error"] = Field(..., description="봇 상태")
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


class UpdateBotRequestPut(BaseModel):
    """봇 수정 요청 (PUT - 전체 업데이트, 모든 필드 필수)"""
    name: str = Field(..., min_length=1, max_length=100, description="봇 이름")
    description: Optional[str] = Field(None, max_length=2000, description="봇 설명")
    workflow: Workflow = Field(..., description="Workflow 정의 (필수)")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "고객 문의 응답 봇 v2",
                "description": "업데이트된 설명",
                "workflow": {
                    "schemaVersion": "1.0.0",
                    "workflowRevision": 1,
                    "nodes": [],
                    "edges": []
                }
            }
        }
    )


class UpdateBotRequestPatch(BaseModel):
    """봇 수정 요청 (PATCH - 부분 업데이트, 모든 필드 선택)"""
    name: Optional[str] = Field(None, min_length=1, max_length=100, description="봇 이름")
    description: Optional[str] = Field(None, max_length=2000, description="봇 설명")
    goal: Optional[Union[BotGoal, GoalText]] = Field(
        None,
        description="봇의 목표 (사전 정의된 유형 또는 사용자 정의 텍스트)"
    )
    personality: Optional[str] = Field(None, max_length=2000, description="봇의 성격/어조")
    knowledge: Optional[List[str]] = Field(None, description="문서 ID 배열 (기존 지식 전체 대체)")
    workflow: Optional[Workflow] = Field(None, description="Workflow 정의")
    category: Optional[BotCategory] = Field(None, description="봇 카테고리")
    tags: Optional[List[str]] = Field(None, max_items=10, description="봇 태그 배열")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "수정된 봇 이름",
                "description": "수정된 설명"
            }
        }
    )

    @field_validator("goal")
    @classmethod
    def validate_goal(cls, value):
        return _normalize_goal_value(value)


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


# ========== 명세서 준수 새로운 스키마 ==========

class BotListItemResponse(BaseModel):
    """Bot 목록용 응답 스키마 (명세서 준수)"""
    id: str = Field(..., description="봇 ID")
    name: str = Field(..., description="봇 이름")
    description: Optional[str] = Field(None, description="봇 설명")
    isActive: bool = Field(..., description="활성화 상태")
    nodeCount: int = Field(..., description="Workflow 노드 개수")
    edgeCount: int = Field(..., description="Workflow 엣지 개수")
    category: str = Field(..., description="봇 카테고리")
    tags: List[str] = Field(default_factory=list, description="봇 태그")
    createdBy: int = Field(..., description="생성자 user_id")
    createdAt: datetime = Field(..., description="생성 시간")
    updatedAt: Optional[datetime] = Field(None, description="수정 시간")

    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True
    )

    @classmethod
    def from_bot(cls, bot) -> "BotListItemResponse":
        """Bot 모델에서 응답 생성"""
        # workflow JSON에서 node/edge 개수 계산
        node_count = 0
        edge_count = 0

        if bot.workflow:
            workflow_data = bot.workflow if isinstance(bot.workflow, dict) else json.loads(bot.workflow)
            node_count = len(workflow_data.get('nodes', []))
            edge_count = len(workflow_data.get('edges', []))

        return cls(
            id=bot.bot_id,
            name=bot.name,
            description=bot.description,
            isActive=(bot.status.value == "active"),
            nodeCount=node_count,
            edgeCount=edge_count,
            category=bot.category.value,
            tags=bot.tags if bot.tags else [],
            createdBy=bot.user_id,
            createdAt=bot.created_at,
            updatedAt=bot.updated_at
        )


class PaginationInfo(BaseModel):
    """페이지네이션 정보"""
    page: int = Field(..., description="현재 페이지 번호")
    limit: int = Field(..., description="페이지당 항목 수")
    total: int = Field(..., description="전체 항목 수")
    totalPages: int = Field(..., description="전체 페이지 수")

    model_config = ConfigDict(
        from_attributes=True
    )


class BotListResponseV2(BaseModel):
    """명세서 준수 Bot 목록 응답"""
    data: List[BotListItemResponse] = Field(..., description="Bot 목록")
    pagination: PaginationInfo = Field(..., description="페이지네이션 정보")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "data": [
                    {
                        "id": "bot_1730718000_a8b9c3d4e",
                        "name": "Test",
                        "description": "고객 문의 응답 봇",
                        "isActive": True,
                        "nodeCount": 4,
                        "edgeCount": 3,
                        "createdAt": "2025-11-04T19:21:11.000Z",
                        "updatedAt": "2025-11-04T19:21:11.000Z"
                    }
                ],
                "pagination": {
                    "page": 1,
                    "limit": 10,
                    "total": 1,
                    "totalPages": 1
                }
            }
        }
    )


class BotDetailResponse(BaseModel):
    """Bot 상세 조회 응답 (명세서 준수)"""
    data: Dict[str, Any] = Field(..., description="Bot 상세 데이터")

    @classmethod
    def from_bot(cls, bot) -> "BotDetailResponse":
        """Bot 모델에서 상세 응답 생성"""
        # Workflow 데이터 처리
        workflow_dict = None
        if bot.workflow:
            workflow_data = bot.workflow if isinstance(bot.workflow, dict) else json.loads(bot.workflow)
            # 명세서 형식으로 변환
            workflow_dict = {
                "schemaVersion": workflow_data.get("schemaVersion", "1.0.0"),
                "workflowRevision": workflow_data.get("workflowRevision", 0),
                "projectId": workflow_data.get("projectId"),
                "createdAt": workflow_data.get("createdAt"),
                "updatedAt": workflow_data.get("updatedAt"),
                "nodes": workflow_data.get("nodes", []),
                "edges": workflow_data.get("edges", [])
            }

        return cls(
            data={
                "id": bot.bot_id,
                "name": bot.name,
                "description": bot.description,
                "isActive": bot.status.value == "active",
                "category": bot.category.value,
                "tags": bot.tags if bot.tags else [],
                "createdBy": bot.user_id,
                "createdAt": bot.created_at.isoformat() + "Z",
                "updatedAt": bot.updated_at.isoformat() + "Z" if bot.updated_at else None,
                "workflow": workflow_dict
            }
        )


class CreateBotRequestV2(BaseModel):
    """Bot 생성 요청 (명세서 준수)"""
    name: str = Field(..., min_length=1, max_length=100, description="봇 이름")
    description: Optional[str] = Field(None, description="봇 설명")
    workflow: Dict[str, Any] = Field(..., description="Workflow 정의")
    session_id: Optional[str] = Field(
        default=None,
        description="Setup 단계에서 사용한 임시 봇/세션 ID (session_... 형식)"
    )
    category: Optional[BotCategory] = Field(default=BotCategory.WORKFLOW, description="봇 카테고리")
    tags: List[str] = Field(default_factory=list, max_items=10, description="봇 태그 배열")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "고객 문의 응답 봇",
                "description": "RAG 기반 자동 응답 시스템",
                "session_id": "session_1730718000_ab12cd3",
                "workflow": {
                    "schemaVersion": "1.0.0",
                    "workflowRevision": 0,
                    "projectId": "project-uuid",
                    "nodes": [],
                    "edges": []
                }
            }
        }
    )


class UpdateBotRequestV2(BaseModel):
    """Bot 수정 요청 (명세서 준수)"""
    name: Optional[str] = Field(None, min_length=1, max_length=100, description="봇 이름")
    description: Optional[str] = Field(None, description="봇 설명")
    workflow: Optional[Dict[str, Any]] = Field(None, description="Workflow 정의")
    category: Optional[BotCategory] = Field(None, description="봇 카테고리")
    tags: Optional[List[str]] = Field(None, max_items=10, description="봇 태그 배열")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "고객 문의 응답 봇 v2",
                "description": "업데이트된 설명",
                "workflow": {
                    "schemaVersion": "1.0.0",
                    "workflowRevision": 1,
                    "nodes": [],
                    "edges": []
                }
            }
        }
    )


class StatusToggleRequest(BaseModel):
    """Bot 상태 토글 요청"""
    isActive: bool = Field(..., description="활성화 상태")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "isActive": True
            }
        }
    )


class StatusToggleResponse(BaseModel):
    """Bot 상태 토글 응답"""
    data: Dict[str, Any] = Field(..., description="상태 변경 결과")

    @classmethod
    def from_bot(cls, bot) -> "StatusToggleResponse":
        """Bot 모델에서 상태 토글 응답 생성"""
        return cls(
            data={
                "id": bot.bot_id,
                "isActive": bot.status.value == "active",
                "updatedAt": bot.updated_at.isoformat() + "Z" if bot.updated_at else None
            }
        )
