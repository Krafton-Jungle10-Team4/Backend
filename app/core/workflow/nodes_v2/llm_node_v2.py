"""
워크플로우 V2 LLM 노드

대형 언어 모델을 호출하여 응답을 생성하는 노드입니다.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from app.core.workflow.base_node_v2 import BaseNodeV2, NodeExecutionContext
from app.schemas.workflow import NodePortSchema, PortDefinition, PortType
from app.services.llm_service import LLMService
import logging
import re

logger = logging.getLogger(__name__)


class LLMNodeV2(BaseNodeV2):
    """
    워크플로우 V2 LLM 노드

    프롬프트 템플릿을 처리하고 LLM API를 호출하여 응답을 생성합니다.

    입력 포트:
        - query (STRING): 사용자 질문
        - context (STRING): 컨텍스트 정보 (선택)
        - system_prompt (STRING): 시스템 프롬프트 (선택)

    출력 포트:
        - response (STRING): LLM 응답
        - tokens (NUMBER): 사용된 토큰 수
        - model (STRING): 사용된 모델명
    """

    def get_port_schema(self) -> NodePortSchema:
        """
        포트 스키마 정의

        Returns:
            NodePortSchema: 입력 3개 (query, context, system_prompt), 출력 3개 (response, tokens, model)
        """
        return NodePortSchema(
            inputs=[
                PortDefinition(
                    name="query",
                    type=PortType.STRING,
                    required=True,
                    description="사용자 질문",
                    display_name="질문"
                ),
                PortDefinition(
                    name="context",
                    type=PortType.STRING,
                    required=False,
                    description="컨텍스트 정보 (검색 결과 등)",
                    display_name="컨텍스트"
                ),
                PortDefinition(
                    name="system_prompt",
                    type=PortType.STRING,
                    required=False,
                    description="시스템 프롬프트",
                    display_name="시스템 프롬프트"
                )
            ],
            outputs=[
                PortDefinition(
                    name="response",
                    type=PortType.STRING,
                    required=True,
                    description="LLM 생성 응답",
                    display_name="응답"
                ),
                PortDefinition(
                    name="tokens",
                    type=PortType.NUMBER,
                    required=False,
                    description="사용된 토큰 수",
                    display_name="토큰 수"
                ),
                PortDefinition(
                    name="model",
                    type=PortType.STRING,
                    required=False,
                    description="사용된 모델명",
                    display_name="모델"
                )
            ]
        )

    async def execute_v2(self, context: NodeExecutionContext) -> Dict[str, Any]:
        """
        LLM 노드 실행

        Args:
            context: 실행 컨텍스트

        Returns:
            Dict[str, Any]: {response: 응답텍스트, tokens: 토큰수, model: 모델명}

        Raises:
            ValueError: 필수 입력이 없거나 서비스를 찾을 수 없을 때
        """
        # 입력 조회
        query = context.get_input("query")
        if not query:
            raise ValueError("query input is required")

        context_text = context.get_input("context") or ""
        system_prompt = context.get_input("system_prompt") or ""

        # 서비스 조회
        llm_service = context.get_service("llm_service")
        if not llm_service:
            raise ValueError("llm_service not found in service container")

        stream_handler = context.get_service("stream_handler")

        # 설정 파라미터
        model = self.config.get("model", "gpt-4")
        provider = self.config.get("provider", "openai")
        temperature = self.config.get("temperature", 0.7)
        max_tokens = self.config.get("max_tokens", 4000)
        prompt_template = self.config.get("prompt_template", "{context}\n\nQuestion: {query}\nAnswer:")

        logger.info(f"LLMNodeV2: model={model}, provider={provider}, temp={temperature}")

        # 프롬프트 템플릿 처리
        try:
            prompt = self._render_prompt(
                template=prompt_template,
                query=query,
                context=context_text,
                system_prompt=system_prompt
            )
        except Exception as e:
            logger.error(f"Prompt rendering failed: {str(e)}")
            raise ValueError(f"Failed to render prompt template: {str(e)}")

        # LLM 호출
        try:
            result = await llm_service.generate(
                prompt=prompt,
                model=model,
                provider=provider,
                temperature=temperature,
                max_tokens=max_tokens,
                stream_handler=stream_handler
            )

            response_text: str
            tokens_used: int = 0

            if isinstance(result, dict):
                response_text = (
                    result.get("response")
                    or result.get("text")
                    or ""
                )
                tokens_used = result.get("tokens", 0)
            else:
                response_text = str(result)

            logger.info(f"LLMNodeV2: Generated response ({tokens_used} tokens)")

            return {
                "response": response_text,
                "tokens": tokens_used,
                "model": model
            }

        except Exception as e:
            logger.error(f"LLM generation failed: {str(e)}")
            raise

    def _render_prompt(
        self,
        template: str,
        query: str,
        context: str = "",
        system_prompt: str = ""
    ) -> str:
        """
        프롬프트 템플릿 렌더링

        Args:
            template: 프롬프트 템플릿
            query: 사용자 질문
            context: 컨텍스트 텍스트
            system_prompt: 시스템 프롬프트

        Returns:
            str: 렌더링된 프롬프트
        """
        # 변수 치환
        prompt = template
        prompt = prompt.replace("{query}", query)
        prompt = prompt.replace("{question}", query)  # 별칭 지원
        prompt = prompt.replace("{context}", context)
        prompt = prompt.replace("{system_prompt}", system_prompt)

        # 빈 줄 정리
        prompt = re.sub(r'\n{3,}', '\n\n', prompt)

        return prompt.strip()

    def validate(self) -> tuple[bool, Optional[str]]:
        """
        LLM 노드 검증

        Returns:
            tuple: (유효 여부, 오류 메시지)
        """
        # query 입력이 매핑되어 있는지 확인
        if "query" not in self.variable_mappings:
            return False, "query input must be mapped"

        # 모델 검증
        model = self.config.get("model")
        if not model or not isinstance(model, str):
            return False, "model must be specified as a string"

        # temperature 검증
        temperature = self.config.get("temperature", 0.7)
        if not isinstance(temperature, (int, float)) or temperature < 0 or temperature > 1:
            return False, "temperature must be between 0 and 1"

        # max_tokens 검증
        max_tokens = self.config.get("max_tokens", 4000)
        if not isinstance(max_tokens, int) or max_tokens < 1:
            return False, "max_tokens must be a positive integer"

        return True, None

    def get_required_services(self) -> List[str]:
        """필요한 서비스 목록"""
        return ["llm_service"]
