"""Workspace seeding logic for .workflow/ directory."""
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, TypedDict

from dag_executor.parser import load_workflow
from dag_executor.path_resolution import _resolve_workflow_relative, _resolve_sub_workflow, MAX_RECURSION_DEPTH
from dag_executor.schema import WorkflowDef

logger = logging.getLogger(__name__)


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


def _seed_one_workflow(
    workflow_def: WorkflowDef,
    workflow_dir: Path,
    namespace: str,
    visited: Dict[str, Path],
    depth: int
) -> List[ManifestEntry]:
    """Seed a single workflow and recursively seed its sub-workflows.

    Args:
        workflow_def: Workflow definition to seed
        workflow_dir: Directory to seed into (e.g., <workspace>/.workflow or <workspace>/.workflow/<sub-name>)
        namespace: Current namespace path (e.g., ".workflow" or ".workflow/sub_name")
        visited: Dict mapping sub-workflow stems to their resolved paths (for collision detection)
        depth: Current recursion depth (0 for parent)

    Returns:
        List of manifest entries for this workflow and all sub-workflows

    Raises:
        SeedingError: If any file is missing, path validation fails, or recursion limit exceeded
    """
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
                "workspace_path": f"{namespace}/workflow.yaml",
                "source_path": str(workflow_yaml_path),
                "kind": "workflow_yaml"
            })
        except FileNotFoundError:
            raise SeedingError(f"workflow YAML not found: {workflow_yaml_path}")

        # Create subdirectories
        prompts_dir = workflow_dir / "prompts"
        scripts_dir = workflow_dir / "scripts"

        # Process nodes. The parent (depth=0) fails loudly on
        # prompt_file/script_path resolution errors; sub-workflows (depth>0)
        # log a warning and skip. Sub-workflow paths are typically authored
        # cwd-relative for runtime resolution and don't necessarily resolve
        # under seed-time YAML-relative + safe-roots semantics; the runtime
        # CommandRunner reseeds each sub-workflow in its own workspace, so
        # the parent's recursive snapshot is best-effort.
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
                        "workspace_path": f"{namespace}/prompts/{source_path.name}",
                        "source_path": str(source_path),
                        "kind": "prompt_file"
                    })
                except SeedingError:
                    if depth == 0:
                        raise
                    logger.warning(
                        "skipping unresolvable prompt_file in sub-workflow '%s' (node: %s): %s",
                        namespace, node.id, prompt_file_ref,
                    )
                except Exception as e:
                    if depth == 0:
                        raise SeedingError(f"failed to seed prompt_file: {prompt_file_ref}") from e
                    logger.warning(
                        "skipping prompt_file in sub-workflow '%s' (node: %s) due to %s: %s",
                        namespace, node.id, type(e).__name__, prompt_file_ref,
                    )

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
                        "workspace_path": f"{namespace}/scripts/{source_path.name}",
                        "source_path": str(source_path),
                        "kind": "bash_script"
                    })
                except SeedingError:
                    if depth == 0:
                        raise
                    logger.warning(
                        "skipping unresolvable script_path in sub-workflow '%s' (node: %s): %s",
                        namespace, node.id, script_path_ref,
                    )
                except Exception as e:
                    if depth == 0:
                        raise SeedingError(f"failed to seed script_path: {script_path_ref}") from e
                    logger.warning(
                        "skipping script_path in sub-workflow '%s' (node: %s) due to %s: %s",
                        namespace, node.id, type(e).__name__, script_path_ref,
                    )

            # Handle sub-workflow recursion for type=command nodes
            if node.type == "command":
                command_ref = node.command
                if command_ref is None:
                    raise SeedingError(f"command node missing 'command' field: {node.id}")

                # Resolve sub-workflow. type=command nodes have two semantics:
                # (a) reference a YAML sub-workflow (recursable, seedable)
                # (b) reference a markdown slash-command in commands/ (handled
                #     by the runtime command runner via a different path)
                # Seeding can only act on (a). If resolution fails, it's likely
                # (b) — log and skip. Fail-loudly applies only when a YAML
                # resolves but fails to load (see load_workflow below).
                resolved_path = _resolve_sub_workflow(command_ref, workflow_yaml_path)
                if resolved_path is None:
                    logger.warning(
                        "sub-workflow YAML not found for command '%s' (node: %s); "
                        "skipping recursion. If this should be a YAML sub-workflow, "
                        "ensure the file exists under the workflow's parent dir, "
                        "DAG_DASHBOARD_WORKFLOWS_DIR, or ~/.claude/workflows.",
                        command_ref, node.id,
                    )
                    continue

                # Use YAML stem as namespace key
                sub_stem = resolved_path.stem

                # Check for namespace collision
                if sub_stem in visited:
                    if visited[sub_stem] != resolved_path:
                        raise SeedingError(
                            f"namespace collision: stem '{sub_stem}' resolves to both "
                            f"{visited[sub_stem]} and {resolved_path}"
                        )
                    # Same stem, same path — idempotent, skip
                    continue

                # Check recursion depth limit
                if depth + 1 >= MAX_RECURSION_DEPTH:
                    raise SeedingError(
                        f"maximum sub-workflow recursion depth ({MAX_RECURSION_DEPTH}) exceeded"
                    )

                # Mark as visited
                visited[sub_stem] = resolved_path

                # Load sub-workflow
                try:
                    sub_workflow = load_workflow(str(resolved_path))
                except Exception as e:
                    raise SeedingError(f"failed to load sub-workflow {command_ref}: {e}") from e

                # Create sub-workflow directory
                sub_workflow_dir = workflow_dir / sub_stem
                sub_workflow_dir.mkdir(exist_ok=True)

                # Compute sub-namespace
                sub_namespace = f"{namespace}/{sub_stem}"

                # Recursively seed sub-workflow
                sub_manifest = _seed_one_workflow(
                    sub_workflow,
                    sub_workflow_dir,
                    sub_namespace,
                    visited,
                    depth + 1
                )
                manifest.extend(sub_manifest)

    return manifest


def seed_workspace(workflow_def: WorkflowDef, workspace_path: Path) -> List[ManifestEntry]:
    """Seed the .workflow/ directory in the workspace.

    Copies:
    - workflow.yaml to .workflow/workflow.yaml
    - prompt_file references to .workflow/prompts/<basename>
    - script_path references to .workflow/scripts/<basename>
    - Recursively seeds sub-workflows from type=command nodes

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

    # Seed parent and all sub-workflows recursively
    visited: Dict[str, Path] = {}
    manifest = _seed_one_workflow(
        workflow_def,
        workflow_dir,
        ".workflow",
        visited,
        depth=0
    )

    # Write manifest
    manifest_path = workflow_dir / ".manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))

    return manifest
