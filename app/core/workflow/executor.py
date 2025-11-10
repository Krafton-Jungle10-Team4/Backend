"""
워크플로우 실행 엔진

노드 기반 워크플로우를 실행하는 엔진입니다.
토폴로지 정렬을 사용하여 실행 순서를 결정하고 각 노드를 순차적으로 실행합니다.
"""

from typing import Dict, List, Any, Optional
from collections import defaultdict, deque
from app.core.workflow.base_node import BaseNode, NodeType, NodeStatus
from app.core.workflow.node_registry import node_registry
from app.core.workflow.validator import WorkflowValidator
from app.services.vector_service import VectorService
from app.services.llm_service import LLMService
import logging
import asyncio

logger = logging.getLogger(__name__)


class WorkflowExecutionContext:
    """
    워크플로우 실행 컨텍스트

    노드 간 데이터 전달과 상태 관리를 담당합니다.
    """

    def __init__(self, session_id: str, user_message: str):
        """
        실행 컨텍스트 초기화

        Args:
            session_id: 세션 ID
            user_message: 사용자 메시지
        """
        self.session_id = session_id
        self.user_message = user_message
        self.node_outputs: Dict[str, Any] = {}
        self.metadata: Dict[str, Any] = {}

        # 서비스 인스턴스
        self.vector_service: Optional[VectorService] = None
        self.llm_service: Optional[LLMService] = None
        self.bot_id: Optional[int] = None
        self.db: Optional[Any] = None

    def set_node_output(self, node_id: str, output: Any):
        """노드 출력 저장"""
        self.node_outputs[node_id] = output

    def get_node_output(self, node_id: str) -> Optional[Any]:
        """노드 출력 조회"""
        return self.node_outputs.get(node_id)

    def to_dict(self) -> Dict[str, Any]:
        """컨텍스트를 딕셔너리로 변환"""
        return {
            "session_id": self.session_id,
            "user_message": self.user_message,
            "node_outputs": self.node_outputs,
            "metadata": self.metadata,
            "vector_service": self.vector_service,
            "llm_service": self.llm_service,
            "bot_id": self.bot_id,
            "db": self.db
        }


class WorkflowExecutor:
    """
    워크플로우 실행 엔진

    노드 기반 워크플로우를 실행합니다.
    """

    def __init__(self):
        """실행 엔진 초기화"""
        self.validator = WorkflowValidator()
        self.nodes: Dict[str, BaseNode] = {}
        self.execution_order: List[str] = []

    async def execute(
        self,
        workflow_data: Dict[str, Any],
        session_id: str,
        user_message: str,
        bot_id: str,
        db: Any,
        vector_service: Optional[VectorService] = None,
        llm_service: Optional[LLMService] = None
    ) -> str:
        """
        워크플로우 실행

        Args:
            workflow_data: 워크플로우 정의
            session_id: 세션 ID
            user_message: 사용자 메시지
            bot_id: 봇 ID
            db: 데이터베이스 세션
            vector_service: 벡터 서비스 (옵셔널)
            llm_service: LLM 서비스 (옵셔널)

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

            self._normalize_workflow_schema(nodes_data)

            is_valid, errors, warnings = self.validator.validate(nodes_data, edges_data)
            if not is_valid:
                error_msg = "\n".join(errors)
                raise ValueError(f"워크플로우 검증 실패: {error_msg}")

            if warnings:
                for warning in warnings:
                    logger.warning(f"워크플로우 경고: {warning}")

            # 노드 인스턴스 생성
            self._create_nodes(nodes_data, edges_data)

            # 실행 순서 결정
            self.execution_order = self.validator.get_execution_order(nodes_data, edges_data)
            if not self.execution_order:
                raise ValueError("워크플로우 실행 순서를 결정할 수 없습니다")

            logger.info(f"워크플로우 실행 순서: {self.execution_order}")

            # 실행 컨텍스트 생성
            context = WorkflowExecutionContext(session_id, user_message)
            context.vector_service = vector_service
            context.llm_service = llm_service
            context.bot_id = bot_id
            context.db = db

            # 노드 실행
            final_response = await self._execute_nodes(context)

            return final_response

        except Exception as e:
            logger.error(f"워크플로우 실행 실패: {str(e)}")
            raise RuntimeError(f"워크플로우 실행 실패: {str(e)}")

    @staticmethod
    def _normalize_workflow_schema(nodes_data: List[Dict[str, Any]]) -> None:
        """레거시 워크플로우 데이터를 최신 스키마로 정규화"""

        for node in nodes_data:
            node_type = node.get("type")
            data = node.setdefault("data", {})

            if node_type == NodeType.LLM.value:
                model_value = data.get("model")
                if isinstance(model_value, dict):
                    data["model"] = model_value.get("name") or model_value.get("id") or "gpt-4"
                elif not isinstance(model_value, str) or not model_value:
                    data["model"] = "gpt-4"

                if "prompt_template" not in data and data.get("prompt"):
                    data["prompt_template"] = data["prompt"]

            if node_type == NodeType.KNOWLEDGE_RETRIEVAL.value:
                if "dataset_id" not in data and data.get("dataset"):
                    data["dataset_id"] = data["dataset"]
                if not data.get("dataset_id"):
                    data["dataset_id"] = "default-dataset"

                if "top_k" not in data and data.get("topK") is not None:
                    data["top_k"] = data["topK"]

                if "document_ids" not in data and data.get("documentIds"):
                    data["document_ids"] = data["documentIds"]

    def _create_nodes(self, nodes_data: List[Dict], edges_data: List[Dict]):
        """
        노드 인스턴스 생성

        Args:
            nodes_data: 노드 데이터
            edges_data: 엣지 데이터
        """
        self.nodes = {}

        # 노드 생성
        for node_data in nodes_data:
            node_id = node_data.get("id")
            node_type = node_data.get("type")
            position = node_data.get("position", {"x": 0, "y": 0})
            config_data = node_data.get("data", {})

            try:
                # NodeType enum으로 변환
                node_type_enum = NodeType(node_type)

                # 노드 인스턴스 생성
                node = node_registry.create_node(
                    node_type=node_type_enum,
                    node_id=node_id,
                    config=config_data,
                    position=position
                )

                self.nodes[node_id] = node

            except Exception as e:
                logger.error(f"노드 생성 실패 ({node_id}): {str(e)}")
                raise ValueError(f"노드 생성 실패 ({node_id}): {str(e)}")

        # 엣지 연결
        for edge_data in edges_data:
            source = edge_data.get("source")
            target = edge_data.get("target")

            if source in self.nodes and target in self.nodes:
                self.nodes[source].add_output(target)
                self.nodes[target].add_input(source)

    async def _execute_nodes(self, context: WorkflowExecutionContext) -> str:
        """
        노드들을 순서대로 실행

        Args:
            context: 실행 컨텍스트

        Returns:
            str: 최종 응답
        """
        final_response = "워크플로우 실행 완료"

        for node_id in self.execution_order:
            node = self.nodes.get(node_id)
            if not node:
                logger.warning(f"노드 {node_id}를 찾을 수 없습니다")
                continue

            try:
                logger.info(f"노드 실행 중: {node_id} ({node.node_type.value})")

                # 노드 실행
                result = await node.execute(context.to_dict())

                # 결과 저장
                if result.output:
                    context.set_node_output(node_id, result.output)

                    # End 노드의 경우 최종 응답 추출
                    if node.node_type == NodeType.END and isinstance(result.output, dict):
                        final_response = result.output.get("response", final_response)

                logger.info(f"노드 {node_id} 실행 완료")

            except Exception as e:
                logger.error(f"노드 {node_id} 실행 실패: {str(e)}")
                node.set_status(NodeStatus.FAILED)
                # 실패한 노드가 있어도 계속 진행 (옵션에 따라 중단할 수도 있음)
                continue

        return final_response

    async def execute_parallel(
        self,
        workflow_data: Dict[str, Any],
        session_id: str,
        user_message: str,
        vector_service: Optional[VectorService] = None,
        llm_service: Optional[LLMService] = None
    ) -> str:
        """
        워크플로우 병렬 실행 (향후 구현)

        독립적인 노드들을 병렬로 실행하여 성능을 향상시킵니다.

        Args:
            workflow_data: 워크플로우 정의
            session_id: 세션 ID
            user_message: 사용자 메시지
            vector_service: 벡터 서비스
            llm_service: LLM 서비스

        Returns:
            str: 최종 응답
        """
        # TODO: 병렬 실행 구현
        # 1. 의존성 분석
        # 2. 독립 노드 그룹 식별
        # 3. asyncio.gather()로 병렬 실행
        # 4. 결과 병합
        raise NotImplementedError("병렬 실행은 아직 구현되지 않았습니다")

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
