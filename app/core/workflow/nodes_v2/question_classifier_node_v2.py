"""
Question Classifier 노드 (V2)

사용자 질문을 사전에 정의된 카테고리로 분류하고
클래스별 분기 출력을 제공하는 노드입니다.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
import logging

from app.core.workflow.base_node_v2 import BaseNodeV2, NodeExecutionContext
from app.schemas.workflow import NodePortSchema, PortDefinition, PortType
from app.services.llm_service import LLMService
from app.core.workflow.nodes_v2.utils.template_renderer import (
    TemplateRenderer,
    TemplateRenderError,
)

logger = logging.getLogger(__name__)


class QuestionClassifierNodeV2(BaseNodeV2):
    """
    질문 분류 노드

    입력:
        - query (string, required)
        - files (array_file, optional – Vision 모드)

    출력:
        - class_name (string)
        - usage (object)
        - class_{id}_branch (boolean) — 클래스별 브랜치
    """

    def get_port_schema(self) -> NodePortSchema:
        classes = self._get_classes()
        vision_enabled = bool(self.config.get("vision", {}).get("enabled"))

        inputs = [
            PortDefinition(
                name="query",
                type=PortType.STRING,
                required=True,
                description="분류 대상 질문",
                display_name="질문",
            )
        ]

        if vision_enabled:
            inputs.append(
                PortDefinition(
                    name="files",
                    type=PortType.ARRAY_FILE,
                    required=False,
                    description="Vision 모델로 전달할 파일(이미지) 목록",
                    display_name="파일",
                )
            )

        outputs: List[PortDefinition] = [
            PortDefinition(
                name="class_name",
                type=PortType.STRING,
                required=True,
                description="선택된 클래스 이름",
                display_name="Class Name",
            ),
            PortDefinition(
                name="query",
                type=PortType.STRING,
                required=True,
                description="입력된 원본 질문 (pass-through)",
                display_name="질문",
            ),
            PortDefinition(
                name="usage",
                type=PortType.OBJECT,
                required=False,
                description="LLM 토큰 사용량 정보",
                display_name="Usage",
            ),
        ]

        for topic in classes:
            # topic['id']가 이미 'class_'로 시작하면 제거하고 다시 추가
            topic_id = topic['id']
            if topic_id.startswith('class_'):
                topic_id = topic_id[6:]  # 'class_' 제거 (6자)
            port_name = f"class_{topic_id}_branch"
            
            outputs.append(
                PortDefinition(
                    name=port_name,
                    type=PortType.BOOLEAN,
                    required=True,
                    description=f"'{topic['name']}' 분기가 선택되면 true",
                    display_name=topic["name"],
                )
            )

        return NodePortSchema(inputs=inputs, outputs=outputs)

    async def execute_v2(self, context: NodeExecutionContext) -> Dict[str, Any]:
        query = context.get_input("query")
        query_template = (self.config.get("query_template") or "").strip()

        if query_template:
            query = self._render_query_template(
                context=context,
                template=query_template,
                fallback=query if isinstance(query, str) else "",
            )
        
        classes = self._get_classes()
        if not classes:
            raise ValueError("Question Classifier 노드에는 최소 1개의 클래스가 필요합니다")
        
        # 피드백 분류인 경우, query_template이 없으면 system.user_message를 자동으로 사용
        if not query_template:
            class_names = [topic["name"] for topic in classes]
            is_feedback_classification = any(
                "마음에" in name or "만족" in name or "좋아" in name or "불만" in name
                for name in class_names
            )
            
            if is_feedback_classification:
                # system.user_message를 시도
                try:
                    system_user_message = context.variable_pool.resolve_value_selector("system.user_message")
                    if system_user_message and isinstance(system_user_message, str) and system_user_message.strip():
                        query = system_user_message.strip()
                        logger.info(
                            "QuestionClassifierNodeV2 using system.user_message for feedback: '%s'",
                            query,
                        )
                except Exception as e:
                    logger.debug(
                        "QuestionClassifierNodeV2 could not resolve system.user_message: %s, using provided query",
                        e,
                    )

        if not query or not isinstance(query, str):
            raise ValueError("Question Classifier 노드에는 query 입력이 필요합니다")

        logger.info(
            "QuestionClassifierNodeV2 query input: '%s' (length: %d)",
            query,
            len(query),
        )

        llm_service: Optional[LLMService] = context.get_service("llm_service")
        if not llm_service:
            raise ValueError("LLM 서비스가 ServiceContainer에 등록되어 있지 않습니다")

        model_config = self._normalize_model_config()
        prompt = self._build_prompt(query, classes)
        logger.debug(
            "QuestionClassifierNodeV2 prompt (length: %d):\n%s",
            len(prompt),
            prompt[:500] + "..." if len(prompt) > 500 else prompt,
        )
        temperature = model_config["completion_params"]["temperature"]
        max_tokens = model_config["completion_params"]["max_tokens"]

        logger.info(
            "QuestionClassifierNodeV2 executing (model=%s provider=%s classes=%s)",
            model_config["name"],
            model_config["provider"],
            [topic["name"] for topic in classes],
        )

        # LLM을 사용하여 사용자 피드백을 클래스로 분류
        class_names = [topic["name"] for topic in classes]
        
        llm_response = await llm_service.generate(
            prompt=prompt,
            model=model_config["name"],
            provider=model_config["provider"],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        raw_text, tokens_used = self._extract_llm_result(llm_response)
        logger.info(
            "QuestionClassifierNodeV2 LLM raw response: '%s' (length: %d)",
            raw_text,
            len(raw_text),
        )
        resolved_class = self._parse_classification(
            raw_text,
            class_names,
        )
        logger.info(
            "QuestionClassifierNodeV2 parsed class: '%s' (from raw: '%s', query: '%s')",
            resolved_class,
            raw_text,
            query,
        )

        outputs: Dict[str, Any] = {
            "class_name": resolved_class,
            "query": query,  # 원본 query를 pass-through
            "usage": {
                "total_tokens": tokens_used,
            },
        }

        # 출력 포트 이름과 핸들을 일치시키기 위해 포트 이름을 직접 사용
        matched_topic = None
        matched_port_name = None
        
        for topic in classes:
            # topic['id']가 이미 'class_'로 시작하면 제거하고 다시 추가
            topic_id = topic['id']
            if topic_id.startswith('class_'):
                topic_id = topic_id[6:]  # 'class_' 제거 (6자)
            port_name = f"class_{topic_id}_branch"
            
            is_matched = topic["name"] == resolved_class
            outputs[port_name] = is_matched
            
            if is_matched:
                matched_topic = topic
                matched_port_name = port_name
        
        if matched_port_name:
            context.set_next_edge_handle([matched_port_name])

        return outputs

    def _normalize_model_config(self) -> Dict[str, Any]:
        """
        프론트엔드에서 전달받은 모델 설정을 정규화
        
        프론트엔드에서 ModelConfig 객체 { provider, name, mode, completion_params } 형태로 전달됨
        name 필드에는 실제 모델 ID가 저장되어 있음 (예: "anthropic.claude-3-5-sonnet-20240620-v1:0")
        """
        raw_model = self.config.get("model") or {}

        if isinstance(raw_model, str):
            # 문자열인 경우 (하위 호환성)
            raw_model = {"name": raw_model}

        # 프론트엔드에서 선택한 provider와 model을 그대로 사용
        provider = (raw_model.get("provider") or "bedrock").lower()
        name = raw_model.get("name") or "anthropic.claude-3-haiku-20240307-v1:0"
        
        # provider가 없으면 모델명으로부터 추론
        if not raw_model.get("provider") and name:
            model_str = name.lower()
            if model_str.startswith("anthropic.claude") or "amazon.titan" in model_str:
                provider = "bedrock"
            elif model_str.startswith("gpt") or model_str.startswith("o1") or model_str.startswith("o3"):
                provider = "openai"
            elif model_str.startswith("claude"):
                provider = "anthropic"
            elif "gemini" in model_str:
                provider = "google"

        completion = raw_model.get("completion_params") or {}
        temperature = completion.get("temperature")
        max_tokens = completion.get("max_tokens")

        try:
            temperature = float(temperature)
        except (TypeError, ValueError):
            temperature = 0.3

        try:
            max_tokens = int(max_tokens)
        except (TypeError, ValueError):
            max_tokens = 64

        return {
            "provider": provider,
            "name": name,
            "completion_params": {
                "temperature": min(max(temperature, 0.0), 1.0),
                "max_tokens": max(max_tokens, 16),
            },
        }

    def _get_classes(self) -> List[Dict[str, str]]:
        classes = self.config.get("classes") or []
        normalized: List[Dict[str, str]] = []

        for index, topic in enumerate(classes):
            if not isinstance(topic, dict):
                continue

            name = (topic.get("name") or "").strip()
            if not name:
                continue

            topic_id = topic.get("id") or self._slugify(name) or f"class_{index}"
            normalized.append({"id": topic_id, "name": name})

        return normalized

    def _build_prompt(self, query: str, classes: List[Dict[str, str]]) -> str:
        formatted_classes = "\n".join(f"- {topic['name']}" for topic in classes)
        custom_instruction = (self.config.get("instruction") or "").strip()

        # 클래스 이름에서 피드백 분류 여부 확인 (특수 처리)
        class_names = [topic['name'] for topic in classes]
        is_feedback_classification = any(
            "마음에" in name or "만족" in name or "좋아" in name or "불만" in name
            for name in class_names
        )

        if is_feedback_classification:
            # 클래스 이름에서 긍정/부정 추론
            positive_class = None
            negative_class = None
            for name in class_names:
                if "들지 않는" in name or "안" in name or "불만" in name:
                    negative_class = name
                elif ("마음에 드는" in name or "만족" in name) and "들지 않는" not in name:
                    positive_class = name
            
            if positive_class and negative_class:
                base_instruction = (
                    "You are a feedback classifier. "
                    "The user was previously asked '마음에 드시나요?' (Are you satisfied?) and is now responding with their feedback.\n\n"
                    f"Analyze the user's feedback message and classify it into ONE of these two categories:\n"
                    f"1. \"{positive_class}\" - If the user indicates satisfaction, approval, or positive sentiment\n"
                    f"2. \"{negative_class}\" - If the user indicates dissatisfaction, disapproval, or negative sentiment\n\n"
                    "You MUST respond with EXACTLY one of the category names above, using the exact same wording. "
                    "Do not use abbreviations, variations, or your own words. Only use the exact category name."
                )
            else:
                base_instruction = (
                    "You are a feedback classifier. "
                    "The user was previously asked '마음에 드시나요?' (Are you satisfied?) and is now responding with their feedback. "
                    "Analyze the user's feedback message and classify it into one of the categories below.\n\n"
                    "You MUST respond with EXACTLY one of the category names listed below, word-for-word. "
                    "Do not use abbreviations or variations."
                )
        else:
            base_instruction = (
                "You are a question classifier. "
                "Choose the single most appropriate category from the list below. "
                "You MUST respond with EXACTLY one of the category names listed below, word-for-word. "
                "Do not use abbreviations or variations."
            )

        # 피드백 분류인 경우 예시 추가
        if is_feedback_classification and len(classes) == 2:
            # 긍정/부정 분류 예시 생성 (사용자가 실제로 사용하는 다양한 표현 포함)
            positive_examples = [
                "ㅇㅇ", "어", "괜찮네", "맘에 들어", "마음에 든다구", "마음에 들어", 
                "좋아요", "만족해요", "좋아", "괜찮아", "좋습니다", "괜찮아요"
            ]
            negative_examples = [
                "별론데", "그닥", "더 좋은거 없어", "마음에 안들어", "안들어", 
                "별로야", "불만족", "싫어", "다시 찾아줘", "다른거", "아니야"
            ]
            
            # 어떤 클래스가 긍정/부정인지 추론
            positive_class = None
            negative_class = None
            for name in class_names:
                if "들지 않는" in name or "안" in name or "불만" in name:
                    negative_class = name
                elif ("마음에 드는" in name or "만족" in name) and "들지 않는" not in name:
                    positive_class = name
            
            if positive_class and negative_class:
                examples_text = "\nExamples (POSITIVE → satisfied, NEGATIVE → dissatisfied):\n"
                # 더 많은 예시 추가 (5개씩)
                for example in positive_examples[:5]:
                    examples_text += f"  Input: \"{example}\" → Output: \"{positive_class}\"\n"
                for example in negative_examples[:5]:
                    examples_text += f"  Input: \"{example}\" → Output: \"{negative_class}\"\n"
            else:
                examples_text = ""
        else:
            examples_text = ""

        if custom_instruction:
            instruction_block = f"{base_instruction}\n\nAdditional instructions:\n{custom_instruction}"
        else:
            instruction_block = base_instruction

        if is_feedback_classification and positive_class and negative_class:
            # 피드백 분류인 경우 더 명확한 형식
            return (
                f"{instruction_block}\n\n"
                f"User's feedback message:\n{query}\n\n"
                f"Classify this feedback into one of these categories:\n"
                f"- \"{positive_class}\"\n"
                f"- \"{negative_class}\"\n\n"
                f"Your response must be EXACTLY one of the category names above (including quotation marks if shown). "
                f"Do not add any explanation, just the category name."
            )
        else:
            return (
                f"{instruction_block}\n\n"
                f"Available categories (respond with EXACT category name):\n{formatted_classes}\n"
                f"{examples_text}\n"
                f"User Question:\n{query}\n\n"
                "Answer with EXACTLY one category name from the list above, using the exact same wording."
            )

    def _extract_llm_result(self, result: Any) -> tuple[str, int]:
        if isinstance(result, dict):
            text = (
                result.get("response")
                or result.get("text")
                or result.get("content")
                or ""
            )
            usage = result.get("tokens") or result.get("usage", {}).get("total_tokens", 0)
            return str(text), int(usage or 0)

        return str(result), 0

    def _parse_classification(self, raw_text: str, valid_classes: List[str]) -> str:
        """
        LLM 응답을 파싱하여 유효한 클래스 이름을 반환합니다.
        LLM이 이미 분류를 수행하므로, 하드코딩된 키워드 매칭 없이 LLM 응답을 신뢰합니다.
        """
        cleaned = (raw_text or "").strip()
        normalized_classes = [name.lower() for name in valid_classes]
        cleaned_lower = cleaned.lower()

        # 1. 정확한 매칭 (대소문자 무시)
        if cleaned_lower in normalized_classes:
            original_index = normalized_classes.index(cleaned_lower)
            logger.debug(
                "QuestionClassifierNodeV2 exact match: '%s' → '%s'",
                cleaned,
                valid_classes[original_index],
            )
            return valid_classes[original_index]

        # 2. 부분 매칭: LLM 응답에 클래스 이름이 포함되어 있는지 확인
        # (LLM이 약간 다른 형식으로 응답했을 경우 대비)
        best_match = None
        best_match_length = 0
        
        for original, normalized in zip(valid_classes, normalized_classes):
            # LLM 응답에 클래스 이름이 포함되어 있거나, 클래스 이름에 LLM 응답이 포함되어 있는지 확인
            if normalized in cleaned_lower or cleaned_lower in normalized:
                match_length = min(len(normalized), len(cleaned_lower))
                if match_length > best_match_length:
                    best_match = original
                    best_match_length = match_length
        
        if best_match:
            logger.debug(
                "QuestionClassifierNodeV2 partial match: '%s' → '%s'",
                cleaned,
                best_match,
            )
            return best_match

        logger.warning(
            "QuestionClassifierNodeV2 could not parse class from '%s', defaulting to first. Valid classes: %s",
            raw_text,
            valid_classes,
        )
        return valid_classes[0]

    @staticmethod
    def _slugify(value: str) -> str:
        return (
            value.lower()
            .replace(" ", "_")
            .replace("/", "_")
            .replace("__", "_")
            .strip("_")
        )

    def _render_query_template(
        self,
        context: NodeExecutionContext,
        template: str,
        fallback: str,
    ) -> str:
        """
        TemplateRenderer를 사용해 query_template을 렌더링한다.
        """
        try:
            rendered_group, metadata = TemplateRenderer.render(template, context.variable_pool)
            context.metadata.setdefault("question_classifier", {})[self.node_id] = metadata
            return rendered_group.text
        except TemplateRenderError as exc:
            logger.error(
                "QuestionClassifierNodeV2 failed to render query template: %s",
                exc,
            )
            if fallback:
                return fallback
            raise ValueError(f"Failed to render query_template: {exc}") from exc
