"""Label lifecycle management for workflow execution.

Provides event-driven label management that can be integrated with issue tracking
systems like Jira. Labels are updated based on workflow and node lifecycle events.
"""
from typing import Callable, Dict, Optional

from .events import EventType, WorkflowEvent
from .schema import LabelsConfig


# Type alias for label callback function
# Signature: (issue_key: str, action: str, label: str) -> None
# action is one of: "add", "remove"
LabelCallback = Callable[[str, str, str], None]


class LabelManager:
    """Manages label lifecycle based on workflow events.
    
    The LabelManager listens to workflow events and manages labels according to:
    - Node start events: Apply the node's label (removing previous label if any)
    - Workflow failure: Apply the configured failure label
    
    This class is designed to work as an event listener, decoupling label
    management from the core executor logic.
    """

    def __init__(
        self,
        issue_key: str,
        labels_config: LabelsConfig,
        node_labels: Dict[str, Optional[str]],
        callback: LabelCallback
    ) -> None:
        """Initialize label manager.
        
        Args:
            issue_key: Issue key (e.g., "GW-123") for label operations
            labels_config: Label configuration from workflow config
            node_labels: Mapping of node IDs to their labels (from NodeDef.label)
            callback: Callback function to execute label operations
        """
        self._issue_key = issue_key
        self._labels_config = labels_config
        self._node_labels = node_labels
        self._callback = callback
        self._current_label: Optional[str] = None

    def handle_event(self, event: WorkflowEvent) -> None:
        """Handle workflow event and manage labels accordingly.
        
        Args:
            event: Workflow event to process
        """
        if event.event_type == EventType.NODE_STARTED:
            self._handle_node_started(event)
        elif event.event_type == EventType.WORKFLOW_FAILED:
            self._handle_workflow_failed()

    def _handle_node_started(self, event: WorkflowEvent) -> None:
        """Handle NODE_STARTED event.
        
        If the node has a label configured:
        1. Remove the previous label if one is active
        2. Add the new node's label
        
        If the node has no label configured, remove the previous label if any.
        
        Args:
            event: Node started event
        """
        if event.node_id is None:
            return

        new_label = self._node_labels.get(event.node_id)
        
        # Remove previous label if one is active
        if self._current_label is not None:
            self._callback(self._issue_key, "remove", self._current_label)
            self._current_label = None
        
        # Add new label if the node has one configured
        if new_label is not None:
            self._callback(self._issue_key, "add", new_label)
            self._current_label = new_label

    def _handle_workflow_failed(self) -> None:
        """Handle WORKFLOW_FAILED event.
        
        If a failure label is configured:
        1. Remove any active step label
        2. Add the failure label
        """
        if self._labels_config.on_failure is None:
            return
        
        # Remove active step label if present
        if self._current_label is not None:
            self._callback(self._issue_key, "remove", self._current_label)
            self._current_label = None
        
        # Add failure label
        self._callback(self._issue_key, "add", self._labels_config.on_failure)
