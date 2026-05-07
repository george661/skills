"""Read orchestrator chat history from claude session JSONL files.

Claude persists every user + assistant turn (and everything in between) to
``~/.claude/projects/<cwd-slug>/<session_uuid>.jsonl`` whenever a session is
started with ``--session-id`` or ``--resume``. That file is the source of
truth for orchestrator conversations — we don't duplicate it in our own
``chat_messages`` table.

This module projects the JSONL format to the shape the dashboard UI already
consumes: ``role`` (operator/agent), ``content`` (string), ``created_at``
(ISO), ``session_id``.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


logger = logging.getLogger(__name__)


def _projects_root() -> Path:
    """Root directory claude stores session JSONL files under.

    Extracted so tests can monkeypatch a tmp directory without touching
    ``Path.home()`` globally.
    """
    return Path.home() / ".claude" / "projects"


def _find_session_file(session_uuid: str) -> Optional[Path]:
    """Locate the JSONL file for a session by walking the project roots.

    Claude derives the project directory from the subprocess's cwd. We don't
    capture that on the relay (and don't want to — it's implementation
    detail of claude's storage). Scanning the handful of project dirs for a
    matching UUID filename is cheap and keeps the spawn path simple.
    """
    root = _projects_root()
    if not root.is_dir():
        return None
    target = f"{session_uuid}.jsonl"
    for project_dir in root.iterdir():
        if not project_dir.is_dir():
            continue
        candidate = project_dir / target
        if candidate.is_file():
            return candidate
    return None


def _iter_records(path: Path) -> Iterable[Dict[str, Any]]:
    """Yield one parsed record per non-empty line.

    Silently skips lines that fail to parse — claude may still be writing
    the last record when we read, and a half-flushed line must not crash
    the history endpoint.
    """
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    yield json.loads(stripped)
                except json.JSONDecodeError as e:
                    logger.debug(
                        f"skipping malformed JSONL line in {path}: {e}"
                    )
    except OSError as e:
        logger.warning(f"failed to read session JSONL {path}: {e}")


def _extract_assistant_text(message: Dict[str, Any]) -> str:
    """Join all text blocks in an assistant message; skip tool_use blocks.

    Claude emits assistant messages as ``{"content": [{"type":"text",...},
    {"type":"tool_use",...}]}``. The dashboard only renders text; tool use
    shows up implicitly via the orchestrator's eventual conclusion.
    """
    content = message.get("content")
    if isinstance(content, str):
        # Defensive: older CLI versions and some tests emit a bare string.
        return content
    if not isinstance(content, list):
        return ""
    parts: List[str] = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            text = block.get("text", "")
            if isinstance(text, str):
                parts.append(text)
    return "".join(parts)


def _extract_user_text(message: Dict[str, Any]) -> str:
    """User messages are either a bare string or a list with a text block."""
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: List[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text", "")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)
    return ""


def read_session_transcript(session_uuid: str) -> List[Dict[str, Any]]:
    """Return the chat history for a claude session, projected to UI shape.

    Each returned row has:
        role:        "operator" (user) or "agent" (assistant)
        content:     concatenated text
        created_at:  ISO timestamp from the JSONL record
        session_id:  the claude session UUID

    Returns an empty list if the JSONL does not exist (session never ran,
    or was deleted, or the UUID is wrong). Tool-only assistant turns with
    no text are filtered out — they'd render as empty bubbles in the UI.
    """
    path = _find_session_file(session_uuid)
    if path is None:
        return []

    rows: List[Dict[str, Any]] = []
    for record in _iter_records(path):
        record_type = record.get("type")
        if record_type not in ("user", "assistant"):
            # Skip last-prompt, queue-operation, and any future bookkeeping
            # records claude introduces.
            continue
        message = record.get("message") or {}
        if record_type == "user":
            text = _extract_user_text(message)
            role = "operator"
        else:
            text = _extract_assistant_text(message)
            role = "agent"
        if not text:
            continue
        rows.append({
            "role": role,
            "content": text,
            "created_at": record.get("timestamp", ""),
            "session_id": record.get("sessionId", session_uuid),
        })
    return rows
