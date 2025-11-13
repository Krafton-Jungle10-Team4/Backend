"""
워크플로우 V2 통합 테스트

V2 시스템의 기본 동작을 검증합니다:
- WorkflowExecutorV2 실행
- 포트 기반 데이터 흐름
- 실행 기록 저장
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from app.core.workflow.executor_v2 import WorkflowExecutorV2
from app.core.workflow.base_node import NodeStatus


@pytest.fixture
def mock_db_session():
    """Mock 데이터베이스 세션"""
    db = MagicMock()
    db.add = MagicMock()
    db.commit = MagicMock()
    db.rollback = MagicMock()
    return db


@pytest.fixture
def mock_vector_service():
    """Mock VectorService"""
    service = AsyncMock()
    service.search = AsyncMock(return_value=[
        {
            "content": "파이썬은 고급 프로그래밍 언어입니다.",
            "metadata": {"document_id": "doc-1", "chunk_id": "chunk-1"},
            "similarity": 0.95
        },
        {
            "content": "파이썬은 간결하고 읽기 쉬운 문법을 가지고 있습니다.",
            "metadata": {"document_id": "doc-1", "chunk_id": "chunk-2"},
            "similarity": 0.92
        }
    ])
    return service


@pytest.fixture
def mock_llm_service():
    """Mock LLMService"""
    service = AsyncMock()
    service.generate = AsyncMock(return_value="파이썬은 간결하고 읽기 쉬운 프로그래밍 언어입니다.")
    service.get_token_count = AsyncMock(return_value=150)
    return service


@pytest.fixture
def basic_v2_workflow():
    """기본 V2 워크플로우 정의"""
    return {
        "nodes": [
            {
                "id": "start-1",
                "type": "start",
                "data": {},
                "variable_mappings": {}
            },
            {
                "id": "knowledge-1",
                "type": "knowledge-retrieval",
                "data": {
                    "top_k": 3
                },
                "variable_mappings": {
                    "query": "start-1.query"
                }
            },
            {
                "id": "llm-1",
                "type": "llm",
                "data": {
                    "model": "gpt-4",
                    "prompt_template": "Context: {{context}}\n\nQuestion: {{query}}\n\nAnswer:",
                    "temperature": 0.7,
                    "max_tokens": 500
                },
                "variable_mappings": {
                    "query": "start-1.query",
                    "context": "knowledge-1.context"
                }
            },
            {
                "id": "end-1",
                "type": "end",
                "data": {},
                "variable_mappings": {
                    "response": "llm-1.response"
                }
            }
        ],
        "edges": [
            {"id": "e1", "source": "start-1", "target": "knowledge-1"},
            {"id": "e2", "source": "knowledge-1", "target": "llm-1"},
            {"id": "e3", "source": "llm-1", "target": "end-1"}
        ],
        "environment_variables": {},
        "conversation_variables": {}
    }


@pytest.mark.asyncio
async def test_v2_basic_workflow_execution(
    basic_v2_workflow,
    mock_db_session,
    mock_vector_service,
    mock_llm_service
):
    """V2 워크플로우 기본 실행 테스트"""

    # Arrange
    executor = WorkflowExecutorV2()
    user_message = "파이썬이란 무엇인가요?"
    session_id = "test-session-123"
    bot_id = "test-bot-456"

    # Act
    response = await executor.execute(
        workflow_data=basic_v2_workflow,
        session_id=session_id,
        user_message=user_message,
        bot_id=bot_id,
        db=mock_db_session,
        vector_service=mock_vector_service,
        llm_service=mock_llm_service,
        stream_handler=None,
        text_normalizer=lambda x: x
    )

    # Assert
    assert response is not None
    assert isinstance(response, str)
    assert "파이썬" in response

    # Mock 서비스 호출 검증
    mock_vector_service.search.assert_called_once()
    mock_llm_service.generate.assert_called_once()

    print(f"✅ 기본 워크플로우 실행 성공: {response[:50]}...")


@pytest.mark.asyncio
async def test_v2_variable_pool_data_flow(
    basic_v2_workflow,
    mock_db_session,
    mock_vector_service,
    mock_llm_service
):
    """V2 VariablePool 데이터 흐름 테스트"""

    # Arrange
    executor = WorkflowExecutorV2()
    user_message = "테스트 질문"

    # Act
    await executor.execute(
        workflow_data=basic_v2_workflow,
        session_id="test-session",
        user_message=user_message,
        bot_id="test-bot",
        db=mock_db_session,
        vector_service=mock_vector_service,
        llm_service=mock_llm_service
    )

    # Assert - VariablePool에 데이터가 올바르게 저장되었는지 확인
    variable_pool = executor.variable_pool

    # System Variables
    assert variable_pool.get_system_variable("user_message") == user_message
    assert variable_pool.get_system_variable("session_id") == "test-session"
    assert variable_pool.get_system_variable("bot_id") == "test-bot"

    # Node Outputs
    start_outputs = variable_pool.get_all_node_outputs("start-1")
    assert start_outputs is not None
    assert "query" in start_outputs

    knowledge_outputs = variable_pool.get_all_node_outputs("knowledge-1")
    assert knowledge_outputs is not None
    assert "context" in knowledge_outputs

    llm_outputs = variable_pool.get_all_node_outputs("llm-1")
    assert llm_outputs is not None
    assert "response" in llm_outputs

    print("✅ VariablePool 데이터 흐름 검증 완료")


@pytest.mark.asyncio
async def test_v2_execution_history_saved(
    basic_v2_workflow,
    mock_db_session,
    mock_vector_service,
    mock_llm_service
):
    """V2 실행 기록 저장 테스트"""

    # Arrange
    executor = WorkflowExecutorV2()

    # Act
    await executor.execute(
        workflow_data=basic_v2_workflow,
        session_id="test-session",
        user_message="테스트",
        bot_id="test-bot",
        db=mock_db_session,
        vector_service=mock_vector_service,
        llm_service=mock_llm_service
    )

    # Assert
    # WorkflowExecutionRun이 생성되었는지 확인
    assert executor.execution_run is not None
    assert executor.execution_run.bot_id == "test-bot"
    assert executor.execution_run.session_id == "test-session"
    assert executor.execution_run.status == "completed"

    # DB add, commit 호출 확인
    assert mock_db_session.add.called
    assert mock_db_session.commit.called

    # 노드 실행 기록 확인
    assert len(executor.execution_run.node_executions) == 4  # 4개 노드

    # 각 노드 실행 기록 검증
    node_exec_ids = [ne.node_id for ne in executor.execution_run.node_executions]
    assert "start-1" in node_exec_ids
    assert "knowledge-1" in node_exec_ids
    assert "llm-1" in node_exec_ids
    assert "end-1" in node_exec_ids

    print("✅ 실행 기록 저장 검증 완료")


@pytest.mark.asyncio
async def test_v2_port_based_connections(
    mock_db_session,
    mock_vector_service,
    mock_llm_service
):
    """V2 포트 기반 연결 테스트"""

    # Arrange - variable_mappings로 명시적 연결
    workflow = {
        "nodes": [
            {
                "id": "start-1",
                "type": "start",
                "data": {},
                "variable_mappings": {}
            },
            {
                "id": "llm-1",
                "type": "llm",
                "data": {
                    "model": "gpt-4",
                    "prompt_template": "Question: {{query}}",
                    "temperature": 0.7,
                    "max_tokens": 100
                },
                "variable_mappings": {
                    "query": "start-1.query"  # ← 명시적 포트 연결
                }
            },
            {
                "id": "end-1",
                "type": "end",
                "data": {},
                "variable_mappings": {
                    "response": "llm-1.response"  # ← 명시적 포트 연결
                }
            }
        ],
        "edges": [
            {"id": "e1", "source": "start-1", "target": "llm-1"},
            {"id": "e2", "source": "llm-1", "target": "end-1"}
        ],
        "environment_variables": {},
        "conversation_variables": {}
    }

    executor = WorkflowExecutorV2()

    # Act
    response = await executor.execute(
        workflow_data=workflow,
        session_id="test-session",
        user_message="테스트 질문",
        bot_id="test-bot",
        db=mock_db_session,
        vector_service=mock_vector_service,
        llm_service=mock_llm_service
    )

    # Assert
    assert response is not None

    # 포트 연결 검증
    variable_pool = executor.variable_pool

    # start-1.query가 올바르게 설정되었는지
    start_query = variable_pool.resolve_value_selector("start-1.query")
    assert start_query == "테스트 질문"

    # llm-1.response가 생성되었는지
    llm_response = variable_pool.resolve_value_selector("llm-1.response")
    assert llm_response is not None

    print("✅ 포트 기반 연결 검증 완료")


@pytest.mark.asyncio
async def test_v2_node_execution_order(
    basic_v2_workflow,
    mock_db_session,
    mock_vector_service,
    mock_llm_service
):
    """V2 노드 실행 순서 검증"""

    # Arrange
    executor = WorkflowExecutorV2()

    # Act
    await executor.execute(
        workflow_data=basic_v2_workflow,
        session_id="test-session",
        user_message="테스트",
        bot_id="test-bot",
        db=mock_db_session,
        vector_service=mock_vector_service,
        llm_service=mock_llm_service
    )

    # Assert - 실행 순서 확인
    execution_order = executor.execution_order
    assert execution_order == ["start-1", "knowledge-1", "llm-1", "end-1"]

    # 각 노드 상태 확인
    node_statuses = executor.get_all_node_statuses()
    assert all(status == NodeStatus.COMPLETED for status in node_statuses.values())

    print(f"✅ 노드 실행 순서 검증 완료: {execution_order}")


@pytest.mark.asyncio
async def test_v2_error_handling(
    basic_v2_workflow,
    mock_db_session,
    mock_vector_service,
    mock_llm_service
):
    """V2 에러 처리 테스트"""

    # Arrange - LLM 서비스가 실패하도록 설정
    mock_llm_service.generate = AsyncMock(side_effect=Exception("LLM API Error"))

    executor = WorkflowExecutorV2()

    # Act & Assert
    with pytest.raises(RuntimeError) as exc_info:
        await executor.execute(
            workflow_data=basic_v2_workflow,
            session_id="test-session",
            user_message="테스트",
            bot_id="test-bot",
            db=mock_db_session,
            vector_service=mock_vector_service,
            llm_service=mock_llm_service
        )

    assert "V2 워크플로우 실행 실패" in str(exc_info.value)

    # 실행 기록에 실패가 기록되었는지 확인
    if executor.execution_run:
        assert executor.execution_run.status == "failed"
        assert executor.execution_run.error_message is not None

    print("✅ 에러 처리 검증 완료")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
