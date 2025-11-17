"""
임베딩 워커 서비스

SQS 큐에서 문서 처리 메시지를 수신하고 백그라운드에서 임베딩 처리를 수행합니다.
"""
import asyncio
import json
import os
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from app.config import settings
from app.core.logging_config import get_logger
from app.core.aws_clients import get_s3_client, get_sqs_client
from app.models.document import Document, DocumentStatus
from app.core.embeddings import get_embedding_service, CircuitBreakerOpenError
from app.core.vector_store import get_vector_store
from app.core.document_processor import DocumentProcessor
from app.core.chunking import get_text_chunker
from app.core.exceptions import (
    DocumentProcessingError,
    DocumentParsingError,
    VectorStoreError
)

logger = get_logger(__name__)


class EmbeddingWorker:
    """
    임베딩 워커 서비스

    SQS 큐에서 문서 처리 작업을 폴링하고 S3에서 파일을 다운로드하여
    파싱 → 청킹 → 임베딩 → pgvector 저장 파이프라인을 실행합니다.
    """

    def __init__(self):
        self.s3_client = get_s3_client()
        self.sqs_client = get_sqs_client()
        self.embedding_service = get_embedding_service()
        self.document_processor = DocumentProcessor()
        self.text_chunker = get_text_chunker()

        # 임시 디렉토리 생성
        Path(settings.upload_temp_dir).mkdir(parents=True, exist_ok=True)

        # 비동기 DB 세션 생성
        self.engine = create_async_engine(
            settings.get_database_url(),
            echo=False,
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=10
        )
        self.async_session = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False
        )

        logger.info("임베딩 워커 초기화 완료")

    async def start(self):
        """워커 시작 (무한 루프)"""
        logger.info("🚀 임베딩 워커 시작")
        logger.info(f"SQS 큐: {settings.sqs_queue_url}")
        logger.info(f"S3 버킷: {settings.s3_bucket_name}")
        logger.info(f"Long Polling: 5초")

        while True:
            try:
                # SQS에서 메시지 수신 (Long Polling)
                messages = await self.sqs_client.receive_messages(
                    max_messages=1,
                    wait_time_seconds=5  # Long Polling (빠른 응답성 확보)
                )

                if not messages:
                    logger.debug("수신된 메시지 없음")
                    continue

                # 메시지 처리
                for message in messages:
                    await self._process_message(message)

            except KeyboardInterrupt:
                logger.info("워커 종료 신호 수신")
                break
            except Exception as e:
                logger.error(f"워커 메인 루프 에러: {e}", exc_info=True)
                await asyncio.sleep(5)  # 에러 발생 시 5초 대기

    async def _process_message(self, message: Dict[str, Any]):
        """
        SQS 메시지 처리

        Args:
            message: SQS 메시지 객체
        """
        receipt_handle = message.get("ReceiptHandle")
        message_id = message.get("MessageId")

        try:
            # 메시지 본문 파싱
            body = json.loads(message.get("Body", "{}"))
            document_id = body.get("document_id")
            bot_id = body.get("bot_id")
            user_uuid = body.get("user_uuid")
            s3_uri = body.get("s3_uri")
            original_filename = body.get("original_filename")
            file_extension = body.get("file_extension")
            retry_count = body.get("retry_count", 0)

            logger.info(f"📨 메시지 수신: document_id={document_id}, file={original_filename}, retry={retry_count}")

            # 필수 필드 검증
            if not all([document_id, bot_id, s3_uri, original_filename]):
                logger.error(f"메시지 필드 누락: {body}")
                await self.sqs_client.delete_message(receipt_handle)
                return

            # 문서 처리
            start_time = time.time()
            await self._process_document(
                document_id=document_id,
                bot_id=bot_id,
                user_uuid=user_uuid,
                s3_uri=s3_uri,
                original_filename=original_filename,
                file_extension=file_extension
            )

            processing_time = int(time.time() - start_time)
            logger.info(f"✅ 문서 처리 완료: document_id={document_id} ({processing_time}초)")

            # 메시지 삭제 (처리 완료)
            await self.sqs_client.delete_message(receipt_handle)

        except Exception as e:
            logger.error(f"❌ 메시지 처리 실패 (message_id={message_id}): {e}", exc_info=True)
            # 메시지를 삭제하지 않으면 자동으로 DLQ로 이동 (maxReceiveCount 초과 시)

    async def _process_document(
        self,
        document_id: str,
        bot_id: str,
        user_uuid: str,
        s3_uri: str,
        original_filename: str,
        file_extension: str
    ):
        """
        문서 처리 파이프라인

        1. 상태를 PROCESSING으로 변경
        2. S3에서 파일 다운로드
        3. 파싱 → 청킹 → 임베딩 → pgvector 저장
        4. 상태를 DONE으로 변경
        """
        async with self.async_session() as db:
            try:
                # 1. 상태를 PROCESSING으로 변경
                await self._update_document_status(
                    db=db,
                    document_id=document_id,
                    status=DocumentStatus.PROCESSING,
                    processing_started_at=datetime.now(timezone.utc)
                )

                # 2. S3에서 파일 다운로드
                logger.info(f"S3 다운로드 시작: {s3_uri}")
                s3_key = s3_uri.replace(f"s3://{settings.s3_bucket_name}/", "")
                file_content = await self.s3_client.download_file(s3_key)

                # 3. 임시 파일로 저장
                temp_file_path = os.path.join(
                    settings.upload_temp_dir,
                    f"{document_id}{Path(original_filename).suffix}"
                )
                with open(temp_file_path, "wb") as f:
                    f.write(file_content)

                try:
                    # 4. 문서 파싱
                    logger.info(f"문서 파싱 시작: {original_filename}")
                    text = self.document_processor.process_file(temp_file_path)

                    if not text or not text.strip():
                        raise DocumentParsingError("문서에서 텍스트를 추출할 수 없습니다")

                    # 5. 텍스트 청킹
                    logger.info(f"텍스트 청킹 시작")
                    chunks = self.text_chunker.split_text(text)

                    if not chunks:
                        raise DocumentProcessingError("텍스트 청킹에 실패했습니다")

                    # 6. 임베딩 생성
                    logger.info(f"임베딩 생성 시작: {len(chunks)}개 청크")
                    try:
                        embeddings = await self.embedding_service.embed_documents(chunks)
                    except CircuitBreakerOpenError as e:
                        # Circuit Breaker가 열린 경우: 메시지를 다시 큐로 반환 (재시도)
                        logger.warning(f"Circuit Breaker 열림: {e}")
                        await self._update_document_status(
                            db=db,
                            document_id=document_id,
                            status=DocumentStatus.PENDING,
                            error_message=f"Circuit Breaker 작동 - 재시도 대기 중"
                        )
                        # 메시지를 삭제하지 않으면 자동으로 재시도됨
                        raise

                    # 7. 메타데이터 생성
                    file_size = os.path.getsize(temp_file_path)
                    metadata = self.document_processor.extract_metadata(temp_file_path, file_size)
                    metadata.update({
                        "document_id": document_id,
                        "bot_id": bot_id,
                        "user_uuid": user_uuid,
                        "original_filename": original_filename,
                        "created_at": datetime.now().isoformat(),
                        "chunk_count": len(chunks)
                    })

                    # 8. 벡터 스토어에 저장
                    logger.info(f"벡터 스토어에 저장 시작 (bot_id={bot_id})")
                    vector_store = get_vector_store(bot_id=bot_id, user_uuid=user_uuid, db=db)

                    chunk_ids = [f"{document_id}_chunk_{i}" for i in range(len(chunks))]
                    chunk_metadatas = [
                        {
                            **metadata,
                            "chunk_index": i,
                            "chunk_id": chunk_ids[i]
                        }
                        for i in range(len(chunks))
                    ]

                    await vector_store.add_documents(
                        ids=chunk_ids,
                        embeddings=embeddings,
                        documents=chunks,
                        metadatas=chunk_metadatas,
                        source_document_id=document_id  # ← documents 테이블 연결
                    )

                    # 9. 상태를 DONE으로 변경
                    await self._update_document_status(
                        db=db,
                        document_id=document_id,
                        status=DocumentStatus.DONE,
                        chunk_count=len(chunks),
                        completed_at=datetime.now(timezone.utc)
                    )

                    logger.info(f"✅ 문서 처리 성공: {document_id} ({len(chunks)} 청크)")

                finally:
                    # 10. 임시 파일 삭제
                    self._cleanup_temp_file(temp_file_path)

            except DocumentParsingError as e:
                logger.error(f"문서 파싱 실패: {e}")
                await self._update_document_status(
                    db=db,
                    document_id=document_id,
                    status=DocumentStatus.FAILED,
                    error_message=f"문서 파싱 실패: {str(e)}",
                    completed_at=datetime.now(timezone.utc)
                )
                raise

            except VectorStoreError as e:
                logger.error(f"벡터 저장 실패: {e}")
                await self._update_document_status(
                    db=db,
                    document_id=document_id,
                    status=DocumentStatus.FAILED,
                    error_message=f"벡터 저장 실패: {str(e)}",
                    completed_at=datetime.now(timezone.utc)
                )
                raise

            except Exception as e:
                logger.error(f"문서 처리 실패: {e}", exc_info=True)
                error_trace = traceback.format_exc()
                await self._update_document_status(
                    db=db,
                    document_id=document_id,
                    status=DocumentStatus.FAILED,
                    error_message=f"{type(e).__name__}: {str(e)}",
                    completed_at=datetime.now(timezone.utc)
                )
                raise

    async def _update_document_status(
        self,
        db: AsyncSession,
        document_id: str,
        status: DocumentStatus,
        error_message: Optional[str] = None,
        chunk_count: Optional[int] = None,
        processing_started_at: Optional[datetime] = None,
        completed_at: Optional[datetime] = None
    ):
        """
        documents 테이블 상태 업데이트

        Args:
            db: 데이터베이스 세션
            document_id: 문서 ID
            status: 새 상태
            error_message: 에러 메시지 (실패 시)
            chunk_count: 청크 개수 (완료 시)
            processing_started_at: 처리 시작 시간
            completed_at: 완료 시간
        """
        try:
            # Document 조회
            result = await db.execute(
                select(Document).where(Document.document_id == document_id)
            )
            document = result.scalar_one_or_none()

            if not document:
                logger.error(f"문서를 찾을 수 없음: {document_id}")
                return

            # 상태 업데이트
            document.status = status
            document.updated_at = datetime.now(timezone.utc)

            if error_message:
                document.error_message = error_message

            if chunk_count is not None:
                document.chunk_count = chunk_count

            if processing_started_at:
                document.processing_started_at = processing_started_at

            if completed_at:
                document.completed_at = completed_at
                # 처리 시간 계산 (초)
                if document.processing_started_at:
                    # timezone-naive datetime을 timezone-aware로 변환
                    start_time = document.processing_started_at
                    if start_time.tzinfo is None:
                        start_time = start_time.replace(tzinfo=timezone.utc)
                    processing_time = (completed_at - start_time).total_seconds()
                    document.processing_time = int(processing_time)

                # 성공적으로 완료된 경우 embedded_at 설정
                if status == DocumentStatus.DONE:
                    document.embedded_at = completed_at

            await db.commit()
            logger.info(f"상태 업데이트: document_id={document_id}, status={status.value}")

        except Exception as e:
            logger.error(f"상태 업데이트 실패: {e}", exc_info=True)
            await db.rollback()
            raise

    def _cleanup_temp_file(self, file_path: str):
        """임시 파일 삭제"""
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
                logger.debug(f"임시 파일 삭제: {file_path}")
        except Exception as e:
            logger.warning(f"임시 파일 삭제 실패: {file_path}, {e}")

    async def shutdown(self):
        """워커 종료 시 리소스 정리"""
        logger.info("워커 종료 중...")
        await self.engine.dispose()
        logger.info("워커 종료 완료")


# 싱글톤 인스턴스
_worker_instance: Optional[EmbeddingWorker] = None


def get_embedding_worker() -> EmbeddingWorker:
    """임베딩 워커 싱글톤"""
    global _worker_instance
    if _worker_instance is None:
        _worker_instance = EmbeddingWorker()
    return _worker_instance
