"""Renderer for promptc documents."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal, Mapping, Optional

from promptc.config import ParserConfig
from promptc.errors import RenderError
from promptc.expression import ExpressionError, evaluate
from promptc.resolver import resolve_command, resolve_file, resolve_skill
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


def render(
    doc: Doc,
    inputs: Optional[Mapping[str, Any]] = None,
    config: Optional[ParserConfig] = None,
    *,
    mode: Literal["a", "b"] = "a",
) -> str:
    """Render a promptc Doc to a string.

    Args:
        doc: The parsed and validated promptc document
        inputs: Optional input values for variable substitution
        config: Optional parser configuration (defaults to ParserConfig())
        mode: Rendering mode. "a" (default) emits run blocks as LLM instructions;
              "b" strips run blocks and preserves unbound $run_id.field refs as literals.

    Returns:
        Rendered document as a string

    Raises:
        RenderError: If required inputs are missing, type validation fails,
                     or unsupported features are encountered
    """
    # Validate and resolve inputs
    resolved_inputs = _validate_inputs(doc, inputs or {})

    # Build context for evaluation and substitution
    context = {
        **resolved_inputs,
        "inputs": resolved_inputs,
        "_doc": doc,  # Internal: pass doc for ref resolution
        "_config": config or ParserConfig(),  # Internal: use provided or default config
        "_include_stack": [doc.path] if doc.path else [],  # Internal: track include chain
        "_mode": mode,  # Internal: rendering mode
    }

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
        # In Mode-B, strip run blocks entirely
        mode = context.get("_mode", "a")
        if mode == "b":
            return ""
        return _render_run_node(node, context)

    elif isinstance(node, RefNode):
        doc = context.get("_doc")
        config = context.get("_config", ParserConfig())
        base_path = Path(doc.path).parent if doc and doc.path else None

        # Resolve the target
        if node.command:
            resolved = resolve_command(node.command, config, base_path)
            if resolved is None:
                raise RenderError(
                    f"Command reference target not found: {node.command}",
                    path=doc.path if doc else None,
                )
            target = str(resolved)
            label = node.command
        elif node.skill:
            resolved = resolve_skill(node.skill, config, base_path)
            if resolved is None:
                raise RenderError(
                    f"Skill reference target not found: {node.skill}",
                    path=doc.path if doc else None,
                )
            target = str(resolved)
            label = node.skill
        elif node.file:
            try:
                resolved = resolve_file(node.file, base_path)
            except ValueError as e:
                # Boundary validation failure (e.g., absolute path outside project root)
                raise RenderError(
                    str(e),
                    path=doc.path if doc else None,
                )
            if resolved is None:
                # If include mode, this is an error
                if node.include:
                    raise RenderError(
                        f"File reference target not found: {node.file}",
                        path=doc.path if doc else None,
                    )
                # For link mode with file=, be lenient and just use the spec
                target = node.file
            else:
                target = str(resolved)
            label = node.file
        else:
            # Should not happen due to schema validation
            raise RenderError("RefNode has no target (file/command/skill)")

        # Include mode - recursively render the target file
        if node.include:
            # Get include stack and depth from context
            include_stack = context.get("_include_stack", [])
            current_depth = len(include_stack)

            # Check max depth
            if current_depth >= config.max_include_depth:
                chain = include_stack + [target]
                raise RenderError(
                    f"Include depth exceeded (max {config.max_include_depth})",
                    path=doc.path if doc else None,
                    include_chain=chain,
                )

            # Check for cycles
            if target in include_stack:
                chain = include_stack + [target]
                raise RenderError(
                    "Include cycle detected",
                    path=doc.path if doc else None,
                    include_chain=chain,
                )

            # Read and parse the target file
            try:
                from promptc import parse_str
                target_path = Path(target)
                target_content = target_path.read_text()
                target_ast = parse_str(target_content, path=target)
                target_doc = Doc.from_ast(target_ast, path=target)

                # Create new context with updated include stack
                new_context = {
                    **context,
                    "_doc": target_doc,
                    "_include_stack": include_stack + [target],
                }

                # Recursively render the target document
                parts = []
                for target_node in target_doc.nodes:
                    parts.append(_render_node(target_node, new_context))

                return "".join(parts)

            except FileNotFoundError:
                raise RenderError(
                    f"Include target not found: {target}",
                    path=doc.path if doc else None,
                )

        # Link mode - build markdown link
        if node.section:
            return f"[{label}#{node.section}]({target}#{node.section})"
        else:
            return f"[{label}]({target})"

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

    elif kind == "run":
        # Reconstruct RunNode from AST dict representation
        from promptc.schema import RunNode
        # Extract attributes from attrs dict
        attrs = node_dict.get("attrs", {})
        # Assemble body from text children (paired form)
        children = node_dict.get("children", [])
        body_parts = [c.get("body", "") for c in children if c.get("kind") == "text"]
        body_text = "".join(body_parts).strip() if body_parts else None

        # Build RunNode with extracted data
        run_node = RunNode(
            skill=attrs.get("skill"),
            tool=attrs.get("tool"),
            bash=attrs.get("bash"),
            command=attrs.get("command"),
            prompt_file=attrs.get("prompt_file"),
            id=attrs.get("id"),
            capture=attrs.get("capture"),
            timeout_ms=attrs.get("timeout_ms"),
            on_failure=attrs.get("on_failure"),
            body=body_text,
            source_span=node_dict.get("source_span", {}),
        )
        return _render_run_node(run_node, context)

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
            # {% $run_id.field %} form
            mode = context.get("_mode", "a")
            if mode == "b":
                # Mode-B: preserve as literal text
                return f"${var_name}.{field_path}"
            else:
                # Mode-A: not supported
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
