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
    
    # Check deny list
    assert "deny" in settings["permissions"]
    deny_list = settings["permissions"]["deny"]
    assert "Read(/**)" in deny_list
    assert "Read(~/**)" in deny_list
    assert "Write(/**)" in deny_list
    assert "WebFetch" in deny_list
    assert "Bash(curl:*)" in deny_list
    assert "Bash(wget:*)" in deny_list
    
    # Check hooks
    assert "hooks" in settings
    assert "PreToolUse" in settings["hooks"]
    hook_config = settings["hooks"]["PreToolUse"]
    assert hook_config["matcher"] == "*"
    assert sys.executable in hook_config["command"]
    assert "dag_dashboard.orchestrator_hooks.pretool_guard" in hook_config["command"]


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
