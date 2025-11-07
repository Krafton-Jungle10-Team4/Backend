"""
문서 처리 모듈
"""
import logging
from pathlib import Path
from typing import List

from pypdf import PdfReader
from pypdf.errors import PdfReadError
from docx import Document
from docx.opc.exceptions import PackageNotFoundError

from app.core.exceptions import (
    DocumentParsingError,
    UnsupportedDocumentTypeError
)

logger = logging.getLogger(__name__)


class DocumentProcessor:
    """문서 파싱 및 처리 클래스"""
    
    @staticmethod
    def process_file(file_path: str) -> str:
        """
        파일을 파싱하여 텍스트 추출

        Args:
            file_path: 처리할 파일 경로

        Returns:
            추출된 텍스트

        Raises:
            UnsupportedDocumentTypeError: 지원하지 않는 파일 형식
            DocumentParsingError: 문서 파싱 중 오류 발생
        """
        path = Path(file_path)
        file_extension = path.suffix.lower()

        logger.info(f"문서 처리 시작: {file_path}")

        # 지원하지 않는 파일 형식 체크
        if file_extension not in [".pdf", ".txt", ".docx"]:
            raise UnsupportedDocumentTypeError(
                message=f"지원하지 않는 파일 형식입니다: {file_extension}",
                details={
                    "file_path": file_path,
                    "file_extension": file_extension,
                    "supported_types": [".pdf", ".txt", ".docx"]
                }
            )

        try:
            if file_extension == ".pdf":
                # PDF 처리
                try:
                    reader = PdfReader(file_path)
                    text = "\n\n".join([page.extract_text() for page in reader.pages])
                except PdfReadError as e:
                    raise DocumentParsingError(
                        message="PDF 파일 파싱에 실패했습니다",
                        details={
                            "file_path": file_path,
                            "error": str(e)
                        }
                    )

            elif file_extension == ".txt":
                # TXT 처리
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        text = f.read()
                except UnicodeDecodeError:
                    # UTF-8 실패 시 다른 인코딩 시도
                    try:
                        with open(file_path, 'r', encoding='cp949') as f:
                            text = f.read()
                    except Exception as e:
                        raise DocumentParsingError(
                            message="텍스트 파일 인코딩 처리에 실패했습니다",
                            details={
                                "file_path": file_path,
                                "error": str(e)
                            }
                        )

            elif file_extension == ".docx":
                # DOCX 처리
                try:
                    doc = Document(file_path)
                    text = "\n\n".join([paragraph.text for paragraph in doc.paragraphs])
                except PackageNotFoundError as e:
                    raise DocumentParsingError(
                        message="DOCX 파일을 찾을 수 없거나 손상되었습니다",
                        details={
                            "file_path": file_path,
                            "error": str(e)
                        }
                    )

            logger.info(f"문서 처리 완료: {len(text)} characters")
            return text

        except DocumentParsingError:
            # 이미 처리된 커스텀 예외는 그대로 전달
            raise
        except Exception as e:
            logger.error(f"문서 처리 실패: {e}", exc_info=True)
            raise DocumentParsingError(
                message="문서 처리 중 예기치 않은 오류가 발생했습니다",
                details={
                    "file_path": file_path,
                    "file_extension": file_extension,
                    "error_type": type(e).__name__,
                    "error": str(e)
                }
            )
    
    @staticmethod
    def extract_metadata(file_path: str, file_size: int) -> dict:
        """파일 메타데이터 추출"""
        path = Path(file_path)
        
        return {
            "filename": path.name,
            "file_type": path.suffix.lower().replace(".", ""),
            "file_size": file_size,
            "file_path": str(path)
        }