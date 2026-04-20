"""Entry point for running dag-dashboard server."""
import logging
import uvicorn

from .config import Settings
from .notifier import SlackNotifier
from .server import create_app

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main() -> None:
    """Start the dag-dashboard server."""
    settings = Settings()
    settings.validate_host()

    slack_notifier = None
    if settings.slack_enabled:
        slack_notifier = SlackNotifier(
            db_path=settings.db_dir / "dashboard.db",
            webhook_url=settings.slack_webhook_url,
            bot_token=settings.slack_bot_token,
            channel_id=settings.slack_channel_id,
        )

    app = create_app(
        db_dir=settings.db_dir,
        events_dir=settings.events_dir,
        max_sse_connections=settings.max_sse_connections,
        slack_notifier=slack_notifier,
        dashboard_url=settings.dashboard_url,
        checkpoint_prefix=settings.checkpoint_prefix,
        checkpoint_dir_fallback=settings.checkpoint_dir,
    )

    logger.info(f"Starting DAG Dashboard on {settings.host}:{settings.port}")
    logger.info(f"Database directory: {settings.db_dir}")
    logger.info(f"Events directory: {settings.events_dir}")
    logger.info(f"Max SSE connections per run: {settings.max_sse_connections}")
    if settings.checkpoint_prefix:
        logger.info(f"Checkpoint prefix: {settings.checkpoint_prefix}")
    else:
        logger.info("Checkpoint browsing disabled (checkpoint_prefix not set)")

    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        log_level="info"
    )


if __name__ == "__main__":
    main()
