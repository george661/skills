"""Workspace seeding logic for .workflow/ directory."""
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, TypedDict

from dag_executor.path_resolution import _resolve_workflow_relative
from dag_executor.schema import WorkflowDef


class SeedingError(RuntimeError):
    """Error during workspace seeding."""
    pass


class ManifestEntry(TypedDict):
    """Entry in .workflow/.manifest.json."""
    workspace_path: str
    source_path: str
    kind: str  # "workflow_yaml", "prompt_file", "bash_script"


def _get_safe_roots() -> List[Path]:
    """Get list of safe root directories for path resolution.

    Safe roots are:
    - repo_root/commands
    - repo_root/workflows
    - DAG_DASHBOARD_WORKFLOWS_DIR entries
    - ~/.claude/workflows

    Returns:
        List of safe root paths
    """
    import os
    from dag_executor.path_resolution import _find_repo_root

    safe_roots = []

    # Find repo root
    repo_root = _find_repo_root(Path.cwd())
    if repo_root:
        safe_roots.append(repo_root / "commands")
        safe_roots.append(repo_root / "workflows")

    # Add DAG_DASHBOARD_WORKFLOWS_DIR entries
    env_dirs = os.environ.get("DAG_DASHBOARD_WORKFLOWS_DIR", "")
    if env_dirs:
        safe_roots.extend(Path(d) for d in env_dirs.split(os.pathsep) if d)

    # Add ~/.claude/workflows
    safe_roots.append(Path.home() / ".claude" / "workflows")

    return safe_roots


def _resolve_source_path(workflow_yaml_path: Path, ref: str) -> Path:
    """Resolve a relative reference to an absolute source path.

    Uses the same resolution logic as runtime (via _resolve_workflow_relative),
    ensuring that prompt_file and script_path references resolve consistently
    between seeding and execution.

    Args:
        workflow_yaml_path: Path to the workflow YAML file
        ref: Relative path reference from the workflow (e.g., "../../commands/foo.md")

    Returns:
        Absolute path to the source file

    Raises:
        SeedingError: If path is absolute or resolves outside safe roots
    """
    # Reject absolute paths
    if Path(ref).is_absolute():
        raise SeedingError(f"absolute paths are not allowed: {ref}")

    # Use the same resolution logic as runtime
    resolved = _resolve_workflow_relative(ref, workflow_yaml_path, suffixes=None)

    if resolved is None:
        raise SeedingError(f"referenced file not found: {ref}")

    # Verify resolved path is under one of the safe roots or the workflow's repo root.
    safe_roots = _get_safe_roots()

    # Allow paths anywhere under the workflow's own repo root (production case).
    from dag_executor.path_resolution import _find_repo_root
    repo_root = _find_repo_root(workflow_yaml_path)
    if repo_root:
        safe_roots.append(repo_root)
    else:
        # Test-fixture fallback: when there's no repo root (no .git ancestor),
        # constrain to the workflow YAML's own directory only. This is strict
        # by design — fixtures should reference files co-located with them.
        # Production code paths always have a repo root, so this branch never
        # widens the production boundary.
        safe_roots.append(workflow_yaml_path.parent)

    is_safe = False
    for root in safe_roots:
        try:
            resolved.relative_to(root)
            is_safe = True
            break
        except ValueError:
            continue

    if not is_safe:
        raise SeedingError(
            f"path resolves outside allowed safe roots: {ref} -> {resolved}"
        )

    return resolved


def seed_workspace(workflow_def: WorkflowDef, workspace_path: Path) -> List[ManifestEntry]:
    """Seed the .workflow/ directory in the workspace.

    Copies:
    - workflow.yaml to .workflow/workflow.yaml
    - prompt_file references to .workflow/prompts/<basename>
    - script_path references to .workflow/scripts/<basename>

    For programmatic workflows (no _source_path), still creates .workflow/
    directory and writes empty .manifest.json.

    Args:
        workflow_def: Parsed workflow definition (may have _source_path set)
        workspace_path: Path to the workspace directory

    Returns:
        List of manifest entries for all seeded files (empty if no _source_path)

    Raises:
        SeedingError: If any referenced file is missing or path validation fails
    """
    # Create .workflow/ directory structure
    workflow_dir = workspace_path / ".workflow"
    workflow_dir.mkdir(exist_ok=True)
    prompts_dir = workflow_dir / "prompts"
    scripts_dir = workflow_dir / "scripts"

    manifest: List[ManifestEntry] = []

    # Check if workflow was loaded from a file
    workflow_source = getattr(workflow_def, '_source_path', None)
    has_source = workflow_source is not None

    if has_source:
        assert workflow_source is not None  # narrow for mypy
        workflow_yaml_path = Path(workflow_source)

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

    # Process nodes (only if we have a source path)
    if has_source:
        for node in workflow_def.nodes:
            # Handle prompt_file
            prompt_file_ref = node.prompt_file
            if prompt_file_ref is not None:
                try:
                    source_path = _resolve_source_path(workflow_yaml_path, prompt_file_ref)
                    if not source_path.exists():
                        raise SeedingError(
                            f"referenced file not found: {prompt_file_ref} (node: {node.id})"
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
                    raise SeedingError(f"failed to seed prompt_file: {prompt_file_ref}") from e

            # Handle script_path
            script_path_ref = node.script_path
            if script_path_ref is not None:
                try:
                    source_path = _resolve_source_path(workflow_yaml_path, script_path_ref)
                    if not source_path.exists():
                        raise SeedingError(
                            f"referenced file not found: {script_path_ref} (node: {node.id})"
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
                    raise SeedingError(f"failed to seed script_path: {script_path_ref}") from e

            # NOTE: sub-workflow seeding (recursing into .workflow/<sub-name>/
            # for type=command nodes) is intentionally deferred to a follow-up
            # ticket. Phase 1 covers schema + per-parent-workflow seeding; the
            # sub-workflow recursion needs careful design around namespace
            # collisions and the manifest path scheme, and isn't required for
            # the boundary enforcement landing in Phase 4 (GW-5936). See the
            # follow-up ticket linked on the parent epic GW-5928.

    # Write manifest
    manifest_path = workflow_dir / ".manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))

    return manifest
