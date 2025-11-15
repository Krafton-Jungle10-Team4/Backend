"""
워크플로우 V2 실행 엔진

포트 기반 데이터 흐름과 변수 풀을 사용하는 V2 실행 엔진입니다.
"""

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

    async def execute(
        self,
        workflow_data: Dict[str, Any],
        session_id: str,
        user_message: str,
        bot_id: str,
        db: Any,
        vector_service: Optional[VectorService] = None,
        llm_service: Optional[LLMService] = None,
        stream_handler: Optional[Any] = None,
        text_normalizer: Optional[Callable[[str], str]] = None
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

            # 시스템 변수 설정
            self.variable_pool.set_system_variable("user_message", user_message)
            self.variable_pool.set_system_variable("session_id", session_id)
            self.variable_pool.set_system_variable("bot_id", bot_id)

            # 서비스 컨테이너 초기화
            self.service_container = ServiceContainer()
            self.service_container.register("vector_service", vector_service)
            self.service_container.register("llm_service", llm_service)
            self.service_container.register("bot_id", bot_id)
            self.service_container.register("session_id", session_id)
            self.service_container.register("db_session", db)
            self.service_container.register("stream_handler", stream_handler)
            self.service_container.register("text_normalizer", text_normalizer)

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
            self._create_execution_run(
                workflow_data=workflow_data,
                session_id=session_id,
                bot_id=bot_id,
                user_message=user_message,
                db=db,
                workflow_version_id=self.workflow_version_id
            )

            # 노드 실행
            final_response = await self._execute_v2_nodes(stream_handler, text_normalizer)

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
            self._finalize_execution_run(
                status="succeeded",
                final_response=final_response,
                db=db
            )

            return final_response

        except Exception as e:
            logger.error(f"V2 워크플로우 실행 실패: {str(e)}")

            # 실행 기록 실패 처리
            if self.execution_run:
                self._finalize_execution_run(
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
        text_normalizer: Optional[Callable[[str], str]] = None
    ) -> str:
        """
        V2 노드들을 순서대로 실행

        Args:
            stream_handler: 스트림 핸들러
            text_normalizer: 텍스트 정규화 함수

        Returns:
            str: 최종 응답
        """
        final_response = "V2 워크플로우 실행 완료"

        incoming_counts = self._build_incoming_counts()
        edges_by_source = self._group_edges_by_source()
        ready_queue: deque[str] = deque()
        executed_nodes: set[str] = set()

        for node_id in self.execution_order:
            if incoming_counts.get(node_id, 0) == 0:
                ready_queue.append(node_id)

        while ready_queue:
            node_id = ready_queue.popleft()
            if node_id in executed_nodes:
                continue

            node = self.nodes.get(node_id)
            if not node:
                logger.warning(f"V2 노드 {node_id}를 찾을 수 없습니다")
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

                # 실행 컨텍스트 생성
                context = NodeExecutionContext(
                    node_id=node_id,
                    variable_pool=self.variable_pool,
                    service_container=self.service_container,
                    metadata={"prepared_inputs": prepared_inputs}
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
                self._create_node_execution(
                    node_id=node_id,
                    node_type=node.__class__.__name__,
                    execution_order=self.execution_order.index(node_id),
                    inputs=prepared_inputs,
                    outputs=result.output,
                    status=result.status.value,
                    error_message=result.error,
                    started_at=node_start_time,
                    finished_at=node_end_time,
                    execution_metadata=execution_metadata,
                    process_data=process_data
                )

                context.metadata.clear()

                if result.status == NodeStatus.FAILED:
                    raise RuntimeError(result.error or f"V2 Node {node_id} failed")

                executed_nodes.add(node_id)
                outgoing_edges = self._select_outgoing_edges(edges_by_source.get(node_id, []), edge_handles)
                for edge in outgoing_edges:
                    target = edge.get("target")
                    if target not in self.nodes:
                        continue
                    incoming_counts[target] = max(incoming_counts.get(target, 0) - 1, 0)
                    if incoming_counts[target] == 0:
                        ready_queue.append(target)

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
                self._create_node_execution(
                    node_id=node_id,
                    node_type=node.__class__.__name__,
                    execution_order=self.execution_order.index(node_id),
                    inputs=prepared_inputs if 'prepared_inputs' in locals() else {},
                    outputs={},
                    status=NodeStatus.FAILED.value,
                    error_message=str(e),
                    started_at=node_start_time,
                    finished_at=node_end_time,
                    execution_metadata=execution_metadata,
                    process_data=process_data
                )

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
        counts: Dict[str, int] = {node_id: 0 for node_id in self.nodes.keys()}
        for edge in self.edges:
            source = edge.get("source")
            target = edge.get("target")
            if source in self.nodes and target in self.nodes:
                counts[target] = counts.get(target, 0) + 1
                counts.setdefault(source, counts.get(source, 0))
        return counts

    def _group_edges_by_source(self) -> Dict[str, List[Dict[str, Any]]]:
        mapping: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for edge in self.edges:
            source = edge.get("source")
            target = edge.get("target")
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
                except Exception as e:
                    logger.warning(f"Failed to resolve input '{port_name}' from '{selector}': {e}")
                    prepared_inputs[port_name] = None

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

    def _create_execution_run(
        self,
        workflow_data: Dict[str, Any],
        session_id: str,
        bot_id: str,
        user_message: str,
        db: Any,
        workflow_version_id: Optional[str] = None
    ) -> None:
        """
        워크플로우 실행 기록 생성

        Args:
            workflow_data: 워크플로우 정의
            session_id: 세션 ID
            bot_id: 봇 ID
            user_message: 사용자 메시지
            db: 데이터베이스 세션
        """
        if not db:
            logger.warning("DB 세션이 없어 실행 기록을 저장하지 않습니다")
            return

        try:
            version_uuid = None
            if workflow_version_id:
                try:
                    version_uuid = uuid.UUID(str(workflow_version_id))
                except (ValueError, TypeError):
                    logger.warning("Invalid workflow_version_id provided: %s", workflow_version_id)

            self.execution_run = WorkflowExecutionRun(
                id=uuid.uuid4(),
                bot_id=bot_id,
                workflow_version_id=version_uuid,
                session_id=session_id,
                graph_snapshot=workflow_data,
                inputs={"user_message": user_message},
                outputs={},
                status="running",
                started_at=self.run_start_time,
                total_steps=len(self.execution_order)
            )

            db.add(self.execution_run)
            db.commit()
            logger.info(f"V2 워크플로우 실행 기록 생성: run_id={self.execution_run.id}")

        except Exception as e:
            logger.error(f"실행 기록 생성 실패: {str(e)}")
            db.rollback()

    def _finalize_execution_run(
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
        if not self.execution_run or not db:
            return

        try:
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
                for node_exec in self.execution_run.node_executions
            )
            self.execution_run.total_tokens = total_tokens

            db.commit()
            logger.info(
                f"V2 워크플로우 실행 완료: run_id={self.execution_run.id}, "
                f"status={status}, elapsed={elapsed_ms}ms"
            )

        except Exception as e:
            logger.error(f"실행 기록 완료 처리 실패: {str(e)}")
            db.rollback()

    def _create_node_execution(
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
        execution_metadata: Optional[Dict[str, Any]] = None,
        process_data: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        노드 실행 기록 생성

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
            execution_metadata: 실행 메타데이터 (Answer 노드 렌더링 정보 등)
        """
        if not self.execution_run:
            return

        try:
            elapsed_ms = int((finished_at - started_at).total_seconds() * 1000)

            # 토큰 사용량 추출 (LLM 노드의 경우)
            tokens_used = 0
            if node_type == "LLMNodeV2" and outputs:
                tokens_used = outputs.get("tokens", 0)

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

            # execution_run의 node_executions에 추가
            if not hasattr(self.execution_run, 'node_executions'):
                self.execution_run.node_executions = []
            self.execution_run.node_executions.append(node_execution)

            logger.debug(
                f"노드 실행 기록 생성: node_id={node_id}, "
                f"status={status}, elapsed={elapsed_ms}ms"
            )

        except Exception as e:
            logger.error(f"노드 실행 기록 생성 실패: {str(e)}")
