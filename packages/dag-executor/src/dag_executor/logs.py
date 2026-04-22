"""Log tailing implementation for dag-exec logs command."""
import json
import sys
import time
from pathlib import Path
from typing import Optional
import argparse


def tail_logs_local(
    run_id: str,
    events_dir: Path,
    node_filter: Optional[str] = None,
    stream_filter: str = "all",
    follow: bool = False
) -> int:
    """Tail logs from local NDJSON file.
    
    Args:
        run_id: Workflow run ID
        events_dir: Directory containing event NDJSON files
        node_filter: Optional node ID to filter logs
        stream_filter: 'all', 'stdout', or 'stderr'
        follow: Whether to follow (tail -f style)
    
    Returns:
        Exit code (0 on success)
    """
    ndjson_path = events_dir / f"{run_id}.ndjson"
    
    if not ndjson_path.exists():
        print(f"Error: Event file not found: {ndjson_path}", file=sys.stderr)
        print(f"Hint: Use --remote <url> to tail from dashboard", file=sys.stderr)
        return 1
    
    # Read existing lines
    try:
        with open(ndjson_path, 'r') as f:
            for line in f:
                _process_log_line(line.strip(), node_filter, stream_filter)
    except Exception as e:
        print(f"Error reading event file: {e}", file=sys.stderr)
        return 1
    
    # Follow mode: tail new lines until workflow completes
    if follow:
        print("Following... (Ctrl+C to stop)", file=sys.stderr)
        with open(ndjson_path, 'r') as f:
            # Seek to end
            f.seek(0, 2)
            
            workflow_terminal = False
            while not workflow_terminal:
                line = f.readline()
                if line:
                    _process_log_line(line.strip(), node_filter, stream_filter)
                    
                    # Check if workflow reached terminal state
                    try:
                        event = json.loads(line)
                        if event.get('event_type') in [
                            'workflow_completed', 'workflow_failed', 
                            'workflow_cancelled', 'workflow_interrupted'
                        ]:
                            workflow_terminal = True
                    except:
                        pass
                else:
                    time.sleep(0.1)
    
    return 0


def _process_log_line(
    line: str,
    node_filter: Optional[str],
    stream_filter: str
) -> None:
    """Process a single event line and print if it's a matching log event."""
    if not line:
        return
    
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        return
    
    # Filter for node_log_line events
    if event.get('event_type') != 'node_log_line':
        return
    
    metadata = event.get('metadata', {})
    node_id = metadata.get('node_id')
    stream = metadata.get('stream')
    log_line = metadata.get('line', '')
    
    # Apply node filter
    if node_filter and node_id != node_filter:
        return
    
    # Apply stream filter
    if stream_filter != 'all' and stream != stream_filter:
        return
    
    # Print formatted log line
    node_label = f"[{node_id}]" if not node_filter else ""
    print(f"[{stream}]{node_label} {log_line}")


def tail_logs_remote(
    run_id: str,
    dashboard_url: str,
    node_filter: Optional[str] = None,
    stream_filter: str = "all",
    follow: bool = False
) -> int:
    """Tail logs from remote dashboard via SSE.
    
    Args:
        run_id: Workflow run ID
        dashboard_url: Dashboard base URL (e.g., http://127.0.0.1:8100)
        node_filter: Optional node ID to filter logs
        stream_filter: 'all', 'stdout', or 'stderr'
        follow: Whether to follow (watch for new events)
    
    Returns:
        Exit code (0 on success)
    """
    try:
        import httpx
        from httpx_sse import connect_sse
    except ImportError:
        print("Error: httpx and httpx-sse required for remote mode", file=sys.stderr)
        print("Install: pip install httpx httpx-sse", file=sys.stderr)
        return 1
    
    # First fetch historical logs via REST
    try:
        with httpx.Client() as client:
            response = client.get(
                f"{dashboard_url}/api/workflows/{run_id}/nodes/{node_filter or 'all'}/logs",
                params={"limit": 500, "stream": stream_filter}
            )
            if response.status_code == 200:
                data = response.json()
                for log_entry in data.get('lines', []):
                    stream = log_entry.get('stream')
                    line = log_entry.get('line')
                    node_label = f"[{node_filter}]" if node_filter else ""
                    print(f"[{stream}]{node_label} {line}")
    except Exception as e:
        print(f"Error fetching historical logs: {e}", file=sys.stderr)
    
    # Follow mode: subscribe to SSE
    if follow:
        print("Following... (Ctrl+C to stop)", file=sys.stderr)
        try:
            with httpx.Client() as client:
                with connect_sse(client, "GET", f"{dashboard_url}/api/workflows/{run_id}/events") as event_source:
                    for sse_event in event_source.iter_sse():
                        try:
                            event = json.loads(sse_event.data)
                            
                            # Check for workflow terminal state
                            if event.get('event_type') in [
                                'workflow_completed', 'workflow_failed',
                                'workflow_cancelled', 'workflow_interrupted'
                            ]:
                                break
                            
                            # Process log lines
                            if event.get('event_type') == 'node_log_line':
                                metadata = event.get('metadata', {})
                                node_id = metadata.get('node_id')
                                stream = metadata.get('stream')
                                log_line = metadata.get('line', '')
                                
                                # Apply filters
                                if node_filter and node_id != node_filter:
                                    continue
                                if stream_filter != 'all' and stream != stream_filter:
                                    continue
                                
                                node_label = f"[{node_id}]" if not node_filter else ""
                                print(f"[{stream}]{node_label} {log_line}")
                        except Exception:
                            pass
        except KeyboardInterrupt:
            print("\nStopped", file=sys.stderr)
        except Exception as e:
            print(f"Error following logs: {e}", file=sys.stderr)
            return 1
    
    return 0


def run_logs(argv: list[str]) -> int:
    """Entry point for dag-exec logs subcommand."""
    parser = argparse.ArgumentParser(
        prog="dag-exec logs",
        description="Tail workflow execution logs"
    )
    parser.add_argument("run_id", help="Workflow run ID")
    parser.add_argument("--node", help="Filter by node ID")
    parser.add_argument("--stream", choices=["all", "stdout", "stderr"], default="all",
                        help="Filter by stream (default: all)")
    parser.add_argument("--follow", "-f", action="store_true",
                        help="Follow log output (tail -f style)")
    parser.add_argument("--events-dir", type=Path, 
                        default=Path.home() / ".dag-executor" / "events",
                        help="Events directory for local mode")
    parser.add_argument("--remote", help="Dashboard URL for remote mode (e.g., http://127.0.0.1:8100)")
    
    args = parser.parse_args(argv)
    
    if args.remote:
        return tail_logs_remote(
            args.run_id,
            args.remote,
            node_filter=args.node,
            stream_filter=args.stream,
            follow=args.follow
        )
    else:
        return tail_logs_local(
            args.run_id,
            args.events_dir,
            node_filter=args.node,
            stream_filter=args.stream,
            follow=args.follow
        )
