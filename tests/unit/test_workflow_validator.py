"""WorkflowValidator 관련 단위 테스트"""

import copy

from app.core.workflow.validator import WorkflowValidator
from tests.data.workflow_v2_feedback_graph import FEEDBACK_WORKFLOW_GRAPH


def test_validator_normalizes_placeholder_ports_and_mappings():
    """placeholder 핸들과 누락된 variable_mappings를 자동 보정한다"""
    validator = WorkflowValidator()

    nodes = [
        {
            "id": "start-1",
            "type": "start",
            "position": {"x": 0, "y": 0},
            "data": {"type": "start"},
            "ports": {
                "inputs": [],
                "outputs": [
                    {"name": "query", "type": "string", "required": True},
                    {"name": "session_id", "type": "string", "required": False},
                ],
            },
            "variable_mappings": {},
        },
        {
            "id": "llm-1",
            "type": "llm",
            "position": {"x": 200, "y": 0},
            "data": {"type": "llm"},
            "ports": {
                "inputs": [
                    {"name": "query", "type": "string", "required": True},
                ],
                "outputs": [
                    {"name": "response", "type": "string", "required": True},
                ],
            },
            "variable_mappings": {},
        },
        {
            "id": "answer-1",
            "type": "answer",
            "position": {"x": 400, "y": 0},
            "data": {"type": "answer"},
            "ports": {
                "inputs": [],
                "outputs": [
                    {"name": "final_output", "type": "string", "required": True},
                ],
            },
            "variable_mappings": {},
        },
        {
            "id": "end-1",
            "type": "end",
            "position": {"x": 600, "y": 0},
            "data": {"type": "end"},
            "ports": {
                "inputs": [
                    {"name": "response", "type": "string", "required": True},
                ],
                "outputs": [],
            },
            "variable_mappings": {},
        },
    ]

    edges = [
        {
            "id": "edge-start-llm",
            "source": "start-1",
            "target": "llm-1",
            "source_port": "source",
            "target_port": "target",
        },
        {
            "id": "edge-answer-end",
            "source": "answer-1",
            "target": "end-1",
            "source_port": "source",
            "target_port": "target",
        },
        {
            "id": "edge-llm-end",
            "source": "llm-1",
            "target": "end-1",
            "source_port": "source",
            "target_port": "target",
        },
    ]

    is_valid, errors, warnings = validator.validate(nodes, edges)

    assert is_valid, f"unexpected errors: {errors}"

    node_map = {node["id"]: node for node in nodes}

    assert node_map["llm-1"]["variable_mappings"]["query"] == "start-1.query"
    assert node_map["end-1"]["variable_mappings"]["response"] == "answer-1.final_output"

    edge_map = {edge["id"]: edge for edge in edges}
    assert edge_map["edge-start-llm"]["source_port"] == "query"
    assert edge_map["edge-start-llm"]["target_port"] == "query"
    assert edge_map["edge-answer-end"]["source_port"] == "final_output"
    assert edge_map["edge-answer-end"]["target_port"] == "response"


def test_validator_converts_conversation_edges_to_variable_mappings():
    """conv/conversation 가짜 노드를 variable mapping으로 변환한다"""
    validator = WorkflowValidator()

    nodes = [
        {
            "id": "start-1",
            "type": "start",
            "position": {"x": 0, "y": 0},
            "data": {"type": "start"},
            "ports": {
                "inputs": [],
                "outputs": [
                    {"name": "query", "type": "string", "required": True},
                ],
            },
        },
        {
            "id": "llm-1",
            "type": "llm",
            "position": {"x": 200, "y": 0},
            "data": {"type": "llm"},
            "ports": {
                "inputs": [
                    {"name": "query", "type": "string", "required": True},
                    {"name": "context", "type": "string", "required": False},
                ],
                "outputs": [
                    {"name": "response", "type": "string", "required": True},
                ],
            },
            "variable_mappings": {},
        },
        {
            "id": "answer-1",
            "type": "answer",
            "position": {"x": 400, "y": 0},
            "data": {"type": "answer", "template": "{{llm-1.response}}"},
            "ports": {
                "inputs": [],
                "outputs": [
                    {"name": "final_output", "type": "string", "required": True},
                ],
            },
            "variable_mappings": {},
        },
        {
            "id": "end-1",
            "type": "end",
            "position": {"x": 600, "y": 0},
            "data": {"type": "end"},
            "ports": {
                "inputs": [
                    {"name": "response", "type": "string", "required": True},
                ],
                "outputs": [],
            },
            "variable_mappings": {},
        },
    ]

    edges = [
        {
            "id": "edge-start-llm",
            "source": "start-1",
            "target": "llm-1",
            "source_port": "query",
            "target_port": "query",
        },
        {
            "id": "edge-conv-context",
            "source": "conv",
            "target": "llm-1",
            "source_port": "summary",
            "target_port": "context",
        },
        {
            "id": "edge-llm-answer",
            "source": "llm-1",
            "target": "answer-1",
            "source_port": "response",
            "target_port": "final_output",
        },
        {
            "id": "edge-answer-end",
            "source": "answer-1",
            "target": "end-1",
            "source_port": "final_output",
            "target_port": "response",
        },
    ]

    is_valid, errors, _ = validator.validate(nodes, edges)

    assert is_valid, f"unexpected errors: {errors}"
    node_map = {node["id"]: node for node in nodes}
    assert node_map["llm-1"]["variable_mappings"]["query"] == "start-1.query"
    assert node_map["llm-1"]["variable_mappings"]["context"] == "conversation.summary"


def test_feedback_plan_graph_matches_validator_contract():
    """workflow_v2_current_plan.md에 정의된 피드백 플로우가 유효한지 확인한다"""
    validator = WorkflowValidator()

    nodes = copy.deepcopy(FEEDBACK_WORKFLOW_GRAPH["nodes"])
    edges = copy.deepcopy(FEEDBACK_WORKFLOW_GRAPH["edges"])

    is_valid, errors, warnings = validator.validate(nodes, edges)

    assert is_valid, f"plan graph should be valid, got errors: {errors}"
    assert errors == []
    assert warnings == []

    node_map = {node["id"]: node for node in nodes}
    assigner_initial = node_map["assigner-initial"]
    assert assigner_initial["variable_mappings"]["operation_0_target"] == "conversation.latest_summary"
    assert assigner_initial["variable_mappings"]["operation_1_target"] == "conversation.pending_response"
    assert assigner_initial["variable_mappings"]["operation_3_value"] == "start-1.query"

    assigner_repeat = node_map["assigner-repeat"]
    assert assigner_repeat["variable_mappings"]["operation_3_value"] == "system.user_message"

    assigner_complete = node_map["assigner-complete"]
    assert assigner_complete["variable_mappings"]["operation_0_value"] == "llm-sns.response"

    answer_node = node_map["answer-1"]
    assert answer_node["data"]["template"].strip() == "{{ conversation.pending_response }}"
    assert any(
        edge["source"] == "answer-1" and edge["target"] == "end-1" for edge in edges
    ), "Answer must feed End per validator contract"

    required_conv_keys = [
        "feedback_stage",
        "pending_response",
        "latest_summary",
        "last_query",
        "last_feedback",
    ]
    for key in required_conv_keys:
        assert key in FEEDBACK_WORKFLOW_GRAPH["conversation_variables"]


def test_multiple_end_nodes_allowed_with_branch_nodes():
    """분기 노드가 있는 워크플로우에서 여러 End 노드를 허용한다"""
    validator = WorkflowValidator()

    nodes = [
        {
            "id": "start-1",
            "type": "start",
            "position": {"x": 0, "y": 0},
            "data": {"type": "start"},
            "ports": {
                "inputs": [],
                "outputs": [
                    {"name": "query", "type": "string", "required": True},
                ],
            },
        },
        {
            "id": "classifier-1",
            "type": "question-classifier",
            "position": {"x": 200, "y": 0},
            "data": {"type": "question-classifier"},
            "ports": {
                "inputs": [
                    {"name": "query", "type": "string", "required": True},
                ],
                "outputs": [
                    {"name": "배송", "type": "string", "required": False},
                    {"name": "제품", "type": "string", "required": False},
                ],
            },
            "variable_mappings": {},
        },
        {
            "id": "llm-shipping",
            "type": "llm",
            "position": {"x": 400, "y": -100},
            "data": {"type": "llm"},
            "ports": {
                "inputs": [
                    {"name": "query", "type": "string", "required": True},
                ],
                "outputs": [
                    {"name": "response", "type": "string", "required": True},
                ],
            },
            "variable_mappings": {},
        },
        {
            "id": "llm-product",
            "type": "llm",
            "position": {"x": 400, "y": 100},
            "data": {"type": "llm"},
            "ports": {
                "inputs": [
                    {"name": "query", "type": "string", "required": True},
                ],
                "outputs": [
                    {"name": "response", "type": "string", "required": True},
                ],
            },
            "variable_mappings": {},
        },
        {
            "id": "answer-shipping",
            "type": "answer",
            "position": {"x": 600, "y": -100},
            "data": {"type": "answer", "template": "{{llm-shipping.response}}"},
            "ports": {
                "inputs": [],
                "outputs": [
                    {"name": "final_output", "type": "string", "required": True},
                ],
            },
            "variable_mappings": {},
        },
        {
            "id": "answer-product",
            "type": "answer",
            "position": {"x": 600, "y": 100},
            "data": {"type": "answer", "template": "{{llm-product.response}}"},
            "ports": {
                "inputs": [],
                "outputs": [
                    {"name": "final_output", "type": "string", "required": True},
                ],
            },
            "variable_mappings": {},
        },
        {
            "id": "end-shipping",
            "type": "end",
            "position": {"x": 800, "y": -100},
            "data": {"type": "end"},
            "ports": {
                "inputs": [
                    {"name": "response", "type": "string", "required": True},
                ],
                "outputs": [],
            },
            "variable_mappings": {},
        },
        {
            "id": "end-product",
            "type": "end",
            "position": {"x": 800, "y": 100},
            "data": {"type": "end"},
            "ports": {
                "inputs": [
                    {"name": "response", "type": "string", "required": True},
                ],
                "outputs": [],
            },
            "variable_mappings": {},
        },
    ]

    edges = [
        {
            "id": "edge-start-classifier",
            "source": "start-1",
            "target": "classifier-1",
            "source_port": "query",
            "target_port": "query",
        },
        {
            "id": "edge-classifier-shipping",
            "source": "classifier-1",
            "target": "llm-shipping",
            "source_port": "배송",
            "target_port": "query",
        },
        {
            "id": "edge-classifier-product",
            "source": "classifier-1",
            "target": "llm-product",
            "source_port": "제품",
            "target_port": "query",
        },
        {
            "id": "edge-shipping-answer",
            "source": "llm-shipping",
            "target": "answer-shipping",
            "source_port": "response",
            "target_port": "final_output",
        },
        {
            "id": "edge-product-answer",
            "source": "llm-product",
            "target": "answer-product",
            "source_port": "response",
            "target_port": "final_output",
        },
        {
            "id": "edge-answer-shipping-end",
            "source": "answer-shipping",
            "target": "end-shipping",
            "source_port": "final_output",
            "target_port": "response",
        },
        {
            "id": "edge-answer-product-end",
            "source": "answer-product",
            "target": "end-product",
            "source_port": "final_output",
            "target_port": "response",
        },
    ]

    is_valid, errors, warnings = validator.validate(nodes, edges)

    # 분기 노드가 있으므로 여러 End 노드가 허용되어야 함
    assert is_valid, f"workflow with branch nodes should allow multiple end nodes, got errors: {errors}"
    assert not any("End 노드는 하나만" in error for error in errors)


def test_multiple_end_nodes_rejected_without_branch_nodes():
    """분기 노드가 없는 워크플로우에서 여러 End 노드는 거부된다"""
    validator = WorkflowValidator()

    nodes = [
        {
            "id": "start-1",
            "type": "start",
            "position": {"x": 0, "y": 0},
            "data": {"type": "start"},
            "ports": {
                "inputs": [],
                "outputs": [
                    {"name": "query", "type": "string", "required": True},
                ],
            },
        },
        {
            "id": "llm-1",
            "type": "llm",
            "position": {"x": 200, "y": 0},
            "data": {"type": "llm"},
            "ports": {
                "inputs": [
                    {"name": "query", "type": "string", "required": True},
                ],
                "outputs": [
                    {"name": "response", "type": "string", "required": True},
                ],
            },
            "variable_mappings": {},
        },
        {
            "id": "answer-1",
            "type": "answer",
            "position": {"x": 400, "y": 0},
            "data": {"type": "answer", "template": "{{llm-1.response}}"},
            "ports": {
                "inputs": [],
                "outputs": [
                    {"name": "final_output", "type": "string", "required": True},
                ],
            },
            "variable_mappings": {},
        },
        {
            "id": "end-1",
            "type": "end",
            "position": {"x": 600, "y": -50},
            "data": {"type": "end"},
            "ports": {
                "inputs": [
                    {"name": "response", "type": "string", "required": True},
                ],
                "outputs": [],
            },
            "variable_mappings": {},
        },
        {
            "id": "end-2",
            "type": "end",
            "position": {"x": 600, "y": 50},
            "data": {"type": "end"},
            "ports": {
                "inputs": [
                    {"name": "response", "type": "string", "required": True},
                ],
                "outputs": [],
            },
            "variable_mappings": {},
        },
    ]

    edges = [
        {
            "id": "edge-start-llm",
            "source": "start-1",
            "target": "llm-1",
            "source_port": "query",
            "target_port": "query",
        },
        {
            "id": "edge-llm-answer",
            "source": "llm-1",
            "target": "answer-1",
            "source_port": "response",
            "target_port": "final_output",
        },
        {
            "id": "edge-answer-end1",
            "source": "answer-1",
            "target": "end-1",
            "source_port": "final_output",
            "target_port": "response",
        },
        {
            "id": "edge-answer-end2",
            "source": "answer-1",
            "target": "end-2",
            "source_port": "final_output",
            "target_port": "response",
        },
    ]

    is_valid, errors, warnings = validator.validate(nodes, edges)

    # 분기 노드가 없으므로 여러 End 노드는 거부되어야 함
    assert not is_valid
    assert any("End 노드는 하나만" in error for error in errors)
