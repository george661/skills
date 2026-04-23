"""Static asset tests for the Settings page (GW-5199)."""
from pathlib import Path

from fastapi.testclient import TestClient

from dag_dashboard.config import Settings
from dag_dashboard.database import init_db
from dag_dashboard.server import create_app


def _client(tmp_path: Path) -> TestClient:
    db_path = tmp_path / "test.db"
    init_db(db_path)
    settings = Settings(
        slack_enabled=False,
        slack_webhook_url="",
        trigger_enabled=False,
        workflows_dir=tmp_path / "workflows",
    )
    app = create_app(
        db_path=db_path,
        events_dir=tmp_path / "events",
        settings=settings,
    )
    return TestClient(app)


def test_settings_page_js_is_served(tmp_path: Path) -> None:
    """The settings-page.js bundle is packaged and served under /js/."""
    client = _client(tmp_path)
    response = client.get("/js/settings-page.js")
    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]
    assert "window.renderSettings" in response.text


def test_settings_page_js_posts_to_test_slack_endpoint(tmp_path: Path) -> None:
    """The settings page must call POST /api/settings/slack/test."""
    client = _client(tmp_path)
    js = client.get("/js/settings-page.js").text
    assert "/api/settings/slack/test" in js
    assert "/api/settings" in js  # GET + PUT


def test_settings_page_js_masks_secret_inputs(tmp_path: Path) -> None:
    """Secret inputs must start read-only with an Edit button affordance."""
    client = _client(tmp_path)
    js = client.get("/js/settings-page.js").text
    assert "settings-edit-btn" in js
    assert "readonly" in js
    assert "data-masked" in js


def test_index_html_links_settings_script_and_nav(tmp_path: Path) -> None:
    """index.html must link settings-page.js and include a Settings nav link."""
    client = _client(tmp_path)
    html = client.get("/").text
    # Script tag included before app.js
    settings_idx = html.find("settings-page.js")
    app_idx = html.find("/js/app.js")
    assert settings_idx != -1, "settings-page.js not referenced"
    assert app_idx != -1, "app.js not referenced"
    assert settings_idx < app_idx, "settings-page.js must be loaded before app.js"

    # Both nav bars link to #/settings
    assert html.count('href="#/settings"') >= 2, "Settings nav link missing from desktop or mobile nav"

    # Matching data-route is present
    assert 'data-route="/settings"' in html


def test_settings_css_rules_exist(tmp_path: Path) -> None:
    """styles.css contains the classes referenced by settings-page.js."""
    client = _client(tmp_path)
    css = client.get("/css/styles.css").text
    for rule in (
        ".settings-page",
        ".settings-form",
        ".settings-fieldset",
        ".settings-field",
        ".settings-error",
        ".settings-input",
        ".settings-banner",
    ):
        assert rule in css, f"{rule} missing from styles.css"


def test_app_js_registers_settings_route(tmp_path: Path) -> None:
    """app.js registers the /settings route handler."""
    client = _client(tmp_path)
    js = client.get("/js/app.js").text
    assert "router.register('/settings'" in js


def test_settings_page_references_allow_destructive_nodes(tmp_path: Path) -> None:
    """The settings page must reference allow_destructive_nodes setting."""
    client = _client(tmp_path)
    js = client.get("/js/settings-page.js").text
    assert "allow_destructive_nodes" in js, "allow_destructive_nodes key not found in settings-page.js"
    assert "Builder" in js, "Builder section not found in settings-page.js"
