"""
Prompt Template 단위 테스트
"""
import pytest
from app.core.prompt_templates import PromptTemplate


class TestPromptTemplate:
    """PromptTemplate 클래스 테스트"""

    def test_system_prompt_exists(self):
        """시스템 프롬프트가 정의되어 있는지 확인"""
        assert PromptTemplate.SYSTEM_PROMPT is not None
        assert len(PromptTemplate.SYSTEM_PROMPT) > 0
        assert "문서" in PromptTemplate.SYSTEM_PROMPT
        assert "답변" in PromptTemplate.SYSTEM_PROMPT

    def test_format_context_single_chunk(self):
        """단일 청크 컨텍스트 포맷팅"""
        chunks = [
            {
                "document": "FastAPI는 빠른 웹 프레임워크입니다.",
                "metadata": {
                    "filename": "test.pdf",
                    "chunk_index": 0
                }
            }
        ]

        context = PromptTemplate.format_context(chunks)

        assert "[문서 1 - test.pdf]" in context
        assert "FastAPI는 빠른 웹 프레임워크입니다." in context

    def test_format_context_multiple_chunks(self, sample_chunks):
        """여러 청크 컨텍스트 포맷팅"""
        context = PromptTemplate.format_context(sample_chunks)

        assert "[문서 1 - fastapi_guide.pdf]" in context
        assert "[문서 2 - fastapi_guide.pdf]" in context
        assert "FastAPI는 빠르고 현대적인" in context
        assert "비동기 프로그래밍" in context

    def test_format_context_empty_chunks(self):
        """빈 청크 리스트 처리"""
        chunks = []
        context = PromptTemplate.format_context(chunks)

        assert context == ""

    def test_format_context_missing_metadata(self):
        """메타데이터 누락 시 기본값 사용"""
        chunks = [
            {
                "document": "테스트 내용",
                "metadata": {}
            }
        ]

        context = PromptTemplate.format_context(chunks)

        assert "[문서 1 - Unknown]" in context
        assert "테스트 내용" in context

    def test_build_messages_basic(self):
        """기본 메시지 구성"""
        user_query = "FastAPI의 장점은 무엇인가요?"
        context = "[문서 1 - test.pdf]\nFastAPI는 빠릅니다."

        messages = PromptTemplate.build_messages(
            user_query=user_query,
            context=context
        )

        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == PromptTemplate.SYSTEM_PROMPT
        assert messages[1]["role"] == "user"
        assert "참고 문서" in messages[1]["content"]
        assert context in messages[1]["content"]
        assert user_query in messages[1]["content"]

    def test_build_messages_with_history(self):
        """대화 히스토리 포함 메시지 구성"""
        user_query = "더 자세히 설명해주세요"
        context = "[문서 1 - test.pdf]\n추가 정보"
        conversation_history = [
            {"role": "user", "content": "FastAPI가 뭔가요?"},
            {"role": "assistant", "content": "FastAPI는 웹 프레임워크입니다."}
        ]

        messages = PromptTemplate.build_messages(
            user_query=user_query,
            context=context,
            conversation_history=conversation_history
        )

        assert len(messages) == 4  # system + 2 history + user
        assert messages[0]["role"] == "system"
        assert messages[1] == conversation_history[0]
        assert messages[2] == conversation_history[1]
        assert messages[3]["role"] == "user"

    def test_build_messages_without_history(self):
        """대화 히스토리 없이 메시지 구성"""
        user_query = "테스트 질문"
        context = "테스트 컨텍스트"

        messages = PromptTemplate.build_messages(
            user_query=user_query,
            context=context,
            conversation_history=None
        )

        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"

    def test_build_messages_structure(self):
        """메시지 구조 검증"""
        user_query = "질문"
        context = "컨텍스트"

        messages = PromptTemplate.build_messages(
            user_query=user_query,
            context=context
        )

        for message in messages:
            assert "role" in message
            assert "content" in message
            assert message["role"] in ["system", "user", "assistant"]
            assert isinstance(message["content"], str)
