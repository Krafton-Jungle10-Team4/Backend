# 워크플로우 V2 프론트엔드-백엔드 통신 플로우

## 개요

이 문서는 리팩토링된 워크플로우 V2 시스템에서 프론트엔드(ReactFlow 기반 워크플로우 빌더)와 백엔드 간의 데이터 흐름과 API 상호작용을 상세히 설명합니다.

---

## 1. 워크플로우 편집 플로우

### 1.1 워크플로우 빌더 진입

**프론트엔드 동작**:
```typescript
// 사용자가 봇 상세 페이지에서 "워크플로우 편집" 클릭
const WorkflowEditor = () => {
  const { botId } = useParams();
  const [workflow, setWorkflow] = useState<WorkflowGraph | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    loadWorkflow();
  }, [botId]);

  const loadWorkflow = async () => {
    try {
      // 1. Draft 워크플로우 조회 시도
      const response = await fetch(
        `/api/v1/bots/${botId}/workflows/versions?status=draft`
      );
      const versions = await response.json();

      if (versions.length > 0) {
        // Draft 존재: 로드
        const draftId = versions[0].id;
        const detailResponse = await fetch(
          `/api/v1/bots/${botId}/workflows/versions/${draftId}`
        );
        const draft = await detailResponse.json();
        setWorkflow(draft.graph);
      } else {
        // Draft 없음: 기본 워크플로우 템플릿 로드
        setWorkflow(getDefaultWorkflow());
      }
    } catch (error) {
      console.error("워크플로우 로드 실패:", error);
    } finally {
      setIsLoading(false);
    }
  };

  return <ReactFlowCanvas workflow={workflow} onUpdate={handleUpdate} />;
};
```

**백엔드 API**:
```python
# GET /api/v1/bots/{bot_id}/workflows/versions?status=draft

@router.get("/versions")
async def list_workflow_versions(
    bot_id: str,
    status: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """워크플로우 버전 목록 조회"""
    service = WorkflowVersionService(db)

    # Bot 소유권 확인
    bot = await service.get_bot(bot_id)
    if bot.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="권한 없음")

    # 버전 조회
    query = db.query(BotWorkflowVersion).filter(
        BotWorkflowVersion.bot_id == bot_id
    )

    if status:
        query = query.filter(BotWorkflowVersion.status == status)

    versions = query.order_by(BotWorkflowVersion.created_at.desc()).all()

    return [
        {
            "id": v.id,
            "version": v.version,
            "status": v.status,
            "created_at": v.created_at,
            "updated_at": v.updated_at
        }
        for v in versions
    ]
```

**응답 예시**:
```json
[
  {
    "id": "draft-uuid-123",
    "version": "draft",
    "status": "draft",
    "created_at": "2025-11-13T10:00:00Z",
    "updated_at": "2025-11-13T10:30:00Z"
  }
]
```

---

### 1.2 노드 추가 및 연결

**프론트엔드 동작**:
```typescript
// 노드 타입 정보 조회 (페이지 로드 시 1회)
const [nodeTypes, setNodeTypes] = useState<NodeType[]>([]);

useEffect(() => {
  loadNodeTypes();
}, []);

const loadNodeTypes = async () => {
  const response = await fetch('/api/v1/workflows/node-types');
  const types = await response.json();
  setNodeTypes(types);
};

// 사용자가 노드 팔레트에서 노드 드래그 앤 드롭
const onNodeAdd = (type: string, position: { x: number; y: number }) => {
  // 노드 타입 정보에서 포트 스키마 가져오기
  const nodeTypeInfo = nodeTypes.find(nt => nt.type === type);

  const newNode: WorkflowNode = {
    id: `${type}_${Date.now()}`,
    type: type,
    position: position,
    data: {}, // 노드별 기본 설정
    ports: nodeTypeInfo.ports, // 입출력 포트 정의
    variable_mappings: {}
  };

  setNodes([...nodes, newNode]);
};

// 사용자가 노드 간 연결 (엣지 생성)
const onConnect = (connection: Connection) => {
  // 타입 호환성 검증
  const sourceNode = nodes.find(n => n.id === connection.source);
  const targetNode = nodes.find(n => n.id === connection.target);

  const sourcePort = sourceNode.ports.outputs.find(
    p => p.name === connection.sourceHandle
  );
  const targetPort = targetNode.ports.inputs.find(
    p => p.name === connection.targetHandle
  );

  if (sourcePort.type !== targetPort.type && targetPort.type !== "any") {
    alert("포트 타입이 호환되지 않습니다!");
    return;
  }

  const newEdge: WorkflowEdge = {
    id: `edge_${Date.now()}`,
    source: connection.source,
    target: connection.target,
    source_port: connection.sourceHandle,
    target_port: connection.targetHandle,
    data_type: sourcePort.type
  };

  setEdges([...edges, newEdge]);

  // 자동 저장 트리거 (30초 디바운스)
  scheduleAutoSave();
};
```

**백엔드 API (노드 타입 조회)**:
```python
# GET /api/v1/workflows/node-types

@router.get("/node-types")
async def get_node_types():
    """사용 가능한 노드 타입 목록 반환"""

    # 노드 레지스트리에서 정보 수집
    from app.core.workflow.node_registry import node_registry

    node_types = []
    for node_type, node_class in node_registry.items():
        # 임시 인스턴스 생성하여 포트 정보 추출
        temp_instance = node_class(
            node_id="temp",
            config={}
        )

        node_types.append({
            "type": node_type,
            "name": temp_instance.display_name,
            "category": temp_instance.category,
            "description": temp_instance.description,
            "input_ports": [
                {
                    "name": p.name,
                    "type": p.type,
                    "required": p.required,
                    "default_value": p.default_value,
                    "description": p.description,
                    "display_name": p.display_name
                }
                for p in temp_instance.get_input_schema()
            ],
            "output_ports": [
                {
                    "name": p.name,
                    "type": p.type,
                    "required": p.required,
                    "description": p.description,
                    "display_name": p.display_name
                }
                for p in temp_instance.get_output_schema()
            ],
            "config_schema": temp_instance.get_config_schema()
        })

    return node_types
```

**응답 예시**:
```json
[
  {
    "type": "knowledge",
    "name": "Knowledge Retrieval",
    "category": "retrieval",
    "description": "벡터 검색을 통해 관련 문서를 검색합니다",
    "input_ports": [
      {
        "name": "query",
        "type": "string",
        "required": true,
        "default_value": null,
        "description": "검색 쿼리",
        "display_name": "쿼리"
      },
      {
        "name": "top_k",
        "type": "number",
        "required": false,
        "default_value": 5,
        "description": "검색할 문서 수",
        "display_name": "Top K"
      }
    ],
    "output_ports": [
      {
        "name": "documents",
        "type": "array",
        "required": true,
        "description": "검색된 문서 목록",
        "display_name": "문서"
      },
      {
        "name": "context",
        "type": "string",
        "required": true,
        "description": "연결된 문서 텍스트",
        "display_name": "컨텍스트"
      }
    ],
    "config_schema": {
      "type": "object",
      "properties": {
        "top_k": {
          "type": "number",
          "default": 5,
          "minimum": 1,
          "maximum": 20
        },
        "score_threshold": {
          "type": "number",
          "default": 0.7,
          "minimum": 0,
          "maximum": 1
        }
      }
    }
  }
]
```

---

### 1.3 자동 저장 (Draft 업데이트)

**프론트엔드 동작**:
```typescript
// 30초 디바운스 자동 저장
const scheduleAutoSave = useCallback(
  debounce(() => {
    saveDraft();
  }, 30000),
  [nodes, edges]
);

const saveDraft = async () => {
  const workflowGraph = {
    nodes: nodes.map(node => ({
      id: node.id,
      type: node.type,
      position: node.position,
      data: node.data,
      ports: node.ports,
      variable_mappings: node.variable_mappings || {}
    })),
    edges: edges.map(edge => ({
      id: edge.id,
      source: edge.source,
      target: edge.target,
      source_port: edge.sourceHandle,
      target_port: edge.targetHandle,
      data_type: edge.data?.type || "any"
    }))
  };

  try {
    const response = await fetch(
      `/api/v1/bots/${botId}/workflows/versions/draft`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          graph: workflowGraph,
          environment_variables: {},
          conversation_variables: {}
        })
      }
    );

    if (response.ok) {
      console.log("Draft 자동 저장 완료");
      showToast("저장됨", "success");
    }
  } catch (error) {
    console.error("저장 실패:", error);
    showToast("저장 실패", "error");
  }
};
```

**백엔드 API**:
```python
# POST /api/v1/bots/{bot_id}/workflows/versions/draft

@router.post("/versions/draft")
async def create_or_update_draft(
    bot_id: str,
    request: WorkflowVersionCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Draft 생성 또는 업데이트"""
    service = WorkflowVersionService(db)

    # 권한 확인
    bot = await service.get_bot(bot_id)
    if bot.user_id != current_user.id:
        raise HTTPException(status_code=403)

    # 기존 draft 찾기
    existing_draft = db.query(BotWorkflowVersion).filter(
        and_(
            BotWorkflowVersion.bot_id == bot_id,
            BotWorkflowVersion.status == "draft"
        )
    ).first()

    if existing_draft:
        # 업데이트
        existing_draft.graph = request.graph
        existing_draft.environment_variables = request.environment_variables
        existing_draft.conversation_variables = request.conversation_variables
        existing_draft.updated_at = datetime.now()
        version = existing_draft
    else:
        # 신규 생성
        version = BotWorkflowVersion(
            bot_id=bot_id,
            version="draft",
            status="draft",
            graph=request.graph,
            environment_variables=request.environment_variables,
            conversation_variables=request.conversation_variables,
            created_by=current_user.id
        )
        db.add(version)

    db.commit()
    db.refresh(version)

    return {
        "id": version.id,
        "version": version.version,
        "status": version.status,
        "created_at": version.created_at,
        "updated_at": version.updated_at
    }
```

---

### 1.4 워크플로우 검증

**프론트엔드 동작**:
```typescript
// 사용자가 "발행" 버튼 클릭 전 검증
const validateWorkflow = async () => {
  setIsValidating(true);

  try {
    const response = await fetch(
      `/api/v1/bots/${botId}/workflows/validate`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          graph: {
            nodes: nodes,
            edges: edges
          }
        })
      }
    );

    const result = await response.json();

    if (result.is_valid) {
      // 검증 성공: 발행 진행
      publishWorkflow();
    } else {
      // 검증 실패: 에러/경고 표시
      setValidationErrors(result.errors);
      setValidationWarnings(result.warnings);

      // 에러 노드 하이라이트
      result.errors.forEach(error => {
        if (error.node_id) {
          highlightNode(error.node_id, 'error');
        }
      });
    }
  } catch (error) {
    console.error("검증 실패:", error);
  } finally {
    setIsValidating(false);
  }
};
```

**백엔드 API**:
```python
# POST /api/v1/bots/{bot_id}/workflows/validate

@router.post("/validate")
async def validate_workflow(
    bot_id: str,
    request: WorkflowValidationRequest,
    db: Session = Depends(get_db)
):
    """워크플로우 검증"""
    from app.core.workflow.validator import WorkflowValidatorV2

    validator = WorkflowValidatorV2()
    errors = []
    warnings = []

    # 1. 구조 검증
    if not validator.has_start_node(request.graph):
        errors.append({
            "node_id": None,
            "type": "missing_start",
            "message": "Start 노드가 없습니다",
            "severity": "error"
        })

    if not validator.has_end_node(request.graph):
        errors.append({
            "node_id": None,
            "type": "missing_end",
            "message": "End 노드가 없습니다",
            "severity": "error"
        })

    # 2. 사이클 검증 (루프 노드 제외)
    cycles = validator.detect_cycles(request.graph)
    if cycles:
        errors.append({
            "node_id": None,
            "type": "cycle_detected",
            "message": f"순환 참조 발견: {' -> '.join(cycles[0])}",
            "severity": "error"
        })

    # 3. 포트 연결 검증
    for node in request.graph.nodes:
        # 필수 입력 포트가 연결되었는지 확인
        required_inputs = [
            p for p in node.ports.inputs if p.required
        ]

        for port in required_inputs:
            connected = any(
                e.target == node.id and e.target_port == port.name
                for e in request.graph.edges
            )

            if not connected and not node.variable_mappings.get(port.name):
                errors.append({
                    "node_id": node.id,
                    "type": "missing_connection",
                    "message": f"필수 입력 포트 '{port.display_name}'가 연결되지 않았습니다",
                    "severity": "error"
                })

    # 4. 타입 호환성 검증
    for edge in request.graph.edges:
        source_node = next(n for n in request.graph.nodes if n.id == edge.source)
        target_node = next(n for n in request.graph.nodes if n.id == edge.target)

        source_port = next(
            p for p in source_node.ports.outputs if p.name == edge.source_port
        )
        target_port = next(
            p for p in target_node.ports.inputs if p.name == edge.target_port
        )

        if source_port.type != target_port.type and target_port.type != "any":
            errors.append({
                "node_id": edge.target,
                "type": "type_mismatch",
                "message": f"타입 불일치: {source_port.type} → {target_port.type}",
                "severity": "error"
            })

    # 5. 고립된 노드 경고
    connected_nodes = set()
    for edge in request.graph.edges:
        connected_nodes.add(edge.source)
        connected_nodes.add(edge.target)

    for node in request.graph.nodes:
        if node.id not in connected_nodes and node.type not in ["start", "end"]:
            warnings.append({
                "node_id": node.id,
                "type": "orphaned_node",
                "message": "연결되지 않은 노드입니다",
                "severity": "warning"
            })

    return {
        "is_valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings
    }
```

**응답 예시 (검증 실패)**:
```json
{
  "is_valid": false,
  "errors": [
    {
      "node_id": "llm_1",
      "type": "missing_connection",
      "message": "필수 입력 포트 '쿼리'가 연결되지 않았습니다",
      "severity": "error"
    },
    {
      "node_id": "knowledge_1",
      "type": "type_mismatch",
      "message": "타입 불일치: array → string",
      "severity": "error"
    }
  ],
  "warnings": [
    {
      "node_id": "condition_1",
      "type": "orphaned_node",
      "message": "연결되지 않은 노드입니다",
      "severity": "warning"
    }
  ]
}
```

---

### 1.5 워크플로우 발행

**프론트엔드 동작**:
```typescript
const publishWorkflow = async () => {
  // 1. 검증 통과 확인
  const validationResult = await validateWorkflow();
  if (!validationResult.is_valid) {
    return;
  }

  // 2. 확인 모달
  const confirmed = await showConfirmDialog({
    title: "워크플로우 발행",
    message: "발행 후 이 워크플로우가 활성화됩니다. 계속하시겠습니까?",
    confirmText: "발행",
    cancelText: "취소"
  });

  if (!confirmed) return;

  // 3. 발행 API 호출
  try {
    const response = await fetch(
      `/api/v1/bots/${botId}/workflows/versions/${draftId}/publish`,
      { method: "POST" }
    );

    if (response.ok) {
      const publishedVersion = await response.json();
      showToast(`버전 ${publishedVersion.version} 발행 완료!`, "success");

      // 워크플로우 목록으로 이동
      navigate(`/bots/${botId}/workflows`);
    }
  } catch (error) {
    console.error("발행 실패:", error);
    showToast("발행 중 오류가 발생했습니다", "error");
  }
};
```

**백엔드 API**:
```python
# POST /api/v1/bots/{bot_id}/workflows/versions/{version_id}/publish

@router.post("/versions/{version_id}/publish")
async def publish_workflow(
    bot_id: str,
    version_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Draft를 발행하여 새 버전 생성"""
    service = WorkflowVersionService(db)

    # 권한 확인
    bot = await service.get_bot(bot_id)
    if bot.user_id != current_user.id:
        raise HTTPException(status_code=403)

    # Draft 조회
    draft = db.query(BotWorkflowVersion).filter(
        and_(
            BotWorkflowVersion.id == version_id,
            BotWorkflowVersion.bot_id == bot_id,
            BotWorkflowVersion.status == "draft"
        )
    ).first()

    if not draft:
        raise HTTPException(status_code=404, detail="Draft를 찾을 수 없습니다")

    # 최종 검증
    validator = WorkflowValidatorV2()
    validation_result = validator.validate(draft.graph)
    if not validation_result["is_valid"]:
        raise HTTPException(
            status_code=400,
            detail={"message": "검증 실패", "errors": validation_result["errors"]}
        )

    # 새 버전 번호 생성
    last_version = db.query(BotWorkflowVersion).filter(
        and_(
            BotWorkflowVersion.bot_id == bot_id,
            BotWorkflowVersion.status == "published"
        )
    ).order_by(BotWorkflowVersion.created_at.desc()).first()

    if last_version:
        # v1.1 → v1.2
        parts = last_version.version.lstrip('v').split('.')
        new_version = f"v{parts[0]}.{int(parts[1]) + 1}"
    else:
        new_version = "v1.0"

    # Draft를 Published로 변경
    draft.version = new_version
    draft.status = "published"
    draft.published_at = datetime.now()

    # Bot의 V2 플래그 활성화
    bot.use_workflow_v2 = True

    db.commit()
    db.refresh(draft)

    # 새 빈 Draft 생성 (다음 편집용)
    new_draft = BotWorkflowVersion(
        bot_id=bot_id,
        version="draft",
        status="draft",
        graph=draft.graph,  # 발행된 그래프 복사
        environment_variables=draft.environment_variables,
        conversation_variables=draft.conversation_variables,
        created_by=current_user.id
    )
    db.add(new_draft)
    db.commit()

    return {
        "id": draft.id,
        "version": draft.version,
        "status": draft.status,
        "published_at": draft.published_at
    }
```

---

## 2. 워크플로우 실행 플로우

### 2.1 챗봇 대화 시작

**프론트엔드 동작**:
```typescript
// 사용자가 채팅창에 메시지 입력 및 전송
const sendMessage = async (message: string) => {
  // 1. UI에 사용자 메시지 추가
  addMessage({ role: "user", content: message });

  // 2. 챗봇 API 호출
  try {
    const response = await fetch(`/api/v1/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        bot_id: botId,
        message: message,
        session_id: sessionId
      })
    });

    const result = await response.json();

    // 3. 봇 응답 추가
    addMessage({ role: "assistant", content: result.response });

    // 4. 실행 ID 저장 (나중에 디버깅용)
    setLastRunId(result.run_id);
  } catch (error) {
    console.error("메시지 전송 실패:", error);
    addMessage({
      role: "assistant",
      content: "죄송합니다. 오류가 발생했습니다."
    });
  }
};
```

**백엔드 API**:
```python
# POST /api/v1/chat

@router.post("/chat")
async def chat(
    request: ChatRequest,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional)
):
    """챗봇 메시지 처리"""
    chat_service = ChatService(db)

    result = await chat_service.process_message(
        bot_id=request.bot_id,
        message=request.message,
        session_id=request.session_id,
        user_id=current_user.id if current_user else None
    )

    return {
        "response": result.get("final_output", "응답을 생성할 수 없습니다"),
        "run_id": result.get("run_id"),
        "tokens_used": result.get("total_tokens", 0)
    }
```

**ChatService 내부 처리**:
```python
class ChatService:
    async def process_message(
        self,
        bot_id: str,
        message: str,
        session_id: str,
        user_id: Optional[str] = None
    ):
        # 1. Bot 조회
        bot = await self.bot_service.get_bot(bot_id)

        # 2. 워크플로우 방식 결정
        if bot.use_workflow_v2:
            return await self._execute_workflow_v2(bot, message, session_id, user_id)
        elif bot.workflow:
            return await self._execute_workflow_legacy(bot, message, session_id)
        else:
            return await self._execute_simple_rag(bot, message, session_id)

    async def _execute_workflow_v2(self, bot, message, session_id, user_id):
        # 1. 발행된 워크플로우 버전 조회
        workflow_version = await self._get_published_workflow(bot.bot_id)
        if not workflow_version:
            # Fallback
            return await self._execute_workflow_legacy(bot, message, session_id)

        # 2. 실행 기록 생성 (시작)
        run = await self._create_execution_run(
            bot_id=bot.bot_id,
            workflow_version_id=workflow_version.id,
            session_id=session_id,
            user_id=user_id,
            inputs={"user_message": message},
            graph_snapshot=workflow_version.graph
        )

        # 3. Context 생성
        context = WorkflowExecutionContext(
            session_id=session_id,
            user_message=message
        )

        # 서비스 컨테이너 설정
        services = ServiceContainer(
            vector_service=self.vector_service,
            llm_service=self.llm_service,
            db=self.db
        )
        context.set_services(services)

        # 환경 변수 설정
        for key, value in workflow_version.environment_variables.items():
            context.variable_pool.set_environment_variable(key, value)

        # 4. 워크플로우 실행
        executor = WorkflowExecutor()

        try:
            start_time = datetime.now()

            # Workflow 객체로 변환
            workflow = Workflow(
                nodes=[WorkflowNode(**n) for n in workflow_version.graph["nodes"]],
                edges=[WorkflowEdge(**e) for e in workflow_version.graph["edges"]]
            )

            result = await executor.execute(workflow, context)

            # 실행 기록 완료
            elapsed_time = (datetime.now() - start_time).total_seconds() * 1000

            await self._complete_execution_run(
                run_id=run.id,
                outputs=result,
                status="succeeded",
                elapsed_time=int(elapsed_time)
            )

            return {
                "final_output": result.get("final_output", ""),
                "run_id": str(run.id),
                "total_tokens": result.get("total_tokens", 0)
            }

        except Exception as e:
            logger.error(f"워크플로우 실행 실패: {str(e)}", exc_info=True)

            await self._complete_execution_run(
                run_id=run.id,
                outputs={},
                status="failed",
                error_message=str(e),
                elapsed_time=0
            )

            raise HTTPException(status_code=500, detail=str(e))

    async def _create_execution_run(
        self,
        bot_id: str,
        workflow_version_id: str,
        session_id: str,
        user_id: Optional[str],
        inputs: dict,
        graph_snapshot: dict
    ):
        """실행 기록 생성"""
        run = WorkflowExecutionRun(
            bot_id=bot_id,
            workflow_version_id=workflow_version_id,
            session_id=session_id,
            user_id=user_id,
            inputs=inputs,
            graph_snapshot=graph_snapshot,
            status="running",
            started_at=datetime.now()
        )
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)
        return run

    async def _complete_execution_run(
        self,
        run_id: str,
        outputs: dict,
        status: str,
        elapsed_time: int,
        error_message: Optional[str] = None
    ):
        """실행 기록 완료"""
        run = self.db.query(WorkflowExecutionRun).filter(
            WorkflowExecutionRun.id == run_id
        ).first()

        run.outputs = outputs
        run.status = status
        run.error_message = error_message
        run.finished_at = datetime.now()
        run.elapsed_time = elapsed_time

        self.db.commit()
```

---

### 2.2 실행 중 노드별 기록 저장

**WorkflowExecutor 내부**:
```python
class WorkflowExecutor:
    async def execute(self, workflow: Workflow, context: WorkflowExecutionContext):
        # ... (기존 코드)

        for node_id in self.execution_order:
            node = nodes[node_id]

            # 노드 실행 기록 시작
            node_execution_id = await self._create_node_execution(
                run_id=context.run_id,
                node_id=node_id,
                node_type=node.node_type
            )

            start_time = datetime.now()

            try:
                # 입력 수집
                inputs = await self._gather_node_inputs(node_id, workflow, context)

                # 실행
                outputs = await node.execute(inputs, context.services)

                # VariablePool에 저장
                for port_name, value in outputs.items():
                    context.variable_pool.set_node_output(node_id, port_name, value)

                # 실행 시간 계산
                elapsed_time = (datetime.now() - start_time).total_seconds() * 1000

                # 노드 실행 기록 완료
                await self._complete_node_execution(
                    node_execution_id=node_execution_id,
                    inputs=inputs,
                    outputs=outputs,
                    status="succeeded",
                    elapsed_time=int(elapsed_time)
                )

            except Exception as e:
                elapsed_time = (datetime.now() - start_time).total_seconds() * 1000

                await self._complete_node_execution(
                    node_execution_id=node_execution_id,
                    inputs=inputs if 'inputs' in locals() else {},
                    outputs={},
                    status="failed",
                    error_message=str(e),
                    elapsed_time=int(elapsed_time)
                )
                raise

        # ... (기존 코드)

    async def _create_node_execution(
        self,
        run_id: str,
        node_id: str,
        node_type: str
    ):
        """노드 실행 기록 시작"""
        from app.models.workflow_version import WorkflowNodeExecution

        node_exec = WorkflowNodeExecution(
            workflow_run_id=run_id,
            node_id=node_id,
            node_type=node_type,
            status="running",
            started_at=datetime.now()
        )
        self.db.add(node_exec)
        self.db.commit()
        self.db.refresh(node_exec)
        return node_exec.id

    async def _complete_node_execution(
        self,
        node_execution_id: str,
        inputs: dict,
        outputs: dict,
        status: str,
        elapsed_time: int,
        error_message: Optional[str] = None
    ):
        """노드 실행 기록 완료"""
        from app.models.workflow_version import WorkflowNodeExecution
        import json

        node_exec = self.db.query(WorkflowNodeExecution).filter(
            WorkflowNodeExecution.id == node_execution_id
        ).first()

        # 데이터 크기 체크 (100KB 초과 시 오프로드)
        inputs_json = json.dumps(inputs)
        outputs_json = json.dumps(outputs)

        if len(inputs_json) > 100_000:
            # S3에 저장하고 미리보기만 DB에
            inputs_preview = self._truncate_data(inputs)
            node_exec.inputs = inputs_preview
            node_exec.is_truncated = True
            node_exec.truncated_fields = {"inputs": True}
            # TODO: S3 업로드 구현
        else:
            node_exec.inputs = inputs

        if len(outputs_json) > 100_000:
            outputs_preview = self._truncate_data(outputs)
            node_exec.outputs = outputs_preview
            node_exec.is_truncated = True
            if node_exec.truncated_fields:
                node_exec.truncated_fields["outputs"] = True
            else:
                node_exec.truncated_fields = {"outputs": True}
        else:
            node_exec.outputs = outputs

        node_exec.status = status
        node_exec.error_message = error_message
        node_exec.finished_at = datetime.now()
        node_exec.elapsed_time = elapsed_time

        self.db.commit()

    def _truncate_data(self, data: dict, max_length: int = 1000) -> dict:
        """데이터 미리보기 생성"""
        preview = {}
        for key, value in data.items():
            if isinstance(value, str) and len(value) > max_length:
                preview[key] = value[:max_length] + "... [truncated]"
            elif isinstance(value, list) and len(value) > 10:
                preview[key] = value[:10] + ["... [truncated]"]
            else:
                preview[key] = value
        return preview
```

---

## 3. 실행 이력 조회 플로우

### 3.1 실행 목록 조회

**프론트엔드 동작**:
```typescript
// 워크플로우 실행 이력 페이지
const WorkflowRunsPage = () => {
  const { botId } = useParams();
  const [runs, setRuns] = useState<WorkflowRun[]>([]);
  const [pagination, setPagination] = useState({
    page: 0,
    pageSize: 50,
    total: 0
  });
  const [filters, setFilters] = useState({
    status: null,
    startDate: null,
    endDate: null
  });

  useEffect(() => {
    loadRuns();
  }, [botId, pagination.page, filters]);

  const loadRuns = async () => {
    const params = new URLSearchParams({
      limit: pagination.pageSize.toString(),
      offset: (pagination.page * pagination.pageSize).toString()
    });

    if (filters.status) {
      params.append("status", filters.status);
    }
    if (filters.startDate) {
      params.append("start_date", filters.startDate.toISOString());
    }
    if (filters.endDate) {
      params.append("end_date", filters.endDate.toISOString());
    }

    const response = await fetch(
      `/api/v1/bots/${botId}/workflows/runs?${params}`
    );
    const result = await response.json();

    setRuns(result.runs);
    setPagination({
      ...pagination,
      total: result.total
    });
  };

  return (
    <div>
      {/* 필터 UI */}
      <RunFilters filters={filters} onFilterChange={setFilters} />

      {/* 실행 목록 테이블 */}
      <table>
        <thead>
          <tr>
            <th>실행 ID</th>
            <th>상태</th>
            <th>시작 시간</th>
            <th>소요 시간</th>
            <th>토큰 사용량</th>
            <th>동작</th>
          </tr>
        </thead>
        <tbody>
          {runs.map(run => (
            <tr key={run.id}>
              <td>{run.id.substring(0, 8)}...</td>
              <td>
                <StatusBadge status={run.status} />
              </td>
              <td>{new Date(run.started_at).toLocaleString()}</td>
              <td>{run.elapsed_time}ms</td>
              <td>{run.total_tokens}</td>
              <td>
                <button onClick={() => viewRunDetail(run.id)}>
                  상세보기
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {/* 페이지네이션 */}
      <Pagination
        page={pagination.page}
        pageSize={pagination.pageSize}
        total={pagination.total}
        onPageChange={(page) => setPagination({ ...pagination, page })}
      />
    </div>
  );
};
```

**백엔드 API**:
```python
# GET /api/v1/bots/{bot_id}/workflows/runs

@router.get("/runs")
async def list_workflow_runs(
    bot_id: str,
    status: Optional[str] = Query(None),
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    limit: int = Query(50, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """실행 기록 목록 조회"""

    # 권한 확인
    bot = db.query(Bot).filter(Bot.bot_id == bot_id).first()
    if not bot or bot.user_id != current_user.id:
        raise HTTPException(status_code=404)

    # 쿼리 구성
    query = db.query(WorkflowExecutionRun).filter(
        WorkflowExecutionRun.bot_id == bot_id
    )

    if status:
        query = query.filter(WorkflowExecutionRun.status == status)

    if start_date:
        query = query.filter(WorkflowExecutionRun.started_at >= start_date)

    if end_date:
        query = query.filter(WorkflowExecutionRun.started_at <= end_date)

    # 전체 개수
    total = query.count()

    # 페이지네이션
    runs = query.order_by(
        WorkflowExecutionRun.started_at.desc()
    ).offset(offset).limit(limit).all()

    return {
        "runs": [
            {
                "id": r.id,
                "session_id": r.session_id,
                "status": r.status,
                "started_at": r.started_at,
                "finished_at": r.finished_at,
                "elapsed_time": r.elapsed_time,
                "total_tokens": r.total_tokens,
                "total_steps": r.total_steps
            }
            for r in runs
        ],
        "total": total,
        "page": offset // limit,
        "page_size": limit
    }
```

---

### 3.2 실행 상세 및 노드별 기록

**프론트엔드 동작**:
```typescript
const WorkflowRunDetailPage = () => {
  const { botId, runId } = useParams();
  const [run, setRun] = useState<WorkflowRunDetail | null>(null);
  const [nodeExecutions, setNodeExecutions] = useState<NodeExecution[]>([]);

  useEffect(() => {
    loadRunDetail();
    loadNodeExecutions();
  }, [runId]);

  const loadRunDetail = async () => {
    const response = await fetch(
      `/api/v1/bots/${botId}/workflows/runs/${runId}`
    );
    const data = await response.json();
    setRun(data);
  };

  const loadNodeExecutions = async () => {
    const response = await fetch(
      `/api/v1/bots/${botId}/workflows/runs/${runId}/nodes`
    );
    const data = await response.json();
    setNodeExecutions(data);
  };

  const viewNodeDetail = async (nodeId: string) => {
    const response = await fetch(
      `/api/v1/bots/${botId}/workflows/runs/${runId}/nodes/${nodeId}`
    );
    const detail = await response.json();

    // 모달로 상세 표시
    showNodeDetailModal({
      nodeId: detail.node_id,
      inputs: detail.inputs,
      outputs: detail.outputs,
      isTruncated: detail.is_truncated,
      fullDataUrls: detail.full_data_urls
    });
  };

  return (
    <div>
      {/* 실행 개요 */}
      <RunSummary run={run} />

      {/* 워크플로우 시각화 (노드 상태 표시) */}
      <WorkflowVisualization
        graph={run?.graph_snapshot}
        nodeExecutions={nodeExecutions}
      />

      {/* 노드 실행 타임라인 */}
      <NodeExecutionTimeline>
        {nodeExecutions.map(ne => (
          <TimelineItem
            key={ne.id}
            nodeId={ne.node_id}
            status={ne.status}
            elapsedTime={ne.elapsed_time}
            onClick={() => viewNodeDetail(ne.node_id)}
          />
        ))}
      </NodeExecutionTimeline>

      {/* 노드 실행 목록 */}
      <table>
        <thead>
          <tr>
            <th>노드 ID</th>
            <th>노드 타입</th>
            <th>상태</th>
            <th>실행 시간</th>
            <th>토큰 사용</th>
            <th>동작</th>
          </tr>
        </thead>
        <tbody>
          {nodeExecutions.map(ne => (
            <tr key={ne.id}>
              <td>{ne.node_id}</td>
              <td>{ne.node_type}</td>
              <td><StatusBadge status={ne.status} /></td>
              <td>{ne.elapsed_time}ms</td>
              <td>{ne.tokens_used}</td>
              <td>
                <button onClick={() => viewNodeDetail(ne.node_id)}>
                  입출력 보기
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};
```

**백엔드 API (실행 상세)**:
```python
# GET /api/v1/bots/{bot_id}/workflows/runs/{run_id}

@router.get("/runs/{run_id}")
async def get_workflow_run(
    bot_id: str,
    run_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """실행 기록 상세 조회"""

    run = db.query(WorkflowExecutionRun).filter(
        and_(
            WorkflowExecutionRun.id == run_id,
            WorkflowExecutionRun.bot_id == bot_id
        )
    ).first()

    if not run:
        raise HTTPException(status_code=404)

    # 권한 확인
    bot = db.query(Bot).filter(Bot.bot_id == bot_id).first()
    if bot.user_id != current_user.id:
        raise HTTPException(status_code=403)

    return {
        "id": run.id,
        "bot_id": run.bot_id,
        "workflow_version_id": run.workflow_version_id,
        "session_id": run.session_id,
        "status": run.status,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "elapsed_time": run.elapsed_time,
        "total_tokens": run.total_tokens,
        "total_steps": run.total_steps,
        "graph_snapshot": run.graph_snapshot,
        "inputs": run.inputs,
        "outputs": run.outputs,
        "error_message": run.error_message
    }
```

**백엔드 API (노드 실행 목록)**:
```python
# GET /api/v1/bots/{bot_id}/workflows/runs/{run_id}/nodes

@router.get("/runs/{run_id}/nodes")
async def get_node_executions(
    bot_id: str,
    run_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """노드 실행 기록 목록"""

    # 권한 확인
    run = db.query(WorkflowExecutionRun).filter(
        WorkflowExecutionRun.id == run_id
    ).first()
    if not run or run.bot_id != bot_id:
        raise HTTPException(status_code=404)

    bot = db.query(Bot).filter(Bot.bot_id == bot_id).first()
    if bot.user_id != current_user.id:
        raise HTTPException(status_code=403)

    # 노드 실행 기록 조회
    node_execs = db.query(WorkflowNodeExecution).filter(
        WorkflowNodeExecution.workflow_run_id == run_id
    ).order_by(WorkflowNodeExecution.started_at).all()

    return [
        {
            "id": ne.id,
            "node_id": ne.node_id,
            "node_type": ne.node_type,
            "status": ne.status,
            "inputs": ne.inputs,  # 미리보기 (truncated)
            "outputs": ne.outputs,  # 미리보기 (truncated)
            "started_at": ne.started_at,
            "finished_at": ne.finished_at,
            "elapsed_time": ne.elapsed_time,
            "tokens_used": ne.tokens_used,
            "is_truncated": ne.is_truncated,
            "truncated_fields": ne.truncated_fields
        }
        for ne in node_execs
    ]
```

**백엔드 API (노드 실행 상세)**:
```python
# GET /api/v1/bots/{bot_id}/workflows/runs/{run_id}/nodes/{node_id}

@router.get("/runs/{run_id}/nodes/{node_id}")
async def get_node_execution_detail(
    bot_id: str,
    run_id: str,
    node_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """노드 실행 상세 (전체 데이터 포함)"""

    # 권한 확인 (생략)

    node_exec = db.query(WorkflowNodeExecution).filter(
        and_(
            WorkflowNodeExecution.workflow_run_id == run_id,
            WorkflowNodeExecution.node_id == node_id
        )
    ).first()

    if not node_exec:
        raise HTTPException(status_code=404)

    result = {
        "id": node_exec.id,
        "node_id": node_exec.node_id,
        "node_type": node_exec.node_type,
        "status": node_exec.status,
        "inputs": node_exec.inputs,
        "outputs": node_exec.outputs,
        "process_data": node_exec.process_data,
        "error_message": node_exec.error_message,
        "started_at": node_exec.started_at,
        "finished_at": node_exec.finished_at,
        "elapsed_time": node_exec.elapsed_time,
        "tokens_used": node_exec.tokens_used,
        "is_truncated": node_exec.is_truncated
    }

    # 데이터가 truncated된 경우 전체 데이터 URL 제공
    if node_exec.is_truncated:
        # S3에서 presigned URL 생성
        full_data_urls = {}

        if node_exec.truncated_fields.get("inputs"):
            full_data_urls["inputs"] = await generate_presigned_url(
                f"workflow-data/{run_id}/{node_id}/inputs.json"
            )

        if node_exec.truncated_fields.get("outputs"):
            full_data_urls["outputs"] = await generate_presigned_url(
                f"workflow-data/{run_id}/{node_id}/outputs.json"
            )

        result["full_data_urls"] = full_data_urls

    return result
```

---

## 4. 전체 플로우 다이어그램

```
┌─────────────────────────────────────────────────────────────────┐
│                        프론트엔드                                 │
└─────────────────────────────────────────────────────────────────┘

[워크플로우 편집]
  1. GET /workflows/versions?status=draft → Draft 로드
  2. GET /workflows/node-types → 노드 타입 정보
  3. [사용자가 노드 추가/연결]
  4. POST /workflows/versions/draft → 자동 저장 (30초)
  5. [사용자가 "발행" 클릭]
  6. POST /workflows/validate → 검증
  7. POST /workflows/versions/{id}/publish → 발행

[챗봇 대화]
  1. POST /chat → 메시지 전송
     ↓
  2. [백엔드 워크플로우 실행]
     ↓
  3. ← 응답 수신 (response, run_id)

[실행 이력]
  1. GET /workflows/runs → 실행 목록
  2. [사용자가 특정 실행 선택]
  3. GET /workflows/runs/{run_id} → 실행 상세
  4. GET /workflows/runs/{run_id}/nodes → 노드 실행 목록
  5. [사용자가 노드 상세 클릭]
  6. GET /workflows/runs/{run_id}/nodes/{node_id} → 노드 상세

┌─────────────────────────────────────────────────────────────────┐
│                         백엔드                                    │
└─────────────────────────────────────────────────────────────────┘

[워크플로우 편집 API]
  WorkflowVersionService
  ├─ create_or_update_draft() → DB에 저장
  ├─ publish_draft() → 버전 생성 + Bot 활성화
  └─ list_versions() → 버전 목록 반환

[워크플로우 검증]
  WorkflowValidatorV2
  ├─ has_start_node()
  ├─ has_end_node()
  ├─ detect_cycles()
  ├─ validate_connections()
  └─ check_type_compatibility()

[챗봇 실행]
  ChatService
  ├─ process_message()
  │   ├─ V2 활성화? → _execute_workflow_v2()
  │   ├─ 기존 워크플로우? → _execute_workflow_legacy()
  │   └─ 없음? → _execute_simple_rag()
  │
  └─ _execute_workflow_v2()
      ├─ get_published_workflow() → 발행된 버전 조회
      ├─ create_execution_run() → 실행 기록 시작
      ├─ WorkflowExecutor.execute()
      │   ├─ [각 노드 실행]
      │   ├─ create_node_execution() → 노드 기록 시작
      │   ├─ node.execute(inputs, services)
      │   └─ complete_node_execution() → 노드 기록 완료
      └─ complete_execution_run() → 실행 기록 완료

[실행 이력 API]
  WorkflowExecutionService
  ├─ list_runs() → 페이지네이션 + 필터
  ├─ get_run() → 실행 상세
  ├─ get_node_executions() → 노드 실행 목록
  └─ get_node_execution_detail() → 노드 상세 + Presigned URL

┌─────────────────────────────────────────────────────────────────┐
│                       데이터베이스                                 │
└─────────────────────────────────────────────────────────────────┘

bots
├─ use_workflow_v2 (V2 활성화 여부)
└─ legacy_workflow (백업)

bot_workflow_versions
├─ version ("draft" or "v1.0", "v1.1", ...)
├─ status (draft/published/archived)
├─ graph (JSONB: nodes + edges)
└─ environment_variables

workflow_execution_runs
├─ workflow_version_id (실행 시점 버전)
├─ graph_snapshot (재현용 스냅샷)
├─ inputs, outputs
├─ status, elapsed_time, total_tokens
└─ [1:N] → workflow_node_executions

workflow_node_executions
├─ node_id, node_type
├─ inputs, outputs (미리보기 or 전체)
├─ is_truncated, truncated_fields
└─ status, elapsed_time, tokens_used
```

---

## 5. 주요 시나리오별 흐름 요약

### 시나리오 1: 새 봇 생성 후 워크플로우 편집

1. **봇 생성**: `POST /bots` → 기본 Draft 자동 생성 (BotService)
2. **편집기 진입**: `GET /workflows/versions?status=draft` → Draft 로드
3. **노드 타입 조회**: `GET /workflows/node-types` → 팔레트 표시
4. **편집**: 노드 추가/연결 → 30초마다 `POST /workflows/versions/draft`
5. **검증**: `POST /workflows/validate` → 에러 확인
6. **발행**: `POST /workflows/versions/{id}/publish` → v1.0 생성, use_workflow_v2=true

### 시나리오 2: 기존 워크플로우 수정 후 재발행

1. **편집기 진입**: `GET /workflows/versions?status=draft` → 기존 Draft 로드
2. **편집**: 노드 수정 → 자동 저장
3. **발행**: `POST /workflows/versions/{draft_id}/publish` → v1.1 생성
4. **새 Draft 자동 생성**: v1.1 기반으로 새 Draft 생성 (다음 편집용)

### 시나리오 3: 챗봇 대화 및 디버깅

1. **메시지 전송**: `POST /chat` → ChatService.process_message()
2. **워크플로우 실행**:
   - WorkflowExecutionRun 생성 (status=running)
   - 각 노드 실행 시 WorkflowNodeExecution 생성
   - 노드별 inputs/outputs 저장 (100KB 초과 시 S3 오프로드)
   - 실행 완료 시 WorkflowExecutionRun 업데이트 (status=succeeded)
3. **디버깅**: `GET /workflows/runs/{run_id}` → 실행 상세 확인
4. **노드 분석**: `GET /workflows/runs/{run_id}/nodes/{node_id}` → 노드 입출력 확인

### 시나리오 4: 실행 이력 분석

1. **목록 조회**: `GET /workflows/runs?status=failed` → 실패한 실행만 필터
2. **상세 분석**: `GET /workflows/runs/{run_id}` → 그래프 스냅샷, 에러 메시지 확인
3. **문제 노드 식별**: `GET /workflows/runs/{run_id}/nodes` → 어느 노드에서 실패했는지
4. **입출력 확인**: `GET /workflows/runs/{run_id}/nodes/{node_id}` → 실패 원인 파악

---

## 6. 데이터 흐름 상세

### 워크플로우 그래프 데이터 구조

```typescript
// 프론트엔드 → 백엔드
interface WorkflowGraph {
  nodes: Array<{
    id: string;
    type: "start" | "knowledge" | "llm" | "end" | "condition" | "loop";
    position: { x: number; y: number };
    data: Record<string, any>;  // 노드별 설정
    ports: {
      inputs: PortDefinition[];
      outputs: PortDefinition[];
    };
    variable_mappings: Record<string, VariableMapping>;
  }>;
  edges: Array<{
    id: string;
    source: string;
    target: string;
    source_port: string;
    target_port: string;
    data_type: "string" | "number" | "array" | "object" | "any";
  }>;
}

// 백엔드 저장 (JSONB)
{
  "nodes": [...],
  "edges": [...]
}
```

### 실행 데이터 흐름

```
사용자 입력 → WorkflowExecutionRun.inputs
   ↓
Start 노드 실행
   ↓
VariablePool.set_node_output("start_1", "user_message", "...")
   ↓
Knowledge 노드 실행
   - inputs: {"query": VariablePool.get("start_1", "user_message")}
   - outputs: {"documents": [...], "context": "..."}
   ↓
VariablePool.set_node_output("knowledge_1", "documents", [...])
VariablePool.set_node_output("knowledge_1", "context", "...")
   ↓
LLM 노드 실행
   - inputs: {
       "user_message": VariablePool.get("start_1", "user_message"),
       "context": VariablePool.get("knowledge_1", "context")
     }
   - outputs: {"response": "..."}
   ↓
VariablePool.set_node_output("llm_1", "response", "...")
   ↓
End 노드 실행
   - inputs: {"response": VariablePool.get("llm_1", "response")}
   - outputs: {"final_output": "..."}
   ↓
WorkflowExecutionRun.outputs = {"final_output": "..."}
```

---

## 결론

이 플로우 문서는 리팩토링된 워크플로우 V2 시스템에서 프론트엔드와 백엔드가 어떻게 상호작용하는지 상세히 설명합니다:

✅ **편집 플로우**: Draft 관리, 자동 저장, 검증, 발행
✅ **실행 플로우**: 포트 기반 데이터 흐름, 노드별 기록 저장
✅ **이력 플로우**: 실행 목록 조회, 노드별 디버깅

각 API 엔드포인트의 요청/응답 예시와 함께 백엔드 내부 처리 로직도 포함되어 있어, 프론트엔드 개발자와 백엔드 개발자 모두 전체 시스템을 이해하고 구현할 수 있습니다.
