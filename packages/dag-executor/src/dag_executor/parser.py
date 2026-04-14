"""YAML workflow parser with schema validation."""
from pathlib import Path
from typing import Dict, List

import yaml
from pydantic import ValidationError

from dag_executor.schema import WorkflowDef


def load_workflow(yaml_path: str) -> WorkflowDef:
    """Load and validate a workflow definition from a YAML file.
    
    Args:
        yaml_path: Path to the workflow YAML file
        
    Returns:
        Validated WorkflowDef object
        
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
        Validated WorkflowDef object
        
    Raises:
        ValueError: If the YAML is invalid or contains duplicate node IDs
        ValidationError: If the workflow definition fails schema validation
    """
    if not yaml_string or not yaml_string.strip():
        raise ValueError("YAML string cannot be empty")
    
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
    
    return workflow
