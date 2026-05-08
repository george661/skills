"""Tier-aware validation rule engine for promptc AST documents.

# Adding a new tier? Audit every rule in RULES list for scope applicability.
# A new tier silently inherits "unscoped" behavior from rules that use
# scope=ALL_TIERS, which is almost certainly wrong without explicit review.
"""
from __future__ import annotations

import ast
import multiprocessing
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Literal, Optional

from pydantic import ValidationError

from promptc.ast_nodes import Node
from promptc.ast_nodes import SourceSpan as AstSourceSpan
from promptc.config import ParserConfig
from promptc.errors import LimitExceededError, ParseError
from promptc.expression import validate_expr
from promptc.parser import Parser, parse_str
from promptc.resolver import resolve_command, resolve_file, resolve_skill
from promptc.schema import (
    Doc,
    PhaseNode,
    RawNode,
    RefNode,
    RunNode,
    TextNode,
    ValidationIssue,
    ValidationReport,
    WhenNode,
)

Tier = Literal["contract", "mixed", "reference"]
ALL_TIERS: frozenset[Tier] = frozenset({"contract", "mixed", "reference"})
CONTRACT_ONLY: frozenset[Tier] = frozenset({"contract"})
CONTRACT_OR_MIXED: frozenset[Tier] = frozenset({"contract", "mixed"})
REFERENCE_ONLY: frozenset[Tier] = frozenset({"reference"})

# Synthetic payload for ReDoS probe — classic trigger for (a+)+ / (a|a)*
_REDOS_PROBE = "a" * 64 + "!"

# Regex patterns used by reference-scanning rules
_INPUT_REF = re.compile(r"\{%\s*\$inputs\.([a-zA-Z_][a-zA-Z0-9_]*)")
_RUN_ID_REF = re.compile(r"\{%\s*\$(?!inputs\b)([a-zA-Z_][a-zA-Z0-9_]*)\.([a-zA-Z_][a-zA-Z0-9_]*)")


@dataclass
class _RuleCtx:
    """Shared state for rules (pre-computed once to avoid re-walking the AST)."""
    all_text: str
    all_run_ids: set[str]
    input_names: set[str]
    output_names: set[str]
    config: ParserConfig
    base_path: Optional[Path]


# ---- public API ----

def validate(doc: Doc, *, config: Optional[ParserConfig] = None) -> ValidationReport:
    """Run the rule engine on an already-loaded Doc. Never raises."""
    cfg = config or ParserConfig()
    ctx = _build_ctx(doc, cfg)
    issues: list[ValidationIssue] = []

    # ReDoS probe runs first — cheap and catches pathological input patterns
    # before the other rules loop over them.
    issues.extend(_probe_redos(doc, cfg))

    # Rule loop
    for rule_fn, scope in RULES:
        if doc.tier in scope:
            issues.extend(rule_fn(doc, ctx))

    has_error = any(i.severity == "error" for i in issues)
    return ValidationReport(ok=not has_error, issues=issues)


def validate_path(
    path: str | Path,
    *,
    config: Optional[ParserConfig] = None,
) -> ValidationReport:
    """Load-and-validate pipeline. Catches parse/schema errors and returns
    them as a ValidationReport rather than raising.

    Reference-tier heuristic for inline-tag prose (docs/promptc-spec.md):
    When parse fails AND the path does NOT start with 'commands/' or 'skills/'
    and does NOT declare doc_type in frontmatter, we treat it as reference
    tier and downgrade the parse error to a warning so the repo-tree smoke
    test passes on docs that quote promptc syntax inside prose.
    """
    cfg = config or ParserConfig()
    path_obj = Path(path)
    src_path = str(path)

    try:
        source = path_obj.read_text(encoding="utf-8")
    except OSError as e:
        return ValidationReport(
            ok=False,
            issues=[ValidationIssue(severity="error", code="FILE_READ_ERROR",
                                    message=str(e), source_span=None)],
        )

    try:
        children = Parser(cfg).parse(source, path=src_path)
        lines = source.split("\n")
        doc_node = Node(
            kind="document", attrs={}, children=children, body=None,
            source_span=AstSourceSpan(1, 1, len(lines), len(lines[-1]) if lines else 1),
        )
        doc = Doc.from_ast(doc_node, path=src_path)
    except (ParseError, LimitExceededError, ValidationError) as e:
        severity, code = _classify_parse_failure_for_path(src_path, type(e).__name__)
        return ValidationReport(
            ok=(severity != "error"),
            issues=[ValidationIssue(
                severity=severity, code=code, message=str(e), source_span=None,
            )],
        )

    return validate(doc, config=cfg)


# ---- parse-failure classification ----

def _classify_parse_failure_for_path(
    path: str, error_type: str,
) -> tuple[Literal["error", "warning"], str]:
    """Decide severity for a parse failure based on the file's likely tier.

    Commands and skills are expected to parse cleanly (error on parse failure).
    Other files (docs/, templates/, etc.) are reference-tier (warning on parse failure).

    We check if the path contains /commands/ or /skills/ as a directory in the
    final project-relative portion (not in parent directories like worktree names).
    """
    from pathlib import Path

    # Convert to Path and get the parts
    path_obj = Path(path)
    parts = list(path_obj.parts)

    # Find the last occurrence of certain known repo-root indicators
    # If we find 'commands' or 'skills' AFTER any of these, it's a project directory
    root_indicators = {'packages', 'src', '.git', 'worktrees'}
    last_root_idx = -1
    for i, part in enumerate(parts):
        if part in root_indicators or part.startswith('GW-'):
            last_root_idx = i

    # Check the parts after the last root indicator
    relevant_parts = parts[last_root_idx + 1:] if last_root_idx >= 0 else parts

    # If commands or skills appears in the relevant portion, it's contract-tier
    if "commands" in relevant_parts or "skills" in relevant_parts:
        return ("error", f"PARSE_{error_type.upper()}")

    # Everything else is reference-tier (docs, templates, etc.)
    return ("warning", f"PARSE_{error_type.upper()}_REFERENCE")


# ---- _RuleCtx construction ----

def _build_ctx(doc: Doc, cfg: ParserConfig) -> _RuleCtx:
    """Pre-compute traversal state once."""
    text_parts: list[str] = []
    run_ids: set[str] = set()

    for node in doc.nodes:
        if isinstance(node, TextNode):
            text_parts.append(node.content)
        elif isinstance(node, RawNode):
            pass
        elif isinstance(node, RunNode):
            if node.id:
                run_ids.add(node.id)
        elif isinstance(node, (PhaseNode, WhenNode)):
            for child_dict in node.children:
                _collect_from_dict(child_dict, text_parts, run_ids)

    base_path = Path(doc.path).parent if doc.path else None
    return _RuleCtx(
        all_text="\n".join(text_parts),
        all_run_ids=run_ids,
        input_names={i.name for i in doc.inputs},
        output_names={o.name for o in doc.outputs},
        config=cfg,
        base_path=base_path,
    )


def _collect_from_dict(
    node_dict: dict[str, Any], text_parts: list[str], run_ids: set[str],
) -> None:
    """Walk the ast_nodes-dict representation used for phase/when children."""
    kind = node_dict.get("kind")
    if kind == "text":
        body = node_dict.get("body") or node_dict.get("content") or ""
        text_parts.append(str(body))
    elif kind == "run":
        rid = node_dict.get("attrs", {}).get("id")
        if rid:
            run_ids.add(rid)
    for child in node_dict.get("children", []) or []:
        _collect_from_dict(child, text_parts, run_ids)


# ---- ReDoS probe ----

def _regex_match_worker(pattern: str, payload: str) -> None:
    """Worker function for regex matching in subprocess."""
    compiled = re.compile(pattern)
    compiled.match(payload)


def _probe_redos(doc: Doc, cfg: ParserConfig) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for inp in doc.inputs:
        if not inp.pattern:
            continue
        try:
            re.compile(inp.pattern)
        except re.error as e:
            issues.append(ValidationIssue(
                severity="error", code="REDOS_INVALID_REGEX",
                message=f"input '{inp.name}' pattern is not a valid regex: {e}",
                source_span=None,
            ))
            continue
        # Use multiprocessing.Pool to ensure timeout kills the worker process
        with multiprocessing.Pool(processes=1) as pool:
            result = pool.apply_async(_regex_match_worker, (inp.pattern, _REDOS_PROBE))
            try:
                result.get(timeout=cfg.regex_timeout_ms / 1000.0)
            except multiprocessing.TimeoutError:
                pool.terminate()  # Kill the worker process
                pool.join()
                issues.append(ValidationIssue(
                    severity="error", code="REDOS_PROBE",
                    message=(
                        f"input '{inp.name}' pattern {inp.pattern!r} exceeded "
                        f"{cfg.regex_timeout_ms}ms on synthetic payload — "
                        "potential catastrophic backtracking"
                    ),
                    source_span=None,
                ))
    return issues


# ---- rule implementations ----

def _rule_contract_requires_outputs(doc: Doc, ctx: _RuleCtx) -> list[ValidationIssue]:
    """[C] Contract-tier command must have at least one output."""
    if doc.resolved_doc_type == "command" and len(doc.outputs) == 0:
        return [ValidationIssue(
            severity="error",
            code="C_CONTRACT_NO_OUTPUT",
            message="contract-tier command must declare at least one {% output %}",
            source_span=None,
        )]
    return []


def _rule_contract_unused_outputs_in_prose(doc: Doc, ctx: _RuleCtx) -> list[ValidationIssue]:
    """[C] Output declared but not mentioned in prose (warning)."""
    issues: list[ValidationIssue] = []
    for out in doc.outputs:
        if out.name.lower() not in ctx.all_text.lower():
            issues.append(ValidationIssue(
                severity="warning",
                code="C_OUTPUT_NOT_MENTIONED",
                message=f"output '{out.name}' is declared but not mentioned in prose",
                source_span=None,
            ))
    return issues


def _rule_meta_required_attributes(doc: Doc, ctx: _RuleCtx) -> list[ValidationIssue]:
    """[M] Meta must have required attributes."""
    issues: list[ValidationIssue] = []
    if not doc.meta or not doc.meta.description:
        issues.append(ValidationIssue(
            severity="error",
            code="M_META_MISSING_DESCRIPTION",
            message="meta.description is required",
            source_span=None,
        ))
    # If under commands/, must have doc_type
    if doc.path and ("/commands/" in doc.path or doc.path.startswith("commands/")):
        if not doc.meta or not doc.meta.doc_type:
            issues.append(ValidationIssue(
                severity="error",
                code="M_META_MISSING_DOC_TYPE",
                message="meta.doc_type is required for files under commands/",
                source_span=None,
            ))
    return issues


def _rule_duplicate_input_output_names(doc: Doc, ctx: _RuleCtx) -> list[ValidationIssue]:
    """Duplicate name across inputs or outputs."""
    issues: list[ValidationIssue] = []
    all_names = [i.name for i in doc.inputs] + [o.name for o in doc.outputs]
    counts = Counter(all_names)
    for name, count in counts.items():
        if count > 1:
            issues.append(ValidationIssue(
                severity="error",
                code="DUP_NAME",
                message=f"duplicate name '{name}' across inputs/outputs (appears {count} times)",
                source_span=None,
            ))
    return issues


def _rule_duplicate_phase_run_ids(doc: Doc, ctx: _RuleCtx) -> list[ValidationIssue]:
    """Duplicate id across phases/runs."""
    issues: list[ValidationIssue] = []
    all_ids: list[str] = []

    for node in doc.nodes:
        if isinstance(node, PhaseNode) and node.name:
            all_ids.append(node.name)
        elif isinstance(node, RunNode) and node.id:
            all_ids.append(node.id)
        elif isinstance(node, (PhaseNode, WhenNode)):
            for child_dict in node.children:
                _collect_ids_from_dict(child_dict, all_ids)

    counts = Counter(all_ids)
    for id_val, count in counts.items():
        if count > 1:
            issues.append(ValidationIssue(
                severity="error",
                code="DUP_ID",
                message=f"duplicate id '{id_val}' across phases/runs (appears {count} times)",
                source_span=None,
            ))
    return issues


def _collect_ids_from_dict(node_dict: dict[str, Any], all_ids: list[str]) -> None:
    """Helper for collecting IDs from nested structures."""
    kind = node_dict.get("kind")
    if kind == "phase":
        name = node_dict.get("attrs", {}).get("name")
        if name:
            all_ids.append(name)
    elif kind == "run":
        rid = node_dict.get("attrs", {}).get("id")
        if rid:
            all_ids.append(rid)
    for child in node_dict.get("children", []) or []:
        _collect_ids_from_dict(child, all_ids)


def _rule_unresolved_input_refs(doc: Doc, ctx: _RuleCtx) -> list[ValidationIssue]:
    """{% $inputs.X %} with no declared input."""
    issues: list[ValidationIssue] = []
    if not ctx.input_names:
        return []

    refs = _INPUT_REF.findall(ctx.all_text)
    for ref in refs:
        if ref not in ctx.input_names:
            issues.append(ValidationIssue(
                severity="error",
                code="UNRESOLVED_INPUT_REF",
                message=f"reference to undefined input: $inputs.{ref}",
                source_span=None,
            ))
    return issues


def _rule_unresolved_run_id_refs(doc: Doc, ctx: _RuleCtx) -> list[ValidationIssue]:
    """{% $Y.field %} where Y is not a declared run id."""
    issues: list[ValidationIssue] = []
    refs = _RUN_ID_REF.findall(ctx.all_text)
    for run_id, field in refs:
        if run_id not in ctx.all_run_ids:
            issues.append(ValidationIssue(
                severity="error",
                code="UNRESOLVED_RUN_ID_REF",
                message=f"reference to undefined run id: ${run_id}.{field}",
                source_span=None,
            ))
    return issues


def _rule_invalid_when_expressions(doc: Doc, ctx: _RuleCtx) -> list[ValidationIssue]:
    """Invalid {% when %} expression."""
    issues: list[ValidationIssue] = []
    known_names = ctx.input_names | ctx.all_run_ids | {"inputs"}

    # Collect all when expressions from nodes
    when_exprs: list[str] = []
    for node in doc.nodes:
        if isinstance(node, WhenNode):
            when_exprs.append(node.expr)
            for child_dict in node.children:
                _collect_when_from_dict(child_dict, when_exprs)
        elif isinstance(node, PhaseNode):
            if node.when:
                when_exprs.append(node.when)
            for child_dict in node.children:
                _collect_when_from_dict(child_dict, when_exprs)

    for expr in when_exprs:
        expr_issues = validate_expr(expr, known_names)
        for msg in expr_issues:
            issues.append(ValidationIssue(
                severity="error",
                code="INVALID_WHEN",
                message=f"invalid when expression: {msg}",
                source_span=None,
            ))
    return issues


def _collect_when_from_dict(node_dict: dict[str, Any], when_exprs: list[str]) -> None:
    """Helper for collecting when expressions from nested structures."""
    kind = node_dict.get("kind")
    if kind == "when":
        expr = node_dict.get("attrs", {}).get("expr")
        if expr:
            when_exprs.append(expr)
    elif kind == "phase":
        when = node_dict.get("attrs", {}).get("when")
        if when:
            when_exprs.append(when)
    for child in node_dict.get("children", []) or []:
        _collect_when_from_dict(child, when_exprs)


def _rule_dangling_run_skill_targets(doc: Doc, ctx: _RuleCtx) -> list[ValidationIssue]:
    """{% run skill=X %} unresolved."""
    issues: list[ValidationIssue] = []
    for node in doc.nodes:
        if hasattr(node, "kind") and node.kind == "run" and hasattr(node, "skill") and node.skill:
            resolved = resolve_skill(node.skill, ctx.config, ctx.base_path)
            if not resolved:
                issues.append(ValidationIssue(
                    severity="error",
                    code="DANGLING_SKILL",
                    message=f"cannot resolve skill: {node.skill}",
                    source_span=None,
                ))
    return issues


def _rule_dangling_ref_targets(doc: Doc, ctx: _RuleCtx) -> list[ValidationIssue]:
    """{% ref ... %} unresolved."""
    issues: list[ValidationIssue] = []
    for node in doc.nodes:
        if hasattr(node, "kind") and node.kind == "ref":
            if hasattr(node, "command") and node.command:
                resolved = resolve_command(node.command, ctx.config, ctx.base_path)
                if not resolved:
                    issues.append(ValidationIssue(
                        severity="error",
                        code="DANGLING_REF",
                        message=f"cannot resolve command: {node.command}",
                        source_span=None,
                    ))
            elif hasattr(node, "skill") and node.skill:
                resolved = resolve_skill(node.skill, ctx.config, ctx.base_path)
                if not resolved:
                    issues.append(ValidationIssue(
                        severity="error",
                        code="DANGLING_REF",
                        message=f"cannot resolve skill: {node.skill}",
                        source_span=None,
                    ))
            elif hasattr(node, "file") and node.file:
                try:
                    resolved = resolve_file(node.file, ctx.base_path)
                    if not resolved:
                        issues.append(ValidationIssue(
                            severity="error",
                            code="DANGLING_REF",
                            message=f"cannot resolve file: {node.file}",
                            source_span=None,
                        ))
                except ValueError as e:
                    issues.append(ValidationIssue(
                        severity="error",
                        code="DANGLING_REF",
                        message=f"invalid file reference: {e}",
                        source_span=None,
                    ))
    return issues


def _rule_cyclic_or_deep_includes(doc: Doc, ctx: _RuleCtx) -> list[ValidationIssue]:
    """Cycle OR depth > max in include graph."""
    if not doc.path:
        return []

    def walk_includes(path: Path, stack: list[str], cfg: ParserConfig) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        path_str = str(path)

        if path_str in stack:
            issues.append(ValidationIssue(
                severity="error",
                code="CYCLIC_INCLUDE",
                message=f"cyclic include detected: {' -> '.join(stack + [path_str])}",
                source_span=None,
            ))
            return issues

        if len(stack) > cfg.max_include_depth:
            issues.append(ValidationIssue(
                severity="error",
                code="INCLUDE_TOO_DEEP",
                message=f"include depth {len(stack)} exceeds maximum {cfg.max_include_depth}",
                source_span=None,
            ))
            return issues

        try:
            source = path.read_text(encoding="utf-8")
            doc_node = parse_str(source, path=path_str)
            # parse_str returns a Node with children
            parsed_doc = Doc.from_ast(doc_node, path=path_str)
        except Exception:
            return []

        # Find ref nodes with include=true in the parsed doc
        for node in parsed_doc.nodes:
            if isinstance(node, RefNode) and node.include and node.file is not None:
                try:
                    resolved = resolve_file(node.file, path.parent)
                    if resolved:
                        issues.extend(walk_includes(resolved, stack + [path_str], cfg))
                except ValueError:
                    pass

        return issues

    return walk_includes(Path(doc.path), [], ctx.config)


def _rule_missing_required_tag_attributes(doc: Doc, ctx: _RuleCtx) -> list[ValidationIssue]:
    """Missing required attribute on any tag."""
    issues: list[ValidationIssue] = []

    for node in doc.nodes:
        kind = node.kind if hasattr(node, "kind") else None
        if kind == "phase":
            if not hasattr(node, "name") or not node.name:
                issues.append(ValidationIssue(
                    severity="error",
                    code="MISSING_REQUIRED_ATTR",
                    message="{% phase %} tag requires 'name' attribute",
                    source_span=None,
                ))
        elif kind == "when":
            if not hasattr(node, "expr") or not node.expr:
                issues.append(ValidationIssue(
                    severity="error",
                    code="MISSING_REQUIRED_ATTR",
                    message="{% when %} tag requires 'expr' attribute",
                    source_span=None,
                ))
        elif kind == "run":
            has_target = (
                (hasattr(node, "skill") and node.skill) or
                (hasattr(node, "tool") and node.tool) or
                (hasattr(node, "bash") and node.bash)
            )
            if not has_target:
                issues.append(ValidationIssue(
                    severity="error",
                    code="MISSING_REQUIRED_ATTR",
                    message="{% run %} tag requires one of: skill, tool, or bash",
                    source_span=None,
                ))
        elif kind == "ref":
            has_target = (
                (hasattr(node, "file") and node.file) or
                (hasattr(node, "command") and node.command) or
                (hasattr(node, "skill") and node.skill)
            )
            if not has_target:
                issues.append(ValidationIssue(
                    severity="error",
                    code="MISSING_REQUIRED_ATTR",
                    message="{% ref %} tag requires one of: file, command, or skill",
                    source_span=None,
                ))

    return issues


def _rule_enum_without_values(doc: Doc, ctx: _RuleCtx) -> list[ValidationIssue]:
    """Enum type with no values."""
    issues: list[ValidationIssue] = []
    for inp in doc.inputs:
        if inp.type == "enum" and not inp.values:
            issues.append(ValidationIssue(
                severity="error",
                code="ENUM_NO_VALUES",
                message=f"input '{inp.name}' has type=enum but no values list",
                source_span=None,
            ))
    for out in doc.outputs:
        if out.type == "enum" and not out.values:
            issues.append(ValidationIssue(
                severity="error",
                code="ENUM_NO_VALUES",
                message=f"output '{out.name}' has type=enum but no values list",
                source_span=None,
            ))
    return issues


def _rule_inputs_not_referenced(doc: Doc, ctx: _RuleCtx) -> list[ValidationIssue]:
    """Input declared but never referenced (warning)."""
    issues: list[ValidationIssue] = []
    referenced = {n for n in _INPUT_REF.findall(ctx.all_text)}
    for inp in doc.inputs:
        if inp.name not in referenced:
            issues.append(ValidationIssue(
                severity="warning",
                code="INPUT_UNREFERENCED",
                message=f"input '{inp.name}' is declared but never referenced",
                source_span=None,
            ))
    return issues


def _rule_empty_phases(doc: Doc, ctx: _RuleCtx) -> list[ValidationIssue]:
    """Phase with no body (warning)."""
    issues: list[ValidationIssue] = []
    for node in doc.nodes:
        if isinstance(node, PhaseNode):
            if not node.children or all(
                (c.get("kind") == "text" and not (c.get("body") or c.get("content", "")).strip())
                for c in node.children
            ):
                issues.append(ValidationIssue(
                    severity="warning",
                    code="EMPTY_PHASE",
                    message=f"phase '{node.name}' has no body or only whitespace",
                    source_span=None,
                ))
    return issues


def _rule_constant_when_expressions(doc: Doc, ctx: _RuleCtx) -> list[ValidationIssue]:
    """Constant when (always true/false) - warning."""
    issues: list[ValidationIssue] = []

    when_exprs: list[str] = []
    for node in doc.nodes:
        kind = node.kind if hasattr(node, "kind") else None
        if kind == "when" and hasattr(node, "expr"):
            when_exprs.append(node.expr)
        elif kind == "phase" and hasattr(node, "when") and node.when:
            when_exprs.append(node.when)

    for expr in when_exprs:
        try:
            tree = ast.parse(expr, mode="eval")
            has_names = any(isinstance(n, ast.Name) for n in ast.walk(tree))
            if not has_names:
                issues.append(ValidationIssue(
                    severity="warning",
                    code="CONSTANT_WHEN",
                    message=f"when expression '{expr}' is constant (contains no variables)",
                    source_span=None,
                ))
        except SyntaxError:
            pass

    return issues


def _rule_reference_tier_uses_inputs_without_decl(doc: Doc, ctx: _RuleCtx) -> list[ValidationIssue]:
    """Reference-tier uses $inputs.X with no declared input (warning)."""
    issues: list[ValidationIssue] = []
    if not ctx.input_names:
        refs = _INPUT_REF.findall(ctx.all_text)
        if refs:
            issues.append(ValidationIssue(
                severity="warning",
                code="REF_TIER_UNDECLARED_INPUTS",
                message="reference-tier doc uses $inputs.* but declares no inputs",
                source_span=None,
            ))
    return issues


# ---- RULES list ----

RULES: list[tuple[Callable[[Doc, _RuleCtx], list[ValidationIssue]], frozenset[Tier]]] = [
    # [C] rules - apply to commands to enforce contract-tier requirements
    # Fires for commands without outputs (which are mixed-tier by definition)
    (_rule_contract_requires_outputs, CONTRACT_OR_MIXED),
    (_rule_contract_unused_outputs_in_prose, CONTRACT_ONLY),

    # [M] rules
    (_rule_meta_required_attributes, CONTRACT_OR_MIXED),

    # Unscoped errors
    (_rule_duplicate_input_output_names, ALL_TIERS),
    (_rule_duplicate_phase_run_ids, ALL_TIERS),
    (_rule_unresolved_input_refs, ALL_TIERS),
    (_rule_unresolved_run_id_refs, ALL_TIERS),
    (_rule_invalid_when_expressions, ALL_TIERS),
    (_rule_dangling_run_skill_targets, ALL_TIERS),
    (_rule_dangling_ref_targets, ALL_TIERS),
    (_rule_cyclic_or_deep_includes, ALL_TIERS),
    (_rule_missing_required_tag_attributes, ALL_TIERS),
    (_rule_enum_without_values, ALL_TIERS),

    # Unscoped warnings
    (_rule_inputs_not_referenced, ALL_TIERS),
    (_rule_empty_phases, ALL_TIERS),
    (_rule_constant_when_expressions, ALL_TIERS),

    # Reference-only warnings
    (_rule_reference_tier_uses_inputs_without_decl, REFERENCE_ONLY),
]
