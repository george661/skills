"""Tests for configuration settings."""
from pathlib import Path
import os
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


def test_warns_on_wildcard_bind(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Should warn when binding to 0.0.0.0."""
    monkeypatch.setenv("DAG_DASHBOARD_HOST", "0.0.0.0")
    settings = Settings()
    settings.validate_host()
    assert "WARNING" in caplog.text
    assert "0.0.0.0" in caplog.text


def test_workflows_dirs_parses_colon_separated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DAG_DASHBOARD_WORKFLOWS_DIR should parse colon-separated paths."""
    monkeypatch.setenv("DAG_DASHBOARD_WORKFLOWS_DIR", "workflows:/tmp/extra-workflows")
    settings = Settings()
    assert settings.workflows_dirs == [Path("workflows"), Path("/tmp/extra-workflows")]


def test_workflows_dirs_single_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """Single path should still work (backwards compat)."""
    monkeypatch.setenv("DAG_DASHBOARD_WORKFLOWS_DIR", "workflows")
    settings = Settings()
    assert settings.workflows_dirs == [Path("workflows")]


def test_workflows_dirs_default() -> None:
    """Default should be [Path('workflows')]."""
    settings = Settings()
    assert settings.workflows_dirs == [Path("workflows")]


def test_workflows_dir_property() -> None:
    """workflows_dir should be string representation of first dir for backwards compat."""
    settings = Settings()
    assert settings.workflows_dir == "workflows"
    assert settings.workflows_dirs[0] == Path("workflows")


def test_fts5_enabled_defaults_to_false() -> None:
    """FTS5 should be disabled by default."""
    settings = Settings()
    assert settings.fts5_enabled is False


def test_fts5_enabled_from_DAG_DASHBOARD_FTS_env_var(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DAG_DASHBOARD_FTS=true should enable FTS5."""
    monkeypatch.setenv("DAG_DASHBOARD_FTS", "true")
    settings = Settings()
    assert settings.fts5_enabled is True


def test_node_log_line_cap_default_is_50000() -> None:
    """Default node_log_line_cap should be 50000."""
    settings = Settings()
    assert settings.node_log_line_cap == 50000


def test_node_log_line_cap_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """DAG_DASHBOARD_NODE_LOG_LINE_CAP should override default."""
    monkeypatch.setenv("DAG_DASHBOARD_NODE_LOG_LINE_CAP", "75000")
    settings = Settings()
    assert settings.node_log_line_cap == 75000
