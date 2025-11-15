import pytest

from app.core.workflow.nodes_v2.assigner_node_v2 import AssignerNodeV2
from app.core.workflow.base_node_v2 import NodeExecutionContext
from app.core.workflow.variable_pool import VariablePool
from app.core.workflow.service_container import ServiceContainer


@pytest.mark.asyncio
async def test_assigner_updates_conversation_variable():
    node = AssignerNodeV2(
        node_id="assigner_1",
        config={
            "operations": [
                {
                    "write_mode": "over-write",
                    "input_type": "constant",
                    "constant_value": "대화 요약",
                }
            ]
        },
        variable_mappings={
            "operation_0_target": "conversation.summary",
        },
    )

    variable_pool = VariablePool(conversation_variables={"summary": ""})
    context = NodeExecutionContext(
        node_id="assigner_1",
        variable_pool=variable_pool,
        service_container=ServiceContainer(),
        metadata={"prepared_inputs": {"operation_0_target": ""}},
    )

    await node.execute(context)

    assert variable_pool.get_conversation_variable("summary") == "대화 요약"
