"""Route tests for settings API endpoints."""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dag_dashboard.config import Settings
from dag_dashboard.database import init_db
from dag_dashboard.server import create_app


@pytest.fixture
def test_db(tmp_path: Path) -> Path:
    """Create a test database."""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    return db_path


@pytest.fixture
def client(test_db: Path, tmp_path: Path) -> TestClient:
    """Create test client with settings endpoint."""
    settings = Settings(
        slack_enabled=False,
        slack_webhook_url="",
        trigger_enabled=False,
        workflows_dir=tmp_path / "workflows"
    )
    app = create_app(
        db_path=test_db,
        events_dir=tmp_path / "events",
        settings=settings
    )
    return TestClient(app)


def test_get_returns_merged_settings_with_masked_secrets(client: TestClient, test_db: Path) -> None:
    """Test GET /api/settings returns merged settings with secrets masked."""
    response = client.get("/api/settings")
    
    assert response.status_code == 200
    data = response.json()
    
    assert "settings" in data
    settings = data["settings"]
    
    # Should include all whitelisted keys
    assert "slack_enabled" in settings
    assert "trigger_enabled" in settings
    assert "max_sse_connections" in settings
    
    # Each setting should have value, source, is_secret
    for key, setting in settings.items():
        assert "value" in setting
        assert "source" in setting
        assert "is_secret" in setting


def test_put_persists_override_and_reloads_in_memory(client: TestClient, test_db: Path) -> None:
    """Test PUT persists to db and reloads app.state.settings."""
    # Initial state
    response = client.get("/api/settings")
    initial = response.json()["settings"]["trigger_enabled"]["value"]
    
    # PUT a new value
    response = client.put("/api/settings", json={
        "updates": {"trigger_enabled": True},
        "updated_by": "test-user"
    })
    
    assert response.status_code == 200
    
    # GET again - should reflect new value without restart
    response = client.get("/api/settings")
    updated = response.json()["settings"]["trigger_enabled"]["value"]
    
    assert updated is True
    
    # Source should now be 'db'
    assert response.json()["settings"]["trigger_enabled"]["source"] == "db"


def test_put_rejects_unknown_key_400(client: TestClient) -> None:
    """Test PUT with unknown key returns 400."""
    response = client.put("/api/settings", json={
        "updates": {"unknown_key": "value"},
        "updated_by": "test"
    })
    
    assert response.status_code == 400
    data = response.json()
    assert "detail" in data
    assert "errors" in data["detail"]


def test_put_rejects_invalid_type_400(client: TestClient) -> None:
    """Test PUT with invalid type returns 400."""
    response = client.put("/api/settings", json={
        "updates": {"trigger_rate_limit_per_min": "not-an-int"},
        "updated_by": "test"
    })
    
    assert response.status_code == 400
    data = response.json()
    assert "detail" in data
    assert "errors" in data["detail"]


def test_put_rejects_incoherent_slack_config_400(client: TestClient) -> None:
    """Test PUT enabling Slack with both webhook and bot token returns 400."""
    response = client.put("/api/settings", json={
        "updates": {
            "slack_enabled": True,
            "slack_webhook_url": "https://hooks.slack.com/test",
            "slack_bot_token": "xoxb-FAKE-TEST-TOKEN-123"
        },
        "updated_by": "test"
    })
    
    assert response.status_code == 400
    data = response.json()
    assert "detail" in data
    assert "errors" in data["detail"]


def test_put_no_partial_writes_on_validation_error(client: TestClient, test_db: Path) -> None:
    """Test PUT with mix of valid and invalid keys persists nothing."""
    # Attempt to write valid + invalid
    response = client.put("/api/settings", json={
        "updates": {
            "trigger_enabled": True,
            "trigger_rate_limit_per_min": "invalid"
        },
        "updated_by": "test"
    })
    
    assert response.status_code == 400
    
    # Verify trigger_enabled was NOT written
    from dag_dashboard.settings_store import get_setting
    result = get_setting(test_db, "trigger_enabled")
    assert result is None  # Should not exist in db


def test_restart_preserves_overrides(tmp_path: Path) -> None:
    """Test that after PUT, a new Settings instance loads db values."""
    from dag_dashboard.database import init_db
    from dag_dashboard.settings_store import put_setting
    
    db_path = tmp_path / "test.db"
    init_db(db_path)
    
    # Write an override
    put_setting(db_path, "trigger_enabled", True, updated_by="test")
    
    # Create new Settings and reload from db
    settings = Settings()
    settings.reload_from_db(db_path)
    
    # Should have loaded the db value
    assert settings.trigger_enabled is True


def test_health_endpoint_unaffected(client: TestClient) -> None:
    """Test that /health still works (regression guard)."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_secrets_are_masked_in_get_response(client: TestClient, test_db: Path) -> None:
    """Test that secret values are masked in GET response."""
    from dag_dashboard.settings_store import put_setting
    
    # Write a secret
    put_setting(test_db, "slack_webhook_url", "https://hooks.slack.com/services/T00/B00/secretkey", updated_by="test")
    
    response = client.get("/api/settings")
    settings = response.json()["settings"]
    
    # Should be masked
    assert settings["slack_webhook_url"]["value"] == "•••• tkey"


def test_put_node_log_line_cap_validates_range_lower(client: TestClient) -> None:
    """Test PUT with node_log_line_cap=0 returns 400."""
    response = client.put("/api/settings", json={
        "updates": {"node_log_line_cap": 0},
        "updated_by": "test"
    })

    assert response.status_code == 400
    data = response.json()
    assert "detail" in data
    assert "errors" in data["detail"]


def test_put_node_log_line_cap_validates_range_upper(client: TestClient) -> None:
    """Test PUT with node_log_line_cap=10_000_001 returns 400."""
    response = client.put("/api/settings", json={
        "updates": {"node_log_line_cap": 10_000_001},
        "updated_by": "test"
    })

    assert response.status_code == 400
    data = response.json()
    assert "detail" in data
    assert "errors" in data["detail"]


def test_put_node_log_line_cap_accepts_boundaries(client: TestClient) -> None:
    """Test PUT with node_log_line_cap=1 and 10_000_000 are accepted."""
    # Test lower bound
    response = client.put("/api/settings", json={
        "updates": {"node_log_line_cap": 1},
        "updated_by": "test"
    })
    assert response.status_code == 200

    # Test upper bound
    response = client.put("/api/settings", json={
        "updates": {"node_log_line_cap": 10_000_000},
        "updated_by": "test"
    })
    assert response.status_code == 200


def test_put_node_log_line_cap_persists_and_reloads(client: TestClient, test_db: Path) -> None:
    """Test PUT persists node_log_line_cap to db and reloads in memory."""
    # PUT a new value
    response = client.put("/api/settings", json={
        "updates": {"node_log_line_cap": 75000},
        "updated_by": "test-user"
    })

    assert response.status_code == 200

    # GET again - should reflect new value
    response = client.get("/api/settings")
    settings = response.json()["settings"]

    assert settings["node_log_line_cap"]["value"] == 75000
    assert settings["node_log_line_cap"]["source"] == "db"


def test_node_log_line_cap_db_override_applied_on_startup(tmp_path: Path) -> None:
    """Test that node_log_line_cap from db is applied to EventCollector on startup."""
    from dag_dashboard.database import init_db
    from dag_dashboard.settings_store import put_setting

    db_path = tmp_path / "test.db"
    init_db(db_path)

    # Write a db override
    put_setting(db_path, "node_log_line_cap", 12345, updated_by="test")

    # Create app (triggers lifespan which should reload from db)
    settings = Settings()
    app = create_app(
        db_path=db_path,
        events_dir=tmp_path / "events",
        settings=settings
    )

    # Use TestClient context manager to trigger lifespan
    with TestClient(app) as client:
        # Verify collector has the db value
        assert app.state.collector.node_log_line_cap == 12345


def test_put_allow_destructive_nodes_true(client: TestClient) -> None:
    """Test PUT /api/settings with allow_destructive_nodes=true returns 200."""
    response = client.put("/api/settings", json={"updates": {"allow_destructive_nodes": True}})

    assert response.status_code == 200
    data = response.json()
    assert "settings" in data
    assert data["settings"]["allow_destructive_nodes"]["value"] is True


def test_put_allow_destructive_nodes_false(client: TestClient) -> None:
    """Test PUT /api/settings with allow_destructive_nodes=false returns 200."""
    response = client.put("/api/settings", json={"updates": {"allow_destructive_nodes": False}})

    assert response.status_code == 200
    data = response.json()
    assert "settings" in data
    assert data["settings"]["allow_destructive_nodes"]["value"] is False


def test_put_allow_destructive_nodes_rejects_non_bool(client: TestClient) -> None:
    """Test PUT /api/settings rejects non-bool value for allow_destructive_nodes."""
    response = client.put("/api/settings", json={"updates": {"allow_destructive_nodes": "yes"}})

    assert response.status_code == 400
    data = response.json()
    assert "detail" in data
    assert "errors" in data["detail"]
    errors = {e["key"]: e["detail"] for e in data["detail"]["errors"]}
    assert "allow_destructive_nodes" in errors
    assert "must be boolean" in errors["allow_destructive_nodes"]


def test_get_settings_includes_allow_destructive_nodes(client: TestClient) -> None:
    """Test GET /api/settings includes allow_destructive_nodes in merged response."""
    response = client.get("/api/settings")

    assert response.status_code == 200
    data = response.json()
    assert "settings" in data
    assert "allow_destructive_nodes" in data["settings"]

    # Should have default value (False) and source "default"
    setting = data["settings"]["allow_destructive_nodes"]
    assert setting["value"] is False
    assert setting["source"] == "default"
