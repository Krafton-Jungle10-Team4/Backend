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

        logger.info(f"LLMNodeV2: model={model}, provider={provider}, temp={temperature}, max_tokens={max_tokens}")

        # 프롬프트 템플릿 처리
        try:
            if prompt_template:
                # 템플릿 내용 로깅
                logger.info(f"[LLMNodeV2] 프롬프트 템플릿 사용: {len(prompt_template)} chars")
                logger.debug(f"[LLMNodeV2] 프롬프트 템플릿 내용: {prompt_template[:200]}...")
                
                # {{ }} 형식의 변수가 있는지 확인
                parser = VariableTemplateParser(prompt_template)
                has_double_brace_vars = len(parser.extract_variable_selectors()) > 0
                
                # 단순 { } 형식의 변수가 있는지 확인 (query, context, system_prompt 등)
                has_simple_vars = bool(re.search(r'\{query\}|\{context\}|\{system_prompt\}|\{question\}', prompt_template))
                
                if has_double_brace_vars:
                    # {{ }} 형식의 변수가 있으면 TemplateRenderer 사용
                    logger.debug("[LLMNodeV2] {{ }} 형식의 변수 감지, TemplateRenderer 사용")
                    prompt_group = self._render_template_with_variable_pool(
                        template=prompt_template,
                        context=context,
                    )
                    prompt = prompt_group.text
                    
                    # 단순 { } 형식의 변수도 있으면 추가로 처리
                    if has_simple_vars:
                        logger.debug("[LLMNodeV2] 단순 { } 형식의 변수도 감지, 추가 치환 수행")
                        prompt = self._render_prompt(
                            template=prompt,
                            query=query,
                            context=context_text,
                            system_prompt=system_prompt
                        )
                elif has_simple_vars:
                    # 단순 { } 형식의 변수만 있으면 _render_prompt 사용
                    logger.debug("[LLMNodeV2] 단순 { } 형식의 변수만 감지, _render_prompt 사용")
                    prompt = self._render_prompt(
                        template=prompt_template,
                        query=query,
                        context=context_text,
                        system_prompt=system_prompt
                    )
                else:
                    # 변수가 없으면 템플릿 그대로 사용
                    logger.debug("[LLMNodeV2] 템플릿에 변수가 없음, 그대로 사용")
                    prompt = prompt_template
                
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

        단순 포트 이름(query, context 등)을 노드 ID 없이 사용할 수 있도록
        {{ context }} → {{ self.context }}로 자동 변환합니다.
        """
        try:
            # 현재 노드의 입력 포트 값을 "self" prefix로 변수 풀에 임시 주입
            query = context.get_input("query")
            context_text = context.get_input("context") or ""
            system_prompt = context.get_input("system_prompt") or ""

            # 임시 노드로 주입
            context.variable_pool.set_node_output("self", "query", query)
            context.variable_pool.set_node_output("self", "context", context_text)
            context.variable_pool.set_node_output("self", "system_prompt", system_prompt)

            # 단순 포트 이름을 self. prefix로 자동 변환
            # {{ context }} → {{ self.context }}
            # {{ query }} → {{ self.query }}
            template_processed = template
            for port_name in ["context", "query", "system_prompt"]:
                # {{ port_name }} 패턴을 {{ self.port_name }}으로 변환 (공백 고려)
                template_processed = re.sub(
                    rf'\{{\{{\s*{port_name}\s*\}}\}}',
                    f'{{{{ self.{port_name} }}}}',
                    template_processed
                )

            if template_processed != template:
                logger.debug(f"[LLMNodeV2] 템플릿 자동 변환: 단순 포트 이름 → self.포트")

            # 실행 경로상의 모든 노드의 변수를 허용하도록 셀렉터 목록 계산
            allowed_selectors = self._compute_allowed_selectors_from_execution_path(context)

            parser = VariableTemplateParser(template_processed)
            selectors = parser.extract_variable_selectors()
            rendered_group, metadata = TemplateRenderer.render(
                template_processed,
                context.variable_pool,
                allowed_selectors=allowed_selectors
            )
            metadata["selectors"] = selectors
            context.metadata.setdefault("llm_prompt", {})[self.node_id] = metadata
            return rendered_group
        except TemplateRenderError as exc:
            logger.error("LLMNodeV2 template render failed: %s", exc)
            raise ValueError(f"Failed to render prompt template: {exc}") from exc

    def _compute_allowed_selectors_from_execution_path(self, context: NodeExecutionContext) -> List[str]:
        """
        실행 경로상의 노드들의 변수 셀렉터 목록을 계산

        실행 플로우를 따라 도달한 모든 노드들의 출력 변수를 사용할 수 있도록 허용합니다.
        이를 통해 직접 연결되지 않았더라도 실행 경로상의 모든 노드의 변수에 접근할 수 있습니다.

        Args:
            context: 실행 컨텍스트 (실행 경로 정보 포함)

        Returns:
            List[str]: 허용된 변수 셀렉터 목록
        """
        allowed = []

        # 실행 경로상의 노드들의 출력을 허용
        if hasattr(context, 'executed_nodes') and context.executed_nodes:
            logger.debug(f"[LLMNodeV2] 실행 경로상의 노드들: {context.executed_nodes}")

            # 실행 경로상의 노드들의 일반적인 출력 포트들
            # (실제로는 노드 타입별로 다르지만, 일반적인 이름들을 포함)
            common_outputs = [
                'output', 'response', 'result', 'results',
                'query', 'value', 'session_id', 'text',
                'tokens', 'model', 'data', 'content',
                'answer', 'question', 'context', 'summary',
                'extracted', 'processed', 'transformed'
            ]

            for node_id in context.executed_nodes:
                # 각 노드의 가능한 출력들을 허용
                for output in common_outputs:
                    selector = f"{node_id}.{output}"
                    allowed.append(selector)

                # 특히 tavilySearch 노드의 경우 results 포트를 명시적으로 허용
                if 'tavily' in node_id.lower() or 'search' in node_id.lower():
                    allowed.append(f"{node_id}.results")
                    allowed.append(f"{node_id}.result")
                    allowed.append(f"{node_id}.data")
                    allowed.append(f"{node_id}.response")

        # variable_mappings에 정의된 셀렉터들도 추가
        for port_name, selector in self.variable_mappings.items():
            if selector:
                if isinstance(selector, str):
                    allowed.append(selector)
                elif isinstance(selector, dict):
                    var_selector = selector.get("variable")
                    if var_selector:
                        allowed.append(var_selector)

        # 자기 자신의 입력 포트도 허용 (self.port_name 형식)
        for port_name in self.get_input_port_names():
            allowed.append(f"self.{port_name}")

        # 중복 제거
        allowed = list(set(allowed))

        logger.info(f"[LLMNodeV2] 허용된 변수 셀렉터: {len(allowed)}개")
        logger.debug(f"[LLMNodeV2] 허용된 셀렉터 목록 (샘플): {allowed[:10]}...")

        return allowed
