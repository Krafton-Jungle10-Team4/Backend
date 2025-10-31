"""
애플리케이션 설정 관리
"""
from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    """애플리케이션 설정 클래스"""
    
    # 애플리케이션
    app_name: str = "FastAPI RAG Backend"
    app_version: str = "1.0.0"
    debug: bool = False
    log_level: str = "info"
    
    # 서버
    host: str = "0.0.0.0"
    port: int = 8000
    workers: int = 4
    
    # AWS
    aws_region: str = "ap-northeast-2"
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    s3_bucket_name: str = ""
    
    # ChromaDB
    chroma_host: str = "localhost"
    chroma_port: int = 8001
    chroma_collection_name: str = "documents"
    
    # 임베딩
    embedding_model: str = "BAAI/bge-small-en-v1.5"  # EC2 무료 티어 대응 (~100MB)
    embedding_device: str = "cpu"
    batch_size: int = 32
    
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
    
    class Config:
        env_file = ".env.local"
        case_sensitive = False


settings = Settings()
