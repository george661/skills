"""Promptc parser: tokenizes and builds AST from prompt composition syntax.

Supports:
- Tag syntax: {% tag attr=val %}, {% tag /%}, {% tag %}...{% /tag %}
- Attributes: strings, bools, numbers, string arrays
- Raw blocks: {% raw %}...{% endraw %} (no inner interpretation)
- Unknown tag names → structural nodes (schema validation is GW-5481)
"""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from pathlib import Path
from typing import Any

from promptc.ast_nodes import Node, SourceSpan
from promptc.config import ParserConfig
from promptc.errors import LimitExceededError, ParseError, TimeoutError

# Tag patterns
TAG_OPEN = re.compile(r'\{%\s*([a-zA-Z_][a-zA-Z0-9_-]*)\s*')
TAG_CLOSE_SELF = re.compile(r'/%\}')
TAG_CLOSE = re.compile(r'%\}')
TAG_END = re.compile(r'\{%\s*/([a-zA-Z_][a-zA-Z0-9_-]*)\s*%\}')

# Attribute patterns (simple and safe - not vulnerable to ReDoS)
ATTR_NAME = re.compile(r'([a-zA-Z_][a-zA-Z0-9_-]*)\s*=\s*')
STRING_VALUE = re.compile(r'"((?:[^\\"]|\\.)*)"')
BOOL_VALUE = re.compile(r'(true|false)\b')
NUMBER_VALUE = re.compile(r'(-?\d+(?:\.\d+)?)\b')
ARRAY_VALUE = re.compile(r'\[([^\]]*)\]')


class Parser:
    """Parser for promptc syntax."""

    def __init__(self, config: ParserConfig | None = None) -> None:
        self.config = config or ParserConfig()
        self._tag_count = 0
        self._node_count = 0
        self._path: str | None = None

    def parse(self, source: str, path: str | None = None) -> list[Node]:
        """Parse source text into a list of AST nodes.

        Args:
            source: Prompt composition source text
            path: Optional file path for error reporting

        Returns:
            List of top-level AST nodes

        Raises:
            ParseError: Invalid syntax
            LimitExceededError: Tag or node count exceeded
        """
        self._tag_count = 0
        self._node_count = 0
        self._path = path

        nodes: list[Node] = []
        pos = 0
        line = 1
        col = 1

        while pos < len(source):
            # Check for tag start
            match = TAG_OPEN.match(source, pos)
            if match:
                tag_name = match.group(1)
                self._check_tag_limit()

                # Handle raw blocks specially
                if tag_name == "raw":
                    node, new_pos, new_line, new_col = self._parse_raw_block(
                        source, pos, line, col
                    )
                    nodes.append(node)
                    pos = new_pos
                    line = new_line
                    col = new_col
                    continue

                # Parse tag
                node, new_pos, new_line, new_col = self._parse_tag(
                    source, pos, line, col, tag_name
                )
                nodes.append(node)
                pos = new_pos
                line = new_line
                col = new_col
            else:
                # Check for orphan closing tag at top level
                end_match = TAG_END.match(source, pos)
                if end_match:
                    orphan_tag = end_match.group(1)
                    raise self._error(
                        f"Unexpected closing tag: {orphan_tag} has no matching opening tag",
                        line,
                        col
                    )
                # Consume text until next tag or EOF
                next_tag = source.find("{%", pos)
                if next_tag == -1:
                    text = source[pos:]
                    pos = len(source)
                else:
                    text = source[pos:next_tag]
                    pos = next_tag

                if text:
                    # Create text node
                    start_line, start_col = line, col
                    for char in text:
                        if char == '\n':
                            line += 1
                            col = 1
                        else:
                            col += 1

                    self._check_node_limit()
                    nodes.append(Node(
                        kind="text",
                        attrs={},
                        children=[],
                        body=text,
                        source_span=SourceSpan(start_line, start_col, line, col)
                    ))

        return nodes

    def _parse_tag(
        self, source: str, pos: int, line: int, col: int, tag_name: str
    ) -> tuple[Node, int, int, int]:
        """Parse a single tag (self-closing or paired)."""
        start_line, start_col = line, col

        # Skip past tag name
        match = TAG_OPEN.match(source, pos)
        if not match:
            raise self._error("Invalid tag syntax", line, col)

        pos += len(match.group(0))
        col += len(match.group(0))

        # Parse attributes
        attrs, pos, line, col = self._parse_attributes(source, pos, line, col)

        # Skip whitespace
        while pos < len(source) and source[pos] in ' \t':
            pos += 1
            col += 1

        # Check for self-closing
        if pos + 2 < len(source) and source[pos:pos+3] == '/%}':
            pos += 3
            col += 3

            self._check_node_limit()
            return (
                Node(
                    kind=tag_name,
                    attrs=attrs,
                    children=[],
                    body=None,
                    source_span=SourceSpan(start_line, start_col, line, col)
                ),
                pos,
                line,
                col
            )

        # Check for regular close
        if pos + 1 < len(source) and source[pos:pos+2] == '%}':
            pos += 2
            col += 2
        else:
            raise self._error("Expected %} or /%}", line, col)

        # Parse children until closing tag
        children: list[Node] = []
        while pos < len(source):
            # Check for closing tag
            end_match = TAG_END.match(source, pos)
            if end_match:
                closing_tag_name = end_match.group(1)
                if closing_tag_name == tag_name:
                    end_len = len(end_match.group(0))
                    pos += end_len
                    col += end_len

                    self._check_node_limit()
                    return (
                        Node(
                            kind=tag_name,
                            attrs=attrs,
                            children=children,
                            body=None,
                            source_span=SourceSpan(start_line, start_col, line, col)
                        ),
                        pos,
                        line,
                        col
                    )
                else:
                    # Mismatched closing tag
                    raise self._error(
                        f"Mismatched closing tag: expected {tag_name}, got {closing_tag_name}",
                        line,
                        col
                    )

            # Parse child node
            next_tag = TAG_OPEN.match(source, pos)
            if next_tag:
                child_tag_name = next_tag.group(1)
                self._check_tag_limit()

                if child_tag_name == "raw":
                    child, pos, line, col = self._parse_raw_block(source, pos, line, col)
                else:
                    child, pos, line, col = self._parse_tag(source, pos, line, col, child_tag_name)
                children.append(child)
            else:
                # Text content
                next_tag_pos = source.find("{%", pos)
                if next_tag_pos == -1:
                    raise self._error(f"Unclosed tag: {tag_name}", line, col)

                text = source[pos:next_tag_pos]
                if text:
                    text_start_line, text_start_col = line, col
                    for char in text:
                        if char == '\n':
                            line += 1
                            col = 1
                        else:
                            col += 1

                    self._check_node_limit()
                    children.append(Node(
                        kind="text",
                        attrs={},
                        children=[],
                        body=text,
                        source_span=SourceSpan(text_start_line, text_start_col, line, col)
                    ))
                pos = next_tag_pos

        raise self._error(f"Unclosed tag: {tag_name}", start_line, start_col)

    def _parse_raw_block(
        self, source: str, pos: int, line: int, col: int
    ) -> tuple[Node, int, int, int]:
        """Parse {% raw %}...{% endraw %} with no inner interpretation."""
        start_line, start_col = line, col

        # Skip past {% raw %}
        open_match = TAG_OPEN.match(source, pos)
        if not open_match or open_match.group(1) != "raw":
            raise self._error("Expected {% raw %}", line, col)

        pos += len(open_match.group(0))
        col += len(open_match.group(0))

        # Skip to %}
        while pos < len(source) and source[pos] in ' \t':
            pos += 1
            col += 1

        if pos + 1 < len(source) and source[pos:pos+2] == '%}':
            pos += 2
            col += 2
        else:
            raise self._error("Expected %}", line, col)

        # Find {% endraw %}
        end_marker = "{% endraw %}"
        end_pos = source.find(end_marker, pos)
        if end_pos == -1:
            raise self._error("Unclosed {% raw %} block", start_line, start_col)

        # Extract body
        body = source[pos:end_pos]

        # Update position
        for char in body:
            if char == '\n':
                line += 1
                col = 1
            else:
                col += 1
        pos = end_pos + len(end_marker)
        col += len(end_marker)

        self._check_node_limit()
        return (
            Node(
                kind="raw",
                attrs={},
                children=[],
                body=body,
                source_span=SourceSpan(start_line, start_col, line, col)
            ),
            pos,
            line,
            col
        )

    def _parse_attributes(
        self, source: str, pos: int, line: int, col: int
    ) -> tuple[dict[str, Any], int, int, int]:
        """Parse tag attributes."""
        attrs: dict[str, Any] = {}

        while pos < len(source):
            # Skip whitespace
            while pos < len(source) and source[pos] in ' \t':
                pos += 1
                col += 1

            # Check if we've hit the tag close
            if pos >= len(source) or source[pos:pos+2] in ['%}', '/%']:
                break

            # Parse attribute name
            attr_match = ATTR_NAME.match(source, pos)
            if not attr_match:
                break

            attr_name = attr_match.group(1)
            pos += len(attr_match.group(0))
            col += len(attr_match.group(0))

            # Parse value
            value, value_len = self._parse_attribute_value(source, pos, line, col)
            attrs[attr_name] = value
            pos += value_len
            col += value_len

        return attrs, pos, line, col

    def _parse_attribute_value(self, source: str, pos: int, line: int, col: int) -> tuple[Any, int]:
        """Parse a single attribute value."""
        # String (with timeout protection)
        match = self._regex_match_with_timeout(STRING_VALUE, source, pos)
        if match:
            # Unescape \" and \\
            value = match.group(1)
            value = value.replace(r'\"', '"').replace(r'\\', '\\')
            return value, len(match.group(0))

        # Array
        match = self._regex_match_with_timeout(ARRAY_VALUE, source, pos)
        if match:
            array_content = match.group(1)
            # Parse array elements - must be double-quoted strings
            elements = []
            if array_content.strip():
                for elem in array_content.split(','):
                    elem = elem.strip()
                    if elem.startswith('"') and elem.endswith('"') and len(elem) >= 2:
                        # Unescape the string value
                        unescaped = elem[1:-1].replace(r'\"', '"').replace(r'\\', '\\')
                        elements.append(unescaped)
                    elif elem:  # Non-empty but not properly quoted
                        raise self._error(
                            f"Array elements must be double-quoted strings, got: {elem}",
                            line,
                            col
                        )
            return elements, len(match.group(0))

        # Boolean
        match = BOOL_VALUE.match(source, pos)
        if match:
            return match.group(1) == "true", len(match.group(0))

        # Number
        match = NUMBER_VALUE.match(source, pos)
        if match:
            val = match.group(1)
            return float(val) if '.' in val else int(val), len(match.group(0))

        raise self._error("Invalid attribute value", line, col)

    def _check_tag_limit(self) -> None:
        """Check if tag count limit is exceeded."""
        self._tag_count += 1
        if self._tag_count > self.config.max_tags_per_file:
            raise LimitExceededError(
                "Tag count limit exceeded",
                self.config.max_tags_per_file,
                self._tag_count
            )

    def _check_node_limit(self) -> None:
        """Check if AST node limit is exceeded."""
        self._node_count += 1
        if self._node_count > self.config.max_ast_nodes:
            raise LimitExceededError(
                "AST node limit exceeded",
                self.config.max_ast_nodes,
                self._node_count
            )

    def _error(self, message: str, line: int, col: int) -> ParseError:
        """Create a ParseError with path information."""
        return ParseError(message, line, col, self._path)

    def _regex_match_with_timeout(
        self, pattern: re.Pattern[str], source: str, pos: int
    ) -> re.Match[str] | None:
        """Execute regex match with timeout protection against ReDoS.

        Args:
            pattern: Compiled regex pattern
            source: Source string to match against
            pos: Position to start matching

        Returns:
            Match object or None if no match

        Raises:
            TimeoutError: If match exceeds configured timeout
        """
        def do_match() -> re.Match[str] | None:
            return pattern.match(source, pos)

        timeout_seconds = self.config.regex_timeout_ms / 1000.0
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(do_match)
            try:
                return future.result(timeout=timeout_seconds)
            except FuturesTimeoutError:
                raise TimeoutError(
                    f"Regex match exceeded timeout at position {pos}",
                    self.config.regex_timeout_ms
                )


def parse(path: str | Path) -> Node:
    """Parse a promptc file into a document AST node.

    Args:
        path: Path to the promptc file

    Returns:
        Document node with children representing the parsed content

    Raises:
        ParseError: Invalid syntax
        LimitExceededError: Tag or node count exceeded
    """
    path_obj = Path(path)
    source = path_obj.read_text(encoding='utf-8')
    parser = Parser()
    children = parser.parse(source, path=str(path_obj))

    # Calculate document span
    lines = source.split('\n')
    end_line = len(lines)
    end_col = len(lines[-1]) if lines else 1

    return Node(
        kind="document",
        attrs={},
        children=children,
        body=None,
        source_span=SourceSpan(1, 1, end_line, end_col)
    )


def parse_str(text: str, *, path: str | None = None) -> Node:
    """Parse a promptc string into a document AST node.

    Args:
        text: Promptc source text
        path: Optional file path for error reporting

    Returns:
        Document node with children representing the parsed content

    Raises:
        ParseError: Invalid syntax
        LimitExceededError: Tag or node count exceeded
    """
    parser = Parser()
    children = parser.parse(text, path=path)

    # Calculate document span
    lines = text.split('\n')
    end_line = len(lines)
    end_col = len(lines[-1]) if lines else 1

    return Node(
        kind="document",
        attrs={},
        children=children,
        body=None,
        source_span=SourceSpan(1, 1, end_line, end_col)
    )
