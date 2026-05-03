"""Promptc parser: tokenizes and builds AST from prompt composition syntax.

Supports:
- Tag syntax: {% tag attr=val %}, {% tag /%}, {% tag %}...{% /tag %}
- Attributes: strings, bools, numbers, string arrays
- Raw blocks: {% raw %}...{% endraw %} (no inner interpretation)
- Unknown tag names → structural nodes (schema validation is GW-5481)
"""
from __future__ import annotations

import re
from typing import Any

from promptc.ast_nodes import Node, SourceSpan
from promptc.config import ParserConfig
from promptc.errors import LimitExceededError, ParseError

# Tag patterns
TAG_OPEN = re.compile(r'\{%\s*([a-zA-Z_][a-zA-Z0-9_-]*)\s*')
TAG_CLOSE_SELF = re.compile(r'/%\}')
TAG_CLOSE = re.compile(r'%\}')
TAG_END = re.compile(r'\{%\s*/([a-zA-Z_][a-zA-Z0-9_-]*)\s*%\}')

# Attribute patterns (simple and safe - not vulnerable to ReDoS)
ATTR_NAME = re.compile(r'([a-zA-Z_][a-zA-Z0-9_-]*)\s*=\s*')
STRING_VALUE = re.compile(r'"([^"]*)"')
BOOL_VALUE = re.compile(r'(true|false)\b')
NUMBER_VALUE = re.compile(r'(-?\d+(?:\.\d+)?)\b')
ARRAY_VALUE = re.compile(r'\[([^\]]*)\]')


class Parser:
    """Parser for promptc syntax."""

    def __init__(self, config: ParserConfig | None = None) -> None:
        self.config = config or ParserConfig()
        self._tag_count = 0
        self._node_count = 0

    def parse(self, source: str) -> list[Node]:
        """Parse source text into a list of AST nodes.

        Args:
            source: Prompt composition source text

        Returns:
            List of top-level AST nodes

        Raises:
            ParseError: Invalid syntax
            LimitExceededError: Tag or node count exceeded
        """
        self._tag_count = 0
        self._node_count = 0

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
            raise ParseError("Invalid tag syntax", line, col)

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
            raise ParseError("Expected %} or /%}", line, col)

        # Parse children until closing tag
        children: list[Node] = []
        while pos < len(source):
            # Check for closing tag
            end_match = TAG_END.match(source, pos)
            if end_match and end_match.group(1) == tag_name:
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
                    raise ParseError(f"Unclosed tag: {tag_name}", line, col)

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

        raise ParseError(f"Unclosed tag: {tag_name}", start_line, start_col)

    def _parse_raw_block(
        self, source: str, pos: int, line: int, col: int
    ) -> tuple[Node, int, int, int]:
        """Parse {% raw %}...{% endraw %} with no inner interpretation."""
        start_line, start_col = line, col

        # Skip past {% raw %}
        open_match = TAG_OPEN.match(source, pos)
        if not open_match or open_match.group(1) != "raw":
            raise ParseError("Expected {% raw %}", line, col)

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
            raise ParseError("Expected %}", line, col)

        # Find {% /raw %}
        end_marker = "{% /raw %}"
        end_pos = source.find(end_marker, pos)
        if end_pos == -1:
            raise ParseError("Unclosed {% raw %} block", start_line, start_col)

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
            value, value_len = self._parse_attribute_value(source, pos)
            attrs[attr_name] = value
            pos += value_len
            col += value_len

        return attrs, pos, line, col

    def _parse_attribute_value(self, source: str, pos: int) -> tuple[Any, int]:
        """Parse a single attribute value."""
        # String
        match = STRING_VALUE.match(source, pos)
        if match:
            return match.group(1), len(match.group(0))

        # Array
        match = ARRAY_VALUE.match(source, pos)
        if match:
            array_content = match.group(1)
            # Parse array elements
            elements = []
            if array_content.strip():
                for elem in array_content.split(','):
                    elem = elem.strip()
                    if elem.startswith('"') and elem.endswith('"'):
                        elements.append(elem[1:-1])
                    else:
                        elements.append(elem)
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

        raise ParseError("Invalid attribute value", 0, pos)

    def _check_tag_limit(self) -> None:
        """Check if tag count limit is exceeded."""
        self._tag_count += 1
        if self._tag_count > self.config.max_tags:
            raise LimitExceededError(
                "Tag count limit exceeded",
                self.config.max_tags,
                self._tag_count
            )

    def _check_node_limit(self) -> None:
        """Check if AST node limit is exceeded."""
        self._node_count += 1
        if self._node_count > self.config.max_nodes:
            raise LimitExceededError(
                "AST node limit exceeded",
                self.config.max_nodes,
                self._node_count
            )
