"""AST node definitions for the promptc parser.

Per CLAUDE.md's 500-line rule, AST nodes are separated from parser.py.
The spec's schema.py (GW-5481) will handle tag-schema validation later.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class SourceSpan:
    """Source location metadata for error reporting and debugging."""

    start_line: int
    start_col: int
    end_line: int
    end_col: int

    def to_dict(self) -> dict[str, int]:
        return {
            "start_line": self.start_line,
            "start_col": self.start_col,
            "end_line": self.end_line,
            "end_col": self.end_col,
        }


@dataclass
class Node:
    """Base AST node with source location tracking."""

    kind: str
    attrs: dict[str, Any]
    children: list[Node]
    body: str | None  # For text nodes and raw blocks
    source_span: SourceSpan

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-safe dictionary."""
        return {
            "kind": self.kind,
            "attrs": self.attrs,
            "children": [child.to_dict() for child in self.children],
            "body": self.body,
            "source_span": self.source_span.to_dict(),
        }
