"""
문서 처리 서비스
"""
import logging
import time
import uuid
import os
from pathlib import Path
from typing import Optional
from datetime import datetime
from fastapi import UploadFile

from app.config import settings
from app.core.embeddings import get_embedding_service
from app.core.vector_store import get_vector_store
from app.core.document_processor import DocumentProcessor
from app.core.chunking import get_text_chunker
from app.models.documents import DocumentUploadResponse
from app.core.exceptions import (
    DocumentProcessingError,
    DocumentParsingError,
    DocumentChunkingError,
    VectorStoreError,
    FileProcessingError
)

logger = logging.getLogger(__name__)


class DocumentService:
    """문서 처리 비즈니스 로직"""
    
    def __init__(self):
        self.embedding_service = get_embedding_service()
        self.document_processor = DocumentProcessor()
        self.text_chunker = get_text_chunker()

        # 업로드 디렉토리 생성
        Path(settings.upload_temp_dir).mkdir(parents=True, exist_ok=True)
    
    async def process_and_store_document(
        self,
        file: UploadFile,
        bot_id: Optional[str],
        user_uuid: str,
        db = None
    ) -> DocumentUploadResponse:
        """
        문서 업로드 및 처리 전체 파이프라인

        Args:
            file: 업로드 파일
            bot_id: 봇 ID (선택 사항, 지정되지 않으면 사용자 전역 지식으로 저장)
            user_uuid: 문서를 업로드한 사용자 UUID (유저 간 공유 기준)
            db: 데이터베이스 세션 (AsyncSession)
        """
        start_time = time.time()

        if not user_uuid:
            raise ValueError("user_uuid는 필수입니다")

        # 봇별 벡터 스토어 가져오기 (DB 세션 주입)
        vector_store = get_vector_store(bot_id=bot_id, user_uuid=user_uuid, db=db)
        
        # 1. 파일 저장
        document_id = str(uuid.uuid4())
        file_path = await self._save_uploaded_file(file, document_id)
        
        try:
            # 2. 파일 크기 확인
            file_size = os.path.getsize(file_path)
            
            # 3. 문서 파싱
            logger.info(f"문서 파싱 시작: {file.filename}")
            text = self.document_processor.process_file(file_path)
            
            if not text or not text.strip():
                raise ValueError("문서에서 텍스트를 추출할 수 없습니다")
            
            # 4. 텍스트 청킹
            logger.info(f"텍스트 청킹 시작")
            chunks = self.text_chunker.split_text(text)
            
            if not chunks:
                raise ValueError("텍스트 청킹에 실패했습니다")
            
            # 5. 임베딩 생성
            logger.info(f"임베딩 생성 시작: {len(chunks)}개 청크")
            # 비동기로 임베딩 생성 (블로킹 방지)
            embeddings = await self.embedding_service.embed_documents(chunks)
            
            # 6. 메타데이터 생성
            metadata = self.document_processor.extract_metadata(file_path, file_size)
            metadata["document_id"] = document_id
            metadata["original_filename"] = file.filename  # 원본 파일명 저장
            metadata["created_at"] = datetime.now().isoformat()
            metadata["chunk_count"] = len(chunks)
            metadata["bot_id"] = bot_id
            metadata["user_uuid"] = user_uuid
            
            # 7. 벡터 스토어에 저장
            logger.info(f"벡터 스토어에 저장 시작 (bot_id={bot_id})")
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
                metadatas=chunk_metadatas
            )
            
            # 8. 임시 파일 삭제
            self._cleanup_temp_file(file_path)
            
            processing_time = time.time() - start_time
            
            logger.info(f"문서 처리 완료: {document_id} ({processing_time:.2f}초)")
            
            return DocumentUploadResponse(
                document_id=document_id,
                filename=file.filename,
                file_size=file_size,
                chunk_count=len(chunks),
                processing_time=processing_time,
                status="success",
                message=f"문서가 성공적으로 처리되었습니다. {len(chunks)}개 청크 생성됨"
            )

        except DocumentParsingError as e:
            # 문서 파싱 오류 (이미 구체화된 예외)
            self._cleanup_temp_file(file_path)
            logger.error(f"문서 파싱 실패: {e}")
            raise
        except VectorStoreError as e:
            # 벡터 스토어 오류 (이미 구체화된 예외)
            self._cleanup_temp_file(file_path)
            logger.error(f"벡터 저장 실패: {e}")
            raise
        except ValueError as e:
            # 검증 오류
            self._cleanup_temp_file(file_path)
            logger.error(f"문서 처리 검증 실패: {e}")
            raise DocumentProcessingError(
                message=str(e),
                details={
                    "document_id": document_id,
                    "filename": file.filename
                }
            )
        except Exception as e:
            # 예기치 않은 오류
            self._cleanup_temp_file(file_path)
            logger.error(f"문서 처리 실패: {e}", exc_info=True)
            raise DocumentProcessingError(
                message="문서 처리 중 예기치 않은 오류가 발생했습니다",
                details={
                    "document_id": document_id,
                    "filename": file.filename,
                    "error_type": type(e).__name__,
                    "error": str(e)
                }
            )
    
    async def _save_uploaded_file(self, file: UploadFile, document_id: str) -> str:
        """업로드된 파일을 임시 디렉토리에 저장"""
        file_extension = Path(file.filename).suffix
        file_path = os.path.join(
            settings.upload_temp_dir,
            f"{document_id}{file_extension}"
        )
        
        with open(file_path, "wb") as buffer:
            content = await file.read()
            buffer.write(content)
        
        logger.info(f"파일 저장 완료: {file_path}")
        return file_path
    
    def _cleanup_temp_file(self, file_path: str):
        """임시 파일 삭제"""
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
                logger.info(f"임시 파일 삭제: {file_path}")
        except OSError as e:
            logger.warning(f"임시 파일 삭제 실패 (OS 오류): {file_path}, {e}")
        except Exception as e:
            logger.warning(f"임시 파일 삭제 실패 (예기치 않은 오류): {file_path}, {e}")
    
    async def get_document_info(
        self,
        document_id: str,
        user_uuid: str,
        bot_id: Optional[str] = None,
        db = None
    ) -> dict:
        """문서 정보 조회"""
        if not user_uuid:
            raise ValueError("user_uuid는 필수입니다")

        vector_store = get_vector_store(bot_id=bot_id, user_uuid=user_uuid, db=db)

        doc = await vector_store.get_document(f"{document_id}_chunk_0")

        if not doc:
            raise ValueError(f"문서를 찾을 수 없습니다: {document_id}")

        return {
            "document_id": document_id,
            "metadata": doc["metadata"]
        }
    
    async def delete_document(
        self,
        document_id: str,
        user_uuid: str,
        bot_id: Optional[str] = None,
        db = None
    ):
        """문서 삭제 (임베딩 + documents 테이블 레코드)"""
        if not user_uuid:
            raise ValueError("user_uuid는 필수입니다")

        logger.info(f"문서 삭제 요청: {document_id} (bot_id={bot_id}, user_uuid={user_uuid})")
        
        # 1. 벡터 임베딩 삭제
        vector_store = get_vector_store(bot_id=bot_id, user_uuid=user_uuid, db=db)
        await vector_store.delete_document(document_id)
        logger.info(f"벡터 임베딩 삭제 완료: {document_id}")
        
        # 2. documents 테이블에서 S3 URI 조회 및 레코드 삭제
        from app.models.document import Document
        from sqlalchemy import select, delete as sql_delete
        
        # S3 URI 조회
        result = await db.execute(
            select(Document).where(
                Document.document_id == document_id,
                Document.user_uuid == user_uuid
            )
        )
        document = result.scalar_one_or_none()
        
        if document:
            s3_uri = document.s3_uri
            
            # documents 테이블 레코드 삭제
            delete_stmt = sql_delete(Document).where(
                Document.document_id == document_id,
                Document.user_uuid == user_uuid
            )
            await db.execute(delete_stmt)
            await db.commit()
            logger.info(f"documents 테이블 레코드 삭제 완료: {document_id}")
            
            # 3. S3 파일 삭제
            if s3_uri:
                try:
                    from app.core.aws_clients import get_s3_client
                    s3_client = get_s3_client()
                    await s3_client.delete_file(s3_uri)
                    logger.info(f"S3 파일 삭제 완료: {s3_uri}")
                except Exception as e:
                    logger.warning(f"S3 파일 삭제 실패 (무시하고 계속): {e}")
        else:
            logger.warning(f"문서를 찾을 수 없음: {document_id} (user_uuid={user_uuid})")
    
    async def search_documents(
        self,
        query: str,
        db,
        top_k: int = None,
        bot_id: Optional[str] = None,
        user_uuid: Optional[str] = None
    ) -> dict:
        """문서 검색"""
        if not user_uuid:
            raise ValueError("user_uuid는 필수입니다")

        vector_store = get_vector_store(bot_id=bot_id, user_uuid=user_uuid, db=db)

        if top_k is None:
            top_k = settings.default_top_k

        if top_k > settings.max_top_k:
            top_k = settings.max_top_k

        query_embedding = await self.embedding_service.embed_query(query)

        filter_dict = {"user_uuid": user_uuid}

        results = await vector_store.search(
            query_embedding=query_embedding,
            top_k=top_k,
            filter_dict=filter_dict
        )

        return results


# 의존성 주입을 위한 함수
def get_document_service() -> DocumentService:
    """문서 서비스 인스턴스 반환"""
    return DocumentService()
