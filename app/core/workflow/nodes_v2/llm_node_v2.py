"""
워크플로우 V2 LLM 노드

대형 언어 모델을 호출하여 응답을 생성하는 노드입니다.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from app.core.workflow.base_node_v2 import BaseNodeV2, NodeExecutionContext
from app.schemas.workflow import NodePortSchema, PortDefinition, PortType
from app.services.llm_service import LLMService
from app.core.workflow.nodes_v2.utils.template_renderer import (
    TemplateRenderer,
    TemplateRenderError,
)
from app.core.workflow.nodes_v2.utils.variable_template_parser import VariableTemplateParser
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
        
        # 컨텍스트가 비어있는 경우 경고 로깅
        if not context_text:
            logger.warning(f"[LLMNodeV2] Context is empty for node {self.node_id}. "
                          f"Variable mappings: {self.variable_mappings}")

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
        prompt_template = (self.config.get("prompt_template") or "").strip()

        logger.info(f"LLMNodeV2: model={model}, provider={provider}, temp={temperature}")

        # 프롬프트 템플릿 처리
        try:
            if prompt_template:
                # 템플릿 내용 로깅
                logger.info(f"[LLMNodeV2] 프롬프트 템플릿 사용: {len(prompt_template)} chars")
                logger.debug(f"[LLMNodeV2] 프롬프트 템플릿 내용: {prompt_template[:200]}...")
                
                # context 변수가 템플릿에 포함되어 있는지 확인
                has_context_var = "context" in prompt_template.lower() or any(
                    "context" in str(selector).lower() 
                    for selector in self.variable_mappings.values()
                    if isinstance(selector, (str, dict))
                )
                
                if not has_context_var and context_text:
                    logger.warning(
                        f"[LLMNodeV2] 프롬프트 템플릿에 context 변수가 없지만 context가 제공되었습니다. "
                        f"context 길이: {len(context_text)} chars. "
                        f"템플릿에 {{{{1763265553497.context}}}} 또는 context 변수를 추가하세요."
                    )
                
                prompt_group = self._render_template_with_variable_pool(
                    template=prompt_template,
                    context=context,
                )
                prompt = prompt_group.text
                
                # 렌더링 결과 로깅
                logger.debug(
                    f"[LLMNodeV2] 템플릿 렌더링 결과: "
                    f"템플릿 길이={len(prompt_template)}, "
                    f"출력 길이={len(prompt)} chars"
                )
            else:
                logger.info(f"[LLMNodeV2] 기본 프롬프트 템플릿 사용 (prompt_template이 설정되지 않음)")
                prompt = self._render_prompt(
                    template="{context}\n\nQuestion: {query}\nAnswer:",
                    query=query,
                    context=context_text,
                    system_prompt=system_prompt
                )
            
            # 프롬프트 로깅 (처음 500자만)
            logger.info(f"[LLMNodeV2] 프롬프트 생성 완료: {len(prompt)} chars")
            logger.debug(f"[LLMNodeV2] 프롬프트 미리보기: {prompt[:500]}...")
            
            # context가 비어있는데 프롬프트가 짧은 경우 경고
            if context_text and len(prompt) < len(context_text) * 0.5:
                logger.warning(
                    f"[LLMNodeV2] ⚠️ 프롬프트가 context보다 훨씬 짧습니다! "
                    f"context={len(context_text)} chars, prompt={len(prompt)} chars. "
                    f"템플릿에 context 변수가 포함되지 않았을 수 있습니다."
                )
        except Exception as e:
            logger.error(f"Prompt rendering failed: {str(e)}")
            raise ValueError(f"Failed to render prompt template: {str(e)}")

        # LLM 호출
        try:
            # stream_handler가 있으면 스트리밍 사용, 없으면 일반 생성 사용
            if stream_handler:
                result = await llm_service.generate_stream(
                    prompt=prompt,
                    model=model,
                    provider=provider,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    on_chunk=stream_handler.emit_content_chunk
                )
            else:
                result = await llm_service.generate(
                    prompt=prompt,
                    model=model,
                    provider=provider,
                    temperature=temperature,
                    max_tokens=max_tokens
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
            
            # 응답이 비어있는 경우 경고
            if not response_text or len(response_text.strip()) == 0:
                logger.warning(f"[LLMNodeV2] 응답이 비어있습니다! tokens={tokens_used}, provider={provider}, model={model}")
                logger.warning(f"[LLMNodeV2] 프롬프트 길이: {len(prompt)}, context 길이: {len(context_text)}")
            else:
                logger.info(f"[LLMNodeV2] 응답 생성 완료: {len(response_text)} chars")
                logger.debug(f"[LLMNodeV2] 응답 미리보기: {response_text[:200]}...")

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

    def _render_template_with_variable_pool(
        self,
        template: str,
        context: NodeExecutionContext,
    ):
        """
        TemplateRenderer를 사용해 {{ }} 템플릿을 렌더링한다.
        """
        try:
            parser = VariableTemplateParser(template)
            selectors = parser.extract_variable_selectors()
            rendered_group, metadata = TemplateRenderer.render(template, context.variable_pool)
            metadata["selectors"] = selectors
            context.metadata.setdefault("llm_prompt", {})[self.node_id] = metadata
            return rendered_group
        except TemplateRenderError as exc:
            logger.error("LLMNodeV2 template render failed: %s", exc)
            raise ValueError(f"Failed to render prompt template: {exc}") from exc
