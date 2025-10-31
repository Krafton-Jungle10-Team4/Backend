"""
텍스트 청킹 모듈
"""
import logging
from typing import List

# LangChain의 RecursiveCharacterTextSplitter 사용
#이 splitter는  문서를 재귀적으로 나눔
#먼저 큰 단위(예: 문단 단위 → \n\n)로 나누려고 시도
#그래도 너무 길면 문장 단위(. )로 나눔
#그래도 길면 단어 단위( )로 나눔
#마지막으로 그래도 길면 문자 단위로 자름 
from langchain.text_splitter import RecursiveCharacterTextSplitter
from app.config import settings

logger = logging.getLogger(__name__)


class TextChunker:
    """텍스트 청킹 클래스"""
    
    def __init__(
        self,
        chunk_size: int = None,
        chunk_overlap: int = None
    ):
        self.chunk_size = chunk_size or settings.chunk_size
        self.chunk_overlap = chunk_overlap or settings.chunk_overlap
        
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            length_function=len,
            separators=["\n\n", "\n", ". ", " ", ""]
        )
    
    def split_text(self, text: str) -> List[str]:
        """텍스트를 청크로 분할"""
        if not text or not text.strip():
            logger.warning("빈 텍스트가 입력되었습니다")
            return []
        
        chunks = self.splitter.split_text(text)
        
        logger.info(f"텍스트 분할 완료: {len(chunks)}개 청크 생성")
        return chunks
    
    def split_documents(self, texts: List[str]) -> List[str]:
        """여러 문서를 청크로 분할"""
        all_chunks = []
        
        for text in texts:
            chunks = self.split_text(text)
            all_chunks.extend(chunks)
        
        logger.info(f"총 {len(all_chunks)}개 청크 생성")
        return all_chunks


def get_text_chunker(chunk_size: int = None, chunk_overlap: int = None) -> TextChunker:
    """텍스트 청커 인스턴스 반환"""
    return TextChunker(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
