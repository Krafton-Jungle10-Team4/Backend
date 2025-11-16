"""Executable workflow graph that mirrors workflow_v2_current_plan.md.

The graph encodes the following stages:
- Initial search → summary → assigner updates conversation state
- Feedback classification with negative and positive reroute
- Single Answer → End chain fed by conversation.pending_response

This artifact is used in tests to ensure WorkflowValidator accepts the
plan without errors.
"""

FEEDBACK_WORKFLOW_GRAPH = {
    "environment_variables": {},
    "conversation_variables": {
        "feedback_stage": "",
        "pending_response": "",
        "latest_summary": "",
        "last_query": "",
        "last_feedback": "",
    },
    "nodes": [
        {
            "id": "start-1",
            "type": "start",
            "position": {"x": 0, "y": 0},
            "data": {"type": "start", "title": "Start"},
            "variable_mappings": {},
        },
        {
            "id": "router-1",
            "type": "if-else",
            "position": {"x": 200, "y": 0},
            "data": {
                "type": "if-else",
                "cases": [
                    {
                        "case_id": "initial_request",
                        "logical_operator": "and",
                        "conditions": [
                            {
                                "variable_selector": "conversation.feedback_stage",
                                "comparison_operator": "=",
                                "value": "",
                                "varType": "string",
                            }
                        ],
                    }
                ],
            },
            "variable_mappings": {},
        },
        {
            "id": "tavily-initial",
            "type": "tavily-search",
            "position": {"x": 400, "y": -160},
            "data": {
                "type": "tavily-search",
                "topic": "general",
                "search_depth": "basic",
                "max_results": 5,
                "include_answer": False,
            },
            "variable_mappings": {
                "query": "start-1.query",
            },
        },
        {
            "id": "llm-summary",
            "type": "llm",
            "position": {"x": 620, "y": -160},
            "data": {
                "type": "llm",
                "provider": "openai",
                "model": "gpt-4o-mini",
                "prompt_template": (
                    "You are a helpful assistant summarizing the latest question.\n"
                    "Question: {{ start-1.query }}\n"
                    "Context: {{ tavily-initial.context }}\n\n"
                    "Provide a concise answer and end with '이 요약이 마음에 드셨나요?'."
                ),
                "temperature": 0.2,
                "max_tokens": 400,
            },
            "variable_mappings": {
                "query": "start-1.query",
                "context": "tavily-initial.context",
            },
        },
        {
            "id": "assigner-initial",
            "type": "assigner",
            "position": {"x": 820, "y": -160},
            "data": {
                "operations": [
                    {"write_mode": "over-write", "input_type": "variable"},
                    {"write_mode": "over-write", "input_type": "variable"},
                    {"write_mode": "over-write", "input_type": "constant", "constant_value": "wait_feedback"},
                    {"write_mode": "over-write", "input_type": "variable"},
                    {"write_mode": "over-write", "input_type": "constant", "constant_value": ""},
                ]
            },
            "variable_mappings": {
                "operation_0_target": "conversation.latest_summary",
                "operation_0_value": "llm-summary.response",
                "operation_1_target": "conversation.pending_response",
                "operation_1_value": "llm-summary.response",
                "operation_2_target": "conversation.feedback_stage",
                "operation_3_target": "conversation.last_query",
                "operation_3_value": "start-1.query",
                "operation_4_target": "conversation.last_feedback",
            },
        },
        {
            "id": "classifier-1",
            "type": "question-classifier",
            "position": {"x": 420, "y": 160},
            "data": {
                "type": "question-classifier",
                "model": {
                    "provider": "openai",
                    "name": "gpt-4o-mini",
                    "completion_params": {"temperature": 0.2, "max_tokens": 64},
                },
                "classes": [
                    {"id": "positive", "name": "마음에 든다"},
                    {"id": "negative", "name": "마음에 들지 않는다"},
                ],
                "query_template": (
                    "이전 응답: {{ conversation.pending_response }}\n"
                    "사용자 피드백: {{ system.user_message }}"
                ),
                "instruction": "Classify whether the user is satisfied or dissatisfied.",
            },
            "variable_mappings": {
                "query": "system.user_message",
            },
        },
        {
            "id": "tavily-repeat",
            "type": "tavily-search",
            "position": {"x": 620, "y": 80},
            "data": {
                "type": "tavily-search",
                "topic": "general",
                "search_depth": "advanced",
                "max_results": 5,
                "include_answer": False,
            },
            "variable_mappings": {
                "query": "conversation.last_query",
            },
        },
        {
            "id": "llm-repeat",
            "type": "llm",
            "position": {"x": 840, "y": 80},
            "data": {
                "type": "llm",
                "provider": "openai",
                "model": "gpt-4o-mini",
                "prompt_template": (
                    "사용자 피드백을 반영하여 더 나은 제안을 작성하세요.\n"
                    "이전 답변: {{ conversation.pending_response }}\n"
                    "피드백: {{ system.user_message }}\n"
                    "최신 검색 결과: {{ tavily-repeat.context }}"
                ),
                "temperature": 0.3,
                "max_tokens": 400,
            },
            "variable_mappings": {
                "query": "conversation.last_query",
                "context": "tavily-repeat.context",
            },
        },
        {
            "id": "assigner-repeat",
            "type": "assigner",
            "position": {"x": 1040, "y": 80},
            "data": {
                "operations": [
                    {"write_mode": "over-write", "input_type": "variable"},
                    {"write_mode": "over-write", "input_type": "variable"},
                    {"write_mode": "over-write", "input_type": "constant", "constant_value": "wait_feedback"},
                    {"write_mode": "over-write", "input_type": "variable"},
                ]
            },
            "variable_mappings": {
                "operation_0_target": "conversation.latest_summary",
                "operation_0_value": "llm-repeat.response",
                "operation_1_target": "conversation.pending_response",
                "operation_1_value": "llm-repeat.response",
                "operation_2_target": "conversation.feedback_stage",
                "operation_3_target": "conversation.last_feedback",
                "operation_3_value": "system.user_message",
            },
        },
        {
            "id": "llm-sns",
            "type": "llm",
            "position": {"x": 640, "y": 320},
            "data": {
                "type": "llm",
                "provider": "openai",
                "model": "gpt-4o-mini",
                "prompt_template": (
                    "사용자가 만족했습니다. 최신 요약을 기반으로 짧은 축하 메시지와 공유용 문구를 작성하세요.\n"
                    "요약: {{ conversation.latest_summary }}\n"
                    "피드백: {{ system.user_message }}"
                ),
                "temperature": 0.4,
                "max_tokens": 300,
            },
            "variable_mappings": {
                "query": "system.user_message",
                "context": "conversation.latest_summary",
            },
        },
        {
            "id": "assigner-complete",
            "type": "assigner",
            "position": {"x": 860, "y": 320},
            "data": {
                "operations": [
                    {"write_mode": "over-write", "input_type": "variable"},
                    {"write_mode": "over-write", "input_type": "constant", "constant_value": ""},
                    {"write_mode": "over-write", "input_type": "variable"},
                ]
            },
            "variable_mappings": {
                "operation_0_target": "conversation.pending_response",
                "operation_0_value": "llm-sns.response",
                "operation_1_target": "conversation.feedback_stage",
                "operation_2_target": "conversation.last_feedback",
                "operation_2_value": "system.user_message",
            },
        },
        {
            "id": "answer-1",
            "type": "answer",
            "position": {"x": 1080, "y": 120},
            "data": {
                "type": "answer",
                "template": "{{ conversation.pending_response }}",
                "description": "Unified answer node",
                "output_format": "text",
            },
            "variable_mappings": {},
        },
        {
            "id": "end-1",
            "type": "end",
            "position": {"x": 1260, "y": 120},
            "data": {"type": "end", "title": "End"},
            "variable_mappings": {
                "response": "answer-1.final_output",
            },
        },
    ],
    "edges": [
        {
            "id": "edge-start-router",
            "source": "start-1",
            "target": "router-1",
            "source_port": "query",
        },
        {
            "id": "edge-router-initial",
            "source": "router-1",
            "target": "tavily-initial",
            "source_port": "if",
        },
        {
            "id": "edge-router-classifier",
            "source": "router-1",
            "target": "classifier-1",
            "source_port": "else",
        },
        {
            "id": "edge-start-llm-summary",
            "source": "start-1",
            "target": "llm-summary",
            "source_port": "query",
            "target_port": "query",
        },
        {
            "id": "edge-tavily-initial-llm",
            "source": "tavily-initial",
            "target": "llm-summary",
            "source_port": "context",
            "target_port": "context",
        },
        {
            "id": "edge-llm-summary-assigner-0",
            "source": "llm-summary",
            "target": "assigner-initial",
            "source_port": "response",
            "target_port": "operation_0_value",
        },
        {
            "id": "edge-llm-summary-assigner-1",
            "source": "llm-summary",
            "target": "assigner-initial",
            "source_port": "response",
            "target_port": "operation_1_value",
        },
        {
            "id": "edge-start-assigner-initial",
            "source": "start-1",
            "target": "assigner-initial",
            "source_port": "query",
            "target_port": "operation_3_value",
        },
        {
            "id": "edge-assigner-initial-answer",
            "source": "assigner-initial",
            "target": "answer-1",
            "source_port": "operation_0_result",
            "target_port": "target",
        },
        {
            "id": "edge-classifier-negative",
            "source": "classifier-1",
            "target": "tavily-repeat",
            "source_port": "class_negative_branch",
        },
        {
            "id": "edge-classifier-positive",
            "source": "classifier-1",
            "target": "llm-sns",
            "source_port": "class_positive_branch",
        },
        {
            "id": "edge-tavily-repeat-llm",
            "source": "tavily-repeat",
            "target": "llm-repeat",
            "source_port": "context",
            "target_port": "context",
        },
        {
            "id": "edge-llm-repeat-assigner-0",
            "source": "llm-repeat",
            "target": "assigner-repeat",
            "source_port": "response",
            "target_port": "operation_0_value",
        },
        {
            "id": "edge-llm-repeat-assigner-1",
            "source": "llm-repeat",
            "target": "assigner-repeat",
            "source_port": "response",
            "target_port": "operation_1_value",
        },
        {
            "id": "edge-assigner-repeat-answer",
            "source": "assigner-repeat",
            "target": "answer-1",
            "source_port": "operation_0_result",
            "target_port": "target",
        },
        {
            "id": "edge-llm-sns-assigner",
            "source": "llm-sns",
            "target": "assigner-complete",
            "source_port": "response",
            "target_port": "operation_0_value",
        },
        {
            "id": "edge-assigner-complete-answer",
            "source": "assigner-complete",
            "target": "answer-1",
            "source_port": "operation_0_result",
            "target_port": "target",
        },
        {
            "id": "edge-answer-end",
            "source": "answer-1",
            "target": "end-1",
            "source_port": "final_output",
            "target_port": "response",
        },
    ],
}

