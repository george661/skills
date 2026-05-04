"""Tests for promptc schema models."""
from __future__ import annotations

import pytest
from pydantic import BaseModel, ValidationError

from promptc import parse_str
from promptc.schema import (
    Doc,
    InputDecl,
    MetaDecl,
    OutputDecl,
    ParseErrorInfo,
    ParseResult,
    PhaseNode,
    RefNode,
    RunNode,
    SourceSpan,
    TextNode,
    ValidationIssue,
    ValidationReport,
    WhenNode,
)


class TestPydanticV2Verification:
    """Test that all public types are pydantic BaseModel subclasses."""

    def test_all_public_types_are_basemodel(self) -> None:
        """All schema types should be pydantic BaseModel subclasses."""
        types_to_check = [
            Doc,
            MetaDecl,
            InputDecl,
            OutputDecl,
            PhaseNode,
            RunNode,
            RefNode,
            WhenNode,
            TextNode,
            SourceSpan,
            ParseErrorInfo,
            ParseResult,
            ValidationIssue,
            ValidationReport,
        ]
        for typ in types_to_check:
            assert issubclass(typ, BaseModel), f"{typ.__name__} must be BaseModel subclass"

    def test_models_are_frozen(self) -> None:
        """Models should be frozen (immutable)."""
        doc = Doc(
            path="test.md",
            source_span=SourceSpan(start_line=1, start_col=1, end_line=1, end_col=10),
        )
        with pytest.raises(ValidationError):
            doc.path = "new.md"  # type: ignore[misc]


class TestTierClassification:
    """Test document tier classification."""

    def test_reference_tier_from_empty_doc(self) -> None:
        """Doc with no meta should be reference tier."""
        doc = Doc(
            meta=None,
            outputs=[],
            nodes=[],
            source_span=SourceSpan(start_line=1, start_col=1, end_line=1, end_col=1),
        )
        assert doc.tier == "reference"

    def test_mixed_tier_meta_no_output(self) -> None:
        """Doc with meta but no outputs should be mixed tier."""
        doc = Doc(
            meta=MetaDecl(description="test"),
            outputs=[],
            nodes=[],
            source_span=SourceSpan(start_line=1, start_col=1, end_line=1, end_col=1),
        )
        assert doc.tier == "mixed"

    def test_contract_tier_meta_and_output(self) -> None:
        """Doc with meta and outputs should be contract tier."""
        doc = Doc(
            meta=MetaDecl(description="test"),
            outputs=[OutputDecl(name="result", type="string")],
            nodes=[],
            source_span=SourceSpan(start_line=1, start_col=1, end_line=1, end_col=1),
        )
        assert doc.tier == "contract"


class TestPathBasedDocTypeInference:
    """Test path-based doc_type inference."""

    def test_path_commands_infers_command(self) -> None:
        """Path starting with commands/ should infer command doc_type."""
        doc = Doc(
            path="commands/work.md",
            doc_type=None,
            source_span=SourceSpan(start_line=1, start_col=1, end_line=1, end_col=1),
        )
        assert doc.resolved_doc_type == "command"

    def test_path_skills_infers_skill(self) -> None:
        """Path starting with skills/ should infer skill doc_type."""
        doc = Doc(
            path="skills/fly-operations.md",
            doc_type=None,
            source_span=SourceSpan(start_line=1, start_col=1, end_line=1, end_col=1),
        )
        assert doc.resolved_doc_type == "skill"

    def test_path_other_infers_reference(self) -> None:
        """Other paths should infer reference doc_type."""
        doc = Doc(
            path="docs/guide.md",
            doc_type=None,
            source_span=SourceSpan(start_line=1, start_col=1, end_line=1, end_col=1),
        )
        assert doc.resolved_doc_type == "reference"

    def test_explicit_doc_type_overrides_path(self) -> None:
        """Explicit doc_type should override path heuristic."""
        doc = Doc(
            path="commands/x.md",
            doc_type="reference",
            source_span=SourceSpan(start_line=1, start_col=1, end_line=1, end_col=1),
        )
        assert doc.resolved_doc_type == "reference"

    def test_cross_platform_path_separators(self) -> None:
        """Backslash paths should normalize correctly."""
        doc = Doc(
            path="commands\\foo.md",
            doc_type=None,
            source_span=SourceSpan(start_line=1, start_col=1, end_line=1, end_col=1),
        )
        assert doc.resolved_doc_type == "command"


class TestASTRoundtrip:
    """Test AST round-trip preservation."""

    def test_roundtrip_preserves_node_order_and_interleaving(self) -> None:
        """Round-trip should preserve node order including interleaving."""
        source = 'text {% phase name="p" %}nested{% /phase %} more text {% ref file="x" /%}'
        ast = parse_str(source)
        doc = Doc.from_ast(ast, path="test.md")

        # Should have 4 nodes in order: text, phase, text, ref
        assert len(doc.nodes) == 4
        assert doc.nodes[0].kind == "text"
        assert doc.nodes[1].kind == "phase"
        assert doc.nodes[2].kind == "text"
        assert doc.nodes[3].kind == "ref"

    def test_roundtrip_phase_preserves_nested_tags(self) -> None:
        """Phase blocks should preserve nested tag structure."""
        source = '{% phase name="test" %}text {% run command="cmd" /%} more{% /phase %}'
        ast = parse_str(source)
        doc = Doc.from_ast(ast, path="test.md")

        # Find the phase node
        phase_nodes = [n for n in doc.nodes if n.kind == "phase"]
        assert len(phase_nodes) == 1
        phase = phase_nodes[0]
        assert isinstance(phase, PhaseNode)

        # Phase should have children preserved
        assert len(phase.children) > 0
        # Should have at least the nested run node
        run_children = [c for c in phase.children if c.get("kind") == "run"]
        assert len(run_children) == 1

    def test_roundtrip_strips_meta_input_output(self) -> None:
        """Meta, input, output nodes should be extracted, not in nodes list."""
        source = (
            '{% meta description="x" /%}'
            '{% input name="a" type="string" /%}'
            '{% output name="b" type="string" /%}text'
        )
        ast = parse_str(source)
        doc = Doc.from_ast(ast, path="test.md")

        # Meta, inputs, outputs should be extracted
        assert doc.meta is not None
        assert len(doc.inputs) == 1
        assert len(doc.outputs) == 1

        # nodes should only have text, not meta/input/output
        assert len(doc.nodes) == 1
        assert doc.nodes[0].kind == "text"

    def test_roundtrip_preserves_source_spans(self) -> None:
        """Source spans should be preserved through round-trip."""
        source = '{% phase name="test" %}body{% /phase %}'
        ast = parse_str(source)
        doc = Doc.from_ast(ast, path="test.md")

        phase_nodes = [n for n in doc.nodes if n.kind == "phase"]
        assert len(phase_nodes) == 1
        phase = phase_nodes[0]

        # Source span should exist and have valid line/col info
        assert phase.source_span.start_line > 0
        assert phase.source_span.end_line > 0


class TestCLAUDEMDNoFrontmatter:
    """Test CLAUDE.md-style docs without frontmatter."""

    def test_claude_md_no_frontmatter_classifies_reference_renders_without_error(self) -> None:
        """CLAUDE.md with no frontmatter should parse, classify as reference, and serialize."""
        # Realistic CLAUDE.md prose without any tag syntax
        source = """# Project Overview

This is a project description with no metadata tags.

## Features

- Feature 1
- Feature 2

## Usage

Just regular markdown text."""

        ast = parse_str(source)
        doc = Doc.from_ast(ast, path="CLAUDE.md")

        # Should classify as reference tier
        assert doc.tier == "reference"

        # Should serialize without error
        dumped = doc.model_dump()
        assert dumped is not None
        assert dumped["tier"] == "reference"


class TestSkillFileMixedTier:
    """Test skill file with meta but no output."""

    def test_skill_with_meta_no_output_is_mixed(self) -> None:
        """Skill with meta but no output should be mixed tier."""
        source = '{% meta description="x" /%}\nprose text'
        ast = parse_str(source)
        doc = Doc.from_ast(ast, path="skills/example.md")

        assert doc.tier == "mixed"
        assert doc.meta is not None
        assert len(doc.outputs) == 0


class TestCommandFileContractTier:
    """Test command file with meta and output."""

    def test_command_with_meta_and_output_is_contract(self) -> None:
        """Command with meta and output should be contract tier."""
        source = '{% meta description="x" /%}{% output name="result" type="string" /%}\nprose'
        ast = parse_str(source)
        doc = Doc.from_ast(ast, path="commands/example.md")

        assert doc.tier == "contract"
        assert doc.meta is not None
        assert len(doc.outputs) == 1


class TestUnknownMetaKeys:
    """Test that unknown meta keys are preserved in extras."""

    def test_unknown_meta_keys_preserved_in_extras(self) -> None:
        """Unknown meta attributes should go into extras dict."""
        source = '{% meta description="x" weirdKey=true customAttr="value" /%}'
        ast = parse_str(source)
        doc = Doc.from_ast(ast, path="test.md")

        assert doc.meta is not None
        assert doc.meta.description == "x"
        assert "weirdKey" in doc.meta.extras
        assert doc.meta.extras["weirdKey"] is True
        assert "customAttr" in doc.meta.extras
        assert doc.meta.extras["customAttr"] == "value"


class TestParseResultShape:
    """Test ParseResult and ParseErrorInfo data structures."""

    def test_parse_result_success(self) -> None:
        """ParseResult with success should roundtrip."""
        result = ParseResult[str](success=True, value="ok")
        assert result.success is True
        assert result.value == "ok"
        assert len(result.errors) == 0

    def test_parse_result_error(self) -> None:
        """ParseResult with errors should roundtrip."""
        error = ParseErrorInfo(code="E001", message="bad")
        result = ParseResult[str](success=False, errors=[error])
        assert result.success is False
        assert result.value is None
        assert len(result.errors) == 1
        assert result.errors[0].code == "E001"


class TestValidationReportShape:
    """Test ValidationReport and issue filtering."""

    def test_validation_report_filters(self) -> None:
        """ValidationReport should filter errors and warnings."""
        span = SourceSpan(start_line=1, start_col=1, end_line=1, end_col=10)
        issues = [
            ValidationIssue(severity="error", code="E1", message="error 1", source_span=span),
            ValidationIssue(severity="error", code="E2", message="error 2", source_span=span),
            ValidationIssue(severity="warning", code="W1", message="warning 1", source_span=span),
        ]
        report = ValidationReport(ok=False, issues=issues)

        assert len(report.errors) == 2
        assert len(report.warnings) == 1
        assert all(e.severity == "error" for e in report.errors)
        assert all(w.severity == "warning" for w in report.warnings)


class TestModelExtraForbid:
    """Test that models reject extra attributes."""

    def test_doc_rejects_extra_attributes(self) -> None:
        """Doc should reject unknown attributes."""
        with pytest.raises(ValidationError):
            Doc(
                path="test.md",
                unknown_field="value",  # type: ignore[call-arg]
                source_span=SourceSpan(start_line=1, start_col=1, end_line=1, end_col=1),
            )

    def test_input_decl_rejects_extra_attributes(self) -> None:
        """InputDecl should reject unknown attributes."""
        with pytest.raises(ValidationError):
            InputDecl(
                name="test",
                type="string",
                unknown_field="value",  # type: ignore[call-arg]
            )
