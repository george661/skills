"""CLI entry point for DAG executor."""
import argparse
import json
import sys
from typing import Any, Dict, List, Optional

from dag_executor import (
    load_workflow,
    execute_workflow,
    resume_workflow,
    topological_sort_with_layers,
    CheckpointStore,
    WorkflowResult,
)


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    """Parse CLI arguments.
    
    Args:
        argv: Argument list (defaults to sys.argv[1:])
    
    Returns:
        Parsed arguments namespace
    """
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
    # Load and validate workflow
    workflow_def = load_workflow(workflow_path)
    
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
    
    # Output edges
    for node in workflow_def.nodes:
        if node.depends_on:
            for dep in node.depends_on:
                print(f"    {dep} --> {node.id}")
    
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
        status_symbol = "✓" if node_summary.status.value == "COMPLETED" else "✗"
        print(f"  {status_symbol} {node_summary.id}: {node_summary.status.value}")
    print()


def main(argv: Optional[List[str]] = None) -> None:
    """Main CLI entry point.
    
    Args:
        argv: Argument list (defaults to sys.argv[1:])
    """
    try:
        args = parse_args(argv)
        
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
        
        # Setup checkpoint store if needed
        checkpoint_store = None
        checkpoint_dir = args.checkpoint_dir or workflow_def.config.checkpoint_prefix
        if checkpoint_dir:
            checkpoint_store = CheckpointStore(checkpoint_dir)
        
        # Resume mode
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
            )
        else:
            # Normal execution
            print(f"Executing workflow '{workflow_def.name}'...")
            result = execute_workflow(
                workflow_def=workflow_def,
                inputs=inputs,
                concurrency_limit=args.concurrency,
                checkpoint_store=checkpoint_store,
            )
        
        # Print summary
        print_summary(result)
        
        # Exit with appropriate code
        if result.status.value == "completed":
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
        import traceback
        traceback.print_exc()
        sys.exit(1)
