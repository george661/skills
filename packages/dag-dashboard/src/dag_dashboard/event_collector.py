"""Filesystem watcher for NDJSON event files."""
import asyncio
import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from .broadcast import Broadcaster

logger = logging.getLogger(__name__)


class EventCollector:
    """Watches NDJSON files and persists events to SQLite + broadcasts."""

    def __init__(
        self,
        events_dir: Path,
        db_path: Path,
        broadcaster: Broadcaster,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        """
        Initialize event collector.
        
        Args:
            events_dir: Directory containing {run_id}.ndjson files
            db_path: Path to SQLite database
            broadcaster: Broadcaster instance for real-time event distribution
            loop: Event loop for async bridge (run_coroutine_threadsafe)
        """
        self.events_dir = events_dir
        self.db_path = db_path
        self.broadcaster = broadcaster
        self.loop = loop
        self.observer = Observer()
        self._file_positions: Dict[str, int] = {}
        
        # Create event handler
        handler = _EventFileHandler(self)
        self.observer.schedule(handler, str(events_dir), recursive=False)  # type: ignore[no-untyped-call]

    def start(self) -> None:
        """Start watching the events directory."""
        self.observer.start()  # type: ignore[no-untyped-call]
        logger.info(f"Event collector started watching {self.events_dir}")

    def stop(self) -> None:
        """Stop watching the events directory."""
        self.observer.stop()  # type: ignore[no-untyped-call]
        self.observer.join(timeout=2.0)
        logger.info("Event collector stopped")

    def _process_file(self, file_path: Path) -> None:
        """
        Process NDJSON file: tail from last position, persist, and broadcast.
        
        Called from watchdog thread (synchronous).
        """
        if not file_path.name.endswith(".ndjson"):
            return
        
        run_id = file_path.stem
        
        # Handle file deletion or recreation
        if not file_path.exists():
            logger.warning(f"File {file_path} deleted, resetting position")
            self._file_positions.pop(str(file_path), None)
            return
        
        # Get current file size and last position
        current_size = file_path.stat().st_size
        last_position = self._file_positions.get(str(file_path), 0)
        
        # If file was truncated or recreated, reset position
        if current_size < last_position:
            logger.info(f"File {file_path} truncated or recreated, resetting position")
            last_position = 0
        
        # Read new lines from last position
        try:
            with open(file_path, "r") as f:
                f.seek(last_position)
                new_lines = f.readlines()
                new_position = f.tell()
            
            # Update position
            self._file_positions[str(file_path)] = new_position
            
            # Process each line
            for line in new_lines:
                line = line.strip()
                if not line:
                    continue
                
                try:
                    event_data = json.loads(line)
                    self._persist_and_broadcast(run_id, event_data)
                except json.JSONDecodeError as e:
                    logger.warning(f"Skipping malformed JSON in {file_path}: {e}")
                    continue
                except Exception as e:
                    logger.error(f"Error processing event from {file_path}: {e}")
                    continue
        
        except Exception as e:
            logger.error(f"Error reading file {file_path}: {e}")

    def _persist_and_broadcast(self, run_id: str, event_data: Dict[str, Any]) -> None:
        """
        Persist event to SQLite and broadcast to subscribers.

        Runs in watchdog thread (synchronous).
        """
        # Extract fields from event
        workflow_name = event_data.get("workflow_name", "unknown")
        event_type = event_data.get("event_type", "unknown")

        # Serialize payload to JSON string if it's a dict
        raw_payload = event_data.get("payload", {})
        if isinstance(raw_payload, dict):
            payload = json.dumps(raw_payload)
        elif isinstance(raw_payload, str):
            payload = raw_payload
        else:
            payload = json.dumps({"value": raw_payload})

        created_at = event_data.get("created_at", datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))

        # Persist to SQLite
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")

            # Handle workflow_started event: store workflow definition and create node stubs
            if event_type == "workflow_started":
                workflow_definition = raw_payload.get("workflow_definition") if isinstance(raw_payload, dict) else None

                # Insert workflow_runs row with workflow_definition (use INSERT OR IGNORE + UPDATE to avoid cascade delete)
                cursor.execute(
                    """
                    INSERT OR IGNORE INTO workflow_runs (id, workflow_name, status, started_at, workflow_definition)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (run_id, workflow_name, "running", created_at, workflow_definition)
                )
                cursor.execute(
                    """
                    UPDATE workflow_runs
                    SET workflow_definition = ?, status = ?, started_at = ?
                    WHERE id = ? AND workflow_definition IS NULL
                    """,
                    (workflow_definition, "running", created_at, run_id)
                )

                # Parse workflow definition to extract nodes and their dependencies
                if workflow_definition:
                    try:
                        import yaml
                        workflow_dict = yaml.safe_load(workflow_definition)
                        nodes = workflow_dict.get("nodes", [])

                        # Create node_executions entries for each node with depends_on
                        for node in nodes:
                            node_name = node.get("name")
                            depends_on = node.get("depends_on", [])
                            node_id = f"{run_id}:{node_name}"

                            cursor.execute(
                                """
                                INSERT OR IGNORE INTO node_executions
                                (id, run_id, node_name, status, started_at, depends_on)
                                VALUES (?, ?, ?, ?, ?, ?)
                                """,
                                (node_id, run_id, node_name, "pending", created_at, json.dumps(depends_on))
                            )
                    except Exception as e:
                        logger.warning(f"Failed to parse workflow definition for {run_id}: {e}")
            else:
                # Ensure workflow_runs row exists (INSERT OR IGNORE)
                cursor.execute(
                    """
                    INSERT OR IGNORE INTO workflow_runs (id, workflow_name, status, started_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (run_id, workflow_name, "running", created_at)
                )

            # Insert event
            cursor.execute(
                """
                INSERT INTO events (run_id, event_type, payload, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (run_id, event_type, payload, created_at)
            )

            conn.commit()
        finally:
            conn.close()

        # Broadcast to subscribers (async bridge from sync thread)
        broadcast_event = {
            "event_type": event_type,
            "payload": payload,
            "created_at": created_at
        }

        asyncio.run_coroutine_threadsafe(
            self.broadcaster.publish(run_id, broadcast_event),
            self.loop
        )


class _EventFileHandler(FileSystemEventHandler):
    """Watchdog event handler for NDJSON files."""

    def __init__(self, collector: EventCollector) -> None:
        """Initialize with reference to collector."""
        self.collector = collector

    def on_modified(self, event: FileSystemEvent) -> None:
        """Handle file modification events."""
        if event.is_directory:
            return
        
        file_path = Path(event.src_path)
        self.collector._process_file(file_path)

    def on_created(self, event: FileSystemEvent) -> None:
        """Handle file creation events."""
        if event.is_directory:
            return
        
        file_path = Path(event.src_path)
        self.collector._process_file(file_path)
