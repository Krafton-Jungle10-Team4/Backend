"""
Workflow 실행 엔진

⚠️ DEPRECATED: 이 파일은 레거시 코드입니다.
새로운 워크플로우 실행은 app.core.workflow.executor.WorkflowExecutor를 사용하세요.
"""
import logging
from typing import Dict, Any, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.workflow import Workflow, WorkflowNode, WorkflowEdge
from app.services.vector_service import VectorService
from app.services.llm_service import LLMService
from app.core.exceptions import (
    WorkflowExecutionError,
    WorkflowValidationError,
    LLMServiceError,
    VectorStoreError
)

logger = logging.getLogger(__name__)


class WorkflowExecutionContext:
    """Workflow 실행 컨텍스트"""

    def __init__(self):
        self.user_message: str = ""
        self.retrieved_documents: List[Dict[str, Any]] = []
        self.llm_response: str = ""
        self.session_id: str = ""
        self.metadata: Dict[str, Any] = {}


class WorkflowEngine:
    """Workflow 실행 엔진"""

    def __init__(
        self,
        vector_service: VectorService,
        llm_service: LLMService
    ):
        self.vector_service = vector_service
        self.llm_service = llm_service

    async def execute_workflow(
        self,
        workflow: Workflow,
        user_message: str,
        user_uuid: str,
        session_id: str,
        db: AsyncSession
    ) -> Dict[str, Any]:
        """
        Workflow 실행

        Args:
            workflow: 실행할 Workflow 정의
            user_message: 사용자 메시지
            user_uuid: 사용자 UUID
            session_id: 세션 ID
            db: 데이터베이스 세션

        Returns:
            실행 결과
        """
        logger.info(f"[WorkflowEngine] Workflow 실행 시작: session={session_id}")

        # 실행 컨텍스트 초기화
        context = WorkflowExecutionContext()
        context.user_message = user_message
        context.session_id = session_id

        # 실행 순서 계산 (토폴로지 정렬)
        execution_order = self._calculate_execution_order(workflow)
        logger.info(f"[WorkflowEngine] 실행 순서: {execution_order}")

        # 노드 순차 실행
        for node_id in execution_order:
            node = self._find_node_by_id(workflow.nodes, node_id)
            if not node:
                logger.warning(f"[WorkflowEngine] 노드를 찾을 수 없음: {node_id}")
                continue

            logger.info(f"[WorkflowEngine] 노드 실행: {node_id} (type: {node.type})")

            try:
                await self._execute_node(node, context, user_uuid, db)
            except (LLMServiceError, VectorStoreError) as e:
                logger.error(f"[WorkflowEngine] 노드 실행 중 서비스 오류: {node_id}, error: {e}", exc_info=True)
                raise WorkflowExecutionError(
                    message=f"워크플로우 노드 실행 중 서비스 오류가 발생했습니다: {node_id}",
                    details={
                        "node_id": node_id,
                        "node_type": node.type,
                        "error": str(e)
                    }
                )
            except Exception as e:
                logger.error(f"[WorkflowEngine] 노드 실행 실패: {node_id}, error: {e}", exc_info=True)
                raise WorkflowExecutionError(
                    message=f"워크플로우 노드 실행 중 예기치 않은 오류가 발생했습니다: {node_id}",
                    details={
                        "node_id": node_id,
                        "node_type": node.type,
                        "error_type": type(e).__name__,
                        "error": str(e)
                    }
                )

        logger.info(f"[WorkflowEngine] Workflow 실행 완료")

        # 결과 반환
        return {
            "response": context.llm_response,
            "sources": context.retrieved_documents,
            "session_id": context.session_id,
            "retrieved_chunks": len(context.retrieved_documents)
        }

    async def _execute_node(
        self,
        node: WorkflowNode,
        context: WorkflowExecutionContext,
        user_uuid: str,
        db: AsyncSession
    ):
        """개별 노드 실행"""
        node_type = node.data.get("type")

        if node_type == "start":
            # Start 노드: 초기화만 수행
            logger.debug("[WorkflowEngine] Start 노드 처리")

        elif node_type == "knowledge-retrieval":
            # Knowledge Retrieval 노드: 문서 검색
            await self._execute_knowledge_retrieval(node, context, user_uuid, db)

        elif node_type == "llm":
            # LLM 노드: AI 응답 생성
            await self._execute_llm(node, context, user_uuid)

        elif node_type == "end":
            # End 노드: 완료 처리
            logger.debug("[WorkflowEngine] End 노드 처리")

        else:
            logger.warning(f"[WorkflowEngine] 알 수 없는 노드 타입: {node_type}")

    async def _execute_knowledge_retrieval(
        self,
        node: WorkflowNode,
        context: WorkflowExecutionContext,
        user_uuid: str,
        db: AsyncSession
    ):
        """Knowledge Retrieval 노드 실행"""
        top_k = node.data.get("top_k", 5)

        logger.info(f"[WorkflowEngine] 문서 검색 시작: query='{context.user_message[:50]}...', top_k={top_k}")

        # 벡터 검색 실행
        results = await self.vector_service.search_similar_chunks(
            user_uuid=user_uuid,
            query=context.user_message,
            top_k=top_k,
            db=db
        )

        # 컨텍스트에 저장
        context.retrieved_documents = [
            {
                "document_id": r["metadata"].get("document_id", "unknown"),
                "chunk_id": r["metadata"].get("chunk_id", "unknown"),
                "content": r["content"][:500],  # 500자로 제한
                "similarity_score": r["similarity"],
                "metadata": r["metadata"]
            }
            for r in results
        ]

        logger.info(f"[WorkflowEngine] 문서 검색 완료: {len(context.retrieved_documents)}개 청크")

    async def _execute_llm(
        self,
        node: WorkflowNode,
        context: WorkflowExecutionContext,
        user_uuid: str
    ):
        """LLM 노드 실행"""
        model_info = node.data.get("model")
        provider = node.data.get("provider")
        model_name = None

        if isinstance(model_info, dict):
            provider = provider or model_info.get("provider")
            model_name = model_info.get("name") or model_info.get("id")
        else:
            model_name = model_info

        if not provider:
            normalized = (model_name or "").lower()
            if normalized.startswith("gpt"):
                provider = "openai"
            elif normalized.startswith("claude"):
                provider = "anthropic"
            elif normalized.startswith("gemini"):
                provider = "google"
            else:
                provider = "openai"
        provider = provider.lower()
        prompt_template = node.data.get("prompt", "검색된 문서를 기반으로 답변하세요.")
        temperature = node.data.get("temperature", 0.7)
        max_tokens = node.data.get("max_tokens", 2000)

        logger.info(
            "[WorkflowEngine] LLM 호출: provider=%s model=%s temp=%.2f",
            provider,
            model_name or "default",
            temperature
        )

        # 프롬프트 생성
        context_text = "\n\n".join([
            f"[문서 {i+1}]\n{doc['content']}"
            for i, doc in enumerate(context.retrieved_documents)
        ])

        # LLM 호출
        response = await self.llm_service.generate_response(
            query=context.user_message,
            context=context_text,
            temperature=temperature,
            max_tokens=max_tokens,
            provider=provider,
            model=model_name
        )

        context.llm_response = response
        logger.info(f"[WorkflowEngine] LLM 응답 생성 완료: {len(response)}자")

    def _calculate_execution_order(self, workflow: Workflow) -> List[str]:
        """
        토폴로지 정렬로 노드 실행 순서 계산

        Returns:
            노드 ID 순서 리스트
        """
        # 간단한 구현: edge를 따라 순차적으로 정렬
        # (실제로는 DAG 토폴로지 정렬 알고리즘 사용 권장)

        if not workflow.edges:
            # edge가 없으면 노드 순서대로
            return [node.id for node in workflow.nodes]

        # 인접 리스트 구성
        graph: Dict[str, List[str]] = {}
        in_degree: Dict[str, int] = {}

        for node in workflow.nodes:
            graph[node.id] = []
            in_degree[node.id] = 0

        for edge in workflow.edges:
            graph[edge.source].append(edge.target)
            in_degree[edge.target] = in_degree.get(edge.target, 0) + 1

        # 진입 차수가 0인 노드부터 시작 (Kahn's algorithm)
        queue = [node_id for node_id, degree in in_degree.items() if degree == 0]
        result = []

        while queue:
            current = queue.pop(0)
            result.append(current)

            for neighbor in graph[current]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if len(result) != len(workflow.nodes):
            # 순환 그래프 감지
            logger.warning("[WorkflowEngine] 순환 그래프 감지됨, 노드 순서대로 실행")
            return [node.id for node in workflow.nodes]

        return result

    def _find_node_by_id(self, nodes: List[WorkflowNode], node_id: str) -> Optional[WorkflowNode]:
        """노드 ID로 노드 찾기"""
        for node in nodes:
            if node.id == node_id:
                return node
        return None


def get_workflow_engine(
    vector_service: VectorService,
    llm_service: LLMService
) -> WorkflowEngine:
    """Workflow Engine 인스턴스 생성"""
    return WorkflowEngine(vector_service, llm_service)
