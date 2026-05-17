"""Tests for settings.json seeding."""
import json
import sys
from pathlib import Path

import pytest

from dag_dashboard.orchestrator_hooks.settings_template import seed_settings_json


@pytest.fixture
def workspace_dir(tmp_path: Path) -> Path:
    """Create a temporary workspace directory."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return workspace


def test_seed_creates_settings_json(workspace_dir: Path):
    """seed_settings_json should create .claude/settings.json."""
    result = seed_settings_json(workspace_dir)

    assert result.exists()
    assert result == workspace_dir / ".claude" / "settings.json"


def test_seed_creates_denied_events_jsonl(workspace_dir: Path):
    """seed_settings_json should create .claude/denied-events.jsonl."""
    seed_settings_json(workspace_dir)

    sentinel = workspace_dir / ".claude" / "denied-events.jsonl"
    assert sentinel.exists()


def test_settings_json_content(workspace_dir: Path):
    """settings.json should have correct allow/deny/hooks config."""
    settings_path = seed_settings_json(workspace_dir)

    with open(settings_path) as f:
        settings = json.load(f)

    # Check allow list
    assert "permissions" in settings
    assert "allow" in settings["permissions"]
    allow_list = settings["permissions"]["allow"]
    assert "Read(./**)" in allow_list
    assert "Write(./**)" in allow_list
    assert "Edit(./**)" in allow_list
    assert "Bash(git status:*)" in allow_list
    assert "Bash(rg:*)" in allow_list

    # Check deny list — bash egress only; path denies live in the hook
    # because Claude Code's `Read(/path)` resolves project-root-relative
    # (where project root = workspace) and would block legitimate reads.
    assert "deny" in settings["permissions"]
    deny_list = settings["permissions"]["deny"]
    assert "WebFetch" in deny_list
    assert "Bash(curl:*)" in deny_list
    assert "Bash(wget:*)" in deny_list
    assert "Bash(ssh:*)" in deny_list


def test_hook_config_matches_claude_code_schema(workspace_dir: Path):
    """settings.json hooks.PreToolUse must match Claude Code's expected shape.

    Claude Code expects a list of matcher blocks, each with an inner
    `hooks` array of `{type, command}` objects. A flat `{matcher, command}`
    object is silently ignored, leaving the orchestrator unsandboxed.
    """
    settings_path = seed_settings_json(workspace_dir)

    with open(settings_path) as f:
        settings = json.load(f)

    assert "hooks" in settings
    pretool_use = settings["hooks"].get("PreToolUse")
    # Must be a list of matcher blocks
    assert isinstance(pretool_use, list), (
        f"hooks.PreToolUse must be a list, got {type(pretool_use).__name__}"
    )
    assert len(pretool_use) == 1
    block = pretool_use[0]
    assert block["matcher"] == "*"
    # Each matcher block has an inner `hooks` array of {type, command}
    assert isinstance(block["hooks"], list)
    assert len(block["hooks"]) == 1
    hook = block["hooks"][0]
    assert hook["type"] == "command"
    assert sys.executable in hook["command"]
    assert "dag_dashboard.orchestrator_hooks.pretool_guard" in hook["command"]


def test_seed_is_idempotent(workspace_dir: Path):
    """Re-seeding should overwrite cleanly."""
    # Seed twice
    path1 = seed_settings_json(workspace_dir)

    # Modify the file
    path1.write_text("corrupted")

    # Re-seed
    path2 = seed_settings_json(workspace_dir)

    assert path1 == path2
    # Should be valid JSON again
    with open(path2) as f:
        json.load(f)  # Should not raise


def test_seed_returns_absolute_path(workspace_dir: Path):
    """seed_settings_json should return an absolute path."""
    result = seed_settings_json(workspace_dir)
    assert result.is_absolute()


def test_settings_allow_list_includes_phase_6_write_side_git_commands(workspace_dir: Path):
    """settings.json allow list should include write-side git commands from Phase 6."""
    settings_path = seed_settings_json(workspace_dir)

    with open(settings_path) as f:
        settings = json.load(f)

    allow_list = settings["permissions"]["allow"]

    # Phase 6 commands
    assert "Bash(git add:*)" in allow_list
    assert "Bash(git commit:*)" in allow_list
    assert "Bash(git checkout:*)" in allow_list

    # git push should NOT be in allow list (that's GW-5717)
    assert "Bash(git push:*)" not in allow_list

    # Existing read-side command should still be present
    assert "Bash(git status:*)" in allow_list
