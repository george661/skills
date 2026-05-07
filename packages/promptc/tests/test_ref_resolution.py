"""Tests for reference resolution (GW-5476)."""
from __future__ import annotations

from pathlib import Path

import pytest

from promptc import RenderError, parse_str, render
from promptc.schema import Doc


class TestRefCommandLinkMode:
    """Tests for {% ref command=\"...\" /%} link-mode rendering."""

    def test_ref_command_link_mode_renders_link_when_target_exists(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Command ref in link mode should render markdown link."""
        # Create a fake commands directory with a file
        commands_dir = tmp_path / ".claude" / "commands"
        commands_dir.mkdir(parents=True)
        command_file = commands_dir / "foo.md"
        command_file.write_text("# Foo command")

        # Set up environment so resolver finds the command
        monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))

        # Source with command ref
        source = '{% ref command="/foo" /%}'
        ast = parse_str(source)
        doc = Doc.from_ast(ast)

        result = render(doc, {})

        # Should render a link to the command file
        assert "[/foo]" in result
        assert str(command_file) in result


class TestRefMissingTarget:
    """Tests for missing ref targets."""

    def test_ref_command_missing_target_raises_render_error(self) -> None:
        """Missing command target should raise RenderError."""
        source = '{% ref command="/nope" /%}'
        ast = parse_str(source)
        doc = Doc.from_ast(ast)

        with pytest.raises(RenderError) as exc_info:
            render(doc, {})

        # Error should mention the command target
        assert "command" in str(exc_info.value).lower()
        assert "/nope" in str(exc_info.value) or "nope" in str(exc_info.value)


class TestRefNodeSchema:
    """Tests for RefNode schema validation."""

    def test_refnode_schema_requires_exactly_one_target(self) -> None:
        """RefNode should reject if both file and command are set."""
        from promptc.schema import RefNode, SourceSpan

        span = SourceSpan(start_line=1, start_col=0, end_line=1, end_col=10)

        # Should raise validation error when both file and command are set
        with pytest.raises(ValueError) as exc_info:
            RefNode(file="foo.md", command="/bar", source_span=span)

        assert "exactly one" in str(exc_info.value).lower()

    def test_refnode_schema_parses_command_and_skill_attrs(self) -> None:
        """Doc.from_ast should pass through command and skill attrs."""
        # Test command attr
        source = '{% ref command="/foo" /%}'
        ast = parse_str(source)
        doc = Doc.from_ast(ast)

        # Should have at least one node
        assert len(doc.nodes) > 0
        # First body node should be RefNode with command set
        first_node = doc.nodes[0]
        assert hasattr(first_node, "command")
        assert first_node.command == "/foo"  # type: ignore

        # Test skill attr
        source = '{% ref skill="bar" /%}'
        ast = parse_str(source)
        doc = Doc.from_ast(ast)

        first_node = doc.nodes[0]
        assert hasattr(first_node, "skill")
        assert first_node.skill == "bar"  # type: ignore


class TestRefSkillLinkMode:
    """Tests for {% ref skill=\"...\" /%} link-mode rendering."""

    def test_ref_skill_link_mode_renders_link_when_target_exists(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Skill ref in link mode should render markdown link."""
        # Create a fake skills directory with SKILL.md pattern
        skills_dir = tmp_path / ".claude" / "skills" / "foo"
        skills_dir.mkdir(parents=True)
        skill_file = skills_dir / "SKILL.md"
        skill_file.write_text("# Foo skill")

        # Set up environment so resolver finds the skill
        monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))

        # Source with skill ref
        source = '{% ref skill="foo" /%}'
        ast = parse_str(source)
        doc = Doc.from_ast(ast)

        result = render(doc, {})

        # Should render a link to the skill file
        assert "[foo]" in result
        assert str(skill_file) in result


class TestRefFileMissingTarget:
    """Tests for file ref with missing target in include mode."""

    def test_ref_file_missing_target_raises_render_error(self, tmp_path: Path) -> None:
        """Missing file target in include mode should raise RenderError."""
        source = '{% ref file="nonexistent.md" include=true /%}'
        ast = parse_str(source)
        doc = Doc.from_ast(ast, path=str(tmp_path / "test.md"))

        with pytest.raises(RenderError) as exc_info:
            render(doc, {})

        # Error should mention the file not found
        error_str = str(exc_info.value).lower()
        assert "not found" in error_str or "nonexistent" in error_str


class TestRefFileIncludeMode:
    """Tests for {% ref file=\"...\" include=true /%} inline rendering."""

    def test_ref_file_include_inlines_rendered_content(self, tmp_path: Path) -> None:
        """File ref with include=true should inline the file content."""
        # Create included file
        included_file = tmp_path / "CLAUDE.md"
        included_file.write_text("This is included content.")

        # Create main file that includes it
        main_file = tmp_path / "main.md"
        source = f'{{% ref file="{included_file.name}" include=true /%}}'
        ast = parse_str(source, path=str(main_file))
        doc = Doc.from_ast(ast, path=str(main_file))

        # Render should inline the content
        result = render(doc, {})

        assert "This is included content." in result


class TestRefIncludeCycles:
    """Tests for cyclic include detection."""

    def test_ref_include_cycle_raises_render_error(self, tmp_path: Path) -> None:
        """Cyclic includes (A->B->A) should raise RenderError with chain."""
        # Create files A and B
        file_a = tmp_path / "a.md"
        file_b = tmp_path / "b.md"

        # A includes B
        file_a.write_text(f'{{% ref file="{file_b.name}" include=true /%}}')
        # B includes A (cycle)
        file_b.write_text(f'{{% ref file="{file_a.name}" include=true /%}}')

        # Try to render A
        ast = parse_str(file_a.read_text(), path=str(file_a))
        doc = Doc.from_ast(ast, path=str(file_a))

        # Should raise with cycle detected
        with pytest.raises(RenderError) as exc_info:
            render(doc, {})

        error = exc_info.value
        assert "cycle" in str(error).lower()
        assert error.include_chain  # Should have include chain populated


class TestRefIncludeDepth:
    """Tests for max include depth enforcement."""

    def test_ref_include_exceeding_max_depth_raises_render_error(self, tmp_path: Path) -> None:
        """Include chain exceeding max depth should raise RenderError."""
        # Create chain A->B->C->D (depth 4, default max is 3)
        file_a = tmp_path / "a.md"
        file_b = tmp_path / "b.md"
        file_c = tmp_path / "c.md"
        file_d = tmp_path / "d.md"

        file_d.write_text("Depth 4 content")
        file_c.write_text(f'{{% ref file="{file_d.name}" include=true /%}}')
        file_b.write_text(f'{{% ref file="{file_c.name}" include=true /%}}')
        file_a.write_text(f'{{% ref file="{file_b.name}" include=true /%}}')

        ast = parse_str(file_a.read_text(), path=str(file_a))
        doc = Doc.from_ast(ast, path=str(file_a))

        # Should raise with depth exceeded
        with pytest.raises(RenderError) as exc_info:
            render(doc, {})

        error = exc_info.value
        assert "depth" in str(error).lower()
        assert error.include_chain  # Should have include chain populated
        # Chain should contain all 4 files (a->b->c->d)
        assert len(error.include_chain) >= 4


class TestRefCommandLeadingSlash:
    """Tests for command name normalization."""

    def test_ref_command_leading_slash_is_stripped(self, tmp_path: Path, monkeypatch) -> None:
        """Command refs with and without leading slash should resolve to same file."""
        commands_dir = tmp_path / ".claude" / "commands"
        commands_dir.mkdir(parents=True)
        command_file = commands_dir / "validate.md"
        command_file.write_text("# Validate command")

        monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))

        # Test with leading slash
        source1 = '{% ref command="/validate" /%}'
        ast1 = parse_str(source1)
        doc1 = Doc.from_ast(ast1)
        result1 = render(doc1, {})

        # Test without leading slash
        source2 = '{% ref command="validate" /%}'
        ast2 = parse_str(source2)
        doc2 = Doc.from_ast(ast2)
        result2 = render(doc2, {})

        # Both should resolve to the same file
        assert str(command_file) in result1
        assert str(command_file) in result2
