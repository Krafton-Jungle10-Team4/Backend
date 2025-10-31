"""
문서 처리 모듈
"""
import logging
from pathlib import Path
from typing import List


# 자동 감지 - 파일 확장자를 보고 자동으로 적절한 파서 선택 -> 현재는 3개 확장자 지원 
from unstructured.partition.auto import partition
from unstructured.partition.pdf import partition_pdf
from unstructured.partition.text import partition_text
from unstructured.partition.docx import partition_docx

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
                elements = partition_pdf(filename=file_path)
            elif file_extension == ".txt":
                elements = partition_text(filename=file_path)
            elif file_extension == ".docx":
                elements = partition_docx(filename=file_path)
            else:
                # 자동 감지
                elements = partition(filename=file_path)
            
            # 텍스트 추출 및 결합
            text = "\n\n".join([str(element) for element in elements])
            
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
