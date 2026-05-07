"""Renderer for promptc documents."""
from __future__ import annotations

import re
from typing import Any, Mapping, Optional

from promptc.errors import RenderError
from promptc.expression import ExpressionError, evaluate
from promptc.schema import (
    Doc,
    OutputDecl,
    PhaseNode,
    RawNode,
    RefNode,
    RunNode,
    TextNode,
    WhenNode,
)


def render(doc: Doc, inputs: Optional[Mapping[str, Any]] = None) -> str:
    """Render a promptc Doc to a string.

    Args:
        doc: The parsed and validated promptc document
        inputs: Optional input values for variable substitution

    Returns:
        Rendered document as a string

    Raises:
        RenderError: If required inputs are missing, type validation fails,
                     or unsupported features are encountered
    """
    # Validate and resolve inputs
    resolved_inputs = _validate_inputs(doc, inputs or {})

    # Build context for evaluation and substitution
    context = {**resolved_inputs, "inputs": resolved_inputs}

    # Render body nodes
    parts = []
    for node in doc.nodes:
        parts.append(_render_node(node, context))

    body = "".join(parts)

    # Append OUTPUT CONTRACT for contract tier
    if doc.tier == "contract" and doc.outputs:
        body += "\n\n" + _build_contract_block(doc.outputs)

    return body


def _validate_inputs(doc: Doc, inputs: Mapping[str, Any]) -> dict[str, Any]:
    """Validate inputs against input declarations.

    Reference tier (no meta) accepts any inputs without validation.
    Contract/mixed tiers validate required inputs and types.
    """
    # Reference tier: no validation
    if doc.meta is None:
        return dict(inputs)

    resolved: dict[str, Any] = {}
    missing: list[str] = []
    type_errors: list[str] = []

    for decl in doc.inputs:
        if decl.name in inputs:
            value = inputs[decl.name]
            # Type check
            if not _check_type(value, decl.type):
                type_errors.append(
                    f"{decl.name}: expected {decl.type}, got {type(value).__name__}"
                )
            resolved[decl.name] = value
        elif decl.required:
            if decl.default is not None:
                resolved[decl.name] = decl.default
            else:
                missing.append(decl.name)
        elif decl.default is not None:
            resolved[decl.name] = decl.default

    if missing or type_errors:
        raise RenderError(
            "Input validation failed", missing=missing, type_errors=type_errors
        )

    return resolved


def _check_type(value: Any, expected_type: str) -> bool:
    """Check if value matches expected type."""
    type_map: dict[str, type[Any] | tuple[type[Any], ...]] = {
        "string": str,
        "int": int,
        "float": (int, float),  # int is acceptable for float
        "bool": bool,
        "list": list,
        "object": dict,
    }
    expected = type_map.get(expected_type)
    if expected is None:
        return True
    return isinstance(value, expected)


def _render_node(node: Any, context: dict[str, Any]) -> str:
    """Render a single node."""
    if isinstance(node, TextNode):
        return _substitute_variables(node.content, context)

    elif isinstance(node, RawNode):
        # Raw nodes are emitted verbatim, no substitution
        return node.content

    elif isinstance(node, PhaseNode):
        # Check phase when condition
        if node.when:
            try:
                if not evaluate(node.when, context):
                    return ""
            except ExpressionError as e:
                raise RenderError(f"Phase when expression error: {e}")

        # Render children
        child_parts = []
        for child_dict in node.children:
            # Children are dicts from to_dict(), need to reconstruct
            child_parts.append(_render_dict_node(child_dict, context))

        body = "".join(child_parts)
        return f"## Phase: {node.name}\n\n{body}\n"

    elif isinstance(node, WhenNode):
        # Evaluate condition
        try:
            if not evaluate(node.expr, context):
                return ""
        except ExpressionError as e:
            raise RenderError(f"When expression error: {e}")

        # Render children
        child_parts = []
        for child_dict in node.children:
            child_parts.append(_render_dict_node(child_dict, context))

        return "".join(child_parts)

    elif isinstance(node, RunNode):
        return _render_run_node(node, context)

    elif isinstance(node, RefNode):
        if node.include:
            raise RenderError(
                "{% ref include=true %} is not supported in this version"
            )
        # Link mode
        if node.section:
            return f"[{node.file}#{node.section}]({node.file}#{node.section})"
        else:
            return f"[{node.file}]({node.file})"

    return ""


def _render_dict_node(node_dict: dict[str, Any], context: dict[str, Any]) -> str:
    """Render a node from dict representation (children of Phase/When)."""
    kind = node_dict.get("kind")

    if kind == "text":
        # ast_nodes use 'body' field, schema uses 'content'
        content = node_dict.get("content") or node_dict.get("body", "")
        return _substitute_variables(str(content) if content else "", context)

    elif kind == "raw":
        content = node_dict.get("content") or node_dict.get("body", "")
        return str(content) if content else ""

    # For other node types, we'd need to reconstruct them
    # For now, return empty (children of Phase/When are typically just text)
    return ""


def _render_run_node(node: RunNode, context: dict[str, Any]) -> str:
    """Render a run node in Mode-A format."""
    lines = []

    # Determine invocation form
    if node.skill:
        # Skill form
        body = _substitute_variables(node.body or "", context)
        lines.append(f"Call the {node.skill} skill:")
        lines.append("```bash")
        lines.append(f"npx tsx ~/.claude/skills/{node.skill}.ts '{body}'")
        lines.append("```")
        if node.id:
            capture_type = node.capture or "json"
            lines.append(
                f"Capture the {capture_type} output and bind it as `${node.id}`. "
                f"Downstream references like `${node.id}.{{field}}` "
                "refer to fields of that captured object."
            )

    elif node.bash:
        # Bash form
        bash_cmd = _substitute_variables(node.bash, context)
        lines.append("Execute the following bash command:")
        lines.append("```bash")
        lines.append(bash_cmd)
        lines.append("```")
        if node.id:
            capture_type = node.capture or "text"
            lines.append(
                f"Capture the {capture_type} output and bind it as `${node.id}`."
            )

    elif node.tool:
        # Tool form
        body = _substitute_variables(node.body or "", context)
        lines.append(f"Invoke the {node.tool} tool:")
        lines.append("```bash")
        lines.append(body)
        lines.append("```")
        if node.id:
            capture_type = node.capture or "json"
            lines.append(
                f"Capture the {capture_type} output and bind it as `${node.id}`."
            )

    elif node.command:
        # Command form (back-compat)
        lines.append("Execute the following command:")
        lines.append("```bash")
        lines.append(node.command)
        lines.append("```")

    elif node.prompt_file:
        # Prompt file form (back-compat)
        lines.append(
            f"Render the prompt file at `{node.prompt_file}` and execute its instructions."
        )

    return "\n".join(lines)


def _substitute_variables(text: str, context: dict[str, Any]) -> str:
    """Substitute {% $inputs.X %} and {% $run_id.field %} variables in text."""
    # Pattern: {% $name.field %} or {% $name %}
    pattern = r"\{%\s*\$([a-zA-Z_][a-zA-Z0-9_]*)(?:\.([a-zA-Z_][a-zA-Z0-9_]*))?\s*%\}"

    def replacer(match: re.Match[str]) -> str:
        var_name = match.group(1)
        field_path = match.group(2)

        # Check if var_name is in context
        if var_name == "inputs":
            # {% $inputs.field %} form
            if field_path and field_path in context.get("inputs", {}):
                value = context["inputs"][field_path]
                return str(value)
            elif field_path:
                raise RenderError(
                    f"Undeclared input reference: $inputs.{field_path}"
                )
            else:
                # {% $inputs %} without field
                return str(context.get("inputs", {}))

        elif var_name in context and field_path is None:
            # {% $name %} form where name is a declared input
            return str(context[var_name])

        elif field_path:
            # {% $run_id.field %} form - not supported in Mode A
            raise RenderError(
                "Mode-B run_context substitution is not supported; "
                f"{{% ${var_name}.{field_path} %}} requires dag-executor integration"
            )

        else:
            # Unknown variable
            raise RenderError(f"Undeclared input reference: ${var_name}")

    return re.sub(pattern, replacer, text)


def _build_contract_block(outputs: list[OutputDecl]) -> str:
    """Build the OUTPUT CONTRACT block for contract-tier documents."""
    lines = [
        "## OUTPUT CONTRACT",
        "",
        "Emit the following fields in your response:",
        "",
    ]

    for output in outputs:
        if output.description:
            lines.append(f"- `{output.name}` ({output.type}): {output.description}")
        else:
            lines.append(f"- `{output.name}` ({output.type})")

    return "\n".join(lines)
