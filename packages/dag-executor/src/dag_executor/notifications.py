"""Notification dispatcher for workflow events.

Bridges EventEmitter events to notification transports (e.g., Slack).
Filters events based on workflow YAML config, formats Block Kit cards, and
dispatches to the configured notifier.
"""
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from .events import EventEmitter, EventType, WorkflowEvent
from .schema import NotificationsConfig, SlackNotificationConfig, WorkflowConfig

logger = logging.getLogger(__name__)

# Map friendly YAML event names to EventType enum values
EVENT_NAME_MAP: Dict[str, EventType] = {
    "gate_pending": EventType.NODE_INTERRUPTED,
    "workflow_failed": EventType.WORKFLOW_FAILED,
    "workflow_completed": EventType.WORKFLOW_COMPLETED,
    "workflow_started": EventType.WORKFLOW_STARTED,
    "node_failed": EventType.NODE_FAILED,
    "node_completed": EventType.NODE_COMPLETED,
}


class NotificationDispatcher:
    """Dispatches workflow events to Slack notifier based on config."""

    def __init__(
        self,
        config: SlackNotificationConfig,
        notifier_factory: Callable[[SlackNotificationConfig], Any],
    ):
        """Initialize dispatcher.

        Args:
            config: Slack notification configuration from workflow YAML
            notifier_factory: Factory function that creates a notifier from config
        """
        self.config = config
        self._notifier = notifier_factory(config)
        
        # Build set of EventType values to trigger on
        self._trigger_events = {
            EVENT_NAME_MAP[event_name]
            for event_name in config.events
            if event_name in EVENT_NAME_MAP
        }

    def on_event(self, event: WorkflowEvent) -> None:
        """Handle workflow event, dispatching to notifier if matched.

        Args:
            event: Workflow event from EventEmitter
        """
        # Filter: only dispatch configured events
        if event.event_type not in self._trigger_events:
            return

        try:
            # Build a minimal Block Kit card
            card = self._build_card(event)
            
            # Dispatch to notifier
            # notifier.notify() is defensive and swallows exceptions internally
            self._notifier.notify(event.workflow_id, event.event_type.value, card)
        except Exception as exc:
            # Defensive: notification failures never crash execution
            logger.warning(
                "Notification dispatch failed for event %s: %s",
                event.event_type.value,
                exc
            )

    def _build_card(self, event: WorkflowEvent) -> Dict[str, Any]:
        """Build Block Kit card for the event.

        Args:
            event: Workflow event

        Returns:
            Block Kit card dict (simplified format)
        """
        # Build title based on event type
        title = f"Workflow {event.event_type.value.replace('_', ' ').title()}"

        # Build text blocks - explicitly typed for mypy
        fields: list[Dict[str, str]] = [
            {
                "type": "mrkdwn",
                "text": f"*Workflow:*\n{event.workflow_id}"
            }
        ]

        # Add node info if present
        if event.node_id:
            fields.append({
                "type": "mrkdwn",
                "text": f"*Node:*\n{event.node_id}"
            })

        # Add status if present
        if event.status:
            fields.append({
                "type": "mrkdwn",
                "text": f"*Status:*\n{event.status.value}"
            })

        # Add duration if present
        if event.duration_ms is not None:
            duration_sec = event.duration_ms / 1000.0
            fields.append({
                "type": "mrkdwn",
                "text": f"*Duration:*\n{duration_sec:.2f}s"
            })

        blocks: list[Dict[str, Any]] = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": title
                }
            },
            {
                "type": "section",
                "fields": fields
            }
        ]

        return {"blocks": blocks}


def attach_to(
    emitter: EventEmitter,
    workflow_config: WorkflowConfig,
    db_path: Path,
) -> Optional[Callable[[], None]]:
    """Attach notification dispatcher to event emitter.

    Args:
        emitter: EventEmitter to subscribe to
        workflow_config: Workflow configuration
        db_path: Path to SQLite database for threading state

    Returns:
        Unsubscribe callable if notifications configured, None otherwise
    """
    # Check if notifications configured
    if workflow_config.notifications is None:
        return None
    if workflow_config.notifications.slack is None:
        return None

    slack_config = workflow_config.notifications.slack

    # Resolve credentials from environment
    webhook_url = None
    bot_token = None
    channel_id = slack_config.channel

    if slack_config.webhook_url_env:
        webhook_url = os.environ.get(slack_config.webhook_url_env)
        if not webhook_url:
            logger.warning(
                "Notification webhook env var %s not set, skipping notifications",
                slack_config.webhook_url_env
            )
            return None

    if slack_config.bot_token_env:
        bot_token = os.environ.get(slack_config.bot_token_env)
        if not bot_token:
            logger.warning(
                "Notification bot token env var %s not set, skipping notifications",
                slack_config.bot_token_env
            )
            return None

    # Create notifier factory that wires in the real SlackNotifier
    def notifier_factory(config: SlackNotificationConfig) -> Any:
        # Import here to avoid hard dependency on dag-dashboard at module load time
        try:
            from dag_dashboard.notifier import SlackNotifier
        except ImportError:
            logger.warning("dag-dashboard not installed, notifications disabled")
            # Return a no-op notifier
            class NoOpNotifier:
                def notify(self, run_id: str, event_type: str, card: Dict[str, Any]) -> None:
                    pass
            return NoOpNotifier()

        return SlackNotifier(
            db_path=db_path,
            webhook_url=webhook_url,
            bot_token=bot_token,
            channel_id=channel_id,
        )

    # Create dispatcher
    dispatcher = NotificationDispatcher(slack_config, notifier_factory)

    # Subscribe to events
    from .events import StreamMode
    unsubscribe = emitter.subscribe(dispatcher.on_event, StreamMode.STATE_UPDATES)

    return unsubscribe
