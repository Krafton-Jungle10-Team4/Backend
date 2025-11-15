from app.core.workflow.nodes_v2.utils.variable_template_parser import (
    VariableTemplateParser,
)


def test_variable_template_parser_extracts_ordered_unique_selectors():
    parser = VariableTemplateParser(
        "Hello {{start.query}}, summary: {{conversation.summary}} {{start.query}}"
    )
    selectors = parser.extract_variable_selectors()
    assert selectors == ["start.query", "conversation.summary"]
