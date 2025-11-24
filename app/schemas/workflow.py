"""
Workflow 관련 스키마
"""
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List, Dict, Any, Literal
from enum import Enum
from datetime import datetime


class NodePosition(BaseModel):
    """노드 위치"""
    x: float = Field(..., description="X 좌표")
    y: float = Field(..., description="Y 좌표")


# ============ V2 스키마: 포트 시스템 ============

class PortType(str, Enum):
    """포트 데이터 타입"""
    STRING = "string"
    NUMBER = "number"
    BOOLEAN = "boolean"
    ARRAY = "array"
    ARRAY_FILE = "array_file"
    OBJECT = "object"
    FILE = "file"
    ANY = "any"


class WriteMode(str, Enum):
    """작업 타입 열거형"""
    # 기본 작업
    OVERWRITE = "over-write"
    CLEAR = "clear"
    SET = "set"

    # 배열 작업
    APPEND = "append"
    EXTEND = "extend"
    REMOVE_FIRST = "remove-first"
    REMOVE_LAST = "remove-last"

    # 산술 작업 (number 전용)
    INCREMENT = "+="
    DECREMENT = "-="
    MULTIPLY = "*="
    DIVIDE = "/="


class AssignerInputType(str, Enum):
    """입력 타입"""
    VARIABLE = "variable"  # 포트 연결로 받음
    CONSTANT = "constant"  # config에서 상수 값 사용


class PortDefinition(BaseModel):
    """포트 정의"""
    name: str = Field(..., description="포트 이름 (예: query, context, response)")
    type: PortType = Field(..., description="데이터 타입")
    required: bool = Field(True, description="필수 여부")
    default_value: Optional[Any] = Field(None, description="기본값")
    description: str = Field("", description="포트 설명")
    display_name: str = Field("", description="UI 표시명")


class NodePortSchema(BaseModel):
    """노드의 입출력 포트 스키마"""
    inputs: List[PortDefinition] = Field(default_factory=list)
    outputs: List[PortDefinition] = Field(default_factory=list)


class ValueSelector(BaseModel):
    """다른 노드 출력 참조"""
    variable: str = Field(..., description="형식: {node_id}.{port_name}")
    value_type: PortType = Field(PortType.ANY, description="값 타입")


class VariableMapping(BaseModel):
    """노드 입력 포트와 데이터 소스 매핑"""
    target_port: str = Field(..., description="대상 입력 포트")
    source: ValueSelector = Field(..., description="소스 변수 참조")


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


class AnswerNodeData(BaseModel):
    """Answer 노드의 데이터 스키마"""
    type: Literal["answer"] = Field("answer", description="노드 타입")
    template: str = Field(..., min_length=1, description="응답 템플릿 (필수)")
    description: Optional[str] = Field(None, description="노드 설명")
    output_format: Literal["text", "json"] = Field("text", description="출력 형식")

    @classmethod
    def __get_validators__(cls):
        yield cls.validate_model

    @classmethod
    def validate_model(cls, values):
        """템플릿 유효성 검사"""
        if isinstance(values, dict):
            template = values.get("template", "")
        else:
            template = getattr(values, "template", "")

        if not template or template.strip() == "":
            raise ValueError("템플릿은 비어있을 수 없습니다")

        # 길이 제한
        if len(template) > 20 * 1024:
            raise ValueError("템플릿 길이가 20KB를 초과할 수 없습니다")

        return values


class WorkflowNode(BaseModel):
    """Workflow 노드"""
    id: str = Field(..., description="노드 ID")
    type: str = Field(..., description="노드 타입")
    position: NodePosition = Field(..., description="노드 위치")
    data: Dict[str, Any] = Field(..., description="노드 데이터")

    # V2 필드 (하위 호환성 위해 Optional)
    ports: Optional[NodePortSchema] = Field(None, description="입출력 포트 스키마 (V2)")
    variable_mappings: Dict[str, Any] = Field(default_factory=dict, description="변수 매핑 (V2)")

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

    # V2 필드 (하위 호환성 위해 Optional)
    source_port: Optional[str] = Field(None, description="소스 포트 이름 (V2)")
    target_port: Optional[str] = Field(None, description="타겟 포트 이름 (V2)")
    data_type: Optional[PortType] = Field(None, description="데이터 타입 (V2)")

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
    category: Optional[str] = Field(None, description="노드 카테고리 (예: Tools, LLM)")
    description: Optional[str] = Field(None, description="노드 설명")
    input_ports: Optional[List[PortDefinition]] = Field(None, description="입력 포트 목록")
    output_ports: Optional[List[PortDefinition]] = Field(None, description="출력 포트 목록")
    default_data: Optional[Dict[str, Any]] = Field(None, description="노드 생성 시 기본값")


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


# ============ V2 스키마: 워크플로우 버전 관리 ============

class WorkflowVersionStatus(str, Enum):
    """워크플로우 버전 상태"""
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class WorkflowGraph(BaseModel):
    """워크플로우 그래프 (V2)"""
    nodes: List[WorkflowNode] = Field(..., description="노드 목록")
    edges: List[WorkflowEdge] = Field(..., description="엣지 목록")


class WorkflowVersionCreate(BaseModel):
    """워크플로우 버전 생성 요청"""
    graph: WorkflowGraph = Field(..., description="워크플로우 그래프")
    environment_variables: Dict[str, Any] = Field(default_factory=dict, description="환경 변수")
    conversation_variables: Dict[str, Any] = Field(default_factory=dict, description="대화 변수")


class WorkflowVersionResponse(BaseModel):
    """워크플로우 버전 응답"""
    id: str = Field(..., description="버전 ID")
    bot_id: str = Field(..., description="봇 ID")
    version: str = Field(..., description="버전 번호")
    status: WorkflowVersionStatus = Field(..., description="상태")
    created_at: datetime = Field(..., description="생성 시간")
    updated_at: datetime = Field(..., description="수정 시간")
    published_at: Optional[datetime] = Field(None, description="발행 시간")


class WorkflowVersionDetail(WorkflowVersionResponse):
    """워크플로우 버전 상세"""
    graph: WorkflowGraph = Field(..., description="워크플로우 그래프")
    environment_variables: Dict[str, Any] = Field(default_factory=dict, description="환경 변수")
    conversation_variables: Dict[str, Any] = Field(default_factory=dict, description="대화 변수")


# ============ V2 스키마: 실행 기록 관리 ============

class WorkflowRunResponse(BaseModel):
    """워크플로우 실행 기록 응답"""
    id: str = Field(..., description="실행 ID")
    bot_id: str = Field(..., description="봇 ID")
    workflow_version_id: Optional[str] = Field(None, description="워크플로우 버전 ID")
    session_id: Optional[str] = Field(None, description="세션 ID")
    status: str = Field(..., description="실행 상태")
    error_message: Optional[str] = Field(None, description="에러 메시지")
    started_at: datetime = Field(..., description="시작 시간")
    finished_at: Optional[datetime] = Field(None, description="종료 시간")
    elapsed_time: Optional[int] = Field(None, description="실행 시간 (milliseconds)")
    total_tokens: int = Field(0, description="총 사용 토큰 수")
    total_cost: Optional[float] = Field(None, description="총 비용 (USD)")
    total_steps: int = Field(0, description="총 실행 단계 수")
    inputs: Optional[Dict[str, Any]] = Field(None, description="입력 데이터")
    created_at: datetime = Field(..., description="생성 시간")


class WorkflowRunDetail(WorkflowRunResponse):
    """워크플로우 실행 기록 상세"""
    graph_snapshot: Dict[str, Any] = Field(..., description="실행 시점 그래프 스냅샷")
    inputs: Optional[Dict[str, Any]] = Field(None, description="입력 데이터")
    outputs: Optional[Dict[str, Any]] = Field(None, description="출력 데이터")


class NodeExecutionResponse(BaseModel):
    """노드 실행 기록 응답"""
    id: str = Field(..., description="노드 실행 ID")
    workflow_run_id: str = Field(..., description="워크플로우 실행 ID")
    node_id: str = Field(..., description="노드 ID")
    node_type: str = Field(..., description="노드 타입")
    execution_order: Optional[int] = Field(None, description="실행 순서")
    status: str = Field(..., description="실행 상태")
    error_message: Optional[str] = Field(None, description="에러 메시지")
    started_at: datetime = Field(..., description="시작 시간")
    finished_at: Optional[datetime] = Field(None, description="종료 시간")
    elapsed_time: Optional[int] = Field(None, description="실행 시간 (milliseconds)")
    tokens_used: int = Field(0, description="사용 토큰 수")
    cost: Optional[float] = Field(None, description="비용 (USD)")
    model: Optional[str] = Field(None, description="사용된 모델명")
    is_truncated: bool = Field(False, description="데이터 잘림 여부")
    created_at: datetime = Field(..., description="생성 시간")


class NodeExecutionDetail(NodeExecutionResponse):
    """노드 실행 기록 상세"""
    inputs: Optional[Dict[str, Any]] = Field(None, description="입력 데이터")
    outputs: Optional[Dict[str, Any]] = Field(None, description="출력 데이터")
    process_data: Optional[Dict[str, Any]] = Field(None, description="처리 데이터")
    truncated_fields: Optional[Dict[str, Any]] = Field(None, description="잘린 필드 정보")


class PaginatedWorkflowRuns(BaseModel):
    """페이지네이션된 워크플로우 실행 목록"""
    items: List[WorkflowRunResponse] = Field(..., description="실행 목록")
    total: int = Field(..., description="전체 개수")
    limit: int = Field(..., description="페이지 크기")
    offset: int = Field(..., description="오프셋")


class WorkflowExecutionStatistics(BaseModel):
    """워크플로우 실행 통계"""
    total_runs: int = Field(..., description="총 실행 횟수")
    succeeded_runs: int = Field(..., description="성공 횟수")
    failed_runs: int = Field(..., description="실패 횟수")
    avg_elapsed_time: float = Field(..., description="평균 실행 시간 (milliseconds)")
    total_tokens: int = Field(..., description="총 토큰 사용량")


# ============ 라이브러리 관련 스키마 (신규) ============

class LibraryMetadata(BaseModel):
    """라이브러리 메타데이터"""
    library_name: Optional[str] = Field(None, max_length=255, description="라이브러리에 표시될 이름 (미제공 시 봇 이름 사용)")
    library_description: Optional[str] = Field(None, max_length=1000, description="설명")
    library_category: Optional[str] = Field(None, max_length=100, description="카테고리")
    library_tags: Optional[List[str]] = Field(default_factory=list, description="태그 목록")


class PublishWorkflowRequest(BaseModel):
    """워크플로우 발행 요청 (라이브러리 메타데이터 포함)"""
    library_metadata: Optional[LibraryMetadata] = Field(None, description="라이브러리 메타데이터 (선택)")


class WorkflowVersionResponseWithLibrary(WorkflowVersionResponse):
    """워크플로우 버전 응답 (라이브러리 필드 포함)"""
    library_name: Optional[str] = Field(None, description="라이브러리 이름")
    library_description: Optional[str] = Field(None, description="라이브러리 설명")
    library_category: Optional[str] = Field(None, description="라이브러리 카테고리")
    library_tags: Optional[List[str]] = Field(None, description="라이브러리 태그")
    library_visibility: Optional[str] = Field(None, description="라이브러리 공개 범위")
    is_in_library: bool = Field(False, description="라이브러리 포함 여부")
    library_published_at: Optional[datetime] = Field(None, description="라이브러리 게시 시간")

    # 통계 및 스키마 정보
    input_schema: Optional[List[PortDefinition]] = Field(None, description="입력 스키마")
    output_schema: Optional[List[PortDefinition]] = Field(None, description="출력 스키마")
    node_count: Optional[int] = Field(None, description="노드 개수")
    edge_count: Optional[int] = Field(None, description="엣지 개수")
    port_definitions: Optional[Dict[str, Any]] = Field(None, description="포트 정의")


class LibraryAgentResponse(BaseModel):
    """라이브러리 에이전트 응답 (간소화된 정보)"""
    id: str = Field(..., description="버전 ID (UUID)")
    bot_id: str = Field(..., description="봇 ID")
    version: str = Field(..., description="버전 번호")
    library_name: str = Field(..., description="라이브러리 이름")
    library_description: Optional[str] = Field(None, description="라이브러리 설명")
    library_category: Optional[str] = Field(None, description="라이브러리 카테고리")
    library_tags: Optional[List[str]] = Field(None, description="라이브러리 태그")
    library_visibility: str = Field(..., description="라이브러리 공개 범위")
    library_published_at: datetime = Field(..., description="라이브러리 게시 시간")

    # 통계 정보
    node_count: Optional[int] = Field(None, description="노드 개수")
    edge_count: Optional[int] = Field(None, description="엣지 개수")

    # 배포 관련 필드 추가
    deployment_status: Optional[str] = Field(None, description="배포 상태 (None | 'draft' | 'published' | 'suspended')")
    widget_key: Optional[str] = Field(None, description="Widget Key")
    deployed_at: Optional[datetime] = Field(None, description="배포 시간")

    model_config = ConfigDict(from_attributes=True)


class LibraryAgentDetailResponse(BaseModel):
    """라이브러리 에이전트 상세 응답 (graph 포함)"""
    id: str = Field(..., description="버전 ID (UUID)")
    bot_id: str = Field(..., description="봇 ID")
    version: str = Field(..., description="버전 번호")
    graph: Dict[str, Any] = Field(..., description="워크플로우 그래프")
    environment_variables: Optional[Dict[str, Any]] = Field(None, description="환경 변수")
    conversation_variables: Optional[Dict[str, Any]] = Field(None, description="대화 변수")
    library_name: str = Field(..., description="라이브러리 이름")
    library_description: Optional[str] = Field(None, description="라이브러리 설명")
    library_category: Optional[str] = Field(None, description="라이브러리 카테고리")
    library_tags: Optional[List[str]] = Field(None, description="라이브러리 태그")
    library_visibility: str = Field(..., description="라이브러리 공개 범위")
    library_published_at: datetime = Field(..., description="라이브러리 게시 시간")
    created_at: datetime = Field(..., description="생성 시간")

    # 통계 및 스키마 정보
    input_schema: Optional[List[PortDefinition]] = Field(None, description="입력 스키마")
    output_schema: Optional[List[PortDefinition]] = Field(None, description="출력 스키마")
    node_count: Optional[int] = Field(None, description="노드 개수")
    edge_count: Optional[int] = Field(None, description="엣지 개수")
    port_definitions: Optional[Dict[str, Any]] = Field(None, description="포트 정의")

    # 배포 관련 필드 추가
    deployment_status: Optional[str] = Field(None, description="배포 상태 (None | 'draft' | 'published' | 'suspended')")
    widget_key: Optional[str] = Field(None, description="Widget Key")
    deployed_at: Optional[datetime] = Field(None, description="배포 시간")

    model_config = ConfigDict(from_attributes=True)


class LibraryFilterParams(BaseModel):
    """라이브러리 필터 파라미터"""
    category: Optional[str] = Field(None, description="카테고리 필터")
    visibility: Optional[str] = Field(None, description="공개 범위 필터")
    search: Optional[str] = Field(None, description="검색어 (이름, 설명)")
    tags: Optional[List[str]] = Field(None, description="태그 필터")
    page: int = Field(1, ge=1, description="페이지 번호")
    page_size: int = Field(20, ge=1, le=100, description="페이지 크기")


class LibraryAgentsResponse(BaseModel):
    """라이브러리 에이전트 목록 응답"""
    agents: List[LibraryAgentResponse] = Field(..., description="에이전트 목록")
    total: int = Field(..., description="전체 개수")
    page: int = Field(..., description="현재 페이지")
    page_size: int = Field(..., description="페이지 크기")
    total_pages: int = Field(..., description="전체 페이지 수")


class LibraryImportRequest(BaseModel):
    """라이브러리 에이전트 가져오기 요청"""
    source_version_id: str = Field(..., description="가져올 라이브러리 버전 ID (UUID)")


# ============ Assigner Node V2 스키마 ============

class AssignerOperation(BaseModel):
    """단일 작업 정의"""
    write_mode: WriteMode = Field(..., description="수행할 작업 타입")
    input_type: AssignerInputType = Field(
        default=AssignerInputType.VARIABLE,
        description="입력 방식 (variable: 포트 연결, constant: 상수)"
    )
    constant_value: Optional[Any] = Field(
        default=None,
        description="input_type이 constant일 때 사용할 값"
    )

    model_config = ConfigDict(use_enum_values=True)


class AssignerNodeConfig(BaseModel):
    """Assigner 노드 설정"""
    version: Literal["2"] = "2"
    operations: List[AssignerOperation] = Field(
        default_factory=list,
        description="작업 목록"
    )

    model_config = ConfigDict(use_enum_values=True)


class AssignerNodeInput(BaseModel):
    """실행 시 입력 (동적 필드)"""
    # operation_0_target, operation_0_value, operation_1_target, ...

    model_config = ConfigDict(extra="allow")  # 동적 필드 허용


class AssignerNodeOutput(BaseModel):
    """실행 결과 (동적 필드)"""
    # operation_0_result, operation_1_result, ...

    model_config = ConfigDict(extra="allow")


# ============ Export ============

__all__ = [
    # Enums
    "PortType",
    "WriteMode",
    "AssignerInputType",
    "WorkflowVersionStatus",

    # Port 시스템
    "PortDefinition",
    "NodePortSchema",
    "ValueSelector",
    "VariableMapping",

    # 노드 데이터
    "NodePosition",
    "StartNodeData",
    "KnowledgeRetrievalNodeData",
    "LLMNodeData",
    "EndNodeData",
    "AnswerNodeData",

    # 워크플로우 구조
    "WorkflowNode",
    "EdgeData",
    "WorkflowEdge",
    "Workflow",

    # 검증
    "WorkflowValidationRequest",
    "WorkflowValidationResponse",

    # 노드 타입 정보
    "NodeTypeInfo",
    "NodeTypesResponse",

    # 모델 정보
    "ModelInfo",
    "ModelsResponse",

    # V2 버전 관리
    "WorkflowGraph",
    "WorkflowVersionCreate",
    "WorkflowVersionResponse",
    "WorkflowVersionDetail",

    # V2 실행 기록
    "WorkflowRunResponse",
    "WorkflowRunDetail",
    "NodeExecutionResponse",
    "NodeExecutionDetail",
    "PaginatedWorkflowRuns",
    "WorkflowExecutionStatistics",

    # 라이브러리 관련 (신규)
    "LibraryMetadata",
    "PublishWorkflowRequest",
    "WorkflowVersionResponseWithLibrary",
    "LibraryAgentResponse",
    "LibraryAgentDetailResponse",
    "LibraryFilterParams",
    "LibraryAgentsResponse",
    "LibraryImportRequest",

    # Assigner Node V2
    "AssignerOperation",
    "AssignerNodeConfig",
    "AssignerNodeInput",
    "AssignerNodeOutput",
]
