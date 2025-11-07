"""
워크플로우 관련 API 엔드포인트

노드 타입 조회, 워크플로우 검증, 모델 목록 등의 기능을 제공합니다.
"""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.auth.dependencies import get_current_user_from_jwt as get_current_user
from app.core.workflow.node_registry import node_registry
from app.core.workflow.validator import WorkflowValidator
from app.models.user import User
from app.schemas.workflow import (
    Workflow,
    WorkflowValidationRequest,
    WorkflowValidationResponse,
    NodeTypeInfo,
    NodeTypesResponse,
    ModelInfo,
    ModelsResponse
)
from app.services.bot_service import BotService
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/workflows")


@router.get(
    "/node-types",
    response_model=NodeTypesResponse,
    summary="노드 타입 목록 조회",
    description="사용 가능한 모든 워크플로우 노드 타입과 설정 스키마를 반환합니다."
)
async def get_node_types(
    current_user: User = Depends(get_current_user)
) -> NodeTypesResponse:
    """
    노드 타입 목록 조회

    Returns:
        NodeTypesResponse: 노드 타입 정보 목록
    """
    try:
        # 레지스트리에서 모든 노드 스키마 가져오기
        schemas = node_registry.list_schemas()

        node_types = []
        for schema in schemas:
            # NodeSchema를 NodeTypeInfo로 변환
            config_schema = schema.config_schema

            # config_schema가 dict인지 확인
            if config_schema and not isinstance(config_schema, dict):
                config_schema = config_schema.dict() if hasattr(config_schema, 'dict') else None

            node_type_info = NodeTypeInfo(
                type=schema.type.value,
                label=schema.label,
                icon=schema.icon,
                max_instances=schema.max_instances,
                configurable=schema.configurable,
                config_schema=config_schema
            )
            node_types.append(node_type_info)

        return NodeTypesResponse(node_types=node_types)

    except Exception as e:
        logger.error(f"Failed to get node types: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"노드 타입 조회 실패: {str(e)}"
        )


@router.get(
    "/node-types/{node_type}",
    response_model=NodeTypeInfo,
    summary="특정 노드 타입 정보 조회",
    description="특정 노드 타입의 상세 정보와 설정 스키마를 반환합니다."
)
async def get_node_type(
    node_type: str,
    current_user: User = Depends(get_current_user)
) -> NodeTypeInfo:
    """
    특정 노드 타입 정보 조회

    Args:
        node_type: 노드 타입

    Returns:
        NodeTypeInfo: 노드 타입 정보
    """
    try:
        from app.core.workflow.base_node import NodeType

        # 문자열을 NodeType enum으로 변환
        try:
            node_type_enum = NodeType(node_type)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"노드 타입 '{node_type}'를 찾을 수 없습니다"
            )

        # 스키마 조회
        schema = node_registry.get_schema(node_type_enum)
        if not schema:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"노드 타입 '{node_type}'의 스키마를 찾을 수 없습니다"
            )

        config_schema = schema.config_schema
        if config_schema and not isinstance(config_schema, dict):
            config_schema = config_schema.dict() if hasattr(config_schema, 'dict') else None

        return NodeTypeInfo(
            type=schema.type.value,
            label=schema.label,
            icon=schema.icon,
            max_instances=schema.max_instances,
            configurable=schema.configurable,
            config_schema=config_schema
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get node type {node_type}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"노드 타입 조회 실패: {str(e)}"
        )


@router.post(
    "/validate",
    response_model=WorkflowValidationResponse,
    summary="워크플로우 검증",
    description="워크플로우 구조의 유효성을 검사합니다."
)
async def validate_workflow(
    request: WorkflowValidationRequest,
    current_user: User = Depends(get_current_user)
) -> WorkflowValidationResponse:
    """
    워크플로우 검증

    Args:
        request: 워크플로우 검증 요청

    Returns:
        WorkflowValidationResponse: 검증 결과
    """
    try:
        validator = WorkflowValidator()

        # 노드와 엣지를 딕셔너리로 변환
        nodes = [node.dict() for node in request.nodes]
        edges = [edge.dict() for edge in request.edges]

        # 검증 수행
        is_valid, errors, warnings = validator.validate(nodes, edges)

        # 실행 순서 계산
        execution_order = None
        if is_valid:
            execution_order = validator.get_execution_order(nodes, edges)

        return WorkflowValidationResponse(
            is_valid=is_valid,
            errors=errors,
            warnings=warnings,
            execution_order=execution_order
        )

    except Exception as e:
        logger.error(f"Workflow validation failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"워크플로우 검증 실패: {str(e)}"
        )


@router.put(
    "/bots/{bot_id}/workflow",
    response_model=dict,
    summary="봇 워크플로우 업데이트",
    description="봇의 워크플로우를 저장하거나 업데이트합니다."
)
async def update_bot_workflow(
    bot_id: str,
    workflow: Workflow,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> dict:
    """
    봇 워크플로우 업데이트

    Args:
        bot_id: 봇 ID
        workflow: 워크플로우 정의
        current_user: 현재 사용자
        db: 데이터베이스 세션

    Returns:
        dict: 성공 메시지
    """
    try:
        # 워크플로우 검증
        validator = WorkflowValidator()
        nodes = [node.dict() for node in workflow.nodes]
        edges = [edge.dict() for edge in workflow.edges]

        is_valid, errors, warnings = validator.validate(nodes, edges)

        if not is_valid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "message": "워크플로우 검증 실패",
                    "errors": errors,
                    "warnings": warnings
                }
            )

        # 봇 서비스를 통해 워크플로우 업데이트
        bot_service = BotService()
        success = await bot_service.update_bot_workflow(
            bot_id=bot_id,
            team_id=current_user.team_id,
            workflow=workflow.dict(),
            db=db
        )

        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="봇을 찾을 수 없습니다"
            )

        return {
            "message": "워크플로우가 성공적으로 업데이트되었습니다",
            "warnings": warnings if warnings else []
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update bot workflow: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"워크플로우 업데이트 실패: {str(e)}"
        )


@router.post(
    "/bots/{bot_id}/workflow/validate",
    response_model=WorkflowValidationResponse,
    summary="봇 워크플로우 검증",
    description="봇의 워크플로우를 저장하기 전에 검증합니다."
)
async def validate_bot_workflow(
    bot_id: str,
    workflow: Workflow,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> WorkflowValidationResponse:
    """
    봇 워크플로우 검증

    Args:
        bot_id: 봇 ID
        workflow: 워크플로우 정의
        current_user: 현재 사용자
        db: 데이터베이스 세션

    Returns:
        WorkflowValidationResponse: 검증 결과
    """
    try:
        # 봇 존재 여부 확인
        bot_service = BotService()
        bot = await bot_service.get_bot_by_id(bot_id, current_user.team_id, db)
        if not bot:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="봇을 찾을 수 없습니다"
            )

        # 워크플로우 검증
        validator = WorkflowValidator()
        nodes = [node.dict() for node in workflow.nodes]
        edges = [edge.dict() for edge in workflow.edges]

        is_valid, errors, warnings = validator.validate(nodes, edges)

        # 실행 순서 계산
        execution_order = None
        if is_valid:
            execution_order = validator.get_execution_order(nodes, edges)

        return WorkflowValidationResponse(
            is_valid=is_valid,
            errors=errors,
            warnings=warnings,
            execution_order=execution_order
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Bot workflow validation failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"워크플로우 검증 실패: {str(e)}"
        )


@router.get(
    "/models",
    response_model=ModelsResponse,
    summary="LLM 모델 목록 조회",
    description="사용 가능한 LLM 모델 목록을 반환합니다."
)
async def get_models(
    current_user: User = Depends(get_current_user)
) -> ModelsResponse:
    """
    LLM 모델 목록 조회

    Returns:
        ModelsResponse: 모델 목록
    """
    try:
        # 하드코딩된 모델 목록 (실제로는 설정이나 DB에서 가져와야 함)
        models = [
            ModelInfo(
                id="gpt-4",
                name="GPT-4",
                provider="OpenAI",
                description="OpenAI의 최신 대규모 언어 모델"
            ),
            ModelInfo(
                id="gpt-3.5-turbo",
                name="GPT-3.5 Turbo",
                provider="OpenAI",
                description="빠르고 효율적인 OpenAI 모델"
            ),
            ModelInfo(
                id="claude-3",
                name="Claude 3",
                provider="Anthropic",
                description="Anthropic의 최신 AI 모델"
            )
        ]

        return ModelsResponse(models=models)

    except Exception as e:
        logger.error(f"Failed to get models: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"모델 목록 조회 실패: {str(e)}"
        )