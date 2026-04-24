"""Command runner for recursive workflow execution nodes."""
import asyncio
import concurrent.futures
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Coroutine, Dict, List, Optional, TypeVar

_T = TypeVar("_T")


def _resolve_sub_workflow(reference: str, parent_source: Optional[Path]) -> Optional[Path]:
    """Resolve a `command:` field to a concrete YAML path.

    A `command:` value is either:
      - an absolute or relative filesystem path ending in .yaml/.yml, or
      - a bare workflow name (e.g. "validate-epic-audit-children") expected to
        live alongside the parent workflow or in a known install location.

    Search order:
      1. The literal string as a path (covers both ".yaml-ful" and absolute refs)
      2. `<parent-dir>/<name>.yaml` and `.yml` — the common co-located case
      3. Each entry in `DAG_DASHBOARD_WORKFLOWS_DIR` (colon-separated)
      4. `~/.claude/workflows/<name>.yaml`

    Returns the first existing file, or None if nothing matched.
    """
    # 1. Literal path (handles e.g. "foo/bar.yaml" or "/abs/path.yaml").
    # Require a regular file — a matching directory name at CWD (e.g. a
    # stale `.dag-checkpoints/` leak) should not pre-empt the search.
    direct = Path(reference)
    if direct.is_file():
        return direct

    # Bare-name candidates — try both extensions
    candidate_names: List[str] = []
    if reference.endswith(".yaml") or reference.endswith(".yml"):
        candidate_names.append(reference)
    else:
        candidate_names.extend([reference + ".yaml", reference + ".yml"])

    search_dirs: List[Path] = []
    # 2. Parent workflow's directory
    if parent_source is not None:
        search_dirs.append(parent_source.parent)
    # 3. DAG_DASHBOARD_WORKFLOWS_DIR (colon-separated list)
    env_dirs = os.environ.get("DAG_DASHBOARD_WORKFLOWS_DIR", "")
    if env_dirs:
        search_dirs.extend(Path(d) for d in env_dirs.split(os.pathsep) if d)
    # 4. ~/.claude/workflows
    search_dirs.append(Path.home() / ".claude" / "workflows")

    for base in search_dirs:
        for name in candidate_names:
            candidate = base / name
            if candidate.is_file():
                return candidate

    return None


def _run_coroutine_sync(coro: "Coroutine[Any, Any, _T]") -> _T:
    """Run an async coroutine from a synchronous context, regardless of loop state.

    CommandRunner.run() is synchronous but calls WorkflowExecutor.execute() which is async.
    In production this runs on a ThreadPoolExecutor worker with no loop, so a fresh loop
    works directly. In tests (pytest-asyncio), it may run on a thread that already owns
    a running loop, which would make asyncio.run() / loop.run_until_complete() raise.
    Shunting execution onto a fresh worker thread with its own loop sidesteps both cases.
    """
    def _worker() -> _T:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(_worker).result()

from dag_executor.schema import NodeResult, NodeStatus, WorkflowStatus
from dag_executor.runners.base import BaseRunner, RunnerContext, register_runner
from dag_executor.parser import load_workflow

# Maximum recursion depth for command nodes
MAX_RECURSION_DEPTH = 5


@register_runner("command")
class CommandRunner(BaseRunner):
    """Runner for command execution nodes.
    
    Loads and executes sub-workflows recursively with depth limiting.
    """
    
    def run(self, ctx: RunnerContext) -> NodeResult:
        """Execute a command node.
        
        Args:
            ctx: Runner execution context
            
        Returns:
            NodeResult with execution status and sub-workflow output
        """
        # Check recursion depth
        current_depth = getattr(ctx, "_recursion_depth", 0)
        if current_depth >= MAX_RECURSION_DEPTH:
            return NodeResult(
                status=NodeStatus.FAILED,
                error=f"Maximum recursion depth ({MAX_RECURSION_DEPTH}) exceeded"
            )
        
        command = ctx.node_def.command
        if command is None:
            raise ValueError("command field is required for type=command")
        args = ctx.node_def.args or []
        inputs_map = ctx.node_def.inputs_map or {}

        # Try loading the reference as-is first. This preserves the existing
        # contract where `command:` is either a path or a name patched into a
        # test loader. Only if that fails with FileNotFoundError do we run the
        # name-to-path resolver (parent dir + DAG_DASHBOARD_WORKFLOWS_DIR +
        # ~/.claude/workflows) and retry.
        parent_source = ctx.workflow_def._source_path if ctx.workflow_def is not None else None

        workflow_def = None
        load_error: Optional[Exception] = None
        try:
            workflow_def = load_workflow(command)
        except FileNotFoundError as e:
            load_error = e
        except Exception as e:
            return NodeResult(
                status=NodeStatus.FAILED,
                error=f"Failed to load workflow '{command}': {str(e)}"
            )

        if workflow_def is None:
            resolved_path = _resolve_sub_workflow(command, parent_source)
            if resolved_path is not None:
                try:
                    workflow_def = load_workflow(str(resolved_path))
                except Exception as e:
                    return NodeResult(
                        status=NodeStatus.FAILED,
                        error=f"Failed to load workflow '{command}': {str(e)}"
                    )
            else:
                return NodeResult(
                    status=NodeStatus.FAILED,
                    error=(
                        f"Failed to load workflow '{command}': {load_error}. "
                        f"Searched parent dir, DAG_DASHBOARD_WORKFLOWS_DIR, and ~/.claude/workflows. "
                        f"Pass an absolute/relative path or place the file alongside the parent."
                    ),
                )
        
        # Build inputs for sub-workflow from args and resolved inputs
        sub_workflow_inputs = {}
        
        # Add args as positional inputs
        for i, arg in enumerate(args):
            sub_workflow_inputs[f"arg{i}"] = arg
        
        # Add resolved inputs
        sub_workflow_inputs.update(ctx.resolved_inputs)
        
        # Add inputs_map (resolving $ref values)
        if inputs_map:
            from dag_executor.variables import resolve_variables
            for key, value in inputs_map.items():
                # Resolve the value if it's a $ref
                resolved_value = resolve_variables(
                    value,
                    node_outputs=ctx.node_outputs,
                    workflow_inputs=ctx.workflow_inputs
                )
                # inputs_map overrides positional args (kwargs-override-args semantics)
                sub_workflow_inputs[key] = resolved_value

        # Generate a unique run_id for the sub-workflow
        sub_run_id = str(uuid.uuid4())

        # Execute sub-workflow with real WorkflowExecutor. See _run_coroutine_sync for
        # why this goes through a worker thread — it handles both production (no loop
        # on current thread) and test (pytest-asyncio loop already running) cases.
        try:
            from dag_executor.executor import WorkflowExecutor
            executor = WorkflowExecutor()
            workflow_result = _run_coroutine_sync(
                executor.execute(
                    workflow_def=workflow_def,
                    inputs=sub_workflow_inputs,
                    event_emitter=ctx.event_emitter,
                    run_id=sub_run_id,
                    parent_run_id=ctx.parent_run_id,
                    subprocess_registry=ctx.subprocess_registry,
                    conversation_id=ctx.conversation_id,
                    db_path=ctx.db_path,
                    _recursion_depth=current_depth + 1,
                )
            )
            
            # Emit terminal WORKFLOW_COMPLETED or WORKFLOW_FAILED event
            if ctx.event_emitter is not None:
                from dag_executor.events import EventType, WorkflowEvent
                terminal_status = workflow_result.status
                sub_workflow_name = getattr(workflow_def, "name", command)
                ctx.event_emitter.emit(WorkflowEvent(
                    event_type=EventType.WORKFLOW_COMPLETED if terminal_status == WorkflowStatus.COMPLETED else EventType.WORKFLOW_FAILED,
                    workflow_id=sub_workflow_name,
                    status=terminal_status,
                    timestamp=datetime.now(timezone.utc),
                    metadata={
                        "parent_run_id": ctx.parent_run_id,
                        "workflow_name": sub_workflow_name,
                        "run_id": sub_run_id,
                    },
                ))
            
            # Convert workflow result to node result
            if workflow_result.status == WorkflowStatus.FAILED:
                # Extract error from failed nodes
                error_messages = []
                for node_id, node_result in workflow_result.node_results.items():
                    if node_result.status == NodeStatus.FAILED and node_result.error:
                        error_messages.append(f"{node_id}: {node_result.error}")
                error = f"Sub-workflow failed: {'; '.join(error_messages)}" if error_messages else "Sub-workflow failed"
                return NodeResult(
                    status=NodeStatus.FAILED,
                    error=error
                )
            
            # Return outputs from sub-workflow as node output
            return NodeResult(
                status=NodeStatus.COMPLETED,
                output=workflow_result.outputs
            )
        except Exception as e:
            # Log full stack trace for debugging
            import logging
            logger = logging.getLogger(__name__)
            logger.exception(f"Sub-workflow {command} execution failed")

            # Emit terminal WORKFLOW_FAILED event when child executor raises
            if ctx.event_emitter is not None:
                from dag_executor.events import EventType, WorkflowEvent
                sub_workflow_name = getattr(workflow_def, "name", command)
                ctx.event_emitter.emit(WorkflowEvent(
                    event_type=EventType.WORKFLOW_FAILED,
                    workflow_id=sub_workflow_name,
                    status=WorkflowStatus.FAILED,
                    timestamp=datetime.now(timezone.utc),
                    metadata={
                        "parent_run_id": ctx.parent_run_id,
                        "workflow_name": sub_workflow_name,
                        "run_id": sub_run_id,
                        "error": f"{type(e).__name__}: {str(e)}",
                    },
                ))
            return NodeResult(
                status=NodeStatus.FAILED,
                error=f"Sub-workflow execution failed: {type(e).__name__}: {str(e)}"
            )
