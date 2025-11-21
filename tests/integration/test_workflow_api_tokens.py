"""
Workflow API 토큰 정보 정확성 통합 테스트

문제 5 (토큰/시간 로그 누락) 해결 검증
"""
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Dict, Any
import uuid

from app.models.workflow_version import WorkflowExecutionRun, WorkflowNodeExecution
from app.models.bot_api_key import BotAPIKey
from app.models.bot import Bot
from app.models.workflow_version import BotWorkflowVersion


@pytest.mark.asyncio
async def test_workflow_execution_returns_accurate_tokens(
    async_client: AsyncClient,
    db: AsyncSession
):
    """워크플로우 실행 응답에 정확한 토큰 정보가 포함되는지 테스트"""
    
    # Given: 테스트용 Bot, Workflow, API Key 생성
    bot_id = str(uuid.uuid4())
    test_bot = Bot(
        bot_id=bot_id,
        name="Token Test Bot",
        user_id="test_user_123",
        use_workflow_v2=True
    )
    db.add(test_bot)
    
    # 간단한 LLM 워크플로우 생성
    workflow_version = BotWorkflowVersion(
        id=uuid.uuid4(),
        bot_id=bot_id,
        graph={
            "nodes": [
                {
                    "id": "start",
                    "type": "start",
                    "data": {"title": "Start"}
                },
                {
                    "id": "llm_1",
                    "type": "llm",
                    "data": {
                        "title": "LLM",
                        "model": "gpt-4o-mini",
                        "system_prompt": "You are a helpful assistant.",
                        "temperature": 0.7
                    }
                },
                {
                    "id": "answer",
                    "type": "answer",
                    "data": {"title": "Answer"}
                },
                {
                    "id": "end",
                    "type": "end",
                    "data": {"title": "End"}
                }
            ],
            "edges": [
                {"source": "start", "target": "llm_1"},
                {"source": "llm_1", "target": "answer"},
                {"source": "answer", "target": "end"}
            ]
        },
        version_number=1,
        input_schema=[
            {
                "key": "user_query",
                "type": "string",
                "required": True,
                "is_primary": True
            }
        ]
    )
    db.add(workflow_version)
    
    # API Key 생성
    api_key_value = f"sk-test-{uuid.uuid4().hex[:24]}"
    api_key = BotAPIKey(
        id=uuid.uuid4(),
        bot_id=bot_id,
        key=api_key_value,
        name="Test API Key",
        workflow_version_id=workflow_version.id,
        bind_to_latest_published=False,
        rate_limit=100
    )
    db.add(api_key)
    
    await db.commit()
    
    # When: API 호출
    response = await async_client.post(
        "/api/v1/public/workflows/run",
        headers={"X-API-Key": api_key_value},
        json={"inputs": {"user_query": "테스트 질문"}}
    )
    
    # Then: 응답 검증
    assert response.status_code == 200
    data = response.json()
    run_id = data["workflow_run_id"]
    
    # 1. API 응답 검증
    assert data["status"] == "completed"
    assert data["usage"]["total_tokens"] > 0, "total_tokens should be > 0"
    assert data["elapsed_time"] > 0, "elapsed_time should be > 0"
    
    # 2. 조회 API 검증
    detail_response = await async_client.get(
        f"/api/v1/public/workflows/runs/{run_id}",
        headers={"X-API-Key": api_key_value}
    )
    assert detail_response.status_code == 200
    detail_data = detail_response.json()
    
    assert detail_data["usage"]["total_tokens"] > 0
    assert detail_data["usage"]["total_tokens"] == data["usage"]["total_tokens"]
    
    # 3. DB 레코드와 노드 실행 기록 검증
    result = await db.execute(
        select(WorkflowExecutionRun).where(
            WorkflowExecutionRun.id == run_id
        )
    )
    execution_run = result.scalar_one()
    
    # API 전용 필드 검증
    assert execution_run.api_key_id is not None, "api_key_id should be set"
    assert str(execution_run.api_key_id) == str(api_key.id)
    
    # 노드 실행 기록 조회
    node_exec_result = await db.execute(
        select(WorkflowNodeExecution).where(
            WorkflowNodeExecution.workflow_run_id == run_id
        )
    )
    node_executions = node_exec_result.scalars().all()
    
    assert len(node_executions) > 0, "Should have node execution records"
    
    # 노드별 토큰 합계 계산
    node_tokens_sum = sum(
        node_exec.tokens_used or 0
        for node_exec in node_executions
    )
    
    # WorkflowExecutionRun.total_tokens == 노드별 합계
    assert execution_run.total_tokens == node_tokens_sum, (
        f"Execution run total_tokens ({execution_run.total_tokens}) "
        f"should match node executions sum ({node_tokens_sum})"
    )
    
    # API 응답 == DB 레코드
    assert data["usage"]["total_tokens"] == execution_run.total_tokens


@pytest.mark.asyncio
async def test_single_execution_run_created(
    async_client: AsyncClient,
    db: AsyncSession
):
    """API 실행 시 단일 실행 기록만 생성되는지 테스트"""
    
    # Given: 테스트용 Bot, Workflow, API Key 생성
    bot_id = str(uuid.uuid4())
    test_bot = Bot(
        bot_id=bot_id,
        name="Single Run Test Bot",
        user_id="test_user_456",
        use_workflow_v2=True
    )
    db.add(test_bot)
    
    workflow_version = BotWorkflowVersion(
        id=uuid.uuid4(),
        bot_id=bot_id,
        graph={
            "nodes": [
                {"id": "start", "type": "start", "data": {}},
                {"id": "answer", "type": "answer", "data": {}},
                {"id": "end", "type": "end", "data": {}}
            ],
            "edges": [
                {"source": "start", "target": "answer"},
                {"source": "answer", "target": "end"}
            ]
        },
        version_number=1,
        input_schema=[{"key": "query", "type": "string", "required": True}]
    )
    db.add(workflow_version)
    
    api_key_value = f"sk-test-{uuid.uuid4().hex[:24]}"
    api_key = BotAPIKey(
        id=uuid.uuid4(),
        bot_id=bot_id,
        key=api_key_value,
        name="Test Key",
        workflow_version_id=workflow_version.id,
        bind_to_latest_published=False
    )
    db.add(api_key)
    
    await db.commit()
    
    # 실행 전 레코드 개수
    count_before = await db.execute(
        select(WorkflowExecutionRun).where(
            WorkflowExecutionRun.bot_id == bot_id
        )
    )
    runs_before = count_before.scalars().all()
    initial_count = len(runs_before)
    
    # When: API 실행
    response = await async_client.post(
        "/api/v1/public/workflows/run",
        headers={"X-API-Key": api_key_value},
        json={"inputs": {"query": "test"}}
    )
    
    assert response.status_code == 200
    run_id = response.json()["workflow_run_id"]
    
    # Then: 실행 기록이 정확히 1개만 증가했는지 확인
    count_after = await db.execute(
        select(WorkflowExecutionRun).where(
            WorkflowExecutionRun.bot_id == bot_id
        )
    )
    runs_after = count_after.scalars().all()
    
    assert len(runs_after) == initial_count + 1, (
        f"Expected {initial_count + 1} runs, got {len(runs_after)}. "
        f"Duplicate execution run created!"
    )
    
    # 생성된 레코드 검증
    latest_run = runs_after[-1]
    assert str(latest_run.id) == run_id
    assert latest_run.api_key_id is not None


@pytest.mark.asyncio
async def test_nested_workflow_inherits_api_metadata(
    async_client: AsyncClient,
    db: AsyncSession
):
    """중첩 워크플로우가 부모의 API 메타데이터를 상속받는지 테스트"""
    
    # Given: 라이브러리 워크플로우 생성
    library_bot_id = str(uuid.uuid4())
    library_bot = Bot(
        bot_id=library_bot_id,
        name="Library Bot",
        user_id="test_user_789",
        use_workflow_v2=True
    )
    db.add(library_bot)
    
    library_workflow = BotWorkflowVersion(
        id=uuid.uuid4(),
        bot_id=library_bot_id,
        graph={
            "nodes": [
                {"id": "start", "type": "start", "data": {}},
                {
                    "id": "llm",
                    "type": "llm",
                    "data": {
                        "model": "gpt-4o-mini",
                        "system_prompt": "Helper"
                    }
                },
                {"id": "answer", "type": "answer", "data": {}},
                {"id": "end", "type": "end", "data": {}}
            ],
            "edges": [
                {"source": "start", "target": "llm"},
                {"source": "llm", "target": "answer"},
                {"source": "answer", "target": "end"}
            ]
        },
        version_number=1
    )
    db.add(library_workflow)
    
    # Given: 메인 워크플로우 (imported workflow 포함)
    main_bot_id = str(uuid.uuid4())
    main_bot = Bot(
        bot_id=main_bot_id,
        name="Main Bot",
        user_id="test_user_789",
        use_workflow_v2=True
    )
    db.add(main_bot)
    
    main_workflow = BotWorkflowVersion(
        id=uuid.uuid4(),
        bot_id=main_bot_id,
        graph={
            "nodes": [
                {"id": "start", "type": "start", "data": {}},
                {
                    "id": "imported",
                    "type": "imported-workflow",
                    "data": {
                        "source_version_id": str(library_workflow.id)
                    }
                },
                {"id": "answer", "type": "answer", "data": {}},
                {"id": "end", "type": "end", "data": {}}
            ],
            "edges": [
                {"source": "start", "target": "imported"},
                {"source": "imported", "target": "answer"},
                {"source": "answer", "target": "end"}
            ]
        },
        version_number=1,
        input_schema=[{"key": "query", "type": "string", "required": True}]
    )
    db.add(main_workflow)
    
    api_key_value = f"sk-test-{uuid.uuid4().hex[:24]}"
    api_key = BotAPIKey(
        id=uuid.uuid4(),
        bot_id=main_bot_id,
        key=api_key_value,
        name="Test Key",
        workflow_version_id=main_workflow.id,
        bind_to_latest_published=False
    )
    db.add(api_key)
    
    await db.commit()
    
    # When: API 실행
    response = await async_client.post(
        "/api/v1/public/workflows/run",
        headers={"X-API-Key": api_key_value},
        json={"inputs": {"query": "nested test"}}
    )
    
    # Then
    assert response.status_code == 200
    run_id = response.json()["workflow_run_id"]
    
    # 메인 워크플로우 실행 기록 확인
    result = await db.execute(
        select(WorkflowExecutionRun).where(
            WorkflowExecutionRun.id == run_id
        )
    )
    main_run = result.scalar_one()
    
    assert main_run.api_key_id is not None
    assert str(main_run.api_key_id) == str(api_key.id)
    
    # 중첩 워크플로우 실행 기록 확인 (library_bot_id로 생성됨)
    nested_result = await db.execute(
        select(WorkflowExecutionRun).where(
            WorkflowExecutionRun.bot_id == library_bot_id
        ).order_by(WorkflowExecutionRun.started_at.desc())
    )
    nested_runs = nested_result.scalars().all()
    
    if nested_runs:
        nested_run = nested_runs[0]
        # 중첩 워크플로우도 부모의 API 메타데이터를 상속받아야 함
        assert nested_run.api_key_id is not None, (
            "Nested workflow should inherit api_key_id from parent"
        )
        assert str(nested_run.api_key_id) == str(api_key.id)


@pytest.mark.asyncio
async def test_token_breakdown_accuracy(
    async_client: AsyncClient,
    db: AsyncSession
):
    """prompt_tokens + completion_tokens = total_tokens 검증"""
    
    # Given
    bot_id = str(uuid.uuid4())
    test_bot = Bot(
        bot_id=bot_id,
        name="Token Breakdown Bot",
        user_id="test_user_999",
        use_workflow_v2=True
    )
    db.add(test_bot)
    
    workflow_version = BotWorkflowVersion(
        id=uuid.uuid4(),
        bot_id=bot_id,
        graph={
            "nodes": [
                {"id": "start", "type": "start", "data": {}},
                {
                    "id": "llm_1",
                    "type": "llm",
                    "data": {
                        "model": "gpt-4o-mini",
                        "system_prompt": "You are helpful."
                    }
                },
                {
                    "id": "llm_2",
                    "type": "llm",
                    "data": {
                        "model": "gpt-4o-mini",
                        "system_prompt": "You are creative."
                    }
                },
                {"id": "answer", "type": "answer", "data": {}},
                {"id": "end", "type": "end", "data": {}}
            ],
            "edges": [
                {"source": "start", "target": "llm_1"},
                {"source": "llm_1", "target": "llm_2"},
                {"source": "llm_2", "target": "answer"},
                {"source": "answer", "target": "end"}
            ]
        },
        version_number=1,
        input_schema=[{"key": "query", "type": "string", "required": True}]
    )
    db.add(workflow_version)
    
    api_key_value = f"sk-test-{uuid.uuid4().hex[:24]}"
    api_key = BotAPIKey(
        id=uuid.uuid4(),
        bot_id=bot_id,
        key=api_key_value,
        name="Test Key",
        workflow_version_id=workflow_version.id,
        bind_to_latest_published=False
    )
    db.add(api_key)
    
    await db.commit()
    
    # When
    response = await async_client.post(
        "/api/v1/public/workflows/run",
        headers={"X-API-Key": api_key_value},
        json={"inputs": {"query": "Tell me a story"}}
    )
    
    # Then
    assert response.status_code == 200
    data = response.json()
    
    usage = data["usage"]
    prompt_tokens = usage.get("prompt_tokens", 0)
    completion_tokens = usage.get("completion_tokens", 0)
    total_tokens = usage.get("total_tokens", 0)
    
    # 토큰 합계 일관성 검증
    assert prompt_tokens > 0, "prompt_tokens should be > 0"
    assert completion_tokens > 0, "completion_tokens should be > 0"
    assert total_tokens == prompt_tokens + completion_tokens, (
        f"Token sum mismatch: {prompt_tokens} + {completion_tokens} != {total_tokens}"
    )

