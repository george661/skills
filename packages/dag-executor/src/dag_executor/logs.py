"""Log tailing implementation for ``dag-exec logs`` command.

Reads NODE_LOG_LINE events (WorkflowEvent shape):
    {"event_type": "node_log_line",
     "node_id": "<node>",
     "metadata": {"sequence": <int>, "stream": "stdout|stderr", "line": "<text>"},
     "timestamp": "..."}

``node_id`` is top-level; ``sequence``/``stream``/``line`` are under ``metadata``.
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional


_TERMINAL_EVENTS = {
    "workflow_completed",
    "workflow_failed",
    "workflow_cancelled",
    "workflow_interrupted",
}


def _default_events_dir() -> Path:
    """Resolve events dir: $DAG_EVENTS_DIR env > ``./.dag-events`` (matches cancel subcommand)."""
    env = os.environ.get("DAG_EVENTS_DIR")
    return Path(env) if env else Path(".dag-events")


def _emit(event: Dict[str, Any], node_filter: Optional[str], stream_filter: str) -> bool:
    """Emit a single log line if it matches filters. Returns True on terminal event."""
    event_type = event.get("event_type")

    if event_type in _TERMINAL_EVENTS:
        return True

    if event_type != "node_log_line":
        return False

    node_id = event.get("node_id")
    metadata = event.get("metadata") or {}
    stream = metadata.get("stream")
    log_line = metadata.get("line", "")

    if node_filter and node_id != node_filter:
        return False
    if stream_filter != "all" and stream != stream_filter:
        return False

    node_label = "" if node_filter else f"[{node_id}]"
    print(f"[{stream}]{node_label} {log_line}")
    return False


def _process_log_line(
    line: str,
    node_filter: Optional[str],
    stream_filter: str,
) -> bool:
    """Parse and emit one NDJSON line. Returns True if workflow reached terminal state."""
    if not line:
        return False
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        return False
    return _emit(event, node_filter, stream_filter)


def tail_logs_local(
    run_id: str,
    events_dir: Path,
    node_filter: Optional[str] = None,
    stream_filter: str = "all",
    follow: bool = False,
) -> int:
    """Tail logs from ``{events_dir}/{run_id}.ndjson``."""
    ndjson_path = events_dir / f"{run_id}.ndjson"

    if not ndjson_path.exists():
        print(f"Error: Event file not found: {ndjson_path}", file=sys.stderr)
        print("Hint: pass --events-dir or use --remote <url> to tail from dashboard", file=sys.stderr)
        return 1

    workflow_terminal = False
    try:
        with open(ndjson_path, "r") as f:
            for raw in f:
                if _process_log_line(raw.strip(), node_filter, stream_filter):
                    workflow_terminal = True
    except OSError as e:
        print(f"Error reading event file: {e}", file=sys.stderr)
        return 1

    if not follow or workflow_terminal:
        return 0

    print("Following... (Ctrl+C to stop)", file=sys.stderr)
    try:
        with open(ndjson_path, "r") as f:
            f.seek(0, 2)  # seek to end
            while not workflow_terminal:
                raw = f.readline()
                if raw:
                    if _process_log_line(raw.strip(), node_filter, stream_filter):
                        workflow_terminal = True
                else:
                    time.sleep(0.1)
    except KeyboardInterrupt:
        print("\nStopped", file=sys.stderr)
    return 0


def tail_logs_remote(
    run_id: str,
    dashboard_url: str,
    node_filter: Optional[str] = None,
    stream_filter: str = "all",
    follow: bool = False,
) -> int:
    """Tail logs from a running dashboard over SSE (and historical REST if ``--node`` is set)."""
    try:
        import httpx
        from httpx_sse import connect_sse
    except ImportError:
        print("Error: httpx and httpx-sse required for remote mode", file=sys.stderr)
        print("Install: pip install httpx httpx-sse", file=sys.stderr)
        return 1

    # Historical fetch requires a node: the REST endpoint is per-node
    # (/api/workflows/{run_id}/nodes/{node_id}/logs). If --node isn't given,
    # skip the historical pass and fall straight to SSE (live only).
    if node_filter:
        try:
            with httpx.Client() as client:
                resp = client.get(
                    f"{dashboard_url}/api/workflows/{run_id}/nodes/{node_filter}/logs",
                    params={"limit": 500, "stream": stream_filter},
                )
                if resp.status_code == 200:
                    for entry in resp.json().get("lines", []):
                        stream = entry.get("stream")
                        log_line = entry.get("line", "")
                        print(f"[{stream}] {log_line}")
                elif resp.status_code != 404:
                    print(f"Warning: historical fetch returned {resp.status_code}", file=sys.stderr)
        except httpx.HTTPError as e:
            print(f"Error fetching historical logs: {e}", file=sys.stderr)
    elif not follow:
        print(
            "Error: remote mode without --follow requires --node <name>",
            file=sys.stderr,
        )
        print(
            "Hint: the REST endpoint is per-node; use --follow to stream all nodes via SSE",
            file=sys.stderr,
        )
        return 2

    if not follow:
        return 0

    print("Following... (Ctrl+C to stop)", file=sys.stderr)
    try:
        with httpx.Client(timeout=None) as client:
            with connect_sse(client, "GET", f"{dashboard_url}/api/workflows/{run_id}/events") as source:
                for sse_event in source.iter_sse():
                    try:
                        event = json.loads(sse_event.data)
                    except json.JSONDecodeError:
                        continue

                    # Dashboard wraps events as {"event_type": ..., "payload": <json-string>, ...}
                    # where payload is the serialized WorkflowEvent. Unwrap if present.
                    payload = event.get("payload")
                    if isinstance(payload, str):
                        try:
                            event = json.loads(payload)
                        except json.JSONDecodeError:
                            continue

                    if _emit(event, node_filter, stream_filter):
                        break
    except KeyboardInterrupt:
        print("\nStopped", file=sys.stderr)
    except httpx.HTTPError as e:
        print(f"Error following logs: {e}", file=sys.stderr)
        return 1

    return 0


def run_logs(argv: "list[str]") -> int:
    """Entry point for ``dag-exec logs`` subcommand."""
    parser = argparse.ArgumentParser(
        prog="dag-exec logs",
        description="Tail workflow execution logs",
    )
    parser.add_argument("run_id", help="Workflow run ID")
    parser.add_argument("--node", help="Filter by node ID")
    parser.add_argument(
        "--stream",
        choices=["all", "stdout", "stderr"],
        default="all",
        help="Filter by stream (default: all)",
    )
    parser.add_argument(
        "--follow", "-f",
        action="store_true",
        help="Follow log output (tail -f style); exits on workflow terminal state",
    )
    parser.add_argument(
        "--events-dir",
        type=Path,
        default=None,
        help="Events directory for local mode (default: $DAG_EVENTS_DIR or ./.dag-events)",
    )
    parser.add_argument(
        "--remote",
        help="Dashboard URL for remote mode (e.g., http://127.0.0.1:8100)",
    )

    args = parser.parse_args(argv)

    if args.remote:
        return tail_logs_remote(
            args.run_id,
            args.remote,
            node_filter=args.node,
            stream_filter=args.stream,
            follow=args.follow,
        )

    events_dir = args.events_dir if args.events_dir else _default_events_dir()
    return tail_logs_local(
        args.run_id,
        events_dir,
        node_filter=args.node,
        stream_filter=args.stream,
        follow=args.follow,
    )
