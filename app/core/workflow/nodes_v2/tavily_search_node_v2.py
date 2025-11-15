"""
Tavily Search V2 노드 구현

실시간 웹 검색을 수행하는 워크플로우 V2 노드입니다.
use_workflow_v2=True인 봇에서만 사용 가능합니다.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import Field
from app.core.workflow.base_node_v2 import (
    BaseNodeV2,
    NodeExecutionContext,
)
from app.core.workflow.base_node import NodeConfig
from app.schemas.workflow import NodePortSchema, PortDefinition, PortType
from app.core.workflow.node_registry_v2 import register_node_v2
from app.core.providers.tavily import TavilyClient, TavilySearchRequest
from app.config import settings
import logging

logger = logging.getLogger(__name__)


class TavilySearchNodeConfig(NodeConfig):
    """Tavily Search V2 노드 설정"""
    search_depth: str = Field(default="basic", description="basic | advanced")
    topic: str = Field(default="general", description="general | news | finance")
    max_results: int = Field(default=5, ge=0, le=20)
    include_domains: Optional[List[str]] = Field(default=None)
    exclude_domains: Optional[List[str]] = Field(default=None)
    time_range: Optional[str] = Field(default=None)
    start_date: Optional[str] = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    end_date: Optional[str] = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    include_answer: bool = Field(default=False)
    include_raw_content: bool = Field(default=False)


@register_node_v2("tavily-search")
class TavilySearchNodeV2(BaseNodeV2):
    """Tavily Search V2 노드"""

    def __init__(
        self,
        node_id: str,
        config: Optional[Dict[str, Any]] = None,
        variable_mappings: Optional[Dict[str, Any]] = None
    ):
        """
        Tavily Search 노드 초기화

        Args:
            node_id: 노드 고유 ID
            config: 노드 설정 (data 필드)
            variable_mappings: 입력 포트와 변수 매핑
        """
        super().__init__(node_id, config, variable_mappings)

        # config를 TavilySearchNodeConfig 인스턴스로 변환
        if config:
            try:
                self.typed_config = TavilySearchNodeConfig(**config)
            except Exception as e:
                logger.warning(f"Failed to parse config as TavilySearchNodeConfig: {e}")
                self.typed_config = TavilySearchNodeConfig()
        else:
            self.typed_config = TavilySearchNodeConfig()

    def get_port_schema(self) -> NodePortSchema:
        """
        노드의 입출력 포트 스키마 반환

        Returns:
            NodePortSchema: 입출력 포트 정의
        """
        return NodePortSchema(
            inputs=[
                PortDefinition(
                    name="query",
                    type=PortType.STRING,
                    required=True,
                    description="Tavily로 검색할 쿼리",
                    display_name="검색 쿼리"
                )
            ],
            outputs=[
                PortDefinition(
                    name="retrieved_documents",
                    type=PortType.ARRAY,
                    required=True,
                    description="LLM 노드 호환 문서 배열 (Knowledge 노드와 동일 형식)",
                    display_name="검색 문서 (배열)"
                ),
                PortDefinition(
                    name="context",
                    type=PortType.STRING,
                    required=True,
                    description="검색 결과를 문자열로 결합 (LLM에 직접 전달 가능)",
                    display_name="검색 컨텍스트"
                ),
                PortDefinition(
                    name="results",
                    type=PortType.ARRAY,
                    required=True,
                    description="검색 결과 배열 (원본 Tavily 응답)",
                    display_name="검색 결과"
                ),
                PortDefinition(
                    name="result_count",
                    type=PortType.NUMBER,
                    required=True,
                    description="검색 결과 개수",
                    display_name="결과 개수"
                ),
                PortDefinition(
                    name="response_time",
                    type=PortType.NUMBER,
                    required=True,
                    description="응답 시간 (초)",
                    display_name="응답 시간"
                ),
                PortDefinition(
                    name="answer",
                    type=PortType.STRING,
                    required=False,
                    description="AI가 생성한 답변 (include_answer=true일 때)",
                    display_name="답변"
                )
            ]
        )

    async def execute_v2(self, context: NodeExecutionContext) -> Dict[str, Any]:
        """
        Tavily Search 노드 실행

        Args:
            context: 실행 컨텍스트

        Returns:
            Dict[str, Any]: {port_name: value} 형식의 출력

        Raises:
            ValueError: query 입력이 없거나 API 키가 설정되지 않은 경우
        """
        query = context.get_input("query")
        if not query:
            raise ValueError("query input is required")

        cfg = self.typed_config
        api_key = getattr(settings, "tavily_api_key", None)
        if not api_key:
            raise ValueError("Tavily API key is not configured")

        async with TavilyClient(api_key=api_key) as tavily_client:
            search_result = await tavily_client.search(
                TavilySearchRequest(
                    query=str(query),
                    search_depth=cfg.search_depth,
                    topic=cfg.topic,
                    max_results=cfg.max_results,
                    include_domains=cfg.include_domains,
                    exclude_domains=cfg.exclude_domains,
                    time_range=cfg.time_range,
                    start_date=cfg.start_date,
                    end_date=cfg.end_date,
                    include_answer=cfg.include_answer,
                    include_raw_content=cfg.include_raw_content,
                )
            )

        # LLM 노드 호환 문서 배열 생성
        retrieved_documents = [
            {
                "content": result.content,
                "metadata": {
                    "title": result.title,
                    "url": result.url,
                    "score": result.score,
                },
            }
            for result in search_result.results
        ]

        # 검색 결과를 문자열로 결합
        context_text = "\n\n".join(
            f"[{idx+1}] {item.title}\n{item.content}\nURL: {item.url}"
            for idx, item in enumerate(search_result.results)
        )

        # 출력 구성
        output: Dict[str, Any] = {
            "retrieved_documents": retrieved_documents,
            "context": context_text,
            "results": [
                {
                    "title": result.title,
                    "url": result.url,
                    "content": result.content,
                    "score": result.score,
                    "raw_content": result.raw_content,
                    "favicon": result.favicon,
                }
                for result in search_result.results
            ],
            "result_count": len(search_result.results),
            "response_time": search_result.response_time,
        }

        # include_answer가 활성화되고 답변이 있는 경우에만 추가
        if cfg.include_answer and search_result.answer:
            output["answer"] = search_result.answer

        return output

    def validate(self) -> tuple[bool, Optional[str]]:
        """
        노드 설정 검증

        Returns:
            tuple: (유효 여부, 오류 메시지)
        """
        # 기본 포트 검증 (부모 클래스)
        is_valid, error = super().validate()
        if not is_valid:
            return is_valid, error

        cfg = self.typed_config
        if not cfg:
            return True, None

        # max_results 검증
        if not isinstance(cfg.max_results, int) or not (0 <= cfg.max_results <= 20):
            return False, "max_results must be between 0 and 20"

        # search_depth 검증
        if cfg.search_depth not in ["basic", "advanced"]:
            return False, "search_depth must be 'basic' or 'advanced'"

        # topic 검증
        if cfg.topic not in ["general", "news", "finance"]:
            return False, "topic must be 'general', 'news', or 'finance'"

        return True, None
