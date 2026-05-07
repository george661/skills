"""Promptc: Prompt composition language compiler for Claude agents."""
from __future__ import annotations

from promptc.ast_nodes import Node, SourceSpan
from promptc.config import ParserConfig
from promptc.contract import parse_output
from promptc.errors import LimitExceededError, ParseError, RenderError, TimeoutError
from promptc.expression import ExpressionError, evaluate
from promptc.parser import load, parse, parse_str
from promptc.renderer import render
from promptc.schema import (
    ContractParseResult,
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
    "load",
    "parse",
    "parse_str",
    "render",
    "parse_output",
    "ParserConfig",
    "Node",
    "SourceSpan",
    "ParseError",
    "RenderError",
    "LimitExceededError",
    "TimeoutError",
    "ExpressionError",
    "evaluate",
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
    "ContractParseResult",
    "ValidationIssue",
    "ValidationReport",
]
