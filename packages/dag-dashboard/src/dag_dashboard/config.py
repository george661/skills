"""Configuration settings for dag-dashboard."""
import logging
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    """Application settings with secure defaults."""

    model_config = SettingsConfigDict(env_prefix="DAG_DASHBOARD_")

    host: str = "127.0.0.1"
    port: int = 8100
    db_dir: Path = Path.home() / ".dag-dashboard"

    def validate_host(self) -> None:
        """Warn if binding to wildcard address."""
        if self.host == "0.0.0.0":
            logger.warning(
                "WARNING: Binding to 0.0.0.0 exposes the dashboard to the network. "
                "Use 127.0.0.1 for local-only access."
            )
