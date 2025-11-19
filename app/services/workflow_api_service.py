"""
워크플로우 API 실행 서비스

RESTful API를 통한 워크플로우 실행 로직
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi import HTTPException, status
from typing import Dict, Any, Optional
from datetime import datetime, timezone
import uuid
import logging

from app.models.workflow_version import BotWorkflowVersion, WorkflowExecutionRun
from app.models.bot_api_key import BotAPIKey
from app.core.workflow.executor_v2 import WorkflowExecutorV2

logger = logging.getLogger(__name__)


class WorkflowAPIService:
    """워크플로우 API 실행 서비스"""
    
    @staticmethod
    async def validate_inputs_against_schema(
        inputs: Dict[str, Any],
        input_value: Optional[str],
        schema: Optional[list]
    ) -> None:
        """
        입력값을 Input Schema와 비교하여 검증
        
        Args:
            inputs: 사용자 입력 딕셔너리
            input_value: 대표 입력값 (Input Schema의 is_primary 필드)
            schema: Input Schema (list of dict)
        
        Raises:
            HTTPException: 검증 실패 시
        """
        if not schema:
            # 스키마가 정의되지 않았으면 검증 생략
            return
        
        for field in schema:
            key = field.get("key")
            required = field.get("required", False)
            field_type = field.get("type", "string")
            is_primary = field.get("is_primary", False)
            
            # is_primary 필드와 input_value 동기화 확인
            if is_primary and required:
                if not input_value and key not in inputs:
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        detail={
                            "code": "VALIDATION_ERROR",
                            "message": f"'{key}' is required (primary input)",
                            "field": key
                        }
                    )
                
                # input_value가 있으면 inputs[key]에 자동 매핑
                if input_value and key not in inputs:
                    inputs[key] = input_value
            
            # 필수 필드 체크
            if required and key not in inputs:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail={
                        "code": "VALIDATION_ERROR",
                        "message": f"'{key}' is required",
                        "field": key
                    }
                )
            
            # 필드가 제공된 경우 타입 검증
            if key in inputs:
                value = inputs[key]
                
                # 타입 검증
                if not WorkflowAPIService._is_type(value, field_type):
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        detail={
                            "code": "VALIDATION_ERROR",
                            "message": f"'{key}' must be of type '{field_type}'",
                            "field": key
                        }
                    )
                
                # enum 타입 검증
                if field_type == "enum":
                    allowed_options = field.get("options", [])
                    if value not in allowed_options:
                        raise HTTPException(
                            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail={
                                "code": "VALIDATION_ERROR",
                                "message": f"'{key}' must be one of {allowed_options}",
                                "field": key,
                                "allowed_values": allowed_options
                            }
                        )
    
    @staticmethod
    def _is_type(value: Any, expected_type: str) -> bool:
        """값이 예상 타입과 일치하는지 확인"""
        type_mapping = {
            "string": str,
            "number": (int, float),
            "integer": int,
            "float": float,
            "boolean": bool,
            "enum": str,  # enum은 문자열로 취급
            "array": list,
            "object": dict
        }
        
        expected_python_type = type_mapping.get(expected_type)
        if not expected_python_type:
            # 알 수 없는 타입은 통과
            return True
        
        return isinstance(value, expected_python_type)
    
    @staticmethod
    async def get_workflow_version_for_api_key(
        api_key: BotAPIKey,
        db: AsyncSession
    ) -> BotWorkflowVersion:
        """
        API 키에 바인딩된 워크플로우 버전 조회
        
        Args:
            api_key: BotAPIKey 모델
            db: 데이터베이스 세션
        
        Returns:
            BotWorkflowVersion: 실행할 워크플로우 버전
        """
        if api_key.bind_to_latest_published:
            # 최신 published 버전 조회
            result = await db.execute(
                select(BotWorkflowVersion)
                .where(
                    BotWorkflowVersion.bot_id == api_key.bot_id,
                    BotWorkflowVersion.published_at.isnot(None)
                )
                .order_by(BotWorkflowVersion.published_at.desc())
                .limit(1)
            )
            workflow_version = result.scalar_one_or_none()
            
            if not workflow_version:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail={
                        "code": "NO_PUBLISHED_VERSION",
                        "message": "No published workflow version available"
                    }
                )
            
            return workflow_version
        else:
            # 고정 버전 사용
            if not api_key.workflow_version_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "code": "NO_VERSION_BOUND",
                        "message": "API key is not bound to any workflow version"
                    }
                )
            
            result = await db.execute(
                select(BotWorkflowVersion)
                .where(BotWorkflowVersion.id == api_key.workflow_version_id)
            )
            workflow_version = result.scalar_one_or_none()
            
            if not workflow_version:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={
                        "code": "VERSION_NOT_FOUND",
                        "message": "Workflow version not found"
                    }
                )
            
            if not workflow_version.published_at:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail={
                        "code": "VERSION_NOT_PUBLISHED",
                        "message": "Workflow version is not published"
                    }
                )
            
            return workflow_version
    
    @staticmethod
    async def execute_workflow_via_api(
        workflow_version: BotWorkflowVersion,
        inputs: Dict[str, Any],
        input_value: Optional[str],
        session_id: Optional[str],
        user_id: Optional[str],
        api_key: BotAPIKey,
        metadata: Dict[str, Any],
        response_mode: str,
        db: AsyncSession
    ) -> Dict[str, Any]:
        """
        API를 통한 워크플로우 실행
        
        Args:
            workflow_version: 실행할 워크플로우 버전
            inputs: 입력 변수
            input_value: 대표 입력값
            session_id: 세션 ID (대화 연속성)
            user_id: 최종 사용자 ID
            api_key: API 키
            metadata: 메타데이터
            response_mode: 응답 모드 (blocking/streaming)
            db: 데이터베이스 세션
        
        Returns:
            실행 결과 딕셔너리
        """
        # 1. WorkflowExecutionRun 생성
        run_id = uuid.uuid4()
        execution_run = WorkflowExecutionRun(
            id=run_id,
            bot_id=workflow_version.bot_id,
            workflow_version_id=workflow_version.id,
            session_id=session_id or f"api_session_{uuid.uuid4().hex[:16]}",
            user_id=user_id,
            api_key_id=api_key.id,
            api_request_id=metadata.get("request_id"),
            graph_snapshot=workflow_version.graph,
            inputs=inputs,
            status="running",
            started_at=datetime.now(timezone.utc)
        )
        
        db.add(execution_run)
        await db.commit()
        await db.refresh(execution_run)
        
        try:
            # 2. 워크플로우 실행
            executor = WorkflowExecutorV2(
                workflow_version=workflow_version,
                session_id=execution_run.session_id,
                db=db
            )
            
            # 실행 (blocking 모드)
            result = await executor.execute(inputs=inputs)
            
            # 3. 실행 결과 업데이트
            execution_run.status = "completed"
            execution_run.outputs = result.get("outputs", {})
            execution_run.finished_at = datetime.now(timezone.utc)
            execution_run.elapsed_time = int((execution_run.finished_at - execution_run.started_at).total_seconds() * 1000)
            execution_run.total_tokens = result.get("usage", {}).get("total_tokens", 0)
            
            await db.commit()
            await db.refresh(execution_run)
            
            # 4. 응답 생성
            return {
                "workflow_run_id": str(execution_run.id),
                "bot_id": execution_run.bot_id,
                "workflow_version_id": str(execution_run.workflow_version_id),
                "status": execution_run.status,
                "outputs": execution_run.outputs,
                "usage": {
                    "prompt_tokens": result.get("usage", {}).get("prompt_tokens", 0),
                    "completion_tokens": result.get("usage", {}).get("completion_tokens", 0),
                    "total_tokens": execution_run.total_tokens
                },
                "created_at": execution_run.started_at.isoformat(),
                "finished_at": execution_run.finished_at.isoformat(),
                "elapsed_time": execution_run.elapsed_time / 1000.0,  # seconds
                "session_id": execution_run.session_id
            }
        
        except Exception as e:
            # 실행 실패
            logger.error(f"워크플로우 실행 실패 (run_id={run_id}): {e}")
            
            execution_run.status = "failed"
            execution_run.error_message = str(e)
            execution_run.finished_at = datetime.now(timezone.utc)
            execution_run.elapsed_time = int((execution_run.finished_at - execution_run.started_at).total_seconds() * 1000)
            
            await db.commit()
            
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={
                    "code": "WORKFLOW_EXECUTION_FAILED",
                    "message": "Workflow execution failed",
                    "workflow_run_id": str(run_id),
                    "error": str(e)
                }
            )

