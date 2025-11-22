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
from app.core.workflow.node_registry_v2 import node_registry_v2
from app.core.workflow.validator import WorkflowValidator
from app.models.user import User
from app.schemas.workflow import (
    Workflow,
    WorkflowValidationRequest,
    WorkflowValidationResponse,
    NodeTypeInfo,
    NodeTypesResponse,
    ModelInfo,
    ModelsResponse,
    PortDefinition
)
from app.services.bot_service import BotService
from app.config import settings
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/workflows")

# V2 노드 메타데이터 (label, icon, category, description)
V2_NODE_METADATA = {
    "tavily-search": {
        "label": "Tavily Search",
        "icon": "search",
        "category": "Tools",
        "description": "실시간 웹 검색을 수행하는 노드",
    },
    "start": {
        "label": "Start",
        "icon": "play",
        "category": "System",
        "description": "워크플로우 시작 노드",
    },
    "end": {
        "label": "End",
        "icon": "flag",
        "category": "System",
        "description": "워크플로우 종료 노드",
    },
    "llm": {
        "label": "LLM",
        "icon": "brain",
        "category": "AI",
        "description": "언어 모델 응답 생성 노드",
        "default_data": {
            "provider": "openai",
            "model": "chatgpt-4o-latest",  # 실제 OpenAI API 모델 ID 사용
            "prompt": "",
            "temperature": 0.7,
            "maxTokens": 4000,
        },
    },
    "knowledge-retrieval": {
        "label": "Knowledge Retrieval",
        "icon": "book",
        "category": "Data",
        "description": "지식베이스 검색 노드",
    },
    "if-else": {
        "label": "If-Else",
        "icon": "git-branch",
        "category": "Logic",
        "description": "조건 분기 노드",
    },
    "question-classifier": {
        "label": "Question Classifier",
        "icon": "filter",
        "category": "Logic",
        "description": "질문 분류 노드",
    },
    "answer": {
        "type": "answer",
        "label": "응답",
        "description": "워크플로우의 최종 응답을 생성합니다",
        "category": "System",
        "icon": "message-square",
        "color": "#10b981",
        "is_required": True,
        "supports_file_var": True
    },
}


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
    노드 타입 목록 조회 (V1 + V2 병합)

    Returns:
        NodeTypesResponse: 노드 타입 정보 목록
    """
    try:
        node_types = []
        processed_types = set()

        # V1 레지스트리에서 노드 스키마 가져오기
        v1_schemas = node_registry.list_schemas()
        for schema in v1_schemas:
            config_schema = schema.config_schema
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
            processed_types.add(schema.type.value)

        # V2 레지스트리에서 노드 타입 가져오기
        v2_node_types = node_registry_v2.list_types()
        for node_type_str in v2_node_types:
            # 이미 V1에서 처리된 노드는 건너뛰기
            if node_type_str in processed_types:
                continue

            # V2 노드 인스턴스 생성 (포트 스키마 조회용)
            try:
                node_instance = node_registry_v2.create_node(node_type_str, f"temp_{node_type_str}")
                port_schema = node_instance.get_port_schema()

                # 메타데이터 조회
                metadata = V2_NODE_METADATA.get(node_type_str, {})

                node_type_info = NodeTypeInfo(
                    type=node_type_str,
                    label=metadata.get("label", node_type_str.replace("-", " ").title()),
                    icon=metadata.get("icon", "cog"),
                    max_instances=-1,  # V2 노드는 무제한
                    configurable=True,
                    config_schema=None,  # V2는 config_schema 대신 포트로 관리
                    category=metadata.get("category"),
                    description=metadata.get("description"),
                    input_ports=port_schema.inputs if port_schema else None,
                    output_ports=port_schema.outputs if port_schema else None,
                    default_data=metadata.get("default_data")
                )
                node_types.append(node_type_info)
                processed_types.add(node_type_str)

            except Exception as e:
                logger.warning(f"Failed to get V2 node info for {node_type_str}: {e}")
                continue

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
    특정 노드 타입 정보 조회 (V1 + V2 지원)

    Args:
        node_type: 노드 타입

    Returns:
        NodeTypeInfo: 노드 타입 정보
    """
    try:
        from app.core.workflow.base_node import NodeType

        # V2 레지스트리에서 먼저 확인
        if node_type in node_registry_v2.list_types():
            try:
                node_instance = node_registry_v2.create_node(node_type, f"temp_{node_type}")
                port_schema = node_instance.get_port_schema()
                metadata = V2_NODE_METADATA.get(node_type, {})

                return NodeTypeInfo(
                    type=node_type,
                    label=metadata.get("label", node_type.replace("-", " ").title()),
                    icon=metadata.get("icon", "cog"),
                    max_instances=-1,
                    configurable=True,
                    config_schema=None,
                    category=metadata.get("category"),
                    description=metadata.get("description"),
                    input_ports=port_schema.inputs if port_schema else None,
                    output_ports=port_schema.outputs if port_schema else None,
                    default_data=metadata.get("default_data")
                )
            except Exception as e:
                logger.error(f"Failed to get V2 node info for {node_type}: {e}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"V2 노드 정보 조회 실패: {str(e)}"
                )

        # V1 레지스트리에서 확인
        try:
            node_type_enum = NodeType(node_type)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"노드 타입 '{node_type}'를 찾을 수 없습니다"
            )

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
        workflow_data = request.model_dump()
        nodes = workflow_data.get("nodes", [])
        edges = workflow_data.get("edges", [])

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
        workflow_data = workflow.model_dump()
        validator = WorkflowValidator()
        nodes = workflow_data.get("nodes", [])
        edges = workflow_data.get("edges", [])

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

        _log_llm_selection(bot_id, workflow)

        # 봇 서비스를 통해 워크플로우 업데이트
        bot_service = BotService()
        success = await bot_service.update_bot_workflow(
            bot_id=bot_id,
            user_id=current_user.id,
            workflow=workflow_data,
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
        bot = await bot_service.get_bot_by_id(bot_id, current_user.id, db)
        if not bot:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="봇을 찾을 수 없습니다"
            )

        workflow_data = workflow.model_dump()
        validator = WorkflowValidator()
        nodes = workflow_data.get("nodes", [])
        edges = workflow_data.get("edges", [])

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
    모델 카탈로그에서 동적으로 사용 가능한 모델을 가져옵니다.

    Returns:
        ModelsResponse: 모델 목록
    """
    try:
        models = []
        
        # ⭐️ Bedrock 모델 카탈로그에서 동적으로 가져오기
        try:
            import boto3
            from app.config import settings
            
            bedrock_client = boto3.client(
                'bedrock',
                region_name=settings.bedrock_region or 'ap-northeast-2'
            )
            
            # 모델 카탈로그에서 Claude 모델 조회 (ON_DEMAND 지원 모델만)
            response = bedrock_client.list_foundation_models(
                byProvider='Anthropic',
                byInferenceType='ON_DEMAND'
            )
            
            for model_summary in response.get('modelSummaries', []):
                model_id = model_summary.get('modelId', '')
                model_name = model_summary.get('modelName', '')
                
                # Claude 모델만 필터링
                if 'claude' in model_id.lower():
                    # 모델 이름에 버전 정보 추가
                    display_name = f"{model_name} (Bedrock)"
                    if 'haiku' in model_id.lower():
                        description = "AWS Bedrock Claude Haiku - 빠르고 저렴한 모델"
                    elif 'sonnet' in model_id.lower():
                        description = "AWS Bedrock Claude Sonnet - 고성능 모델 (비쌈)"
                    else:
                        description = f"AWS Bedrock {model_name}"
                    
                    models.append(ModelInfo(
                        id=model_id,
                        name=display_name,
                        provider="bedrock",
                        description=description
                    ))
            
            logger.info(f"모델 카탈로그에서 {len(models)}개의 Bedrock 모델을 가져왔습니다.")
        except Exception as e:
            logger.warning(f"모델 카탈로그에서 모델을 가져오는 중 오류 발생: {e}. 기본 모델 목록을 사용합니다.")
            # 폴백: 기본 모델 목록
            models.extend([
                ModelInfo(
                    id="anthropic.claude-3-haiku-20240307-v1:0",
                    name="Claude Haiku 3 (Bedrock)",
                    provider="bedrock",
                    description="AWS Bedrock Claude Haiku 3 - 빠르고 저렴한 모델 (기본값)"
                ),
                ModelInfo(
                    id="anthropic.claude-3-5-sonnet-20240620-v1:0",
                    name="Claude Sonnet 3.5 (Bedrock)",
                    provider="bedrock",
                    description="AWS Bedrock Claude Sonnet 3.5 - 고성능 모델 (비쌈)"
                ),
            ])
        
        # ⭐️ OpenAI 모델 목록 동적으로 가져오기
        try:
            from openai import AsyncOpenAI
            
            if settings.openai_api_key:
                openai_client = AsyncOpenAI(api_key=settings.openai_api_key)
                openai_models_response = await openai_client.models.list()
                
                # OpenAI 모델 필터링 (gpt, o1 등 채팅 모델만)
                openai_chat_models = [
                    model for model in openai_models_response.data
                    if any(model.id.startswith(prefix) for prefix in ['gpt-', 'o1-', 'o3-'])
                    and 'instruct' not in model.id.lower()  # instruct 모델 제외
                ]
                
                # 모델 이름 매핑 (더 읽기 쉬운 이름)
                model_name_mapping = {
                    'gpt-4o': 'GPT-4o',
                    'gpt-4o-mini': 'GPT-4o mini',
                    'gpt-4-turbo': 'GPT-4 Turbo',
                    'gpt-4': 'GPT-4',
                    'gpt-3.5-turbo': 'GPT-3.5 Turbo',
                    'o1-preview': 'O1 Preview',
                    'o1-mini': 'O1 Mini',
                    'o3-mini': 'O3 Mini',
                }
                
                for model in openai_chat_models:
                    model_id = model.id
                    display_name = model_name_mapping.get(model_id, model_id.replace('gpt-', 'GPT-').replace('o1-', 'O1 ').replace('o3-', 'O3 ').title())
                    
                    # 설명 생성
                    if 'gpt-4o' in model_id:
                        description = "OpenAI의 고성능 멀티모달 모델"
                    elif 'gpt-4o-mini' in model_id:
                        description = "OpenAI의 빠르고 저렴한 멀티모달 모델"
                    elif 'gpt-4-turbo' in model_id:
                        description = "OpenAI의 고성능 GPT-4 Turbo 모델"
                    elif 'gpt-4' in model_id:
                        description = "OpenAI의 고성능 GPT-4 모델"
                    elif 'gpt-3.5' in model_id:
                        description = "OpenAI의 빠르고 저렴한 GPT-3.5 모델"
                    elif 'o1' in model_id or 'o3' in model_id:
                        description = "OpenAI의 추론 최적화 모델"
                    else:
                        description = f"OpenAI {display_name} 모델"
                    
                    models.append(ModelInfo(
                        id=model_id,
                        name=display_name,
                        provider="openai",
                        description=description
                    ))
                
                logger.info(f"OpenAI API에서 {len(openai_chat_models)}개의 모델을 가져왔습니다.")
            else:
                logger.warning("OpenAI API 키가 설정되지 않아 기본 모델 목록을 사용합니다.")
                raise ValueError("OpenAI API key not configured")
                
        except Exception as e:
            logger.warning(f"OpenAI 모델 목록을 가져오는 중 오류 발생: {e}. 기본 모델 목록을 사용합니다.")
            # 폴백: 일반적으로 사용 가능한 OpenAI 모델 목록
            models.extend([
                ModelInfo(
                    id="gpt-4o",
                    name="GPT-4o",
                    provider="openai",
                    description="OpenAI의 고성능 멀티모달 모델"
                ),
                ModelInfo(
                    id="gpt-4o-mini",
                    name="GPT-4o mini",
                    provider="openai",
                    description="OpenAI의 빠르고 저렴한 멀티모달 모델"
                ),
                ModelInfo(
                    id="gpt-4-turbo",
                    name="GPT-4 Turbo",
                    provider="openai",
                    description="OpenAI의 고성능 GPT-4 Turbo 모델"
                ),
                ModelInfo(
                    id="gpt-4",
                    name="GPT-4",
                    provider="openai",
                    description="OpenAI의 고성능 GPT-4 모델"
                ),
                ModelInfo(
                    id="gpt-3.5-turbo",
                    name="GPT-3.5 Turbo",
                    provider="openai",
                    description="OpenAI의 빠르고 저렴한 GPT-3.5 모델"
                ),
                ModelInfo(
                    id="gpt-5-chat-latest",
                    name="GPT-5 Chat",
                    provider="openai",
                    description="OpenAI GPT-5 채팅 모델 (로컬 개발용)"
                ),
            ])
        
        # Anthropic Direct 모델 (로컬 개발용)
        models.extend([
            ModelInfo(
                id="claude-sonnet-4-5-20250929",
                name="Claude 4.5 Sonnet",
                provider="anthropic",
                description="Anthropic의 범용 Sonnet 모델 (로컬 개발용)"
            ),
            ModelInfo(
                id="claude-haiku-4-5-20251001",
                name="Claude 4.5 Haiku",
                provider="anthropic",
                description="낮은 지연시간의 경량 Claude 모델 (로컬 개발용)"
            ),
        ])
        
        # Google Gemini 모델 (로컬 개발용)
        models.extend([
            ModelInfo(
                id="gemini-2.5-flash",
                name="Gemini 2.5 Flash",
                provider="google",
                description="Google Gemini 2.5 Flash 모델 (로컬 개발용)"
            ),
            ModelInfo(
                id="gemini-2.5-pro",
                name="Gemini 2.5 Pro",
                provider="google",
                description="Google Gemini 2.5 Pro 모델 (로컬 개발용)"
            ),
        ])

        return ModelsResponse(models=models)

    except Exception as e:
        logger.error(f"Failed to get models: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"모델 목록 조회 실패: {str(e)}"
        )


def _log_llm_selection(bot_id: str, workflow: Workflow) -> None:
    """저장 시 선택된 LLM Provider/Model 로그"""
    for node in workflow.nodes:
        if node.type != "llm":
            continue
        data = node.data or {}
        provider = data.get("provider")
        raw_model = data.get("model")

        model_name = None
        if isinstance(raw_model, dict):
            provider = provider or raw_model.get("provider")
            model_name = raw_model.get("name") or raw_model.get("id")
        else:
            model_name = raw_model

        provider = _infer_provider(provider, model_name)
        logger.info(
            "[Workflow] Bot %s LLM node %s saved with provider=%s model=%s",
            bot_id,
            node.id,
            provider,
            model_name or "default"
        )


def _infer_provider(provider: Optional[str], model_name: Optional[str]) -> str:
    """모델명 기반 provider 추론 (로그용)"""
    if provider:
        return provider
    if not model_name:
        return settings.llm_provider or "openai"
    lowered = model_name.lower()
    if lowered.startswith("gpt") or lowered.startswith("o1"):
        return "openai"
    if lowered.startswith("claude"):
        return "anthropic"
    if lowered.startswith("gemini"):
        return "google"
    if "/" in lowered:
        return lowered.split("/")[0]
    return settings.llm_provider or "openai"
