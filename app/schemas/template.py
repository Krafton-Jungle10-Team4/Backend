"""확장된 템플릿 스키마"""
from pydantic import BaseModel, Field, ConfigDict, field_validator
from typing import List, Optional, Dict, Any
from datetime import datetime
from uuid import UUID


class Author(BaseModel):
    """작성자 정보"""
    id: str
    name: str
    email: Optional[str] = None


class TemplateMetadata(BaseModel):
    """템플릿 메타데이터"""
    tags: List[str] = Field(default_factory=list)
    category: Optional[str] = None
    visibility: str = Field(default="private", pattern="^(private|team|public)$")
    source_workflow_id: Optional[str] = None
    source_version_id: Optional[str] = None
    node_count: int = 0
    edge_count: int = 0
    estimated_tokens: Optional[int] = None
    estimated_cost: Optional[float] = None


class PortDefinition(BaseModel):
    """포트 정의"""
    name: str = Field(..., min_length=1, max_length=100)
    type: str = Field(..., pattern="^(string|number|boolean|array|object|any)$")
    required: bool = True
    description: Optional[str] = None
    display_name: Optional[str] = None
    default_value: Optional[Any] = None

    @field_validator('name')
    @classmethod
    def validate_port_name(cls, v: str) -> str:
        """포트 이름 검증"""
        if not v.replace('_', '').isalnum():
            raise ValueError("포트 이름은 영문자, 숫자, 언더스코어만 허용됩니다")
        return v


class TemplateGraph(BaseModel):
    """템플릿 그래프 구조"""
    nodes: List[Dict[str, Any]]
    edges: List[Dict[str, Any]]

    @field_validator('nodes')
    @classmethod
    def validate_nodes(cls, v: List[Dict]) -> List[Dict]:
        """노드 검증"""
        if not v:
            raise ValueError("최소 1개 이상의 노드가 필요합니다")

        # Start/End 노드 확인
        has_start = any(node.get('data', {}).get('type') == 'start' for node in v)
        has_end = any(node.get('data', {}).get('type') in ['end', 'answer'] for node in v)

        if not has_start:
            raise ValueError("Start 노드가 필요합니다")
        if not has_end:
            raise ValueError("End 또는 Answer 노드가 필요합니다")

        return v


class WorkflowTemplate(BaseModel):
    """템플릿 응답 (완전한 구조)"""
    id: str
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    version: str = Field(default="1.0.0", pattern=r"^\d+\.\d+\.\d+$")
    created_at: datetime
    updated_at: Optional[datetime] = None
    author: Author
    metadata: TemplateMetadata
    graph: TemplateGraph
    input_schema: List[PortDefinition]
    output_schema: List[PortDefinition]
    thumbnail_url: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class ExportConfig(BaseModel):
    """Export 요청 스키마"""
    workflow_id: str = Field(..., description="워크플로우 ID (bot_id)")
    version_id: str = Field(..., description="워크플로우 버전 ID")
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=1000)
    category: Optional[str] = Field(None, max_length=50)
    tags: List[str] = Field(default_factory=list)
    visibility: str = Field(default="private", pattern="^(private|team|public)$")
    custom_input_schema: Optional[List[PortDefinition]] = None
    custom_output_schema: Optional[List[PortDefinition]] = None
    thumbnail_url: Optional[str] = None
    estimated_tokens: Optional[int] = Field(None, ge=0)
    estimated_cost: Optional[float] = None


class ExportValidation(BaseModel):
    """Export 검증 결과"""
    is_valid: bool
    has_published_version: bool
    has_start_node: bool
    has_end_node: bool
    detected_input_ports: List[PortDefinition]
    detected_output_ports: List[PortDefinition]
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    node_count: int = 0
    edge_count: int = 0


class ImportValidation(BaseModel):
    """Import 검증 결과"""
    is_valid: bool
    is_compatible: bool
    missing_node_types: List[str] = Field(default_factory=list)
    version_mismatch: bool = False
    can_upgrade: bool = False
    warnings: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)


class TemplateUsageCreate(BaseModel):
    """템플릿 사용 기록 생성"""
    workflow_id: str
    workflow_version_id: Optional[str] = None
    node_id: str
    event_type: str = Field(default="imported", pattern="^(imported|executed)$")
    note: Optional[str] = None


class TemplateUsageResponse(BaseModel):
    """템플릿 사용 기록 응답"""
    id: str
    template_id: str
    workflow_id: str
    workflow_version_id: Optional[str] = None
    node_id: str
    user_id: str
    event_type: str = Field(pattern="^(imported|executed)$")
    note: Optional[str] = None
    occurred_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TemplateSummary(BaseModel):
    """목록 응답용 템플릿 요약"""
    id: str
    name: str
    description: Optional[str] = None
    version: str
    created_at: datetime
    updated_at: Optional[datetime] = None
    author: Author
    metadata: TemplateMetadata
    input_schema: List[PortDefinition]
    output_schema: List[PortDefinition]
    thumbnail_url: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class TemplateListResponse(BaseModel):
    """템플릿 목록 응답"""
    templates: List[TemplateSummary]
    pagination: Dict[str, int]  # {"total": 45, "skip": 0, "limit": 20}
