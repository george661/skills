"""Workspace seeding logic for .workflow/ directory."""
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, TypedDict

from dag_executor.schema import WorkflowDef


class SeedingError(RuntimeError):
    """Error during workspace seeding."""
    pass


class ManifestEntry(TypedDict):
    """Entry in .workflow/.manifest.json."""
    workspace_path: str
    source_path: str
    kind: str  # "workflow_yaml", "prompt_file", "bash_script"


def _resolve_source_path(workflow_yaml_dir: Path, ref: str) -> Path:
    """Resolve a relative reference to an absolute source path.

    Args:
        workflow_yaml_dir: Directory containing the workflow YAML
        ref: Relative path reference from the workflow (e.g., "scripts/test.sh")

    Returns:
        Absolute path to the source file

    Raises:
        SeedingError: If path is absolute or resolves outside the repo root
    """
    # Reject absolute paths
    if Path(ref).is_absolute():
        raise SeedingError(f"absolute paths are not allowed: {ref}")

    # Resolve relative to workflow YAML directory
    resolved = (workflow_yaml_dir / ref).resolve()

    # For security, ensure resolved path stays within a reasonable boundary.
    # We allow ".." in paths (existing workflows use this), but the resolved
    # path must not escape too far up. We check that it stays within the
    # repo root by ensuring it doesn't go above the workflow directory's
    # great-great-grandparent (4 levels up covers workflows/subdir/ -> repo root).
    # This prevents /etc/passwd but allows ../../commands/foo.md from workflows/.
    boundary = workflow_yaml_dir.resolve()
    for _ in range(4):  # Allow up to 4 levels up
        boundary = boundary.parent

    try:
        resolved.relative_to(boundary)
    except ValueError:
        raise SeedingError(
            f"path resolves outside allowed boundary: {ref} -> {resolved}"
        )

    return resolved


def seed_workspace(workflow_def: WorkflowDef, workspace_path: Path) -> List[ManifestEntry]:
    """Seed the .workflow/ directory in the workspace.
    
    Copies:
    - workflow.yaml to .workflow/workflow.yaml
    - prompt_file references to .workflow/prompts/<basename>
    - script_path references to .workflow/scripts/<basename>
    
    Args:
        workflow_def: Parsed workflow definition with _source_path set
        workspace_path: Path to the workspace directory
        
    Returns:
        List of manifest entries for all seeded files (empty if no _source_path)

    Raises:
        SeedingError: If any referenced file is missing or path validation fails
    """
    # Skip seeding if workflow was not loaded from a file (e.g., programmatically created)
    if not hasattr(workflow_def, '_source_path') or workflow_def._source_path is None:
        return []
    
    workflow_yaml_path = Path(workflow_def._source_path)
    workflow_yaml_dir = workflow_yaml_path.parent
    
    # Create .workflow/ directory structure
    workflow_dir = workspace_path / ".workflow"
    workflow_dir.mkdir(exist_ok=True)
    prompts_dir = workflow_dir / "prompts"
    scripts_dir = workflow_dir / "scripts"
    
    manifest: List[ManifestEntry] = []
    
    # Copy workflow.yaml
    workflow_dest = workflow_dir / "workflow.yaml"
    try:
        workflow_dest.write_text(workflow_yaml_path.read_text())
        manifest.append({
            "workspace_path": ".workflow/workflow.yaml",
            "source_path": str(workflow_yaml_path),
            "kind": "workflow_yaml"
        })
    except FileNotFoundError:
        raise SeedingError(f"workflow YAML not found: {workflow_yaml_path}")
    
    # Process nodes
    for node in workflow_def.nodes:
        # Handle prompt_file
        if hasattr(node, 'prompt_file') and node.prompt_file:
            try:
                source_path = _resolve_source_path(workflow_yaml_dir, node.prompt_file)
                if not source_path.exists():
                    raise SeedingError(
                        f"referenced file not found: {node.prompt_file} (node: {node.id})"
                    )
                
                prompts_dir.mkdir(exist_ok=True)
                dest_path = prompts_dir / source_path.name
                dest_path.write_text(source_path.read_text())
                
                manifest.append({
                    "workspace_path": f".workflow/prompts/{source_path.name}",
                    "source_path": str(source_path),
                    "kind": "prompt_file"
                })
            except SeedingError:
                raise
            except Exception as e:
                raise SeedingError(f"failed to seed prompt_file: {node.prompt_file}") from e
        
        # Handle script_path
        if hasattr(node, 'script_path') and node.script_path:
            try:
                source_path = _resolve_source_path(workflow_yaml_dir, node.script_path)
                if not source_path.exists():
                    raise SeedingError(
                        f"referenced file not found: {node.script_path} (node: {node.id})"
                    )
                
                scripts_dir.mkdir(exist_ok=True)
                dest_path = scripts_dir / source_path.name
                dest_path.write_text(source_path.read_text())
                
                manifest.append({
                    "workspace_path": f".workflow/scripts/{source_path.name}",
                    "source_path": str(source_path),
                    "kind": "bash_script"
                })
            except SeedingError:
                raise
            except Exception as e:
                raise SeedingError(f"failed to seed script_path: {node.script_path}") from e
    
    # Write manifest
    manifest_path = workflow_dir / ".manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))
    
    return manifest
