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

    async def generate_response(
        self,
        request: ChatRequest
    ) -> ChatResponse:
        """챗봇 응답 생성 (RAG 파이프라인)"""

        logger.info(f"챗봇 요청: '{request.message[:50]}...'")

        try:
            # 1. 쿼리 임베딩 생성
            logger.debug("쿼리 임베딩 생성 중...")
            # 사용자의 질문 텍스트(request.message)를 임베딩 벡터(List[float])로 변환
            # 이후 벡터 스토어 유사도 검색에 입력으로 사용
            query_embedding = self.embedding_service.embed_query(request.message)

            # 2. 벡터 검색
            logger.debug(f"벡터 검색 중 (top_k={request.top_k})...")
            search_results = self.vector_store.search(
                query_embedding=query_embedding,
                top_k=request.top_k
            )

            # 3. 검색 결과 추출
            retrieved_chunks = self._extract_chunks(search_results)

            if not retrieved_chunks:
                logger.warning("검색 결과 없음")
                return ChatResponse(
                    response="죄송합니다. 관련 문서를 찾을 수 없습니다. 다른 질문을 해주세요.",
                    sources=[],
                    session_id=request.session_id or "default",
                    retrieved_chunks=0
                )

            # 4. 컨텍스트 구성
            logger.debug(f"컨텍스트 구성 중 ({len(retrieved_chunks)}개 청크)...")
            context = self.prompt_template.format_context(retrieved_chunks)

            # 5. 프롬프트 메시지 생성
            messages = self.prompt_template.build_messages(
                user_query=request.message,
                context=context
            )

            # 6. LLM 호출
            logger.info("LLM API 호출 중...")
            llm_response = await self.llm_client.generate(
                messages=messages,
                temperature=settings.chat_temperature,
                max_tokens=settings.chat_max_tokens
            )

            logger.info(f"LLM 응답 생성 완료 ({len(llm_response)} 글자)")

            # 7. 출처 정보 생성
            sources = self._build_sources(retrieved_chunks, search_results)

            # LLM 응답과 메타데이터를 담아 ChatResponse 객체로 최종 반환
            return ChatResponse(
                # LLM이 생성한 최종 답변 문자열
                response=llm_response,
                # 검색된 출처 리스트를 포함, 아니면 빈 리스트로 반환
                # 벡터 검색으로 찾아낸 근거 문서들의 메타데이터 목록
                sources=sources if request.include_sources else [],
                # 요청에 세션 ID가 없으면 "default"로 대체
                session_id=request.session_id or "default",
                # 벡터 검색으로 실제로 프롬프트 컨텍스트에 사용된 청크 개수
                retrieved_chunks=len(retrieved_chunks)
            )

        except Exception as e:
            logger.error(f"챗봇 응답 생성 실패: {e}", exc_info=True)
            raise
