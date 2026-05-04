"""Pydantic v2 data models for promptc AST and tag declarations.

This module provides the typed public API layer that consumers will use.
Parser produces untyped ast_nodes.Node dataclasses; schema.py converts
those into strictly-validated pydantic models with tier classification,
path-based doc_type inference, and structural node preservation.

Note on ParseError naming: The ParseError exception already exists in
errors.py for syntax errors. This module's ParseErrorInfo is a data
class for parse-output result wrappers (consumed by contract parser).
"""
from __future__ import annotations

from typing import Any, Generic, Literal, TypeVar, Union

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator
from typing_extensions import Annotated

from promptc import ast_nodes

# TypeVar for generic ParseResult
T = TypeVar("T")


class SourceSpan(BaseModel):
    """Source location metadata matching ast_nodes.SourceSpan."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    start_line: int
    start_col: int
    end_line: int
    end_col: int

    @classmethod
    def from_ast(cls, node_span: ast_nodes.SourceSpan) -> SourceSpan:
        """Convert parser's SourceSpan to pydantic model."""
        return cls(
            start_line=node_span.start_line,
            start_col=node_span.start_col,
            end_line=node_span.end_line,
            end_col=node_span.end_col,
        )


class MetaDecl(BaseModel):
    """Frontmatter metadata from {% meta %} tag."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    doc_type: Literal["command", "skill", "reference"] | None = None
    description: str | None = None
    model: str | None = None
    owner: str | None = None
    extras: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def extract_extras(cls, data: Any) -> Any:
        """Move unknown keys into extras dict."""
        if not isinstance(data, dict):
            return data

        known_fields = {"doc_type", "description", "model", "owner", "extras"}
        extras = {}
        cleaned = {}

        for key, value in data.items():
            if key in known_fields:
                cleaned[key] = value
            else:
                extras[key] = value

        if extras:
            cleaned["extras"] = extras

        return cleaned


class InputDecl(BaseModel):
    """Typed input declaration from {% input %} tag."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    type: Literal["string", "int", "float", "bool", "list", "object"]
    required: bool = True
    default: Any = None
    description: str | None = None


class OutputDecl(BaseModel):
    """Typed output declaration from {% output %} tag."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    type: Literal["string", "int", "float", "bool", "list", "object"]
    description: str | None = None


class TextNode(BaseModel):
    """Prose text node."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["text"] = "text"
    content: str
    source_span: SourceSpan


class RawNode(BaseModel):
    """Raw block node."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["raw"] = "raw"
    content: str
    source_span: SourceSpan


class PhaseNode(BaseModel):
    """Phase block with nested children preserved."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["phase"] = "phase"
    name: str
    children: list[dict[str, Any]]
    source_span: SourceSpan


class RunNode(BaseModel):
    """Run command node (self-closing tag)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["run"] = "run"
    command: str | None = None
    prompt_file: str | None = None
    on_failure: str | None = None
    source_span: SourceSpan


class RefNode(BaseModel):
    """Reference node (self-closing tag)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["ref"] = "ref"
    file: str
    include: bool = False
    section: str | None = None
    source_span: SourceSpan


class WhenNode(BaseModel):
    """Conditional block with nested children preserved."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["when"] = "when"
    expr: str
    children: list[dict[str, Any]]
    source_span: SourceSpan


# Discriminated union of all schema nodes
SchemaNode = Annotated[
    Union[PhaseNode, RunNode, RefNode, WhenNode, TextNode, RawNode],
    Field(discriminator="kind"),
]


class Doc(BaseModel):
    """Top-level document model with tier classification."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str | None = None
    doc_type: Literal["command", "skill", "reference"] | None = None
    meta: MetaDecl | None = None
    inputs: list[InputDecl] = Field(default_factory=list)
    outputs: list[OutputDecl] = Field(default_factory=list)
    nodes: list[SchemaNode] = Field(default_factory=list)
    source_span: SourceSpan

    @computed_field  # type: ignore[misc]
    @property
    def tier(self) -> Literal["contract", "mixed", "reference"]:
        """Document tier: contract (meta+outputs), mixed (meta, no outputs), reference (no meta)."""
        if self.meta is None:
            return "reference"
        if len(self.outputs) > 0:
            return "contract"
        return "mixed"

    @computed_field  # type: ignore[misc]
    @property
    def resolved_doc_type(self) -> Literal["command", "skill", "reference"]:
        """Resolved doc_type: explicit override wins, else path heuristic."""
        if self.doc_type is not None:
            return self.doc_type

        # Path-based heuristic
        if self.path is None:
            return "reference"

        # Normalize path to posix style for cross-platform matching
        # Replace backslashes with forward slashes to handle Windows paths on Unix
        normalized = self.path.replace("\\", "/")

        if normalized.startswith("commands/"):
            return "command"
        if normalized.startswith("skills/"):
            return "skill"
        return "reference"

    @classmethod
    def from_ast(cls, doc_node: ast_nodes.Node, path: str | None = None) -> Doc:
        """Convert parser's AST node to typed Doc model."""
        meta: MetaDecl | None = None
        inputs: list[InputDecl] = []
        outputs: list[OutputDecl] = []
        nodes: list[SchemaNode] = []

        # Extract source span for the doc
        source_span = SourceSpan.from_ast(doc_node.source_span)

        # Process children nodes
        for child in doc_node.children:
            node_span = SourceSpan.from_ast(child.source_span)

            if child.kind == "meta":
                # Extract meta attributes
                meta = MetaDecl(**child.attrs)

            elif child.kind == "input":
                # Extract input declaration
                inputs.append(InputDecl(**child.attrs))

            elif child.kind == "output":
                # Extract output declaration
                outputs.append(OutputDecl(**child.attrs))

            elif child.kind == "phase":
                # Phase with preserved children
                nodes.append(
                    PhaseNode(
                        name=child.attrs.get("name", ""),
                        children=[c.to_dict() for c in child.children],
                        source_span=node_span,
                    )
                )

            elif child.kind == "run":
                # Run command node
                nodes.append(
                    RunNode(
                        command=child.attrs.get("command"),
                        prompt_file=child.attrs.get("prompt_file"),
                        on_failure=child.attrs.get("on_failure"),
                        source_span=node_span,
                    )
                )

            elif child.kind == "ref":
                # Reference node
                nodes.append(
                    RefNode(
                        file=child.attrs.get("file", ""),
                        include=child.attrs.get("include", False),
                        section=child.attrs.get("section"),
                        source_span=node_span,
                    )
                )

            elif child.kind == "when":
                # When conditional with preserved children
                nodes.append(
                    WhenNode(
                        expr=child.attrs.get("expr", ""),
                        children=[c.to_dict() for c in child.children],
                        source_span=node_span,
                    )
                )

            elif child.kind == "text":
                # Text node - content is in body field per N1 note from review
                nodes.append(
                    TextNode(
                        content=child.body or "",
                        source_span=node_span,
                    )
                )

            elif child.kind == "raw":
                # Raw node - content is in body field
                nodes.append(
                    RawNode(
                        content=child.body or "",
                        source_span=node_span,
                    )
                )

            # All other node types are ignored (defensive programming)

        return cls(
            path=path,
            doc_type=meta.doc_type if meta else None,
            meta=meta,
            inputs=inputs,
            outputs=outputs,
            nodes=nodes,
            source_span=source_span,
        )


class ParseErrorInfo(BaseModel):
    """Parse error information (renamed to avoid collision with ParseError exception)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    code: str
    message: str
    line: int | None = None
    column: int | None = None
    path: str | None = None


class ParseResult(BaseModel, Generic[T]):
    """Generic parse result wrapper."""

    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    success: bool
    value: T | None = None
    errors: list[ParseErrorInfo] = Field(default_factory=list)


class ValidationIssue(BaseModel):
    """Validation issue with severity."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    severity: Literal["error", "warning", "info"]
    code: str
    message: str
    source_span: SourceSpan | None = None


class ValidationReport(BaseModel):
    """Validation report with convenience filters."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ok: bool
    issues: list[ValidationIssue] = Field(default_factory=list)

    @property
    def errors(self) -> list[ValidationIssue]:
        """Filter issues to errors only."""
        return [issue for issue in self.issues if issue.severity == "error"]

    @property
    def warnings(self) -> list[ValidationIssue]:
        """Filter issues to warnings only."""
        return [issue for issue in self.issues if issue.severity == "warning"]
