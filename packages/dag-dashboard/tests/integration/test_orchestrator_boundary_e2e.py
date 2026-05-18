"""End-to-end tests for the orchestrator edit boundary (GW-5928 / GW-6012).

These tests spawn an actual ``claude`` subprocess (no mocks) against a temp
workspace seeded the way :func:`OrchestratorRelay.start` does, then ask the
agent to perform tool operations and assert the boundary holds.

Why these are required: the unit tests in ``test_orchestrator_settings_seed.py``
and ``test_pretool_guard.py`` validate the JSON shape of the seeded
``settings.json`` and the deny logic of the hook script in isolation. They
do NOT spawn ``claude`` and so they cannot detect:

- ``--bare`` skipping hooks unconditionally (the GW-6012 root cause)
- Settings-merge behavior between user ``~/.claude/settings.json`` and the
  workspace settings.json
- Whether the actual stream-json tool-use payload makes it through the hook
  to the deny path

Opt-in via ``DAG_ORCHESTRATOR_BOUNDARY_E2E=1`` because:

- ``claude`` binary may not be on PATH (CI runners)
- AWS credentials must be valid for Bedrock (CI doesn't have them)
- Wall-clock cost is ~10-30s per test
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Generator

import pytest


pytestmark = pytest.mark.skipif(
    os.getenv("DAG_ORCHESTRATOR_BOUNDARY_E2E") != "1",
    reason=(
        "Orchestrator boundary e2e tests are opt-in. Set "
        "DAG_ORCHESTRATOR_BOUNDARY_E2E=1 to enable. Requires `claude` on "
        "PATH and valid Bedrock credentials."
    ),
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def claude_binary() -> str:
    """Locate the ``claude`` binary, skipping the test if not installed."""
    binary = shutil.which("claude")
    if not binary:
        pytest.skip("`claude` not found on PATH")
    return binary


@pytest.fixture
def workspace(tmp_path: Path) -> Generator[Path, None, None]:
    """Seed a temp workspace with the same .claude/settings.json the relay
    would write at orchestrator spawn time.

    Mirrors the behavior of
    :func:`dag_dashboard.orchestrator_hooks.settings_template.seed_settings_json`.
    """
    from dag_dashboard.orchestrator_hooks.settings_template import (
        seed_settings_json,
    )

    ws = tmp_path / "workspace"
    ws.mkdir()
    seed_settings_json(ws)
    yield ws


def _run_claude_with_workspace_settings(
    *,
    claude_binary: str,
    workspace: Path,
    prompt: str,
    extra_env: dict | None = None,
    extra_args: list[str] | None = None,
    timeout: int = 60,
) -> subprocess.CompletedProcess:
    """Spawn claude with the same flags the relay uses (post-GW-6012).

    Returns the completed process so tests can assert on stdout / stderr /
    side effects in the workspace's .claude/denied-events.jsonl.
    """
    settings_path = workspace / ".claude" / "settings.json"
    cmd = [
        claude_binary,
        "--setting-sources", "project",
        "--settings", str(settings_path),
        "--print",
        "--permission-mode", "dontAsk",
        "--allowedTools", "Bash,Read,Write,Edit",
        "--append-system-prompt", "Reply terse. Quote deny reasons verbatim.",
        "--output-format", "text",
        *(extra_args or []),
        "--",
        prompt,
    ]
    env = {**os.environ, "DAG_ORCHESTRATOR_WORKSPACE": str(workspace)}
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        cmd,
        cwd=str(workspace),
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


# ---------------------------------------------------------------------------
# GW-6012: PreToolUse hook fires under the post-fix spawn config
# ---------------------------------------------------------------------------


@pytest.mark.timeout(120)
def test_out_of_workspace_read_is_denied(
    claude_binary: str, workspace: Path
) -> None:
    """An attempt to Read a file outside the workspace must be denied by
    the PreToolUse hook seeded into the workspace settings.json.

    This is the regression test that would have caught GW-6012 on PR-201.
    """
    target = "/etc/hosts"  # readable in principle, definitely outside workspace

    proc = _run_claude_with_workspace_settings(
        claude_binary=claude_binary,
        workspace=workspace,
        prompt=(
            f"Use the Read tool on {target}. "
            "Reply ONLY with 'PERMITTED' followed by the first line, or "
            "'DENIED' followed by the deny reason verbatim."
        ),
    )

    assert proc.returncode == 0, (
        f"claude exited {proc.returncode}: stderr={proc.stderr[-500:]!r}"
    )

    # The hook must have written a deny event for the out-of-ws read.
    denied_path = workspace / ".claude" / "denied-events.jsonl"
    assert denied_path.exists(), "denied-events.jsonl missing"
    deny_lines = [
        line for line in denied_path.read_text().splitlines() if line.strip()
    ]
    assert deny_lines, (
        f"hook did not write any deny events; stdout={proc.stdout[-500:]!r}"
    )

    # The most recent entry should refer to our target path.
    last_event = json.loads(deny_lines[-1])
    assert last_event["tool_name"] == "Read"
    assert last_event["tool_input"]["file_path"] == target
    assert "outside workspace" in last_event["reason"]


@pytest.mark.timeout(120)
def test_in_workspace_read_is_permitted(
    claude_binary: str, workspace: Path
) -> None:
    """An in-workspace read must succeed (hook returns allow, no deny event)."""
    inside = workspace / "inside.txt"
    inside.write_text("expected-content\n")

    proc = _run_claude_with_workspace_settings(
        claude_binary=claude_binary,
        workspace=workspace,
        prompt=(
            "Use the Read tool on ./inside.txt. "
            "Reply ONLY with the file contents on a single line."
        ),
    )

    assert proc.returncode == 0, (
        f"claude exited {proc.returncode}: stderr={proc.stderr[-500:]!r}"
    )
    assert "expected-content" in proc.stdout, (
        f"in-workspace read did not return expected content; "
        f"stdout={proc.stdout!r}"
    )

    # No deny event should have been written for this run.
    denied_path = workspace / ".claude" / "denied-events.jsonl"
    if denied_path.exists():
        events = [
            json.loads(line)
            for line in denied_path.read_text().splitlines()
            if line.strip()
        ]
        # Filter to events that match THIS run's read of inside.txt
        relevant = [
            e for e in events
            if e.get("tool_input", {}).get("file_path", "").endswith(
                "inside.txt"
            )
        ]
        assert not relevant, (
            f"in-workspace read was unexpectedly denied: {relevant}"
        )


# ---------------------------------------------------------------------------
# GW-6012: --setting-sources project suppresses user-level hooks
# ---------------------------------------------------------------------------


@pytest.mark.timeout(120)
def test_user_settings_hooks_are_suppressed(
    claude_binary: str, workspace: Path, tmp_path: Path
) -> None:
    """With ``--setting-sources project``, hooks declared in user
    ``~/.claude/settings.json`` must not fire on orchestrator tool calls.

    This pins the suppression invariant. Without it, every orchestrator
    tool call would also run the operator's 10+ user-level PreToolUse hooks
    (tokf, pre-command, enforce-skill-project-root, etc.) which would slow
    the orchestrator and risk side effects from hooks not designed for
    sandboxed orchestrator context.

    Strategy: point ``HOME`` at a temp dir with a marker hook that touches
    a sentinel file. After running claude, assert the sentinel does NOT
    exist — proving the user hook never fired.
    """
    fake_home = tmp_path / "fake_home"
    (fake_home / ".claude").mkdir(parents=True)
    sentinel = tmp_path / "user_hook_marker.txt"

    # Marker hook: writes the sentinel on any PreToolUse invocation.
    user_settings = {
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "*",
                    "hooks": [
                        {
                            "type": "command",
                            "command": (
                                f"{sys.executable} -c "
                                f"\"open({str(sentinel)!r}, 'w').write('fired')\""
                            ),
                        }
                    ],
                }
            ]
        }
    }
    (fake_home / ".claude" / "settings.json").write_text(
        json.dumps(user_settings)
    )

    inside = workspace / "inside.txt"
    inside.write_text("hello\n")

    proc = _run_claude_with_workspace_settings(
        claude_binary=claude_binary,
        workspace=workspace,
        prompt="Use the Read tool on ./inside.txt. Reply with the contents.",
        extra_env={"HOME": str(fake_home)},
    )

    assert proc.returncode == 0, (
        f"claude exited {proc.returncode}: stderr={proc.stderr[-500:]!r}"
    )

    # The marker hook would only fire if claude loaded user
    # ~/.claude/settings.json. With --setting-sources project it must not.
    assert not sentinel.exists(), (
        "user-level PreToolUse hook fired despite --setting-sources project. "
        f"Sentinel content: {sentinel.read_text()!r}"
    )
