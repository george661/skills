"""Settings store for dashboard_settings table."""
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

# Whitelisted settings keys that can be edited via API
WHITELISTED_KEYS = {
    "slack_enabled",
    "slack_webhook_url",
    "slack_bot_token",
    "slack_channel_id",
    "trigger_enabled",
    "trigger_secret",
    "trigger_rate_limit_per_min",
    "max_sse_connections",
    "dashboard_url",
    "workflows_dir",
    "node_log_line_cap",
    "allow_destructive_nodes",
}

# Keys that contain secrets (should be masked in GET responses)
SECRET_KEYS = {
    "slack_webhook_url",
    "slack_bot_token",
    "trigger_secret",
}


def is_secret_key(key: str) -> bool:
    """Check if a key is a secret."""
    return key in SECRET_KEYS


def mask_secret(value: Any) -> str:
    """Mask a secret value, showing only last 4 chars.

    Args:
        value: The secret value to mask

    Returns:
        Masked string in format "•••• <last4>" or empty string
    """
    if not value:
        return ""

    str_value = str(value)
    if len(str_value) <= 4:
        return "•••• " + str_value

    last4 = str_value[-4:]
    return f"•••• {last4}"


def get_setting(db_path: Path, key: str) -> Optional[Dict[str, Any]]:
    """Get a single setting from the database.

    Args:
        db_path: Path to SQLite database
        key: Setting key to retrieve

    Returns:
        Dict with 'value', 'is_secret', 'updated_at', 'updated_by' or None
    """
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT value, is_secret, updated_at, updated_by FROM dashboard_settings WHERE key = ?",
            (key,)
        )
        row = cursor.fetchone()

        if not row:
            return None

        # Decode JSON value
        try:
            value = json.loads(row[0])
        except (json.JSONDecodeError, TypeError):
            value = row[0]

        return {
            "value": value,
            "is_secret": row[1],
            "updated_at": row[2],
            "updated_by": row[3],
        }
    finally:
        conn.close()


def get_all_settings(db_path: Path) -> Dict[str, Any]:
    """Get all settings from the database.

    Args:
        db_path: Path to SQLite database

    Returns:
        Dict mapping key to setting dict
    """
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT key, value, is_secret, updated_at, updated_by FROM dashboard_settings"
        )
        rows = cursor.fetchall()

        result = {}
        for row in rows:
            key = row[0]
            try:
                value = json.loads(row[1])
            except (json.JSONDecodeError, TypeError):
                value = row[1]

            result[key] = {
                "value": value,
                "is_secret": row[2],
                "updated_at": row[3],
                "updated_by": row[4],
            }

        return result
    finally:
        conn.close()


def put_setting(
    db_path: Path,
    key: str,
    value: Any,
    updated_by: Optional[str] = None
) -> None:
    """Write a setting to the database.

    Args:
        db_path: Path to SQLite database
        key: Setting key
        value: Setting value (will be JSON encoded if not string)
        updated_by: Optional identifier of who updated the setting
    """
    # JSON encode non-string values
    if not isinstance(value, str):
        value_str = json.dumps(value)
    else:
        value_str = value

    is_secret = 1 if is_secret_key(key) else 0
    updated_at = datetime.now(timezone.utc).isoformat()

    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO dashboard_settings (key, value, is_secret, updated_at, updated_by)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                is_secret = excluded.is_secret,
                updated_at = excluded.updated_at,
                updated_by = excluded.updated_by
            """,
            (key, value_str, is_secret, updated_at, updated_by)
        )
        conn.commit()
    finally:
        conn.close()


def merge_settings(settings: Any, db_path: Path) -> Dict[str, Dict[str, Any]]:
    """Merge settings from env/defaults and database.

    Merge order: db > env > default

    Args:
        settings: Settings instance with env/default values
        db_path: Path to SQLite database

    Returns:
        Dict mapping each whitelisted key to:
            {
                "value": <actual-value>,
                "source": "env" | "db" | "default",
                "is_secret": bool
            }
    """
    # Get db overrides
    db_settings = get_all_settings(db_path)

    # Build merged result
    result = {}

    # Get Settings defaults
    defaults = settings.__class__()

    for key in WHITELISTED_KEYS:
        # Get the value from settings instance
        current_value = getattr(settings, key, None)
        default_value = getattr(defaults, key, None)

        # Determine source and value
        if key in db_settings:
            # DB override wins
            value = db_settings[key]["value"]
            source = "db"
        elif current_value != default_value:
            # Env override (different from default)
            value = current_value
            source = "env"
        else:
            # Default value
            value = default_value
            source = "default"

        # Convert Path to string for JSON serialization
        if isinstance(value, Path):
            value = str(value)

        result[key] = {
            "value": value,
            "source": source,
            "is_secret": is_secret_key(key),
        }

    return result
