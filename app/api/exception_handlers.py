"""
FastAPI 글로벌 예외 핸들러

모든 커스텀 예외를 적절한 HTTP 응답으로 변환합니다.
"""
import logging
from fastapi import Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.exceptions import (
    BaseAppException,
    # Database exceptions
    DatabaseError,
    DatabaseConnectionError,
    DatabaseTransactionError,
    DatabaseQueryError,
    # Vector Store exceptions
    VectorStoreError,
    VectorStoreConnectionError,
    VectorStoreQueryError,
    VectorStoreDocumentError,
    # Document Processing exceptions
    DocumentProcessingError,
    DocumentParsingError,
    DocumentChunkingError,
    UnsupportedDocumentTypeError,
    # LLM Service exceptions
    LLMServiceError,
    LLMAPIError,
    LLMRateLimitError,
    LLMInvalidResponseError,
    # Bot Service exceptions
    BotServiceError,
    BotNotFoundError,
    BotCreationError,
    BotConfigurationError,
    # Chat Service exceptions
    ChatServiceError,
    ChatSessionError,
    ChatMessageError,
    # Workflow exceptions
    WorkflowError,
    WorkflowExecutionError,
    WorkflowValidationError,
    # Authentication exceptions
    AuthenticationError,
    InvalidCredentialsError,
    TokenError,
    UnauthorizedError,
    # File Upload exceptions
    FileUploadError,
    InvalidFileTypeError,
    FileSizeExceededError,
    FileProcessingError,
    # Validation exceptions
    ValidationError,
    InvalidInputError,
    ResourceNotFoundError,
)

logger = logging.getLogger(__name__)


# 예외 타입별 HTTP 상태 코드 매핑
EXCEPTION_STATUS_MAP = {
    # 400 Bad Request
    ValidationError: status.HTTP_400_BAD_REQUEST,
    InvalidInputError: status.HTTP_400_BAD_REQUEST,
    BotConfigurationError: status.HTTP_400_BAD_REQUEST,
    WorkflowValidationError: status.HTTP_400_BAD_REQUEST,
    UnsupportedDocumentTypeError: status.HTTP_400_BAD_REQUEST,
    InvalidFileTypeError: status.HTTP_400_BAD_REQUEST,
    FileSizeExceededError: status.HTTP_400_BAD_REQUEST,

    # 401 Unauthorized
    UnauthorizedError: status.HTTP_401_UNAUTHORIZED,
    TokenError: status.HTTP_401_UNAUTHORIZED,
    InvalidCredentialsError: status.HTTP_401_UNAUTHORIZED,

    # 404 Not Found
    ResourceNotFoundError: status.HTTP_404_NOT_FOUND,
    BotNotFoundError: status.HTTP_404_NOT_FOUND,

    # 422 Unprocessable Entity
    DocumentParsingError: status.HTTP_422_UNPROCESSABLE_ENTITY,
    DocumentChunkingError: status.HTTP_422_UNPROCESSABLE_ENTITY,
    FileProcessingError: status.HTTP_422_UNPROCESSABLE_ENTITY,

    # 429 Too Many Requests
    LLMRateLimitError: status.HTTP_429_TOO_MANY_REQUESTS,

    # 500 Internal Server Error (서버 측 오류)
    DatabaseError: status.HTTP_500_INTERNAL_SERVER_ERROR,
    DatabaseConnectionError: status.HTTP_500_INTERNAL_SERVER_ERROR,
    DatabaseTransactionError: status.HTTP_500_INTERNAL_SERVER_ERROR,
    DatabaseQueryError: status.HTTP_500_INTERNAL_SERVER_ERROR,
    VectorStoreError: status.HTTP_500_INTERNAL_SERVER_ERROR,
    VectorStoreConnectionError: status.HTTP_500_INTERNAL_SERVER_ERROR,
    VectorStoreQueryError: status.HTTP_500_INTERNAL_SERVER_ERROR,
    VectorStoreDocumentError: status.HTTP_500_INTERNAL_SERVER_ERROR,

    # 502 Bad Gateway (외부 서비스 오류)
    LLMAPIError: status.HTTP_502_BAD_GATEWAY,
    LLMInvalidResponseError: status.HTTP_502_BAD_GATEWAY,

    # 503 Service Unavailable
    LLMServiceError: status.HTTP_503_SERVICE_UNAVAILABLE,
    BotServiceError: status.HTTP_503_SERVICE_UNAVAILABLE,
    ChatServiceError: status.HTTP_503_SERVICE_UNAVAILABLE,
    WorkflowError: status.HTTP_503_SERVICE_UNAVAILABLE,
    ChatSessionError: status.HTTP_503_SERVICE_UNAVAILABLE,
    ChatMessageError: status.HTTP_503_SERVICE_UNAVAILABLE,
    BotCreationError: status.HTTP_503_SERVICE_UNAVAILABLE,
    WorkflowExecutionError: status.HTTP_503_SERVICE_UNAVAILABLE,
    DocumentProcessingError: status.HTTP_503_SERVICE_UNAVAILABLE,
}


def get_http_status_code(exception: BaseAppException) -> int:
    """
    예외 객체에 대한 HTTP 상태 코드 반환

    매핑에 없는 경우 기본값으로 500 반환
    """
    exception_type = type(exception)
    return EXCEPTION_STATUS_MAP.get(exception_type, status.HTTP_500_INTERNAL_SERVER_ERROR)


async def base_app_exception_handler(request: Request, exc: BaseAppException) -> JSONResponse:
    """
    모든 BaseAppException 및 하위 클래스 처리

    커스텀 예외를 적절한 HTTP 응답으로 변환합니다.
    """
    status_code = get_http_status_code(exc)

    # 500번대 에러는 상세 에러 정보를 숨김 (보안)
    if status_code >= 500:
        logger.error(
            f"Server error: {exc.message}",
            extra={
                "error_code": exc.error_code,
                "details": exc.details,
                "path": request.url.path,
                "method": request.method
            },
            exc_info=True
        )
        # 클라이언트에는 일반적인 메시지만 전달
        response_body = {
            "error": "Internal Server Error",
            "message": "서버 내부 오류가 발생했습니다. 잠시 후 다시 시도해주세요.",
            "error_code": exc.error_code,
            "path": request.url.path
        }
    else:
        # 4xx 에러는 상세 정보 포함 가능
        logger.warning(
            f"Client error: {exc.message}",
            extra={
                "error_code": exc.error_code,
                "details": exc.details,
                "path": request.url.path,
                "method": request.method
            }
        )
        response_body = {
            "error": exc.__class__.__name__,
            "message": exc.message,
            "error_code": exc.error_code,
            "details": exc.details,
            "path": request.url.path
        }

    return JSONResponse(
        status_code=status_code,
        content=response_body
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """
    Pydantic 검증 오류 처리
    """
    logger.warning(
        f"Validation error: {exc.errors()}",
        extra={
            "path": request.url.path,
            "method": request.method
        }
    )

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error": "ValidationError",
            "message": "요청 데이터 검증에 실패했습니다",
            "details": exc.errors(),
            "path": request.url.path
        }
    )


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """
    HTTPException 처리
    """
    logger.info(
        f"HTTP exception: {exc.status_code} - {exc.detail}",
        extra={
            "path": request.url.path,
            "method": request.method
        }
    )

    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": "HTTPException",
            "message": exc.detail,
            "path": request.url.path
        }
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    예상하지 못한 예외 처리 (최후의 방어선)
    """
    logger.error(
        f"Unhandled exception: {str(exc)}",
        extra={
            "path": request.url.path,
            "method": request.method,
            "exception_type": type(exc).__name__
        },
        exc_info=True
    )

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": "InternalServerError",
            "message": "예기치 않은 오류가 발생했습니다. 관리자에게 문의해주세요.",
            "path": request.url.path
        }
    )
