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
        # 프롬프트를 기반으로 응답을 생성하는 모델 호출 래퍼
        self.llm_client = get_llm_client()
        # RAG 응답 생성을 위한 시스템/사용자 메시지 템플릿 관리
        self.prompt_template = PromptTemplate()

        logger.info("ChatService 초기화 완료")

    async def generate_response(
        self,
        request: ChatRequest,
        team_uuid: str
    ) -> ChatResponse:
        """챗봇 응답 생성 (RAG 파이프라인)"""

        logger.info(f"챗봇 요청: '{request.message[:50]}...'")

        # 팀별 벡터 스토어 가져오기
        vector_store = get_vector_store(team_uuid=team_uuid)

        try:
            # 1. 쿼리 임베딩 생성
            logger.debug("쿼리 임베딩 생성 중...")
            # 사용자의 질문 텍스트(request.message)를 임베딩 벡터(List[float])로 변환
            # 이후 벡터 스토어 유사도 검색에 입력으로 사용
            query_embedding = self.embedding_service.embed_query(request.message)

            # 2. 벡터 검색
            logger.debug(f"벡터 검색 중 (top_k={request.top_k})...")
            search_results = vector_store.search(
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

    def _extract_chunks(self, search_results: Dict) -> List[Dict]:
        """벡터 검색 결과에서 청크 추출"""
        chunks = []

        if not search_results.get("documents"):
            return chunks

        # ChromaDB는 2차원 배열 반환 (여러 쿼리 지원)
        documents = search_results["documents"][0]
        metadatas = search_results.get("metadatas", [[]])[0]

        for doc, meta in zip(documents, metadatas):
            chunks.append({
                "document": doc,
                "metadata": meta
            })

        logger.debug(f"{len(chunks)}개 청크 추출 완료")
        return chunks

    def _build_sources(
        self,
        chunks: List[Dict],
        search_results: Dict
    ) -> List[Source]:
        """출처 정보 생성"""
        sources = []  # 최종적으로 응답에 포함할 출처 정보 리스트

        # 검색 결과에서 각 청크의 고유 ID 배열(첫 번째 쿼리 결과만 사용)
        ids = search_results.get("ids", [[]])[0]
        # 검색 결과에서 각 청크까지의 거리 배열(값이 낮을수록 더 유사, 첫 번째 쿼리 결과만 사용)
        distances = search_results.get("distances", [[]])[0]

        # 추출된 청크들을 순회하며 출처 정보를 구성
        for i, chunk in enumerate(chunks):
            # 각 청크에 저장된 메타데이터(문서 ID, 파일명, 청크 인덱스 등)
            metadata = chunk.get("metadata", {})

            # 유사도 점수 계산 (거리 -> 유사도 변환)
            # ChromaDB 기본 L2 거리: 낮을수록 유사하므로 1/(1+거리) 형태로 정규화
            # distance가 0이면 → similarity = 1 / (1+0) = 1.0 (완전 동일에 가깝다)
            # distance가 클수록 → similarity = 1 / (1+distance) → 0.0에 가까워짐 (거리가 멀수록 유사도 낮아짐)
            similarity_score = 1.0 / (1.0 + distances[i]) if i < len(distances) else 0.0

            # 한 개의 출처(Source) 레코드를 생성해 리스트에 추가
            sources.append(Source(
                # 문서를 식별할 ID (없으면 "unknown"으로 대체)
                document_id=metadata.get("document_id", "unknown"),
                # 청크의 고유 ID (ids 범위 밖이면 임시 ID 부여)
                chunk_id=ids[i] if i < len(ids) else f"chunk_{i}",
                # 미리보기용 청크 내용(너무 길지 않도록 앞 200자만 포함)
                content=chunk.get("document", "")[:200],  # 200자 제한
                # 계산된 유사도 점수(소수 셋째 자리까지 반올림)
                similarity_score=round(similarity_score, 3),
                # 추가 메타데이터(파일명, 문서 내 청크 인덱스, 파일 타입 등)
                metadata={
                    "filename": metadata.get("filename"),
                    "chunk_index": metadata.get("chunk_index"),
                    "file_type": metadata.get("file_type")
                }
            ))

        return sources


# 싱글톤 인스턴스
_chat_service: Optional[ChatService] = None


def get_chat_service() -> ChatService:
    """챗봇 서비스 싱글톤 인스턴스 반환"""
    global _chat_service
    if _chat_service is None:
        _chat_service = ChatService()
    return _chat_service
