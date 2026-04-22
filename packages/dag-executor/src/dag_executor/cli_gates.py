"""Gates CLI subcommand for listing and approving/rejecting workflow gates."""
import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

from dag_executor.checkpoint import CheckpointStore
from dag_executor.gates import build_approval_resolved_event


def run_gates(argv: list[str]) -> None:
    """Entry point for gates subcommand."""
    parser = argparse.ArgumentParser(
        prog="dag-exec gates",
        description="Manage workflow gates (approve/reject interrupts)",
    )
    subparsers = parser.add_subparsers(dest="action", help="Action to perform")

    # gates list
    list_parser = subparsers.add_parser("list", help="List pending gates for a run")
    list_parser.add_argument("run_id", help="Workflow run ID")
    list_parser.add_argument("--events-dir", help="Events directory (local mode)")
    list_parser.add_argument("--db-path", help="Database path (local mode)")
    list_parser.add_argument("--remote", help="Dashboard URL (remote mode)")
    list_parser.add_argument("--token", help="Bearer token for remote mode")
    list_parser.add_argument("--json", action="store_true", help="Output as JSON")

    # gates approve
    approve_parser = subparsers.add_parser("approve", help="Approve a gate")
    approve_parser.add_argument("run_id", help="Workflow run ID")
    approve_parser.add_argument("node_id", help="Node ID")
    approve_parser.add_argument("--comment", help="Optional comment")
    approve_parser.add_argument("--events-dir", help="Events directory (local mode)")
    approve_parser.add_argument("--checkpoint-dir", help="Checkpoint directory (local mode)")
    approve_parser.add_argument("--workflow-name", help="Workflow name (local mode)")
    approve_parser.add_argument("--db-path", help="Database path (local mode)")
    approve_parser.add_argument("--remote", help="Dashboard URL (remote mode)")
    approve_parser.add_argument("--token", help="Bearer token for remote mode")

    # gates reject
    reject_parser = subparsers.add_parser("reject", help="Reject a gate")
    reject_parser.add_argument("run_id", help="Workflow run ID")
    reject_parser.add_argument("node_id", help="Node ID")
    reject_parser.add_argument("--comment", help="Optional comment")
    reject_parser.add_argument("--events-dir", help="Events directory (local mode)")
    reject_parser.add_argument("--checkpoint-dir", help="Checkpoint directory (local mode)")
    reject_parser.add_argument("--workflow-name", help="Workflow name (local mode)")
    reject_parser.add_argument("--db-path", help="Database path (local mode)")
    reject_parser.add_argument("--remote", help="Dashboard URL (remote mode)")
    reject_parser.add_argument("--token", help="Bearer token for remote mode")

    if not argv or argv[0] in ["-h", "--help"]:
        parser.print_help()
        sys.exit(0)

    args = parser.parse_args(argv)

    if args.action == "list":
        run_gates_list(args)
    elif args.action == "approve":
        run_gates_approve_or_reject(args, decision="approved")
    elif args.action == "reject":
        run_gates_approve_or_reject(args, decision="rejected")
    else:
        parser.print_help()
        sys.exit(1)


def run_gates_list(args: argparse.Namespace) -> None:
    """List pending gates for a run."""
    if args.remote:
        # Remote mode: call API
        url = f"{args.remote}/api/workflows/{args.run_id}/gates"
        headers = {}
        if args.token:
            headers["Authorization"] = f"Bearer {args.token}"

        try:
            response = httpx.get(url, headers=headers, timeout=10.0)
            response.raise_for_status()
            data = response.json()

            if args.json:
                print(json.dumps(data, indent=2))
            else:
                gates = data.get("gates", [])
                if not gates:
                    print(f"No pending gates for run {args.run_id}")
                else:
                    print(f"Pending gates for run {args.run_id}:")
                    for gate in gates:
                        print(f"  - {gate['node_name']} (started: {gate.get('started_at', 'N/A')})")
        except httpx.HTTPError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        # Local mode: read from database
        import sqlite3
        from pathlib import Path

        # Get db_path from flag or env var
        db_path = args.db_path if hasattr(args, 'db_path') and args.db_path else os.environ.get(
            "DAG_DASHBOARD_DB", str(Path.home() / ".dag-dashboard" / "dashboard.db")
        )

        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """
                SELECT ne.node_name, ne.started_at, ne.depends_on, ne.inputs
                FROM node_executions ne
                JOIN workflow_runs wr ON ne.run_id = wr.id
                WHERE ne.status = 'interrupted'
                AND wr.status = 'running'
                AND ne.run_id = ?
                ORDER BY ne.started_at
                """,
                (args.run_id,)
            )
            gates = [dict(row) for row in cursor.fetchall()]
            conn.close()

            if not gates:
                print(f"No pending gates for run {args.run_id}")
            else:
                print(f"Pending gates for run {args.run_id}:")
                for gate in gates:
                    print(f"  - {gate['node_name']} (started: {gate.get('started_at', 'N/A')})")
                    # Show upstream context if available
                    if gate.get('depends_on'):
                        print(f"    depends_on: {gate['depends_on']}")
                    if gate.get('inputs'):
                        print(f"    inputs: {gate['inputs'][:100]}...")  # Show first 100 chars
        except Exception as e:
            print(f"Error reading local database: {e}", file=sys.stderr)
            sys.exit(1)


def run_gates_approve_or_reject(args: argparse.Namespace, decision: str) -> None:
    """Approve or reject a gate."""
    if args.remote:
        # Remote mode: POST to API
        url = f"{args.remote}/api/workflows/{args.run_id}/gates/{args.node_id}/{decision}"
        headers = {"Content-Type": "application/json"}
        if args.token:
            headers["Authorization"] = f"Bearer {args.token}"

        body = {}
        if args.comment:
            body["comment"] = args.comment

        try:
            response = httpx.post(url, json=body, headers=headers, timeout=10.0)
            response.raise_for_status()
            data = response.json()
            print(f"Gate {decision}: {data['node_name']} by {data['decided_by']}")
        except httpx.HTTPError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        # Local mode: write events directly
        import sqlite3

        events_dir = args.events_dir or os.environ.get("DAG_EVENTS_DIR")
        if not events_dir:
            print(
                "Error: DAG_EVENTS_DIR environment variable or --events-dir flag required for local mode. "
                "Must match the value the workflow ran with.",
                file=sys.stderr
            )
            sys.exit(1)

        events_dir_path = Path(events_dir)
        event_file = events_dir_path / f"{args.run_id}.ndjson"

        if not event_file.exists():
            print(f"Error: Event file not found: {event_file}", file=sys.stderr)
            sys.exit(1)

        # Get decided_by (use OS user)
        decided_by = os.getlogin()

        # Get checkpoint_prefix from flag or env var
        checkpoint_prefix = args.checkpoint_dir if hasattr(args, 'checkpoint_dir') and args.checkpoint_dir else os.environ.get(
            "DAG_CHECKPOINT_PREFIX", os.path.expanduser("~/.dag-executor/checkpoints")
        )

        # Get workflow_name from flag or database
        workflow_name = args.workflow_name if hasattr(args, 'workflow_name') and args.workflow_name else None
        if not workflow_name:
            # Try to load from database
            db_path = args.db_path if hasattr(args, 'db_path') and args.db_path else os.environ.get(
                "DAG_DASHBOARD_DB", str(Path.home() / ".dag-dashboard" / "dashboard.db")
            )
            try:
                conn = sqlite3.connect(db_path)
                cursor = conn.execute("SELECT workflow_name FROM workflow_runs WHERE id = ?", (args.run_id,))
                row = cursor.fetchone()
                conn.close()
                if row:
                    workflow_name = row[0]
            except Exception as e:
                print(f"Warning: Could not load workflow_name from database: {e}", file=sys.stderr)

        # For interrupt nodes, save resume_values
        resume_key = None
        resume_value = True if decision == "approved" else False

        if workflow_name:
            try:
                store = CheckpointStore(checkpoint_prefix)
                interrupt_checkpoint = store.load_interrupt(workflow_name, args.run_id)
                if interrupt_checkpoint and interrupt_checkpoint.resume_key:
                    resume_key = interrupt_checkpoint.resume_key
                    resume_values = {resume_key: resume_value}
                    store.save_resume_values(workflow_name, args.run_id, resume_values)
            except FileNotFoundError:
                # No interrupt checkpoint found - that's OK for gate-type nodes
                pass
            except Exception as e:
                print(f"Warning: Could not save resume_values: {e}", file=sys.stderr)

        # Write gate.decided event (backward compat)
        gate_decided_event = {
            "event_type": "gate.decided",
            "payload": json.dumps({
                "node_name": args.node_id,
                "decision": decision,
                "decided_by": decided_by,
                "comment": args.comment,
            }),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        # Write approval_resolved event (new canonical)
        approval_resolved_event = build_approval_resolved_event(
            run_id=args.run_id,
            node_id=args.node_id,
            decision=decision,
            decided_by=decided_by,
            source="cli",
            resume_key=resume_key,
            resume_value=resume_value,
            comment=args.comment,
        )

        with open(event_file, "a") as f:
            f.write(json.dumps(gate_decided_event) + "\n")
            f.write(json.dumps(approval_resolved_event) + "\n")

        print(f"Gate {decision}: {args.node_id}")
        print(f"Events written to: {event_file}")
