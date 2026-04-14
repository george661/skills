"""Event system for workflow execution monitoring and logging."""
import threading
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

from pydantic import BaseModel, Field

from .schema import NodeStatus, WorkflowStatus


class EventType(str, Enum):
    """Types of workflow events."""
    WORKFLOW_STARTED = "workflow_started"
    WORKFLOW_COMPLETED = "workflow_completed"
    WORKFLOW_FAILED = "workflow_failed"
    NODE_STARTED = "node_started"
    NODE_COMPLETED = "node_completed"
    NODE_FAILED = "node_failed"


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
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional event metadata")
    timestamp: datetime = Field(..., description="Event timestamp")


class EventEmitter:
    """Thread-safe event emitter with listener management and JSONL logging.
    
    Supports registering multiple listeners that receive events synchronously.
    Optionally logs events to a JSONL file for audit trails and debugging.
    """
    
    def __init__(self, log_file: Optional[str] = None) -> None:
        """Initialize event emitter.
        
        Args:
            log_file: Optional path to JSONL log file for event persistence
        """
        self._listeners: List[Callable[[WorkflowEvent], None]] = []
        self._lock = threading.Lock()
        self._log_file = Path(log_file) if log_file else None
        self._log_lock = threading.Lock()
        
        # Create log file parent directory if needed
        if self._log_file:
            self._log_file.parent.mkdir(parents=True, exist_ok=True)
    
    def add_listener(self, listener: Callable[[WorkflowEvent], None]) -> None:
        """Add an event listener.
        
        Args:
            listener: Callback function that receives WorkflowEvent objects
        """
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
                # In production, you'd use proper logging here
                print(f"Error in event listener: {e}")
        
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
