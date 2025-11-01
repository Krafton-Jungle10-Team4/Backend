"""
RAG 챗봇 프롬프트 템플릿 관리
"""
from typing import List, Dict, Optional


class PromptTemplate:
    """RAG 챗봇 프롬프트 템플릿"""

    SYSTEM_PROMPT = """당신은 업로드된 문서를 기반으로 질문에 답변하는 AI 어시스턴트입니다.

**답변 규칙:**
1. 제공된 문서 컨텍스트만을 사용하여 답변하세요
2. 컨텍스트에 정보가 없으면 "제공된 문서에서 해당 정보를 찾을 수 없습니다"라고 답변하세요
3. 추측하거나 외부 지식을 사용하지 마세요
4. 명확하고 간결하게 한국어로 답변하세요
5. 가능한 경우 어느 문서에서 정보를 찾았는지 언급하세요"""

    @staticmethod
    def format_context(chunks: List[Dict]) -> str:
        """문서 청크를 컨텍스트 문자열로 변환"""
        context_parts = []

        for i, chunk in enumerate(chunks, 1):
            content = chunk.get("document", "")
            metadata = chunk.get("metadata", {})
            filename = metadata.get("filename", "Unknown")

            context_parts.append(
                f"[문서 {i} - {filename}]\n{content}\n"
            )

        return "\n".join(context_parts)

    @staticmethod
    def build_messages(
        user_query: str,
        context: str,
        conversation_history: Optional[List[Dict]] = None
    ) -> List[Dict[str, str]]:
        """LLM API용 메시지 구성"""
        messages = [
            {"role": "system", "content": PromptTemplate.SYSTEM_PROMPT}
        ]

        # 대화 히스토리 추가
        if conversation_history:
            messages.extend(conversation_history)

        # 현재 질문 + 컨텍스트
        user_message = f"""**참고 문서:**
{context}

**질문:**
{user_query}"""

        messages.append({"role": "user", "content": user_message})

        return messages
