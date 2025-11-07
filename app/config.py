"""
애플리케이션 설정 관리
"""
from pydantic_settings import BaseSettings
from typing import List, Optional
import os


class Settings(BaseSettings):
    """애플리케이션 설정 클래스"""
    
    # 애플리케이션
    app_name: str = "FastAPI RAG Backend"
    app_version: str = "1.0.0"
    debug: bool = False
    log_level: str = "info"
    environment: str = "development"  # development, staging, production
    
    #####################
    # Docker Hub diff
    dockerhub_username: str = ""
    dockerhub_token: str = ""
    #####################

    # 서버
    host: str = "0.0.0.0"
    port: int = 8000
    workers: int = 4
    
    # AWS
    aws_region: str = "ap-northeast-2"
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    s3_bucket_name: str = ""
    
    # Database
    database_url: str = ""

    # ChromaDB
    chroma_host: str = "localhost"
    chroma_port: int = 8001
    chroma_collection_name: str = "documents"
    
    # 임베딩
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"  # t3.medium 최적화 (~80MB, 2-3배 빠름): str = "BAAI/bge-small-en-v1.5"  # EC2 무료 티어 대응 (~100MB)
    embedding_device: str = "cpu"
    batch_size: int = 16  # CPU 최적화 (작은 배치가 CPU에서 더 빠름)
    
    # 문서 처리
    max_file_size: int = 10485760  # 10MB
    allowed_extensions: List[str] = ["pdf", "txt", "docx"]
    chunk_size: int = 512
    chunk_overlap: int = 128
    
    # 검색
    default_top_k: int = 5
    max_top_k: int = 50

    # 업로드
    upload_temp_dir: str = "./data/uploads"
    enable_async_processing: bool = True

    # LLM 설정
    llm_provider: str = "openai"

    # OpenAI - api key는 환경 변수로 관리
    openai_api_key: str = ""
    openai_model: str = "gpt-3.5-turbo"
    openai_organization: Optional[str] = None

    # Anthropic Claude
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-5-20250929"

    # 챗봇 설정
    # 생성 응답의 다양성(창의성): 높을 수록 창의적, 낮을 수록 일관적
    chat_temperature: float = 0.7
    # 한 번의 응답에서 생성할 최대 토큰 수
    chat_max_tokens: int = 1000
    # RAG 검색 시 상위 몇 개의 문서를 가져올지(top-k)
    # 너무 크면 느려지고, 유사하지 않은 정보가 검색되고
    # 너무 작으면 정보 누락이 생길 수 있음
    chat_default_top_k: int = 5

    # 인증 설정 (환경 변수에서 로드)
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = ""

    # JWT (환경 변수에서 로드)
    jwt_secret_key: str = ""
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15      # Access Token: 15분 (보안 강화)
    refresh_token_expire_days: int = 7         # Refresh Token: 7일

    # Session (환경 변수에서 로드)
    session_secret_key: str = ""  # OAuth 세션용 (JWT와 분리)

    # 프론트엔드 (환경 변수에서 로드)
    # 여러 URL을 쉼표로 구분 가능: "https://snapagent.shop,http://localhost:5173"
    frontend_url: str = ""

    def get_frontend_urls(self) -> List[str]:
        """프론트엔드 URL 리스트 반환 (쉼표로 구분된 경우)"""
        if not self.frontend_url:
            return []
        return [url.strip() for url in self.frontend_url.split(",")]

    @property
    def is_production(self) -> bool:
        """프로덕션 환경 여부 확인"""
        return self.environment.lower() == "production"

    @property
    def cors_origins(self) -> List[str]:
        """환경에 따른 CORS 허용 출처 반환"""
        frontend_urls = self.get_frontend_urls()
        if self.is_production:
            # 프로덕션: 설정된 프론트엔드 URL만 허용
            return frontend_urls if frontend_urls else []
        else:
            # 개발/스테이징: 프론트엔드 URL + localhost 허용
            dev_origins = ["http://localhost:5173", "http://localhost:3000"]
            return list(set(frontend_urls + dev_origins)) if frontend_urls else ["*"]

    class Config:
        # 환경에 따라 다른 .env 파일 로드
        # 로컬: .env.local (기본값)
        # 서버: ENV_FILE=.env.production 환경 변수 설정
        env_file = os.getenv("ENV_FILE", ".env.local")
        case_sensitive = False


settings = Settings()
