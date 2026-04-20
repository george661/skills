#!/usr/bin/env python3
"""Post-node notification hook for DAG events.

This hook is invoked by Claude Code after DAG node events and dispatches
notifications to configured transports (e.g., Slack).

Hook contract (Claude Code stdin JSON):
{
  "event": {...},              # WorkflowEvent dict
  "workflow_config_path": "...", # Path to workflow YAML
  "checkpoint_dir": "..."      # Path to checkpoint dir for threading DB
}

Exit codes:
- 0: Success (or notification skipped due to config/env)
- Non-zero: Only logged, never crashes workflow execution
"""
import json
import logging
import sys
from pathlib import Path

logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def main() -> int:
    """Process notification hook from stdin."""
    try:
        # Read hook input
        input_data = json.load(sys.stdin)
        event_dict = input_data.get("event", {})
        workflow_config_path = input_data.get("workflow_config_path")
        checkpoint_dir = input_data.get("checkpoint_dir", "/tmp")

        if not event_dict:
            logger.warning("No event data in hook input, skipping")
            return 0

        # Import executor modules
        try:
            from dag_executor.events import WorkflowEvent
            from dag_executor.parser import load_workflow
            from dag_executor.notifications import NotificationDispatcher
        except ImportError as e:
            logger.warning(f"dag-executor not installed: {e}")
            return 0

        # Parse event
        try:
            event = WorkflowEvent(**event_dict)
        except Exception as e:
            logger.warning(f"Failed to parse event: {e}")
            return 0

        # Load workflow config if provided
        if not workflow_config_path:
            logger.debug("No workflow config path, skipping")
            return 0

        try:
            workflow_def = load_workflow(workflow_config_path)
        except Exception as e:
            logger.warning(f"Failed to load workflow config: {e}")
            return 0

        # Check if notifications configured
        if not workflow_def.config.notifications:
            return 0
        if not workflow_def.config.notifications.slack:
            return 0

        slack_config = workflow_def.config.notifications.slack

        # Create notifier factory
        def notifier_factory(config):
            import os
            # Resolve credentials from environment
            webhook_url = None
            bot_token = None
            channel_id = config.channel

            if config.webhook_url_env:
                webhook_url = os.environ.get(config.webhook_url_env)
                if not webhook_url:
                    logger.warning(f"Webhook env var {config.webhook_url_env} not set")
                    return None

            if config.bot_token_env:
                bot_token = os.environ.get(config.bot_token_env)
                if not bot_token:
                    logger.warning(f"Bot token env var {config.bot_token_env} not set")
                    return None

            # Try to import SlackNotifier
            try:
                from dag_dashboard.notifier import SlackNotifier
            except ImportError:
                logger.warning("dag-dashboard not installed, notifications disabled")
                return None

            db_path = Path(checkpoint_dir) / "notifications.db"
            return SlackNotifier(
                db_path=db_path,
                webhook_url=webhook_url,
                bot_token=bot_token,
                channel_id=channel_id,
            )

        # Create dispatcher and dispatch event
        notifier = notifier_factory(slack_config)
        if notifier is None:
            return 0

        dispatcher = NotificationDispatcher(slack_config, lambda _: notifier)
        dispatcher.on_event(event)

        return 0

    except Exception as e:
        # Never crash — notification failures are logged only
        logger.error(f"Notification hook failed: {e}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
