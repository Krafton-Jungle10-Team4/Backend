"""WorkflowValidator 관련 단위 테스트"""

from app.core.workflow.validator import WorkflowValidator


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
