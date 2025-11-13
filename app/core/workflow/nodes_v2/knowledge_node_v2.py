"""
워크플로우 V2 지식 검색 노드

벡터 DB에서 관련 문서를 검색하는 노드입니다.
"""

from typing import Any, Dict, List, Optional
from app.core.workflow.base_node_v2 import BaseNodeV2, NodeExecutionContext
from app.schemas.workflow import NodePortSchema, PortDefinition, PortType
from app.services.vector_service import VectorService
import logging

logger = logging.getLogger(__name__)


class KnowledgeNodeV2(BaseNodeV2):
    """
    워크플로우 V2 지식 검색 노드

    사용자 쿼리를 받아 벡터 DB에서 관련 문서를 검색합니다.

    입력 포트:
        - query (STRING): 검색 쿼리

    출력 포트:
        - context (STRING): 검색된 문서들의 텍스트 (병합)
        - documents (ARRAY): 검색된 문서 목록 (메타데이터 포함)
        - doc_count (NUMBER): 검색된 문서 개수
    """

    def get_port_schema(self) -> NodePortSchema:
        """
        포트 스키마 정의

        Returns:
            NodePortSchema: 입력 1개 (query), 출력 3개 (context, documents, doc_count)
        """
        return NodePortSchema(
            inputs=[
                PortDefinition(
                    name="query",
                    type=PortType.STRING,
                    required=True,
                    description="검색할 쿼리 텍스트",
                    display_name="검색 쿼리"
                )
            ],
            outputs=[
                PortDefinition(
                    name="context",
                    type=PortType.STRING,
                    required=True,
                    description="검색된 문서들을 병합한 컨텍스트 텍스트",
                    display_name="컨텍스트"
                ),
                PortDefinition(
                    name="documents",
                    type=PortType.ARRAY,
                    required=False,
                    description="검색된 문서 목록 (메타데이터 포함)",
                    display_name="문서 목록"
                ),
                PortDefinition(
                    name="doc_count",
                    type=PortType.NUMBER,
                    required=False,
                    description="검색된 문서 개수",
                    display_name="문서 개수"
                )
            ]
        )

    async def execute_v2(self, context: NodeExecutionContext) -> Dict[str, Any]:
        """
        지식 검색 노드 실행

        Args:
            context: 실행 컨텍스트

        Returns:
            Dict[str, Any]: {context: 병합텍스트, documents: 문서목록, doc_count: 개수}

        Raises:
            ValueError: 필수 입력이 없거나 서비스를 찾을 수 없을 때
        """
        # 입력 조회
        query = context.get_input("query")
        if not query:
            raise ValueError("query input is required")

        # 서비스 조회
        vector_service = context.get_service("vector_service")
        if not vector_service:
            raise ValueError("vector_service not found in service container")

        bot_id = context.get_service("bot_id")
        db_session = context.get_service("db_session")

        # 설정 파라미터
        top_k = self.config.get("top_k", 5)
        dataset_id = self.config.get("dataset_id")
        document_ids = self.config.get("document_ids", [])

        logger.info(f"KnowledgeNodeV2: Searching with query='{query[:50]}...', top_k={top_k}")

        # 벡터 검색 수행
        try:
            # document_ids가 있으면 특정 문서에서만 검색
            if document_ids:
                results = await vector_service.search_in_documents(
                    query=query,
                    document_ids=document_ids,
                    top_k=top_k,
                    bot_id=bot_id,
                    db=db_session
                )
            else:
                # 전체 봇 지식에서 검색
                results = await vector_service.search(
                    query=query,
                    top_k=top_k,
                    bot_id=bot_id,
                    db=db_session
                )

            # 결과 처리
            if not results:
                logger.warning("No documents found")
                return {
                    "context": "",
                    "documents": [],
                    "doc_count": 0
                }

            # 문서 텍스트 병합
            context_text = "\n\n".join([doc.get("content", "") for doc in results])

            logger.info(f"KnowledgeNodeV2: Retrieved {len(results)} documents")

            return {
                "context": context_text,
                "documents": results,
                "doc_count": len(results)
            }

        except Exception as e:
            logger.error(f"Knowledge retrieval failed: {str(e)}")
            raise

    def validate(self) -> tuple[bool, Optional[str]]:
        """
        지식 검색 노드 검증

        Returns:
            tuple: (유효 여부, 오류 메시지)
        """
        # query 입력이 매핑되어 있는지 확인
        if "query" not in self.variable_mappings:
            return False, "query input must be mapped"

        # top_k 검증
        top_k = self.config.get("top_k", 5)
        if not isinstance(top_k, int) or top_k < 1 or top_k > 20:
            return False, "top_k must be an integer between 1 and 20"

        return True, None

    def get_required_services(self) -> List[str]:
        """필요한 서비스 목록"""
        return ["vector_service", "bot_id", "db_session"]
