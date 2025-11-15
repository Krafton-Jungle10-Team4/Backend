from app.core.workflow.variable_pool import VariablePool
from app.core.workflow.nodes_v2.utils.template_renderer import TemplateRenderer


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
