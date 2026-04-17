"""Tests for configuration settings."""
import os
from pathlib import Path
import pytest
from dag_dashboard.config import Settings


def test_default_host() -> None:
    """Default host should be 127.0.0.1 for security."""
    settings = Settings()
    assert settings.host == "127.0.0.1"


def test_default_port() -> None:
    """Default port should be 8100."""
    settings = Settings()
    assert settings.port == 8100


def test_default_db_dir() -> None:
    """Default DB directory should be ~/.dag-dashboard/."""
    settings = Settings()
    expected = Path.home() / ".dag-dashboard"
    assert settings.db_dir == expected


def test_warns_on_wildcard_bind(caplog: pytest.LogCaptureFixture) -> None:
    """Should warn when binding to 0.0.0.0."""
    os.environ["DAG_DASHBOARD_HOST"] = "0.0.0.0"
    try:
        settings = Settings()
        settings.validate_host()
        assert "WARNING" in caplog.text
        assert "0.0.0.0" in caplog.text
    finally:
        os.environ.pop("DAG_DASHBOARD_HOST", None)
