from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime
from app.schemas.document import DocumentInfo


class KnowledgeBase(BaseModel):
    name: str = Field(..., description="지식 이름")
    description: Optional[str] = Field(None, description="지식 설명")
    tags: List[str] = Field(default_factory=list, description="태그 목록")


class KnowledgeCreate(KnowledgeBase):
    pass


class KnowledgeUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[List[str]] = None


class Knowledge(KnowledgeBase):
    id: str
    user_id: str
    document_count: int = Field(0, description="포함된 문서 개수")
    documents: Optional[List[DocumentInfo]] = Field(None, description="문서 목록 (선택사항)")
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
