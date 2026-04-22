"""Gates CLI subcommand for listing and approving/rejecting workflow gates."""
import argparse
import json
import os
import sys
from pathlib import Path

import httpx

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
    list_parser.add_argument("--remote", help="Dashboard URL (remote mode)")
    list_parser.add_argument("--token", help="Bearer token for remote mode")
    list_parser.add_argument("--json", action="store_true", help="Output as JSON")

    # gates approve
    approve_parser = subparsers.add_parser("approve", help="Approve a gate")
    approve_parser.add_argument("run_id", help="Workflow run ID")
    approve_parser.add_argument("node_id", help="Node ID")
    approve_parser.add_argument("--comment", help="Optional comment")
    approve_parser.add_argument("--events-dir", help="Events directory (local mode)")
    approve_parser.add_argument("--remote", help="Dashboard URL (remote mode)")
    approve_parser.add_argument("--token", help="Bearer token for remote mode")

    # gates reject
    reject_parser = subparsers.add_parser("reject", help="Reject a gate")
    reject_parser.add_argument("run_id", help="Workflow run ID")
    reject_parser.add_argument("node_id", help="Node ID")
    reject_parser.add_argument("--comment", help="Optional comment")
    reject_parser.add_argument("--events-dir", help="Events directory (local mode)")
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
        # For local mode, we would need db_path. This is a simplified version.
        # In practice, local mode would need --db-path or similar.
        print("Local mode list not yet implemented. Use --remote.", file=sys.stderr)
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

        # Write gate.decided event (backward compat)
        gate_decided_event = {
            "event_type": "gate.decided",
            "payload": json.dumps({
                "node_name": args.node_id,
                "decision": decision,
                "decided_by": decided_by,
                "comment": args.comment,
            }),
            "created_at": "",  # Will be filled by dashboard
        }

        # Write approval_resolved event (new canonical)
        # For CLI local mode, we don't have easy access to checkpoint to get resume_key
        # So we emit with null resume_key/resume_value for gate-type nodes
        # For interrupt nodes, the executor will handle it via the checkpoint
        approval_resolved_event = build_approval_resolved_event(
            run_id=args.run_id,
            node_id=args.node_id,
            decision=decision,
            decided_by=decided_by,
            source="cli",
            resume_key=None,  # Would need checkpoint access
            resume_value=True if decision == "approved" else False,
            comment=args.comment,
        )

        with open(event_file, "a") as f:
            f.write(json.dumps(gate_decided_event) + "\n")
            f.write(json.dumps(approval_resolved_event) + "\n")

        print(f"Gate {decision}: {args.node_id}")
        print(f"Events written to: {event_file}")
