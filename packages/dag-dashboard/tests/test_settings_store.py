"""Unit tests for settings_store.py."""
import json
import sqlite3
from pathlib import Path

import pytest

from dag_dashboard.settings_store import (
    get_setting,
    get_all_settings,
    put_setting,
    mask_secret,
    is_secret_key,
    merge_settings,
    WHITELISTED_KEYS,
)


def test_schema_creates_dashboard_settings_table(tmp_path: Path) -> None:
    """Test that dashboard_settings table is created by init_db."""
    from dag_dashboard.database import init_db
    
    db_path = tmp_path / "test.db"
    init_db(db_path)
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='dashboard_settings'"
    )
    result = cursor.fetchone()
    conn.close()
    
    assert result is not None, "dashboard_settings table should exist"


def test_merge_order_env_over_default(tmp_path: Path) -> None:
    """Test that env values override defaults in merge logic."""
    from dag_dashboard.config import Settings
    from dag_dashboard.database import init_db
    
    db_path = tmp_path / "test.db"
    init_db(db_path)
    
    # Settings with env override (slack_enabled=True via env)
    settings = Settings(slack_enabled=True, slack_webhook_url="https://hooks.slack.com/test")
    
    merged = merge_settings(settings, db_path)
    
    # Env value should win over default (default is False)
    assert merged["slack_enabled"]["value"] is True
    assert merged["slack_enabled"]["source"] == "env"


def test_merge_order_db_over_env(tmp_path: Path) -> None:
    """Test that db values override env values in merge logic."""
    from dag_dashboard.config import Settings
    from dag_dashboard.database import init_db
    
    db_path = tmp_path / "test.db"
    init_db(db_path)
    
    # Set env value
    settings = Settings(slack_enabled=True, slack_webhook_url="https://hooks.slack.com/test")
    
    # Write db override
    put_setting(db_path, "slack_enabled", False, updated_by="test")
    
    merged = merge_settings(settings, db_path)
    
    # DB value should win over env
    assert merged["slack_enabled"]["value"] is False
    assert merged["slack_enabled"]["source"] == "db"


def test_put_writes_to_db(tmp_path: Path) -> None:
    """Test that put_setting writes to database."""
    from dag_dashboard.database import init_db
    
    db_path = tmp_path / "test.db"
    init_db(db_path)
    
    put_setting(db_path, "trigger_enabled", True, updated_by="test")
    
    # Verify it was written
    result = get_setting(db_path, "trigger_enabled")
    assert result is not None
    assert result["value"] is True


def test_is_secret_flag_persisted(tmp_path: Path) -> None:
    """Test that is_secret flag is correctly set for secret keys."""
    from dag_dashboard.database import init_db
    
    db_path = tmp_path / "test.db"
    init_db(db_path)
    
    # Write a secret key
    put_setting(db_path, "slack_webhook_url", "https://hooks.slack.com/services/T00/B00/xxx", updated_by="test")
    
    result = get_setting(db_path, "slack_webhook_url")
    assert result is not None
    assert result["is_secret"] == 1


def test_mask_secret_shows_last_4(tmp_path: Path) -> None:
    """Test that mask_secret shows last 4 chars for non-empty secrets."""
    value = "fake-slack-token-for-testing-purposes-only-1234"
    masked = mask_secret(value)
    
    # Should be •••• followed by last 4
    assert masked == "•••• 1234"


def test_mask_empty_secret_returns_empty_string(tmp_path: Path) -> None:
    """Test that empty secrets are returned as empty string."""
    assert mask_secret("") == ""
    assert mask_secret(None) == ""
