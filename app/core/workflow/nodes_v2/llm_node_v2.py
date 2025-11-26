"""
워크플로우 V2 LLM 노드

대형 언어 모델을 호출하여 응답을 생성하는 노드입니다.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
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
                    required=False,
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
        # 입력 조회 (query는 optional, 프롬프트에서 다른 변수 참조 가능)
        query = context.get_input("query") or ""

        context_text = context.get_input("context") or ""
        system_prompt = context.get_input("system_prompt") or ""
        has_context_mapping = "context" in self.variable_mappings
        allow_context_fallback = bool(self.config.get("allow_conversation_context_fallback", False))
        conversation_context_key = self.config.get("conversation_context_key", "knowledge_context")
        
        # 컨텍스트가 비어있는 경우 경고 로깅
        if not context_text:
            logger.warning(f"[LLMNodeV2] Context is empty for node {self.node_id}. "
                          f"Variable mappings: {self.variable_mappings}")
            
            # 매핑이 없고 폴백이 허용된 경우 대화 변수에서 컨텍스트 자동 조회
            if not has_context_mapping and allow_context_fallback:
                try:
                    fallback_context = context.variable_pool.get_conversation_variable(conversation_context_key)
                    if fallback_context:
                        context_text = fallback_context
                        logger.info(
                            f"[LLMNodeV2] Using conversation fallback '{conversation_context_key}' "
                            f"for context (len={len(str(context_text))})"
                        )
                    else:
                        logger.warning(
                            f"[LLMNodeV2] Conversation fallback '{conversation_context_key}' is empty or missing"
                        )
                except Exception as fallback_error:
                    logger.warning(f"[LLMNodeV2] Failed to resolve conversation fallback: {fallback_error}")
        
        # 검색 결과 없음 메시지 감지 (KnowledgeNodeV2에서 반환한 메시지)
        is_no_result = self._is_no_result_context(context_text)

        # 컨텍스트가 지식 노드의 "검색 결과 없음" 메시지라면,
        # 이미 실행된 다른 검색/뉴스 노드의 컨텍스트로 교체 시도
        if is_no_result:
            alternative_context, source_node = self._find_alternative_context(context)
            if alternative_context:
                logger.info(
                    "[LLMNodeV2] No-result context replaced with output from node %s (len=%d)",
                    source_node,
                    len(str(alternative_context))
                )
                context_text = alternative_context
                is_no_result = False
            else:
                logger.info("[LLMNodeV2] No-result context retained (no alternative context found)")

        # 서비스 조회
        llm_service = context.get_service("llm_service")
        if not llm_service:
            raise ValueError("llm_service not found in service container")

        stream_handler = context.get_service("stream_handler")

        # 설정 파라미터
        from app.config import settings
        
        # Provider: 노드 설정에서 가져오거나, 환경 변수 또는 기본값 사용
        node_provider = self.config.get("provider")
        if node_provider:
            # 노드 설정에 provider가 있으면 사용 (프론트에서 선택한 값)
            provider = node_provider.lower()
        elif settings.llm_provider:
            # 환경 변수에 provider가 있으면 사용
            provider = settings.llm_provider.lower()
        else:
            # 기본값: bedrock (프로덕션 환경)
            provider = "bedrock"
        
        # Model: 노드 설정에서 가져오거나 provider별 기본값 사용
        model = self.config.get("model")
        if not model:
            # provider별 기본 모델
            if provider == "bedrock":
                model = settings.bedrock_model or "anthropic.claude-3-haiku-20240307-v1:0"
            elif provider == "openai":
                model = settings.openai_model or "gpt-3.5-turbo"
            elif provider == "anthropic":
                model = settings.anthropic_model or "claude-sonnet-4-5-20250929"
            elif provider == "google":
                model = settings.google_default_model or "gemini-2.5-flash"
            else:
                model = "anthropic.claude-3-haiku-20240307-v1:0"  # fallback
        
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
                # 검색 결과가 없는 경우 특별한 프롬프트 사용
                if is_no_result:
                    prompt = self._render_prompt(
                        template=(
                            "사용자 질문: {query}\n\n"
                            "{context}\n\n"
                            "위 메시지를 사용자에게 친절하게 전달하세요. "
                            "기본 인사말이나 일반적인 응답을 하지 말고, 검색 결과가 없다는 것을 명확히 알려주세요."
                        ),
                        query=query,
                        context=context_text,
                        system_prompt=system_prompt
                    )
                else:
                    # 기본 프롬프트: 검색 결과가 질문과 관련 있는지 확인하고 관련 없으면 명확히 말하도록 지시
                    prompt = self._render_prompt(
                        template=(
                            "다음은 사용자 질문에 대한 검색 결과입니다:\n\n"
                            "{context}\n\n"
                            "사용자 질문: {query}\n\n"
                            "위 검색 결과를 바탕으로 사용자 질문에 답변하세요. "
                            "**중요**: 검색 결과가 사용자 질문과 직접적으로 관련이 없는 경우, "
                            "'검색 결과에 해당 정보가 없습니다' 또는 '제공된 문서에는 해당 정보가 포함되어 있지 않습니다' "
                            "라고 명확히 말하세요. 검색 결과를 무리하게 해석하거나 관련 없는 정보를 제공하지 마세요."
                        ),
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

        # LLM 호출 (폴백 로직 포함)
        original_model = model
        fallback_attempted = False
        
        try:
            # 기본 시스템 프롬프트: 한국어 응답 강제 + 검색 결과 관련성 검증
            default_system_prompt = (
                "당신은 유능한 AI 어시스턴트입니다. 사용자에게 친절하고 명확하게 답변해야 합니다. "
                "**항상 한국어로 응답하세요.**\n\n"
                "**중요 규칙**:\n"
                "1. 검색 결과가 사용자 질문과 직접적으로 관련이 있는 경우에만 검색 결과를 사용하여 답변하세요.\n"
                "2. 검색 결과가 질문과 관련이 없거나, 질문에 대한 답을 찾을 수 없는 경우, "
                "'검색 결과에 해당 정보가 없습니다' 또는 '제공된 문서에는 해당 정보가 포함되어 있지 않습니다' "
                "라고 명확히 말하세요.\n"
                "3. 검색 결과를 무리하게 해석하거나, 관련 없는 정보를 제공하지 마세요.\n"
                "4. 사용자가 '배송', '주문', '결제' 등을 물어봤는데 검색 결과가 제품 정보만 있다면, "
                "검색 결과에 해당 정보가 없다고 명확히 알려주세요."
            )
            
            # 검색 결과가 없는 경우 추가 지시사항
            if is_no_result:
                default_system_prompt += (
                    "\n\n**검색 결과가 없는 경우, 사용자에게 '해당 지식은 RAG 문서에 등록되지 않았습니다' "
                    "또는 유사한 메시지를 명확하게 전달하세요. 기본 인사말이나 일반적인 응답을 하지 마세요.**"
                )

            # 사용자가 제공한 system_prompt가 있으면 결합, 없으면 기본 시스템 프롬프트만 사용
            final_system_prompt = system_prompt if system_prompt else default_system_prompt
            if system_prompt and system_prompt != default_system_prompt:
                # 사용자 시스템 프롬프트 + 한국어 강제
                final_system_prompt = f"{system_prompt}\n\n**중요: 반드시 한국어로 응답하세요.**"
                if is_no_result:
                    final_system_prompt += (
                        "\n\n**검색 결과가 없는 경우, 사용자에게 명확하게 알려주세요.**"
                    )

            # Provider client 미리 가져오기 (generate 호출 전)
            provider_key = llm_service._resolve_provider(provider, model)
            client = llm_service._get_client(provider_key)
            
            # stream_handler가 있으면 스트리밍 사용, 없으면 일반 생성 사용
            if stream_handler:
                result = await llm_service.generate_stream(
                    prompt=prompt,
                    model=model,
                    provider=provider,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    on_chunk=stream_handler.emit_content_chunk,
                    system_prompt=final_system_prompt
                )
            else:
                result = await llm_service.generate(
                    prompt=prompt,
                    model=model,
                    provider=provider,
                    temperature=temperature,
                    max_tokens=max_tokens
                )

            tokens_used: int = 0
            prompt_tokens: int = 0
            completion_tokens: int = 0
            
            try:
                usage = None
                usage_consumer = getattr(llm_service, "consume_usage_snapshot", None)
                if callable(usage_consumer):
                    usage = usage_consumer(provider_key)

                if not usage and hasattr(client, 'last_usage') and client.last_usage:
                    usage = client.last_usage.copy() if isinstance(client.last_usage, dict) else client.last_usage

                if isinstance(usage, dict):
                    prompt_tokens = usage.get("input_tokens", 0)
                    completion_tokens = usage.get("output_tokens", 0)
                    tokens_used = usage.get("total_tokens", prompt_tokens + completion_tokens)
                    logger.info(
                        f"[LLMNodeV2] Token usage: prompt={prompt_tokens}, completion={completion_tokens}, total={tokens_used}"
                    )
                else:
                    logger.warning(
                        f"[LLMNodeV2] Provider client에서 토큰 사용량을 찾지 못했습니다. provider={provider_key}, model={model}"
                    )
            except Exception as e:
                logger.warning(f"[LLMNodeV2] 토큰 사용량 조회 실패: {e}")

            response_text: str
            if isinstance(result, dict):
                response_text = (
                    result.get("response")
                    or result.get("text")
                    or ""
                )
                # result에 tokens가 있으면 우선 사용 (하지만 last_usage가 더 정확함)
                if tokens_used == 0:
                    tokens_used = result.get("tokens", 0)
            else:
                response_text = str(result)

            model_used = getattr(llm_service, "last_used_model", None) or model
            if model_used != model:
                logger.info(
                    "[LLMNodeV2] Streaming-safe model override: requested=%s, used=%s",
                    model,
                    model_used
                )
                # 로그/메타데이터용 대체 기록
                override_msg = (
                    f"모델 '{model}'은(는) SSE 스트리밍을 지원하지 않아 '{model_used}'로 대체되었습니다."
                )
                context.metadata.setdefault("model_override", {})[self.node_id] = {
                    "requested_model": model,
                    "used_model": model_used,
                    "reason": "streaming_not_supported",
                    "message": override_msg
                }

            logger.info(f"LLMNodeV2: Generated response ({tokens_used} tokens)")
            
            # 응답이 비어있는 경우 경고
            if not response_text or len(response_text.strip()) == 0:
                logger.warning(f"[LLMNodeV2] 응답이 비어있습니다! tokens={tokens_used}, provider={provider}, model={model_used}")
                logger.warning(f"[LLMNodeV2] 프롬프트 길이: {len(prompt)}, context 길이: {len(context_text)}")
            else:
                logger.info(f"[LLMNodeV2] 응답 생성 완료: {len(response_text)} chars")
                logger.debug(f"[LLMNodeV2] 응답 미리보기: {response_text[:200]}...")

            return {
                "response": response_text,
                "tokens": tokens_used,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "model": model_used
            }

        except Exception as e:
            # ON_DEMAND를 지원하지 않는 모델 에러인지 확인
            from app.core.exceptions import LLMAPIError
            from app.config import settings
            
            should_fallback = False
            fallback_model = None
            
            if isinstance(e, LLMAPIError):
                error_details = getattr(e, 'details', {}) or {}
                if error_details.get('requires_provisioned_throughput', False):
                    # ON_DEMAND를 지원하지 않는 모델 → 기본 모델로 폴백
                    should_fallback = True
                    if provider == "bedrock":
                        fallback_model = settings.bedrock_model or "anthropic.claude-3-haiku-20240307-v1:0"
                        logger.warning(
                            f"모델 '{original_model}'이 ON_DEMAND를 지원하지 않습니다. "
                            f"기본 모델 '{fallback_model}'로 자동 폴백합니다."
                        )
                elif error_details.get('requires_responses_endpoint', False):
                    # chat/completions를 지원하지 않는 모델 → 기본 모델로 폴백
                    should_fallback = True
                    if provider == "openai":
                        fallback_model = settings.openai_model or "gpt-3.5-turbo"
                        logger.warning(
                            f"모델 '{original_model}'이 chat/completions를 지원하지 않습니다. "
                            f"기본 모델 '{fallback_model}'로 자동 폴백합니다."
                        )
            
            # 폴백 시도
            if should_fallback and fallback_model and not fallback_attempted:
                fallback_attempted = True
                model = fallback_model
                try:
                    logger.info(f"폴백 모델 '{fallback_model}'로 재시도 중...")
                    if stream_handler:
                        result = await llm_service.generate_stream(
                            prompt=prompt,
                            model=fallback_model,
                            provider=provider,
                            temperature=temperature,
                            max_tokens=max_tokens,
                            on_chunk=stream_handler.emit_content_chunk,
                            system_prompt=final_system_prompt
                        )
                    else:
                        result = await llm_service.generate(
                            prompt=prompt,
                            model=fallback_model,
                            provider=provider,
                            temperature=temperature,
                            max_tokens=max_tokens
                        )
                    
                    # 폴백 성공 - 결과 처리
                    response_text: str
                    tokens_used: int = 0
                    prompt_tokens: int = 0
                    completion_tokens: int = 0

                    if isinstance(result, dict):
                        response_text = (
                            result.get("response")
                            or result.get("text")
                            or ""
                        )
                        tokens_used = result.get("tokens", 0)
                    else:
                        response_text = str(result)

                    # Provider client에서 토큰 정보 가져오기
                    try:
                        provider_key = llm_service._resolve_provider(provider, fallback_model)
                        usage = None
                        usage_consumer = getattr(llm_service, "consume_usage_snapshot", None)
                        if callable(usage_consumer):
                            usage = usage_consumer(provider_key)

                        if not usage:
                            client = llm_service._get_client(provider_key)
                            if hasattr(client, 'last_usage') and client.last_usage:
                                usage = client.last_usage.copy() if isinstance(client.last_usage, dict) else client.last_usage

                        if isinstance(usage, dict):
                            prompt_tokens = usage.get("input_tokens", 0)
                            completion_tokens = usage.get("output_tokens", 0)
                            tokens_used = usage.get("total_tokens", prompt_tokens + completion_tokens)
                            logger.info(
                                f"[LLMNodeV2] Token usage: prompt={prompt_tokens}, completion={completion_tokens}, total={tokens_used}"
                            )
                    except Exception as token_error:
                        logger.warning(f"[LLMNodeV2] 토큰 사용량 조회 실패: {token_error}")

                    logger.info(f"LLMNodeV2: Generated response with fallback model ({tokens_used} tokens)")
                    model_used = getattr(llm_service, "last_used_model", None) or fallback_model
                    if model_used != fallback_model:
                        logger.info(
                            "[LLMNodeV2] Streaming-safe model override after fallback: requested=%s, used=%s",
                            fallback_model,
                            model_used
                        )
                        override_msg = (
                            f"모델 '{fallback_model}'은(는) SSE 스트리밍을 지원하지 않아 "
                            f"'{model_used}'로 대체되었습니다."
                        )
                        context.metadata.setdefault("model_override", {})[self.node_id] = {
                            "requested_model": fallback_model,
                            "used_model": model_used,
                            "reason": "streaming_not_supported",
                            "message": override_msg
                        }
                    
                    return {
                        "response": response_text,
                        "tokens": tokens_used,
                        "prompt_tokens": prompt_tokens,
                        "completion_tokens": completion_tokens,
                        "model": model_used  # 실제 사용된 모델 ID 반환
                    }
                except Exception as fallback_error:
                    logger.error(f"폴백 모델 '{fallback_model}' 호출도 실패: {str(fallback_error)}")
                    raise LLMAPIError(
                        message=(
                            f"원본 모델 '{original_model}'과 폴백 모델 '{fallback_model}' 모두 호출에 실패했습니다. "
                            f"원본 에러: {str(e)}"
                        ),
                        details={
                            "original_model": original_model,
                            "fallback_model": fallback_model,
                            "original_error": str(e),
                            "fallback_error": str(fallback_error)
                        }
                    )
            else:
                # 폴백 불가능한 경우 원래 에러 그대로 전파
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

        # 대화 변수(conversation variables)는 항상 허용 (전역 변수)
        # 프론트엔드에서 프롬프트 템플릿에 사용할 수 있도록 항상 포함
        # VariablePool에 실제로 존재하는 conversation variables를 가져와서 추가
        if context.variable_pool:
            conversation_vars = context.variable_pool.get_all_conversation_variables()
            for var_name in conversation_vars.keys():
                # conv.var_name과 conversation.var_name 두 형식 모두 허용
                allowed.append(f"conv.{var_name}")
                allowed.append(f"conversation.{var_name}")

        # 중복 제거
        allowed = list(set(allowed))

        logger.info(f"[LLMNodeV2] 허용된 변수 셀렉터: {len(allowed)}개")
        logger.debug(f"[LLMNodeV2] 허용된 셀렉터 목록 (샘플): {allowed[:10]}...")

        return allowed

    def _is_no_result_context(self, context_text: Any) -> bool:
        """지식 노드의 '검색 결과 없음' 메시지인지 판별"""
        if not context_text:
            return False

        text = context_text if isinstance(context_text, str) else str(context_text)
        markers = [
            "검색 결과가 없습니다",
            "해당 질문에 대한 정보가 RAG 문서에 등록되지 않았습니다",
        ]
        return any(marker in text for marker in markers)

    def _find_alternative_context(
        self,
        context: NodeExecutionContext
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        지식 노드가 '검색 결과 없음'을 반환했을 때 사용할 대체 컨텍스트를 찾는다.

        이미 실행된 노드 중에서 유효한 context/retrieved_documents/results 출력이 있는
        최신 노드를 우선적으로 사용한다.
        """
        if not context or not getattr(context, "variable_pool", None):
            return None, None

        executed_nodes = getattr(context, "executed_nodes", []) or []
        pool = context.variable_pool

        for node_id in reversed(executed_nodes):
            if not node_id or node_id == self.node_id:
                continue

            node_outputs = pool.get_all_node_outputs(node_id)
            if not node_outputs:
                continue

            # 1) 문자열 context가 있으면 우선 사용
            ctx_value = node_outputs.get("context")
            if isinstance(ctx_value, str) and ctx_value.strip() and not self._is_no_result_context(ctx_value):
                return ctx_value, node_id

            # 2) retrieved_documents 배열을 병합
            docs = node_outputs.get("retrieved_documents")
            if isinstance(docs, list) and docs:
                doc_texts = []
                for doc in docs:
                    if isinstance(doc, dict):
                        content = doc.get("content") or doc.get("text")
                        if content:
                            doc_texts.append(str(content))
                    elif isinstance(doc, str):
                        doc_texts.append(doc)

                merged_docs = "\n\n".join([d for d in doc_texts if d])
                if merged_docs and not self._is_no_result_context(merged_docs):
                    return merged_docs, node_id

            # 3) 검색 결과 배열(results)을 단순 병합
            results = node_outputs.get("results")
            if isinstance(results, list) and results:
                parts = []
                for item in results:
                    if isinstance(item, dict):
                        snippet = item.get("content") or item.get("title")
                        if snippet:
                            parts.append(str(snippet))
                    elif isinstance(item, str):
                        parts.append(item)

                merged_results = "\n\n".join([p for p in parts if p])
                if merged_results and not self._is_no_result_context(merged_results):
                    return merged_results, node_id

        return None, None
