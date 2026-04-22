"""CLI entry point for DAG executor."""
import argparse
import os
import json
import sqlite3
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from dag_executor import (
    load_workflow,
    execute_workflow,
    resume_workflow,
    topological_sort_with_layers,
    CheckpointStore,
    WorkflowResult,
    WorkflowEvent,
    NodeStatus,
    WorkflowStatus,
    EventEmitter,
    StreamMode,
)
from dag_executor.replay import execute_replay
from dag_executor.validator import WorkflowValidator

SUBCOMMANDS = {"replay", "history", "inspect", "cancel", "search", "logs", "rerun", "gates"}


def _build_list_parser(subparsers: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    """Add 'list' subcommand for workflow catalog."""
    list_parser = subparsers.add_parser(
        "list",
        help="List available workflows in a directory",
    )
    list_parser.add_argument(
        "directory",
        nargs="?",
        default=".",
        help="Directory to scan for .yaml workflow files (default: current dir)",
    )
    list_parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Output as JSON",
    )


def _build_info_parser(subparsers: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    """Add 'info' subcommand for workflow details."""
    info_parser = subparsers.add_parser(
        "info",
        help="Show detailed info about a workflow",
    )
    info_parser.add_argument(
        "workflow",
        help="Path to workflow YAML file",
    )


def run_list(directory: str, json_output: bool = False) -> None:
    """List all valid workflows in a directory or multiple directories from env var.

    If --directory is provided, scans that single directory only.
    If --directory is not provided (defaults to "."), checks DAG_DASHBOARD_WORKFLOWS_DIR
    env var for a colon-separated list of directories to scan (first-dir-wins collision).

    Scans for .yaml files, attempts to parse each as a WorkflowDef,
    and displays a catalog of valid workflows.

    Args:
        directory: Directory to scan (or "." to use env var)
        json_output: If True, output as JSON
    """
    import os
    from pathlib import Path

    # If directory is "." (default), check env var for multiple dirs
    explicit_single_dir = False
    if directory == ".":
        env_dirs = os.environ.get("DAG_DASHBOARD_WORKFLOWS_DIR", "")
        if env_dirs:
            scan_dirs = [Path(d.strip()) for d in env_dirs.split(os.pathsep) if d.strip()]
        else:
            scan_dirs = [Path(".")]
    else:
        # Explicit directory provided, scan only that one
        scan_dirs = [Path(directory)]
        explicit_single_dir = True

    workflows: List[Dict[str, Any]] = []
    seen_names: set[str] = set()

    for scan_dir in scan_dirs:
        if not scan_dir.exists() or not scan_dir.is_dir():
            # Preserve pre-existing behavior: hard-fail when the user passed a
            # single explicit directory. Multi-dir env-var mode skips with a warning.
            if explicit_single_dir:
                print(f"Error: '{scan_dir}' is not a directory", file=sys.stderr)
                sys.exit(1)
            if not scan_dir.exists():
                print(f"Warning: '{scan_dir}' does not exist, skipping", file=sys.stderr)
            else:
                print(f"Warning: '{scan_dir}' is not a directory, skipping", file=sys.stderr)
            continue

        for yaml_file in sorted(scan_dir.glob("*.yaml")):
            try:
                wf = load_workflow(str(yaml_file))
                # First-dir-wins collision: skip if we've already seen this workflow name
                if wf.name in seen_names:
                    continue
                seen_names.add(wf.name)

                workflows.append({
                    "file": yaml_file.name,
                    "name": wf.name,
                    "nodes": len(wf.nodes),
                    "inputs": list(wf.inputs.keys()),
                    "checkpoint_prefix": wf.config.checkpoint_prefix,
                    "source_dir": str(scan_dir),
                })
            except (ValueError, Exception):
                continue  # Skip non-workflow YAML files

    if json_output:
        print(json.dumps(workflows, indent=2))
    else:
        if not workflows:
            print("No workflows found.")
            return
        print(f"{'File':<30} {'Name':<35} {'Nodes':>5}  Inputs")
        print("-" * 90)
        for entry in workflows:
            inputs_str = ", ".join(str(i) for i in entry["inputs"]) if entry["inputs"] else "(none)"
            print(f"{entry['file']:<30} {entry['name']:<35} {entry['nodes']:>5}  {inputs_str}")


def run_info(workflow_path: str) -> None:
    """Show detailed info about a workflow.

    Args:
        workflow_path: Path to workflow YAML file
    """
    workflow_def = load_workflow(workflow_path)

    print(f"Workflow: {workflow_def.name}")
    print(f"File: {workflow_path}")
    print(f"Checkpoint prefix: {workflow_def.config.checkpoint_prefix}")
    print(f"Worktree: {workflow_def.config.worktree}")
    print()

    # Inputs
    if workflow_def.inputs:
        print("Inputs:")
        for name, inp in workflow_def.inputs.items():
            req = "required" if inp.required else "optional"
            default = f" (default: {inp.default})" if inp.default is not None else ""
            pattern = f" [pattern: {inp.pattern}]" if inp.pattern else ""
            print(f"  {name}: {inp.type} ({req}){default}{pattern}")
        print()

    # Node summary by type
    type_counts: Dict[str, int] = {}
    for node in workflow_def.nodes:
        type_counts[node.type] = type_counts.get(node.type, 0) + 1
    print(f"Nodes: {len(workflow_def.nodes)} total")
    for ntype, count in sorted(type_counts.items()):
        print(f"  {ntype}: {count}")
    print()

    # Execution plan
    layers = topological_sort_with_layers(workflow_def.nodes)
    node_map = {n.id: n for n in workflow_def.nodes}
    print("Execution Plan:")
    for layer_idx, layer_ids in enumerate(layers):
        parallel = " (parallel)" if len(layer_ids) > 1 else ""
        print(f"  Layer {layer_idx}{parallel}:")
        for nid in layer_ids:
            node = node_map[nid]
            print(f"    {nid}: {node.name} [{node.type}]")

    # Outputs
    if workflow_def.outputs:
        print()
        print("Outputs:")
        for name, out in workflow_def.outputs.items():
            field = f".{out.field}" if out.field else ""
            print(f"  {name}: from {out.node}{field}")

    # Exit hooks
    if workflow_def.config.on_exit:
        print()
        print("Exit Hooks:")
        for hook in workflow_def.config.on_exit:
            runs = ", ".join(hook.run_on)
            print(f"  {hook.id}: {hook.type} (runs on: {runs})")


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    """Parse CLI arguments.

    Args:
        argv: Argument list (defaults to sys.argv[1:])

    Returns:
        Parsed arguments namespace
    """
    args_list = argv if argv is not None else sys.argv[1:]

    # Check if first arg is a subcommand (list, info) — handle separately
    # to avoid breaking the original `dag-exec workflow.yaml` syntax
    if args_list and args_list[0] in ("list", "info"):
        sub_parser = argparse.ArgumentParser(prog="dag-exec")
        sub = sub_parser.add_subparsers(dest="subcommand")
        _build_list_parser(sub)
        _build_info_parser(sub)
        return sub_parser.parse_args(args_list)

    parser = argparse.ArgumentParser(
        prog="dag-exec",
        description="Execute DAG workflows from YAML files",
    )

    parser.add_argument(
        "workflow",
        help="Path to workflow YAML file",
    )
    
    parser.add_argument(
        "inputs",
        nargs="*",
        help="Workflow inputs as key=value pairs or JSON object",
    )
    
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume workflow from checkpoint",
    )
    
    parser.add_argument(
        "--run-id",
        help=(
            "Run ID. Required with --resume. For normal execution, when set, "
            "the executor uses this run_id instead of generating a new UUID; "
            "this is how the dashboard trigger endpoint keeps its database "
            "run_id in sync with the NDJSON filename and cancel marker path."
        ),
    )
    
    parser.add_argument(
        "--resume-values",
        help="JSON object of resume values for interrupt points",
    )
    
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate YAML and print execution plan without executing",
    )
    
    parser.add_argument(
        "--visualize",
        action="store_true",
        help="Output mermaid DAG diagram",
    )
    
    parser.add_argument(
        "--concurrency",
        type=int,
        default=10,
        help="Maximum concurrent node executions (default: 10)",
    )
    
    parser.add_argument(
        "--checkpoint-dir",
        help="Override checkpoint directory (defaults to workflow config)",
    )

    parser.add_argument(
        "--stream",
        nargs="?",
        const="all",
        choices=["all", "state_updates"],
        help="Stream execution events to stderr (default: all)",
    )

    parser.add_argument(
        "--progress",
        action="store_true",
        help="Show progress bar during execution",
    )

    parser.add_argument(
        "--events-dir",
        help=(
            "Directory for NDJSON event logs and cancel markers. "
            "When set, events are written to {events-dir}/{run_id}.ndjson "
            "and the executor polls {events-dir}/{run_id}.cancel for "
            "cancellation signals. Env var: DAG_EVENTS_DIR."
        ),
    )

    return parser.parse_args(argv)


def parse_inputs(input_args: List[str]) -> Dict[str, Any]:
    """Parse input arguments into a dictionary.
    
    Supports:
    - key=value pairs: user_id=123 dry_run=true
    - JSON objects: '{"user_id": "123", "dry_run": true}'
    
    Args:
        input_args: List of input argument strings
    
    Returns:
        Dictionary of parsed inputs
    """
    inputs: Dict[str, Any] = {}
    
    for arg in input_args:
        # Try JSON first
        if arg.startswith("{"):
            try:
                json_inputs = json.loads(arg)
                inputs.update(json_inputs)
                continue
            except json.JSONDecodeError:
                pass
        
        # Try key=value
        if "=" in arg:
            key, value = arg.split("=", 1)
            # Try to parse as JSON value (for booleans, numbers, etc.)
            try:
                inputs[key] = json.loads(value)
            except json.JSONDecodeError:
                # Keep as string
                inputs[key] = value
        else:
            print(f"Warning: Ignoring invalid input format: {arg}", file=sys.stderr)
    
    return inputs


def run_dry_run(workflow_path: str) -> None:
    """Validate workflow and print execution plan.

    Args:
        workflow_path: Path to workflow YAML file
    """
    # Load workflow
    workflow_def = load_workflow(workflow_path)

    # Run pre-flight validation
    workflow_path_obj = Path(workflow_path)
    parent_dir = workflow_path_obj.parent
    validator = WorkflowValidator(
        skills_dir=parent_dir / "skills" if (parent_dir / "skills").exists() else None,
        commands_dir=parent_dir / "commands" if (parent_dir / "commands").exists() else None,
        workflows_dir=parent_dir / "workflows" if (parent_dir / "workflows").exists() else None,
    )
    validation_result = validator.validate(workflow_def)

    # Print validation summary
    print(f"Validation: {validation_result.summary()}")
    print()

    # If there are errors, print them and exit
    if not validation_result.passed:
        print("Validation Errors:")
        for error in validation_result.errors:
            node_str = f"[{error.node_id}] " if error.node_id else ""
            print(f"  ✗ {node_str}{error.message}")
        print()
        sys.exit(1)

    # If there are warnings, print them
    if validation_result.warnings:
        print("Validation Warnings:")
        for warning in validation_result.warnings:
            node_str = f"[{warning.node_id}] " if warning.node_id else ""
            print(f"  ⚠ {node_str}{warning.message}")
        print()

    # Print workflow info
    print(f"✓ Workflow '{workflow_def.name}' is valid")
    print(f"  Checkpoint prefix: {workflow_def.config.checkpoint_prefix}")
    print(f"  Nodes: {len(workflow_def.nodes)}")
    print()

    # Compute execution plan (topological layers)
    layers = topological_sort_with_layers(workflow_def.nodes)

    # Build node map for lookup
    node_map = {node.id: node for node in workflow_def.nodes}

    print("Execution Plan:")
    print("=" * 60)
    for layer_idx, layer_node_ids in enumerate(layers):
        print(f"\nLayer {layer_idx} (parallel execution):")
        for node_id in layer_node_ids:
            node = node_map[node_id]
            deps = f" (depends on: {', '.join(node.depends_on)})" if node.depends_on else ""
            print(f"  - {node.id}: {node.name}{deps}")
            if node.edges:
                for edge in node.edges:
                    if edge.condition:
                        print(f"      -> {edge.target} (when: {edge.condition})")
                    elif edge.default:
                        print(f"      -> {edge.target} (default)")
    print()


def run_visualize(workflow_path: str) -> None:
    """Output mermaid DAG diagram.

    Args:
        workflow_path: Path to workflow YAML file
    """
    from dag_executor.terminal.mermaid_gen import generate_mermaid

    workflow_def = load_workflow(workflow_path)
    print(generate_mermaid(workflow_def))


def print_summary(result: WorkflowResult) -> None:
    """Print workflow execution summary.

    Args:
        result: Workflow execution result
    """
    print()
    print("=" * 60)
    print("Workflow Execution Summary")
    print("=" * 60)
    print(f"Status: {result.status.value}")
    print(f"Run ID: {result.run_id}")
    print(f"Nodes executed: {len(result.node_results)}")
    print()

    # Print node statuses
    for node_summary in result.nodes:
        status_symbol = "✓" if node_summary.status == NodeStatus.COMPLETED else "✗"
        print(f"  {status_symbol} {node_summary.id}: {node_summary.status.value}")
    print()


def _flat_node_order(nodes: List[Any]) -> List[str]:
    """Return a flat topological node order from workflow nodes."""
    layers = topological_sort_with_layers(nodes)
    order: List[str] = []
    for layer in layers:
        order.extend(layer)
    return order


def run_history(argv: List[str]) -> None:
    """Run the ``history`` subcommand.

    ``dag-exec history workflow.yaml [--run-id RUN_ID]``
    """
    parser = argparse.ArgumentParser(prog="dag-exec history")
    parser.add_argument("workflow", help="Path to workflow YAML file")
    parser.add_argument("--run-id", help="Show node checkpoints for a specific run")
    parser.add_argument("--checkpoint-dir", help="Override checkpoint directory")
    args = parser.parse_args(argv)

    workflow_def = load_workflow(args.workflow)
    checkpoint_dir = args.checkpoint_dir or workflow_def.config.checkpoint_prefix
    store = CheckpointStore(checkpoint_dir)

    if args.run_id:
        # Show node checkpoints for a specific run
        nodes = store.load_all_nodes(workflow_def.name, args.run_id)
        node_list = []
        for node_id, cp in sorted(nodes.items()):
            node_list.append({
                "node_id": node_id,
                "status": cp.status.value,
                "content_hash": cp.content_hash,
                "started_at": cp.started_at,
                "completed_at": cp.completed_at,
            })
        print(json.dumps({"workflow_name": workflow_def.name, "run_id": args.run_id, "nodes": node_list}, indent=2))
    else:
        # List all runs
        run_ids = store.list_runs(workflow_def.name)
        runs = []
        for rid in run_ids:
            meta = store.load_metadata(workflow_def.name, rid)
            nodes = store.load_all_nodes(workflow_def.name, rid)
            runs.append({
                "run_id": rid,
                "status": meta.status if meta else "unknown",
                "started_at": meta.started_at if meta else "",
                "node_count": len(nodes),
            })
        print(json.dumps({"workflow_name": workflow_def.name, "runs": runs}, indent=2))


def run_inspect(argv: List[str]) -> None:
    """Run the ``inspect`` subcommand.

    ``dag-exec inspect workflow.yaml --run-id RUN_ID [--node NODE_ID]``
    """
    parser = argparse.ArgumentParser(prog="dag-exec inspect")
    parser.add_argument("workflow", help="Path to workflow YAML file")
    parser.add_argument("--run-id", required=True, help="Run ID to inspect")
    parser.add_argument("--node", help="Specific node ID to inspect")
    parser.add_argument("--checkpoint-dir", help="Override checkpoint directory")
    args = parser.parse_args(argv)

    workflow_def = load_workflow(args.workflow)
    checkpoint_dir = args.checkpoint_dir or workflow_def.config.checkpoint_prefix
    store = CheckpointStore(checkpoint_dir)

    meta = store.load_metadata(workflow_def.name, args.run_id)
    if not meta:
        print(json.dumps({"error": f"No metadata found for run '{args.run_id}'"}), file=sys.stderr)
        sys.exit(1)

    if args.node:
        # Dump full NodeCheckpoint for the specific node
        cp = store.load_node(workflow_def.name, args.run_id, args.node)
        if not cp:
            print(json.dumps({"error": f"No checkpoint for node '{args.node}'"}), file=sys.stderr)
            sys.exit(1)
        print(json.dumps(cp.model_dump(), indent=2))
    else:
        # Dump metadata + all node summaries
        nodes = store.load_all_nodes(workflow_def.name, args.run_id)
        node_summaries = []
        for node_id, cp in sorted(nodes.items()):
            node_summaries.append({
                "node_id": node_id,
                "status": cp.status.value,
                "content_hash": cp.content_hash,
            })
        output = meta.model_dump()
        output["nodes"] = node_summaries
        print(json.dumps(output, indent=2))


def run_rerun(argv: List[str]) -> None:
    """Run the ``rerun`` subcommand.

    ``dag-exec rerun RUN_ID --workflow WORKFLOW_PATH [--db-path DB_PATH] [--remote URL]``
    """
    parser = argparse.ArgumentParser(prog="dag-exec rerun")
    parser.add_argument("run_id", help="Prior run ID to rerun")
    parser.add_argument("--workflow", help="Path to workflow file (required for local mode)")
    parser.add_argument("--db-path", default=str(Path.home() / ".dag-dashboard" / "dashboard.db"),
                        help="Path to dashboard database (default: ~/.dag-dashboard/dashboard.db)")
    parser.add_argument("--remote", help="Remote dashboard URL (for remote mode)")

    args = parser.parse_args(argv)

    # Remote mode: POST to API
    if args.remote:
        try:
            import urllib.request
            url = f"{args.remote.rstrip('/')}/api/workflows/{args.run_id}/rerun"
            req = urllib.request.Request(
                url,
                data=json.dumps({}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req) as response:
                result = json.loads(response.read().decode("utf-8"))
            print(f"Rerun started: {result['run_id']}")
            sys.exit(0)
        except Exception as e:
            print(f"Error calling remote API: {e}", file=sys.stderr)
            sys.exit(1)

    # Local mode: Read DB and spawn subprocess
    if not args.workflow:
        print("Error: --workflow is required for local mode", file=sys.stderr)
        sys.exit(1)

    db_path = Path(args.db_path)
    if not db_path.exists():
        print(f"Database not found: {db_path}", file=sys.stderr)
        sys.exit(1)

    # Load prior run from DB
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT workflow_name, inputs FROM workflow_runs WHERE id = ?",
            (args.run_id,)
        )
        row = cursor.fetchone()
        conn.close()

        if not row:
            print(f"Run not found: {args.run_id}", file=sys.stderr)
            sys.exit(1)

        workflow_name = row[0]
        prior_inputs = json.loads(row[1]) if row[1] else {}

    except Exception as e:
        print(f"Error reading database: {e}", file=sys.stderr)
        sys.exit(1)

    # Generate new run ID and timestamp
    new_run_id = str(uuid.uuid4())
    started_at = datetime.now(timezone.utc).isoformat()

    # Insert new run row with parent_run_id BEFORE spawning subprocess
    try:
        conn = sqlite3.connect(db_path)
        conn.execute(
            """
            INSERT INTO workflow_runs (id, workflow_name, status, started_at, inputs, parent_run_id)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (new_run_id, workflow_name, "running", started_at, json.dumps(prior_inputs), args.run_id)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error inserting run record: {e}", file=sys.stderr)
        sys.exit(1)

    # Build subprocess command
    workflow_path = Path(args.workflow)
    if not workflow_path.exists():
        print(f"Workflow file not found: {workflow_path}", file=sys.stderr)
        sys.exit(1)

    cmd = ["dag-exec", str(workflow_path)]
    for k, v in prior_inputs.items():
        if isinstance(v, (dict, list)):
            cmd.append(f"{k}={json.dumps(v)}")
        else:
            cmd.append(f"{k}={v}")
    cmd.extend(["--run-id", new_run_id])

    # Spawn subprocess
    try:
        subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        print(f"Rerun started: {new_run_id}")
    except Exception as e:
        print(f"Error spawning subprocess: {e}", file=sys.stderr)
        sys.exit(1)


def run_replay(argv: List[str]) -> None:
    """Run the ``replay`` subcommand.

    ``dag-exec replay workflow.yaml --run-id RUN_ID --from-node NODE_ID [--with-override k=v ...]``
    """
    parser = argparse.ArgumentParser(prog="dag-exec replay")
    parser.add_argument("workflow", help="Path to workflow YAML file")
    parser.add_argument("--run-id", required=True, help="Run ID to replay from")
    parser.add_argument("--from-node", required=True, help="Node ID to replay from")
    parser.add_argument("--with-override", action="append", default=[], help="key=value overrides")
    parser.add_argument("--checkpoint-dir", help="Override checkpoint directory")
    args = parser.parse_args(argv)

    workflow_def = load_workflow(args.workflow)
    checkpoint_dir = args.checkpoint_dir or workflow_def.config.checkpoint_prefix
    store = CheckpointStore(checkpoint_dir)

    # Parse overrides from CLI arguments
    overrides: Dict[str, Any] = {}
    for override in args.with_override:
        if "=" in override:
            key, value = override.split("=", 1)
            try:
                overrides[key] = json.loads(value)
            except json.JSONDecodeError:
                overrides[key] = value

    # Execute replay preparation
    try:
        replay_summary = execute_replay(
            workflow_def=workflow_def,
            store=store,
            run_id=args.run_id,
            from_node=args.from_node,
            overrides=overrides,
        )
    except ValueError as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)

    new_run_id = replay_summary["new_run_id"]

    # Load the updated metadata to get inputs with overrides
    meta = store.load_metadata(workflow_def.name, new_run_id)
    if not meta:
        print(json.dumps({"error": "Failed to load replay metadata"}), file=sys.stderr)
        sys.exit(1)

    # Execute the workflow from the replay checkpoint
    result = resume_workflow(
        workflow_name=workflow_def.name,
        run_id=new_run_id,
        checkpoint_store=store,
        workflow_def=workflow_def,
        inputs=meta.inputs,
    )

    # Print summary
    summary = {
        **replay_summary,
        "status": result.status.value,
        "nodes_executed": len(result.node_results),
    }
    print(json.dumps(summary, indent=2))


def run_cancel(argv: List[str]) -> int:
    """Run the ``cancel`` subcommand.

    ``dag-exec cancel RUN_ID [--events-dir DIR] [--cancelled-by USER]``

    Writes atomic cancel marker to {events_dir}/{run_id}.cancel
    """
    from dag_executor.cancel import InvalidRunIdError, write_cancel_marker

    parser = argparse.ArgumentParser(prog="dag-exec cancel")
    parser.add_argument("run_id", help="Run ID to cancel")
    parser.add_argument("--events-dir", help="Events directory (default: $DAG_EVENTS_DIR or .dag-events)")
    parser.add_argument("--cancelled-by", default="cli", help="User or system that initiated cancel")
    args = parser.parse_args(argv)

    # Determine events_dir: flag > env var > default
    if args.events_dir:
        events_dir = Path(args.events_dir)
    elif "DAG_EVENTS_DIR" in os.environ:
        events_dir = Path(os.environ["DAG_EVENTS_DIR"])
    else:
        events_dir = Path(".dag-events")

    try:
        write_cancel_marker(events_dir, args.run_id, args.cancelled_by)
    except InvalidRunIdError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2

    return 0


def main(argv: Optional[List[str]] = None) -> None:
    """Main CLI entry point.

    Args:
        argv: Argument list (defaults to sys.argv[1:])
    """
    try:
        if argv is None:
            argv = sys.argv[1:]

        if argv and argv[0] in SUBCOMMANDS:
            subcmd = argv[0]
            if subcmd == "history":
                run_history(argv[1:])
                return
            elif subcmd == "inspect":
                run_inspect(argv[1:])
                return
            elif subcmd == "replay":
                run_replay(argv[1:])
                return
            elif subcmd == "cancel":
                run_cancel(argv[1:])
                return
            elif subcmd == "search":
                run_search(argv[1:])
                return
            elif subcmd == "logs":
                from dag_executor.logs import run_logs
                sys.exit(run_logs(argv[1:]))
            elif subcmd == "rerun":
                run_rerun(argv[1:])
                return
            elif subcmd == "gates":
                from dag_executor.cli_gates import run_gates
                run_gates(argv[1:])
                return

        args = parse_args(argv)

        # Subcommand dispatch (list, info)
        subcommand = getattr(args, "subcommand", None)
        if subcommand == "list":
            run_list(args.directory, args.json_output)
            sys.exit(0)
        elif subcommand == "info":
            run_info(args.workflow)
            sys.exit(0)

        # Dry-run mode
        if args.dry_run:
            run_dry_run(args.workflow)
            sys.exit(0)
        
        # Visualize mode
        if args.visualize:
            run_visualize(args.workflow)
            sys.exit(0)
        
        # Load workflow
        workflow_def = load_workflow(args.workflow)

        # Parse inputs
        inputs = parse_inputs(args.inputs)

        # Resolve events_dir from --events-dir flag or DAG_EVENTS_DIR env var.
        # When set, the executor writes {events_dir}/{run_id}.ndjson and polls
        # {events_dir}/{run_id}.cancel for cancellation markers.
        events_dir_str = args.events_dir or os.environ.get("DAG_EVENTS_DIR")
        events_dir: Optional[Path] = None
        if events_dir_str:
            events_dir = Path(events_dir_str)
            events_dir.mkdir(parents=True, exist_ok=True)

        # Resolve run_id. When the caller (e.g. dashboard trigger) supplies one
        # via --run-id, use it so the NDJSON filename, cancel marker path, and
        # the caller's database row all agree. Otherwise generate a fresh UUID.
        import uuid
        from dag_executor.cancel import InvalidRunIdError, validate_run_id
        if args.run_id and not args.resume:
            try:
                validate_run_id(args.run_id)
            except InvalidRunIdError as e:
                print(f"Error: {e}", file=sys.stderr)
                sys.exit(2)
            run_id = args.run_id
        else:
            run_id = str(uuid.uuid4())

        # Setup event emitter if streaming, progress, notifications, or events_dir configured.
        # events_dir forces event logging so the dashboard collector can tail runs.
        event_emitter = None
        progress_bar = None
        notification_unsubscribe = None

        needs_emitter = args.stream or args.progress or events_dir is not None or (
            workflow_def.config.notifications is not None and
            workflow_def.config.notifications.slack is not None
        )

        if needs_emitter:
            log_file = (
                str(events_dir / f"{run_id}.ndjson")
                if events_dir is not None
                else None
            )
            event_emitter = EventEmitter(log_file=log_file)

            if args.stream:
                mode = StreamMode.STATE_UPDATES if args.stream == "state_updates" else StreamMode.ALL

                def _print_event(event: WorkflowEvent) -> None:
                    ts = event.timestamp.strftime("%H:%M:%S")
                    node = f" [{event.node_id}]" if event.node_id else ""
                    print(f"[{ts}]{node} {event.event_type.value}", file=sys.stderr)

                event_emitter.subscribe(_print_event, mode)

            if args.progress:
                from dag_executor.terminal import ProgressBar
                progress_bar = ProgressBar(total_nodes=len(workflow_def.nodes))
                progress_bar.attach(event_emitter)

        # Setup checkpoint store if needed
        checkpoint_store = None
        checkpoint_dir = args.checkpoint_dir or workflow_def.config.checkpoint_prefix
        if checkpoint_dir:
            checkpoint_store = CheckpointStore(checkpoint_dir)

        # Wire up notifications if configured
        if event_emitter and workflow_def.config.notifications:
            from dag_executor.notifications import attach_to
            import tempfile
            # Use checkpoint_dir if available, otherwise temp dir
            if checkpoint_dir:
                db_dir = Path(checkpoint_dir)
            else:
                db_dir = Path(tempfile.mkdtemp())
            db_path = db_dir / "notifications.db"
            notification_unsubscribe = attach_to(
                event_emitter,
                workflow_def.config,
                db_path
            )
        # Resume mode
        try:
            if args.resume:
                if not args.run_id:
                    print("Error: --run-id is required with --resume", file=sys.stderr)
                    sys.exit(1)

                if not checkpoint_store:
                    print("Error: Workflow must have checkpoint_prefix for resume", file=sys.stderr)
                    sys.exit(1)

                print(f"Resuming workflow '{workflow_def.name}' (run: {args.run_id})...")

                # Parse resume values if provided
                resume_values = None
                if args.resume_values:
                    try:
                        resume_values = json.loads(args.resume_values)
                    except json.JSONDecodeError as e:
                        print(f"Error: Invalid JSON in --resume-values: {e}", file=sys.stderr)
                        sys.exit(1)

                result = resume_workflow(
                    workflow_name=workflow_def.name,
                    run_id=args.run_id,
                    checkpoint_store=checkpoint_store,
                    workflow_def=workflow_def,
                    inputs=inputs if inputs else None,
                    resume_values=resume_values,
                    concurrency_limit=args.concurrency,
                    event_emitter=event_emitter,
                )
            else:
                # Normal execution
                print(f"Executing workflow '{workflow_def.name}'...")
                result = execute_workflow(
                    workflow_def=workflow_def,
                    inputs=inputs,
                    concurrency_limit=args.concurrency,
                    checkpoint_store=checkpoint_store,
                    event_emitter=event_emitter,
                    run_id=run_id,
                    events_dir=events_dir,
                )
        finally:
            # Cleanup notification listener if attached
            if notification_unsubscribe:
                notification_unsubscribe()

        # Print summary using new RunSummary, with backward-compatible fallback
        from dag_executor.terminal import RunSummary
        summary = RunSummary.render(result, workflow_def)
        print(summary)

        # Print old-style messages to maintain backward compatibility with tests
        print()
        print("=" * 60)
        print("Workflow Execution Summary")
        print("=" * 60)
        print(f"Status: {result.status.value}")
        print(f"Run ID: {result.run_id}")
        print(f"Nodes executed: {len(result.node_results)}")
        print()

        # Exit with appropriate code
        if result.status == WorkflowStatus.COMPLETED:
            print("Workflow completed successfully")
            sys.exit(0)
        else:
            print(f"Workflow failed with status: {result.status.value}", file=sys.stderr)
            sys.exit(1)
    
    except FileNotFoundError as e:
        print(f"Error: Workflow file not found: {e}", file=sys.stderr)
        sys.exit(1)
    
    except ValueError as e:
        print(f"Error: Invalid workflow: {e}", file=sys.stderr)
        sys.exit(1)
    
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def run_search(argv: List[str]) -> None:
    """Run search subcommand."""
    import argparse
    import json
    import os
    import sqlite3
    from pathlib import Path
    
    parser = argparse.ArgumentParser(prog="dag-exec search")
    parser.add_argument("query", help="Search query string")
    parser.add_argument("--kinds", default="runs,nodes,events", help="Comma-separated kinds")
    parser.add_argument("--limit", type=int, default=50, help="Max results")
    parser.add_argument("--json", dest="json_output", action="store_true", help="JSON output")
    parser.add_argument("--db", type=Path, help="Database path (local mode)")
    parser.add_argument("--remote", help="Remote dashboard URL (remote mode)")
    parser.add_argument("--token", help="Bearer token for remote mode")
    
    args = parser.parse_args(argv)
    
    # Remote mode
    if args.remote:
        import httpx
        
        token = args.token or os.environ.get("DAG_EXEC_SEARCH_TOKEN")
        if not token:
            print("Error: Remote mode requires --token or DAG_EXEC_SEARCH_TOKEN env var", file=sys.stderr)
            sys.exit(2)
        
        url = f"{args.remote.rstrip('/')}/api/search"
        response = httpx.get(
            url,
            params={"q": args.query, "kinds": args.kinds, "limit": args.limit},
            headers={"Authorization": f"Bearer {token}"}
        )
        
        if response.status_code != 200:
            print(f"Error: {response.status_code} {response.text}", file=sys.stderr)
            sys.exit(1)
        
        data = response.json()
        if args.json_output:
            print(json.dumps(data, indent=2))
        else:
            print(f"Found {data['total']} results for '{data['query']}':")
            for r in data['results']:
                print(f"  [{r['kind']}] {r['run_id']}: {r['snippet'][:80]}")
        return
    
    # Local mode
    db_path = args.db
    if not db_path:
        db_dir = Path.home() / ".dag-dashboard"
        db_path = db_dir / "dashboard.db"
    
    if not db_path.exists():
        print(f"Error: Database not found at {db_path}", file=sys.stderr)
        sys.exit(1)
    
    from dag_executor.search_local import search_all
    
    conn = sqlite3.connect(str(db_path))
    try:
        kinds_list = [k.strip() for k in args.kinds.split(",")]
        results = search_all(conn, q=args.query, kinds=kinds_list, limit=args.limit)
        
        if args.json_output:
            print(json.dumps({"query": args.query, "total": len(results), "results": results}, indent=2))
        else:
            print(f"Found {len(results)} results for '{args.query}':")
            for r in results:
                print(f"  [{r['kind']}] {r['run_id']}: {r['snippet'][:80]}")
    finally:
        conn.close()
