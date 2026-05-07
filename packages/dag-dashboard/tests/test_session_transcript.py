"""Tests for reading orchestrator chat history from claude session JSONL."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from dag_dashboard import session_transcript
from dag_dashboard.session_transcript import read_session_transcript


@pytest.fixture
def fake_claude_projects(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point ``session_transcript._projects_root`` at a tmp directory.

    Claude stores sessions under ~/.claude/projects/<cwd-slug>/<uuid>.jsonl.
    Tests need to stage fixture JSONL files without touching the real home.
    """
    projects_root = tmp_path / "projects"
    projects_root.mkdir()
    monkeypatch.setattr(
        session_transcript, "_projects_root", lambda: projects_root
    )
    return projects_root


def _write_session(projects_root: Path, session_uuid: str, records: list[dict]) -> Path:
    """Stage a JSONL fixture under a plausible project dir."""
    project_dir = projects_root / "-Users-someone-dev-project"
    project_dir.mkdir(parents=True, exist_ok=True)
    path = project_dir / f"{session_uuid}.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n")
    return path


def test_empty_when_no_file(fake_claude_projects: Path) -> None:
    """Unknown session UUIDs return an empty list, never raise.

    The /chat/history endpoint asks for history the moment a run page loads;
    if the orchestrator hasn't produced any turns yet, the JSONL doesn't
    exist. That's a normal case, not an error.
    """
    assert read_session_transcript("nonexistent-uuid") == []


def test_maps_user_and_assistant_roles(fake_claude_projects: Path) -> None:
    """user -> operator, assistant -> agent; timestamps + sessionId preserved."""
    sid = "11111111-1111-1111-1111-111111111111"
    _write_session(fake_claude_projects, sid, [
        {
            "type": "user",
            "message": {"role": "user", "content": "what's up"},
            "timestamp": "2026-05-07T10:00:00.000Z",
            "sessionId": sid,
        },
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "not much"}],
            },
            "timestamp": "2026-05-07T10:00:01.000Z",
            "sessionId": sid,
        },
    ])

    rows = read_session_transcript(sid)
    assert len(rows) == 2
    assert rows[0] == {
        "role": "operator",
        "content": "what's up",
        "created_at": "2026-05-07T10:00:00.000Z",
        "session_id": sid,
    }
    assert rows[1] == {
        "role": "agent",
        "content": "not much",
        "created_at": "2026-05-07T10:00:01.000Z",
        "session_id": sid,
    }


def test_filters_tool_use_blocks(fake_claude_projects: Path) -> None:
    """tool_use blocks inside assistant messages are stripped.

    Claude emits assistant messages whose content is a heterogeneous
    list — text blocks we render, tool_use blocks we don't. Users see
    the concatenated text; tool execution is implicit in the narrative.
    """
    sid = "22222222-2222-2222-2222-222222222222"
    _write_session(fake_claude_projects, sid, [
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "Let me check "},
                    {"type": "tool_use", "name": "Bash", "input": {"command": "curl"}, "id": "t1"},
                    {"type": "text", "text": "— the run is healthy."},
                ],
            },
            "timestamp": "2026-05-07T10:01:00.000Z",
            "sessionId": sid,
        },
    ])

    rows = read_session_transcript(sid)
    assert len(rows) == 1
    assert rows[0]["content"] == "Let me check — the run is healthy."


def test_skips_bookkeeping_records(fake_claude_projects: Path) -> None:
    """last-prompt / queue-operation / other internal types don't surface."""
    sid = "33333333-3333-3333-3333-333333333333"
    _write_session(fake_claude_projects, sid, [
        {"type": "queue-operation", "operation": "enqueue", "sessionId": sid,
         "timestamp": "2026-05-07T10:00:00Z"},
        {
            "type": "user",
            "message": {"role": "user", "content": "hi"},
            "timestamp": "2026-05-07T10:00:01Z",
            "sessionId": sid,
        },
        {"type": "last-prompt", "lastPrompt": "hi", "leafUuid": "x", "sessionId": sid},
    ])

    rows = read_session_transcript(sid)
    assert len(rows) == 1
    assert rows[0]["role"] == "operator"
    assert rows[0]["content"] == "hi"


def test_empty_assistant_text_is_filtered(fake_claude_projects: Path) -> None:
    """Tool-only assistant turns don't render as empty bubbles.

    When the orchestrator invokes a tool and the text blocks are empty,
    we'd produce a blank message in the UI. Drop those rows entirely; the
    narrative continues in the next turn.
    """
    sid = "44444444-4444-4444-4444-444444444444"
    _write_session(fake_claude_projects, sid, [
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "name": "Bash", "input": {"c": "ls"}, "id": "t1"},
                ],
            },
            "timestamp": "2026-05-07T10:00:00Z",
            "sessionId": sid,
        },
    ])

    assert read_session_transcript(sid) == []


def test_malformed_lines_are_skipped(fake_claude_projects: Path) -> None:
    """A half-written last line doesn't crash the reader.

    Claude writes JSONL incrementally; a /chat/history call racing a
    write could catch a truncated final record. The reader must tolerate
    that and return every well-formed line before it.
    """
    sid = "55555555-5555-5555-5555-555555555555"
    path = fake_claude_projects / "-Users-x-dev-y"
    path.mkdir()
    jsonl = path / f"{sid}.jsonl"
    good_record = {
        "type": "user",
        "message": {"role": "user", "content": "hi"},
        "timestamp": "2026-05-07T10:00:00Z",
        "sessionId": sid,
    }
    jsonl.write_text(json.dumps(good_record) + "\n" + '{"type":"user","message":')

    rows = read_session_transcript(sid)
    assert len(rows) == 1
    assert rows[0]["content"] == "hi"


def test_search_walks_project_dirs(fake_claude_projects: Path) -> None:
    """The session file can live under any project-slug directory.

    We don't capture the subprocess cwd when spawning claude; the lookup
    walks every project dir under ~/.claude/projects and returns the
    first match by UUID. This test stages the file under a distinctly-
    named project to prove the walk.
    """
    sid = "66666666-6666-6666-6666-666666666666"
    other = fake_claude_projects / "-some-random-other-dir"
    other.mkdir()
    target = fake_claude_projects / "-Users-someone-dev-elsewhere"
    target.mkdir()
    (target / f"{sid}.jsonl").write_text(json.dumps({
        "type": "assistant",
        "message": {"role": "assistant", "content": [{"type": "text", "text": "found"}]},
        "timestamp": "2026-05-07T10:00:00Z",
        "sessionId": sid,
    }) + "\n")

    rows = read_session_transcript(sid)
    assert len(rows) == 1
    assert rows[0]["content"] == "found"
