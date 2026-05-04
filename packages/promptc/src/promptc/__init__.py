"""Promptc: Prompt composition language compiler for Claude agents."""
from __future__ import annotations

from promptc.ast_nodes import Node, SourceSpan
from promptc.config import ParserConfig
from promptc.errors import LimitExceededError, ParseError, TimeoutError
from promptc.parser import parse, parse_str
from promptc.schema import (
    Doc,
    InputDecl,
    MetaDecl,
    OutputDecl,
    ParseErrorInfo,
    ParseResult,
    PhaseNode,
    RawNode,
    RefNode,
    RunNode,
    TextNode,
    ValidationIssue,
    ValidationReport,
    WhenNode,
)

__all__ = [
    "parse",
    "parse_str",
    "ParserConfig",
    "Node",
    "SourceSpan",
    "ParseError",
    "LimitExceededError",
    "TimeoutError",
    # Schema models
    "Doc",
    "MetaDecl",
    "InputDecl",
    "OutputDecl",
    "PhaseNode",
    "RunNode",
    "RefNode",
    "WhenNode",
    "TextNode",
    "RawNode",
    "ParseErrorInfo",
    "ParseResult",
    "ValidationIssue",
    "ValidationReport",
]
