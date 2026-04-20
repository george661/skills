"""Progress bar for workflow execution."""
import os
import sys
from datetime import datetime
from typing import TYPE_CHECKING, Callable, Optional, TextIO

if TYPE_CHECKING:
    from dag_executor.events import EventEmitter, WorkflowEvent


class ProgressBar:
    """Live progress bar that subscribes to workflow events."""
    
    def __init__(self, total_nodes: int, stderr: Optional[TextIO] = None):
        """Initialize progress bar.
        
        Args:
            total_nodes: Total number of nodes in workflow
            stderr: Output stream (defaults to sys.stderr)
        """
        self.total_nodes = total_nodes
        self.completed = 0
        self.current_node_id: Optional[str] = None
        self.current_model: Optional[str] = None
        self.accumulated_cost = 0.0
        self.start_time = datetime.now()
        self.stderr = stderr or sys.stderr
        self.use_ansi = not os.environ.get("NO_COLOR")
        self._unsubscribe: Optional[Callable[[], None]] = None
    
    def attach(self, emitter: "EventEmitter") -> None:
        """Attach to event emitter to receive updates.
        
        Args:
            emitter: EventEmitter to subscribe to
        """
        def on_event(event: "WorkflowEvent") -> None:
            from dag_executor.events import EventType
            
            if event.event_type == EventType.NODE_STARTED:
                self.current_node_id = event.node_id
                self.current_model = event.model
                self._render()
            
            elif event.event_type == EventType.NODE_COMPLETED:
                self.completed += 1
                # Extract cost from metadata if present
                cost = event.metadata.get("cost_usd", 0.0)
                self.accumulated_cost += cost
                self._render()
            
            elif event.event_type == EventType.WORKFLOW_COMPLETED:
                # Clean up subscription
                if self._unsubscribe:
                    self._unsubscribe()

        from dag_executor.events import StreamMode

        self._unsubscribe = emitter.subscribe(on_event, StreamMode.STATE_UPDATES)
    
    def _render(self) -> None:
        """Render progress bar to stderr."""
        elapsed = datetime.now() - self.start_time
        elapsed_str = f"{int(elapsed.total_seconds() // 60):02d}:{int(elapsed.total_seconds() % 60):02d}"
        
        # Build progress bar
        if self.total_nodes > 0:
            percent = self.completed / self.total_nodes
            bar_width = 20
            filled = int(bar_width * percent)
            bar = "█" * filled + "░" * (bar_width - filled)
        else:
            bar = "░" * 20
        
        # Format line
        parts = [
            f"[{bar}]",
            f"{self.completed}/{self.total_nodes} nodes",
        ]
        
        if self.current_node_id:
            parts.append(f"Current: {self.current_node_id}")
        
        if self.current_model:
            parts.append(f"Model: {self.current_model}")
        
        parts.append(f"Cost: ${self.accumulated_cost:.2f}")
        parts.append(elapsed_str)
        
        line = " | ".join(parts)
        
        # Write with in-place update or newline
        if self.use_ansi:
            self.stderr.write(f"\r{line}")
            self.stderr.flush()
        else:
            self.stderr.write(f"{line}\n")
            self.stderr.flush()
