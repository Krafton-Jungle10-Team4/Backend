"""
워크플로우 실행 기록 API 엔드포인트

워크플로우 실행 기록 조회, 노드 실행 상세 조회 등의 기능을 제공합니다.
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional
from datetime import datetime
import logging

from app.core.database import get_db
from app.core.auth.dependencies import get_current_user_from_jwt as get_current_user
from app.models.user import User
from app.schemas.workflow import (
    WorkflowRunResponse,
    WorkflowRunDetail,
    NodeExecutionResponse,
    NodeExecutionDetail,
    PaginatedWorkflowRuns,
    WorkflowExecutionStatistics
)
from app.services.workflow_execution_service import WorkflowExecutionService
from app.services.bot_service import BotService
from app.core.pricing import calculate_token_cost
from decimal import Decimal

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/bots/{bot_id}/workflow-executions",
    tags=["workflow-executions"]
)

# 레거시 호환: 프론트엔드가 /workflows/runs 경로를 참조하는 경우가 있어
# 동일한 핸들러를 재사용하는 보조 라우터를 추가한다.
legacy_router = APIRouter(
    prefix="/bots/{bot_id}/workflows/runs",
    tags=["workflow-executions (legacy)"]
)


@router.get(
    "",
    response_model=PaginatedWorkflowRuns,
    summary="워크플로우 실행 기록 목록 조회",
    description="Bot의 워크플로우 실행 기록 목록을 페이지네이션하여 조회합니다."
)
async def list_execution_runs(
    bot_id: str,
    status: Optional[str] = Query(None, description="필터링할 실행 상태"),
    start_date: Optional[datetime] = Query(None, description="시작 날짜"),
    end_date: Optional[datetime] = Query(None, description="종료 날짜"),
    limit: int = Query(50, le=100, description="페이지 크기"),
    offset: int = Query(0, ge=0, description="오프셋"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> PaginatedWorkflowRuns:
    """
    실행 기록 목록 조회

    - 페이지네이션 지원
    - 상태, 날짜 범위로 필터링 가능
    """
    try:
        # 봇 접근 권한 확인
        bot_service = BotService()
        bot = await bot_service.get_bot_by_id(bot_id, current_user.id, db)
        if not bot:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="봇을 찾을 수 없거나 접근 권한이 없습니다"
            )

        # 실행 기록 조회
        service = WorkflowExecutionService(db)
        result = await service.list_runs(
            bot_id=bot_id,
            status=status,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
            offset=offset
        )

        # 각 실행에 대해 비용 계산
        runs = []
        for run in result["items"]:
            # 비용 계산: LLM 노드의 비용 합산
            total_cost = None
            try:
                node_executions = await service.get_node_executions(str(run.id))
                cost_sum = Decimal("0")
                for ne in node_executions:
                    if ne.node_type.lower() == "llm" or ne.node_type == "LLMNodeV2":
                        if ne.outputs:
                            prompt_tokens = ne.outputs.get("prompt_tokens", 0)
                            completion_tokens = ne.outputs.get("completion_tokens", 0)
                            model = ne.outputs.get("model")
                            
                            if model and (prompt_tokens > 0 or completion_tokens > 0):
                                cost = calculate_token_cost(model, prompt_tokens, completion_tokens)
                                if cost:
                                    cost_sum += cost
                
                if cost_sum > 0:
                    total_cost = float(cost_sum)
            except Exception as e:
                logger.warning(f"Failed to calculate cost for run {run.id}: {e}")
            
            runs.append(
                WorkflowRunResponse(
                    id=str(run.id),
                    bot_id=run.bot_id,
                    workflow_version_id=str(run.workflow_version_id) if run.workflow_version_id else None,
                    session_id=run.session_id,
                    status=run.status,
                    error_message=run.error_message,
                    started_at=run.started_at,
                    finished_at=run.finished_at,
                    elapsed_time=run.elapsed_time,
                    total_tokens=run.total_tokens,
                    total_cost=total_cost,
                    total_steps=run.total_steps,
                    created_at=run.created_at
                )
            )

        return PaginatedWorkflowRuns(
            items=runs,
            total=result["total"],
            limit=result["limit"],
            offset=result["offset"]
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to list execution runs: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"실행 기록 목록 조회 실패: {str(e)}"
        )


legacy_router.add_api_route(
    "",
    list_execution_runs,
    methods=["GET"],
    response_model=PaginatedWorkflowRuns,
    summary="워크플로우 실행 기록 목록 조회",
    description="(레거시 경로) Bot의 워크플로우 실행 기록 목록을 페이지네이션하여 조회합니다."
)


@router.get(
    "/{run_id}",
    response_model=WorkflowRunDetail,
    summary="워크플로우 실행 기록 상세 조회",
    description="특정 워크플로우 실행 기록의 상세 정보를 조회합니다."
)
async def get_execution_run(
    bot_id: str,
    run_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> WorkflowRunDetail:
    """
    실행 기록 상세 조회

    - 실행 시점 그래프 스냅샷, 입력/출력 데이터 포함
    """
    try:
        # 봇 접근 권한 확인
        bot_service = BotService()
        bot = await bot_service.get_bot_by_id(bot_id, current_user.id, db)
        if not bot:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="봇을 찾을 수 없거나 접근 권한이 없습니다"
            )

        # 실행 기록 조회
        service = WorkflowExecutionService(db)
        run = await service.get_run(run_id)

        if not run or run.bot_id != bot_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="실행 기록을 찾을 수 없습니다"
            )

        # 총 비용 계산: 모든 LLM 노드의 비용 합산
        total_cost = None
        node_executions = await service.get_node_executions(run_id)
        
        logger.info(f"[get_execution_run] Calculating cost for run {run_id}, found {len(node_executions)} nodes")
        
        cost_sum = Decimal("0")
        for ne in node_executions:
            logger.info(f"[get_execution_run] Checking node {ne.node_id}, type={ne.node_type}, has_outputs={ne.outputs is not None}")
            if ne.node_type.lower() == "llm" or ne.node_type == "LLMNodeV2":
                if ne.outputs:
                    prompt_tokens = ne.outputs.get("prompt_tokens", 0)
                    completion_tokens = ne.outputs.get("completion_tokens", 0)
                    model = ne.outputs.get("model")
                    
                    logger.info(f"[get_execution_run] LLM node {ne.node_id}: model={model}, prompt={prompt_tokens}, completion={completion_tokens}")
                    
                    if model and (prompt_tokens > 0 or completion_tokens > 0):
                        cost = calculate_token_cost(model, prompt_tokens, completion_tokens)
                        logger.info(f"[get_execution_run] Calculated cost: ${cost}")
                        if cost:
                            cost_sum += cost
                else:
                    logger.warning(f"[get_execution_run] LLM node {ne.node_id} has no outputs!")
        
        if cost_sum > 0:
            total_cost = float(cost_sum)
        
        logger.info(f"[get_execution_run] Total cost for run {run_id}: ${total_cost}")

        return WorkflowRunDetail(
            id=str(run.id),
            bot_id=run.bot_id,
            workflow_version_id=str(run.workflow_version_id) if run.workflow_version_id else None,
            session_id=run.session_id,
            status=run.status,
            error_message=run.error_message,
            started_at=run.started_at,
            finished_at=run.finished_at,
            elapsed_time=run.elapsed_time,
            total_tokens=run.total_tokens,
            total_cost=total_cost,
            total_steps=run.total_steps,
            created_at=run.created_at,
            graph_snapshot=run.graph_snapshot,
            inputs=run.inputs,
            outputs=run.outputs
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get execution run: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"실행 기록 조회 실패: {str(e)}"
        )


legacy_router.add_api_route(
    "/{run_id}",
    get_execution_run,
    methods=["GET"],
    response_model=WorkflowRunDetail,
    summary="워크플로우 실행 기록 상세 조회",
    description="(레거시 경로) 특정 워크플로우 실행 기록의 상세 정보를 조회합니다."
)


@router.get(
    "/{run_id}/nodes",
    response_model=List[NodeExecutionResponse],
    summary="노드 실행 기록 목록 조회",
    description="특정 워크플로우 실행의 모든 노드 실행 기록을 조회합니다."
)
async def get_node_executions(
    bot_id: str,
    run_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> List[NodeExecutionResponse]:
    """
    노드 실행 기록 목록 조회

    - 실행 순서대로 정렬됨
    """
    try:
        # 봇 접근 권한 확인
        bot_service = BotService()
        bot = await bot_service.get_bot_by_id(bot_id, current_user.id, db)
        if not bot:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="봇을 찾을 수 없거나 접근 권한이 없습니다"
            )

        # 실행 기록 확인
        exec_service = WorkflowExecutionService(db)
        run = await exec_service.get_run(run_id)

        if not run or run.bot_id != bot_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="실행 기록을 찾을 수 없습니다"
            )

        # 노드 실행 기록 조회
        node_executions = await exec_service.get_node_executions(run_id)

        results = []
        for ne in node_executions:
            # LLM 노드인 경우 비용 계산
            cost = None
            model = None
            
            if (ne.node_type.lower() == "llm" or ne.node_type == "LLMNodeV2") and ne.outputs:
                # outputs에서 토큰 및 모델 정보 추출
                prompt_tokens = ne.outputs.get("prompt_tokens", 0)
                completion_tokens = ne.outputs.get("completion_tokens", 0)
                model = ne.outputs.get("model")
                
                if model and (prompt_tokens > 0 or completion_tokens > 0):
                    cost_decimal = calculate_token_cost(model, prompt_tokens, completion_tokens)
                    if cost_decimal:
                        cost = float(cost_decimal)
            
            results.append(
                NodeExecutionResponse(
                    id=str(ne.id),
                    workflow_run_id=str(ne.workflow_run_id),
                    node_id=ne.node_id,
                    node_type=ne.node_type,
                    execution_order=ne.execution_order,
                    status=ne.status,
                    error_message=ne.error_message,
                    started_at=ne.started_at,
                    finished_at=ne.finished_at,
                    elapsed_time=ne.elapsed_time,
                    tokens_used=ne.tokens_used,
                    cost=cost,
                    model=model,
                    is_truncated=ne.is_truncated,
                    created_at=ne.created_at
                )
            )
        
        return results

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get node executions: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"노드 실행 기록 조회 실패: {str(e)}"
        )


legacy_router.add_api_route(
    "/{run_id}/nodes",
    get_node_executions,
    methods=["GET"],
    response_model=List[NodeExecutionResponse],
    summary="노드 실행 기록 목록 조회",
    description="(레거시 경로) 특정 워크플로우 실행의 모든 노드 실행 기록을 조회합니다."
)


@router.get(
    "/{run_id}/nodes/{node_execution_id}",
    response_model=NodeExecutionDetail,
    summary="노드 실행 기록 상세 조회",
    description="특정 노드 실행 기록의 상세 정보를 조회합니다."
)
async def get_node_execution_detail(
    bot_id: str,
    run_id: str,
    node_execution_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> NodeExecutionDetail:
    """
    노드 실행 기록 상세 조회

    - 입력/출력/처리 데이터 포함
    """
    try:
        # 봇 접근 권한 확인
        bot_service = BotService()
        bot = await bot_service.get_bot_by_id(bot_id, current_user.id, db)
        if not bot:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="봇을 찾을 수 없거나 접근 권한이 없습니다"
            )

        # 실행 기록 확인
        exec_service = WorkflowExecutionService(db)
        run = await exec_service.get_run(run_id)

        if not run or run.bot_id != bot_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="실행 기록을 찾을 수 없습니다"
            )

        # 노드 실행 기록 조회
        node_execution = await exec_service.get_node_execution(node_execution_id)

        if not node_execution or str(node_execution.workflow_run_id) != run_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="노드 실행 기록을 찾을 수 없습니다"
            )

        return NodeExecutionDetail(
            id=str(node_execution.id),
            workflow_run_id=str(node_execution.workflow_run_id),
            node_id=node_execution.node_id,
            node_type=node_execution.node_type,
            execution_order=node_execution.execution_order,
            status=node_execution.status,
            error_message=node_execution.error_message,
            started_at=node_execution.started_at,
            finished_at=node_execution.finished_at,
            elapsed_time=node_execution.elapsed_time,
            tokens_used=node_execution.tokens_used,
            is_truncated=node_execution.is_truncated,
            created_at=node_execution.created_at,
            inputs=node_execution.inputs,
            outputs=node_execution.outputs,
            process_data=node_execution.process_data,
            truncated_fields=node_execution.truncated_fields
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get node execution detail: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"노드 실행 상세 조회 실패: {str(e)}"
        )


legacy_router.add_api_route(
    "/{run_id}/nodes/{node_execution_id}",
    get_node_execution_detail,
    methods=["GET"],
    response_model=NodeExecutionDetail,
    summary="노드 실행 기록 상세 조회",
    description="(레거시 경로) 특정 노드 실행 기록의 상세 정보를 조회합니다."
)


@router.get(
    "/statistics",
    response_model=WorkflowExecutionStatistics,
    summary="워크플로우 실행 통계 조회",
    description="Bot의 워크플로우 실행 통계를 조회합니다."
)
async def get_execution_statistics(
    bot_id: str,
    start_date: Optional[datetime] = Query(None, description="시작 날짜"),
    end_date: Optional[datetime] = Query(None, description="종료 날짜"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> WorkflowExecutionStatistics:
    """
    실행 통계 조회

    - 총 실행 횟수, 성공/실패 횟수
    - 평균 실행 시간, 총 토큰 사용량
    """
    try:
        # 봇 접근 권한 확인
        bot_service = BotService()
        bot = await bot_service.get_bot_by_id(bot_id, current_user.id, db)
        if not bot:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="봇을 찾을 수 없거나 접근 권한이 없습니다"
            )

        # 통계 조회
        service = WorkflowExecutionService(db)
        stats = await service.get_run_statistics(
            bot_id=bot_id,
            start_date=start_date,
            end_date=end_date
        )

        return WorkflowExecutionStatistics(**stats)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get execution statistics: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"실행 통계 조회 실패: {str(e)}"
        )


legacy_router.add_api_route(
    "/statistics",
    get_execution_statistics,
    methods=["GET"],
    response_model=WorkflowExecutionStatistics,
    summary="워크플로우 실행 통계 조회",
    description="(레거시 경로) Bot의 워크플로우 실행 통계를 조회합니다."
)


@router.delete(
    "/{run_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="워크플로우 실행 기록 삭제",
    description="특정 워크플로우 실행 기록을 삭제합니다."
)
async def delete_execution_run(
    bot_id: str,
    run_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    실행 기록 삭제

    - 관련 노드 실행 기록도 함께 삭제됨 (CASCADE)
    """
    try:
        # 봇 접근 권한 확인
        bot_service = BotService()
        bot = await bot_service.get_bot_by_id(bot_id, current_user.id, db)
        if not bot:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="봇을 찾을 수 없거나 접근 권한이 없습니다"
            )

        # 실행 기록 확인
        exec_service = WorkflowExecutionService(db)
        run = await exec_service.get_run(run_id)

        if not run or run.bot_id != bot_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="실행 기록을 찾을 수 없습니다"
            )

        # 삭제
        success = await exec_service.delete_run(run_id)

        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="실행 기록 삭제 실패"
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete execution run: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"실행 기록 삭제 실패: {str(e)}"
        )


legacy_router.add_api_route(
    "/{run_id}",
    delete_execution_run,
    methods=["DELETE"],
    status_code=status.HTTP_204_NO_CONTENT,
    summary="워크플로우 실행 기록 삭제",
    description="(레거시 경로) 특정 워크플로우 실행 기록을 삭제합니다."
)
