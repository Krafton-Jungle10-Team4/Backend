"""
FastAPI RAG Backend - 메인 애플리케이션
"""
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.middleware.sessions import SessionMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException
from slowapi.errors import RateLimitExceeded
from app.config import settings
from app.core.middleware.rate_limit import (
    limiter,
    public_limiter,
    custom_rate_limit_handler
)
from app.core.middleware.audit_logging import AuditLoggingMiddleware
from app.api.v1.endpoints import (
    upload,
    chat,
    auth,
    bots,
    workflows,
    deployment,
    widget,
    workflow_versions,
    workflow_executions
)
from app.core.exceptions import BaseAppException
from app.api.exception_handlers import (
    base_app_exception_handler,
    validation_exception_handler,
    http_exception_handler,
    unhandled_exception_handler
)
from app.core.logging_config import setup_logging, get_logger

# 구조화된 로깅 설정
setup_logging(
    log_level=settings.log_level,
    use_structured=True  # 구조화된 포맷 사용
)
logger = get_logger(__name__)

# FastAPI 앱 생성
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="RAG 기반 문서 검색 백엔드 API",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Rate limiter 등록
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, custom_rate_limit_handler)

# 글로벌 예외 핸들러 등록 (순서 중요: 구체적인 것부터 등록)
app.add_exception_handler(BaseAppException, base_app_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(StarletteHTTPException, http_exception_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)

# 세션 미들웨어 (OAuth에 필요)
# 보안: JWT와 Session Secret Key를 분리하는 이유
# 1. 단일 장애점 제거: 하나의 키 유출 시 전체 인증 시스템 침해 방지
# 2. 권한 분리 원칙: 각 인증 메커니즘(JWT, Session)은 독립적인 키 사용
# 3. 영향 범위 제한: Session 키 유출 시 OAuth만 영향, JWT는 안전
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret_key,  # Session 전용 시크릿 키 (JWT와 분리)
    max_age=1800,  # 30분
    same_site="lax",
    https_only=settings.is_production  # 프로덕션: HTTPS only, 개발: HTTP 허용
)

# CORS 설정 (커스텀 미들웨어)
cors_origins = settings.cors_origins
logger.info(f"CORS 허용 출처: {cors_origins}")

from app.core.middleware.widget_cors import WidgetCORSMiddleware
app.add_middleware(WidgetCORSMiddleware)

# 감사 로깅 미들웨어
app.add_middleware(AuditLoggingMiddleware)

# API 라우터 등록
app.include_router(auth.router, prefix="/api/v1/auth", tags=["인증"])
app.include_router(bots.router, prefix="/api/v1/bots", tags=["봇 관리"])
app.include_router(workflows.router, prefix="/api/v1", tags=["워크플로우"])
app.include_router(workflow_versions.router, prefix="/api/v1", tags=["워크플로우 V2 - 버전 관리"])
app.include_router(workflow_executions.router, prefix="/api/v1", tags=["워크플로우 V2 - 실행 기록"])
app.include_router(upload.router, prefix="/api/v1/documents", tags=["문서"])
app.include_router(chat.router, prefix="/api/v1/chat", tags=["챗봇"])
app.include_router(deployment.router, prefix="/api/v1/bots", tags=["배포 관리"])
app.include_router(widget.router, prefix="/api/v1/widget", tags=["Widget"])


@app.on_event("startup")
async def startup_event():
    """애플리케이션 시작 시 실행"""
    logger.info(f"{settings.app_name} v{settings.app_version} 시작")
    logger.info(f"디버그 모드: {settings.debug}")
    logger.info(f"임베딩 모델: {settings.embedding_model}")

    # 워크플로우 노드 등록
    logger.info("워크플로우 노드 등록 중...")
    from app.core.workflow.nodes import StartNode, EndNode, KnowledgeNode, LLMNode
    logger.info("✅ 워크플로우 노드 등록 완료")

    # Redis 연결
    try:
        from app.core.redis_client import redis_client
        await redis_client.connect()
    except Exception as e:
        logger.error(f"Redis 연결 실패, 계속 진행: {e}")

    # LLM 설정 검증
    logger.info("LLM 설정 검증 중...")
    if settings.llm_provider == "openai":
        if not settings.openai_api_key:
            raise ValueError(
                "❌ OPENAI_API_KEY가 설정되지 않았습니다. "
                ".env.local 파일을 확인하세요."
            )
        logger.info(f"✅ OpenAI 설정 완료 (모델: {settings.openai_model})")
    elif settings.llm_provider == "anthropic":
        if not settings.anthropic_api_key:
            raise ValueError(
                "❌ ANTHROPIC_API_KEY가 설정되지 않았습니다. "
                ".env.local 파일을 확인하세요."
            )
        logger.info(f"✅ Anthropic Claude 설정 완료 (모델: {settings.anthropic_model})")
    logger.info(f"🤖 LLM 제공자: {settings.llm_provider}")

    # 임베딩 모델 미리 로드 (Eager Loading)
    # logger.info("임베딩 모델 로딩 시작...")
    # from app.core.embeddings import get_embedding_service
    # embedding_service = get_embedding_service()
    # embedding_service.load_model()  # AWS Bedrock 사용으로 로컬 모델 로딩 불필요
    logger.info("✅ 임베딩 서비스 준비 완료 (AWS Bedrock 사용)")


@app.on_event("shutdown")
async def shutdown_event():
    """애플리케이션 종료 시 실행"""
    logger.info(f"{settings.app_name} 종료")

    # Redis 연결 종료
    from app.core.redis_client import redis_client
    await redis_client.close()

    # 임베딩 서비스 ThreadPoolExecutor 정리
    from app.core.embeddings import get_embedding_service
    embedding_service = get_embedding_service()
    embedding_service.shutdown()
    logger.info("✅ 임베딩 서비스 리소스 정리 완료")


@app.get("/")
async def root():
    """루트 엔드포인트"""
    return {
        "message": "FastAPI RAG Backend API",
        "version": settings.app_version,
        "docs": "/docs"
    }


@app.get("/health")
@limiter.limit(f"{settings.rate_limit_per_minute} per minute")
async def health_check(request: Request):
    """헬스 체크 엔드포인트"""
    return {
        "status": "healthy",
        "app_name": settings.app_name,
        "version": settings.app_version
    }


@app.get("/api/v1/health")
async def api_health_check():
    """API 버전별 헬스 체크"""
    return {
        "status": "healthy",
        "api_version": "v1",
        "app_version": settings.app_version
    }
