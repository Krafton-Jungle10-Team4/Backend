"""
애플리케이션 설정 관리
"""
from pydantic_settings import BaseSettings
from pydantic import ConfigDict
from typing import List, Optional, Dict
import os


class Settings(BaseSettings):
    """애플리케이션 설정 클래스"""
    
    # 애플리케이션
    app_name: str = "FastAPI RAG Backend"
    app_version: str = "1.0.0"
    debug: bool = False
    log_level: str = "info"
    use_structured_logging: bool = True  # 구조화된 로깅 사용 여부 (가독성 향상)
    environment: str = "development"  # development, staging, production
    auto_run_migrations: bool = True  # 앱 기동 시 alembic upgrade 실행 여부
    
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

    # AWS SQS (비동기 문서 처리)
    sqs_queue_url: str = ""  # 메인 큐 URL
    sqs_queue_arn: str = ""  # 메인 큐 ARN
    sqs_dlq_url: str = ""    # DLQ URL
    sqs_dlq_arn: str = ""    # DLQ ARN
    
    # Database
    database_url: str = ""
    database_host: str = "localhost"
    database_port: int = 5432
    database_name: str = "ragdb"
    database_user: str = "postgres"
    database_password: str = ""
    database_ssl_mode: str = "prefer"  # disable | prefer | require

    # ChromaDB
    chroma_host: str = "localhost"
    chroma_port: int = 8001
    chroma_collection_name: str = "documents"

    # Redis
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_password: str = ""
    redis_db: int = 0
    redis_url: str = ""
    redis_use_ssl: bool = False

    # 연결 문자열 생성 규칙을 한 곳에 모아 일관성 있게 관리하려는 목적
    # 비밀번호 포함/미포함, 기본값 처리 등을 캡슐화
    def get_database_url(self) -> str:
        """
        환경에 맞는 Database URL 반환
        - 로컬: SSL 없음
        - 프로덕션: SSL 필수
        """
        # database_url이 명시되어 있으면 우선 사용
        if self.database_url:
            base_url = self.database_url

            # 프로덕션: SSL 파라미터 추가 (asyncpg용)
            if self.is_production:
                # 이미 SSL 파라미터가 있는지 확인
                if "ssl=" not in base_url:
                    separator = "&" if "?" in base_url else "?"
                    return f"{base_url}{separator}ssl=require"
                return base_url
            else:
                # 로컬: SSL 파라미터 제거 또는 그대로 사용
                if "sslmode=disable" in base_url:
                    return base_url
                # SSL 파라미터가 있다면 제거
                if "sslmode=" in base_url:
                    import re
                    # SSL 관련 파라미터 제거
                    base_url = re.sub(r'[?&]ssl(mode)?=[^&]+', '', base_url)
                    # 불필요한 ? 또는 & 정리
                    base_url = base_url.replace("?&", "?").rstrip("?&")
                return base_url

        # database_url이 없으면 개별 설정으로 구성
        user = self.database_user
        password = self.database_password
        host = self.database_host
        port = self.database_port
        name = self.database_name

        base_url = f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{name}"

        if self.is_production:
            return f"{base_url}?ssl=require"
        else:
            return base_url

    def get_database_url_sync(self) -> str:
        """
        Alembic 등 동기 드라이버에서 사용할 수 있는 Database URL
        (asyncpg 접두사가 있으면 제거)
        """
        url = self.get_database_url()
        if "+asyncpg" in url:
            return url.replace("+asyncpg", "")
        return url

    def get_redis_url(self) -> str:
        """
        환경에 맞는 Redis URL 반환
        - 로컬: redis:// (비암호화)
        - 프로덕션: rediss:// (TLS)
        """
        # redis_url이 명시되어 있으면 우선 사용
        if self.redis_url:
            return self.redis_url

        # 프로덕션: TLS 사용
        if self.is_production or self.redis_use_ssl:
            protocol = "rediss"
            port = self.redis_port or 6379  # ElastiCache는 6379에서도 TLS 지원
        else:
            # 로컬: 비암호화
            protocol = "redis"
            port = self.redis_port or 6379

        # URL 구성
        if self.redis_password:
            return f"{protocol}://:{self.redis_password}@{self.redis_host}:{port}/{self.redis_db}"
        else:
            return f"{protocol}://{self.redis_host}:{port}/{self.redis_db}"

    # Rate Limiting
    rate_limit_enabled: bool = True
    rate_limit_per_minute: int = 100
    rate_limit_public_per_hour: int = 1000

    # 임베딩 설정
    use_mock_embeddings: bool = False  # 로컬 개발용 Mock 임베딩 사용 여부

    # 임베딩 (레거시 - 로컬 모델)
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"  # t3.medium 최적화 (~80MB, 2-3배 빠름)
    embedding_device: str = "cpu"
    batch_size: int = 16  # CPU 최적화 (작은 배치가 CPU에서 더 빠름)

    # AWS Bedrock 임베딩 (현재 사용 중)
    bedrock_model_id: str = "amazon.titan-embed-text-v2:0"  # Titan Embeddings v2
    bedrock_dimensions: int = 1024  # 임베딩 차원 (256, 384, 1024 선택 가능)
    bedrock_normalize: bool = True  # 벡터 정규화 (검색 성능 향상)

    # Bedrock API 재시도 및 Rate Limiting 설정
    bedrock_max_retries: int = 5  # 최대 재시도 횟수
    bedrock_retry_multiplier: int = 2  # Exponential backoff 배수
    bedrock_retry_min_wait: int = 1  # 최소 대기 시간 (초)
    bedrock_retry_max_wait: int = 60  # 최대 대기 시간 (초)
    bedrock_max_concurrent_requests: int = 3  # 동시 요청 제한 (rate limit 보호)
    bedrock_request_interval: float = 0.1  # 요청 간 최소 간격 (초)

    # Circuit Breaker 설정
    bedrock_circuit_failure_threshold: int = 10  # Circuit open 임계값 (연속 실패 횟수)
    bedrock_circuit_recovery_timeout: int = 60  # Circuit 복구 대기 시간 (초)
    
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

    # Google Gemini
    google_api_key: str = ""
    google_default_model: str = "gemini-2.5-flash"

    # Tavily Search
    tavily_api_key: Optional[str] = None

    # AWS Bedrock (Claude via AWS) - 서울 리전
    bedrock_region: str = "ap-northeast-2"
    bedrock_model: str = "anthropic.claude-3-haiku-20240307-v1:0"  # Haiku 3 (ON_DEMAND 지원)

    # 챗봇 설정
    # 생성 응답의 다양성(창의성): 높을 수록 창의적, 낮을 수록 일관적
    chat_temperature: float = 0.7
    # 한 번의 응답에서 생성할 최대 토큰 수
    chat_max_tokens: int = 4000
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

    # 백엔드 API 공개 URL (Widget 임베드 스크립트 등에서 사용)
    backend_url: str = "https://api.snapagent.store"

    # 백엔드 API 공개 URL (Widget WebSocket 등에서 사용)
    # 프로덕션: "https://snapagent.store", 개발: "http://localhost:8001"
    api_public_url: str = "http://localhost:8001"

    # Widget 설정 (명세 WIDGET_EMBEDDING_API_SPECIFICATION.md:144 준수)
    widget_session_expire_hours: int = 1  # Widget 세션 유효 시간 (1시간)
    widget_refresh_token_expire_days: int = 7  # Refresh Token 유효 시간

    def get_frontend_urls(self) -> List[str]:
        """프론트엔드 URL 리스트 반환 (쉼표로 구분된 경우)"""
        if not self.frontend_url:
            return []
        return [url.strip() for url in self.frontend_url.split(",")]

    @property
    def is_production(self) -> bool:
        """프로덕션 환경 여부"""
        return self.environment.lower() == "production"

    @property
    def is_staging(self) -> bool:
        """스테이징 환경 여부"""
        return self.environment.lower() == "staging"

    @property
    def is_development(self) -> bool:
        """개발 환경 여부"""
        return self.environment.lower() in ["development", "local", "dev"]

    @property
    def cors_origins(self) -> List[str]:
        """환경에 따른 CORS 허용 출처 반환"""
        frontend_urls = self.get_frontend_urls()
        if self.is_production:
            # 프로덕션: 설정된 프론트엔드 URL만 허용
            return frontend_urls if frontend_urls else []
        else:
            # 개발/스테이징: 프론트엔드 URL + localhost 허용
            dev_origins = ["http://localhost:5173", "http://localhost:3000", "http://localhost:3001"]
            return list(set(frontend_urls + dev_origins)) if frontend_urls else ["*"]

    @property
    def redis_ssl_config(self) -> Dict:
        """Redis SSL 설정 (redis-py용)"""
        if self.is_production or self.redis_use_ssl:
            import ssl
            return {
                "ssl_cert_reqs": ssl.CERT_NONE,  # AWS ElastiCache 자체 서명 인증서
            }
        return {}

    @property
    def should_use_mock_embeddings(self) -> bool:
        """Mock 임베딩 사용 여부 결정"""
        # 명시적으로 설정된 경우 우선
        if self.use_mock_embeddings:
            return True
        # 개발 환경이고 AWS 자격증명이 없는 경우
        if self.is_development and not (self.aws_access_key_id and self.aws_secret_access_key):
            return True
        return False

    @property
    def use_bedrock_embedding(self) -> bool:
        """AWS Bedrock 사용 여부"""
        return self.is_production or self.is_staging

    @property
    def embedding_config(self) -> Dict:
        """환경별 임베딩 설정"""
        if self.use_bedrock_embedding:
            return {
                "provider": "bedrock",
                "model_id": self.bedrock_model_id,
                "dimensions": self.bedrock_dimensions,
                "normalize": self.bedrock_normalize,
            }
        else:
            return {
                "provider": "local",
                "model": self.embedding_model,
                "device": self.embedding_device,
                "batch_size": self.batch_size,
            }

    model_config = ConfigDict(
        # 환경에 따라 다른 .env 파일 로드
        # 로컬: .env.local (기본값)
        # 서버: ENV_FILE=.env.production 환경 변수 설정
        env_file = os.getenv("ENV_FILE", ".env.local"),
        env_file_encoding = 'utf-8',
        case_sensitive = False,
        # 환경 변수를 .env 파일보다 우선
        env_prefix = "",
        # .env 파일이 없어도 에러 발생하지 않음
        extra = "ignore"
    )

settings = Settings()
