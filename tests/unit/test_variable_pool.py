import pytest
from app.core.workflow.variable_pool import VariablePool
from app.core.workflow.nodes_v2.utils.template_renderer import (
    TemplateRenderError,
    SegmentGroup,
)


def test_resolve_conversation_alias_and_nested_outputs():
    pool = VariablePool()
    pool.set_conversation_variable("summary", "latest summary")
    pool.set_node_output(
        "tavily_1",
        "results",
        [
            {"title": "Doc A"},
            {"title": "Doc B", "meta": {"url": "https://example.com"}},
        ],
    )

    assert pool.resolve_value_selector("conversation.summary") == "latest summary"
    assert pool.resolve_value_selector("conv.summary") == "latest summary"
    assert pool.resolve_value_selector("tavily_1.results.0.title") == "Doc A"
    assert (
        pool.resolve_value_selector("tavily_1.results.1.meta.url")
        == "https://example.com"
    )


def test_conversation_variable_dirty_flags():
    pool = VariablePool(conversation_variables={"summary": "hello"})
    assert pool.get_dirty_conversation_variables() == {}

    pool.set_conversation_variable("summary", "updated")
    pool.set_conversation_variable("user_query", "news")

    dirty = pool.get_dirty_conversation_variables()
    assert dirty == {"summary": "updated", "user_query": "news"}

    pool.clear_conversation_variable_dirty()
    assert pool.get_dirty_conversation_variables() == {}


# ========== convert_template() 테스트 ==========


def test_convert_template_basic():
    """기본 템플릿 렌더링 테스트"""
    pool = VariablePool()
    pool.set_node_output("llm-1", "response", "안녕하세요")

    result, metadata = pool.convert_template("답변: {{ llm-1.response }}")

    assert isinstance(result, SegmentGroup)
    assert result.text == "답변: 안녕하세요"
    assert metadata["variable_count"] == 1
    assert "llm-1.response" in metadata["used_variables"]


def test_convert_template_multiple_variables():
    """여러 변수 치환 테스트"""
    pool = VariablePool()
    pool.set_node_output("start-1", "query", "파이썬이란?")
    pool.set_node_output("llm-1", "response", "파이썬은 프로그래밍 언어입니다.")
    pool.set_system_variable("bot_id", "test-bot")

    template = "질문: {{ start-1.query }}\n답변: {{ llm-1.response }}\n봇: {{ sys.bot_id }}"
    result, metadata = pool.convert_template(template)

    expected = "질문: 파이썬이란?\n답변: 파이썬은 프로그래밍 언어입니다.\n봇: test-bot"
    assert result.text == expected
    assert metadata["variable_count"] == 3


def test_convert_template_conversation_variable():
    """대화 변수 치환 테스트"""
    pool = VariablePool()
    pool.set_conversation_variable("summary", "이전 대화 요약")

    result, metadata = pool.convert_template("요약: {{ conv.summary }}")

    assert result.text == "요약: 이전 대화 요약"
    assert metadata["variable_count"] == 1


def test_convert_template_environment_variable():
    """환경 변수 치환 테스트"""
    pool = VariablePool(environment_variables={"api_key": "sk-12345"})

    result, metadata = pool.convert_template("API Key: {{ env.api_key }}")

    assert result.text == "API Key: sk-12345"
    assert metadata["variable_count"] == 1


def test_convert_template_system_variable():
    """시스템 변수 치환 테스트"""
    pool = VariablePool(system_variables={"user_message": "안녕하세요"})

    result, metadata = pool.convert_template("메시지: {{ sys.user_message }}")

    assert result.text == "메시지: 안녕하세요"
    assert metadata["variable_count"] == 1


def test_convert_template_dify_style():
    """Dify 스타일 변수 ({{#변수#}}) 테스트"""
    pool = VariablePool()
    pool.set_node_output("llm-1", "response", "테스트 응답")

    result, metadata = pool.convert_template("결과: {{#llm-1.response#}}")

    assert result.text == "결과: 테스트 응답"
    assert metadata["variable_count"] == 1


def test_convert_template_with_whitespace():
    """공백이 있는 템플릿 테스트"""
    pool = VariablePool()
    pool.set_node_output("llm-1", "response", "테스트")

    result, metadata = pool.convert_template("결과: {{  llm-1.response  }}")

    assert result.text == "결과: 테스트"


def test_convert_template_number_variable():
    """숫자 변수 치환 테스트"""
    pool = VariablePool()
    pool.set_node_output("llm-1", "tokens", 150)

    result, metadata = pool.convert_template("토큰 사용량: {{ llm-1.tokens }}")

    assert result.text == "토큰 사용량: 150"


def test_convert_template_array_variable():
    """배열 변수 치환 테스트"""
    pool = VariablePool()
    pool.set_node_output("search-1", "results", ["결과1", "결과2", "결과3"])

    result, metadata = pool.convert_template("검색 결과:\n{{ search-1.results }}")

    # 배열은 markdown 형식으로 렌더링됨
    assert "결과1" in result.markdown
    assert "결과2" in result.markdown


def test_convert_template_nested_access():
    """중첩 속성 접근 테스트"""
    pool = VariablePool()
    pool.set_node_output("api-1", "data", {"user": {"name": "홍길동", "age": 30}})

    result, metadata = pool.convert_template("이름: {{ api-1.data.user.name }}")

    assert result.text == "이름: 홍길동"


def test_convert_template_missing_variable():
    """존재하지 않는 변수 참조 시 에러 테스트"""
    pool = VariablePool()

    with pytest.raises(TemplateRenderError) as exc_info:
        pool.convert_template("{{ nonexistent.variable }}")

    assert "변수" in str(exc_info.value)
    assert "찾을 수 없습니다" in str(exc_info.value)


def test_convert_template_empty():
    """빈 템플릿 처리 테스트"""
    pool = VariablePool()

    with pytest.raises(TemplateRenderError) as exc_info:
        pool.convert_template("")

    assert "비어있습니다" in str(exc_info.value)


def test_convert_template_no_variables():
    """변수가 없는 일반 텍스트 템플릿 테스트"""
    pool = VariablePool()

    result, metadata = pool.convert_template("단순 텍스트입니다.")

    assert result.text == "단순 텍스트입니다."
    assert metadata["variable_count"] == 0


def test_convert_template_metadata():
    """메타데이터 검증 테스트"""
    pool = VariablePool()
    pool.set_node_output("llm-1", "response", "테스트 응답")
    pool.set_conversation_variable("summary", "요약")

    template = "{{ llm-1.response }} - {{ conv.summary }}"
    result, metadata = pool.convert_template(template)

    assert "used_variables" in metadata
    assert "template_length" in metadata
    assert "output_length" in metadata
    assert "variable_count" in metadata
    assert "segments" in metadata

    assert metadata["variable_count"] == 2
    assert metadata["template_length"] == len(template)
    assert metadata["output_length"] == len(result.text)
