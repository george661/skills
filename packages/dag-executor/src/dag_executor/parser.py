"""YAML workflow parser with schema validation."""
from pathlib import Path
from typing import Dict, List

import yaml
from pydantic import ValidationError

from dag_executor.schema import WorkflowDef


def get_node_lines(workflow: WorkflowDef) -> Dict[str, int]:
    """Get the YAML line numbers for each node in a workflow.

    Args:
        workflow: WorkflowDef instance

    Returns:
        Dict mapping node_id to line number (1-indexed)
    """
    return workflow._node_lines


def load_workflow(yaml_path: str) -> WorkflowDef:
    """Load and validate a workflow definition from a YAML file.

    Args:
        yaml_path: Path to the workflow YAML file

    Returns:
        Validated WorkflowDef object (with line numbers tracked internally)

    Raises:
        FileNotFoundError: If the YAML file does not exist
        ValueError: If the YAML is invalid or contains duplicate node IDs
        ValidationError: If the workflow definition fails schema validation
    """
    path = Path(yaml_path)
    if not path.exists():
        raise FileNotFoundError(f"Workflow file not found: {yaml_path}")

    yaml_content = path.read_text()
    return load_workflow_from_string(yaml_content)


def load_workflow_from_string(yaml_string: str) -> WorkflowDef:
    """Load and validate a workflow definition from a YAML string.

    Args:
        yaml_string: YAML content as string

    Returns:
        Validated WorkflowDef object (with line numbers tracked internally)

    Raises:
        ValueError: If the YAML is invalid or contains duplicate node IDs
        ValidationError: If the workflow definition fails schema validation
    """
    if not yaml_string or not yaml_string.strip():
        raise ValueError("YAML string cannot be empty")

    # First pass: extract line numbers for each node
    node_lines: Dict[str, int] = {}
    try:
        # Use yaml.compose to get the node tree with line marks
        import yaml as yaml_module
        loader = yaml_module.SafeLoader(yaml_string)
        try:
            doc = loader.get_single_node()
            if doc and isinstance(doc, yaml_module.MappingNode):
                # Find the 'nodes' key
                for key_node, value_node in doc.value:
                    if isinstance(key_node, yaml_module.ScalarNode) and key_node.value == 'nodes':
                        # value_node should be a sequence of node definitions
                        if isinstance(value_node, yaml_module.SequenceNode):
                            for node_item in value_node.value:
                                if isinstance(node_item, yaml_module.MappingNode):
                                    # Extract node id and line number
                                    node_id = None
                                    for nk, nv in node_item.value:
                                        if isinstance(nk, yaml_module.ScalarNode) and nk.value == 'id':
                                            if isinstance(nv, yaml_module.ScalarNode):
                                                node_id = nv.value
                                                break
                                    if node_id and node_item.start_mark:
                                        # Line numbers are 0-indexed, convert to 1-indexed
                                        node_lines[node_id] = node_item.start_mark.line + 1
        finally:
            loader.dispose()  # type: ignore[no-untyped-call]
    except Exception:
        # If line extraction fails, continue without line numbers
        pass

    # Second pass: normal parsing
    try:
        data = yaml.safe_load(yaml_string)
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid YAML syntax: {e}") from e

    if not isinstance(data, dict):
        raise ValueError("YAML must contain a workflow definition object")

    # Validate through Pydantic
    try:
        workflow = WorkflowDef(**data)
    except ValidationError as e:
        raise e

    # Store line numbers in the workflow's private attribute
    workflow._node_lines = node_lines

    # Additional validation: check for duplicate node IDs
    node_ids: List[str] = [node.id for node in workflow.nodes]
    seen: Dict[str, int] = {}
    duplicates = []

    for node_id in node_ids:
        if node_id in seen:
            duplicates.append(node_id)
        seen[node_id] = seen.get(node_id, 0) + 1

    if duplicates:
        raise ValueError(f"Duplicate node IDs found: {', '.join(set(duplicates))}")

    # Validate reserved input names (starting with __)
    reserved_inputs = [name for name in workflow.inputs.keys() if name.startswith("__")]
    if reserved_inputs:
        raise ValueError(f'Input names starting with "__" are reserved: {", ".join(reserved_inputs)}')

    return workflow
