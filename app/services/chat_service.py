"""
RAG 챗봇 서비스
"""
import asyncio
import copy
import logging
import threading
import json
from typing import List, Dict, Optional, AsyncGenerator, Callable, Awaitable, Any
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.embeddings import get_embedding_service
from app.core.vector_store import get_vector_store
from app.core.llm_client import get_llm_client
from app.core.prompt_templates import PromptTemplate
from app.models.chat import (
    ChatRequest,
    ChatResponse,
    Source,
    ContentEvent,
    SourcesEvent,
    ErrorEvent,
    ErrorCode,
    WorkflowNodeEvent
)
from app.config import settings
from app.utils.validators import sanitize_chat_query
from app.utils.text_utils import strip_markdown
from app.core.exceptions import (
    ChatServiceError,
    ChatMessageError,
    LLMServiceError,
    VectorStoreError,
    LLMRateLimitError
)

logger = logging.getLogger(__name__)


class WorkflowStreamHandler:
    """워크플로우 스트리밍 이벤트 헬퍼"""

    def __init__(
        self,
        emit_fn: Callable[[Dict[str, Any]], Awaitable[None]],
        include_sources: bool,
        text_normalizer: Callable[[str], str]
    ):
        self._emit_fn = emit_fn
        self.include_sources = include_sources
        self._normalize = text_normalizer

    async def emit_node_event(
        self,
        node_id: str,
        node_type: str,
        status: str,
        message: Optional[str] = None,
        output_preview: Optional[str] = None
    ) -> None:
        event = WorkflowNodeEvent(
            node_id=node_id,
            node_type=node_type,
            status=status,
            message=message,
            output_preview=output_preview
        )
        await self._emit_fn(event.model_dump())

    async def emit_content_chunk(self, chunk: str) -> Optional[str]:
        """LLM 토큰 청크를 평문화 후 이벤트 전송"""
        normalized = self._normalize(chunk)
        if not normalized:
            return None

        await self._emit_fn(ContentEvent(data=normalized).model_dump())
        return normalized

    async def emit_sources(self, sources: List[Source]) -> None:
        if not self.include_sources or not sources:
            return
        await self._emit_fn(SourcesEvent(data=sources).model_dump())

    def _convert_documents_to_sources(self, documents: List[Dict[str, Any]]) -> List[Source]:
        sources: List[Source] = []
        for idx, doc in enumerate(documents):
            metadata = doc.get("metadata") or {}
            sources.append(Source(
                document_id=metadata.get("document_id") or metadata.get("doc_id") or "unknown",
                chunk_id=metadata.get("chunk_id") or f"chunk_{idx}",
                content=(doc.get("content") or "")[:200],
                similarity_score=float(doc.get("similarity", 0.0)),
                metadata={
                    "filename": None,
                    "chunk_index": metadata.get("chunk_index"),
                    "file_type": metadata.get("file_type")
                }
            ))
        return sources


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
        user_uuid: str,
        db: Optional[AsyncSession] = None
    ) -> ChatResponse:
        """챗봇 응답 생성 (RAG 파이프라인 또는 Workflow 실행)"""

        logger.info(f"챗봇 요청: '{request.message[:50]}...'")

        # bot_id 검증
        if not request.bot_id:
            raise ValueError("bot_id는 필수 파라미터입니다. 봇별 문서 관리를 위해 bot_id가 필요합니다.")

        # db 세션 검증
        if not db:
            raise ValueError("데이터베이스 세션이 필요합니다. 봇 정보 및 문서 조회를 위해 db 세션이 필요합니다.")

        # Workflow 실행
        return await self._execute_workflow(request, user_uuid, db)

    async def _execute_workflow(
        self,
        request: ChatRequest,
        user_uuid: str,
        db: AsyncSession
    ) -> ChatResponse:
        """Workflow 기반 응답 생성"""
        from app.services.bot_service import get_bot_service

        logger.info(f"[ChatService] Workflow 실행: bot_id={request.bot_id}")

        # Bot 조회
        bot_service = get_bot_service()
        bot = await bot_service.get_bot_by_id(request.bot_id, None, db, include_workflow=True)

        if not bot:
            raise ValueError(f"Bot not found: {request.bot_id}")

        # Workflow가 없으면 기본 RAG 파이프라인으로 fallback
        if not bot.workflow:
            logger.info(f"[ChatService] Bot {request.bot_id}에 Workflow가 없어 기본 RAG 파이프라인 실행")
            return await self._execute_rag_pipeline(request, bot.bot_id, db)

        # 서비스 초기화 (V1/V2 공통)
        from app.services.vector_service import VectorService
        from app.services.llm_service import LLMService

        vector_service = VectorService()
        llm_service = LLMService()
        workflow_data = self._prepare_workflow_data(bot, request)

        # V1/V2 분기 처리
        if getattr(bot, 'use_workflow_v2', False):
            # V2 Workflow Executor 실행
            logger.info(f"[ChatService] V2 Workflow 실행: bot_id={request.bot_id}")
            from app.core.workflow.executor_v2 import WorkflowExecutorV2

            executor = WorkflowExecutorV2()
            response_text = await executor.execute(
                workflow_data=workflow_data,
                session_id=request.session_id or "default",
                user_message=request.message,
                bot_id=bot.bot_id,
                db=db,
                vector_service=vector_service,
                llm_service=llm_service,
                stream_handler=None,
                text_normalizer=strip_markdown
            )
        else:
            # V1 Workflow Executor 실행 (기존 로직)
            logger.info(f"[ChatService] V1 Workflow 실행: bot_id={request.bot_id}")
            from app.core.workflow.executor import WorkflowExecutor

            executor = WorkflowExecutor()
            response_text = await executor.execute(
                workflow_data=workflow_data,
                session_id=request.session_id or "default",
                user_message=request.message,
                bot_id=bot.bot_id,
                db=db,
                vector_service=vector_service,
                llm_service=llm_service,
                stream_handler=None,
                text_normalizer=strip_markdown
            )

        # ChatResponse 형식으로 변환
        return ChatResponse(
            response=response_text,
            sources=[],
            session_id=request.session_id or "default",
            retrieved_chunks=0,
            metadata={}
        )

    async def generate_response_stream(
        self,
        request: ChatRequest,
        user_uuid: str,
        db: Optional[AsyncSession] = None
    ) -> AsyncGenerator[str, None]:
        """워크플로우/일반 RAG 공통 스트리밍 응답 생성"""
        logger.info(f"[ChatService] 스트리밍 요청: '{request.message[:50]}...' (bot_id={request.bot_id})")

        if not request.bot_id:
            raise ValueError("bot_id는 필수 파라미터입니다")

        if not db:
            raise ValueError("데이터베이스 세션이 필요합니다")

        try:
            from app.services.bot_service import get_bot_service

            bot_service = get_bot_service()
            bot = await bot_service.get_bot_by_id(request.bot_id, None, db, include_workflow=True)

            if not bot:
                error_event = ErrorEvent(
                    code=ErrorCode.INVALID_REQUEST,
                    message=f"Bot not found: {request.bot_id}"
                )
                yield json.dumps(error_event.model_dump(), ensure_ascii=False)
                return

            if bot.workflow:
                async for payload in self._stream_workflow_response(bot, request, db):
                    yield payload
                return

            # --- 기본 RAG 스트리밍 파이프라인 ---
            vector_store = get_vector_store(bot_id=request.bot_id, db=db)
            sanitized_message = sanitize_chat_query(request.message)

            query_embedding = await self.embedding_service.embed_query(sanitized_message)
            search_results = await vector_store.search(
                query_embedding=query_embedding,
                top_k=request.top_k,
                filter_dict={"document_id": request.document_ids} if request.document_ids else None
            )

            retrieved_chunks = self._extract_chunks(search_results)
            if not retrieved_chunks:
                error_event = ErrorEvent(
                    code=ErrorCode.INVALID_REQUEST,
                    message="관련 문서를 찾을 수 없습니다"
                )
                yield json.dumps(error_event.model_dump(), ensure_ascii=False)
                return

            context = self.prompt_template.format_context(retrieved_chunks)
            messages = self.prompt_template.build_messages(
                user_query=sanitized_message,
                context=context
            )

            temperature = request.temperature if request.temperature is not None else settings.chat_temperature
            max_tokens = request.max_tokens if request.max_tokens is not None else settings.chat_max_tokens

            resolved_model = self._resolve_model_name(request.model)

            async for chunk in self.llm_client.generate_stream(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                model=resolved_model
            ):
                normalized_chunk = strip_markdown(chunk)
                if not normalized_chunk:
                    continue
                content_event = ContentEvent(data=normalized_chunk)
                yield json.dumps(content_event.model_dump(), ensure_ascii=False)

            if request.include_sources:
                sources = self._build_sources(retrieved_chunks, search_results)
                if sources:
                    sources_event = SourcesEvent(data=sources)
                    yield json.dumps(sources_event.model_dump(), ensure_ascii=False)

        except ValueError as e:
            logger.error(f"[ChatService] 입력 검증 실패: {e}")
            error_event = ErrorEvent(
                code=ErrorCode.INVALID_REQUEST,
                message=str(e)
            )
            yield json.dumps(error_event.model_dump(), ensure_ascii=False)
            return

        except VectorStoreError as e:
            logger.error(f"[ChatService] 벡터 검색 오류: {e}", exc_info=True)
            error_event = ErrorEvent(
                code=ErrorCode.STREAM_ERROR,
                message="문서 검색 중 오류가 발생했습니다"
            )
            yield json.dumps(error_event.model_dump(), ensure_ascii=False)
            return

        except LLMRateLimitError as e:
            logger.error(f"[ChatService] LLM API 사용량 제한: {e}")
            error_event = ErrorEvent(
                code=ErrorCode.RATE_LIMIT_EXCEEDED,
                message="API 사용량 제한을 초과했습니다. 잠시 후 다시 시도해주세요."
            )
            yield json.dumps(error_event.model_dump(), ensure_ascii=False)
            return

        except Exception as e:
            logger.error(f"[ChatService] 스트리밍 중 예기치 않은 오류: {e}", exc_info=True)
            error_event = ErrorEvent(
                code=ErrorCode.UNKNOWN_ERROR,
                message="응답 생성 중 오류가 발생했습니다"
            )
            yield json.dumps(error_event.model_dump(), ensure_ascii=False)
            return

    async def _stream_workflow_response(
        self,
        bot,
        request: ChatRequest,
        db: AsyncSession
    ) -> AsyncGenerator[str, None]:
        """워크플로우 실행 결과를 실시간으로 전송"""
        from app.services.vector_service import VectorService
        from app.services.llm_service import LLMService

        workflow_data = self._prepare_workflow_data(bot, request)
        vector_service = VectorService()
        llm_service = LLMService()

        # V1/V2 분기 처리
        if getattr(bot, 'use_workflow_v2', False):
            logger.info(f"[ChatService] V2 Workflow 스트리밍: bot_id={bot.bot_id}")
            from app.core.workflow.executor_v2 import WorkflowExecutorV2
            executor = WorkflowExecutorV2()
        else:
            logger.info(f"[ChatService] V1 Workflow 스트리밍: bot_id={bot.bot_id}")
            from app.core.workflow.executor import WorkflowExecutor
            executor = WorkflowExecutor()

        queue: asyncio.Queue[Optional[str]] = asyncio.Queue()

        async def emit(event_payload: Dict[str, Any]) -> None:
            await queue.put(json.dumps(event_payload, ensure_ascii=False))

        stream_handler = WorkflowStreamHandler(
            emit_fn=emit,
            include_sources=request.include_sources,
            text_normalizer=strip_markdown
        )

        async def run_workflow():
            try:
                await executor.execute(
                    workflow_data=workflow_data,
                    session_id=request.session_id or "default",
                    user_message=request.message,
                    bot_id=bot.bot_id,
                    db=db,
                    vector_service=vector_service,
                    llm_service=llm_service,
                    stream_handler=stream_handler,
                    text_normalizer=strip_markdown
                )
            except Exception as exc:
                logger.error(f"[ChatService] 워크플로우 스트리밍 실패: {exc}")
                friendly_message = str(exc) or "워크플로우 실행 중 오류가 발생했습니다"
                error_event = ErrorEvent(
                    code=ErrorCode.STREAM_ERROR,
                    message=friendly_message
                )
                await emit(error_event.model_dump())
            finally:
                await queue.put(None)

        task = asyncio.create_task(run_workflow())

        try:
            while True:
                payload = await queue.get()
                if payload is None:
                    break
                yield payload
        finally:
            await task

    async def _execute_rag_pipeline(
        self,
        request: ChatRequest,
        bot_id: str,
        db: AsyncSession
    ) -> ChatResponse:
        """기본 RAG 파이프라인 실행"""
        # 봇별 벡터 스토어 가져오기
        vector_store = get_vector_store(bot_id=bot_id, db=db)

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
            logger.debug(f"벡터 검색 중 (bot_id={bot_id}, top_k={request.top_k})...")
            search_results = await vector_store.search(
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
                    "bot_id": bot_id,
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
                    "bot_id": bot_id,
                    "error_type": type(e).__name__,
                    "error": str(e)
                }
            )

    def _prepare_workflow_data(self, bot, request: ChatRequest) -> Dict[str, Any]:
        """워크플로우 실행 전에 런타임 구성을 정리"""
        workflow_data = copy.deepcopy(bot.workflow) if bot.workflow else {}

        override_model = self._resolve_model_name(request.model)

        if override_model and workflow_data.get("nodes"):
            logger.info(f"[ChatService] 런타임 모델 오버라이드: {override_model}")
            for node in workflow_data["nodes"]:
                if node.get("type") == "llm" and node.get("data"):
                    original_model = node["data"].get("model")
                    node["data"]["model"] = override_model
                    logger.info(
                        f"[ChatService] LLM 노드 모델 변경: {original_model} → {override_model}"
                    )
        elif workflow_data.get("nodes"):
            for node in workflow_data["nodes"]:
                if node.get("type") == "llm" and node.get("data"):
                    node["data"]["model"] = self._resolve_model_name(node["data"].get("model"))

        return workflow_data

    def _resolve_model_name(self, model_name: Optional[str]) -> Optional[str]:
        if not model_name:
            return None

        normalized = model_name.strip().lower()
        alias_map = {
            "anthropic/claude": settings.anthropic_model,
            "anthropic:claude": settings.anthropic_model,
            "claude": settings.anthropic_model,
            "claude-3": settings.anthropic_model,
            "openai/gpt-4o": settings.openai_model,
            "gpt-4": settings.openai_model,
        }

        resolved = alias_map.get(normalized, model_name)
        if resolved != model_name:
            logger.info(f"[ChatService] 모델 별칭 변환: {model_name} -> {resolved}")
        return resolved

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
                    "filename": None,
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
            cleaned = response[:earliest_pos].strip()
        else:
            cleaned = response.strip()

        return strip_markdown(cleaned)


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
