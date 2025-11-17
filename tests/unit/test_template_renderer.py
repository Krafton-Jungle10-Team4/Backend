import pytest
from app.core.workflow.variable_pool import VariablePool
from app.core.workflow.nodes_v2.utils.template_renderer import (
    TemplateRenderer,
    TemplateRenderError
)


def test_template_renderer_returns_segment_group_and_metadata():
    pool = VariablePool()
    pool.set_node_output("start_1", "user_message", "안녕하세요")

    segments, metadata = TemplateRenderer.render(
        "질문: {{start_1.user_message}}",
        pool,
    )

    assert segments.text == "질문: 안녕하세요"
    assert segments.markdown == "질문: 안녕하세요"
    assert metadata["variable_count"] == 1
    assert metadata["segments"][1]["type"] == "string"


def test_template_renderer_handles_array_values():
    pool = VariablePool()
    pool.set_node_output("tavily_1", "results", ["뉴스1", "뉴스2"])

    segments, _ = TemplateRenderer.render(
        "검색 결과:\n{{tavily_1.results}}",
        pool,
    )

    assert "- 뉴스1" in segments.markdown


def test_template_renderer_validates_allowed_selectors():
    """연결된 노드의 변수만 허용하는지 테스트"""
    pool = VariablePool()
    pool.set_node_output("llm_1", "response", "안녕하세요")
    pool.set_node_output("unconnected_node", "output", "이 값은 사용하면 안됨")

    # 허용된 셀렉터 목록
    allowed = ["llm_1.response"]

    # 연결된 변수는 성공
    segments, _ = TemplateRenderer.render(
        "응답: {{llm_1.response}}",
        pool,
        allowed_selectors=allowed
    )
    assert segments.text == "응답: 안녕하세요"

    # 연결되지 않은 변수는 실패
    with pytest.raises(TemplateRenderError) as exc_info:
        TemplateRenderer.render(
            "응답: {{unconnected_node.output}}",
            pool,
            allowed_selectors=allowed
        )
    assert "연결되지 않은 노드" in str(exc_info.value)


def test_template_renderer_allows_all_variables_when_no_restriction():
    """allowed_selectors가 None이면 모든 변수 허용"""
    pool = VariablePool()
    pool.set_node_output("node_1", "output", "값1")
    pool.set_node_output("node_2", "output", "값2")

    segments, _ = TemplateRenderer.render(
        "{{node_1.output}} {{node_2.output}}",
        pool,
        allowed_selectors=None  # 제한 없음
    )
    assert segments.text == "값1 값2"


def test_template_renderer_validates_multiple_variables():
    """여러 변수 참조 시 모두 검증되는지 테스트"""
    pool = VariablePool()
    pool.set_node_output("start", "query", "질문")
    pool.set_node_output("llm", "response", "답변")
    pool.set_node_output("unconnected", "data", "미사용")

    allowed = ["start.query", "llm.response"]

    # 허용된 변수들만 사용 - 성공
    segments, _ = TemplateRenderer.render(
        "{{start.query}} -> {{llm.response}}",
        pool,
        allowed_selectors=allowed
    )
    assert segments.text == "질문 -> 답변"

    # 허용되지 않은 변수 포함 - 실패
    with pytest.raises(TemplateRenderError) as exc_info:
        TemplateRenderer.render(
            "{{start.query}} {{unconnected.data}}",
            pool,
            allowed_selectors=allowed
        )
    assert "unconnected.data" in str(exc_info.value)
