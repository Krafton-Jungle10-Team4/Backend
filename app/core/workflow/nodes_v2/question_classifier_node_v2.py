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
                name="usage",
                type=PortType.OBJECT,
                required=False,
                description="LLM 토큰 사용량 정보",
                display_name="Usage",
            ),
        ]

        for topic in classes:
            outputs.append(
                PortDefinition(
                    name=f"class_{topic['id']}_branch",
                    type=PortType.BOOLEAN,
                    required=True,
                    description=f"'{topic['name']}' 분기가 선택되면 true",
                    display_name=topic["name"],
                )
            )

        return NodePortSchema(inputs=inputs, outputs=outputs)

    async def execute_v2(self, context: NodeExecutionContext) -> Dict[str, Any]:
        query = context.get_input("query")
        if not query or not isinstance(query, str):
            raise ValueError("Question Classifier 노드에는 query 입력이 필요합니다")

        classes = self._get_classes()
        if not classes:
            raise ValueError("Question Classifier 노드에는 최소 1개의 클래스가 필요합니다")

        llm_service: Optional[LLMService] = context.get_service("llm_service")
        if not llm_service:
            raise ValueError("LLM 서비스가 ServiceContainer에 등록되어 있지 않습니다")

        model_config = self._normalize_model_config()
        prompt = self._build_prompt(query, classes)
        temperature = model_config["completion_params"]["temperature"]
        max_tokens = model_config["completion_params"]["max_tokens"]

        logger.info(
            "QuestionClassifierNodeV2 executing (model=%s provider=%s classes=%s)",
            model_config["name"],
            model_config["provider"],
            [topic["name"] for topic in classes],
        )

        llm_response = await llm_service.generate(
            prompt=prompt,
            model=model_config["name"],
            provider=model_config["provider"],
            temperature=temperature,
            max_tokens=max_tokens,
        )

        raw_text, tokens_used = self._extract_llm_result(llm_response)
        resolved_class = self._parse_classification(
            raw_text,
            [topic["name"] for topic in classes],
        )

        outputs: Dict[str, Any] = {
            "class_name": resolved_class,
            "usage": {
                "total_tokens": tokens_used,
            },
        }

        for topic in classes:
            outputs[f"class_{topic['id']}_branch"] = topic["name"] == resolved_class

        return outputs

    def _normalize_model_config(self) -> Dict[str, Any]:
        raw_model = self.config.get("model") or {}

        if isinstance(raw_model, str):
            raw_model = {"name": raw_model}

        provider = (raw_model.get("provider") or "openai").lower()
        name = raw_model.get("name") or "gpt-4o-mini"

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

        base_instruction = (
            "You are a question classifier. "
            "Choose the single most appropriate category from the list below. "
            "Respond with ONLY the category name."
        )

        if custom_instruction:
            instruction_block = f"{base_instruction}\n\nAdditional instructions:\n{custom_instruction}"
        else:
            instruction_block = base_instruction

        return (
            f"{instruction_block}\n\n"
            f"Available categories:\n{formatted_classes}\n\n"
            f"User Question:\n{query}\n\n"
            "Answer with exactly one category name."
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
        cleaned = (raw_text or "").strip().lower()
        normalized_classes = [name.lower() for name in valid_classes]

        if cleaned in normalized_classes:
            original_index = normalized_classes.index(cleaned)
            return valid_classes[original_index]

        for original, normalized in zip(valid_classes, normalized_classes):
            if normalized in cleaned:
                return original

        logger.warning(
            "QuestionClassifierNodeV2 could not parse class from '%s', defaulting to first",
            raw_text,
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
