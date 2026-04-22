"""Workflow definition listing and retrieval."""
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

logger = logging.getLogger(__name__)

# Valid workflow name pattern (alphanumeric and hyphens only)
WORKFLOW_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9-]+$")


def list_definitions(workflows_dirs: List[Path]) -> List[Dict[str, Any]]:
    """
    List all workflow definitions across multiple directories.
    
    Args:
        workflows_dirs: List of directories to scan for YAML files.
    
    Returns:
        List of definition dicts with name, source_dir, and collision info.
    """
    definitions: List[Dict[str, Any]] = []
    seen_names: Dict[str, str] = {}  # name -> first source_dir
    collisions: Dict[str, List[str]] = {}  # name -> list of later source_dirs
    
    for workflows_dir in workflows_dirs:
        if not workflows_dir.exists():
            logger.warning(f"Workflows directory does not exist: {workflows_dir}")
            continue
        
        for yaml_file in workflows_dir.glob("*.yaml"):
            name = yaml_file.stem
            
            # Skip if we've already seen this name (first-dir-wins)
            if name in seen_names:
                collisions.setdefault(name, []).append(str(workflows_dir))
                logger.warning(
                    f"Workflow name collision: '{name}' in {workflows_dir} "
                    f"shadowed by {seen_names[name]}"
                )
                continue
            
            # Try to parse YAML to validate it
            try:
                with open(yaml_file, "r") as f:
                    yaml.safe_load(f)
            except Exception as e:
                logger.warning(f"Skipping invalid YAML {yaml_file}: {e}")
                continue
            
            seen_names[name] = str(workflows_dir)
            definition = {
                "name": name,
                "source_dir": str(workflows_dir),
                "path": str(yaml_file),
            }
            definitions.append(definition)
    
    # Add collision info to definitions that have conflicts
    for definition in definitions:
        name = definition["name"]
        if name in collisions:
            definition["collisions"] = collisions[name]
    
    return definitions


def get_definition(
    workflows_dirs: List[Path], name: str
) -> Optional[Dict[str, Any]]:
    """
    Get a workflow definition by name.
    
    Args:
        workflows_dirs: List of directories to search.
        name: Workflow name (without .yaml extension).
    
    Returns:
        Dict with name, yaml_source, parsed data, or None if not found.
    
    Raises:
        ValueError: If name contains invalid characters (traversal attempt).
    """
    # Security: reject path traversal attempts
    if not WORKFLOW_NAME_PATTERN.match(name):
        raise ValueError(
            f"Invalid workflow name: {name}. "
            "Only alphanumeric characters and hyphens are allowed."
        )
    
    # Search directories in order (first match wins)
    for workflows_dir in workflows_dirs:
        if not workflows_dir.exists():
            continue
        
        yaml_file = workflows_dir / f"{name}.yaml"
        if not yaml_file.exists():
            continue
        
        # Defense-in-depth: ensure resolved path is within the workflows_dir
        try:
            yaml_file.resolve().relative_to(workflows_dir.resolve())
        except ValueError:
            logger.error(
                f"Security: resolved path {yaml_file.resolve()} "
                f"is outside workflows_dir {workflows_dir.resolve()}"
            )
            continue
        
        # Read YAML source
        try:
            with open(yaml_file, "r") as f:
                yaml_source = f.read()
            parsed = yaml.safe_load(yaml_source)
        except Exception as e:
            logger.error(f"Failed to read/parse {yaml_file}: {e}")
            return None
        
        return {
            "name": name,
            "source_dir": str(workflows_dir),
            "path": str(yaml_file),
            "yaml_source": yaml_source.strip(),
            "parsed": parsed,
        }
    
    return None
