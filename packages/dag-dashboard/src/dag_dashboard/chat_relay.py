"""Chat relay for named pipe communication with agents."""
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

from .database import ensure_dir
from .queries import insert_chat_message


class ChatRelay:
    """Manages named pipes for operator-agent chat communication.

    Creates and manages named pipes at {pipe_root}/{run_id}/{node_id}.{in,out}.
    - .in pipe: operator messages written here, read by agent
    - .out pipe: agent responses written here, read by ChatRelay
    """

    def __init__(self, db_path: Path, pipe_root: Path):
        """Initialize ChatRelay.

        Args:
            db_path: Path to SQLite database for message persistence
            pipe_root: Root directory for named pipes
        """
        self.db_path = db_path
        self.pipe_root = pipe_root
        self._readers: Dict[str, threading.Thread] = {}
        self._stop_flags: Dict[str, threading.Event] = {}

    def ensure_pipes(self, run_id: str, node_id: str) -> None:
        """Create named pipes for a run/node if they don't exist.

        Args:
            run_id: Workflow run ID
            node_id: Node execution ID
        """
        pipe_dir = self.pipe_root / run_id
        ensure_dir(pipe_dir)

        in_pipe = pipe_dir / f"{node_id}.in"
        out_pipe = pipe_dir / f"{node_id}.out"

        # Create pipes if they don't exist
        for pipe_path in [in_pipe, out_pipe]:
            if not pipe_path.exists():
                os.mkfifo(pipe_path)
                os.chmod(pipe_path, 0o600)

    def write_to_agent(self, run_id: str, node_id: str, message: str) -> None:
        """Write a message to the agent's input pipe.

        Args:
            run_id: Workflow run ID
            node_id: Node execution ID
            message: Message content to send to agent
        """
        in_pipe = self.pipe_root / run_id / f"{node_id}.in"
        
        # Write to pipe (non-blocking)
        with open(in_pipe, "w") as f:
            f.write(message)
            f.write("\n")

    def start_reading(self, run_id: str, node_id: str, execution_id: str) -> None:
        """Start reading agent responses from the output pipe in a background thread.

        Args:
            run_id: Workflow run ID
            node_id: Node execution ID
            execution_id: Node execution ID for DB persistence
        """
        reader_key = f"{run_id}/{node_id}"
        
        if reader_key in self._readers:
            return  # Already reading
        
        stop_flag = threading.Event()
        self._stop_flags[reader_key] = stop_flag
        
        def read_loop():
            out_pipe = self.pipe_root / run_id / f"{node_id}.out"
            
            while not stop_flag.is_set():
                try:
                    # Open pipe for reading (blocking until writer connects)
                    with open(out_pipe, "r") as f:
                        content = f.read()
                        
                        if content and not stop_flag.is_set():
                            # Persist agent response
                            now = datetime.now(timezone.utc).isoformat()
                            insert_chat_message(
                                self.db_path,
                                execution_id=execution_id,
                                role="agent",
                                content=content,
                                created_at=now,
                                run_id=run_id
                            )
                except Exception:
                    # Ignore errors (e.g., pipe closed during shutdown)
                    if not stop_flag.is_set():
                        break
        
        reader_thread = threading.Thread(target=read_loop, daemon=True)
        reader_thread.start()
        self._readers[reader_key] = reader_thread

    def stop(self) -> None:
        """Stop all reader threads and clean up."""
        # Signal all readers to stop
        for stop_flag in self._stop_flags.values():
            stop_flag.set()
        
        # Wait for readers to finish (with timeout)
        for thread in self._readers.values():
            thread.join(timeout=1.0)
        
        self._readers.clear()
        self._stop_flags.clear()
