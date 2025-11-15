"""
Assigner Node V2 - 포트 기반 변수 조작 노드

11가지 WriteMode 작업을 지원하며, 다중 작업 순차 실행이 가능합니다.
variable_mappings와 NodeExecutionContext 기반으로 입력을 해석합니다.
"""

from typing import Any, Dict, List, Optional

from app.core.workflow.base_node_v2 import BaseNodeV2, NodeExecutionContext
from app.core.workflow.node_registry_v2 import register_node_v2
from app.schemas.workflow import (
    NodePortSchema,
    PortDefinition,
    PortType,
    WriteMode,
    AssignerOperation,
    AssignerInputType,
)


@register_node_v2("assigner")
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
        개별 작업 실행 (Phase 3에서 구현 예정)

        Args:
            operation_index: 작업 인덱스
            write_mode: 작업 타입
            target_value: 대상 변수 값
            source_value: 소스 값 (필요한 경우)

        Returns:
            작업 결과 값

        Raises:
            NotImplementedError: Phase 3에서 구현 예정
        """
        # Phase 3에서 11가지 작업 타입별 로직 구현
        raise NotImplementedError(
            f"작업 {operation_index} ({write_mode}) 실행 로직은 Phase 3에서 구현됩니다."
        )
