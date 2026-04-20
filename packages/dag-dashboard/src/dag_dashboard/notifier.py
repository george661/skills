"""Slack notifier: transports Block Kit cards to Slack with per-run threading.

Two transport modes are supported:

- **Webhook** — POSTs the card JSON directly to an incoming webhook URL. Slack
  webhooks do not return the message ``ts``, so threading is not available in
  this mode. Every notification is a top-level message.
- **Bot token** — POSTs to ``https://slack.com/api/chat.postMessage`` with an
  ``Authorization: Bearer`` header and a ``channel`` id. The first event for a
  given ``run_id`` is stored in the ``slack_threads`` SQLite table; subsequent
  events for the same ``run_id`` include ``thread_ts`` so they land in the
  original thread.

Slack API errors are logged but never raised — an outage on Slack's side must
not crash dashboard event processing.
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Protocol, Tuple

logger = logging.getLogger(__name__)

SLACK_POST_MESSAGE_URL = "https://slack.com/api/chat.postMessage"


class HttpClient(Protocol):
    """Minimal HTTP client contract satisfied by httpx.Client."""

    def post(
        self,
        url: str,
        *,
        json: Optional[Dict[str, Any]] = ...,
        headers: Optional[Dict[str, str]] = ...,
    ) -> Any: ...


class SlackNotifierConfigError(ValueError):
    """Raised when Slack notifier configuration is invalid."""


class SlackNotifier:
    """Send Block Kit cards to Slack, threading per workflow run."""

    def __init__(
        self,
        db_path: Path,
        *,
        webhook_url: Optional[str] = None,
        bot_token: Optional[str] = None,
        channel_id: Optional[str] = None,
        http_client: Optional[HttpClient] = None,
    ) -> None:
        """Initialize notifier.

        Args:
            db_path: Path to the dashboard SQLite database (for slack_threads).
            webhook_url: Slack incoming webhook URL (mutually exclusive with bot_token).
            bot_token: Slack bot token starting with ``xoxb-``.
            channel_id: Slack channel id (required when using bot_token).
            http_client: HTTP client with a ``post`` method. Defaults to
                ``httpx.Client(timeout=10.0)`` when omitted.

        Raises:
            SlackNotifierConfigError: If both or neither transport is configured,
                or if bot_token is given without channel_id.
        """
        if bool(webhook_url) == bool(bot_token):
            raise SlackNotifierConfigError(
                "Exactly one of webhook_url or bot_token must be configured."
            )
        if bot_token and not channel_id:
            raise SlackNotifierConfigError(
                "channel_id is required when bot_token is set."
            )

        self._db_path = db_path
        self._webhook_url = webhook_url
        self._bot_token = bot_token
        self._channel_id = channel_id

        if http_client is None:
            import httpx  # local import: avoid hard dep at module import time

            http_client = httpx.Client(timeout=10.0)
        self._http = http_client

    def notify(self, run_id: str, event_type: str, card: Dict[str, Any]) -> None:
        """Send a card for the given run, threading if possible.

        Network and API errors are logged; never raised.
        """
        try:
            if self._webhook_url:
                self._send_webhook(card)
            else:
                self._send_bot(run_id, card)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(
                "Slack notify failed for run_id=%s event_type=%s: %s",
                run_id,
                event_type,
                exc,
            )

    # -- transports -----------------------------------------------------

    def _send_webhook(self, card: Dict[str, Any]) -> None:
        assert self._webhook_url is not None
        response = self._http.post(self._webhook_url, json=card)
        status = getattr(response, "status_code", 0)
        if status >= 400:
            logger.warning("Slack webhook returned HTTP %s", status)

    def _send_bot(self, run_id: str, card: Dict[str, Any]) -> None:
        assert self._bot_token is not None
        assert self._channel_id is not None

        existing = self._lookup_thread(run_id)
        body: Dict[str, Any] = dict(card)
        body["channel"] = self._channel_id
        if existing is not None:
            _, thread_ts = existing
            body["thread_ts"] = thread_ts

        headers = {
            "Authorization": f"Bearer {self._bot_token}",
            "Content-Type": "application/json; charset=utf-8",
        }
        response = self._http.post(SLACK_POST_MESSAGE_URL, json=body, headers=headers)

        status = getattr(response, "status_code", 0)
        if status >= 400:
            logger.warning("Slack chat.postMessage returned HTTP %s", status)
            return

        try:
            payload = response.json()
        except Exception as exc:
            logger.warning("Slack response was not JSON: %s", exc)
            return

        if not payload.get("ok"):
            logger.warning("Slack chat.postMessage error: %s", payload.get("error"))
            return

        ts = payload.get("ts")
        if existing is None and ts:
            self._store_thread(run_id, self._channel_id, ts)

    # -- slack_threads persistence --------------------------------------

    def _lookup_thread(self, run_id: str) -> Optional[Tuple[str, str]]:
        conn = sqlite3.connect(self._db_path)
        try:
            row = conn.execute(
                "SELECT channel_id, thread_ts FROM slack_threads WHERE run_id = ? "
                "ORDER BY id ASC LIMIT 1",
                (run_id,),
            ).fetchone()
        finally:
            conn.close()
        if row is None:
            return None
        return (row[0], row[1])

    def _store_thread(self, run_id: str, channel_id: str, thread_ts: str) -> None:
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        conn = sqlite3.connect(self._db_path)
        try:
            conn.execute(
                "INSERT INTO slack_threads (run_id, channel_id, thread_ts, created_at) "
                "VALUES (?, ?, ?, ?)",
                (run_id, channel_id, thread_ts, now),
            )
            conn.commit()
        finally:
            conn.close()
