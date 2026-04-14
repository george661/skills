"""Tests for label lifecycle management."""
from unittest.mock import Mock
from datetime import datetime

import pytest

from dag_executor import LabelsConfig
from dag_executor.events import EventType, WorkflowEvent
from dag_executor.labels import LabelManager, LabelCallback
from dag_executor.schema import NodeStatus, WorkflowStatus


class TestLabelManager:
    """Test LabelManager event listener."""

    def test_label_added_on_node_start(self) -> None:
        """Test that label is added when node with label starts."""
        callback = Mock(spec=LabelCallback)
        labels_config = LabelsConfig()
        node_labels = {"node1": "step:validating"}
        
        manager = LabelManager(
            issue_key="GW-123",
            labels_config=labels_config,
            node_labels=node_labels,
            callback=callback
        )
        
        event = WorkflowEvent(
            event_type=EventType.NODE_STARTED,
            workflow_id="wf1",
            node_id="node1",
            status=NodeStatus.RUNNING,
            timestamp=datetime.now()
        )
        
        manager.handle_event(event)
        
        callback.assert_called_once_with("GW-123", "add", "step:validating")

    def test_previous_label_removed_on_new_node_start(self) -> None:
        """Test that previous step label is removed when new node starts."""
        callback = Mock(spec=LabelCallback)
        labels_config = LabelsConfig()
        node_labels = {
            "node1": "step:validating",
            "node2": "step:processing"
        }
        
        manager = LabelManager(
            issue_key="GW-123",
            labels_config=labels_config,
            node_labels=node_labels,
            callback=callback
        )
        
        # Start first node
        event1 = WorkflowEvent(
            event_type=EventType.NODE_STARTED,
            workflow_id="wf1",
            node_id="node1",
            status=NodeStatus.RUNNING,
            timestamp=datetime.now()
        )
        manager.handle_event(event1)
        
        # Start second node - should remove previous and add new
        event2 = WorkflowEvent(
            event_type=EventType.NODE_STARTED,
            workflow_id="wf1",
            node_id="node2",
            status=NodeStatus.RUNNING,
            timestamp=datetime.now()
        )
        manager.handle_event(event2)
        
        assert callback.call_count == 3
        # First call: add step:validating
        callback.assert_any_call("GW-123", "add", "step:validating")
        # Second call: remove step:validating
        callback.assert_any_call("GW-123", "remove", "step:validating")
        # Third call: add step:processing
        callback.assert_any_call("GW-123", "add", "step:processing")

    def test_failure_label_set_on_workflow_failure(self) -> None:
        """Test that failure label is set when workflow fails."""
        callback = Mock(spec=LabelCallback)
        labels_config = LabelsConfig(on_failure="workflow-failed")
        node_labels = {}
        
        manager = LabelManager(
            issue_key="GW-123",
            labels_config=labels_config,
            node_labels=node_labels,
            callback=callback
        )
        
        event = WorkflowEvent(
            event_type=EventType.WORKFLOW_FAILED,
            workflow_id="wf1",
            status=WorkflowStatus.FAILED,
            timestamp=datetime.now()
        )
        
        manager.handle_event(event)
        
        callback.assert_called_once_with("GW-123", "add", "workflow-failed")

    def test_no_call_when_node_has_no_label(self) -> None:
        """Test that callback is not invoked when node has no label."""
        callback = Mock(spec=LabelCallback)
        labels_config = LabelsConfig()
        node_labels = {"node1": None}  # No label configured
        
        manager = LabelManager(
            issue_key="GW-123",
            labels_config=labels_config,
            node_labels=node_labels,
            callback=callback
        )
        
        event = WorkflowEvent(
            event_type=EventType.NODE_STARTED,
            workflow_id="wf1",
            node_id="node1",
            status=NodeStatus.RUNNING,
            timestamp=datetime.now()
        )
        
        manager.handle_event(event)
        
        callback.assert_not_called()

    def test_multi_node_label_lifecycle(self) -> None:
        """Test full lifecycle across multiple nodes."""
        callback = Mock(spec=LabelCallback)
        labels_config = LabelsConfig(on_failure="workflow-failed")
        node_labels = {
            "node1": "step:init",
            "node2": "step:processing",
            "node3": None  # No label
        }
        
        manager = LabelManager(
            issue_key="GW-123",
            labels_config=labels_config,
            node_labels=node_labels,
            callback=callback
        )
        
        # Node 1 starts
        manager.handle_event(WorkflowEvent(
            event_type=EventType.NODE_STARTED,
            workflow_id="wf1",
            node_id="node1",
            status=NodeStatus.RUNNING,
            timestamp=datetime.now()
        ))
        
        # Node 2 starts (node 1 implicitly finished)
        manager.handle_event(WorkflowEvent(
            event_type=EventType.NODE_STARTED,
            workflow_id="wf1",
            node_id="node2",
            status=NodeStatus.RUNNING,
            timestamp=datetime.now()
        ))
        
        # Node 3 starts (no label, should remove previous but not add new)
        manager.handle_event(WorkflowEvent(
            event_type=EventType.NODE_STARTED,
            workflow_id="wf1",
            node_id="node3",
            status=NodeStatus.RUNNING,
            timestamp=datetime.now()
        ))
        
        assert callback.call_count == 4
        calls = [call[0] for call in callback.call_args_list]
        assert calls[0] == ("GW-123", "add", "step:init")
        assert calls[1] == ("GW-123", "remove", "step:init")
        assert calls[2] == ("GW-123", "add", "step:processing")
        assert calls[3] == ("GW-123", "remove", "step:processing")

    def test_workflow_failure_removes_active_step_label(self) -> None:
        """Test that workflow failure removes active step label before adding failure label."""
        callback = Mock(spec=LabelCallback)
        labels_config = LabelsConfig(on_failure="workflow-failed")
        node_labels = {"node1": "step:processing"}
        
        manager = LabelManager(
            issue_key="GW-123",
            labels_config=labels_config,
            node_labels=node_labels,
            callback=callback
        )
        
        # Start node
        manager.handle_event(WorkflowEvent(
            event_type=EventType.NODE_STARTED,
            workflow_id="wf1",
            node_id="node1",
            status=NodeStatus.RUNNING,
            timestamp=datetime.now()
        ))
        
        # Workflow fails while node is running
        manager.handle_event(WorkflowEvent(
            event_type=EventType.WORKFLOW_FAILED,
            workflow_id="wf1",
            status=WorkflowStatus.FAILED,
            timestamp=datetime.now()
        ))
        
        assert callback.call_count == 3
        calls = [call[0] for call in callback.call_args_list]
        assert calls[0] == ("GW-123", "add", "step:processing")
        assert calls[1] == ("GW-123", "remove", "step:processing")
        assert calls[2] == ("GW-123", "add", "workflow-failed")
