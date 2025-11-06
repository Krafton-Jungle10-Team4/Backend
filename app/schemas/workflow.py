"""
Workflow 관련 스키마
"""
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List, Dict, Any, Literal


class NodePosition(BaseModel):
    """노드 위치"""
    x: float = Field(..., description="X 좌표")
    y: float = Field(..., description="Y 좌표")


class StartNodeData(BaseModel):
    """Start 노드 데이터"""
    title: str = Field(..., description="노드 제목")
    desc: str = Field(..., description="노드 설명")
    type: Literal["start"] = Field("start", description="노드 타입")


class KnowledgeRetrievalNodeData(BaseModel):
    """Knowledge Retrieval 노드 데이터"""
    title: str = Field(..., description="노드 제목")
    desc: str = Field(..., description="노드 설명")
    type: Literal["knowledge-retrieval"] = Field("knowledge-retrieval", description="노드 타입")
    dataset: Optional[str] = Field(None, description="데이터셋 ID")
    top_k: int = Field(5, description="검색할 문서 개수", ge=1, le=20)


class LLMNodeData(BaseModel):
    """LLM 노드 데이터"""
    title: str = Field(..., description="노드 제목")
    desc: str = Field(..., description="노드 설명")
    type: Literal["llm"] = Field("llm", description="노드 타입")
    model: Dict[str, str] = Field(..., description="모델 정보 (provider, name)")
    prompt: str = Field(..., description="프롬프트 템플릿")
    temperature: float = Field(0.7, description="Temperature", ge=0.0, le=2.0)
    max_tokens: int = Field(2000, description="최대 토큰 수", ge=100, le=4000)


class EndNodeData(BaseModel):
    """End 노드 데이터"""
    title: str = Field(..., description="노드 제목")
    desc: str = Field(..., description="노드 설명")
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
                        "id": "1",
                        "type": "start",
                        "position": {"x": 100, "y": 150},
                        "data": {
                            "title": "Start",
                            "desc": "시작 노드",
                            "type": "start"
                        }
                    },
                    {
                        "id": "2",
                        "type": "knowledge-retrieval",
                        "position": {"x": 400, "y": 150},
                        "data": {
                            "title": "Knowledge Retrieval",
                            "desc": "지식 검색",
                            "type": "knowledge-retrieval",
                            "dataset": "product-docs",
                            "top_k": 5
                        }
                    }
                ],
                "edges": [
                    {
                        "id": "e1-2",
                        "source": "1",
                        "target": "2",
                        "type": "custom",
                        "data": {
                            "source_type": "start",
                            "target_type": "knowledge-retrieval"
                        }
                    }
                ]
            }
        }
    )
