"""Event system for workflow execution monitoring and logging."""
import logging
import threading
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

from pydantic import BaseModel, Field

from .schema import NodeStatus, WorkflowStatus

logger = logging.getLogger(__name__)


class EventType(str, Enum):
    """Types of workflow events."""
    WORKFLOW_STARTED = "workflow_started"
    WORKFLOW_COMPLETED = "workflow_completed"
    WORKFLOW_FAILED = "workflow_failed"
    WORKFLOW_INTERRUPTED = "workflow_interrupted"
    NODE_STARTED = "node_started"
    NODE_COMPLETED = "node_completed"
    NODE_FAILED = "node_failed"
    NODE_SKIPPED = "node_skipped"
    NODE_INTERRUPTED = "node_interrupted"
    NODE_STREAM_TOKEN = "node_stream_token"
    NODE_PROGRESS = "node_progress"


class StreamMode(str, Enum):
    """Stream filtering modes for event subscribers.

    Controls what events a subscriber receives:
    - ALL: All events (lifecycle, stream tokens, progress)
    - STATE_UPDATES: Only lifecycle events (started/completed/failed/skipped/interrupted)
    - DEBUG: Everything including internal state (superset of ALL, reserved for future use)
    """
    ALL = "all"
    STATE_UPDATES = "state_updates"
    DEBUG = "debug"


class WorkflowEvent(BaseModel):
    """Structured event emitted during workflow execution.

    Events are emitted at key workflow and node lifecycle points,
    enabling monitoring, debugging, and audit trail generation.
    """
    event_type: EventType = Field(..., description="Type of event")
    workflow_id: str = Field(..., description="ID of the workflow")
    node_id: Optional[str] = Field(default=None, description="ID of the node (for node events)")
    status: Optional[Union[NodeStatus, WorkflowStatus]] = Field(
        default=None,
        description="Current status (NodeStatus for node events, WorkflowStatus for workflow events)"
    )
    duration_ms: Optional[int] = Field(default=None, description="Execution duration in milliseconds")
    model: Optional[str] = Field(default=None, description="Model tier used for execution (sonnet/opus/haiku)")
    dispatch: Optional[str] = Field(default=None, description="Dispatch mode (sync/async/webhook)")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional event metadata")
    timestamp: datetime = Field(..., description="Event timestamp")


class EventEmitter:
    """Thread-safe event emitter with listener management and JSONL logging.

    Supports registering multiple listeners that receive events synchronously.
    Optionally logs events to a JSONL file for audit trails and debugging.
    """

    def __init__(
        self,
        log_file: Optional[str] = None,
        workflow_name: Optional[str] = None,
        run_id: Optional[str] = None
    ) -> None:
        """Initialize event emitter.

        Args:
            log_file: Optional path to JSONL log file for event persistence.
                     If not provided, defaults to .dag-checkpoints/{workflow_name}-{run_id}/events.jsonl
                     when workflow_name and run_id are specified.
            workflow_name: Workflow name for default checkpoint path
            run_id: Run ID for default checkpoint path
        """
        self._listeners: List[Callable[[WorkflowEvent], None]] = []
        self._lock = threading.Lock()

        # Determine log file path
        self._log_file: Optional[Path]
        if log_file:
            self._log_file = Path(log_file)
        elif workflow_name and run_id:
            # Use standard checkpoint directory convention
            self._log_file = Path(f".dag-checkpoints/{workflow_name}-{run_id}/events.jsonl")
        else:
            self._log_file = None

        self._log_lock = threading.Lock()

        # Create log file parent directory if needed
        if self._log_file:
            self._log_file.parent.mkdir(parents=True, exist_ok=True)
    
    def add_listener(self, listener: Callable[[WorkflowEvent], None]) -> None:
        """Add an event listener (unfiltered, backward compatible).

        This method provides backward compatibility and receives all events.
        For filtered event streams, use subscribe() instead.

        Args:
            listener: Callback function that receives WorkflowEvent objects
        """
        with self._lock:
            self._listeners.append(listener)

    def subscribe(self, listener: Callable[[WorkflowEvent], None], mode: StreamMode) -> None:
        """Subscribe to events with filtering based on stream mode.

        Args:
            listener: Callback function that receives WorkflowEvent objects
            mode: Stream mode controlling which events are delivered
        """
        # Define state update event types (lifecycle events only)
        state_update_types = {
            EventType.WORKFLOW_STARTED,
            EventType.WORKFLOW_COMPLETED,
            EventType.WORKFLOW_FAILED,
            EventType.WORKFLOW_INTERRUPTED,
            EventType.NODE_STARTED,
            EventType.NODE_COMPLETED,
            EventType.NODE_FAILED,
            EventType.NODE_SKIPPED,
            EventType.NODE_INTERRUPTED,
        }

        # Create filtered listener wrapper based on mode
        if mode == StreamMode.STATE_UPDATES:
            # Only pass through lifecycle events
            def filtered_listener(event: WorkflowEvent) -> None:
                if event.event_type in state_update_types:
                    listener(event)
            with self._lock:
                self._listeners.append(filtered_listener)
        else:
            # ALL and DEBUG modes receive everything
            with self._lock:
                self._listeners.append(listener)
    
    def remove_listener(self, listener: Callable[[WorkflowEvent], None]) -> None:
        """Remove an event listener.
        
        Args:
            listener: Callback function to remove
        """
        with self._lock:
            if listener in self._listeners:
                self._listeners.remove(listener)
    
    def emit(self, event: WorkflowEvent) -> None:
        """Emit an event to all registered listeners.
        
        Listeners are called synchronously. Exceptions in listeners are caught
        and logged to prevent one failing listener from breaking others.
        
        Args:
            event: Event to emit
        """
        # Get snapshot of listeners under lock
        with self._lock:
            listeners = self._listeners.copy()
        
        # Call listeners without holding lock
        for listener in listeners:
            try:
                listener(event)
            except Exception as e:
                # Log exception but continue with other listeners
                logger.warning(f"Error in event listener: {e}")
        
        # Write to JSONL log if configured
        if self._log_file:
            self._write_log(event)
    
    def _write_log(self, event: WorkflowEvent) -> None:
        """Write event to JSONL log file (thread-safe).

        Args:
            event: Event to log
        """
        if self._log_file is None:
            return

        with self._log_lock:
            with open(self._log_file, 'a') as f:
                f.write(event.model_dump_json() + '\n')
