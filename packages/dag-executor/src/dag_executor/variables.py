"""Variable substitution engine for DAG executor.

Resolves variable references in the form:
- $node-id.output.field — references to node outputs
- $input-name — references to workflow inputs
"""
import re
from typing import Any, Dict, List


class VariableResolutionError(Exception):
    """Raised when a variable reference cannot be resolved."""
    
    def __init__(self, message: str, reference: str, available_nodes: List[str], available_inputs: List[str]):
        super().__init__(message)
        self.reference = reference
        self.available_nodes = available_nodes
        self.available_inputs = available_inputs


# Regex to match $variable or $node.field.nested
VARIABLE_PATTERN = re.compile(r'\$([a-zA-Z0-9_-]+(?:\.[a-zA-Z0-9_-]+)*)')


def resolve_variables(
    value: Any,
    node_outputs: Dict[str, Dict[str, Any]],
    workflow_inputs: Dict[str, Any]
) -> Any:
    """Resolve variable references in a value.
    
    Args:
        value: The value to resolve (can be str, dict, list, or primitive)
        node_outputs: Map of node_id -> output dict
        workflow_inputs: Map of input_name -> value
    
    Returns:
        The value with all variable references resolved
    
    Raises:
        VariableResolutionError: If a reference cannot be resolved
    """
    if isinstance(value, str):
        return _resolve_string(value, node_outputs, workflow_inputs)
    elif isinstance(value, dict):
        return {k: resolve_variables(v, node_outputs, workflow_inputs) for k, v in value.items()}
    elif isinstance(value, list):
        return [resolve_variables(item, node_outputs, workflow_inputs) for item in value]
    else:
        # Primitives (int, bool, None, etc.) pass through unchanged
        return value


def _resolve_string(
    value: str,
    node_outputs: Dict[str, Dict[str, Any]],
    workflow_inputs: Dict[str, Any]
) -> Any:
    """Resolve variable references in a string.
    
    If the string is a pure reference (e.g., "$node.output"), return the resolved object directly.
    If the string contains mixed content (e.g., "Hello $name"), perform string interpolation.
    """
    matches = list(VARIABLE_PATTERN.finditer(value))
    
    if not matches:
        # No references, return unchanged
        return value
    
    # Check if this is a pure reference (entire string is just the reference)
    if len(matches) == 1 and matches[0].group(0) == value:
        # Pure reference - return the resolved object directly
        reference = matches[0].group(1)
        return _resolve_reference(reference, node_outputs, workflow_inputs)
    
    # Mixed content - perform string interpolation
    result = value
    for match in matches:
        full_match = match.group(0)  # e.g., "$node.output.field"
        reference = match.group(1)    # e.g., "node.output.field"
        resolved = _resolve_reference(reference, node_outputs, workflow_inputs)
        # Convert resolved value to string for interpolation
        result = result.replace(full_match, str(resolved))
    
    return result


def _resolve_reference(
    reference: str,
    node_outputs: Dict[str, Dict[str, Any]],
    workflow_inputs: Dict[str, Any]
) -> Any:
    """Resolve a single variable reference.
    
    Args:
        reference: The reference path (without leading $), e.g., "node.output.field"
        node_outputs: Map of node_id -> output dict
        workflow_inputs: Map of input_name -> value
    
    Returns:
        The resolved value
    
    Raises:
        VariableResolutionError: If the reference cannot be resolved
    """
    parts = reference.split('.')
    
    # Try to resolve as node output first (priority)
    if parts[0] in node_outputs:
        return _traverse_path(parts[1:], node_outputs[parts[0]], reference, node_outputs, workflow_inputs)
    
    # Try to resolve as workflow input
    if reference in workflow_inputs:
        return workflow_inputs[reference]
    
    # Try to resolve as nested workflow input (e.g., $config.nested)
    if parts[0] in workflow_inputs:
        return _traverse_path(parts[1:], workflow_inputs[parts[0]], reference, node_outputs, workflow_inputs)
    
    # Not found - raise error with context
    available_nodes = list(node_outputs.keys())
    available_inputs = list(workflow_inputs.keys())
    
    error_msg = f"Cannot resolve variable reference: ${reference}\n"
    if available_nodes:
        error_msg += f"Available nodes: {', '.join(available_nodes)}\n"
    if available_inputs:
        error_msg += f"Available inputs: {', '.join(available_inputs)}"
    
    raise VariableResolutionError(error_msg, reference, available_nodes, available_inputs)


def _traverse_path(
    path: List[str],
    obj: Any,
    full_reference: str,
    node_outputs: Dict[str, Dict[str, Any]],
    workflow_inputs: Dict[str, Any]
) -> Any:
    """Traverse a path through nested dicts.
    
    Args:
        path: Remaining path segments to traverse
        obj: Current object to traverse
        full_reference: Full reference path for error messages
        node_outputs: Available node outputs (for error context)
        workflow_inputs: Available workflow inputs (for error context)
    
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
            list(workflow_inputs.keys())
        )
    
    key = path[0]
    if key not in obj:
        available_keys = list(obj.keys()) if isinstance(obj, dict) else []
        raise VariableResolutionError(
            f"Cannot resolve ${full_reference}: key '{key}' not found. Available keys: {', '.join(available_keys)}",
            full_reference,
            list(node_outputs.keys()),
            list(workflow_inputs.keys())
        )
    
    return _traverse_path(path[1:], obj[key], full_reference, node_outputs, workflow_inputs)
