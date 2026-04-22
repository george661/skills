"""Configuration settings for dag-dashboard."""
import logging
import os
from pathlib import Path
from typing import Any, List, Optional, Union

from pydantic import AliasChoices, ConfigDict, Field, computed_field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    """Application settings with secure defaults."""

    model_config = SettingsConfigDict(env_prefix="DAG_DASHBOARD_", extra="allow")

    host: str = "127.0.0.1"
    port: int = 8100
    db_dir: Path = Path.home() / ".dag-dashboard"
    events_dir: Path = Path("dag-events")
    max_sse_connections: int = 50
    checkpoint_prefix: Optional[Path] = None
    checkpoint_dir: Optional[str] = None

    # Trigger endpoint settings
    trigger_enabled: bool = False
    trigger_secret: Optional[str] = None
    trigger_rate_limit_per_min: int = 10
    workflows_dir: Union[str, Path] = "workflows"  # Accepts str (env) or Path (programmatic); normalized to str by validator
    workflows_dirs: List[Path] = Field(default_factory=list)  # Parsed list, populated by validator

    @field_validator("workflows_dir", mode="before")
    @classmethod
    def _coerce_workflows_dir_to_str(cls, v: Any) -> str:
        """Accept Path objects for backwards compatibility; normalize to str."""
        if isinstance(v, Path):
            return str(v)
        return str(v) if not isinstance(v, str) else v

    # Search endpoint settings
    search_token: Optional[str] = None  # Bearer token for search endpoint auth
    search_rate_limit_per_min: int = 30  # Rate limit is per-bearer-token
    fts5_enabled: bool = Field(default=False, validation_alias=AliasChoices("DAG_DASHBOARD_FTS", "fts5_enabled"))

    # Slack notification settings
    slack_enabled: bool = False
    slack_webhook_url: Optional[str] = None
    slack_bot_token: Optional[str] = None
    slack_channel_id: Optional[str] = None
    dashboard_url: str = "http://127.0.0.1:8100"

    @model_validator(mode="after")
    def _parse_workflows_dirs_from_workflows_dir(self) -> "Settings":
        """Parse workflows_dir string into workflows_dirs list."""
        # Only parse if workflows_dirs hasn't been explicitly set
        if not self.workflows_dirs:
            value = self.workflows_dir
            if isinstance(value, Path):
                self.workflows_dirs = [value]
            else:
                # String input - parse colon-separated (Unix) or semicolon (Windows)
                separator = os.pathsep  # ':' on Unix, ';' on Windows
                paths = str(value).split(separator)
                self.workflows_dirs = [Path(p.strip()) for p in paths if p.strip()]

        # Also normalize workflows_dir to be a Path (first dir)
        if self.workflows_dirs:
            self.workflows_dir = str(self.workflows_dirs[0])

        return self

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

    def reload_from_db(self, db_path: Path) -> None:
        """Re-read dashboard_settings and apply overrides in place.

        Preserves env values when no db override is present.

        Args:
            db_path: Path to SQLite database with dashboard_settings table
        """
        import sqlite3
        import json

        conn = sqlite3.connect(db_path)
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT key, value FROM dashboard_settings"
            )
            rows = cursor.fetchall()

            # Build dict of overrides
            overrides = {}
            for key, value_str in rows:
                # Skip keys not in Settings model
                if not hasattr(self, key):
                    continue

                # Decode JSON value
                try:
                    value = json.loads(value_str)
                except (json.JSONDecodeError, TypeError):
                    value = value_str

                overrides[key] = value

            # Apply overrides to self
            for key, value in overrides.items():
                setattr(self, key, value)

            # Re-validate by calling model_validate on a fresh instance
            # This ensures Slack coherency rules are still enforced
            if overrides:
                # Validate by constructing with current values
                current_values = self.model_dump()
                self.__class__(**current_values)

        finally:
            conn.close()
