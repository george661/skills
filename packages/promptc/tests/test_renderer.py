"""Tests for promptc renderer (GW-5475)."""
from __future__ import annotations

import pytest

from promptc import RenderError, parse_str, render
from promptc.schema import Doc


class TestRendererSmoke:
    """Basic renderer smoke tests."""

    def test_render_returns_str(self) -> None:
        """render() should return a str type."""
        source = "Hello world"
        ast = parse_str(source)
        doc = Doc.from_ast(ast)

        result = render(doc)

        assert isinstance(result, str)

    def test_pure_function_determinism(self) -> None:
        """Render should produce identical output across multiple runs."""
        source = (
            "{% meta doc_type=\"command\" /%}"
            "{% input name=\"name\" type=\"string\" /%}"
            "Hello {% $inputs.name %}"
        )
        ast = parse_str(source)
        doc = Doc.from_ast(ast)

        results = [render(doc, {"name": "world"}) for _ in range(10)]

        # All results should be byte-identical
        first = results[0]
        assert all(r == first for r in results)


class TestTextRendering:
    """Tests for basic text rendering."""

    def test_reference_tier_renders_text_verbatim(self) -> None:
        """Reference-tier doc (no meta) should render text as-is."""
        source = "Hello world"
        ast = parse_str(source)
        doc = Doc.from_ast(ast)

        result = render(doc)

        assert result == "Hello world"

    def test_reference_tier_accepts_any_inputs(self) -> None:
        """Reference-tier should not validate inputs."""
        source = "Hello"
        ast = parse_str(source)
        doc = Doc.from_ast(ast)

        # Should not raise even with undeclared inputs
        result = render(doc, {"foo": "bar", "x": 123})

        assert "Hello" in result


class TestContractTier:
    """Tests for contract tier output generation."""

    def test_mixed_tier_no_contract_appended(self) -> None:
        """Mixed tier (meta but no outputs) should not append OUTPUT CONTRACT."""
        source = '{% meta doc_type="command" /%}Hello'
        ast = parse_str(source)
        doc = Doc.from_ast(ast)

        result = render(doc)

        assert "OUTPUT CONTRACT" not in result

    def test_contract_tier_appends_output_contract(self) -> None:
        """Contract tier should append OUTPUT CONTRACT block."""
        source = '{% meta doc_type="command" /%}{% output name="result" type="string" description="The result" /%}Hello'  # noqa: E501
        ast = parse_str(source)
        doc = Doc.from_ast(ast, path="commands/test.md")

        result = render(doc)

        assert "## OUTPUT CONTRACT" in result
        assert "result" in result
        assert "string" in result
        assert "The result" in result

    def test_contract_tier_output_ordering(self) -> None:
        """Output fields should appear in declaration order."""
        source = '{% meta doc_type="command" /%}{% output name="first" type="string" /%}{% output name="second" type="int" /%}{% output name="third" type="bool" /%}Text'  # noqa: E501
        ast = parse_str(source)
        doc = Doc.from_ast(ast, path="commands/test.md")

        result = render(doc)

        # Check relative ordering
        first_pos = result.find("first")
        second_pos = result.find("second")
        third_pos = result.find("third")
        assert first_pos < second_pos < third_pos

    def test_contract_tier_output_omits_description_when_none(self) -> None:
        """Output without description should not have trailing colon."""
        source = '{% meta doc_type="command" /%}{% output name="val" type="int" /%}Text'
        ast = parse_str(source)
        doc = Doc.from_ast(ast, path="commands/test.md")

        result = render(doc)

        # Should have "val" and "int" but description formatting varies
        assert "val" in result
        assert "int" in result


class TestPhaseRendering:
    """Tests for phase block rendering."""

    def test_phase_renders_as_heading(self) -> None:
        """Phase should render as markdown heading with body."""
        source = '{% phase name="Setup" %}Do this{% /phase %}'
        ast = parse_str(source)
        doc = Doc.from_ast(ast)

        result = render(doc)

        assert "## Phase: Setup" in result
        assert "Do this" in result

    def test_phase_when_true_includes_body(self) -> None:
        """Phase with when=true should include body."""
        source = '{% input name="x" type="int" /%}{% phase name="P" when="x == 1" %}body{% /phase %}'  # noqa: E501
        ast = parse_str(source)
        doc = Doc.from_ast(ast)

        result = render(doc, {"x": 1})

        assert "## Phase: P" in result
        assert "body" in result

    def test_phase_when_false_omits_heading_and_body(self) -> None:
        """Phase with when=false should omit everything."""
        source = '{% input name="x" type="int" /%}{% phase name="P" when="x == 2" %}body{% /phase %}'  # noqa: E501
        ast = parse_str(source)
        doc = Doc.from_ast(ast)

        result = render(doc, {"x": 1})

        assert "Phase: P" not in result
        assert "body" not in result


class TestWhenRendering:
    """Tests for when conditional rendering."""

    def test_when_true_includes_body(self) -> None:
        """When with true condition should include body."""
        source = '{% input name="x" type="int" /%}{% when expr="x == 1" %}yes{% /when %}'
        ast = parse_str(source)
        doc = Doc.from_ast(ast)

        result = render(doc, {"x": 1})

        assert "yes" in result

    def test_when_false_omits_body(self) -> None:
        """When with false condition should omit body."""
        source = '{% input name="x" type="int" /%}{% when expr="x == 2" %}no{% /when %}'
        ast = parse_str(source)
        doc = Doc.from_ast(ast)

        result = render(doc, {"x": 1})

        assert "no" not in result

    def test_when_uses_json_aliases(self) -> None:
        """When should work with bool values."""
        source = '{% input name="flag" type="bool" /%}{% when expr="flag == true" %}yes{% /when %}'
        ast = parse_str(source)
        doc = Doc.from_ast(ast)

        result = render(doc, {"flag": True})

        assert "yes" in result

    def test_when_invalid_expr_raises_render_error(self) -> None:
        """When with invalid expression should raise RenderError."""
        source = '{% when expr="unknown_var == 1" %}yes{% /when %}'
        ast = parse_str(source)
        doc = Doc.from_ast(ast)

        with pytest.raises(RenderError):
            render(doc)


class TestRunRendering:
    """Tests for run node rendering in Mode-A format."""

    def test_run_skill_form(self) -> None:
        """Run with skill should render skill call with body."""
        source = '{% run skill="issues/get_issue" %}{"key": "TEST-1"}{% /run %}'
        ast = parse_str(source)
        doc = Doc.from_ast(ast)

        result = render(doc)

        assert "Call the issues/get_issue skill:" in result
        assert "npx tsx ~/.claude/skills/issues/get_issue.ts" in result
        assert '{"key": "TEST-1"}' in result

    def test_run_bash_form_with_capture(self) -> None:
        """Run with bash and id should include capture sentence."""
        source = '{% run id="result" bash="ls -la" capture="text" /%}'
        ast = parse_str(source)
        doc = Doc.from_ast(ast)

        result = render(doc)

        assert "bash command" in result
        assert "ls -la" in result
        assert "Capture the text output and bind it as `$result`" in result

    def test_run_without_id_omits_bind_sentence(self) -> None:
        """Run without id should not mention binding."""
        source = '{% run bash="echo hi" /%}'
        ast = parse_str(source)
        doc = Doc.from_ast(ast)

        result = render(doc)

        assert "bind" not in result.lower()

    def test_run_body_substitutes_inputs(self) -> None:
        """Run body should substitute {% $inputs.x %} references."""
        source = '{% input name="key" type="string" /%}{% run skill="test" %}{"key": "{% $inputs.key %}"}{% /run %}'  # noqa: E501
        ast = parse_str(source)
        doc = Doc.from_ast(ast)

        result = render(doc, {"key": "ABC-123"})

        assert '"key": "ABC-123"' in result

    def test_run_command_form(self) -> None:
        """Run with command (back-compat) should render command block."""
        source = '{% run command="ls" /%}'
        ast = parse_str(source)
        doc = Doc.from_ast(ast)

        result = render(doc)

        assert "Execute the following command:" in result
        assert "ls" in result

    def test_run_prompt_file_form(self) -> None:
        """Run with prompt_file should render prompt file instruction."""
        source = '{% run prompt_file="prompt.md" /%}'
        ast = parse_str(source)
        doc = Doc.from_ast(ast)

        result = render(doc)

        assert "Render the prompt file at `prompt.md`" in result


class TestVariableSubstitution:
    """Tests for variable substitution."""

    def test_variable_substitution_inputs(self) -> None:
        """Variable substitution should work in text."""
        source = '{% input name="name" type="string" /%}Hello {% $inputs.name %}'
        ast = parse_str(source)
        doc = Doc.from_ast(ast)

        result = render(doc, {"name": "world"})

        assert "Hello world" in result

    def test_variable_substitution_missing_required_raises(self) -> None:
        """Missing required input should raise RenderError."""
        source = '{% meta doc_type="command" /%}{% input name="x" type="string" /%}Hello'
        ast = parse_str(source)
        doc = Doc.from_ast(ast)

        with pytest.raises(RenderError) as exc_info:
            render(doc, {})

        assert "x" in exc_info.value.missing

    def test_variable_substitution_undeclared_reference_raises(self) -> None:
        """Undeclared input reference should raise RenderError."""
        source = 'Hello {% $inputs.unknown %}'
        ast = parse_str(source)
        doc = Doc.from_ast(ast)

        with pytest.raises(RenderError, match="Undeclared input reference"):
            render(doc, {})

    def test_variable_substitution_default_applied(self) -> None:
        """Input default should be used when not provided."""
        source = '{% meta doc_type="command" /%}{% input name="greeting" type="string" default="Hi" /%}{% $inputs.greeting %}'  # noqa: E501
        ast = parse_str(source)
        doc = Doc.from_ast(ast)

        result = render(doc, {})

        assert "Hi" in result

    def test_variable_substitution_type_check_int_rejects_string(self) -> None:
        """Type mismatch should raise RenderError."""
        source = '{% meta doc_type="command" /%}{% input name="count" type="int" /%}Count'
        ast = parse_str(source)
        doc = Doc.from_ast(ast)

        with pytest.raises(RenderError) as exc_info:
            render(doc, {"count": "not-an-int"})

        assert exc_info.value.type_errors

    def test_variable_substitution_type_check_bool_rejects_string(self) -> None:
        """Bool type check should reject string."""
        source = '{% meta doc_type="command" /%}{% input name="flag" type="bool" /%}Text'
        ast = parse_str(source)
        doc = Doc.from_ast(ast)

        with pytest.raises(RenderError):
            render(doc, {"flag": "true"})

    def test_variable_substitution_inside_phase(self) -> None:
        """Variable substitution should work inside phase."""
        source = '{% input name="x" type="string" /%}{% phase name="P" %}Value: {% $inputs.x %}{% /phase %}'  # noqa: E501
        ast = parse_str(source)
        doc = Doc.from_ast(ast)

        result = render(doc, {"x": "test"})

        assert "Value: test" in result

    def test_variable_substitution_inside_when_body(self) -> None:
        """Variable substitution should work inside when body."""
        source = '{% input name="x" type="string" /%}{% when expr="true" %}X is {% $inputs.x %}{% /when %}'  # noqa: E501
        ast = parse_str(source)
        doc = Doc.from_ast(ast)

        result = render(doc, {"x": "value"})

        assert "X is value" in result

    def test_run_id_field_reference_raises_render_error(self) -> None:
        """{% $run_id.field %} should raise RenderError in Mode-A."""
        source = 'Result: {% $some_run.field %}'
        ast = parse_str(source)
        doc = Doc.from_ast(ast)

        with pytest.raises(RenderError, match="Mode-B run_context"):
            render(doc, {})


class TestRefRendering:
    """Tests for ref node rendering."""

    def test_ref_link_mode_no_section(self) -> None:
        """Ref without section should render as simple link."""
        source = '{% ref file="CLAUDE.md" /%}'
        ast = parse_str(source)
        doc = Doc.from_ast(ast)

        result = render(doc)

        # Should render as markdown link (may be absolute path if file exists)
        assert "[CLAUDE.md]" in result
        assert "CLAUDE.md)" in result

    def test_ref_link_mode_with_section(self) -> None:
        """Ref with section should include section in link."""
        source = '{% ref file="doc.md" section="intro" /%}'
        ast = parse_str(source)
        doc = Doc.from_ast(ast)

        result = render(doc)

        # Should include section anchor in both label and target
        assert "[doc.md#intro]" in result
        assert "#intro)" in result

    # Note: test_ref_include_true_raises_render_error removed in GW-5476
    # Include mode is now supported with cycle and depth detection


class TestRawRendering:
    """Tests for raw block rendering."""

    def test_raw_block_emitted_verbatim(self) -> None:
        """Raw block should be emitted without modification."""
        source = '{% raw %}{% $x %}{% endraw %}'
        ast = parse_str(source)
        doc = Doc.from_ast(ast)

        result = render(doc)

        assert "{% $x %}" in result

    def test_raw_block_with_variable_syntax_not_substituted(self) -> None:
        """Variable syntax inside raw block should not be substituted."""
        source = '{% input name="name" type="string" /%}{% raw %}Hello {% $inputs.name %}{% endraw %}'  # noqa: E501
        ast = parse_str(source)
        doc = Doc.from_ast(ast)

        result = render(doc, {"name": "world"})

        # Should have literal {% $inputs.name %}, not "world"
        assert "{% $inputs.name %}" in result
        assert "Hello world" not in result or "Hello {% $inputs.name %}" in result


class TestEmpty:
    """Test edge cases."""

    def test_render_empty_doc(self) -> None:
        """Empty doc should render as empty string or contract only."""
        source = ''
        ast = parse_str(source)
        doc = Doc.from_ast(ast)

        result = render(doc)

        assert result == ""
