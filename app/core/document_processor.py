"""
문서 처리 모듈
"""
import logging
from pathlib import Path
from typing import List

from pypdf import PdfReader
from docx import Document

logger = logging.getLogger(__name__)


class DocumentProcessor:
    """문서 파싱 및 처리 클래스"""
    
    @staticmethod
    def process_file(file_path: str) -> str:
        """파일을 파싱하여 텍스트 추출"""
        path = Path(file_path)
        file_extension = path.suffix.lower()
        
        logger.info(f"문서 처리 시작: {file_path}")
        
        try:
            if file_extension == ".pdf":
                # PDF 처리
                reader = PdfReader(file_path)
                text = "\n\n".join([page.extract_text() for page in reader.pages])
                
            elif file_extension == ".txt":
                # TXT 처리
                with open(file_path, 'r', encoding='utf-8') as f:
                    text = f.read()
                    
            elif file_extension == ".docx":
                # DOCX 처리
                doc = Document(file_path)
                text = "\n\n".join([paragraph.text for paragraph in doc.paragraphs])
                
            else:
                raise ValueError(f"지원하지 않는 파일 형식: {file_extension}")
            
            logger.info(f"문서 처리 완료: {len(text)} characters")
            return text
            
        except Exception as e:
            logger.error(f"문서 처리 실패: {e}")
            raise ValueError(f"문서 처리 중 오류 발생: {str(e)}")
    
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