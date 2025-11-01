"""
RAG 챗봇 서비스
"""
import logging
from typing import List, Dict, Optional
from app.core.embeddings import get_embedding_service
from app.core.vector_store import get_vector_store
from app.core.llm_client import get_llm_client
from app.core.prompt_templates import PromptTemplate
from app.models.chat import ChatRequest, ChatResponse, Source
from app.config import settings

logger = logging.getLogger(__name__)


class ChatService:
    """RAG 챗봇 비즈니스 로직"""

    def __init__(self):
        # 입력 텍스트를 벡터(숫자 표현)로 변환
        self.embedding_service = get_embedding_service()
        # 임베딩을 저장/검색하여 유사 문서 조회(Retrieval) 수행
        self.vector_store = get_vector_store()
        # 프롬프트를 기반으로 응답을 생성하는 모델 호출 래퍼
        self.llm_client = get_llm_client()
        # RAG 응답 생성을 위한 시스템/사용자 메시지 템플릿 관리
        self.prompt_template = PromptTemplate()

        logger.info("ChatService 초기화 완료")
