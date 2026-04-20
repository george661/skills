"""CLI entry point for DAG executor."""
import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from dag_executor import (
    load_workflow,
    execute_workflow,
    resume_workflow,
    topological_sort_with_layers,
    CheckpointStore,
    CheckpointMetadata,
    WorkflowResult,
    WorkflowEvent,
    NodeStatus,
    WorkflowStatus,
    EventEmitter,
    StreamMode,
)
from dag_executor.validator import WorkflowValidator

SUBCOMMANDS = {"replay", "history", "inspect"}


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
    """List all valid workflows in a directory.

    Scans for .yaml files, attempts to parse each as a WorkflowDef,
    and displays a catalog of valid workflows.

    Args:
        directory: Directory to scan
        json_output: If True, output as JSON
    """
    from pathlib import Path

    scan_dir = Path(directory)
    if not scan_dir.is_dir():
        print(f"Error: '{directory}' is not a directory", file=sys.stderr)
        sys.exit(1)

    workflows: List[Dict[str, Any]] = []
    for yaml_file in sorted(scan_dir.glob("*.yaml")):
        try:
            wf = load_workflow(str(yaml_file))
            workflows.append({
                "file": yaml_file.name,
                "name": wf.name,
                "nodes": len(wf.nodes),
                "inputs": list(wf.inputs.keys()),
                "checkpoint_prefix": wf.config.checkpoint_prefix,
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
        help="Run ID to resume (required with --resume)",
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
    workflow_def = load_workflow(workflow_path)
    
    print("```mermaid")
    print("graph TD")
    
    # Output nodes
    for node in workflow_def.nodes:
        # Use node.name if available, otherwise node.id
        label = node.name or node.id
        print(f"    {node.id}[{label}]")
    
    # Output dependency edges
    for node in workflow_def.nodes:
        if node.depends_on:
            for dep in node.depends_on:
                print(f"    {dep} --> {node.id}")

    # Output conditional edges
    for node in workflow_def.nodes:
        if node.edges:
            for edge in node.edges:
                if edge.condition:
                    print(f"    {node.id} -->|{edge.condition}| {edge.target}")
                elif edge.default:
                    print(f"    {node.id} -->|default| {edge.target}")

    print("```")


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

    # 1. Load existing metadata
    meta = store.load_metadata(workflow_def.name, args.run_id)
    if not meta:
        print(json.dumps({"error": f"No metadata found for run '{args.run_id}'"}), file=sys.stderr)
        sys.exit(1)

    # 2. Compute topological node order
    node_order = _flat_node_order(workflow_def.nodes)

    # 3. Generate new run_id
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    new_run_id = f"{args.run_id}-replay-{ts}"

    # 4. Copy the run checkpoint directory to the new run_id directory
    original_dir = store._get_run_dir(workflow_def.name, args.run_id)
    new_dir = store._get_run_dir(workflow_def.name, new_run_id)
    shutil.copytree(str(original_dir), str(new_dir))

    # 5. Clear nodes after --from-node
    cleared = store.clear_nodes_after(workflow_def.name, new_run_id, args.from_node, node_order)

    # 6. Update metadata with new run_id and status
    new_meta = CheckpointMetadata(
        workflow_name=meta.workflow_name,
        run_id=new_run_id,
        started_at=meta.started_at,
        inputs=meta.inputs.copy(),
        status="running",
    )

    # 7. Apply overrides
    for override in args.with_override:
        if "=" in override:
            key, value = override.split("=", 1)
            try:
                new_meta.inputs[key] = json.loads(value)
            except json.JSONDecodeError:
                new_meta.inputs[key] = value

    # 8. Save updated metadata
    store.save_metadata(workflow_def.name, new_run_id, new_meta)

    # 9. Execute via resume_workflow
    result = resume_workflow(
        workflow_name=workflow_def.name,
        run_id=new_run_id,
        checkpoint_store=store,
        workflow_def=workflow_def,
        inputs=new_meta.inputs,
    )

    # 10. Print summary
    summary = {
        "new_run_id": new_run_id,
        "parent_run_id": args.run_id,
        "replayed_from": args.from_node,
        "nodes_cleared": cleared,
        "status": result.status.value,
        "nodes_executed": len(result.node_results),
    }
    print(json.dumps(summary, indent=2))


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
                return run_history(argv[1:])
            elif subcmd == "inspect":
                return run_inspect(argv[1:])
            elif subcmd == "replay":
                return run_replay(argv[1:])

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

        # Setup event emitter if streaming or notifications configured
        event_emitter = None
        notification_unsubscribe = None

        # Check if notifications configured
        needs_emitter = args.stream or (
            workflow_def.config.notifications is not None and
            workflow_def.config.notifications.slack is not None
        )

        if needs_emitter:
            event_emitter = EventEmitter()

            # Wire up streaming if requested
            if args.stream:
                mode = StreamMode.STATE_UPDATES if args.stream == "state_updates" else StreamMode.ALL

                def _print_event(event: WorkflowEvent) -> None:
                    ts = event.timestamp.strftime("%H:%M:%S")
                    node = f" [{event.node_id}]" if event.node_id else ""
                    print(f"[{ts}]{node} {event.event_type.value}", file=sys.stderr)

                event_emitter.subscribe(_print_event, mode)

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
                )
        finally:
            # Cleanup notification listener if attached
            if notification_unsubscribe:
                notification_unsubscribe()

        # Print summary
        print_summary(result)

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
