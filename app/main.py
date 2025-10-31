"""
FastAPI RAG Backend - 메인 애플리케이션
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.api.v1.endpoints import upload
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

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API 라우터 등록
app.include_router(upload.router, prefix="/api/v1")


@app.on_event("startup")
async def startup_event():
    """애플리케이션 시작 시 실행"""
    logger.info(f"{settings.app_name} v{settings.app_version} 시작")
    logger.info(f"디버그 모드: {settings.debug}")
    logger.info(f"임베딩 모델: {settings.embedding_model}")

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
