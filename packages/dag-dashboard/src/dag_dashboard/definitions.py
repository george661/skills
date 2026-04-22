"""Workflow definition listing and retrieval."""
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

logger = logging.getLogger(__name__)

# Valid workflow name pattern (alphanumeric and hyphens only)
WORKFLOW_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9-]+$")


class DefinitionParseError(Exception):
    """Raised when a workflow YAML file exists but cannot be parsed."""
    pass


def list_definitions(workflows_dirs: List[Path], db_path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """
    List all workflow definitions across multiple directories.

    Args:
        workflows_dirs: List of directories to scan for YAML files.
        db_path: Optional path to dashboard.db for querying last run info.

    Returns:
        List of definition dicts with name, source_dir, metadata, and collision info.
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

            # Parse YAML to extract metadata
            parsed = None
            try:
                with open(yaml_file, "r") as f:
                    parsed = yaml.safe_load(f)
            except Exception as e:
                logger.warning(f"Skipping invalid YAML {yaml_file}: {e}")
                continue

            # Extract metadata
            description = parsed.get("description", "") if parsed else ""
            inputs = parsed.get("inputs", {}) if parsed else {}

            seen_names[name] = str(workflows_dir)
            definition = {
                "name": name,
                "source_dir": str(workflows_dir),
                "path": str(yaml_file),
                "description": description,
                "inputs": inputs,
            }
            definitions.append(definition)

    # Query last run info from database if available
    if db_path and db_path.exists():
        import sqlite3
        try:
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            for definition in definitions:
                name = definition["name"]
                cursor.execute(
                    """
                    SELECT status, started_at
                    FROM workflow_runs
                    WHERE workflow_name = ?
                    ORDER BY started_at DESC
                    LIMIT 1
                    """,
                    (name,)
                )
                row = cursor.fetchone()
                if row:
                    definition["last_run"] = {
                        "status": row["status"],
                        "started_at": row["started_at"]
                    }
            conn.close()
        except Exception as e:
            logger.warning(f"Failed to query last run info: {e}")

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
            raise DefinitionParseError(f"Failed to parse workflow YAML: {e}")
        
        return {
            "name": name,
            "source_dir": str(workflows_dir),
            "path": str(yaml_file),
            "yaml_source": yaml_source.strip(),
            "parsed": parsed,
        }
    
    return None
