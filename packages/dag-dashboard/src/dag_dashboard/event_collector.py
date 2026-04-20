"""Filesystem watcher for NDJSON event files."""
import asyncio
import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from .broadcast import Broadcaster
from . import formatter as slack_formatter
from .notifier import SlackNotifier

logger = logging.getLogger(__name__)


class EventCollector:
    """Watches NDJSON files and persists events to SQLite + broadcasts."""

    def __init__(
        self,
        events_dir: Path,
        db_path: Path,
        broadcaster: Broadcaster,
        loop: asyncio.AbstractEventLoop,
        slack_notifier: Optional[SlackNotifier] = None,
        dashboard_url: str = "http://127.0.0.1:8100",
    ) -> None:
        """
        Initialize event collector.

        Args:
            events_dir: Directory containing {run_id}.ndjson files
            db_path: Path to SQLite database
            broadcaster: Broadcaster instance for real-time event distribution
            loop: Event loop for async bridge (run_coroutine_threadsafe)
            slack_notifier: Optional Slack notifier. When set, lifecycle events
                are forwarded to Slack with a card built by ``formatter``.
            dashboard_url: Base URL used in Slack card action links.
        """
        self.events_dir = events_dir
        self.db_path = db_path
        self.broadcaster = broadcaster
        self.loop = loop
        self.slack_notifier = slack_notifier
        self.dashboard_url = dashboard_url
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

        # Store the full event_data as payload (WorkflowEvent has no 'payload' field)
        # This preserves node_id, metadata, timestamp, etc. for queries
        # WorkflowEvent stores channel state in metadata, other data in metadata too
        payload = json.dumps(event_data)

        # Channel events (channel_updated, channel_conflict) carry a nested payload dict
        raw_payload = event_data.get("payload", {})

        # Use timestamp field from WorkflowEvent, fallback to created_at or now
        created_at = event_data.get("timestamp") or event_data.get("created_at", datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))

        # Persist to SQLite
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")

            # Handle workflow_started event: store workflow definition and create node stubs
            if event_type == "workflow_started":
                # WorkflowEvent stores workflow_definition in metadata
                workflow_definition = event_data.get("metadata", {}).get("workflow_definition")

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

            # Handle channel events
            if event_type == "channel_updated" and isinstance(raw_payload, dict):
                try:
                    channel_key = raw_payload.get("channel_key")
                    channel_type = raw_payload.get("channel_type")
                    value = raw_payload.get("value")
                    version = raw_payload.get("version")
                    writer_node_id = raw_payload.get("writer_node_id")
                    reducer_strategy = raw_payload.get("reducer_strategy")

                    if channel_key and channel_type is not None and version is not None:
                        # Serialize value to JSON
                        value_json = json.dumps(value) if value is not None else None

                        # Get existing writers or initialize
                        cursor.execute(
                            "SELECT writers_json FROM channel_states WHERE run_id = ? AND channel_key = ?",
                            (run_id, channel_key)
                        )
                        existing_row = cursor.fetchone()
                        if existing_row and existing_row[0]:
                            writers = json.loads(existing_row[0])
                            if writer_node_id and writer_node_id not in writers:
                                writers.append(writer_node_id)
                        else:
                            writers = [writer_node_id] if writer_node_id else []

                        writers_json = json.dumps(writers)

                        # UPSERT channel state
                        cursor.execute(
                            """
                            INSERT INTO channel_states
                            (run_id, channel_key, channel_type, reducer_strategy, value_json, version, writers_json, updated_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                            ON CONFLICT(run_id, channel_key) DO UPDATE SET
                                channel_type = excluded.channel_type,
                                reducer_strategy = excluded.reducer_strategy,
                                value_json = excluded.value_json,
                                version = excluded.version,
                                writers_json = excluded.writers_json,
                                updated_at = excluded.updated_at
                            """,
                            (run_id, channel_key, channel_type, reducer_strategy, value_json, version, writers_json, created_at)
                        )
                    else:
                        logger.warning(f"Malformed channel_updated event for run {run_id}: missing required fields")
                except Exception as e:
                    logger.warning(f"Failed to persist channel_updated event for run {run_id}: {e}")

            elif event_type == "channel_conflict" and isinstance(raw_payload, dict):
                try:
                    channel_key = raw_payload.get("channel_key")
                    writers = raw_payload.get("writers", [])
                    message = raw_payload.get("message", "Channel conflict")

                    if channel_key:
                        conflict_json = json.dumps({"message": message, "timestamp": created_at})
                        writers_json = json.dumps(writers)

                        # Update existing row with conflict information
                        cursor.execute(
                            """
                            UPDATE channel_states
                            SET conflict_json = ?, writers_json = ?, updated_at = ?
                            WHERE run_id = ? AND channel_key = ?
                            """,
                            (conflict_json, writers_json, created_at, run_id, channel_key)
                        )
                except Exception as e:
                    logger.warning(f"Failed to persist channel_conflict event for run {run_id}: {e}")

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

        # Slack notification (best effort — errors logged, never raised)
        if self.slack_notifier is not None:
            self._notify_slack(run_id, event_type, workflow_name, event_data)

    def _notify_slack(
        self,
        run_id: str,
        event_type: str,
        workflow_name: str,
        event_data: Dict[str, Any],
    ) -> None:
        """Build a Block Kit card for lifecycle events and forward to Slack."""
        assert self.slack_notifier is not None

        # event_data is already a dict containing the full WorkflowEvent
        payload: Dict[str, Any] = event_data
        card: Optional[Dict[str, Any]] = None

        if event_type == "workflow_started":
            card = slack_formatter.format_workflow_started(
                workflow_name, run_id, self.dashboard_url
            )
        elif event_type == "workflow_completed":
            duration_ms = int(payload.get("duration_ms", 0) or 0)
            card = slack_formatter.format_workflow_completed(
                workflow_name, run_id, duration_ms, self.dashboard_url
            )
        elif event_type == "workflow_failed":
            error = str(payload.get("error", "") or "")
            card = slack_formatter.format_workflow_failed(
                workflow_name, run_id, error, self.dashboard_url
            )
        elif event_type == "gate_pending":
            node_name = str(payload.get("node_name", "") or "")
            condition = str(payload.get("condition", "") or "")
            card = slack_formatter.format_gate_pending(
                workflow_name, run_id, node_name, condition, self.dashboard_url
            )

        if card is None:
            return

        try:
            self.slack_notifier.notify(run_id, event_type, card)
        except Exception as e:
            logger.warning(f"Slack notify failed for run_id={run_id}: {e}")


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
