"""Variable substitution engine for DAG executor.

Resolves variable references in the form:
- $node-id.output.field — references to node outputs
- $input-name — references to workflow inputs
- $ENV_VAR — process environment variables on the whitelist
"""
import json
import os
import re
from typing import Any, Dict, List, Tuple, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from dag_executor.channels import ChannelStore


# Process environment variables that bash scripts may reference as `$NAME` in their
# script bodies. Kept in sync with validator.ENV_VAR_WHITELIST (validator imports
# this set). The lint pass and runtime resolver MUST agree: anything the lint lets
# through without a matching input/output/channel must resolve at runtime.
ENV_VAR_WHITELIST = frozenset({
    "PROJECT_ROOT",
    "TENANT_NAMESPACE",
    "TENANT_PROJECT",
    "TENANT_DOMAIN_PATH",
    "TENANT_DOCS_REPO",
    "TENANT_SMOKE_TEST_PATH",
    "DOCS_REPO",
    "DAILY_REPORTS_PATH",
    "DAG_EVENTS_DIR",
    "DAG_CREATE_ISSUES_BATCH",
    "DAG_DEPENDENCY_GRAPH",
    "DAG_ISSUE_LIST",
    "HOME",
    "PATH",
    "PWD",
    "USER",
    "SHELL",
})


# Awk built-in field / record variable names. When workflow authors write
# `awk '{print $NF}'` or `awk '{print $1,$3}'` inside a bash script, the
# shell-level resolver must leave those tokens alone so awk can expand them.
# Numeric field refs ($0..$9) are matched by a separate pattern.
_AWK_BUILTINS = frozenset({
    "NF", "NR", "FS", "OFS", "RS", "ORS", "FILENAME", "FNR",
})
_AWK_NUMERIC_REF = re.compile(r"^[0-9]+$")


def _is_awk_builtin(name: str) -> bool:
    """True if `name` is an awk built-in that the shell should leave literal."""
    return name in _AWK_BUILTINS or bool(_AWK_NUMERIC_REF.match(name))


class VariableResolutionError(Exception):
    """Raised when a variable reference cannot be resolved."""

    def __init__(
        self,
        message: str,
        reference: str,
        available_nodes: List[str],
        available_inputs: List[str],
        channel_version: Optional[int] = None
    ):
        super().__init__(message)
        self.reference = reference
        self.available_nodes = available_nodes
        self.available_inputs = available_inputs
        self.channel_version = channel_version


# Regex to match $variable or $node.field.nested or $function(args)
VARIABLE_PATTERN = re.compile(r'\$([a-zA-Z0-9_-]+(?:\.[a-zA-Z0-9_-]+)*)')

# Shell-style ${variable} and ${node.field.nested} forms. Workflow authors
# naturally write ${description} and ${creation_result.bug_key} inside prompts
# and scripts (matches bash's brace syntax). We normalize to $description /
# $creation_result.bug_key before the main resolver runs.
BRACED_VARIABLE_PATTERN = re.compile(r'\$\{([a-zA-Z0-9_-]+(?:\.[a-zA-Z0-9_-]+)*)\}')


def _interpolate(value: Any) -> str:
    """Render a resolved value for string interpolation inside a script.

    Strings are inserted verbatim. Booleans and None use Python-literal form
    (`True`/`False`/`None`) so SimpleEval-parsed gate/interrupt conditions
    like `$x == False` resolve cleanly. Everything else goes through
    json.dumps so bash/jq pipelines see valid JSON rather than Python's
    repr of a dict (which uses single quotes). This matters for workflows
    that pipe an upstream state channel through `jq`:
    `echo "$children_list" | jq '.issues[]'` only works if the variable
    expands to JSON, not Python-repr.
    """
    if isinstance(value, str):
        return value
    if isinstance(value, bool) or value is None:
        return repr(value)
    try:
        return json.dumps(value)
    except (TypeError, ValueError):
        return str(value)
# Regex to match callable references like $repo_path(slug)
CALLABLE_PATTERN = re.compile(r'\$([a-zA-Z0-9_-]+)\(([^)]+)\)')


def resolve_variables(
    value: Any,
    node_outputs: Dict[str, Dict[str, Any]],
    workflow_inputs: Dict[str, Any],
    channel_store: Optional["ChannelStore"] = None,
    skip_names: Optional[set[str]] = None,
) -> Any:
    """Resolve variable references in a value.

    Args:
        value: The value to resolve (can be str, dict, list, or primitive)
        node_outputs: Map of node_id -> output dict
        workflow_inputs: Map of input_name -> value
        channel_store: Optional ChannelStore for channel-based variable resolution
        skip_names: Single-segment names to leave untouched (e.g. bash-local
            variables assigned within a bash script). These pass through with
            their leading `$` intact so the subshell handles them natively.

    Returns:
        The value with all variable references resolved

    Raises:
        VariableResolutionError: If a reference cannot be resolved
    """
    if isinstance(value, str):
        return _resolve_string(value, node_outputs, workflow_inputs, channel_store, skip_names)
    elif isinstance(value, dict):
        return {k: resolve_variables(v, node_outputs, workflow_inputs, channel_store, skip_names) for k, v in value.items()}
    elif isinstance(value, list):
        return [resolve_variables(item, node_outputs, workflow_inputs, channel_store, skip_names) for item in value]
    else:
        # Primitives (int, bool, None, etc.) pass through unchanged
        return value


def _resolve_string(
    value: str,
    node_outputs: Dict[str, Dict[str, Any]],
    workflow_inputs: Dict[str, Any],
    channel_store: Optional["ChannelStore"] = None,
    skip_names: Optional[set[str]] = None,
) -> Any:
    """Resolve variable references in a string.

    If the string is a pure reference (e.g., "$node.output"), return the resolved object directly.
    If the string contains mixed content (e.g., "Hello $name"), perform string interpolation.
    Supports callable references like $repo_path(slug).
    `skip_names` is a set of single-segment names that should be left literal
    (used for bash-local variable names — the subshell handles their expansion).
    """
    skip = skip_names or set()

    # Normalize bash-style ${foo} → $foo so the rest of the resolver doesn't
    # need to duplicate regex logic. Names in `skip` are preserved verbatim so
    # bash subshells still expand their own ${local_var} as before.
    def _unbrace(m: "re.Match[str]") -> str:
        name = m.group(1)
        if name in skip:
            return m.group(0)
        return f"${name}"

    value = BRACED_VARIABLE_PATTERN.sub(_unbrace, value)

    # First check for callable patterns (like $repo_path(...))
    callable_matches = list(CALLABLE_PATTERN.finditer(value))

    # If exactly one callable match equals the entire value, return it directly
    if len(callable_matches) == 1 and callable_matches[0].group(0) == value:
        return _resolve_callable(callable_matches[0].group(1), callable_matches[0].group(2).strip(), node_outputs, workflow_inputs, channel_store)

    # Process callables first
    result = value
    for match in callable_matches:
        full_match = match.group(0)  # e.g., "$repo_path(skills)"
        func_name = match.group(1)   # e.g., "repo_path"
        arg = match.group(2).strip() # e.g., "skills"

        resolved = _resolve_callable(func_name, arg, node_outputs, workflow_inputs, channel_store)
        result = result.replace(full_match, _interpolate(resolved))

    # Now handle regular variable patterns
    matches = list(VARIABLE_PATTERN.finditer(result))

    if not matches and not callable_matches:
        # No references, return unchanged
        return value

    # Check if this is a pure reference (entire string is just the reference).
    # Pure-reference returns bypass skip_names — callers passing a bare "$foo"
    # expect substitution. skip_names only protects mixed-content strings.
    if len(matches) == 1 and matches[0].group(0) == result and not callable_matches:
        reference = matches[0].group(1)
        first_segment = reference.split(".")[0]
        if first_segment not in skip and not (
            "." not in reference and _is_awk_builtin(reference)
        ):
            return _resolve_reference(reference, node_outputs, workflow_inputs, channel_store)

    # Mixed content - perform string interpolation
    for match in matches:
        full_match = match.group(0)  # e.g., "$node.output.field"
        reference = match.group(1)    # e.g., "node.output.field"
        first_segment = reference.split(".")[0]
        # Awk built-in field refs (`$NF`, `$1`, ...) look like bare
        # single-segment refs but belong to an embedded awk program.
        # Leave them literal so awk expands them at runtime.
        if "." not in reference and _is_awk_builtin(reference):
            continue
        if first_segment in skip:
            # Bare `$channel` stays literal — the bash runner injects the
            # serialized value via env var. BUT dot-path refs like
            # `$channel.field` MUST still be substituted: env-var injection
            # gives bash the whole structured value, not the sub-field, and
            # `$channel.field` in bash would concatenate the serialized
            # value with the literal string ".field" (broken). Substitute
            # here so authors can write `${channel.field}` in bash scripts
            # and get the parsed sub-value inlined.
            if "." not in reference:
                continue  # leave `$bare_name` literal — bash will expand it
        resolved = _resolve_reference(reference, node_outputs, workflow_inputs, channel_store)
        # Convert resolved value to string for interpolation
        result = result.replace(full_match, _interpolate(resolved))

    return result



def _resolve_callable(
    func_name: str,
    arg: str,
    node_outputs: Dict[str, Dict[str, Any]],
    workflow_inputs: Dict[str, Any],
    channel_store: Optional["ChannelStore"] = None
) -> Any:
    """Resolve a callable reference like repo_path(slug).
    
    Args:
        func_name: The function name (e.g., "repo_path")
        arg: The argument to the function
        node_outputs: Available node outputs (for error context)
        workflow_inputs: Available workflow inputs (for error context)
        channel_store: Optional channel store
    
    Returns:
        The resolved value from the callable
    
    Raises:
        VariableResolutionError: If the callable is unknown or fails
    """
    if func_name == "repo_path":
        from dag_executor.repo_paths import resolve_repo_path, RepoPathError
        try:
            return resolve_repo_path(arg)
        except RepoPathError as e:
            raise VariableResolutionError(
                f"Cannot resolve $repo_path({arg}): {e}",
                f"repo_path({arg})",
                list(node_outputs.keys()),
                list(workflow_inputs.keys())
            )
    else:
        raise VariableResolutionError(
            f"Unknown callable reference: ${func_name}(...)",
            f"{func_name}({arg})",
            list(node_outputs.keys()),
            list(workflow_inputs.keys())
        )


def _resolve_reference(
    reference: str,
    node_outputs: Dict[str, Dict[str, Any]],
    workflow_inputs: Dict[str, Any],
    channel_store: Optional["ChannelStore"] = None
) -> Any:
    """Resolve a single variable reference.

    Args:
        reference: The reference path (without leading $), e.g., "node.output.field"
        node_outputs: Map of node_id -> output dict
        workflow_inputs: Map of input_name -> value
        channel_store: Optional ChannelStore for channel-based variable resolution

    Returns:
        The resolved value

    Raises:
        VariableResolutionError: If the reference cannot be resolved
    """
    parts = reference.split('.')
    channel_version: Optional[int] = None

    # Try to resolve from channel_store first (highest priority)
    if channel_store is not None:
        try:
            value, version = channel_store.read(parts[0])
            channel_version = version
            # If we have nested path segments, traverse them through the channel value
            if len(parts) > 1:
                return _traverse_path(
                    parts[1:], value, reference, node_outputs, workflow_inputs, channel_version
                )
            return value
        except KeyError:
            # Key not in channel_store, fall through to node_outputs/workflow_inputs
            pass

    # Try to resolve as node output (second priority)
    if parts[0] in node_outputs:
        return _traverse_path(
            parts[1:], node_outputs[parts[0]], reference, node_outputs, workflow_inputs, channel_version
        )

    # Try to resolve as workflow input
    if reference in workflow_inputs:
        return workflow_inputs[reference]

    # Try to resolve as nested workflow input (e.g., $config.nested)
    if parts[0] in workflow_inputs:
        return _traverse_path(
            parts[1:], workflow_inputs[parts[0]], reference, node_outputs, workflow_inputs, channel_version
        )

    # Last-resort: single-segment reference to a whitelisted process env var.
    # Matches validator.ENV_VAR_WHITELIST so lint and runtime agree.
    if len(parts) == 1 and parts[0] in ENV_VAR_WHITELIST:
        return os.environ.get(parts[0], "")

    # Hyphen-prefix handling: the validator allows $foo-bar when `foo` is a
    # valid input/node/channel by treating the hyphen as bash's implicit
    # string concatenation boundary. Mirror that here — split on the first
    # hyphen, resolve the prefix, and interpolate the rest as a literal
    # string suffix. Without this, `$epic-artifacts.json` gives a runtime
    # resolver error even though lint passed. The suffix preserves any
    # trailing segments (dots become plain string concatenation).
    if "-" in parts[0]:
        prefix, sep, first_suffix = parts[0].partition("-")
        try:
            prefix_value = _resolve_reference(prefix, node_outputs, workflow_inputs, channel_store)
        except VariableResolutionError:
            prefix_value = None
        if prefix_value is not None:
            remaining = ".".join(parts[1:])
            tail = f"{sep}{first_suffix}"
            if remaining:
                tail = f"{tail}.{remaining}"
            return f"{prefix_value}{tail}"

    # Not found - raise error with context
    available_nodes = list(node_outputs.keys())
    available_inputs = list(workflow_inputs.keys())

    error_msg = f"Cannot resolve variable reference: ${reference}\n"
    if available_nodes:
        error_msg += f"Available nodes: {', '.join(available_nodes)}\n"
    if available_inputs:
        error_msg += f"Available inputs: {', '.join(available_inputs)}"

    raise VariableResolutionError(
        error_msg, reference, available_nodes, available_inputs, channel_version
    )


def _traverse_path(
    path: List[str],
    obj: Any,
    full_reference: str,
    node_outputs: Dict[str, Dict[str, Any]],
    workflow_inputs: Dict[str, Any],
    channel_version: Optional[int] = None
) -> Any:
    """Traverse a path through nested dicts.

    Args:
        path: Remaining path segments to traverse
        obj: Current object to traverse
        full_reference: Full reference path for error messages
        node_outputs: Available node outputs (for error context)
        workflow_inputs: Available workflow inputs (for error context)
        channel_version: Optional channel version for error context

    Returns:
        The value at the path

    Raises:
        VariableResolutionError: If the path cannot be traversed
    """
    if not path:
        return obj

    if not isinstance(obj, dict):
        raise VariableResolutionError(
            f"Cannot traverse path ${full_reference}: expected dict at '{path[0]}', got {type(obj).__name__}",
            full_reference,
            list(node_outputs.keys()),
            list(workflow_inputs.keys()),
            channel_version
        )

    key = path[0]
    if key not in obj:
        available_keys = list(obj.keys()) if isinstance(obj, dict) else []
        raise VariableResolutionError(
            f"Cannot resolve ${full_reference}: key '{key}' not found. Available keys: {', '.join(available_keys)}",
            full_reference,
            list(node_outputs.keys()),
            list(workflow_inputs.keys()),
            channel_version
        )

    return _traverse_path(path[1:], obj[key], full_reference, node_outputs, workflow_inputs, channel_version)


def extract_variable_references(value: Any) -> List[Tuple[str, str]]:
    """Extract all variable references from a value for static analysis.

    Args:
        value: The value to scan (can be str, dict, list, or primitive)

    Returns:
        List of (node_id, field_path) tuples. For workflow inputs (no dots),
        field_path is empty string. For node references like $node.output.data,
        returns ("node", "output.data").
    """
    refs: List[Tuple[str, str]] = []
    _collect_references(value, refs)
    # Deduplicate while preserving order
    seen = set()
    deduplicated = []
    for ref in refs:
        if ref not in seen:
            seen.add(ref)
            deduplicated.append(ref)
    return deduplicated


def _remove_code_blocks(text: str) -> str:
    """Remove triple-backtick code blocks from text.

    Prompts often contain instructional code snippets inside ```…``` fences
    (shown to the LLM as example invocations) with variable names that are
    not resolved at workflow runtime. Triple-backtick blocks are stripped
    before extracting variable references.

    We do NOT strip indented lines as "code examples" any more: YAML block
    scalars (`script: |`, `prompt: |`) carry meaningful indentation, and
    the prior heuristic silently hid every real reference inside a prompt
    or bash script from the validator. Authors who want an indented literal
    example that shouldn't be validated can put it inside a fenced block.

    Args:
        text: Input text potentially containing code blocks

    Returns:
        Text with fenced code blocks replaced by empty strings
    """
    # Remove triple-backtick code blocks (```...```)
    return re.sub(r'```[^`]*```', '', text, flags=re.DOTALL)


def _collect_references(value: Any, refs: List[Tuple[str, str]]) -> None:
    """Recursively collect variable references from a value.

    Args:
        value: The value to scan
        refs: List to append found references to (modified in place)
    """
    if isinstance(value, str):
        # Strip fenced code blocks (see _remove_code_blocks docstring).
        filtered_str = _remove_code_blocks(value)

        # Braced refs: ${foo} / ${foo.bar} — the closing brace is a hard
        # boundary, so anything after it (including a literal `.tmp`) is NOT
        # part of the reference. We extract these separately BEFORE the
        # generic VARIABLE_PATTERN sweep, then blank out the ${...} spans so
        # the unbraced pattern can't re-match and greedily extend past the
        # closing brace.
        braced_spans: List[Tuple[int, int]] = []
        for match in BRACED_VARIABLE_PATTERN.finditer(filtered_str):
            reference = match.group(1)
            if "." not in reference and _is_awk_builtin(reference):
                continue  # awk built-in written as ${NF} — skip
            parts = reference.split(".", 1)
            node_id = parts[0]
            field_path = parts[1] if len(parts) > 1 else ""
            refs.append((node_id, field_path))
            braced_spans.append(match.span())

        if braced_spans:
            chars = list(filtered_str)
            for start, end in braced_spans:
                for i in range(start, end):
                    chars[i] = " "
            filtered_str = "".join(chars)

        for match in VARIABLE_PATTERN.finditer(filtered_str):
            reference = match.group(1)
            if "." not in reference and _is_awk_builtin(reference):
                continue  # $NF / $1 — awk built-in, not a workflow ref
            parts = reference.split(".", 1)
            node_id = parts[0]
            field_path = parts[1] if len(parts) > 1 else ""
            refs.append((node_id, field_path))
    elif isinstance(value, dict):
        for v in value.values():
            _collect_references(v, refs)
    elif isinstance(value, list):
        for item in value:
            _collect_references(item, refs)
