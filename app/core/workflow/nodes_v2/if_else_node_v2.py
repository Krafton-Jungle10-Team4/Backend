"""
IF-ELSE 노드 (V2)

조건을 평가하여 단일 분기를 활성화하는 노드입니다.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
import logging

from app.core.workflow.base_node_v2 import BaseNodeV2, NodeExecutionContext
from app.schemas.workflow import NodePortSchema, PortDefinition, PortType
from app.core.workflow.variable_pool import VariablePool

logger = logging.getLogger(__name__)


class IfElseNodeV2(BaseNodeV2):
    """
    IF-ELSE 분기 노드

    cases 구성:
        [
            {
                "case_id": "case_1",
                "logical_operator": "and" | "or",
                "conditions": [
                    {
                        "variable_selector": "node_id.port_name",
                        "comparison_operator": "=" | ">" | ...,
                        "value": "...",
                        "varType": "string" | "number" | "boolean",
                    }
                ]
            },
            ...
        ]
    """

    def get_port_schema(self) -> NodePortSchema:
        cases = self._get_cases()
        outputs: List[PortDefinition] = []

        for index, _case in enumerate(cases):
            port_name = "if" if index == 0 else f"elif_{index}"
            label = "IF" if index == 0 else f"ELIF {index}"
            outputs.append(
                PortDefinition(
                    name=port_name,
                    type=PortType.BOOLEAN,
                    required=True,
                    description=f"{label} 분기가 선택되면 true",
                    display_name=label,
                )
            )

        outputs.append(
            PortDefinition(
                name="else",
                type=PortType.BOOLEAN,
                required=True,
                description="모든 조건이 거짓일 때 true",
                display_name="ELSE",
            )
        )

        return NodePortSchema(inputs=[], outputs=outputs)

    async def execute_v2(self, context: NodeExecutionContext) -> Dict[str, Any]:
        cases = self._get_cases()
        matched_index = self._evaluate_cases(cases, context.variable_pool)

        outputs: Dict[str, Any] = {}
        for index, _ in enumerate(cases):
            port_name = "if" if index == 0 else f"elif_{index}"
            outputs[port_name] = matched_index == index

        outputs["else"] = matched_index is None

        handle_candidates = []
        if matched_index is not None:
            port_name = "if" if matched_index == 0 else f"elif_{matched_index}"
            handle_candidates.append(port_name)
            case = cases[matched_index]
            case_id = case.get("case_id")
            if case_id:
                handle_candidates.append(case_id)
        else:
            handle_candidates.append("else")

        context.set_next_edge_handle(handle_candidates)
        return outputs

    def _get_cases(self) -> List[Dict[str, Any]]:
        raw_cases = self.config.get("cases") or []
        if not isinstance(raw_cases, list):
            return []
        return [case for case in raw_cases if isinstance(case, dict)]

    def _evaluate_cases(
        self,
        cases: List[Dict[str, Any]],
        variable_pool: VariablePool,
    ) -> Optional[int]:
        for index, case in enumerate(cases):
            conditions = case.get("conditions") or []
            logical_operator = (case.get("logical_operator") or "and").lower()

            if not conditions:
                logger.info(
                    "IfElseNodeV2 case %s has no conditions, treating as match",
                    case.get("case_id"),
                )
                return index

            results = [
                self._evaluate_condition(condition, variable_pool)
                for condition in conditions
            ]

            if logical_operator == "or":
                is_match = any(results)
            else:
                is_match = all(results)

            if is_match:
                return index

        return None

    def _evaluate_condition(
        self,
        condition: Dict[str, Any],
        variable_pool: VariablePool,
    ) -> bool:
        selector = condition.get("variable_selector")
        operator = str(condition.get("comparison_operator") or "").lower()
        expected_value = condition.get("value")
        var_type = (condition.get("varType") or "string").lower()

        if not selector or not isinstance(selector, str):
            logger.warning("IfElseNodeV2 condition missing selector: %s", condition)
            return False

        actual_value = variable_pool.resolve_value_selector(selector)

        if operator in {"empty", "not empty"}:
            is_empty = (
                actual_value is None
                or actual_value == ""
                or (hasattr(actual_value, "__len__") and len(actual_value) == 0)
            )
            return is_empty if operator == "empty" else not is_empty

        if operator in {"is", "is not"}:
            operator = "=" if operator == "is" else "≠"

        try:
            if var_type == "number":
                actual_value = self._to_number(actual_value)
                expected_value = self._to_number(expected_value)
            elif var_type == "boolean":
                actual_value = self._to_bool(actual_value)
                expected_value = self._to_bool(expected_value)
            else:
                actual_value = "" if actual_value is None else str(actual_value)
                expected_value = "" if expected_value is None else str(expected_value)
        except (TypeError, ValueError):
            logger.warning(
                "IfElseNodeV2 failed to cast values (selector=%s)",
                selector,
            )
            return False

        return self._compare_values(actual_value, expected_value, operator)

    @staticmethod
    def _compare_values(actual: Any, expected: Any, operator: str) -> bool:
        if operator == "=":
            return actual == expected
        if operator == "≠":
            return actual != expected
        if operator == ">":
            return actual > expected
        if operator == "<":
            return actual < expected
        if operator == "≥":
            return actual >= expected
        if operator == "≤":
            return actual <= expected
        if operator == "contains":
            return str(expected).lower() in str(actual).lower()

        logger.warning("IfElseNodeV2 received unknown operator: %s", operator)
        return False

    @staticmethod
    def _to_number(value: Any) -> float:
        if value is None:
            raise ValueError("Cannot convert None to number")
        return float(value)

    @staticmethod
    def _to_bool(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lowered = value.lower()
            if lowered in {"true", "1", "yes"}:
                return True
            if lowered in {"false", "0", "no"}:
                return False
        if isinstance(value, (int, float)):
            return value != 0
        raise ValueError("Cannot convert value to boolean")
