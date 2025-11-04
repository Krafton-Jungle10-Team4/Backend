"""
FastAPI RAG Backend - 메인 애플리케이션
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from app.config import settings
from app.api.v1.endpoints import upload, chat, auth, teams, bots
import logging

# 로깅 설정
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper()),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# FastAPI 앱 생성
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="RAG 기반 문서 검색 백엔드 API",
    docs_url="/docs",
    redoc_url="/redoc"
)

# 세션 미들웨어 (OAuth에 필요)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.jwt_secret_key,  # JWT 시크릿 재사용
    max_age=1800,  # 30분
    same_site="lax",
    https_only=False  # 개발환경: False, 배포환경: True로 변경 필요
)

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API 라우터 등록
app.include_router(auth.router, prefix="/api/v1/auth", tags=["인증"])
app.include_router(teams.router, prefix="/api/v1/teams", tags=["팀 관리"])
app.include_router(bots.router, prefix="/api/v1/bots", tags=["봇 관리"])
app.include_router(upload.router, prefix="/api/v1/documents", tags=["문서"])
app.include_router(chat.router, prefix="/api/v1/chat", tags=["챗봇"])


@app.on_event("startup")
async def startup_event():
    """애플리케이션 시작 시 실행"""
    logger.info(f"{settings.app_name} v{settings.app_version} 시작")
    logger.info(f"디버그 모드: {settings.debug}")
    logger.info(f"임베딩 모델: {settings.embedding_model}")

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
    logger.info("임베딩 모델 로딩 시작...")
    from app.core.embeddings import get_embedding_service
    embedding_service = get_embedding_service()
    embedding_service.load_model()
    logger.info("✅ 임베딩 모델 로딩 완료 - API 요청 처리 준비됨")


@app.on_event("shutdown")
async def shutdown_event():
    """애플리케이션 종료 시 실행"""
    logger.info(f"{settings.app_name} 종료")


@app.get("/")
async def root():
    """루트 엔드포인트"""
    return {
        "message": "FastAPI RAG Backend API",
        "version": settings.app_version,
        "docs": "/docs"
    }


@app.get("/health")
async def health_check():
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
