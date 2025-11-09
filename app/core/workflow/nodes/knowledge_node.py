"""
지식 검색 노드 구현

업로드된 문서에서 관련 정보를 검색하는 노드입니다.
"""

from typing import Any, Dict, Optional, List
from pydantic import Field
from app.core.workflow.base_node import (
    BaseNode,
    NodeType,
    NodeStatus,
    NodeConfig,
    NodeSchema,
    NodeExecutionResult
)
from app.core.workflow.node_registry import register_node
import logging

logger = logging.getLogger(__name__)


class KnowledgeNodeConfig(NodeConfig):
    """지식 검색 노드 설정"""
    dataset_id: str = Field(..., description="데이터셋 ID")
    dataset_name: Optional[str] = Field(None, description="데이터셋 이름")
    mode: str = Field(default="semantic", description="검색 모드 (semantic, keyword)")
    top_k: int = Field(default=5, ge=1, le=20, description="검색 결과 개수")


@register_node(NodeType.KNOWLEDGE_RETRIEVAL)
class KnowledgeNode(BaseNode[KnowledgeNodeConfig]):
    """
    지식 검색 노드

    업로드된 문서에서 사용자 질문과 관련된 정보를 검색합니다.
    여러 개의 Knowledge 노드를 사용하여 다양한 문서에서 정보를 수집할 수 있습니다.
    """

    def __init__(
        self,
        node_id: str,
        node_type: NodeType = NodeType.KNOWLEDGE_RETRIEVAL,
        config: Optional[KnowledgeNodeConfig] = None,
        position: Optional[Dict[str, float]] = None
    ):
        super().__init__(node_id, node_type, config, position)

    async def execute(self, context: Dict[str, Any]) -> NodeExecutionResult:
        """
        지식 검색 실행

        Args:
            context: 실행 컨텍스트

        Returns:
            NodeExecutionResult: 검색 결과
        """
        try:
            self.set_status(NodeStatus.RUNNING)

            if not self.config:
                raise ValueError("Knowledge node requires configuration")

            # 사용자 메시지 가져오기
            user_message = context.get("user_message")
            if not user_message:
                # 이전 노드 출력에서 메시지 찾기
                node_outputs = context.get("node_outputs", {})
                for output in node_outputs.values():
                    if isinstance(output, dict) and "user_message" in output:
                        user_message = output["user_message"]
                        break

            if not user_message:
                raise ValueError("User message not found in context")

            # Vector 서비스 가져오기
            vector_service = context.get("vector_service")
            if not vector_service:
                raise ValueError("Vector service not found in context")

            # bot_id와 db 가져오기
            bot_id = context.get("bot_id")
            if not bot_id:
                raise ValueError("bot_id not found in context")

            db = context.get("db")
            if not db:
                raise ValueError("Database session not found in context")

            # 문서 검색 수행
            search_results = await self._perform_search(
                vector_service,
                user_message,
                bot_id,
                db,
                self.config.top_k,
                self.config.mode
            )

            result = NodeExecutionResult(
                status=NodeStatus.COMPLETED,
                output={
                    "retrieved_documents": search_results,
                    "dataset_id": self.config.dataset_id,
                    "dataset_name": self.config.dataset_name,
                    "search_mode": self.config.mode,
                    "top_k": self.config.top_k
                },
                metadata={
                    "node_id": self.node_id,
                    "node_type": self.node_type.value,
                    "documents_found": len(search_results)
                }
            )

            self.set_status(NodeStatus.COMPLETED)
            logger.info(f"Knowledge node {self.node_id} retrieved {len(search_results)} documents")

            return result

        except Exception as e:
            logger.error(f"Knowledge node execution failed: {str(e)}")
            self.set_status(NodeStatus.FAILED)
            return NodeExecutionResult(
                status=NodeStatus.FAILED,
                error=str(e)
            )

    async def _perform_search(
        self,
        vector_service,
        query: str,
        bot_id: int,
        db: Any,
        top_k: int,
        mode: str
    ) -> List[Dict[str, Any]]:
        """
        실제 검색 수행

        Args:
            vector_service: 벡터 검색 서비스
            query: 검색 쿼리
            bot_id: 봇 ID
            db: 데이터베이스 세션
            top_k: 검색 결과 개수
            mode: 검색 모드

        Returns:
            검색 결과 리스트
        """
        try:
            # 벡터 검색 서비스의 search_similar_chunks 메서드 호출
            results = await vector_service.search_similar_chunks(
                bot_id=bot_id,
                query=query,
                top_k=top_k,
                db=db
            )

            return results

        except Exception as e:
            logger.error(f"Search failed for bot_id {bot_id}: {str(e)}")
            # 검색 실패 시 빈 리스트 반환
            return []

    def validate(self) -> tuple[bool, Optional[str]]:
        """
        지식 검색 노드 검증

        Returns:
            tuple: (유효 여부, 오류 메시지)
        """
        if not self.config:
            return False, "Knowledge node requires configuration"

        if not self.config.dataset_id:
            return False, "Dataset ID is required"

        if self.config.top_k < 1 or self.config.top_k > 20:
            return False, "top_k must be between 1 and 20"

        if self.config.mode not in ["semantic", "keyword"]:
            return False, "Invalid search mode. Must be 'semantic' or 'keyword'"

        if len(self.inputs) == 0:
            return False, "Knowledge node must have at least one input"

        if len(self.outputs) == 0:
            return False, "Knowledge node must have at least one output"

        return True, None

    @classmethod
    def get_schema(cls) -> NodeSchema:
        """
        지식 검색 노드 스키마 반환

        Returns:
            NodeSchema: 노드 스키마
        """
        return NodeSchema(
            type=NodeType.KNOWLEDGE_RETRIEVAL,
            label="지식 검색",
            icon="database",
            max_instances=-1,  # 무제한
            configurable=True,
            config_schema={
                "dataset_id": {
                    "type": "string",
                    "required": True,
                    "description": "데이터셋 ID"
                },
                "dataset_name": {
                    "type": "string",
                    "required": False,
                    "description": "데이터셋 이름"
                },
                "mode": {
                    "type": "enum",
                    "options": ["semantic", "keyword"],
                    "default": "semantic",
                    "description": "검색 모드"
                },
                "top_k": {
                    "type": "number",
                    "min": 1,
                    "max": 20,
                    "default": 5,
                    "description": "검색 결과 개수"
                }
            },
            input_required=True,
            output_provided=True
        )

    @classmethod
    def get_config_class(cls) -> type[NodeConfig]:
        """설정 클래스 반환"""
        return KnowledgeNodeConfig

    def get_required_context_keys(self) -> list[str]:
        """필요한 컨텍스트 키 목록"""
        return ["vector_service"]