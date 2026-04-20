"""Tests for ``SlackNotifier`` transport + threading behavior."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytest

from dag_dashboard.notifier import (
    SLACK_POST_MESSAGE_URL,
    SlackNotifier,
    SlackNotifierConfigError,
)


class FakeResponse:
    def __init__(self, status_code: int = 200, payload: Optional[Dict[str, Any]] = None) -> None:
        self.status_code = status_code
        self._payload = payload if payload is not None else {"ok": True, "ts": "1.0"}

    def json(self) -> Dict[str, Any]:
        return self._payload


class FakeHttpClient:
    """Records posts and returns a scripted sequence of responses."""

    def __init__(self, responses: Optional[List[FakeResponse]] = None) -> None:
        self.responses = list(responses) if responses else []
        self.posts: List[Tuple[str, Dict[str, Any], Dict[str, str]]] = []

    def post(
        self,
        url: str,
        *,
        json: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> FakeResponse:
        self.posts.append((url, json or {}, headers or {}))
        if self.responses:
            return self.responses.pop(0)
        return FakeResponse()


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    db = tmp_path / "dashboard.db"
    conn = sqlite3.connect(db)
    try:
        conn.executescript(
            """
            CREATE TABLE slack_threads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                thread_ts TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        conn.commit()
    finally:
        conn.close()
    return db


CARD: Dict[str, Any] = {"text": "hi", "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": "hi"}}]}


# ------------------- config validation -------------------


def test_config_requires_exactly_one_transport(db_path: Path) -> None:
    with pytest.raises(SlackNotifierConfigError):
        SlackNotifier(db_path=db_path, http_client=FakeHttpClient())

    with pytest.raises(SlackNotifierConfigError):
        SlackNotifier(
            db_path=db_path,
            webhook_url="https://hooks.slack.com/x",
            bot_token="xoxb-1",
            channel_id="C1",
            http_client=FakeHttpClient(),
        )


def test_bot_token_requires_channel_id(db_path: Path) -> None:
    with pytest.raises(SlackNotifierConfigError):
        SlackNotifier(
            db_path=db_path, bot_token="xoxb-1", http_client=FakeHttpClient()
        )


# ------------------- webhook mode -------------------


def test_webhook_posts_card_without_threading(db_path: Path) -> None:
    http = FakeHttpClient([FakeResponse(200), FakeResponse(200)])
    notifier = SlackNotifier(
        db_path=db_path, webhook_url="https://hooks.slack.com/x", http_client=http
    )

    notifier.notify("run-1", "workflow_started", CARD)
    notifier.notify("run-1", "workflow_completed", CARD)

    assert len(http.posts) == 2
    for url, body, _ in http.posts:
        assert url == "https://hooks.slack.com/x"
        assert "thread_ts" not in body
        assert "channel" not in body

    # No thread should be stored for webhook mode
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute("SELECT COUNT(*) FROM slack_threads").fetchone()[0]
    finally:
        conn.close()
    assert rows == 0


def test_webhook_error_is_logged_not_raised(db_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    http = FakeHttpClient([FakeResponse(500)])
    notifier = SlackNotifier(
        db_path=db_path, webhook_url="https://hooks.slack.com/x", http_client=http
    )
    # Should not raise
    notifier.notify("run-1", "workflow_failed", CARD)
    assert any("500" in r.message for r in caplog.records)


# ------------------- bot-token mode -------------------


def test_bot_token_first_message_stores_thread(db_path: Path) -> None:
    http = FakeHttpClient([FakeResponse(200, {"ok": True, "ts": "17.1"})])
    notifier = SlackNotifier(
        db_path=db_path,
        bot_token="xoxb-abc",
        channel_id="C1",
        http_client=http,
    )

    notifier.notify("run-1", "workflow_started", CARD)

    assert len(http.posts) == 1
    url, body, headers = http.posts[0]
    assert url == SLACK_POST_MESSAGE_URL
    assert headers["Authorization"] == "Bearer xoxb-abc"
    assert body["channel"] == "C1"
    assert "thread_ts" not in body

    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT run_id, channel_id, thread_ts FROM slack_threads"
        ).fetchall()
    finally:
        conn.close()
    assert rows == [("run-1", "C1", "17.1")]


def test_bot_token_subsequent_message_threads(db_path: Path) -> None:
    http = FakeHttpClient(
        [
            FakeResponse(200, {"ok": True, "ts": "17.1"}),
            FakeResponse(200, {"ok": True, "ts": "17.2"}),
        ]
    )
    notifier = SlackNotifier(
        db_path=db_path,
        bot_token="xoxb-abc",
        channel_id="C1",
        http_client=http,
    )

    notifier.notify("run-1", "workflow_started", CARD)
    notifier.notify("run-1", "workflow_completed", CARD)

    assert len(http.posts) == 2
    _, first_body, _ = http.posts[0]
    _, second_body, _ = http.posts[1]
    assert "thread_ts" not in first_body
    assert second_body["thread_ts"] == "17.1"

    # Only the first message should have created a thread row
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute("SELECT COUNT(*) FROM slack_threads").fetchone()[0]
    finally:
        conn.close()
    assert rows == 1


def test_bot_token_different_runs_get_different_threads(db_path: Path) -> None:
    http = FakeHttpClient(
        [
            FakeResponse(200, {"ok": True, "ts": "17.1"}),
            FakeResponse(200, {"ok": True, "ts": "18.1"}),
            FakeResponse(200, {"ok": True, "ts": "17.2"}),
        ]
    )
    notifier = SlackNotifier(
        db_path=db_path,
        bot_token="xoxb-abc",
        channel_id="C1",
        http_client=http,
    )

    notifier.notify("run-A", "workflow_started", CARD)
    notifier.notify("run-B", "workflow_started", CARD)
    notifier.notify("run-A", "workflow_completed", CARD)

    _, body_a1, _ = http.posts[0]
    _, body_b1, _ = http.posts[1]
    _, body_a2, _ = http.posts[2]
    assert "thread_ts" not in body_a1
    assert "thread_ts" not in body_b1
    assert body_a2["thread_ts"] == "17.1"


def test_bot_token_api_error_not_raised(db_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    http = FakeHttpClient(
        [FakeResponse(200, {"ok": False, "error": "channel_not_found"})]
    )
    notifier = SlackNotifier(
        db_path=db_path,
        bot_token="xoxb-abc",
        channel_id="C1",
        http_client=http,
    )

    notifier.notify("run-1", "workflow_started", CARD)

    assert any("channel_not_found" in r.message for r in caplog.records)
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute("SELECT COUNT(*) FROM slack_threads").fetchone()[0]
    finally:
        conn.close()
    assert rows == 0


def test_bot_token_http_error_not_raised(db_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    http = FakeHttpClient([FakeResponse(500, {"ok": False})])
    notifier = SlackNotifier(
        db_path=db_path,
        bot_token="xoxb-abc",
        channel_id="C1",
        http_client=http,
    )

    notifier.notify("run-1", "workflow_started", CARD)
    assert any("500" in r.message for r in caplog.records)
