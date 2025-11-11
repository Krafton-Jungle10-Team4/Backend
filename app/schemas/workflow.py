"""
Workflow 관련 스키마
"""
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List, Dict, Any, Literal
from enum import Enum


class NodePosition(BaseModel):
    """노드 위치"""
    x: float = Field(..., description="X 좌표")
    y: float = Field(..., description="Y 좌표")


# 기존 호환성을 위한 노드 데이터 클래스들
class StartNodeData(BaseModel):
    """Start 노드 데이터"""
    title: str = Field(default="Start", description="노드 제목")
    desc: str = Field(default="시작 노드", description="노드 설명")
    type: Literal["start"] = Field("start", description="노드 타입")


class KnowledgeRetrievalNodeData(BaseModel):
    """Knowledge Retrieval 노드 데이터"""
    title: str = Field(default="Knowledge Retrieval", description="노드 제목")
    desc: str = Field(default="지식 검색", description="노드 설명")
    type: Literal["knowledge-retrieval"] = Field("knowledge-retrieval", description="노드 타입")
    dataset_id: Optional[str] = Field(None, alias="dataset", description="데이터셋 ID")
    dataset_name: Optional[str] = Field(None, description="데이터셋 이름")
    mode: str = Field("semantic", description="검색 모드 (semantic, keyword)")
    top_k: int = Field(5, description="검색할 문서 개수", ge=1, le=20)


class LLMNodeData(BaseModel):
    """LLM 노드 데이터"""
    title: str = Field(default="LLM", description="노드 제목")
    desc: str = Field(default="언어 모델", description="노드 설명")
    type: Literal["llm"] = Field("llm", description="노드 타입")
    provider: str = Field(default="openai", description="LLM Provider (slug)")
    model: str = Field(..., description="모델 이름")  # 단순화: Dict -> str
    prompt_template: str = Field(
        default="Context: {context}\nQuestion: {question}\nAnswer:",
        alias="prompt",
        description="프롬프트 템플릿"
    )
    temperature: float = Field(0.7, description="Temperature", ge=0.0, le=1.0)
    max_tokens: int = Field(4000, description="최대 토큰 수", ge=1, le=8192)
    use_context_from: Optional[List[str]] = Field(None, description="컨텍스트로 사용할 노드 ID 리스트")


class EndNodeData(BaseModel):
    """End 노드 데이터"""
    title: str = Field(default="End", description="노드 제목")
    desc: str = Field(default="종료 노드", description="노드 설명")
    type: Literal["end"] = Field("end", description="노드 타입")


class WorkflowNode(BaseModel):
    """Workflow 노드"""
    id: str = Field(..., description="노드 ID")
    type: str = Field(..., description="노드 타입")
    position: NodePosition = Field(..., description="노드 위치")
    data: Dict[str, Any] = Field(..., description="노드 데이터")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": "1",
                "type": "start",
                "position": {"x": 100, "y": 150},
                "data": {
                    "title": "Start",
                    "desc": "시작 노드",
                    "type": "start"
                }
            }
        }
    )


class EdgeData(BaseModel):
    """엣지 데이터"""
    source_type: str = Field(..., description="소스 노드 타입")
    target_type: str = Field(..., description="타겟 노드 타입")


class WorkflowEdge(BaseModel):
    """Workflow 엣지"""
    id: str = Field(..., description="엣지 ID")
    source: str = Field(..., description="소스 노드 ID")
    target: str = Field(..., description="타겟 노드 ID")
    type: str = Field("custom", description="엣지 타입")
    data: EdgeData = Field(..., description="엣지 데이터")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": "e1-2",
                "source": "1",
                "target": "2",
                "type": "custom",
                "data": {
                    "source_type": "start",
                    "target_type": "knowledge-retrieval"
                }
            }
        }
    )


class Workflow(BaseModel):
    """Workflow 정의"""
    nodes: List[WorkflowNode] = Field(..., description="노드 목록")
    edges: List[WorkflowEdge] = Field(..., description="엣지 목록")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "nodes": [
                    {
                        "id": "start-1",
                        "type": "start",
                        "position": {"x": 100, "y": 150},
                        "data": {}
                    },
                    {
                        "id": "knowledge-1",
                        "type": "knowledge-retrieval",
                        "position": {"x": 300, "y": 100},
                        "data": {
                            "dataset_id": "uuid-123",
                            "dataset_name": "product_docs.pdf",
                            "mode": "semantic",
                            "top_k": 5
                        }
                    },
                    {
                        "id": "llm-1",
                        "type": "llm",
                        "position": {"x": 500, "y": 150},
                        "data": {
                            "model": "gpt-4",
                            "prompt_template": "Context: {context}\nQuestion: {question}",
                            "temperature": 0.7,
                            "max_tokens": 4000
                        }
                    },
                    {
                        "id": "end-1",
                        "type": "end",
                        "position": {"x": 700, "y": 150},
                        "data": {}
                    }
                ],
                "edges": [
                    {
                        "id": "e1",
                        "source": "start-1",
                        "target": "knowledge-1",
                        "type": "custom",
                        "data": {
                            "source_type": "start",
                            "target_type": "knowledge-retrieval"
                        }
                    },
                    {
                        "id": "e2",
                        "source": "knowledge-1",
                        "target": "llm-1",
                        "type": "custom",
                        "data": {
                            "source_type": "knowledge-retrieval",
                            "target_type": "llm"
                        }
                    },
                    {
                        "id": "e3",
                        "source": "llm-1",
                        "target": "end-1",
                        "type": "custom",
                        "data": {
                            "source_type": "llm",
                            "target_type": "end"
                        }
                    }
                ]
            }
        }
    )


# 워크플로우 검증 요청/응답 모델
class WorkflowValidationRequest(BaseModel):
    """워크플로우 검증 요청"""
    nodes: List[WorkflowNode] = Field(..., description="노드 목록")
    edges: List[WorkflowEdge] = Field(..., description="엣지 목록")


class WorkflowValidationResponse(BaseModel):
    """워크플로우 검증 응답"""
    is_valid: bool = Field(..., description="유효 여부")
    errors: List[str] = Field(default_factory=list, description="오류 목록")
    warnings: List[str] = Field(default_factory=list, description="경고 목록")
    execution_order: Optional[List[str]] = Field(None, description="실행 순서")


# 노드 타입 정보 응답 모델
class NodeTypeInfo(BaseModel):
    """노드 타입 정보"""
    type: str = Field(..., description="노드 타입")
    label: str = Field(..., description="노드 라벨")
    icon: str = Field(..., description="노드 아이콘")
    max_instances: int = Field(..., description="최대 인스턴스 수 (-1은 무제한)")
    configurable: bool = Field(..., description="설정 가능 여부")
    config_schema: Optional[Dict[str, Any]] = Field(None, description="설정 스키마")


class NodeTypesResponse(BaseModel):
    """노드 타입 목록 응답"""
    node_types: List[NodeTypeInfo] = Field(..., description="노드 타입 목록")


# 모델 목록 응답
class ModelInfo(BaseModel):
    """LLM 모델 정보"""
    id: str = Field(..., description="모델 ID")
    name: str = Field(..., description="모델 이름")
    provider: str = Field(..., description="제공자 식별자(slug)")
    description: Optional[str] = Field(None, description="모델 설명")


class ModelsResponse(BaseModel):
    """모델 목록 응답"""
    models: List[ModelInfo] = Field(..., description="모델 목록")
