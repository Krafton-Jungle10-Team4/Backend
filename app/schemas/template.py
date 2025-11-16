"""템플릿 관련 스키마"""
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional, Dict, Any
from datetime import datetime


class TemplateBase(BaseModel):
    """템플릿 기본 스키마"""
    name: str = Field(..., description="템플릿 이름")
    description: str = Field(..., description="템플릿 설명")
    category: str = Field(..., description="카테고리 (agent, workflow, chatbot 등)")
    icon: Optional[str] = Field(None, description="아이콘 URL")
    type: str = Field(..., description="타입 (workflow, chatbot, agent)")
    author: str = Field(..., description="제작자")
    tags: List[str] = Field(default_factory=list, description="태그 목록")


class TemplateCreate(TemplateBase):
    """템플릿 생성 요청"""
    workflow_config: Dict[str, Any] = Field(..., description="워크플로우 설정 (JSON)")


class Template(TemplateBase):
    """템플릿 응답"""
    id: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
