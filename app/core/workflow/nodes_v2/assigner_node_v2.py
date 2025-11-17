"""
Assigner Node V2 - 포트 기반 변수 조작 노드

11가지 WriteMode 작업을 지원하며, 다중 작업 순차 실행이 가능합니다.
variable_mappings와 NodeExecutionContext 기반으로 입력을 해석합니다.
"""

from typing import Any, Dict, List, Optional
import logging

from app.core.workflow.base_node_v2 import BaseNodeV2, NodeExecutionContext
from app.schemas.workflow import (
    NodePortSchema,
    PortDefinition,
    PortType,
    WriteMode,
    AssignerOperation,
    AssignerInputType,
)

logger = logging.getLogger(__name__)


class AssignerNodeV2(BaseNodeV2):
    """
    Assigner Node V2 - 포트 기반 변수 조작 노드

    특징:
    - 11가지 WriteMode 작업 지원
    - 다중 작업 순차 실행
    - variable_mappings + NodeExecutionContext 기반 입력 해석
    """

    def __init__(
        self,
        node_id: str,
        config: Optional[Dict[str, Any]] = None,
        variable_mappings: Optional[Dict[str, Any]] = None
    ):
        """
        노드 초기화

        Args:
            node_id: 노드 고유 ID
            config: 노드 설정 (operations 포함)
            variable_mappings: 입력 포트 매핑
        """
        super().__init__(node_id, config or {}, variable_mappings)

        raw_operations = (config or {}).get("operations", [])
        self.operations: List[AssignerOperation] = [
            AssignerOperation(**op) if isinstance(op, dict) else op
            for op in raw_operations
        ]

    # ---------- 포트 스키마 ----------

    def get_port_schema(self) -> NodePortSchema:
        """operations 개수에 따라 포트를 동적으로 구성"""
        return self._build_port_schema()

    def _build_port_schema(self) -> NodePortSchema:
        """포트 스키마 동적 생성"""
        inputs: List[PortDefinition] = []
        outputs: List[PortDefinition] = []

        for i, operation in enumerate(self.operations):
            write_mode = operation.write_mode
            input_type = operation.input_type

            # 대상 변수 입력 포트 (항상 필수)
            inputs.append(
                PortDefinition(
                    name=f"operation_{i}_target",
                    type=PortType.ANY,
                    required=True,
                    description=f"작업 {i}의 대상 변수",
                    display_name=f"대상 {i}"
                )
            )

            # 값 입력 포트 (작업 타입에 따라 필요)
            if self._needs_value_input(write_mode):
                is_required = (input_type == AssignerInputType.VARIABLE)
                inputs.append(
                    PortDefinition(
                        name=f"operation_{i}_value",
                        type=self._infer_value_type(write_mode),
                        required=is_required,
                        description=f"작업 {i}의 입력 값",
                        display_name=f"값 {i}"
                    )
                )

            # 결과 출력 포트
            outputs.append(
                PortDefinition(
                    name=f"operation_{i}_result",
                    type=PortType.ANY,
                    required=True,
                    description=f"작업 {i}의 결과 값",
                    display_name=f"결과 {i}"
                )
            )

        return NodePortSchema(inputs=inputs, outputs=outputs)

    # ---------- 실행 로직 ----------

    async def execute_v2(self, context: NodeExecutionContext) -> Dict[str, Any]:
        """
        노드 실행

        Args:
            context: V2 실행 컨텍스트 (VariablePool + ServiceContainer 포함)

        Returns:
            출력 포트별 값 딕셔너리
        """
        # 연결된 노드의 변수만 허용하도록 셀렉터 목록 계산
        allowed_selectors = self._compute_allowed_selectors(context)

        # variable_mappings의 모든 셀렉터가 허용된 것인지 검증
        for port_name, mapping in self.variable_mappings.items():
            selector = None
            if isinstance(mapping, str):
                selector = mapping
            elif isinstance(mapping, dict):
                selector = mapping.get("variable")
                if not selector:
                    source = mapping.get("source") or {}
                    selector = source.get("variable")

            # conversation 변수는 특별히 허용 (전역 변수)
            if selector and not selector.lower().startswith(("conv.", "conversation.")):
                if selector not in allowed_selectors:
                    raise ValueError(
                        f"포트 '{port_name}'의 변수 '{selector}'는 연결되지 않은 노드의 출력입니다. "
                        f"워크플로우 에디터에서 해당 노드를 연결해주세요."
                    )

        outputs: Dict[str, Any] = {}

        for i, operation in enumerate(self.operations):
            write_mode = operation.write_mode

            # 대상 변수 값 가져오기
            target_port = f"operation_{i}_target"
            target_value = context.get_input(target_port)
            if target_value is None:
                raise ValueError(f"필수 입력 포트 누락: {target_port}")

            # 소스 값 가져오기 (필요한 경우)
            source_value: Any = None
            if self._needs_value_input(write_mode):
                if operation.input_type == AssignerInputType.CONSTANT:
                    source_value = operation.constant_value
                    if source_value is None:
                        raise ValueError(
                            f"작업 {i}: constant 모드에서는 constant_value가 필요합니다."
                        )
                else:
                    value_port = f"operation_{i}_value"
                    source_value = context.get_input(value_port)
                    if source_value is None:
                        raise ValueError(f"필수 입력 포트 누락: {value_port}")

            # 작업 실행
            try:
                result = await self._perform_operation(
                    operation_index=i,
                    write_mode=write_mode,
                    target_value=target_value,
                    source_value=source_value
                )
                outputs[f"operation_{i}_result"] = result
                self._maybe_update_conversation_variable(
                    operation_index=i,
                    value=result,
                    context=context
                )
            except Exception as e:
                raise ValueError(
                    f"작업 {i} 실행 실패 (작업 타입: {write_mode}): {str(e)}"
                ) from e

        return outputs

    # ---------- 헬퍼 ----------

    def _needs_value_input(self, write_mode: WriteMode) -> bool:
        """
        작업 타입이 값 입력을 필요로 하는지 확인

        Args:
            write_mode: 작업 타입

        Returns:
            값 입력 필요 여부
        """
        no_value_modes = {
            WriteMode.CLEAR,
            WriteMode.REMOVE_FIRST,
            WriteMode.REMOVE_LAST
        }
        return write_mode not in no_value_modes

    def _infer_value_type(self, write_mode: WriteMode) -> PortType:
        """
        작업 타입에 따른 값 입력 포트의 타입 추론

        Args:
            write_mode: 작업 타입

        Returns:
            포트 타입
        """
        arithmetic_modes = {
            WriteMode.INCREMENT,
            WriteMode.DECREMENT,
            WriteMode.MULTIPLY,
            WriteMode.DIVIDE
        }
        if write_mode in arithmetic_modes:
            return PortType.NUMBER
        return PortType.ANY

    async def _perform_operation(
        self,
        operation_index: int,
        write_mode: WriteMode,
        target_value: Any,
        source_value: Optional[Any] = None
    ) -> Any:
        """
        개별 작업 실행

        Args:
            operation_index: 작업 인덱스
            write_mode: 작업 타입
            target_value: 대상 변수 값
            source_value: 소스 값 (필요한 경우)

        Returns:
            작업 결과 값

        Raises:
            ValueError: 타입 불일치, 경계 조건 위반 등
        """
        # 기본 작업
        if write_mode == WriteMode.OVERWRITE:
            return source_value

        elif write_mode == WriteMode.CLEAR:
            # 타입에 따라 적절한 초기값으로 설정
            if isinstance(target_value, str):
                return ""
            elif isinstance(target_value, list):
                return []
            elif isinstance(target_value, bool):
                return False
            elif isinstance(target_value, dict):
                return {}
            elif isinstance(target_value, (int, float)):
                return 0
            else:
                # 기타 타입은 None으로 초기화
                return None

        elif write_mode == WriteMode.SET:
            return source_value

        # 배열 작업
        elif write_mode == WriteMode.APPEND:
            if not isinstance(target_value, list):
                raise ValueError(
                    f"APPEND 작업은 배열 타입이 필요합니다. "
                    f"현재 타입: {type(target_value).__name__}"
                )
            result = target_value.copy()
            result.append(source_value)
            return result

        elif write_mode == WriteMode.EXTEND:
            if not isinstance(target_value, list):
                raise ValueError(
                    f"EXTEND 작업의 대상은 배열 타입이어야 합니다. "
                    f"현재 타입: {type(target_value).__name__}"
                )
            if not isinstance(source_value, list):
                raise ValueError(
                    f"EXTEND 작업의 소스는 배열 타입이어야 합니다. "
                    f"현재 타입: {type(source_value).__name__}"
                )
            result = target_value.copy()
            result.extend(source_value)
            return result

        elif write_mode == WriteMode.REMOVE_FIRST:
            if not isinstance(target_value, list):
                raise ValueError(
                    f"REMOVE_FIRST 작업은 배열 타입이 필요합니다. "
                    f"현재 타입: {type(target_value).__name__}"
                )
            if len(target_value) == 0:
                raise ValueError("빈 배열에서 첫 번째 요소를 제거할 수 없습니다.")
            result = target_value.copy()
            result.pop(0)
            return result

        elif write_mode == WriteMode.REMOVE_LAST:
            if not isinstance(target_value, list):
                raise ValueError(
                    f"REMOVE_LAST 작업은 배열 타입이 필요합니다. "
                    f"현재 타입: {type(target_value).__name__}"
                )
            if len(target_value) == 0:
                raise ValueError("빈 배열에서 마지막 요소를 제거할 수 없습니다.")
            result = target_value.copy()
            result.pop()
            return result

        # 산술 작업
        elif write_mode == WriteMode.INCREMENT:
            if not isinstance(target_value, (int, float)):
                raise ValueError(
                    f"INCREMENT 작업의 대상은 숫자 타입이어야 합니다. "
                    f"현재 타입: {type(target_value).__name__}"
                )
            if not isinstance(source_value, (int, float)):
                raise ValueError(
                    f"INCREMENT 작업의 소스는 숫자 타입이어야 합니다. "
                    f"현재 타입: {type(source_value).__name__}"
                )
            return target_value + source_value

        elif write_mode == WriteMode.DECREMENT:
            if not isinstance(target_value, (int, float)):
                raise ValueError(
                    f"DECREMENT 작업의 대상은 숫자 타입이어야 합니다. "
                    f"현재 타입: {type(target_value).__name__}"
                )
            if not isinstance(source_value, (int, float)):
                raise ValueError(
                    f"DECREMENT 작업의 소스는 숫자 타입이어야 합니다. "
                    f"현재 타입: {type(source_value).__name__}"
                )
            return target_value - source_value

        elif write_mode == WriteMode.MULTIPLY:
            if not isinstance(target_value, (int, float)):
                raise ValueError(
                    f"MULTIPLY 작업의 대상은 숫자 타입이어야 합니다. "
                    f"현재 타입: {type(target_value).__name__}"
                )
            if not isinstance(source_value, (int, float)):
                raise ValueError(
                    f"MULTIPLY 작업의 소스는 숫자 타입이어야 합니다. "
                    f"현재 타입: {type(source_value).__name__}"
                )
            return target_value * source_value

        elif write_mode == WriteMode.DIVIDE:
            if not isinstance(target_value, (int, float)):
                raise ValueError(
                    f"DIVIDE 작업의 대상은 숫자 타입이어야 합니다. "
                    f"현재 타입: {type(target_value).__name__}"
                )
            if not isinstance(source_value, (int, float)):
                raise ValueError(
                    f"DIVIDE 작업의 소스는 숫자 타입이어야 합니다. "
                    f"현재 타입: {type(source_value).__name__}"
                )
            if source_value == 0:
                raise ValueError("0으로 나눌 수 없습니다.")
            return target_value / source_value

        else:
            raise ValueError(f"지원하지 않는 작업 타입: {write_mode}")

    def _maybe_update_conversation_variable(
        self,
        operation_index: int,
        value: Any,
        context: NodeExecutionContext
    ) -> None:
        """
        대상 selector가 conversation.* 인 경우 conversation_variables에 결과를 저장
        """
        selector = self._get_selector_for_port(f"operation_{operation_index}_target")
        if not selector:
            return

        lowered = selector.lower()
        if lowered.startswith("conv.") or lowered.startswith("conversation."):
            parts = selector.split(".", 1)
            if len(parts) == 2 and parts[1]:
                var_name = parts[1]
                context.variable_pool.set_conversation_variable(var_name, value)
                logger.info(
                    "AssignerNodeV2 saved to conversation variable: '%s' = '%s' (length: %d)",
                    var_name,
                    str(value)[:100] + "..." if len(str(value)) > 100 else str(value),
                    len(str(value)) if isinstance(value, str) else 0,
                )

    def _get_selector_for_port(self, port_name: str) -> Optional[str]:
        """
        variable_mappings에서 포트에 연결된 selector 추출
        """
        mapping = self.variable_mappings.get(port_name)
        if mapping is None:
            return None

        if isinstance(mapping, str):
            return mapping

        if isinstance(mapping, dict):
            if isinstance(mapping.get("variable"), str):
                return mapping["variable"]
            source = mapping.get("source") or {}
            variable = source.get("variable")
            if isinstance(variable, str):
                return variable

        return None
