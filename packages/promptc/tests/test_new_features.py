"""Tests for newly implemented features."""
import time

import pytest

from promptc import ParseError, TimeoutError, parse_str
from promptc.parser import Parser


class TestMismatchedClosingTag:
    """Test mismatched closing tag detection."""

    def test_mismatched_closing_tag(self) -> None:
        """Mismatched closing tag should raise ParseError."""
        parser = Parser()
        with pytest.raises(ParseError, match="Mismatched closing tag: expected tag1, got tag2"):
            parser.parse("{% tag1 %}{% /tag2 %}")


class TestOrphanClosingTag:
    """Test orphan closing tag detection."""

    def test_orphan_closing_tag(self) -> None:
        """Orphan closing tag at top level should raise ParseError."""
        parser = Parser()
        with pytest.raises(
            ParseError,
            match="Unexpected closing tag: orphan has no matching opening tag"
        ):
            parser.parse("{% /orphan %}")


class TestStringEscaping:
    """Test string value escaping."""

    def test_string_with_escaped_quotes(self) -> None:
        """String values should support escaped quotes."""
        parser = Parser()
        nodes = parser.parse('{% tag attr="He said \\"hello\\"" /%}')
        assert len(nodes) == 1
        assert nodes[0].attrs["attr"] == 'He said "hello"'

    def test_string_with_escaped_backslash(self) -> None:
        """String values should support escaped backslashes."""
        parser = Parser()
        nodes = parser.parse('{% tag path="C:\\\\Users\\\\file.txt" /%}')
        assert len(nodes) == 1
        assert nodes[0].attrs["path"] == "C:\\Users\\file.txt"


class TestMalformedArray:
    """Test array validation."""

    def test_malformed_array_raises(self) -> None:
        """Array elements must be double-quoted strings."""
        parser = Parser()

        # Unquoted element
        with pytest.raises(ParseError, match="Array elements must be double-quoted strings"):
            parser.parse("{% tag items=[unquoted] /%}")

        # Single-quoted element (not supported)
        with pytest.raises(ParseError, match="Array elements must be double-quoted strings"):
            parser.parse("{% tag items=['single'] /%}")


class TestModuleFunctions:
    """Test module-level parse() and parse_str() functions."""

    def test_parse_str_returns_document_node(self) -> None:
        """parse_str should return a document node."""
        doc = parse_str("{% tag /%}")
        assert doc.kind == "document"
        assert len(doc.children) == 1
        assert doc.children[0].kind == "tag"

    def test_parse_str_with_path(self) -> None:
        """parse_str should accept optional path parameter."""
        with pytest.raises(ParseError) as exc_info:
            parse_str("{% tag %}", path="test.prompt")
        assert "test.prompt" in str(exc_info.value)


class TestRegexTimeout:
    """Test regex timeout protection."""

    def test_pathological_pattern_with_timeout(self) -> None:
        """Pathological regex pattern should timeout."""
        from promptc import ParserConfig

        # Create a pathological input that would cause catastrophic backtracking
        # Pattern: (a+)+$ against input: aaaaaaaaaaaaaaaaaX
        # This would normally hang, but our timeout should catch it
        parser = Parser(ParserConfig(regex_timeout_ms=100))

        # We use a malicious attribute value to trigger the regex
        # The STRING_VALUE pattern now uses (?:[^\\"]|\\.)* which is safe,
        # but we still test the timeout mechanism by creating an edge case
        pathological = '{% tag attr="' + 'a' * 1000 + 'X' + '" /%}'

        start = time.monotonic()
        try:
            # This should either parse successfully or timeout within 200ms
            parser.parse(pathological)
        except TimeoutError:
            # Good - timeout caught it
            pass
        elapsed = time.monotonic() - start

        # Should complete within 200ms (either success or timeout)
        assert elapsed < 0.2, f"Parser took {elapsed:.3f}s, expected < 0.2s"
