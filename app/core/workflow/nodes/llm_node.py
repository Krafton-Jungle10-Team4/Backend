"""
LLM 노드 구현

언어 모델을 사용하여 응답을 생성하는 노드입니다.
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


class LLMNodeConfig(NodeConfig):
    """LLM 노드 설정"""
    model: str = Field(..., description="사용할 LLM 모델")
    prompt_template: str = Field(
        default="Context: {context}\nQuestion: {question}\nAnswer:",
        description="프롬프트 템플릿"
    )
    temperature: float = Field(default=0.7, ge=0.0, le=1.0, description="Temperature")
    max_tokens: int = Field(default=500, ge=1, le=4000, description="최대 토큰 수")
    use_context_from: Optional[List[str]] = Field(
        default=None,
        description="컨텍스트로 사용할 노드 ID 리스트"
    )


@register_node(NodeType.LLM)
class LLMNode(BaseNode[LLMNodeConfig]):
    """
    LLM 노드

    이전 노드들의 출력(주로 Knowledge 노드의 검색 결과)을 바탕으로
    언어 모델을 사용하여 응답을 생성합니다.
    """

    def __init__(
        self,
        node_id: str,
        node_type: NodeType = NodeType.LLM,
        config: Optional[LLMNodeConfig] = None,
        position: Optional[Dict[str, float]] = None
    ):
        super().__init__(node_id, node_type, config, position)

    async def execute(self, context: Dict[str, Any]) -> NodeExecutionResult:
        """
        LLM 실행

        Args:
            context: 실행 컨텍스트

        Returns:
            NodeExecutionResult: 생성된 응답
        """
        try:
            self.set_status(NodeStatus.RUNNING)

            if not self.config:
                raise ValueError("LLM node requires configuration")

            # 사용자 메시지 가져오기
            user_message = context.get("user_message")
            if not user_message:
                node_outputs = context.get("node_outputs", {})
                for output in node_outputs.values():
                    if isinstance(output, dict) and "user_message" in output:
                        user_message = output["user_message"]
                        break

            if not user_message:
                raise ValueError("User message not found in context")

            # 컨텍스트 수집
            combined_context = self._collect_context(context)

            # LLM 서비스 가져오기
            llm_service = context.get("llm_service")
            if not llm_service:
                raise ValueError("LLM service not found in context")

            # 프롬프트 생성
            prompt = self._create_prompt(user_message, combined_context)

            # LLM 호출
            stream_handler = context.get("stream_handler")
            text_normalizer = context.get("text_normalizer")

            llm_response = await self._call_llm(
                llm_service,
                prompt,
                self.config.model,
                self.config.temperature,
                self.config.max_tokens,
                stream_handler=stream_handler,
                text_normalizer=text_normalizer
            )

            result = NodeExecutionResult(
                status=NodeStatus.COMPLETED,
                output={
                    "llm_response": llm_response,
                    "model": self.config.model,
                    "prompt": prompt,
                    "context_used": bool(combined_context)
                },
                metadata={
                    "node_id": self.node_id,
                    "node_type": self.node_type.value,
                    "model": self.config.model,
                    "temperature": self.config.temperature
                }
            )

            self.set_status(NodeStatus.COMPLETED)
            logger.info(f"LLM node {self.node_id} generated response using {self.config.model}")

            return result

        except Exception as e:
            logger.error(f"LLM node execution failed: {str(e)}")
            self.set_status(NodeStatus.FAILED)
            return NodeExecutionResult(
                status=NodeStatus.FAILED,
                error=str(e)
            )

    def _collect_context(self, context: Dict[str, Any]) -> str:
        """
        이전 노드들의 출력에서 컨텍스트 수집

        Args:
            context: 실행 컨텍스트

        Returns:
            결합된 컨텍스트 문자열
        """
        combined_context = []
        node_outputs = context.get("node_outputs", {})

        # use_context_from이 지정된 경우 해당 노드들의 출력만 사용
        if self.config and self.config.use_context_from:
            target_nodes = self.config.use_context_from
        else:
            # 모든 Knowledge 노드의 출력 사용
            target_nodes = [node_id for node_id in node_outputs.keys()
                           if "knowledge" in node_id.lower()]

        for node_id in target_nodes:
            if node_id in node_outputs:
                output = node_outputs[node_id]
                if isinstance(output, dict) and "retrieved_documents" in output:
                    docs = output["retrieved_documents"]
                    if isinstance(docs, list):
                        for doc in docs:
                            if isinstance(doc, dict) and "content" in doc:
                                combined_context.append(doc["content"])
                            elif isinstance(doc, str):
                                combined_context.append(doc)

        return "\n\n".join(combined_context)

    def _create_prompt(self, question: str, context: str) -> str:
        """
        프롬프트 생성

        Args:
            question: 사용자 질문
            context: 검색된 컨텍스트

        Returns:
            생성된 프롬프트
        """
        if self.config and self.config.prompt_template:
            prompt = self.config.prompt_template.replace("{question}", question)
            prompt = prompt.replace("{context}", context)
            return prompt
        else:
            # 기본 프롬프트
            if context:
                return f"Context: {context}\n\nQuestion: {question}\n\nAnswer:"
            else:
                return f"Question: {question}\n\nAnswer:"

    async def _call_llm(
        self,
        llm_service,
        prompt: str,
        model: str,
        temperature: float,
        max_tokens: int,
        stream_handler=None,
        text_normalizer=None
    ) -> str:
        """
        LLM 서비스 호출

        Args:
            llm_service: LLM 서비스
            prompt: 프롬프트
            model: 모델 이름
            temperature: Temperature
            max_tokens: 최대 토큰 수

        Returns:
            생성된 응답
        """
        try:
            # LLM 서비스의 generate 메서드 호출
            if stream_handler:
                async def on_chunk(chunk: str):
                    return await stream_handler.emit_content_chunk(chunk)

                response = await llm_service.generate_stream(
                    prompt=prompt,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    on_chunk=on_chunk
                )
            else:
                response = await llm_service.generate(
                    prompt=prompt,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens
                )
                if text_normalizer:
                    response = text_normalizer(response)

            return response

        except Exception as e:
            logger.error(f"LLM call failed: {str(e)}")
            raise

    def validate(self) -> tuple[bool, Optional[str]]:
        """
        LLM 노드 검증

        Returns:
            tuple: (유효 여부, 오류 메시지)
        """
        if not self.config:
            return False, "LLM node requires configuration"

        if not self.config.model:
            return False, "Model is required"

        if self.config.temperature < 0 or self.config.temperature > 1:
            return False, "Temperature must be between 0 and 1"

        if self.config.max_tokens < 1 or self.config.max_tokens > 4000:
            return False, "max_tokens must be between 1 and 4000"

        if len(self.inputs) == 0:
            return False, "LLM node must have at least one input"

        if len(self.outputs) == 0:
            return False, "LLM node must have at least one output"

        return True, None

    @classmethod
    def get_schema(cls) -> NodeSchema:
        """
        LLM 노드 스키마 반환

        Returns:
            NodeSchema: 노드 스키마
        """
        return NodeSchema(
            type=NodeType.LLM,
            label="LLM",
            icon="brain",
            max_instances=-1,  # 무제한
            configurable=True,
            config_schema={
                "model": {
                    "type": "enum",
                    "options": ["gpt-4", "gpt-3.5-turbo", "claude-3"],
                    "required": True,
                    "description": "사용할 LLM 모델"
                },
                "prompt_template": {
                    "type": "text",
                    "required": False,
                    "default": "Context: {context}\nQuestion: {question}\nAnswer:",
                    "description": "프롬프트 템플릿"
                },
                "temperature": {
                    "type": "number",
                    "min": 0,
                    "max": 1,
                    "default": 0.7,
                    "description": "Temperature"
                },
                "max_tokens": {
                    "type": "number",
                    "min": 1,
                    "max": 4000,
                    "default": 500,
                    "description": "최대 토큰 수"
                },
                "use_context_from": {
                    "type": "array",
                    "items": "string",
                    "required": False,
                    "description": "컨텍스트로 사용할 노드 ID 리스트"
                }
            },
            input_required=True,
            output_provided=True
        )

    @classmethod
    def get_config_class(cls) -> type[NodeConfig]:
        """설정 클래스 반환"""
        return LLMNodeConfig

    def get_required_context_keys(self) -> list[str]:
        """필요한 컨텍스트 키 목록"""
        return ["llm_service"]
