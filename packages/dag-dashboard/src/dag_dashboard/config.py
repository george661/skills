"""Configuration settings for dag-dashboard."""
import logging
from pathlib import Path
from typing import Optional

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    """Application settings with secure defaults."""

    model_config = SettingsConfigDict(env_prefix="DAG_DASHBOARD_")

    host: str = "127.0.0.1"
    port: int = 8100
    db_dir: Path = Path.home() / ".dag-dashboard"
    events_dir: Path = Path("dag-events")
    max_sse_connections: int = 50
    checkpoint_dir: Optional[str] = None

    # Slack notification settings
    slack_enabled: bool = False
    slack_webhook_url: Optional[str] = None
    slack_bot_token: Optional[str] = None
    slack_channel_id: Optional[str] = None
    dashboard_url: str = "http://127.0.0.1:8100"

    def validate_host(self) -> None:
        """Warn if binding to wildcard address."""
        if self.host == "0.0.0.0":
            logger.warning(
                "WARNING: Binding to 0.0.0.0 exposes the dashboard to the network. "
                "Use 127.0.0.1 for local-only access."
            )

    @model_validator(mode="after")
    def _validate_slack_settings(self) -> "Settings":
        """Ensure Slack settings are coherent when notifications are enabled."""
        if not self.slack_enabled:
            return self
        has_webhook = bool(self.slack_webhook_url)
        has_bot = bool(self.slack_bot_token)
        if has_webhook == has_bot:
            raise ValueError(
                "DAG_DASHBOARD_SLACK_ENABLED requires exactly one of "
                "slack_webhook_url or slack_bot_token."
            )
        if has_bot and not self.slack_channel_id:
            raise ValueError(
                "slack_bot_token requires slack_channel_id to be set."
            )
        return self
