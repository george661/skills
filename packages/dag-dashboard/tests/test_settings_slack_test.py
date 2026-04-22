"""Tests for POST /api/settings/slack/test endpoint."""
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytest
from fastapi.testclient import TestClient

from dag_dashboard.config import Settings
from dag_dashboard.database import init_db
from dag_dashboard.server import create_app
from dag_dashboard.settings_store import put_setting


class _FakeResponse:
    def __init__(self, status_code: int = 200, payload: Optional[Dict[str, Any]] = None) -> None:
        self.status_code = status_code
        self._payload = payload if payload is not None else {"ok": True, "ts": "1.0"}

    def json(self) -> Dict[str, Any]:
        return self._payload


class _FakeHttpClient:
    """Captures posts; satisfies the HttpClient protocol used by SlackNotifier."""

    def __init__(self, responses: Optional[List[_FakeResponse]] = None) -> None:
        self.responses = list(responses) if responses else []
        self.posts: List[Tuple[str, Dict[str, Any], Dict[str, str]]] = []

    def post(
        self,
        url: str,
        *,
        json: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> _FakeResponse:
        self.posts.append((url, json or {}, headers or {}))
        if self.responses:
            return self.responses.pop(0)
        return _FakeResponse()


@pytest.fixture
def test_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "test.db"
    init_db(db_path)
    return db_path


@pytest.fixture
def client(test_db: Path, tmp_path: Path) -> TestClient:
    settings = Settings(
        slack_enabled=False,
        slack_webhook_url="",
        trigger_enabled=False,
        workflows_dir=tmp_path / "workflows",
    )
    app = create_app(
        db_path=test_db,
        events_dir=tmp_path / "events",
        settings=settings,
    )
    return TestClient(app)


def test_post_slack_test_returns_error_when_disabled(client: TestClient) -> None:
    response = client.post("/api/settings/slack/test")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert "not enabled" in body["error"].lower()


def test_post_slack_test_returns_error_when_enabled_but_no_transport(client: TestClient, test_db: Path) -> None:
    # Force an inconsistent stored state by writing directly to the store. This
    # bypasses the PUT cross-field validator (which would reject this config)
    # and lets us verify the endpoint's own defensive check.
    put_setting(test_db, "slack_enabled", True)

    response = client.post("/api/settings/slack/test")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert "webhook" in body["error"].lower() or "bot token" in body["error"].lower()


def test_post_slack_test_sends_card_via_injected_http_client(
    client: TestClient, test_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Configure slack via the real PUT endpoint so validators run
    response = client.put("/api/settings", json={
        "updates": {
            "slack_enabled": True,
            "slack_webhook_url": "https://hooks.slack.com/services/T00/B00/fake",
        }
    })
    assert response.status_code == 200

    # Inject a fake HTTP client through the SlackNotifier constructor used by
    # the endpoint. We patch at the settings_routes import site so the route
    # uses our stub without touching the real httpx import.
    import dag_dashboard.settings_routes as settings_routes
    real_notifier_cls = settings_routes.SlackNotifier
    fake = _FakeHttpClient()

    def _factory(db_path, *, webhook_url=None, bot_token=None, channel_id=None, http_client=None):  # type: ignore[no-untyped-def]
        return real_notifier_cls(
            db_path=db_path,
            webhook_url=webhook_url,
            bot_token=bot_token,
            channel_id=channel_id,
            http_client=fake,
        )

    monkeypatch.setattr(settings_routes, "SlackNotifier", _factory)

    response = client.post("/api/settings/slack/test")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True, body
    assert body["error"] is None
    assert len(fake.posts) == 1
    url, payload, _ = fake.posts[0]
    assert url == "https://hooks.slack.com/services/T00/B00/fake"
    assert "blocks" in payload


def test_post_slack_test_does_not_persist_settings(
    client: TestClient, test_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    response = client.put("/api/settings", json={
        "updates": {
            "slack_enabled": True,
            "slack_webhook_url": "https://hooks.slack.com/services/T00/B00/fake",
            "dashboard_url": "http://initial.example.com",
        }
    })
    assert response.status_code == 200

    import dag_dashboard.settings_routes as settings_routes
    real_notifier_cls = settings_routes.SlackNotifier
    fake = _FakeHttpClient()

    def _factory(db_path, *, webhook_url=None, bot_token=None, channel_id=None, http_client=None):  # type: ignore[no-untyped-def]
        return real_notifier_cls(
            db_path=db_path,
            webhook_url=webhook_url,
            bot_token=bot_token,
            channel_id=channel_id,
            http_client=fake,
        )

    monkeypatch.setattr(settings_routes, "SlackNotifier", _factory)

    client.post("/api/settings/slack/test")

    after = client.get("/api/settings").json()["settings"]
    assert after["dashboard_url"]["value"] == "http://initial.example.com"
    assert after["slack_enabled"]["value"] is True
