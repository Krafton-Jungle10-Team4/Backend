"""
커스텀 예외 클래스 정의

애플리케이션 전반에서 사용할 구체적인 예외 타입들을 정의합니다.
"""
from typing import Optional, Dict, Any


class BaseAppException(Exception):
    """애플리케이션 기본 예외 클래스"""

    def __init__(
        self,
        message: str,
        error_code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None
    ):
        self.message = message
        self.error_code = error_code
        self.details = details or {}
        super().__init__(self.message)


# ============================================================================
# 데이터베이스 관련 예외
# ============================================================================

class DatabaseError(BaseAppException):
    """데이터베이스 관련 기본 예외"""
    pass


class DatabaseConnectionError(DatabaseError):
    """데이터베이스 연결 실패"""
    def __init__(self, message: str = "데이터베이스 연결에 실패했습니다", **kwargs):
        super().__init__(message, error_code="DB_CONNECTION_ERROR", **kwargs)


class DatabaseTransactionError(DatabaseError):
    """데이터베이스 트랜잭션 실패"""
    def __init__(self, message: str = "데이터베이스 트랜잭션 처리 중 오류가 발생했습니다", **kwargs):
        super().__init__(message, error_code="DB_TRANSACTION_ERROR", **kwargs)


class DatabaseQueryError(DatabaseError):
    """데이터베이스 쿼리 실패"""
    def __init__(self, message: str = "데이터베이스 쿼리 실행 중 오류가 발생했습니다", **kwargs):
        super().__init__(message, error_code="DB_QUERY_ERROR", **kwargs)


# ============================================================================
# 벡터 스토어 관련 예외
# ============================================================================

class VectorStoreError(BaseAppException):
    """벡터 스토어 관련 기본 예외"""
    pass


class VectorStoreConnectionError(VectorStoreError):
    """벡터 스토어 연결 실패"""
    def __init__(self, message: str = "벡터 스토어 연결에 실패했습니다", **kwargs):
        super().__init__(message, error_code="VECTOR_STORE_CONNECTION_ERROR", **kwargs)


class VectorStoreQueryError(VectorStoreError):
    """벡터 스토어 쿼리 실패"""
    def __init__(self, message: str = "벡터 검색 중 오류가 발생했습니다", **kwargs):
        super().__init__(message, error_code="VECTOR_STORE_QUERY_ERROR", **kwargs)


class VectorStoreDocumentError(VectorStoreError):
    """벡터 스토어 문서 작업 실패"""
    def __init__(self, message: str = "문서 작업 중 오류가 발생했습니다", **kwargs):
        super().__init__(message, error_code="VECTOR_STORE_DOCUMENT_ERROR", **kwargs)


# ============================================================================
# 문서 처리 관련 예외
# ============================================================================

class DocumentProcessingError(BaseAppException):
    """문서 처리 관련 기본 예외"""
    pass


class DocumentParsingError(DocumentProcessingError):
    """문서 파싱 실패"""
    def __init__(self, message: str = "문서 파싱 중 오류가 발생했습니다", **kwargs):
        super().__init__(message, error_code="DOCUMENT_PARSING_ERROR", **kwargs)


class DocumentChunkingError(DocumentProcessingError):
    """문서 청킹 실패"""
    def __init__(self, message: str = "문서 청킹 중 오류가 발생했습니다", **kwargs):
        super().__init__(message, error_code="DOCUMENT_CHUNKING_ERROR", **kwargs)


class UnsupportedDocumentTypeError(DocumentProcessingError):
    """지원하지 않는 문서 타입"""
    def __init__(self, message: str = "지원하지 않는 문서 형식입니다", **kwargs):
        super().__init__(message, error_code="UNSUPPORTED_DOCUMENT_TYPE", **kwargs)


# ============================================================================
# LLM 서비스 관련 예외
# ============================================================================

class LLMServiceError(BaseAppException):
    """LLM 서비스 관련 기본 예외"""
    pass


class LLMAPIError(LLMServiceError):
    """LLM API 호출 실패"""
    def __init__(self, message: str = "LLM API 호출 중 오류가 발생했습니다", **kwargs):
        super().__init__(message, error_code="LLM_API_ERROR", **kwargs)


class LLMRateLimitError(LLMServiceError):
    """LLM API 사용량 제한"""
    def __init__(self, message: str = "API 사용량 제한에 도달했습니다", **kwargs):
        super().__init__(message, error_code="LLM_RATE_LIMIT_ERROR", **kwargs)


class LLMInvalidResponseError(LLMServiceError):
    """LLM 응답 형식 오류"""
    def __init__(self, message: str = "LLM 응답 형식이 올바르지 않습니다", **kwargs):
        super().__init__(message, error_code="LLM_INVALID_RESPONSE", **kwargs)


# ============================================================================
# 봇 서비스 관련 예외
# ============================================================================

class BotServiceError(BaseAppException):
    """봇 서비스 관련 기본 예외"""
    pass


class BotNotFoundError(BotServiceError):
    """봇을 찾을 수 없음"""
    def __init__(self, message: str = "봇을 찾을 수 없습니다", **kwargs):
        super().__init__(message, error_code="BOT_NOT_FOUND", **kwargs)


class BotCreationError(BotServiceError):
    """봇 생성 실패"""
    def __init__(self, message: str = "봇 생성 중 오류가 발생했습니다", **kwargs):
        super().__init__(message, error_code="BOT_CREATION_ERROR", **kwargs)


class BotConfigurationError(BotServiceError):
    """봇 설정 오류"""
    def __init__(self, message: str = "봇 설정이 올바르지 않습니다", **kwargs):
        super().__init__(message, error_code="BOT_CONFIGURATION_ERROR", **kwargs)


# ============================================================================
# 채팅 서비스 관련 예외
# ============================================================================

class ChatServiceError(BaseAppException):
    """채팅 서비스 관련 기본 예외"""
    pass


class ChatSessionError(ChatServiceError):
    """채팅 세션 오류"""
    def __init__(self, message: str = "채팅 세션 처리 중 오류가 발생했습니다", **kwargs):
        super().__init__(message, error_code="CHAT_SESSION_ERROR", **kwargs)


class ChatMessageError(ChatServiceError):
    """채팅 메시지 처리 오류"""
    def __init__(self, message: str = "메시지 처리 중 오류가 발생했습니다", **kwargs):
        super().__init__(message, error_code="CHAT_MESSAGE_ERROR", **kwargs)


# ============================================================================
# 워크플로우 관련 예외
# ============================================================================

class WorkflowError(BaseAppException):
    """워크플로우 관련 기본 예외"""
    pass


class WorkflowExecutionError(WorkflowError):
    """워크플로우 실행 오류"""
    def __init__(self, message: str = "워크플로우 실행 중 오류가 발생했습니다", **kwargs):
        super().__init__(message, error_code="WORKFLOW_EXECUTION_ERROR", **kwargs)


class WorkflowValidationError(WorkflowError):
    """워크플로우 검증 오류"""
    def __init__(self, message: str = "워크플로우 설정이 올바르지 않습니다", **kwargs):
        super().__init__(message, error_code="WORKFLOW_VALIDATION_ERROR", **kwargs)


# ============================================================================
# 인증 관련 예외
# ============================================================================

class AuthenticationError(BaseAppException):
    """인증 관련 기본 예외"""
    pass


class InvalidCredentialsError(AuthenticationError):
    """잘못된 인증 정보"""
    def __init__(self, message: str = "인증 정보가 올바르지 않습니다", **kwargs):
        super().__init__(message, error_code="INVALID_CREDENTIALS", **kwargs)


class TokenError(AuthenticationError):
    """토큰 관련 오류"""
    def __init__(self, message: str = "토큰이 유효하지 않습니다", **kwargs):
        super().__init__(message, error_code="TOKEN_ERROR", **kwargs)


class UnauthorizedError(AuthenticationError):
    """권한 없음"""
    def __init__(self, message: str = "접근 권한이 없습니다", **kwargs):
        super().__init__(message, error_code="UNAUTHORIZED", **kwargs)


# ============================================================================
# 파일 업로드 관련 예외
# ============================================================================

class FileUploadError(BaseAppException):
    """파일 업로드 관련 기본 예외"""
    pass


class InvalidFileTypeError(FileUploadError):
    """잘못된 파일 형식"""
    def __init__(self, message: str = "지원하지 않는 파일 형식입니다", **kwargs):
        super().__init__(message, error_code="INVALID_FILE_TYPE", **kwargs)


class FileSizeExceededError(FileUploadError):
    """파일 크기 초과"""
    def __init__(self, message: str = "파일 크기가 제한을 초과했습니다", **kwargs):
        super().__init__(message, error_code="FILE_SIZE_EXCEEDED", **kwargs)


class FileProcessingError(FileUploadError):
    """파일 처리 오류"""
    def __init__(self, message: str = "파일 처리 중 오류가 발생했습니다", **kwargs):
        super().__init__(message, error_code="FILE_PROCESSING_ERROR", **kwargs)


# ============================================================================
# 검증 관련 예외
# ============================================================================

class ValidationError(BaseAppException):
    """검증 관련 기본 예외"""
    pass


class InvalidInputError(ValidationError):
    """잘못된 입력값"""
    def __init__(self, message: str = "입력값이 올바르지 않습니다", **kwargs):
        super().__init__(message, error_code="INVALID_INPUT", **kwargs)


class ResourceNotFoundError(BaseAppException):
    """리소스를 찾을 수 없음"""
    def __init__(self, message: str = "요청한 리소스를 찾을 수 없습니다", **kwargs):
        super().__init__(message, error_code="RESOURCE_NOT_FOUND", **kwargs)
