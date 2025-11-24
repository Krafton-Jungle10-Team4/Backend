"""
워크플로우 V2 실행 엔진

포트 기반 데이터 흐름과 변수 풀을 사용하는 V2 실행 엔진입니다.
"""

import asyncio
from typing import Dict, List, Any, Optional, Callable
from collections import deque, defaultdict
from app.core.workflow.base_node_v2 import BaseNodeV2, NodeExecutionContext
from app.core.workflow.variable_pool import VariablePool
from app.core.workflow.service_container import ServiceContainer
from app.core.workflow.node_registry_v2 import node_registry_v2
from app.core.workflow.validator import WorkflowValidator
from app.core.workflow.base_node import NodeStatus
from app.services.vector_service import VectorService
from app.services.llm_service import LLMService
from app.models.workflow_version import WorkflowExecutionRun, WorkflowNodeExecution
from app.models.conversation_variable import ConversationVariable
from app.config import settings
from app.services.event_publisher import WorkflowEventPublisher
import logging
from datetime import datetime
import uuid
from sqlalchemy import select

logger = logging.getLogger(__name__)


class WorkflowExecutorV2:
    """
    워크플로우 V2 실행 엔진

    포트 기반 데이터 흐름을 지원하는 V2 노드들을 실행합니다.
    """

    def __init__(self):
        """실행 엔진 초기화"""
        self.validator = WorkflowValidator()
        self.nodes: Dict[str, BaseNodeV2] = {}
        self.edges: List[Dict[str, Any]] = []
        self.execution_order: List[str] = []
        self.variable_pool: Optional[VariablePool] = None
        self.service_container: Optional[ServiceContainer] = None
        self.execution_run: Optional[WorkflowExecutionRun] = None
        self.run_start_time: Optional[datetime] = None
        self.workflow_version_id: Optional[str] = None
        # 노드 실행 기록을 메모리에 저장 (비동기 컨텍스트 문제 방지)
        self._node_executions_cache: List[WorkflowNodeExecution] = []
        self._virtual_node_aliases = {"conv", "conversation", "env", "environment", "sys", "system"}
        self.cancel_event: Optional[asyncio.Event] = None
        self._event_publisher = WorkflowEventPublisher()
        self._use_async_logs = bool(settings.log_queue_url)

    def _is_virtual_node(self, node_id: Optional[str]) -> bool:
        if not node_id:
            return False
        return str(node_id).lower() in self._virtual_node_aliases

    async def execute(
        self,
        workflow_data: Dict[str, Any],
        session_id: str,
        user_message: str,
        bot_id: str,
        user_uuid: str,
        db: Any,
        vector_service: Optional[VectorService] = None,
        llm_service: Optional[LLMService] = None,
        stream_handler: Optional[Any] = None,
        text_normalizer: Optional[Callable[[str], str]] = None,
        initial_node_outputs: Optional[Dict[str, Dict[str, Any]]] = None,
        api_key_id: Optional[str] = None,
        user_id: Optional[str] = None,
        api_request_id: Optional[str] = None,
        cancel_event: Optional[asyncio.Event] = None
    ) -> str:
        """
        V2 워크플로우 실행

        Args:
            workflow_data: 워크플로우 정의
            session_id: 세션 ID
            user_message: 사용자 메시지
            bot_id: 봇 ID
            db: 데이터베이스 세션
            vector_service: 벡터 서비스
            llm_service: LLM 서비스
            stream_handler: 스트림 핸들러
            text_normalizer: 텍스트 정규화 함수
            initial_node_outputs: 특정 노드/포트에 미리 주입할 값 (nested execution용)
            api_key_id: API 키 ID (RESTful API 호출 시)
            user_id: 최종 사용자 ID (RESTful API 호출 시)
            api_request_id: API 요청 ID (추적용)
            cancel_event: 실행 중단 신호

        Returns:
            str: 최종 응답

        Raises:
            ValueError: 워크플로우 검증 실패 시
            RuntimeError: 실행 중 오류 발생 시
        """
        try:
            # 워크플로우 검증
            nodes_data = workflow_data.get("nodes", [])
            edges_data = workflow_data.get("edges", [])

            is_valid, errors, warnings = self.validator.validate(nodes_data, edges_data)
            if not is_valid:
                error_msg = "\n".join(errors)
                raise ValueError(f"V2 워크플로우 검증 실패: {error_msg}")

            if warnings:
                for warning in warnings:
                    logger.warning(f"V2 워크플로우 경고: {warning}")

            self.workflow_version_id = workflow_data.get("workflow_version_id")
            self.cancel_event = cancel_event

            # 변수 풀 초기화
            environment_vars = workflow_data.get("environment_variables", {})
            conversation_vars = workflow_data.get("conversation_variables", {}) or {}
            persisted_conversation_vars = await self._load_conversation_variables(
                db=db,
                session_id=session_id,
                bot_id=bot_id
            )
            merged_conversation_vars = {**conversation_vars, **persisted_conversation_vars}

            self.variable_pool = VariablePool(
                environment_variables=environment_vars,
                conversation_variables=merged_conversation_vars
            )

            # 초기 노드 출력 주입 (nested execution 등)
            if initial_node_outputs:
                for node_id, ports in initial_node_outputs.items():
                    if not node_id or not isinstance(ports, dict):
                        continue
                    for port_name, value in ports.items():
                        if port_name:
                            self.variable_pool.set_node_output(node_id, port_name, value)

            # 시스템 변수 설정
            self.variable_pool.set_system_variable("user_message", user_message)
            self.variable_pool.set_system_variable("session_id", session_id)
            self.variable_pool.set_system_variable("bot_id", bot_id)

            # 서비스 컨테이너 초기화
            self.service_container = ServiceContainer()
            self.service_container.register("vector_service", vector_service)
            self.service_container.register("llm_service", llm_service)
            self.service_container.register("bot_id", bot_id)
            self.service_container.register("user_uuid", user_uuid)
            self.service_container.register("session_id", session_id)
            self.service_container.register("db_session", db)
            self.service_container.register("stream_handler", stream_handler)
            self.service_container.register("text_normalizer", text_normalizer)

            # API 메타데이터 등록 (중첩 워크플로우에서 접근 가능)
            if api_key_id:
                self.service_container.register("api_key_id", api_key_id)
            if user_id:
                self.service_container.register("user_id", user_id)
            if api_request_id:
                self.service_container.register("api_request_id", api_request_id)

            logger.debug(
                f"ServiceContainer initialized with services: {self.service_container.list_services()}"
            )

            # V2 노드 인스턴스 생성
            self._create_v2_nodes(nodes_data, edges_data)
            self.edges = edges_data

            # 실행 순서 결정
            self.execution_order = self.validator.get_execution_order(nodes_data, edges_data)
            if not self.execution_order:
                raise ValueError("V2 워크플로우 실행 순서를 결정할 수 없습니다")

            logger.info(f"V2 워크플로우 실행 순서: {self.execution_order}")

            # 실행 기록 시작
            self.run_start_time = datetime.utcnow()
            await self._create_execution_run(
                workflow_data=workflow_data,
                session_id=session_id,
                bot_id=bot_id,
                user_message=user_message,
                db=db,
                workflow_version_id=self.workflow_version_id,
                api_key_id=api_key_id,
                user_id=user_id,
                api_request_id=api_request_id
            )

            # 노드 실행
            final_response = await self._execute_v2_nodes(stream_handler, text_normalizer, db)

            # 대화 변수 저장
            try:
                await self._persist_conversation_variables(
                    db=db,
                    bot_id=bot_id,
                    session_id=session_id
                )
            except Exception as persist_error:
                logger.error(
                    "Failed to persist conversation variables: %s",
                    persist_error
                )

            # 실행 기록 완료
            await self._finalize_execution_run(
                status="succeeded",
                final_response=final_response,
                db=db
            )

            return final_response

        except asyncio.CancelledError:
            logger.info("V2 워크플로우 실행이 취소되었습니다.")
            if self.execution_run:
                await self._finalize_execution_run(
                    status="failed",
                    error_message="Cancelled by client",
                    db=db
                )
            raise

        except Exception as e:
            logger.error(f"V2 워크플로우 실행 실패: {str(e)}")

            # 실행 기록 실패 처리
            if self.execution_run:
                await self._finalize_execution_run(
                    status="failed",
                    error_message=str(e),
                    db=db
                )

            raise RuntimeError(f"V2 워크플로우 실행 실패: {str(e)}")

    def _create_v2_nodes(self, nodes_data: List[Dict], edges_data: List[Dict]):
        """
        V2 노드 인스턴스 생성

        Args:
            nodes_data: 노드 데이터
            edges_data: 엣지 데이터
        """
        self.nodes = {}

        # 노드 생성
        for node_data in nodes_data:
            node_id = node_data.get("id")
            node_type = node_data.get("type")
            config_data = node_data.get("data", {})
            variable_mappings = node_data.get("variable_mappings", {})

            try:
                # V2 노드 인스턴스 생성
                node = node_registry_v2.create_node(
                    node_type=node_type,
                    node_id=node_id,
                    config=config_data,
                    variable_mappings=variable_mappings
                )

                self.nodes[node_id] = node
                logger.debug(f"Created V2 node: {node_id} ({node_type})")

            except Exception as e:
                logger.error(f"V2 노드 생성 실패 ({node_id}): {str(e)}")
                raise ValueError(f"V2 노드 생성 실패 ({node_id}): {str(e)}")

    async def _execute_v2_nodes(
        self,
        stream_handler: Optional[Any] = None,
        text_normalizer: Optional[Callable[[str], str]] = None,
        db: Any = None
    ) -> str:
        """
        V2 노드들을 순서대로 실행

        Args:
            stream_handler: 스트림 핸들러
            text_normalizer: 텍스트 정규화 함수

        Returns:
            str: 최종 응답
        """
        final_response = None

        incoming_counts = self._build_incoming_counts()
        edges_by_source = self._group_edges_by_source()
        ready_queue: deque[str] = deque()
        executed_nodes: set[str] = set()

        # 디버그: incoming_counts 로깅
        logger.info(f"📊 Initial incoming_counts: {incoming_counts}")
        logger.info(f"📊 Edges by source (keys): {list(edges_by_source.keys())}")
        logger.info(f"📊 Total edges: {sum(len(v) for v in edges_by_source.values())}")
        
        # 디버그: 각 노드의 엣지 정보 상세 출력
        for source, edges in edges_by_source.items():
            edge_details = []
            for edge in edges:
                target = edge.get("target")
                source_port = edge.get("source_port", "default")
                target_port = edge.get("target_port", "")
                edge_details.append(f"{target}[{source_port}→{target_port}]")
            logger.info(f"    {source} → {', '.join(edge_details)}")

        for node_id in self.execution_order:
            count = incoming_counts.get(node_id, 0)
            if count == 0:
                ready_queue.append(node_id)
                logger.info(f"✅ Node {node_id} added to initial ready_queue (incoming_count=0)")
            else:
                logger.info(f"⏳ Node {node_id} waiting (incoming_count={count})")
        
        logger.info(f"📊 Initial ready_queue: {list(ready_queue)} (size={len(ready_queue)})")

        while ready_queue:
            if self.cancel_event and self.cancel_event.is_set():
                logger.info("🛑 Cancellation requested before processing next node.")
                raise asyncio.CancelledError()

            node_id = ready_queue.popleft()
            
            # 중복 실행 방지 강화: 실행 전에 체크하고 즉시 추가 (낙관적 잠금)
            if node_id in executed_nodes:
                logger.warning(f"노드 {node_id}는 이미 실행되었습니다. 스킵합니다.")
                continue
            
            # 실행 시작 전 executed_nodes에 추가 (중복 실행 방지)
            executed_nodes.add(node_id)

            node = self.nodes.get(node_id)
            if not node:
                logger.warning(f"V2 노드 {node_id}를 찾을 수 없습니다")
                executed_nodes.discard(node_id)  # 실행 실패 시 제거 (재시도 가능하도록)
                continue

            node_start_time = datetime.utcnow()

            try:
                logger.info(f"V2 노드 실행 중: {node_id} ({node.__class__.__name__})")

                if stream_handler:
                    await stream_handler.emit_node_event(
                        node_id=node_id,
                        node_type=node.__class__.__name__,
                        status=NodeStatus.RUNNING.value,
                        message=f"V2 node started"
                    )

                # 입력 준비
                prepared_inputs = self._gather_node_inputs(node)

                # 실행 컨텍스트 생성 (실행된 노드 목록 전달)
                context = NodeExecutionContext(
                    node_id=node_id,
                    variable_pool=self.variable_pool,
                    service_container=self.service_container,
                    metadata={"prepared_inputs": prepared_inputs},
                    executed_nodes=list(executed_nodes)  # 현재까지의 실행 경로 전달
                )

                # 노드 실행
                result = await node.execute(context)
                edge_handles = result.metadata.get("edge_handles", []) if result.metadata else []
                process_data = self._extract_process_data(context, node_id)

                # 결과 처리
                if result.status == NodeStatus.COMPLETED and result.output:
                    # 출력은 이미 variable_pool에 저장됨 (BaseNodeV2.execute()에서)

                    # End 노드의 경우 최종 응답 추출
                    if node.__class__.__name__ == "EndNodeV2":
                        final_output = result.output.get("final_output", {})
                        final_response = final_output.get("response", final_response)

                logger.info(f"V2 노드 {node_id} 실행 완료 (status={result.status.value})")

                if stream_handler:
                    output_preview = self._summarize_output(result.output, text_normalizer)
                    await stream_handler.emit_node_event(
                        node_id=node_id,
                        node_type=node.__class__.__name__,
                        status=result.status.value,
                        message="V2 node completed" if result.status == NodeStatus.COMPLETED else "V2 node finished",
                        output_preview=output_preview,
                        metadata=process_data
                    )

                # 노드 실행 기록 저장
                node_end_time = datetime.utcnow()
                execution_metadata = None
                if context and context.metadata:
                    answer_meta = context.metadata.get("answer")
                    if isinstance(answer_meta, dict):
                        execution_metadata = answer_meta.get(node_id)
                await self._create_node_execution(
                    node_id=node_id,
                    node_type=node.__class__.__name__,
                    execution_order=self.execution_order.index(node_id),
                    inputs=prepared_inputs,
                    outputs=result.output,
                    status=result.status.value,
                    error_message=result.error,
                    started_at=node_start_time,
                    finished_at=node_end_time,
                    db=db,
                    execution_metadata=execution_metadata,
                    process_data=process_data
                )

                context.metadata.clear()

                if result.status == NodeStatus.FAILED:
                    raise RuntimeError(result.error or f"V2 Node {node_id} failed")
                all_edges_for_node = edges_by_source.get(node_id, [])
                outgoing_edges = self._select_outgoing_edges(
                    all_edges_for_node,
                    edge_handles
                )
                
                # 🔥 핵심 수정: 분기 노드 처리 (IfElse, QuestionClassifier 등)
                # 선택되지 않은 분기의 다운스트림 노드 의존성 해소
                if edge_handles and all_edges_for_node:
                    unselected_edges = self._get_unselected_edges(
                        all_edges_for_node,
                        edge_handles
                    )
                    if unselected_edges:
                        logger.info(
                            "🔀 Branch node %s: resolving unselected branches (%d edges)",
                            node_id,
                            len(unselected_edges)
                        )
                        self._resolve_unselected_branch_dependencies(
                            unselected_edges,
                            incoming_counts,
                            ready_queue,
                            executed_nodes
                        )
                
                # 상세한 엣지 매칭 로그
                logger.info(
                    "🔗 Node %s executed:\n"
                    "  - edge_handles: %s\n"
                    "  - total_edges: %d\n"
                    "  - selected_edges: %d\n"
                    "  - current ready_queue size: %d",
                    node_id,
                    edge_handles,
                    len(all_edges_for_node),
                    len(outgoing_edges),
                    len(ready_queue)
                )
                
                # 엣지 매칭 상세 정보
                if all_edges_for_node and not outgoing_edges and edge_handles:
                    logger.warning(
                        "⚠️  Node %s: edge_handles=%s but no edges matched! Available source_ports: %s",
                        node_id,
                        edge_handles,
                        [e.get("source_port") for e in all_edges_for_node]
                    )
                for edge in outgoing_edges:
                    target = edge.get("target")
                    source_port = edge.get("source_port", "default")
                    target_port = edge.get("target_port", "")
                    logger.info(f"  → Processing edge: {node_id}[{source_port}] -> {target}[{target_port}]")
                    if self._is_virtual_node(target) or target not in self.nodes:
                        logger.debug(f"  ⏭️  Skipping edge to {target} (virtual or not in nodes)")
                        continue
                    previous_count = incoming_counts.get(target, 0)
                    incoming_counts[target] = max(previous_count - 1, 0)
                    logger.info(
                        "  ✅ Edge %s -> %s resolved: incoming_count %d -> %d",
                        node_id,
                        target,
                        previous_count,
                        incoming_counts[target]
                    )
                    if incoming_counts[target] == 0:
                        ready_queue.append(target)
                        logger.info("  🎯 Node %s added to ready_queue (all dependencies resolved)", target)
                    else:
                        logger.info(f"  ⏳ Node {target} still waiting ({incoming_counts[target]} dependencies remaining)")
                
                # 루프 끝에서 현재 상태 요약
                waiting_nodes = {k: v for k, v in incoming_counts.items() if v > 0 and k not in executed_nodes}
                logger.info(
                    "📊 After node %s: ready_queue=%s, waiting_nodes=%s, executed=%d/%d",
                    node_id,
                    list(ready_queue),
                    waiting_nodes,
                    len(executed_nodes),
                    len(self.nodes)
                )

            except asyncio.CancelledError:
                logger.info(f"🛑 Node execution cancelled: {node_id}")
                raise

            except Exception as e:
                logger.error(f"V2 노드 {node_id} 실행 실패: {str(e)}")
                node.set_status(NodeStatus.FAILED)

                # 실패한 노드 기록 저장
                node_end_time = datetime.utcnow()
                execution_metadata = None
                process_data = None
                if 'context' in locals() and context and context.metadata:
                    answer_meta = context.metadata.get("answer")
                    if isinstance(answer_meta, dict):
                        execution_metadata = answer_meta.get(node_id)
                    process_data = self._extract_process_data(context, node_id)
                await self._create_node_execution(
                    node_id=node_id,
                    node_type=node.__class__.__name__,
                    execution_order=self.execution_order.index(node_id),
                    inputs=prepared_inputs if 'prepared_inputs' in locals() else {},
                    outputs={},
                    status=NodeStatus.FAILED.value,
                    error_message=str(e),
                    started_at=node_start_time,
                    finished_at=node_end_time,
                    db=db,
                    execution_metadata=execution_metadata,
                    process_data=process_data
                )
                
                # 실패 시 executed_nodes에서 제거하지 않음 (이미 실행된 것으로 간주)
                # 하지만 예외를 다시 발생시켜 워크플로우 실행 중단

                if stream_handler:
                    await stream_handler.emit_node_event(
                        node_id=node_id,
                        node_type=node.__class__.__name__,
                        status=NodeStatus.FAILED.value,
                        message=str(e),
                        metadata=process_data
                    )
                if 'context' in locals() and context:
                    context.metadata.clear()
                raise

        # 워크플로우 실행 완료 후 미실행 노드 확인
        unexecuted_nodes = set(self.nodes.keys()) - executed_nodes
        if unexecuted_nodes:
            logger.warning(
                "⚠️  Workflow completed but some nodes were not executed:\n"
                "  - executed: %d/%d nodes\n"
                "  - unexecuted nodes: %s\n"
                "  - final incoming_counts: %s",
                len(executed_nodes),
                len(self.nodes),
                list(unexecuted_nodes),
                {k: v for k, v in incoming_counts.items() if k in unexecuted_nodes}
            )
        else:
            logger.info(f"✅ All {len(executed_nodes)} nodes executed successfully")

        # 최종 응답이 없으면 실행된 LLM 노드의 response를 찾아서 사용
        if not final_response:
            logger.info("End 노드에서 최종 응답을 찾지 못했습니다. LLM 노드의 response를 찾는 중...")
            for node_id in executed_nodes:
                node = self.nodes.get(node_id)
                if node and node.__class__.__name__ == "LLMNodeV2":
                    llm_outputs = self.variable_pool.get_all_node_outputs(node_id)
                    if llm_outputs and "response" in llm_outputs:
                        final_response = llm_outputs["response"]
                        logger.info(f"✅ LLM 노드 {node_id}의 response를 최종 응답으로 사용: {len(final_response)} chars")
                        break
        
        # 여전히 없으면 에러
        if not final_response:
            logger.error(
                "❌ 최종 응답을 찾을 수 없습니다! "
                "End 노드가 실행되지 않았거나, LLM 노드의 response가 없습니다. "
                "실행된 노드: %s",
                list(executed_nodes)
            )
            final_response = ""  # 빈 문자열 반환 (기본 메시지 제거)

        return final_response

    async def _load_conversation_variables(
        self,
        db: Any,
        session_id: str,
        bot_id: str,
    ) -> Dict[str, Any]:
        """DB에서 대화 변수 로드"""
        if not db or not session_id:
            return {}

        stmt = (
            select(ConversationVariable)
            .where(ConversationVariable.conversation_id == session_id)
            .where(ConversationVariable.bot_id == bot_id)
        )
        result = await db.execute(stmt)
        records = result.scalars().all()
        return {record.key: record.value for record in records}

    async def _persist_conversation_variables(
        self,
        db: Any,
        bot_id: str,
        session_id: str,
    ) -> None:
        """변경된 대화 변수를 DB에 저장"""
        if not db or not self.variable_pool or not session_id:
            return

        dirty_vars = self.variable_pool.get_dirty_conversation_variables()
        if not dirty_vars:
            return

        for key, value in dirty_vars.items():
            stmt = (
                select(ConversationVariable)
                .where(ConversationVariable.conversation_id == session_id)
                .where(ConversationVariable.bot_id == bot_id)
                .where(ConversationVariable.key == key)
            )
            result = await db.execute(stmt)
            record = result.scalar_one_or_none()

            if record:
                record.value = value
                record.updated_at = datetime.utcnow()
            else:
                db.add(
                    ConversationVariable(
                        conversation_id=session_id,
                        bot_id=bot_id,
                        key=key,
                        value=value,
                    )
                )

        await db.flush()
        self.variable_pool.clear_conversation_variable_dirty()

    def _build_incoming_counts(self) -> Dict[str, int]:
        """의존성 카운트 계산 (가상 노드 엣지 제외)"""
        counts: Dict[str, int] = {node_id: 0 for node_id in self.nodes.keys()}
        
        # 디버그: Start 노드 찾기
        start_nodes = [nid for nid, node in self.nodes.items() 
                       if node.__class__.__name__ == 'StartNodeV2']
        
        logger.info(f"🔍 Building incoming_counts from {len(self.edges)} edges...")
        virtual_edges = 0
        invalid_edges = 0
        valid_edges = 0
        start_bypass_count = 0  # Start 노드가 조건 분기를 우회한 잘못된 연결
        
        for edge in self.edges:
            source = edge.get("source")
            target = edge.get("target")
            source_port = edge.get("source_port", "")
            target_port = edge.get("target_port", "")
            
            if self._is_virtual_node(source) or self._is_virtual_node(target):
                virtual_edges += 1
                logger.debug(f"  ⏭️  Skipping virtual edge: {source}[{source_port}] -> {target}[{target_port}]")
                continue
            
            # Start 노드의 잘못된 연결 감지
            if source in start_nodes and target in self.nodes:
                target_node = self.nodes[target]
                target_type = target_node.__class__.__name__
                
                # Start가 조건 분기 노드가 아닌 노드에 직접 연결된 경우
                if target_type not in ['IfElseNodeV2', 'QuestionClassifierNodeV2']:
                    # 해당 노드가 다른 노드로부터도 incoming 엣지를 받는지 확인
                    other_incoming = sum(
                        1 for e in self.edges 
                        if e.get("target") == target and e.get("source") != source and e.get("source") in self.nodes
                    )
                    
                    if other_incoming > 0:
                        start_bypass_count += 1
                        logger.warning(
                            f"  ⚠️  SUSPICIOUS START EDGE: {source}[{source_port}] → {target}[{target_port}] "
                            f"(target type: {target_type}, other_incoming: {other_incoming}). "
                            f"This may bypass branching logic!"
                        )
            
            if source in self.nodes and target in self.nodes:
                counts[target] = counts.get(target, 0) + 1
                counts.setdefault(source, counts.get(source, 0))
                valid_edges += 1
                logger.debug(f"  ✅ Edge {source} -> {target}: incoming_count[{target}] = {counts[target]}")
            else:
                invalid_edges += 1
                missing = []
                if source not in self.nodes:
                    missing.append(f"source '{source}'")
                if target not in self.nodes:
                    missing.append(f"target '{target}'")
                logger.warning(f"  ⚠️  Invalid edge {source} -> {target}: {', '.join(missing)} not in nodes")
        
        logger.info(
            f"🔍 Edge processing summary: valid={valid_edges}, virtual={virtual_edges}, invalid={invalid_edges}"
        )
        
        if start_bypass_count > 0:
            logger.warning(
                f"⚠️  Found {start_bypass_count} suspicious Start node connections that may "
                f"bypass branching logic. This is likely a frontend workflow editor issue."
            )
        
        return counts

    def _group_edges_by_source(self) -> Dict[str, List[Dict[str, Any]]]:
        mapping: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for edge in self.edges:
            source = edge.get("source")
            target = edge.get("target")
            if self._is_virtual_node(source) or self._is_virtual_node(target):
                continue
            if source in self.nodes and target in self.nodes:
                mapping[source].append(edge)
        return mapping

    def _select_outgoing_edges(
        self,
        edges: List[Dict[str, Any]],
        handles: Optional[List[str]]
    ) -> List[Dict[str, Any]]:
        if not edges:
            return []
        if not handles:
            return edges

        normalized = [handle for handle in handles if handle]
        if not normalized:
            return edges

        selected = [edge for edge in edges if edge.get("source_port") in normalized]
        if selected:
            return selected
        return edges

    def _get_unselected_edges(
        self,
        edges: List[Dict[str, Any]],
        selected_handles: List[str]
    ) -> List[Dict[str, Any]]:
        """
        선택되지 않은 분기의 엣지들을 반환
        
        Args:
            edges: 노드의 모든 outgoing 엣지
            selected_handles: 선택된 분기의 핸들 (예: ['if'])
            
        Returns:
            선택되지 않은 분기의 엣지 리스트
        """
        if not edges or not selected_handles:
            return []
        
        # selected_handles에 포함되지 않은 엣지들만 반환
        unselected = [
            edge for edge in edges 
            if edge.get("source_port") and edge.get("source_port") not in selected_handles
        ]
        
        return unselected

    def _resolve_unselected_branch_dependencies(
        self,
        unselected_edges: List[Dict[str, Any]],
        incoming_counts: Dict[str, int],
        ready_queue: deque,
        executed_nodes: set
    ) -> None:
        """
        선택되지 않은 분기의 다운스트림 노드들의 의존성을 재귀적으로 해소
        
        ⚠️ 중요: 이 메서드는 노드를 ready_queue에 추가하지 않고,
        incoming_count만 감소시킵니다. 노드를 실행하려면 다른 경로를 통해
        incoming_count가 0이 되어야 합니다.
        
        Args:
            unselected_edges: 선택되지 않은 분기의 엣지들
            incoming_counts: 노드별 남은 의존성 카운트
            ready_queue: 실행 대기 큐
            executed_nodes: 이미 실행된 노드 집합
        """
        # 처리할 노드들 (BFS 방식)
        nodes_to_process: deque = deque()
        processed: set = set()
        
        # 선택되지 않은 분기의 직접 타겟 노드들을 큐에 추가
        for edge in unselected_edges:
            target = edge.get("target")
            if target and not self._is_virtual_node(target) and target in self.nodes:
                nodes_to_process.append(target)
                logger.debug(f"    ⏭️  Marking unselected branch target: {target}")
        
        # BFS로 다운스트림 노드들의 의존성 해소
        edges_by_source = self._group_edges_by_source()
        
        while nodes_to_process:
            current_node = nodes_to_process.popleft()
            
            # 이미 처리했거나 실행된 노드는 스킵
            if current_node in processed or current_node in executed_nodes:
                continue
            
            processed.add(current_node)
            
            # 이 노드의 incoming_count를 0으로 설정
            # (선택되지 않은 분기의 노드이므로 실행되지 않음)
            old_count = incoming_counts.get(current_node, 0)
            if old_count > 0:
                incoming_counts[current_node] = 0
                logger.info(
                    f"    🔀 Unselected branch node {current_node}: "
                    f"incoming_count {old_count} -> 0 (branch not taken, will NOT be added to ready_queue)"
                )
            
            # ⚠️ 중요: ready_queue에 추가하지 않음!
            # 선택되지 않은 분기의 노드는 실행되어서는 안 됨
            
            # 이 노드의 다운스트림 노드들 처리
            outgoing = edges_by_source.get(current_node, [])
            for edge in outgoing:
                downstream = edge.get("target")
                if not downstream or self._is_virtual_node(downstream) or downstream not in self.nodes:
                    continue
                
                # 다운스트림 노드의 incoming_count 감소
                prev_count = incoming_counts.get(downstream, 0)
                if prev_count > 0:
                    incoming_counts[downstream] = prev_count - 1
                    logger.debug(
                        f"      ⬇️  Downstream {downstream}: "
                        f"incoming_count {prev_count} -> {incoming_counts[downstream]}"
                    )
                    
                    # ⚠️ 변경: ready_queue에 추가하지 않음!
                    # 다른 경로를 통해 incoming_count가 0이 되면 자연스럽게 실행됨
                
                # 이 다운스트림 노드도 처리 대상에 추가
                # (선택되지 않은 분기의 다운스트림일 수 있음)
                if downstream not in processed:
                    nodes_to_process.append(downstream)

    @staticmethod
    def _extract_process_data(context: Optional[NodeExecutionContext], node_id: str) -> Optional[Dict[str, Any]]:
        if not context or not context.metadata:
            return None
        data: Dict[str, Any] = {}
        for key, value in context.metadata.items():
            if isinstance(value, dict) and node_id in value:
                data[key] = value[node_id]
            elif key == node_id:
                data[key] = value
        return data or None

    def _gather_node_inputs(self, node: BaseNodeV2) -> Dict[str, Any]:
        """
        노드의 입력 포트 값들을 수집

        Args:
            node: V2 노드

        Returns:
            Dict[str, Any]: {port_name: value} 형식의 입력
        """
        prepared_inputs = {}

        # variable_mappings에서 각 입력 포트의 소스를 찾아 해석
        for port_name, mapping in node.variable_mappings.items():
            # mapping은 ValueSelector 형식 또는 직접 변수 이름
            if isinstance(mapping, dict):
                # ValueSelector 객체 형식
                selector = mapping.get("variable") or mapping.get("source", {}).get("variable")
            else:
                # 문자열 형식
                selector = mapping

            if selector:
                try:
                    value = self.variable_pool.resolve_value_selector(selector)
                    prepared_inputs[port_name] = value
                    # 디버그 로깅: LLM 노드의 context 입력에 대해 상세 로깅
                    if node.__class__.__name__ == "LLMNodeV2" and port_name == "context":
                        if value:
                            logger.info(f"[LLMNodeV2] Context input resolved: {len(str(value))} chars from '{selector}'")
                        else:
                            logger.warning(f"[LLMNodeV2] Context input is empty or None from '{selector}'")
                            # conversation.result가 있는지 확인
                            try:
                                result_value = self.variable_pool.resolve_value_selector("conversation.result")
                                if result_value:
                                    logger.info(f"[LLMNodeV2] Found conversation.result: {len(str(result_value))} chars (but context input is empty)")
                                else:
                                    logger.warning(f"[LLMNodeV2] conversation.result is also empty or not found")
                            except Exception as e:
                                logger.debug(f"[LLMNodeV2] Could not check conversation.result: {e}")
                except Exception as e:
                    logger.warning(f"Failed to resolve input '{port_name}' from '{selector}': {e}")
                    prepared_inputs[port_name] = None
            else:
                logger.debug(f"No selector found for input port '{port_name}' in node {node.node_id}")

        # LLM 노드의 경우 variable_mappings에 없는 입력 포트도 확인
        if node.__class__.__name__ == "LLMNodeV2":
            schema = node.get_port_schema()
            for port_def in schema.inputs:
                port_name = port_def.name
                if port_name not in prepared_inputs:
                    logger.debug(f"[LLMNodeV2] Input port '{port_name}' not in variable_mappings")

        return prepared_inputs

    @staticmethod
    def _summarize_output(
        output: Any,
        normalizer: Optional[Callable[[str], str]] = None
    ) -> Optional[str]:
        """노드 출력 요약 문자열 생성"""
        summary: Optional[str] = None

        if isinstance(output, dict):
            # V2 노드의 출력 포트 처리
            if "response" in output:
                summary = output["response"]
            elif "context" in output:
                summary = f"Context prepared ({len(output.get('context', ''))} chars)"
            elif "query" in output:
                summary = output["query"]
            elif "final_output" in output:
                final = output["final_output"]
                if isinstance(final, dict):
                    summary = final.get("response", str(final))
        elif isinstance(output, str):
            summary = output

        if summary and normalizer:
            summary = normalizer(summary)

        if summary:
            return summary[:200]
        return None

    def get_node_status(self, node_id: str) -> Optional[NodeStatus]:
        """
        노드 상태 조회

        Args:
            node_id: 노드 ID

        Returns:
            NodeStatus 또는 None
        """
        node = self.nodes.get(node_id)
        return node.status if node else None

    def get_all_node_statuses(self) -> Dict[str, NodeStatus]:
        """
        모든 노드의 상태 조회

        Returns:
            Dict[str, NodeStatus]: 노드 ID와 상태 맵
        """
        return {node_id: node.status for node_id, node in self.nodes.items()}

    async def _create_execution_run(
        self,
        workflow_data: Dict[str, Any],
        session_id: str,
        bot_id: str,
        user_message: str,
        db: Any,
        workflow_version_id: Optional[str] = None,
        api_key_id: Optional[str] = None,
        user_id: Optional[str] = None,
        api_request_id: Optional[str] = None
    ) -> None:
        """
        워크플로우 실행 기록 생성

        Args:
            workflow_data: 워크플로우 정의
            session_id: 세션 ID
            bot_id: 봇 ID
            user_message: 사용자 메시지
            db: 데이터베이스 세션
            workflow_version_id: 워크플로우 버전 ID
            api_key_id: API 키 ID (RESTful API 호출 시)
            user_id: 최종 사용자 ID (RESTful API 호출 시)
            api_request_id: API 요청 ID (추적용)
        """
        if not db:
            logger.warning("DB 세션이 없어 실행 기록을 저장하지 않습니다")
            return

        try:
            generated_id = uuid.uuid4()
            version_uuid = None
            if workflow_version_id:
                try:
                    version_uuid = uuid.UUID(str(workflow_version_id))
                except (ValueError, TypeError):
                    logger.warning("Invalid workflow_version_id provided: %s", workflow_version_id)

            self.execution_run = WorkflowExecutionRun(
                id=generated_id,
                bot_id=bot_id,
                workflow_version_id=version_uuid,
                session_id=session_id,
                graph_snapshot=workflow_data,
                inputs={"user_message": user_message},
                outputs={},
                status="running",
                started_at=self.run_start_time,
                total_steps=len(self.execution_order),
                # API 전용 필드 설정
                api_key_id=api_key_id,
                user_id=user_id,
                api_request_id=api_request_id
            )

            if self._use_async_logs:
                logger.info(
                    "Async log mode enabled. Execution run staged for SQS publishing: run_id=%s",
                    self.execution_run.id
                )

            db.add(self.execution_run)
            await db.commit()
            logger.info(
                f"V2 워크플로우 실행 기록 생성: run_id={self.execution_run.id}, "
                f"api_key_id={api_key_id}, user_id={user_id}"
            )

        except Exception as e:
            logger.error(f"실행 기록 생성 실패: {str(e)}")
            await db.rollback()

    async def _finalize_execution_run(
        self,
        status: str,
        final_response: Optional[str] = None,
        error_message: Optional[str] = None,
        db: Any = None
    ) -> None:
        """
        워크플로우 실행 기록 완료

        Args:
            status: 실행 상태 (completed, failed)
            final_response: 최종 응답
            error_message: 에러 메시지
            db: 데이터베이스 세션
        """
        if not self.execution_run:
            return

        finished_at = datetime.utcnow()
        elapsed_ms = int((finished_at - self.run_start_time).total_seconds() * 1000)

        self.execution_run.status = status
        self.execution_run.finished_at = finished_at
        self.execution_run.elapsed_time = elapsed_ms

        if final_response:
            self.execution_run.outputs = {"final_response": final_response}

        if error_message:
            self.execution_run.error_message = error_message

        # 토큰 합계 계산 (노드 실행 기록에서)
        total_tokens = sum(
            node_exec.tokens_used or 0
            for node_exec in self._node_executions_cache
        )
        self.execution_run.total_tokens = total_tokens

        if not db:
            if self._use_async_logs:
                await self._publish_log_event()
            return

        try:
            # 노드 실행 기록들은 _create_node_execution에서 add/flush 되므로
            # 여기서는 추가 add 없이 커밋만 수행
            await db.commit()
            logger.info(
                f"V2 워크플로우 실행 완료: run_id={self.execution_run.id}, "
                f"status={status}, elapsed={elapsed_ms}ms"
            )

            if self._use_async_logs:
                await self._publish_log_event()

        except Exception as e:
            logger.error(f"실행 기록 완료 처리 실패: {str(e)}")
            await db.rollback()

    async def _publish_log_event(self) -> None:
        """SQS로 실행 로그 이벤트 발행"""
        if not settings.log_queue_url:
            return

        run = self.execution_run
        if not run:
            return

        run_payload = {
            "id": str(run.id),
            "bot_id": run.bot_id,
            "workflow_version_id": str(run.workflow_version_id) if run.workflow_version_id else None,
            "session_id": run.session_id,
            "graph_snapshot": run.graph_snapshot,
            "inputs": run.inputs,
            "outputs": run.outputs,
            "status": run.status,
            "error_message": run.error_message,
            "started_at": self._datetime_to_iso(run.started_at or self.run_start_time),
            "finished_at": self._datetime_to_iso(run.finished_at),
            "elapsed_time": run.elapsed_time,
            "total_tokens": run.total_tokens,
            "total_steps": run.total_steps,
            "api_key_id": str(run.api_key_id) if getattr(run, "api_key_id", None) else None,
            "user_id": getattr(run, "user_id", None),
            "api_request_id": getattr(run, "api_request_id", None)
        }

        nodes_payload = [
            {
                "id": str(node_exec.id),
                "node_id": node_exec.node_id,
                "node_type": node_exec.node_type,
                "execution_order": node_exec.execution_order,
                "inputs": node_exec.inputs,
                "outputs": node_exec.outputs,
                "process_data": node_exec.process_data,
                "status": node_exec.status,
                "error_message": node_exec.error_message,
                "started_at": self._datetime_to_iso(node_exec.started_at),
                "finished_at": self._datetime_to_iso(node_exec.finished_at),
                "elapsed_time": node_exec.elapsed_time,
                "tokens_used": node_exec.tokens_used,
            }
            for node_exec in self._node_executions_cache
        ]

        payload = {
            "event_type": "workflow.log",
            "timestamp": datetime.utcnow().isoformat(),
            "run": run_payload,
            "nodes": nodes_payload
        }

        try:
            await self._event_publisher.publish_log_event(payload)
            logger.info("워크플로우 실행 로그를 SQS에 발행했습니다. run_id=%s", run_payload["id"])
        except Exception as exc:
            logger.error("워크플로우 로그 이벤트 발행 실패: %s", exc)

    @staticmethod
    def _datetime_to_iso(value: Optional[datetime]) -> Optional[str]:
        if not value:
            return None
        return value.isoformat()

    async def _create_node_execution(
        self,
        node_id: str,
        node_type: str,
        execution_order: int,
        inputs: Dict[str, Any],
        outputs: Dict[str, Any],
        status: str,
        error_message: Optional[str],
        started_at: datetime,
        finished_at: datetime,
        db: Any,
        execution_metadata: Optional[Dict[str, Any]] = None,
        process_data: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        노드 실행 기록 생성 및 즉시 저장

        Args:
            node_id: 노드 ID
            node_type: 노드 타입
            execution_order: 실행 순서
            inputs: 입력 데이터
            outputs: 출력 데이터
            status: 실행 상태
            error_message: 에러 메시지
            started_at: 시작 시간
            finished_at: 종료 시간
            db: 데이터베이스 세션
            execution_metadata: 실행 메타데이터 (Answer 노드 렌더링 정보 등)
        """
        if not self.execution_run or not db:
            return

        try:
            elapsed_ms = int((finished_at - started_at).total_seconds() * 1000)

            # 토큰 사용량 추출 (LLM 노드의 경우)
            tokens_used = 0
            model_used = None
            if node_type == "LLMNodeV2" and outputs:
                tokens_used = outputs.get("tokens", 0)
                model_used = outputs.get("model")
                logger.info(f"[WorkflowExecutorV2] LLM 노드 실행 기록: node_id={node_id}, model={model_used}, tokens={tokens_used}")

            # 출력 데이터에 실행 메타데이터 병합
            final_outputs = outputs.copy() if outputs else {}
            if execution_metadata:
                final_outputs["_execution_metadata"] = execution_metadata

            node_execution = WorkflowNodeExecution(
                id=uuid.uuid4(),
                workflow_run_id=self.execution_run.id,
                node_id=node_id,
                node_type=node_type,
                execution_order=execution_order,
                inputs=inputs,
                outputs=final_outputs,
                process_data=process_data,
                status=status,
                error_message=error_message,
                started_at=started_at,
                finished_at=finished_at,
                elapsed_time=elapsed_ms,
                tokens_used=tokens_used
            )

            # 즉시 DB에 저장 (flush 사용하여 트랜잭션 유지)
            db.add(node_execution)
            await db.flush()  # commit 대신 flush 사용 (트랜잭션 유지, ID 생성 보장)
            
            # 메모리 캐시에도 추가 (최종 커밋 시 토큰 합계 계산용)
            self._node_executions_cache.append(node_execution)

            logger.info(
                f"[WorkflowExecutorV2] 노드 실행 기록 저장: node_id={node_id}, "
                f"node_type={node_type}, status={status}, elapsed={elapsed_ms}ms, "
                f"tokens={tokens_used}, model={model_used if node_type == 'LLMNodeV2' else 'N/A'}"
            )

        except Exception as e:
            logger.error(f"노드 실행 기록 저장 실패: {str(e)}")
            # 실패해도 워크플로우 실행은 계속 진행
