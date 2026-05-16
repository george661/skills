"""Tests for /api/runs/{run_id}/pending-changes routes."""
import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dag_dashboard.database import init_db
from dag_dashboard.server import create_app


@pytest.fixture
def client(tmp_path: Path):
    """Create test client with workspace support."""
    db_dir = tmp_path
    init_db(db_dir / "dashboard.db")
    events_dir = tmp_path / "events"
    events_dir.mkdir()
    checkpoint_dir = tmp_path / "checkpoints"
    checkpoint_dir.mkdir(exist_ok=True)

    workflows_dir = tmp_path / "workflows"
    workflows_dir.mkdir()
    (workflows_dir / "prompts").mkdir()
    (workflows_dir / "scripts").mkdir()

    app = create_app(
        db_dir,
        events_dir=events_dir,
        checkpoint_dir_fallback=str(checkpoint_dir),
        workflows_dirs=[workflows_dir]
    )
    return TestClient(app), db_dir / "dashboard.db", tmp_path


def test_pending_changes_returns_empty_when_no_workspace_channel(client) -> None:
    """Test route returns empty when no workspace channel exists."""
    c, db_path, tmp = client
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(
        "INSERT INTO workflow_runs (id, workflow_name, status, started_at) VALUES (?,?,?,?)",
        ("run-1", "wf", "completed", "2026-05-16T00:00:00Z"),
    )
    conn.commit()
    conn.close()

    r = c.get("/api/runs/run-1/pending-changes")
    assert r.status_code == 200
    body = r.json()
    assert body == {"changes": []}


def test_pending_changes_returns_empty_when_workspace_dir_absent(client) -> None:
    """Test route returns empty when workspace path doesn't exist on disk."""
    c, db_path, tmp = client
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(
        "INSERT INTO workflow_runs (id, workflow_name, status, started_at) VALUES (?,?,?,?)",
        ("run-2", "wf", "running", "2026-05-16T00:00:00Z"),
    )
    # Set workspace channel but point to non-existent dir
    conn.execute(
        "INSERT INTO channel_states (run_id, channel_key, channel_type, value_json, updated_at) VALUES (?,?,?,?,?)",
        ("run-2", "workspace", "value", json.dumps(str(tmp / "nonexistent")), "2026-05-16T00:00:01Z"),
    )
    conn.commit()
    conn.close()

    r = c.get("/api/runs/run-2/pending-changes")
    assert r.status_code == 200
    assert r.json() == {"changes": []}


def test_pending_changes_returns_modified_changes(client) -> None:
    """Test route returns modified changes with diff."""
    c, db_path, tmp = client

    # Setup workspace with manifest and modified file
    workspace = tmp / "workspace"
    workspace.mkdir()
    workflow_dir = workspace / ".workflow"
    workflow_dir.mkdir()

    # Create source file
    source_file = tmp / "source.txt"
    source_file.write_text("original content\n")

    # Create manifest
    manifest = [
        {
            "workspace_path": ".workflow/test.txt",
            "source_path": str(source_file),
            "kind": "workflow"
        }
    ]
    (workflow_dir / ".manifest.json").write_text(json.dumps(manifest))

    # Create modified workspace file
    (workflow_dir / "test.txt").write_text("modified content\n")

    # Setup DB
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(
        "INSERT INTO workflow_runs (id, workflow_name, status, started_at) VALUES (?,?,?,?)",
        ("run-3", "wf", "running", "2026-05-16T00:00:00Z"),
    )
    conn.execute(
        "INSERT INTO channel_states (run_id, channel_key, channel_type, value_json, updated_at) VALUES (?,?,?,?,?)",
        ("run-3", "workspace", "value", json.dumps(str(workspace)), "2026-05-16T00:00:01Z"),
    )
    conn.commit()
    conn.close()

    r = c.get("/api/runs/run-3/pending-changes")
    assert r.status_code == 200
    body = r.json()
    assert len(body["changes"]) == 1
    change = body["changes"][0]
    assert change["workspace_path"] == ".workflow/test.txt"
    assert change["source_path"] == str(source_file)
    assert change["kind"] == "modified"
    assert change["manifest_kind"] == "workflow"
    assert "+" in change["diff"] or "-" in change["diff"]  # Has actual diff content


def test_pending_changes_returns_new_files(client) -> None:
    """Test route returns new files not in manifest."""
    c, db_path, tmp = client

    workspace = tmp / "workspace"
    workspace.mkdir()
    workflow_dir = workspace / ".workflow"
    workflow_dir.mkdir()

    # Empty manifest
    (workflow_dir / ".manifest.json").write_text("[]")

    # Create new file
    prompts_dir = workflow_dir / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "new.md").write_text("# New prompt\n")

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(
        "INSERT INTO workflow_runs (id, workflow_name, status, started_at) VALUES (?,?,?,?)",
        ("run-4", "wf", "running", "2026-05-16T00:00:00Z"),
    )
    conn.execute(
        "INSERT INTO channel_states (run_id, channel_key, channel_type, value_json, updated_at) VALUES (?,?,?,?,?)",
        ("run-4", "workspace", "value", json.dumps(str(workspace)), "2026-05-16T00:00:01Z"),
    )
    conn.commit()
    conn.close()

    r = c.get("/api/runs/run-4/pending-changes")
    assert r.status_code == 200
    body = r.json()
    assert len(body["changes"]) == 1
    change = body["changes"][0]
    assert change["workspace_path"] == ".workflow/prompts/new.md"
    assert change["source_path"] is None
    assert change["kind"] == "new"
    assert change["diff"] == ""  # New files have empty diff
    assert change["suggested_target_path"] is not None  # Should suggest prompts/ dir


def test_pending_changes_new_file_includes_suggested_target(client) -> None:
    """Test new file in prompts/ includes suggested target path."""
    c, db_path, tmp = client

    workspace = tmp / "workspace"
    workspace.mkdir()
    workflow_dir = workspace / ".workflow"
    workflow_dir.mkdir()

    (workflow_dir / ".manifest.json").write_text("[]")

    prompts_dir = workflow_dir / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "foo.md").write_text("# Foo\n")

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(
        "INSERT INTO workflow_runs (id, workflow_name, status, started_at) VALUES (?,?,?,?)",
        ("run-4b", "wf", "running", "2026-05-16T00:00:00Z"),
    )
    conn.execute(
        "INSERT INTO channel_states (run_id, channel_key, channel_type, value_json, updated_at) VALUES (?,?,?,?,?)",
        ("run-4b", "workspace", "value", json.dumps(str(workspace)), "2026-05-16T00:00:01Z"),
    )
    conn.commit()
    conn.close()

    r = c.get("/api/runs/run-4b/pending-changes")
    assert r.status_code == 200
    body = r.json()
    assert len(body["changes"]) == 1
    change = body["changes"][0]
    assert change["suggested_target_path"] == str(tmp / "workflows" / "prompts" / "foo.md")


def test_pending_changes_returns_404_for_unknown_run(client) -> None:
    """Test route returns 404 for non-existent run."""
    c, _, _ = client
    r = c.get("/api/runs/does-not-exist/pending-changes")
    assert r.status_code == 404


def test_apply_change_modified_writes_back_to_source(client) -> None:
    """Test applying modified file writes workspace content back to source."""
    c, db_path, tmp = client

    workspace = tmp / "workspace"
    workspace.mkdir()
    workflow_dir = workspace / ".workflow"
    workflow_dir.mkdir()

    source_file = tmp / "source.txt"
    source_file.write_text("original\n")

    manifest = [{"workspace_path": ".workflow/test.txt", "source_path": str(source_file), "kind": "workflow"}]
    (workflow_dir / ".manifest.json").write_text(json.dumps(manifest))
    (workflow_dir / "test.txt").write_text("modified\n")

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(
        "INSERT INTO workflow_runs (id, workflow_name, status, started_at) VALUES (?,?,?,?)",
        ("run-6", "wf", "running", "2026-05-16T00:00:00Z"),
    )
    conn.execute(
        "INSERT INTO channel_states (run_id, channel_key, channel_type, value_json, updated_at) VALUES (?,?,?,?,?)",
        ("run-6", "workspace", "value", json.dumps(str(workspace)), "2026-05-16T00:00:01Z"),
    )
    conn.commit()
    conn.close()

    r = c.post(
        "/api/runs/run-6/pending-changes/apply",
        json={"workspace_path": ".workflow/test.txt", "action": "apply"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["applied"] is True
    assert source_file.read_text() == "modified\n"


def test_apply_new_file_without_target_path_returns_400(client) -> None:
    """Test applying new file without target_path returns 400."""
    c, db_path, tmp = client

    workspace = tmp / "workspace"
    workspace.mkdir()
    workflow_dir = workspace / ".workflow"
    workflow_dir.mkdir()

    (workflow_dir / ".manifest.json").write_text("[]")
    prompts_dir = workflow_dir / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "x.md").write_text("# X\n")

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(
        "INSERT INTO workflow_runs (id, workflow_name, status, started_at) VALUES (?,?,?,?)",
        ("run-7", "wf", "running", "2026-05-16T00:00:00Z"),
    )
    conn.execute(
        "INSERT INTO channel_states (run_id, channel_key, channel_type, value_json, updated_at) VALUES (?,?,?,?,?)",
        ("run-7", "workspace", "value", json.dumps(str(workspace)), "2026-05-16T00:00:01Z"),
    )
    conn.commit()
    conn.close()

    r = c.post(
        "/api/runs/run-7/pending-changes/apply",
        json={"workspace_path": ".workflow/prompts/x.md", "action": "apply"}
    )
    assert r.status_code == 400
    assert "target_path required" in r.json()["detail"]


def test_apply_new_file_with_target_path_writes_to_target(client) -> None:
    """Test applying new file with target_path writes file to target."""
    c, db_path, tmp = client

    workspace = tmp / "workspace"
    workspace.mkdir()
    workflow_dir = workspace / ".workflow"
    workflow_dir.mkdir()

    (workflow_dir / ".manifest.json").write_text("[]")
    prompts_dir = workflow_dir / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "new.md").write_text("# New\n")

    target_file = tmp / "target.md"

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(
        "INSERT INTO workflow_runs (id, workflow_name, status, started_at) VALUES (?,?,?,?)",
        ("run-8", "wf", "running", "2026-05-16T00:00:00Z"),
    )
    conn.execute(
        "INSERT INTO channel_states (run_id, channel_key, channel_type, value_json, updated_at) VALUES (?,?,?,?,?)",
        ("run-8", "workspace", "value", json.dumps(str(workspace)), "2026-05-16T00:00:01Z"),
    )
    conn.commit()
    conn.close()

    r = c.post(
        "/api/runs/run-8/pending-changes/apply",
        json={
            "workspace_path": ".workflow/prompts/new.md",
            "action": "apply",
            "target_path": str(target_file)
        }
    )
    assert r.status_code == 200
    body = r.json()
    assert body["applied"] is True
    assert target_file.exists()
    assert target_file.read_text() == "# New\n"


def test_apply_discard_modified_restores_workspace_to_source(client) -> None:
    """Test discarding modified file removes it from workspace."""
    c, db_path, tmp = client

    workspace = tmp / "workspace"
    workspace.mkdir()
    workflow_dir = workspace / ".workflow"
    workflow_dir.mkdir()

    source_file = tmp / "source.txt"
    source_file.write_text("original\n")

    manifest = [{"workspace_path": ".workflow/test.txt", "source_path": str(source_file), "kind": "workflow"}]
    (workflow_dir / ".manifest.json").write_text(json.dumps(manifest))
    workspace_file = workflow_dir / "test.txt"
    workspace_file.write_text("modified\n")

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(
        "INSERT INTO workflow_runs (id, workflow_name, status, started_at) VALUES (?,?,?,?)",
        ("run-9", "wf", "running", "2026-05-16T00:00:00Z"),
    )
    conn.execute(
        "INSERT INTO channel_states (run_id, channel_key, channel_type, value_json, updated_at) VALUES (?,?,?,?,?)",
        ("run-9", "workspace", "value", json.dumps(str(workspace)), "2026-05-16T00:00:01Z"),
    )
    conn.commit()
    conn.close()

    r = c.post(
        "/api/runs/run-9/pending-changes/apply",
        json={"workspace_path": ".workflow/test.txt", "action": "discard"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["applied"] is True
    assert not workspace_file.exists()


def test_apply_discard_new_removes_file(client) -> None:
    """Test discarding new file removes it from workspace."""
    c, db_path, tmp = client

    workspace = tmp / "workspace"
    workspace.mkdir()
    workflow_dir = workspace / ".workflow"
    workflow_dir.mkdir()

    (workflow_dir / ".manifest.json").write_text("[]")
    prompts_dir = workflow_dir / "prompts"
    prompts_dir.mkdir()
    new_file = prompts_dir / "new.md"
    new_file.write_text("# New\n")

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(
        "INSERT INTO workflow_runs (id, workflow_name, status, started_at) VALUES (?,?,?,?)",
        ("run-10", "wf", "running", "2026-05-16T00:00:00Z"),
    )
    conn.execute(
        "INSERT INTO channel_states (run_id, channel_key, channel_type, value_json, updated_at) VALUES (?,?,?,?,?)",
        ("run-10", "workspace", "value", json.dumps(str(workspace)), "2026-05-16T00:00:01Z"),
    )
    conn.commit()
    conn.close()

    r = c.post(
        "/api/runs/run-10/pending-changes/apply",
        json={"workspace_path": ".workflow/prompts/new.md", "action": "discard"}
    )
    assert r.status_code == 200
    assert not new_file.exists()


def test_apply_returns_404_when_workspace_path_not_in_pending_changes(client) -> None:
    """Test applying non-pending path returns 404."""
    c, db_path, tmp = client

    workspace = tmp / "workspace"
    workspace.mkdir()
    workflow_dir = workspace / ".workflow"
    workflow_dir.mkdir()
    (workflow_dir / ".manifest.json").write_text("[]")

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(
        "INSERT INTO workflow_runs (id, workflow_name, status, started_at) VALUES (?,?,?,?)",
        ("run-11", "wf", "running", "2026-05-16T00:00:00Z"),
    )
    conn.execute(
        "INSERT INTO channel_states (run_id, channel_key, channel_type, value_json, updated_at) VALUES (?,?,?,?,?)",
        ("run-11", "workspace", "value", json.dumps(str(workspace)), "2026-05-16T00:00:01Z"),
    )
    conn.commit()
    conn.close()

    r = c.post(
        "/api/runs/run-11/pending-changes/apply",
        json={"workspace_path": ".workflow/nonexistent.txt", "action": "apply"}
    )
    assert r.status_code == 404


def test_apply_rejects_path_traversal_workspace_path(client) -> None:
    """Test applying path with .. returns 404 (no matching change)."""
    c, db_path, tmp = client

    workspace = tmp / "workspace"
    workspace.mkdir()
    workflow_dir = workspace / ".workflow"
    workflow_dir.mkdir()
    (workflow_dir / ".manifest.json").write_text("[]")

    # Create a sentinel file outside workspace
    parent_sentinel = tmp / "sentinel.txt"
    parent_sentinel.write_text("should not be modified")

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(
        "INSERT INTO workflow_runs (id, workflow_name, status, started_at) VALUES (?,?,?,?)",
        ("run-11b", "wf", "running", "2026-05-16T00:00:00Z"),
    )
    conn.execute(
        "INSERT INTO channel_states (run_id, channel_key, channel_type, value_json, updated_at) VALUES (?,?,?,?,?)",
        ("run-11b", "workspace", "value", json.dumps(str(workspace)), "2026-05-16T00:00:01Z"),
    )
    conn.commit()
    conn.close()

    r = c.post(
        "/api/runs/run-11b/pending-changes/apply",
        json={"workspace_path": "../../sentinel.txt", "action": "apply"}
    )
    assert r.status_code == 404
    # Verify sentinel was not touched
    assert parent_sentinel.read_text() == "should not be modified"


def test_apply_discard_returns_structured_error_when_unlink_fails(
    client, monkeypatch
) -> None:
    """Regression test for C1 (UnboundLocalError): when unlink raises, the
    handler must return a structured ApplyChangeResponse with applied=False,
    not crash with UnboundLocalError on source_path_str.
    """
    c, db_path, tmp = client

    workspace = tmp / "workspace"
    workspace.mkdir()
    workflow_dir = workspace / ".workflow"
    workflow_dir.mkdir()

    source_file = tmp / "source.txt"
    source_file.write_text("original\n")

    manifest = [{"workspace_path": ".workflow/test.txt", "source_path": str(source_file), "kind": "workflow_yaml"}]
    (workflow_dir / ".manifest.json").write_text(json.dumps(manifest))
    workspace_file = workflow_dir / "test.txt"
    workspace_file.write_text("modified\n")

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(
        "INSERT INTO workflow_runs (id, workflow_name, status, started_at) VALUES (?,?,?,?)",
        ("run-12", "wf", "running", "2026-05-16T00:00:00Z"),
    )
    conn.execute(
        "INSERT INTO channel_states (run_id, channel_key, channel_type, value_json, updated_at) VALUES (?,?,?,?,?)",
        ("run-12", "workspace", "value", json.dumps(str(workspace)), "2026-05-16T00:00:01Z"),
    )
    conn.commit()
    conn.close()

    # Force unlink to raise to drive the except branch.
    original_unlink = Path.unlink

    def boom(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        if self == workspace_file:
            raise PermissionError("simulated unlink failure")
        return original_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", boom)

    r = c.post(
        "/api/runs/run-12/pending-changes/apply",
        json={"workspace_path": ".workflow/test.txt", "action": "discard"}
    )
    # Must return 200 with structured failure body, NOT 500 from
    # UnboundLocalError on source_path_str.
    assert r.status_code == 200, f"got {r.status_code}: {r.text}"
    body = r.json()
    assert body["applied"] is False
    assert body["source_path"] == str(source_file)
    assert "simulated unlink failure" in body["error"]
