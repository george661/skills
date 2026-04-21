"""Tests for CLI cancel subcommand."""
import json
import tempfile
from pathlib import Path
import pytest
from dag_executor.cli import run_cancel


def test_cli_cancel_writes_atomic_marker():
    """Test that cancel subcommand writes atomic marker file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        events_dir = Path(tmpdir)
        run_id = "test-run-123"
        
        # Run cancel with explicit events dir
        argv = [ run_id, "--events-dir", str(events_dir), "--cancelled-by", "test-user"]
        result = run_cancel(argv)
        
        # Verify marker file exists
        marker_path = events_dir / f"{run_id}.cancel"
        assert marker_path.exists(), f"Marker file should exist at {marker_path}"
        
        # Verify contents parse as JSON with required fields
        with open(marker_path) as f:
            data = json.load(f)
        
        assert "cancelled_by" in data
        assert data["cancelled_by"] == "test-user"
        assert "cancelled_at" in data
        # cancelled_at should be ISO-8601 format
        assert "T" in data["cancelled_at"]
        assert result == 0


def test_cli_cancel_unknown_run_id_still_writes_marker():
    """Test that cancel writes marker even for unknown run_id (server decides 404)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        events_dir = Path(tmpdir)
        run_id = "nonexistent-run"
        
        # Run cancel - should still write marker (no local validation)
        argv = [ run_id, "--events-dir", str(events_dir)]
        result = run_cancel(argv)
        
        # Verify marker file exists
        marker_path = events_dir / f"{run_id}.cancel"
        assert marker_path.exists()
        assert result == 0


def test_cli_events_dir_flag_and_env_var(monkeypatch):
    """Test that --events-dir flag and DAG_EVENTS_DIR env var both work."""
    with tempfile.TemporaryDirectory() as tmpdir:
        events_dir_flag = Path(tmpdir) / "flag"
        events_dir_env = Path(tmpdir) / "env"
        events_dir_flag.mkdir()
        events_dir_env.mkdir()
        
        run_id = "test-run-456"
        
        # Test with flag (flag should take precedence)
        monkeypatch.setenv("DAG_EVENTS_DIR", str(events_dir_env))
        argv = [ run_id, "--events-dir", str(events_dir_flag)]
        result = run_cancel(argv)
        
        # Verify marker in flag dir, not env dir
        assert (events_dir_flag / f"{run_id}.cancel").exists()
        assert not (events_dir_env / f"{run_id}.cancel").exists()
        assert result == 0
        
        # Test with env var only
        run_id_2 = "test-run-789"
        argv_env = [run_id_2]
        result_env = run_cancel(argv_env)
        
        # Should use env var dir
        assert (events_dir_env / f"{run_id_2}.cancel").exists()
        assert result_env == 0


# ---------------------------------------------------------------------------
# Regression tests for review feedback (C1 — path traversal)
# ---------------------------------------------------------------------------


def test_cli_cancel_rejects_path_traversal_run_id():
    """Malformed run_id containing .. or / must not escape events_dir."""
    with tempfile.TemporaryDirectory() as tmpdir:
        events_dir = Path(tmpdir) / "events"
        events_dir.mkdir()

        argv = ["../../etc/passwd", "--events-dir", str(events_dir)]
        result = run_cancel(argv)

        assert result == 2, "expected exit code 2 for invalid run_id"
        assert not list(events_dir.glob("*.cancel")), (
            "path-traversal run_id wrote a marker inside events_dir"
        )
        # The escape target also must not exist.
        assert not (Path(tmpdir) / "passwd.cancel").exists()


def test_cli_cancel_rejects_slash_in_run_id():
    """Slash in run_id must be rejected (would create a subdirectory)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        events_dir = Path(tmpdir)

        argv = ["foo/bar", "--events-dir", str(events_dir)]
        result = run_cancel(argv)

        assert result == 2
        assert not any(events_dir.glob("**/*.cancel"))


def test_cli_cancel_accepts_uuid_style_run_id():
    """Valid UUID-style run_id is accepted and writes the marker."""
    with tempfile.TemporaryDirectory() as tmpdir:
        events_dir = Path(tmpdir)
        run_id = "550e8400-e29b-41d4-a716-446655440000"

        argv = [run_id, "--events-dir", str(events_dir)]
        result = run_cancel(argv)

        assert result == 0
        assert (events_dir / f"{run_id}.cancel").exists()
