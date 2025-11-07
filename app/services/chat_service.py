"""
RAG 챗봇 서비스
"""
import logging
import threading
from typing import List, Dict, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.embeddings import get_embedding_service
from app.core.vector_store import get_vector_store
from app.core.llm_client import get_llm_client
from app.core.prompt_templates import PromptTemplate
from app.models.chat import ChatRequest, ChatResponse, Source
from app.config import settings
from app.utils.validators import sanitize_chat_query
from app.core.exceptions import (
    ChatServiceError,
    ChatMessageError,
    LLMServiceError,
    VectorStoreError
)

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
        team_uuid: str,
        db: Optional[AsyncSession] = None
    ) -> ChatResponse:
        """챗봇 응답 생성 (RAG 파이프라인 또는 Workflow 실행)"""

        logger.info(f"챗봇 요청: '{request.message[:50]}...'")

        # bot_id가 있으면 Workflow 실행
        if request.bot_id and db:
            return await self._execute_workflow(request, team_uuid, db)

        # 기본 RAG 파이프라인 실행
        return await self._execute_rag_pipeline(request, team_uuid)

    async def _execute_workflow(
        self,
        request: ChatRequest,
        team_uuid: str,
        db: AsyncSession
    ) -> ChatResponse:
        """Workflow 기반 응답 생성"""
        from app.services.bot_service import get_bot_service
        from app.services.workflow_engine import get_workflow_engine, WorkflowEngine
        from app.services.vector_service import get_vector_service
        from app.services.llm_service import get_llm_service

        logger.info(f"[ChatService] Workflow 실행: bot_id={request.bot_id}")

        # Bot 조회
        bot_service = get_bot_service()
        bot = await bot_service.get_bot_by_id(request.bot_id, None, db, include_workflow=True)

        if not bot:
            raise ValueError(f"Bot not found: {request.bot_id}")

        # Workflow가 없으면 기본 RAG 파이프라인으로 fallback
        if not bot.workflow:
            logger.info(f"[ChatService] Bot {request.bot_id}에 Workflow가 없어 기본 RAG 파이프라인 실행")
            return await self._execute_rag_pipeline(request, team_uuid)

        # 새로운 Workflow Executor로 실행
        from app.core.workflow.executor import WorkflowExecutor
        from app.services.vector_service import VectorService
        from app.services.llm_service import LLMService

        vector_service = VectorService()
        llm_service = LLMService()

        executor = WorkflowExecutor()

        # 런타임 모델 오버라이드 처리
        workflow_data = bot.workflow.copy() if bot.workflow else {}
        if request.model and workflow_data.get("nodes"):
            logger.info(f"[ChatService] 런타임 모델 오버라이드: {request.model}")
            for node in workflow_data["nodes"]:
                if node.get("type") == "llm" and node.get("data"):
                    original_model = node["data"].get("model")
                    node["data"]["model"] = request.model
                    logger.info(f"[ChatService] LLM 노드 모델 변경: {original_model} → {request.model}")

        # 워크플로우 실행
        response_text = await executor.execute(
            workflow_data=workflow_data,
            session_id=request.session_id or "default",
            user_message=request.message,
            vector_service=vector_service,
            llm_service=llm_service
        )

        # ChatResponse 형식으로 변환
        return ChatResponse(
            response=response_text,
            sources=[],
            session_id=request.session_id or "default",
            retrieved_chunks=0,
            metadata={}
        )

    async def _execute_rag_pipeline(
        self,
        request: ChatRequest,
        team_uuid: str
    ) -> ChatResponse:
        """기본 RAG 파이프라인 실행"""
        # 팀별 벡터 스토어 가져오기
        vector_store = get_vector_store(team_uuid=team_uuid)

        try:
            # 0. 사용자 입력 검증 및 정제
            try:
                sanitized_message = sanitize_chat_query(request.message)
                logger.debug(f"입력 검증 완료 (원본: {len(request.message)}자 → 정제: {len(sanitized_message)}자)")
            except ValueError as e:
                logger.warning(f"입력 검증 실패: {e}")
                return ChatResponse(
                    response=f"입력 오류: {str(e)}",
                    sources=[],
                    session_id=request.session_id or "default",
                    retrieved_chunks=0
                )

            # 1. 쿼리 임베딩 생성
            logger.debug("쿼리 임베딩 생성 중...")
            # 정제된 사용자 질문을 임베딩 벡터(List[float])로 변환
            # 비동기 메서드 호출 (이벤트 루프 블로킹 방지)
            query_embedding = await self.embedding_service.embed_query(sanitized_message)

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

            # 5. 프롬프트 메시지 생성 (정제된 메시지 사용)
            messages = self.prompt_template.build_messages(
                user_query=sanitized_message,
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

            # 8. LLM 응답 후처리 (Sources 섹션 제거)
            cleaned_response = self._clean_response(llm_response)

            # LLM 응답과 메타데이터를 담아 ChatResponse 객체로 최종 반환
            return ChatResponse(
                # LLM이 생성한 최종 답변 문자열 (후처리 완료)
                response=cleaned_response,
                # 검색된 출처 리스트를 포함, 아니면 빈 리스트로 반환
                # 벡터 검색으로 찾아낸 근거 문서들의 메타데이터 목록
                sources=sources if request.include_sources else [],
                # 요청에 세션 ID가 없으면 "default"로 대체
                session_id=request.session_id or "default",
                # 벡터 검색으로 실제로 프롬프트 컨텍스트에 사용된 청크 개수
                retrieved_chunks=len(retrieved_chunks)
            )

        except VectorStoreError as e:
            logger.error(f"벡터 검색 중 오류: {e}", exc_info=True)
            raise ChatMessageError(
                message="문서 검색 중 오류가 발생했습니다",
                details={
                    "message": request.message[:100],
                    "team_uuid": team_uuid,
                    "error": str(e)
                }
            )
        except LLMServiceError as e:
            logger.error(f"LLM 응답 생성 중 오류: {e}", exc_info=True)
            raise ChatMessageError(
                message="응답 생성 중 오류가 발생했습니다",
                details={
                    "message": request.message[:100],
                    "error": str(e)
                }
            )
        except ValueError as e:
            logger.error(f"입력 검증 오류: {e}", exc_info=True)
            raise ChatMessageError(
                message=str(e),
                details={"message": request.message[:100]}
            )
        except Exception as e:
            logger.error(f"챗봇 응답 생성 실패: {e}", exc_info=True)
            raise ChatServiceError(
                message="챗봇 응답 생성 중 예기치 않은 오류가 발생했습니다",
                details={
                    "message": request.message[:100],
                    "team_uuid": team_uuid,
                    "error_type": type(e).__name__,
                    "error": str(e)
                }
            )

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
                    "filename": metadata.get("original_filename") or metadata.get("filename"),  # 원본 파일명 우선
                    "chunk_index": metadata.get("chunk_index"),
                    "file_type": metadata.get("file_type")
                }
            ))

        return sources

    def _clean_response(self, response: str) -> str:
        """LLM 응답에서 Sources 섹션과 그 이후 모든 내용 제거"""
        # "Sources:" 또는 "출처:" 등이 나오면 그 이전까지만 반환
        # 줄바꿈, 공백, 볼드 마크다운 등 모든 형식 대응

        # Sources: 위치 찾기 (대소문자 무시)
        lower_response = response.lower()

        # 여러 패턴 체크
        markers = [
            'sources:',
            '**sources:**',
            'source:',
            '**source:**',
            '출처:',
            '**출처:**',
            '참고:',
            '**참고:**'
        ]

        # 가장 먼저 나오는 마커 위치 찾기
        earliest_pos = len(response)
        for marker in markers:
            pos = lower_response.find(marker)
            if pos != -1 and pos < earliest_pos:
                earliest_pos = pos

        # Sources 이전까지만 반환
        if earliest_pos < len(response):
            return response[:earliest_pos].strip()

        return response.strip()


# 싱글톤 인스턴스 및 Lock
_chat_service: Optional[ChatService] = None
_chat_service_lock = threading.Lock()


def get_chat_service() -> ChatService:
    """
    챗봇 서비스 싱글톤 인스턴스 반환 (스레드 안전)

    Double-checked locking 패턴 사용
    """
    global _chat_service

    # Fast path: 이미 생성된 경우
    if _chat_service is not None:
        return _chat_service

    # Slow path: Lock 획득 후 생성
    with _chat_service_lock:
        # Double-check
        if _chat_service is None:
            _chat_service = ChatService()
        return _chat_service
