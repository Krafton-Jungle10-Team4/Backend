# 워크플로우 V2 리팩토링 계획서

## 개요

현재 워크플로우 시스템을 Dify 아키텍처 원칙을 적용하여 점진적으로 개선합니다.
**핵심 목표**: 기존 시스템을 유지하면서 포트 기반 데이터 흐름, 변수 시스템, 큐 기반 실행 엔진을 단계적으로 도입

**예상 기간**: 9-12주 | **전략**: 점진적 리팩토링 + 하위 호환성 유지

---

## 현재 시스템 분석

### 기존 아키텍처의 문제점

```
현재 구조:
User Message → WorkflowExecutor → [Start → Knowledge → LLM → End] → Response

데이터 흐름:
- 모든 노드가 WorkflowExecutionContext (Dict) 공유
- context["node_outputs"]를 통한 암묵적 데이터 전달
- 서비스와 데이터가 컨텍스트에 혼재
- 단순 위상정렬 기반 실행
```

### 주요 제약사항

1. **타입 안전성 부재**: 노드가 임의의 키로 공유 dict 접근
2. **강한 결합**: 노드가 context에서 서비스 직접 추출
3. **제한된 실행 로직**: 조건 분기, 루프, 병렬 처리 불가
4. **버전 관리 부재**: 봇당 단일 워크플로우, draft/published 구분 없음
5. **추적 기능 미흡**: 실행 이력 및 디버깅 지원 부족

---

## 리팩토링 1단계: 스키마 강화 (1-2주)

### 목표
기존 `app/schemas/workflow.py`에 포트 시스템과 변수 선택자 개념 추가

### 1.1 현재 스키마 분석

**파일**: `Backend/app/schemas/workflow.py`

```python
# 현재 구조
class WorkflowNode(BaseModel):
    id: str
    type: str  # "start", "knowledge", "llm", "end"
    position: NodePosition
    data: Dict[str, Any]  # 노드별 설정

class WorkflowEdge(BaseModel):
    id: str
    source: str  # node_id
    target: str  # node_id

class Workflow(BaseModel):
    nodes: List[WorkflowNode]
    edges: List[WorkflowEdge]
```

**문제점**:
- 포트 개념 없음 (어떤 출력이 어떤 입력으로 가는지 불명확)
- 데이터 타입 정보 없음
- 엣지가 단순 연결만 표현

### 1.2 리팩토링 작업

#### Step 1: 포트 정의 추가

**파일 수정**: `Backend/app/schemas/workflow.py`

```python
from enum import Enum
from typing import List, Optional, Any, Dict
from pydantic import BaseModel, Field

class PortType(str, Enum):
    """포트 데이터 타입"""
    STRING = "string"
    NUMBER = "number"
    BOOLEAN = "boolean"
    ARRAY = "array"
    OBJECT = "object"
    FILE = "file"
    ANY = "any"

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

# 기존 WorkflowNode에 ports 필드 추가 (옵셔널로)
class WorkflowNode(BaseModel):
    id: str
    type: str
    position: NodePosition
    data: Dict[str, Any]

    # 신규 추가 (하위 호환성 위해 Optional)
    ports: Optional[NodePortSchema] = None
    variable_mappings: Dict[str, Any] = Field(default_factory=dict)

# 기존 WorkflowEdge 확장
class WorkflowEdge(BaseModel):
    id: str
    source: str
    target: str

    # 신규 추가 (하위 호환성 위해 Optional)
    source_port: Optional[str] = None
    target_port: Optional[str] = None
    data_type: Optional[PortType] = None
```

**변경 영향**:
- ✅ 기존 워크플로우 JSON은 그대로 작동 (ports 필드가 Optional)
- ✅ 새 워크플로우는 포트 정보 포함 가능
- ✅ 프론트엔드는 점진적으로 포트 기반 UI로 전환 가능

#### Step 2: 변수 선택자 추가

```python
class ValueSelector(BaseModel):
    """다른 노드 출력 참조"""
    variable: str = Field(..., description="형식: {node_id}.{port_name}")
    value_type: PortType

class VariableMapping(BaseModel):
    """노드 입력 포트와 데이터 소스 매핑"""
    target_port: str
    source: ValueSelector
```

#### Step 3: 워크플로우 버전 스키마 추가

```python
from datetime import datetime

class WorkflowVersionStatus(str, Enum):
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"

class WorkflowVersion(BaseModel):
    """워크플로우 버전 (신규)"""
    id: str
    bot_id: str
    version: str  # "draft" 또는 "v1.0", "v1.1" 등
    status: WorkflowVersionStatus

    # 그래프 정의
    nodes: List[WorkflowNode]
    edges: List[WorkflowEdge]

    # 변수
    environment_variables: Dict[str, Any] = Field(default_factory=dict)
    conversation_variables: Dict[str, Any] = Field(default_factory=dict)

    # 메타데이터
    created_by: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    published_at: Optional[datetime] = None
```

### 1.3 데이터베이스 마이그레이션

#### 마이그레이션 파일 생성

**파일**: `Backend/alembic/versions/xxxx_add_workflow_v2.py`

```python
"""Add workflow V2 tables

Revision ID: xxxx
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

def upgrade():
    # 1. Bot 테이블에 V2 필드 추가
    op.add_column('bots', sa.Column('use_workflow_v2', sa.Boolean(), default=False))
    op.add_column('bots', sa.Column('legacy_workflow', JSONB, nullable=True))

    # 2. 워크플로우 버전 테이블 생성
    op.create_table(
        'bot_workflow_versions',
        sa.Column('id', UUID, primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('bot_id', UUID, sa.ForeignKey('bots.bot_id', ondelete='CASCADE'), nullable=False),
        sa.Column('version', sa.String(50), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),

        sa.Column('graph', JSONB, nullable=False),
        sa.Column('environment_variables', JSONB, server_default='{}'),
        sa.Column('conversation_variables', JSONB, server_default='{}'),
        sa.Column('features', JSONB, server_default='{}'),

        sa.Column('created_by', UUID, sa.ForeignKey('users.id')),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime, server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.Column('published_at', sa.DateTime, nullable=True),

        sa.UniqueConstraint('bot_id', 'version', name='uq_bot_workflow_version')
    )

    op.create_index('idx_bot_workflow_versions_bot_id', 'bot_workflow_versions', ['bot_id'])
    op.create_index('idx_bot_workflow_versions_status', 'bot_workflow_versions', ['bot_id', 'status'])

    # 3. 실행 기록 테이블 생성
    op.create_table(
        'workflow_execution_runs',
        sa.Column('id', UUID, primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('bot_id', UUID, sa.ForeignKey('bots.bot_id', ondelete='CASCADE'), nullable=False),
        sa.Column('workflow_version_id', UUID, sa.ForeignKey('bot_workflow_versions.id')),
        sa.Column('session_id', sa.String(255)),
        sa.Column('user_id', UUID, sa.ForeignKey('users.id')),

        sa.Column('graph_snapshot', JSONB, nullable=False),
        sa.Column('inputs', JSONB),
        sa.Column('outputs', JSONB),

        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('error_message', sa.Text),

        sa.Column('started_at', sa.DateTime, server_default=sa.func.now()),
        sa.Column('finished_at', sa.DateTime),
        sa.Column('elapsed_time', sa.Integer),
        sa.Column('total_tokens', sa.Integer, default=0),
        sa.Column('total_steps', sa.Integer, default=0),

        sa.Column('created_at', sa.DateTime, server_default=sa.func.now())
    )

    op.create_index('idx_workflow_runs_bot_id', 'workflow_execution_runs', ['bot_id'])
    op.create_index('idx_workflow_runs_session', 'workflow_execution_runs', ['session_id'])
    op.create_index('idx_workflow_runs_created_at', 'workflow_execution_runs', ['created_at'], postgresql_using='btree')

    # 4. 노드 실행 기록 테이블
    op.create_table(
        'workflow_node_executions',
        sa.Column('id', UUID, primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('workflow_run_id', UUID, sa.ForeignKey('workflow_execution_runs.id', ondelete='CASCADE'), nullable=False),
        sa.Column('node_id', sa.String(255), nullable=False),
        sa.Column('node_type', sa.String(50), nullable=False),
        sa.Column('execution_order', sa.Integer),

        sa.Column('inputs', JSONB),
        sa.Column('outputs', JSONB),
        sa.Column('process_data', JSONB),

        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('error_message', sa.Text),

        sa.Column('started_at', sa.DateTime, server_default=sa.func.now()),
        sa.Column('finished_at', sa.DateTime),
        sa.Column('elapsed_time', sa.Integer),
        sa.Column('tokens_used', sa.Integer, default=0),

        sa.Column('is_truncated', sa.Boolean, default=False),
        sa.Column('truncated_fields', JSONB),

        sa.Column('created_at', sa.DateTime, server_default=sa.func.now())
    )

    op.create_index('idx_node_exec_run_id', 'workflow_node_executions', ['workflow_run_id'])

def downgrade():
    op.drop_table('workflow_node_executions')
    op.drop_table('workflow_execution_runs')
    op.drop_table('bot_workflow_versions')
    op.drop_column('bots', 'legacy_workflow')
    op.drop_column('bots', 'use_workflow_v2')
```

#### 모델 파일 업데이트

**파일**: `Backend/app/models/bot.py`

```python
# 기존 코드에 추가
class Bot(Base):
    # ... 기존 필드들 ...

    # V2 마이그레이션 필드
    use_workflow_v2 = Column(Boolean, default=False, nullable=False)
    legacy_workflow = Column(JSON, nullable=True)  # 백업용

    # 관계 추가
    workflow_versions = relationship(
        "BotWorkflowVersion",
        back_populates="bot",
        cascade="all, delete-orphan"
    )
```

**신규 파일**: `Backend/app/models/workflow_version.py`

```python
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from app.core.database import Base
import uuid

class BotWorkflowVersion(Base):
    __tablename__ = "bot_workflow_versions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    bot_id = Column(UUID(as_uuid=True), ForeignKey('bots.bot_id', ondelete='CASCADE'), nullable=False)
    version = Column(String(50), nullable=False)
    status = Column(String(20), nullable=False)

    graph = Column(JSONB, nullable=False)
    environment_variables = Column(JSONB, default={})
    conversation_variables = Column(JSONB, default={})
    features = Column(JSONB, default={})

    created_by = Column(UUID(as_uuid=True), ForeignKey('users.id'))
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    published_at = Column(DateTime, nullable=True)

    # 관계
    bot = relationship("Bot", back_populates="workflow_versions")
    execution_runs = relationship("WorkflowExecutionRun", back_populates="workflow_version")

class WorkflowExecutionRun(Base):
    __tablename__ = "workflow_execution_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    bot_id = Column(UUID(as_uuid=True), ForeignKey('bots.bot_id', ondelete='CASCADE'), nullable=False)
    workflow_version_id = Column(UUID(as_uuid=True), ForeignKey('bot_workflow_versions.id'))
    session_id = Column(String(255))
    user_id = Column(UUID(as_uuid=True), ForeignKey('users.id'))

    graph_snapshot = Column(JSONB, nullable=False)
    inputs = Column(JSONB)
    outputs = Column(JSONB)

    status = Column(String(20), nullable=False)
    error_message = Column(Text)

    started_at = Column(DateTime, server_default=func.now())
    finished_at = Column(DateTime)
    elapsed_time = Column(Integer)
    total_tokens = Column(Integer, default=0)
    total_steps = Column(Integer, default=0)

    created_at = Column(DateTime, server_default=func.now())

    # 관계
    workflow_version = relationship("BotWorkflowVersion", back_populates="execution_runs")
    node_executions = relationship("WorkflowNodeExecution", back_populates="run")

class WorkflowNodeExecution(Base):
    __tablename__ = "workflow_node_executions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_run_id = Column(UUID(as_uuid=True), ForeignKey('workflow_execution_runs.id', ondelete='CASCADE'), nullable=False)
    node_id = Column(String(255), nullable=False)
    node_type = Column(String(50), nullable=False)
    execution_order = Column(Integer)

    inputs = Column(JSONB)
    outputs = Column(JSONB)
    process_data = Column(JSONB)

    status = Column(String(20), nullable=False)
    error_message = Column(Text)

    started_at = Column(DateTime, server_default=func.now())
    finished_at = Column(DateTime)
    elapsed_time = Column(Integer)
    tokens_used = Column(Integer, default=0)

    is_truncated = Column(Boolean, default=False)
    truncated_fields = Column(JSONB)

    created_at = Column(DateTime, server_default=func.now())

    # 관계
    run = relationship("WorkflowExecutionRun", back_populates="node_executions")
```

---

## 리팩토링 2단계: 변수 시스템 구축 (3-4주)

### 목표
WorkflowExecutionContext를 분리하여 서비스 컨테이너와 데이터 풀을 독립시킴

### 2.1 현재 컨텍스트 분석

**파일**: `Backend/app/core/workflow/executor.py`

```python
# 현재 구조 - 모든 것이 혼재
class WorkflowExecutionContext:
    def __init__(self, session_id: str, user_message: str):
        self.session_id = session_id
        self.user_message = user_message
        self.node_outputs: Dict[str, Any] = {}  # 데이터

        # 서비스들 (문제: 데이터와 섞임)
        self.vector_service: Optional[VectorService] = None
        self.llm_service: Optional[LLMService] = None
        self.bot_id: Optional[str] = None
        self.db: Optional[Any] = None
```

**문제점**:
- 데이터(node_outputs)와 서비스(vector_service 등)가 혼재
- 노드가 context에서 무엇이든 꺼낼 수 있음 (강한 결합)
- 포트 개념 없이 node_outputs[node_id]로 전체 출력 접근

### 2.2 리팩토링 작업

#### Step 1: VariablePool 클래스 생성

**신규 파일**: `Backend/app/core/workflow/variable_pool.py`

```python
from typing import Dict, Any, Optional, Set
from collections import defaultdict
from app.schemas.workflow import ValueSelector, PortType

class VariablePool:
    """
    워크플로우 실행 중 모든 데이터 관리

    특징:
    - 노드 출력을 포트별로 저장
    - ValueSelector를 통한 참조 해석
    - 환경 변수 및 대화 변수 관리
    """

    def __init__(self):
        # 노드 출력: {node_id: {port_name: value}}
        self._node_outputs: Dict[str, Dict[str, Any]] = defaultdict(dict)

        # 시스템 변수
        self._environment_variables: Dict[str, Any] = {}
        self._conversation_variables: Dict[str, Any] = {}
        self._system_variables: Dict[str, Any] = {}

    def set_node_output(self, node_id: str, port_name: str, value: Any) -> None:
        """노드의 특정 출력 포트 값 저장"""
        self._node_outputs[node_id][port_name] = value

    def get_node_output(self, node_id: str, port_name: str) -> Any:
        """노드의 특정 출력 포트 값 조회"""
        if node_id not in self._node_outputs:
            raise KeyError(f"노드 {node_id}가 아직 실행되지 않았습니다")
        if port_name not in self._node_outputs[node_id]:
            raise KeyError(f"노드 {node_id}에 출력 포트 '{port_name}'가 없습니다")
        return self._node_outputs[node_id][port_name]

    def has_node_output(self, node_id: str, port_name: str) -> bool:
        """노드 출력 존재 여부 확인"""
        return (node_id in self._node_outputs and
                port_name in self._node_outputs[node_id])

    def resolve_value_selector(self, selector: ValueSelector) -> Any:
        """
        변수 참조 해석 (예: "knowledge_1.documents")
        """
        node_id, port_name = selector.variable.split('.', 1)
        return self.get_node_output(node_id, port_name)

    def get_environment_variable(self, key: str) -> Any:
        """환경 변수 조회"""
        return self._environment_variables.get(key)

    def set_environment_variable(self, key: str, value: Any) -> None:
        """환경 변수 설정"""
        self._environment_variables[key] = value

    def get_all_node_outputs(self, node_id: str) -> Dict[str, Any]:
        """특정 노드의 모든 출력 반환 (하위 호환용)"""
        return self._node_outputs.get(node_id, {})
```

#### Step 2: ServiceContainer 클래스 생성

**신규 파일**: `Backend/app/core/workflow/service_container.py`

```python
from dataclasses import dataclass
from typing import Optional, Any, Callable
from sqlalchemy.orm import Session

@dataclass
class ServiceContainer:
    """
    노드에 주입할 서비스 컨테이너

    특징:
    - 노드 실행에 필요한 서비스만 포함
    - 데이터와 완전히 분리
    - 의존성 주입 패턴 적용
    """
    vector_service: Any  # VectorService 타입
    llm_service: Any  # LLMService 타입
    db: Session

    # 옵션 서비스
    stream_handler: Optional[Any] = None
    text_normalizer: Optional[Callable[[str], str]] = None
    file_storage: Optional[Any] = None

    def get_service(self, service_name: str) -> Any:
        """이름으로 서비스 조회"""
        return getattr(self, service_name, None)
```

#### Step 3: 기존 WorkflowExecutionContext 리팩토링

**파일 수정**: `Backend/app/core/workflow/executor.py`

```python
# 기존 클래스 유지하되, 새 컴포넌트로 위임
class WorkflowExecutionContext:
    """
    워크플로우 실행 컨텍스트 (하위 호환성 유지)

    내부적으로 VariablePool과 ServiceContainer 사용
    """

    def __init__(self, session_id: str, user_message: str):
        self.session_id = session_id
        self.user_message = user_message

        # 새 컴포넌트들
        self.variable_pool = VariablePool()
        self.services: Optional[ServiceContainer] = None

        # 하위 호환성을 위한 node_outputs (deprecated)
        self.node_outputs: Dict[str, Any] = {}
        self.metadata: Dict[str, Any] = {}

    def set_services(self, services: ServiceContainer):
        """서비스 컨테이너 설정"""
        self.services = services

    def set_node_output(self, node_id: str, output: Any):
        """
        노드 출력 저장 (하위 호환)

        새 코드에서는 variable_pool.set_node_output() 사용 권장
        """
        self.node_outputs[node_id] = output

        # 새 시스템에도 반영 (포트 이름 없이 전체 저장)
        if isinstance(output, dict):
            for port_name, value in output.items():
                self.variable_pool.set_node_output(node_id, port_name, value)

    def get_node_output(self, node_id: str) -> Optional[Any]:
        """노드 출력 조회 (하위 호환)"""
        return self.node_outputs.get(node_id)

    # 하위 호환성을 위한 프로퍼티들
    @property
    def vector_service(self):
        return self.services.vector_service if self.services else None

    @property
    def llm_service(self):
        return self.services.llm_service if self.services else None

    @property
    def db(self):
        return self.services.db if self.services else None
```

### 2.3 노드 인터페이스 개선

#### Step 1: BaseNodeV2 인터페이스 생성

**신규 파일**: `Backend/app/core/workflow/base_node_v2.py`

```python
from abc import ABC, abstractmethod
from typing import Dict, Any, List
from app.schemas.workflow import PortDefinition, PortType
from app.core.workflow.service_container import ServiceContainer

class BaseNodeV2(ABC):
    """
    향상된 노드 인터페이스 (포트 기반)

    특징:
    - 입출력 포트 명시적 정의
    - 서비스는 컨테이너로 주입
    - 데이터는 포트별로 전달
    """

    def __init__(self, node_id: str, config: Dict[str, Any]):
        self.node_id = node_id
        self.config = config
        self._input_schema: List[PortDefinition] = []
        self._output_schema: List[PortDefinition] = []
        self._initialize_ports()

    @abstractmethod
    def _initialize_ports(self) -> None:
        """포트 정의 (하위 클래스에서 구현)"""
        pass

    def get_input_schema(self) -> List[PortDefinition]:
        """입력 포트 스키마 반환"""
        return self._input_schema

    def get_output_schema(self) -> List[PortDefinition]:
        """출력 포트 스키마 반환"""
        return self._output_schema

    def validate_inputs(self, inputs: Dict[str, Any]) -> None:
        """입력 검증"""
        for port in self._input_schema:
            if port.required and port.name not in inputs:
                raise ValueError(
                    f"필수 입력 포트 '{port.name}'가 제공되지 않았습니다 (노드: {self.node_id})"
                )

    @abstractmethod
    async def execute(
        self,
        inputs: Dict[str, Any],  # {port_name: value}
        services: ServiceContainer
    ) -> Dict[str, Any]:  # {port_name: value}
        """
        노드 실행 (포트 기반 I/O)

        Args:
            inputs: 입력 포트 이름 → 값 딕셔너리
            services: 서비스 컨테이너

        Returns:
            출력 포트 이름 → 값 딕셔너리
        """
        pass
```

#### Step 2: Knowledge 노드 V2 구현 예시

**신규 파일**: `Backend/app/core/workflow/nodes/knowledge_node_v2.py`

```python
from app.core.workflow.base_node_v2 import BaseNodeV2
from app.schemas.workflow import PortDefinition, PortType
from typing import Dict, Any

class KnowledgeNodeV2(BaseNodeV2):
    """Knowledge 노드 V2 (포트 기반)"""

    def _initialize_ports(self):
        """포트 정의"""
        self._input_schema = [
            PortDefinition(
                name="query",
                type=PortType.STRING,
                required=True,
                description="검색 쿼리",
                display_name="쿼리"
            ),
            PortDefinition(
                name="top_k",
                type=PortType.NUMBER,
                required=False,
                default_value=5,
                description="검색할 문서 수",
                display_name="Top K"
            )
        ]

        self._output_schema = [
            PortDefinition(
                name="documents",
                type=PortType.ARRAY,
                required=True,
                description="검색된 문서 목록",
                display_name="문서"
            ),
            PortDefinition(
                name="context",
                type=PortType.STRING,
                required=True,
                description="연결된 문서 텍스트",
                display_name="컨텍스트"
            )
        ]

    async def execute(
        self,
        inputs: Dict[str, Any],
        services: ServiceContainer
    ) -> Dict[str, Any]:
        """실행"""
        self.validate_inputs(inputs)

        query = inputs["query"]
        top_k = inputs.get("top_k", 5)

        # 주입된 서비스 사용 (context에서 꺼내지 않음!)
        documents = await services.vector_service.search(
            bot_id=self.config["bot_id"],
            query=query,
            top_k=top_k
        )

        context = "\n\n".join([doc.content for doc in documents])

        # 출력 포트별로 반환
        return {
            "documents": [doc.dict() for doc in documents],
            "context": context
        }
```

#### Step 3: 노드 어댑터 (하위 호환성)

**신규 파일**: `Backend/app/core/workflow/node_adapter.py`

```python
from app.core.workflow.base_node import BaseNode
from app.core.workflow.base_node_v2 import BaseNodeV2
from app.schemas.workflow import PortDefinition, PortType
from typing import Dict, Any

class NodeAdapter:
    """기존 노드를 V2 인터페이스로 감싸는 어댑터"""

    @staticmethod
    def wrap_legacy_node(legacy_node: BaseNode) -> BaseNodeV2:
        """기존 노드 래핑"""

        class AdaptedNode(BaseNodeV2):
            def __init__(self):
                super().__init__(legacy_node.node_id, legacy_node.config.__dict__)
                self.legacy = legacy_node

            def _initialize_ports(self):
                # 기존 노드의 inputs/outputs를 포트로 변환
                self._input_schema = [
                    PortDefinition(
                        name=inp,
                        type=PortType.ANY,
                        required=True,
                        description=f"입력: {inp}",
                        display_name=inp
                    )
                    for inp in self.legacy.inputs()
                ]

                self._output_schema = [
                    PortDefinition(
                        name=out,
                        type=PortType.ANY,
                        required=True,
                        description=f"출력: {out}",
                        display_name=out
                    )
                    for out in self.legacy.outputs()
                ]

            async def execute(self, inputs: Dict[str, Any], services) -> Dict[str, Any]:
                # 기존 context 형식으로 변환
                context = {
                    "session_id": services.db.__dict__.get("session_id", ""),
                    "user_message": inputs.get("user_message", ""),
                    "node_outputs": inputs,
                    "vector_service": services.vector_service,
                    "llm_service": services.llm_service,
                    "bot_id": self.config.get("bot_id"),
                    "db": services.db,
                }

                # 기존 노드 실행
                result = await self.legacy.execute(context)

                # 결과를 포트별로 추출
                return {out: result.data.get(out) for out in self.legacy.outputs()}

        return AdaptedNode()
```

---

## 리팩토링 3단계: 실행 엔진 개선 (5-8주)

### 목표
WorkflowExecutor를 개선하여 포트 기반 데이터 흐름 지원

### 3.1 현재 Executor 분석

**파일**: `Backend/app/core/workflow/executor.py`

```python
class WorkflowExecutor:
    """현재 단순 토폴로지 정렬 실행기"""

    async def execute(self, workflow, context):
        # 1. 검증
        self.validator.validate(workflow)

        # 2. 노드 생성
        nodes = self._create_nodes(workflow)

        # 3. 실행 순서 계산 (토폴로지 정렬)
        self.execution_order = self.validator.get_execution_order()

        # 4. 순서대로 실행
        for node_id in self.execution_order:
            node = nodes[node_id]
            result = await node.execute(context)
            context.set_node_output(node_id, result.data)
```

**문제점**:
- 포트 개념 없음
- 조건 분기, 루프 미지원
- 병렬 실행 불가
- 노드 준비 상태 체크 없음

### 3.2 리팩토링 작업

#### Step 1: WorkflowExecutor에 포트 지원 추가

**파일 수정**: `Backend/app/core/workflow/executor.py`

```python
class WorkflowExecutor:
    """
    개선된 워크플로우 실행기

    변경사항:
    - 포트 기반 데이터 흐름 지원
    - VariablePool + ServiceContainer 사용
    - 하위 호환성 유지
    """

    def __init__(self):
        self.validator = WorkflowValidator()
        self.nodes: Dict[str, BaseNode] = {}
        self.execution_order: List[str] = []

    async def execute(
        self,
        workflow: Workflow,
        context: WorkflowExecutionContext
    ) -> Dict[str, Any]:
        """워크플로우 실행"""

        # 1. 검증
        self.validator.validate(workflow)

        # 2. 노드 생성 (V2 노드 또는 어댑터로 래핑)
        nodes = await self._create_nodes_v2(workflow)

        # 3. 실행 순서
        self.execution_order = self.validator.get_execution_order()

        # 4. 순서대로 실행 (포트 기반)
        for node_id in self.execution_order:
            node = nodes[node_id]

            # 입력 수집
            inputs = await self._gather_node_inputs(node_id, workflow, context)

            # 실행
            if isinstance(node, BaseNodeV2):
                # V2 노드: 포트 기반 실행
                outputs = await node.execute(inputs, context.services)

                # VariablePool에 저장
                for port_name, value in outputs.items():
                    context.variable_pool.set_node_output(node_id, port_name, value)
            else:
                # 기존 노드: 하위 호환
                result = await node.execute(context.to_dict())
                context.set_node_output(node_id, result.data)

        # 5. 최종 출력 수집
        return await self._collect_final_outputs(workflow, context)

    async def _create_nodes_v2(self, workflow: Workflow) -> Dict[str, Any]:
        """노드 생성 (V2 우선, 기존 노드는 어댑터로 래핑)"""
        nodes = {}

        for node_def in workflow.nodes:
            # V2 노드 생성 시도
            if node_def.ports:  # 포트 정의가 있으면 V2
                node = self._create_v2_node(node_def)
            else:  # 없으면 기존 노드 생성 후 어댑터로 래핑
                legacy_node = self._create_legacy_node(node_def)
                node = NodeAdapter.wrap_legacy_node(legacy_node)

            nodes[node_def.id] = node

        return nodes

    async def _gather_node_inputs(
        self,
        node_id: str,
        workflow: Workflow,
        context: WorkflowExecutionContext
    ) -> Dict[str, Any]:
        """노드의 입력 포트 값 수집"""
        inputs = {}
        node_def = self._get_node_def(workflow, node_id)

        if not node_def.ports:
            # 포트 없는 기존 노드: 전체 context 제공
            return context.to_dict()

        # 포트별로 입력 수집
        for port in node_def.ports.inputs:
            # variable_mappings 확인
            if port.name in node_def.variable_mappings:
                mapping = node_def.variable_mappings[port.name]
                inputs[port.name] = context.variable_pool.resolve_value_selector(mapping["source"])
            else:
                # 엣지에서 찾기
                for edge in workflow.edges:
                    if edge.target == node_id and edge.target_port == port.name:
                        inputs[port.name] = context.variable_pool.get_node_output(
                            edge.source,
                            edge.source_port
                        )
                        break
                else:
                    # 기본값 사용
                    if port.default_value is not None:
                        inputs[port.name] = port.default_value
                    elif port.required:
                        raise ValueError(f"필수 입력 포트 '{port.name}' 값 없음 (노드: {node_id})")

        return inputs

    async def _collect_final_outputs(
        self,
        workflow: Workflow,
        context: WorkflowExecutionContext
    ) -> Dict[str, Any]:
        """최종 출력 수집 (End 노드)"""
        end_nodes = [n for n in workflow.nodes if n.type == "end"]
        if not end_nodes:
            return {}

        end_node = end_nodes[0]
        outputs = {}

        if end_node.ports:
            # V2: 포트별 출력
            for port in end_node.ports.outputs:
                if context.variable_pool.has_node_output(end_node.id, port.name):
                    outputs[port.name] = context.variable_pool.get_node_output(
                        end_node.id,
                        port.name
                    )
        else:
            # 기존: node_outputs에서 가져오기
            outputs = context.get_node_output(end_node.id) or {}

        return outputs
```

#### Step 2: ChatService 수정

**파일 수정**: `Backend/app/services/chat_service.py`

```python
class ChatService:
    async def process_message(
        self,
        bot_id: str,
        message: str,
        session_id: str,
        user_id: Optional[str] = None
    ):
        """메시지 처리"""
        bot = await self.bot_service.get_bot(bot_id)

        # V2 워크플로우 사용 여부 확인
        if bot.use_workflow_v2:
            return await self._execute_workflow_v2(bot, message, session_id, user_id)
        elif bot.workflow:
            return await self._execute_workflow_legacy(bot, message, session_id)
        else:
            return await self._execute_simple_rag(bot, message, session_id)

    async def _execute_workflow_v2(self, bot, message, session_id, user_id):
        """V2 워크플로우 실행"""
        # 1. 발행된 워크플로우 버전 가져오기
        workflow_version = await self._get_published_workflow(bot.bot_id)
        if not workflow_version:
            # fallback to legacy
            return await self._execute_workflow_legacy(bot, message, session_id)

        # 2. 실행 기록 생성
        run = await self._create_execution_run(
            bot_id=bot.bot_id,
            workflow_version_id=workflow_version.id,
            session_id=session_id,
            user_id=user_id,
            inputs={"user_message": message}
        )

        # 3. Context 생성 (V2 컴포넌트 사용)
        context = WorkflowExecutionContext(
            session_id=session_id,
            user_message=message
        )

        # 서비스 컨테이너 설정
        services = ServiceContainer(
            vector_service=self.vector_service,
            llm_service=self.llm_service,
            db=self.db,
            stream_handler=None
        )
        context.set_services(services)

        # 환경 변수 설정
        for key, value in workflow_version.environment_variables.items():
            context.variable_pool.set_environment_variable(key, value)

        # 4. 실행 (개선된 executor)
        executor = WorkflowExecutor()

        try:
            # workflow_version.graph를 Workflow 객체로 변환
            workflow = Workflow(**workflow_version.graph)
            result = await executor.execute(workflow, context)

            # 실행 기록 완료
            await self._complete_execution_run(
                run_id=run.id,
                outputs=result,
                status="succeeded"
            )

            return result

        except Exception as e:
            await self._complete_execution_run(
                run_id=run.id,
                outputs={},
                status="failed",
                error_message=str(e)
            )
            raise

    async def _execute_workflow_legacy(self, bot, message, session_id):
        """기존 워크플로우 실행 (하위 호환)"""
        # 기존 코드 그대로 유지
        pass
```

---

## 리팩토링 4단계: API 구현 (9-10주)

### 목표
워크플로우 버전 관리 및 실행 이력 조회 API 제공

### 4.1 API 엔드포인트 구현

**신규 파일**: `Backend/app/api/v1/endpoints/workflow_versions.py`

```python
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional
from app.core.database import get_db
from app.api.dependencies import get_current_user
from app.models.user import User
from app.schemas.workflow import WorkflowVersion
from app.services.workflow_version_service import WorkflowVersionService

router = APIRouter(
    prefix="/bots/{bot_id}/workflows",
    tags=["workflows"]
)

@router.post("/versions/draft", response_model=WorkflowVersion)
async def create_or_update_draft(
    bot_id: str,
    request: WorkflowVersionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Draft 워크플로우 생성/수정

    - Bot당 하나의 draft만 존재
    - 기존 draft가 있으면 업데이트
    """
    service = WorkflowVersionService(db)
    return await service.create_or_update_draft(
        bot_id=bot_id,
        graph=request.graph,
        environment_variables=request.environment_variables,
        user_id=current_user.id
    )

@router.post("/versions/{version_id}/publish", response_model=WorkflowVersion)
async def publish_workflow(
    bot_id: str,
    version_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Draft를 발행

    - 새 버전 번호 생성 (v1.0, v1.1 등)
    - 해당 버전을 활성 워크플로우로 설정
    """
    service = WorkflowVersionService(db)
    return await service.publish_draft(
        bot_id=bot_id,
        version_id=version_id,
        user_id=current_user.id
    )

@router.get("/versions", response_model=List[WorkflowVersion])
async def list_workflow_versions(
    bot_id: str,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """워크플로우 버전 목록 조회"""
    service = WorkflowVersionService(db)
    return await service.list_versions(
        bot_id=bot_id,
        status=status
    )

@router.get("/versions/{version_id}", response_model=WorkflowVersionDetail)
async def get_workflow_version(
    bot_id: str,
    version_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """특정 버전 상세 조회"""
    service = WorkflowVersionService(db)
    version = await service.get_version(version_id)
    if not version or version.bot_id != bot_id:
        raise HTTPException(status_code=404, detail="버전을 찾을 수 없습니다")
    return version
```

**신규 파일**: `Backend/app/api/v1/endpoints/workflow_executions.py`

```python
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime
from app.core.database import get_db
from app.api.dependencies import get_current_user
from app.schemas.workflow import WorkflowRunResponse, PaginatedWorkflowRuns

router = APIRouter(
    prefix="/bots/{bot_id}/workflows/runs",
    tags=["workflow-executions"]
)

@router.get("", response_model=PaginatedWorkflowRuns)
async def list_execution_runs(
    bot_id: str,
    status: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    limit: int = Query(50, le=100),
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """실행 기록 목록 조회"""
    service = WorkflowExecutionService(db)
    return await service.list_runs(
        bot_id=bot_id,
        status=status,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
        offset=offset
    )

@router.get("/{run_id}", response_model=WorkflowRunDetail)
async def get_execution_run(
    bot_id: str,
    run_id: str,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """실행 기록 상세 조회"""
    service = WorkflowExecutionService(db)
    run = await service.get_run(run_id)
    if not run or run.bot_id != bot_id:
        raise HTTPException(status_code=404, detail="실행 기록을 찾을 수 없습니다")
    return run

@router.get("/{run_id}/nodes", response_model=List[NodeExecutionResponse])
async def get_node_executions(
    bot_id: str,
    run_id: str,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """노드 실행 기록 목록"""
    service = WorkflowExecutionService(db)
    return await service.get_node_executions(run_id)
```

### 4.2 Service 계층 구현

**신규 파일**: `Backend/app/services/workflow_version_service.py`

```python
from sqlalchemy.orm import Session
from sqlalchemy import and_
from typing import List, Optional
from app.models.workflow_version import BotWorkflowVersion
from app.schemas.workflow import WorkflowVersionStatus

class WorkflowVersionService:
    def __init__(self, db: Session):
        self.db = db

    async def create_or_update_draft(
        self,
        bot_id: str,
        graph: dict,
        environment_variables: dict,
        user_id: str
    ) -> BotWorkflowVersion:
        """Draft 생성 또는 업데이트"""

        # 기존 draft 찾기
        existing_draft = self.db.query(BotWorkflowVersion).filter(
            and_(
                BotWorkflowVersion.bot_id == bot_id,
                BotWorkflowVersion.status == WorkflowVersionStatus.DRAFT
            )
        ).first()

        if existing_draft:
            # 업데이트
            existing_draft.graph = graph
            existing_draft.environment_variables = environment_variables
            existing_draft.updated_at = datetime.now()
            self.db.commit()
            self.db.refresh(existing_draft)
            return existing_draft
        else:
            # 신규 생성
            draft = BotWorkflowVersion(
                bot_id=bot_id,
                version="draft",
                status=WorkflowVersionStatus.DRAFT,
                graph=graph,
                environment_variables=environment_variables,
                created_by=user_id
            )
            self.db.add(draft)
            self.db.commit()
            self.db.refresh(draft)
            return draft

    async def publish_draft(
        self,
        bot_id: str,
        version_id: str,
        user_id: str
    ) -> BotWorkflowVersion:
        """Draft 발행"""

        draft = self.db.query(BotWorkflowVersion).filter(
            BotWorkflowVersion.id == version_id,
            BotWorkflowVersion.bot_id == bot_id,
            BotWorkflowVersion.status == WorkflowVersionStatus.DRAFT
        ).first()

        if not draft:
            raise ValueError("Draft를 찾을 수 없습니다")

        # 새 버전 번호 생성
        last_version = self.db.query(BotWorkflowVersion).filter(
            BotWorkflowVersion.bot_id == bot_id,
            BotWorkflowVersion.status == WorkflowVersionStatus.PUBLISHED
        ).order_by(BotWorkflowVersion.created_at.desc()).first()

        if last_version:
            # v1.1 → v1.2
            version_parts = last_version.version.lstrip('v').split('.')
            new_version = f"v{version_parts[0]}.{int(version_parts[1]) + 1}"
        else:
            new_version = "v1.0"

        # Draft를 Published로 변경
        draft.version = new_version
        draft.status = WorkflowVersionStatus.PUBLISHED
        draft.published_at = datetime.now()

        # Bot의 use_workflow_v2 활성화
        from app.models.bot import Bot
        bot = self.db.query(Bot).filter(Bot.bot_id == bot_id).first()
        if bot:
            bot.use_workflow_v2 = True

        self.db.commit()
        self.db.refresh(draft)

        # 새 빈 draft 생성
        new_draft = BotWorkflowVersion(
            bot_id=bot_id,
            version="draft",
            status=WorkflowVersionStatus.DRAFT,
            graph=draft.graph,  # 기존 그래프 복사
            environment_variables=draft.environment_variables,
            created_by=user_id
        )
        self.db.add(new_draft)
        self.db.commit()

        return draft

    async def list_versions(
        self,
        bot_id: str,
        status: Optional[str] = None
    ) -> List[BotWorkflowVersion]:
        """버전 목록"""
        query = self.db.query(BotWorkflowVersion).filter(
            BotWorkflowVersion.bot_id == bot_id
        )

        if status:
            query = query.filter(BotWorkflowVersion.status == status)

        return query.order_by(BotWorkflowVersion.created_at.desc()).all()
```

---

## 마이그레이션 전략

### 기존 봇 전환 스크립트

**신규 파일**: `Backend/scripts/migrate_workflows_to_v2.py`

```python
"""
기존 워크플로우를 V2로 마이그레이션하는 스크립트
"""
import asyncio
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models.bot import Bot
from app.models.workflow_version import BotWorkflowVersion
from app.schemas.workflow import WorkflowVersionStatus

def convert_legacy_workflow_to_v2(legacy_workflow: dict) -> dict:
    """기존 워크플로우를 V2 그래프로 변환"""

    v2_nodes = []
    for node in legacy_workflow.get("nodes", []):
        v2_node = {
            "id": node["id"],
            "type": node["type"],
            "position": node["position"],
            "data": node["data"],
            # 포트 추론 (노드 타입별로)
            "ports": infer_ports_for_node_type(node["type"]),
            "variable_mappings": {}
        }
        v2_nodes.append(v2_node)

    # 엣지에 포트 정보 추가
    v2_edges = []
    for edge in legacy_workflow.get("edges", []):
        v2_edge = {
            "id": edge["id"],
            "source": edge["source"],
            "target": edge["target"],
            # 포트 이름 추론
            "source_port": infer_source_port(edge["source"], legacy_workflow),
            "target_port": infer_target_port(edge["target"], legacy_workflow),
            "data_type": "any"
        }
        v2_edges.append(v2_edge)

    return {
        "nodes": v2_nodes,
        "edges": v2_edges
    }

def infer_ports_for_node_type(node_type: str) -> dict:
    """노드 타입별 포트 추론"""
    ports = {
        "start": {
            "inputs": [],
            "outputs": [
                {"name": "user_message", "type": "string", "required": True},
                {"name": "session_id", "type": "string", "required": True}
            ]
        },
        "knowledge": {
            "inputs": [
                {"name": "query", "type": "string", "required": True}
            ],
            "outputs": [
                {"name": "documents", "type": "array", "required": True},
                {"name": "context", "type": "string", "required": True}
            ]
        },
        "llm": {
            "inputs": [
                {"name": "user_message", "type": "string", "required": True},
                {"name": "context", "type": "string", "required": False}
            ],
            "outputs": [
                {"name": "response", "type": "string", "required": True}
            ]
        },
        "end": {
            "inputs": [
                {"name": "response", "type": "string", "required": True}
            ],
            "outputs": [
                {"name": "final_output", "type": "string", "required": True}
            ]
        }
    }
    return ports.get(node_type, {"inputs": [], "outputs": []})

async def migrate_bot_to_v2(db: Session, bot: Bot, dry_run: bool = False):
    """개별 봇 마이그레이션"""

    if not bot.workflow:
        print(f"봇 {bot.bot_id}: 워크플로우 없음, 스킵")
        return

    try:
        # V2 그래프로 변환
        v2_graph = convert_legacy_workflow_to_v2(bot.workflow)

        if dry_run:
            print(f"봇 {bot.bot_id}: 변환 성공 (dry run)")
            return

        # Draft 버전 생성
        draft = BotWorkflowVersion(
            bot_id=bot.bot_id,
            version="draft",
            status=WorkflowVersionStatus.DRAFT,
            graph=v2_graph,
            environment_variables={},
            created_by=bot.user_id
        )
        db.add(draft)

        # 기존 워크플로우 백업
        bot.legacy_workflow = bot.workflow
        bot.use_workflow_v2 = False  # 수동 활성화 필요

        db.commit()
        print(f"봇 {bot.bot_id}: 마이그레이션 완료")

    except Exception as e:
        print(f"봇 {bot.bot_id}: 마이그레이션 실패 - {str(e)}")
        db.rollback()

async def main():
    """메인 실행 함수"""
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="실제 변경 없이 시뮬레이션")
    parser.add_argument("--bot-id", help="특정 봇만 마이그레이션")
    args = parser.parse_args()

    db = next(get_db())

    try:
        query = db.query(Bot).filter(Bot.workflow.isnot(None))

        if args.bot_id:
            query = query.filter(Bot.bot_id == args.bot_id)

        bots = query.all()
        print(f"총 {len(bots)}개 봇 마이그레이션 시작...")

        for bot in bots:
            await migrate_bot_to_v2(db, bot, dry_run=args.dry_run)

        print("마이그레이션 완료!")

    finally:
        db.close()

if __name__ == "__main__":
    asyncio.run(main())
```

**사용법**:
```bash
# Dry run (시뮬레이션)
python scripts/migrate_workflows_to_v2.py --dry-run

# 실제 마이그레이션
python scripts/migrate_workflows_to_v2.py

# 특정 봇만
python scripts/migrate_workflows_to_v2.py --bot-id abc-123
```

---

## 실행 계획

### 1단계 (1-2주): 스키마 & DB
- [ ] `app/schemas/workflow.py`에 포트/변수 스키마 추가
- [ ] Alembic 마이그레이션 작성 및 실행
- [ ] 모델 파일 업데이트
- [ ] **산출물**: 프론트엔드에 전달할 스키마 명세서

### 2단계 (3-4주): 변수 시스템
- [ ] `VariablePool` 클래스 구현
- [ ] `ServiceContainer` 클래스 구현
- [ ] `BaseNodeV2` 인터페이스 생성
- [ ] Knowledge/LLM/Start/End 노드 V2 구현
- [ ] `NodeAdapter` 구현 (하위 호환)
- [ ] **산출물**: V2 노드 개발 가이드

### 3단계 (5-8주): Executor 개선
- [ ] `WorkflowExecutor`에 포트 지원 추가
- [ ] 입력 수집 로직 구현 (`_gather_node_inputs`)
- [ ] V2/기존 노드 혼용 지원
- [ ] `ChatService` 수정 (V2 실행 분기)
- [ ] 실행 기록 저장 구현
- [ ] **산출물**: 통합 테스트 완료된 실행 엔진

### 4단계 (9-10주): API 구현
- [ ] 워크플로우 버전 API 엔드포인트
- [ ] 실행 이력 API 엔드포인트
- [ ] Service 계층 구현
- [ ] API 문서 자동 생성 (Swagger)
- [ ] **산출물**: API 문서 + Postman 컬렉션

### 5단계 (11-12주): 마이그레이션 & 배포
- [ ] 마이그레이션 스크립트 완성
- [ ] Staging 환경 테스트
- [ ] 성능 벤치마킹
- [ ] 점진적 롤아웃 (10% → 50% → 100%)
- [ ] **산출물**: 운영 가이드

---

## 리스크 및 대응

### 기술 리스크

**리스크**: 포트 기반 전환으로 인한 성능 저하
- **대응**: 벤치마킹 목표 <500ms 오버헤드, 미달 시 최적화
- **롤백**: Feature flag로 기존 엔진 사용 가능

**리스크**: 마이그레이션 중 데이터 손실
- **대응**: `legacy_workflow` 필드에 백업, dry-run 필수
- **롤백**: 백업에서 복구 스크립트 준비

**리스크**: 기존 노드 호환성 문제
- **대응**: `NodeAdapter`로 래핑, 광범위한 테스트
- **롤백**: 봇별 `use_workflow_v2=False` 설정

### 운영 리스크

**리스크**: 프론트엔드 팀과 일정 불일치
- **대응**: 1단계 완료 즉시 스키마 동결 및 공유
- **대안**: Mock API 제공으로 병렬 작업

**리스크**: 사용자 혼란 (UI 변경)
- **대응**: 튜토리얼, 마이그레이션 가이드 제공
- **대안**: 기존 빌더 유지, 점진적 전환

---

## 성공 지표

### 기술 지표
- ✅ 포트 기반 노드 실행 성공률 >99.9%
- ✅ 실행 오버헤드 <500ms (기존 대비)
- ✅ 테스트 커버리지 >85%
- ✅ 마이그레이션 성공률 >95%

### 비즈니스 지표
- ✅ 신규 봇의 80% V2 사용 (2개월 내)
- ✅ 기존 봇 마이그레이션 완료 >90%
- ✅ 워크플로우 복잡도 5배 향상 지원
- ✅ 사용자 만족도 NPS >50

---

## 결론

이 리팩토링 계획은 **기존 코드를 최대한 유지**하면서 Dify 아키텍처의 핵심 개념을 점진적으로 도입합니다:

1. **하위 호환성**: 기존 워크플로우는 계속 작동
2. **점진적 전환**: 스키마 → 변수 시스템 → 실행 엔진 → API 순차 개선
3. **리스크 완화**: Feature flag, 백업, 롤백 전략 완비
4. **병렬 작업**: 프론트엔드, QA, DevOps 팀이 단계별로 합류 가능

**예상 소요**: 12주 | **투입 인력**: 3-4명 백엔드 개발자

핵심은 **기존 시스템을 깨지 않으면서** 새로운 기능을 추가하는 것입니다.
