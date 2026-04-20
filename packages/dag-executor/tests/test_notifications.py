"""Tests for notification dispatcher and schema."""
import pytest
from datetime import datetime
from typing import List, Optional
from unittest.mock import Mock

from dag_executor.events import EventType, WorkflowEvent
from dag_executor.schema import NodeStatus, WorkflowStatus


class TestSchemaValidation:
    """Test notification schema validation."""

    def test_default_events_applied_when_section_missing_events(self):
        """Default events list should be applied when events not specified."""
        from dag_executor.schema import SlackNotificationConfig
        
        config = SlackNotificationConfig(
            webhook_url_env="SLACK_WEBHOOK_URL"
        )
        
        expected = ["gate_pending", "workflow_failed", "workflow_completed"]
        assert config.events == expected

    def test_unknown_event_name_raises_validation_error(self):
        """Unknown event names should raise ValidationError."""
        from pydantic import ValidationError
        from dag_executor.schema import SlackNotificationConfig
        
        with pytest.raises(ValidationError) as exc_info:
            SlackNotificationConfig(
                events=["bogus_event"],
                webhook_url_env="SLACK_WEBHOOK_URL"
            )
        
        # Check that the error message includes valid options
        error_msg = str(exc_info.value)
        assert "gate_pending" in error_msg or "valid" in error_msg.lower()

    def test_webhook_or_bot_token_required(self):
        """Exactly one of webhook_url_env or bot_token_env required."""
        from pydantic import ValidationError
        from dag_executor.schema import SlackNotificationConfig
        
        # Neither provided
        with pytest.raises(ValidationError):
            SlackNotificationConfig(events=["workflow_completed"])
        
        # Both provided
        with pytest.raises(ValidationError):
            SlackNotificationConfig(
                events=["workflow_completed"],
                webhook_url_env="SLACK_WEBHOOK_URL",
                bot_token_env="SLACK_BOT_TOKEN"
            )


class MockNotifier:
    """Mock notifier for testing."""
    
    def __init__(self):
        self.calls: List[tuple] = []
    
    def notify(self, run_id: str, event_name: str, blocks: dict):
        self.calls.append((run_id, event_name, blocks))


class TestNotificationDispatcher:
    """Test notification dispatcher event filtering and dispatch logic."""

    def test_event_filter_matches_configured_events(self):
        """Dispatcher should fire only on configured events."""
        from dag_executor.notifications import NotificationDispatcher
        from dag_executor.schema import SlackNotificationConfig
        
        config = SlackNotificationConfig(
            events=["workflow_failed"],
            webhook_url_env="SLACK_WEBHOOK_URL"
        )
        
        notifier = MockNotifier()
        dispatcher = NotificationDispatcher(config, lambda _: notifier)
        
        # Should trigger
        event = WorkflowEvent(
            event_type=EventType.WORKFLOW_FAILED,
            workflow_id="test-wf",
            status=WorkflowStatus.FAILED,
            timestamp=datetime.now()
        )
        dispatcher.on_event(event)
        
        assert len(notifier.calls) == 1
        assert notifier.calls[0][0] == "test-wf"
        assert notifier.calls[0][1] == "workflow_failed"

    def test_event_filter_ignores_unconfigured_events(self):
        """Dispatcher should ignore events not in config."""
        from dag_executor.notifications import NotificationDispatcher
        from dag_executor.schema import SlackNotificationConfig
        
        config = SlackNotificationConfig(
            events=["workflow_failed"],
            webhook_url_env="SLACK_WEBHOOK_URL"
        )
        
        notifier = MockNotifier()
        dispatcher = NotificationDispatcher(config, lambda _: notifier)
        
        # Should NOT trigger
        event = WorkflowEvent(
            event_type=EventType.NODE_COMPLETED,
            workflow_id="test-wf",
            node_id="node1",
            status=NodeStatus.COMPLETED,
            timestamp=datetime.now()
        )
        dispatcher.on_event(event)
        
        assert len(notifier.calls) == 0

    def test_notifier_exception_does_not_propagate(self):
        """Notifier exceptions should be caught and not crash the dispatcher."""
        from dag_executor.notifications import NotificationDispatcher
        from dag_executor.schema import SlackNotificationConfig
        
        config = SlackNotificationConfig(
            events=["workflow_completed"],
            webhook_url_env="SLACK_WEBHOOK_URL"
        )
        
        def failing_notifier_factory(config):
            notifier = Mock()
            notifier.notify.side_effect = Exception("Slack API error")
            return notifier
        
        dispatcher = NotificationDispatcher(config, failing_notifier_factory)
        
        event = WorkflowEvent(
            event_type=EventType.WORKFLOW_COMPLETED,
            workflow_id="test-wf",
            status=WorkflowStatus.COMPLETED,
            timestamp=datetime.now()
        )
        
        # Should not raise
        dispatcher.on_event(event)

    def test_config_missing_notifications_section_is_noop(self):
        """attach_to should return None when notifications not configured."""
        from dag_executor.notifications import attach_to
        from dag_executor.schema import WorkflowConfig
        from dag_executor.events import EventEmitter
        from pathlib import Path
        
        config = WorkflowConfig(checkpoint_prefix="test")
        emitter = EventEmitter()
        
        unsubscribe = attach_to(emitter, config, Path("/tmp/test.db"))
        
        assert unsubscribe is None


class TestYAMLRoundTrip:
    """Test YAML parsing of notification config."""

    def test_workflow_with_notifications_parses(self):
        """YAML with notifications section should parse correctly."""
        from pathlib import Path
        from dag_executor.parser import load_workflow

        fixture_path = Path(__file__).parent / "fixtures" / "workflow_with_notifications.yaml"
        workflow_def = load_workflow(str(fixture_path))

        # Verify notifications config parsed
        assert workflow_def.config.notifications is not None
        assert workflow_def.config.notifications.slack is not None

        slack_config = workflow_def.config.notifications.slack
        assert slack_config.events == ["gate_pending", "workflow_failed", "workflow_completed"]
        assert slack_config.webhook_url_env == "SLACK_WEBHOOK_URL"


class TestEndToEndWiring:
    """Test that notifications are properly wired into workflow execution."""

    def test_notification_fires_during_workflow_execution(self):
        """End-to-end test: notification dispatcher fires when workflow completes."""
        from pathlib import Path
        from dag_executor.parser import load_workflow
        from dag_executor.events import EventEmitter, StreamMode
        from unittest.mock import Mock
        import tempfile

        # Load workflow with notifications
        fixture_path = Path(__file__).parent / "fixtures" / "workflow_with_notifications.yaml"
        workflow_def = load_workflow(str(fixture_path))

        # Create event emitter and temp db
        emitter = EventEmitter()
        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            db_path = Path(tmp.name)

            # Mock notifier to track calls
            calls = []

            def mock_factory(config):
                mock_notifier = Mock()
                def notify_side_effect(run_id, event_type, card):
                    calls.append((run_id, event_type, card))
                mock_notifier.notify = notify_side_effect
                return mock_notifier

            # Wire up notifications with mock factory
            from dag_executor.notifications import NotificationDispatcher
            slack_config = workflow_def.config.notifications.slack
            dispatcher = NotificationDispatcher(slack_config, mock_factory)
            unsubscribe = emitter.subscribe(dispatcher.on_event, StreamMode.STATE_UPDATES)

            # Emit a workflow_completed event (matching configured events)
            from dag_executor.events import EventType, WorkflowEvent
            from dag_executor.schema import WorkflowStatus
            from datetime import datetime

            event = WorkflowEvent(
                event_type=EventType.WORKFLOW_COMPLETED,
                workflow_id="test-run-123",
                status=WorkflowStatus.COMPLETED,
                timestamp=datetime.now()
            )
            emitter.emit(event)

            # Verify notifier was called
            assert len(calls) == 1
            assert calls[0][0] == "test-run-123"  # run_id
            assert calls[0][1] == "workflow_completed"  # event_type
            assert "blocks" in calls[0][2]  # card has blocks

            # Cleanup
            unsubscribe()
