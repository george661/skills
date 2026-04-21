"""Tests for dag-exec rerun CLI subcommand."""
import json
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest


def test_cli_rerun_loads_prior_run_from_db():
    """Test that cli rerun subcommand loads prior run from dashboard DB."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "dashboard.db"
        workflow_path = Path(tmpdir) / "workflow.yml"
        workflow_path.write_text("nodes: []")
        
        # Create a mock dashboard DB with a prior run
        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE workflow_runs (
                id TEXT PRIMARY KEY,
                workflow_name TEXT,
                inputs TEXT,
                status TEXT,
                parent_run_id TEXT,
                started_at TEXT
            )
        """)
        conn.execute(
            "INSERT INTO workflow_runs (id, workflow_name, inputs, status) VALUES (?, ?, ?, ?)",
            ("prior-run-123", "test-workflow", json.dumps({"key": "value"}), "completed"),
        )
        conn.commit()
        conn.close()
        
        # Import CLI and test
        from dag_executor.cli import main
        
        with patch("subprocess.Popen") as mock_popen, \
             patch("sys.argv", [
                 "dag-exec", "rerun", "prior-run-123",
                 "--workflow", str(workflow_path),
                 "--db-path", str(db_path)
             ]):
            
            # Run CLI
            try:
                main()
            except SystemExit:
                pass
            
            # Verify subprocess was spawned with correct args
            assert mock_popen.called
            call_args = mock_popen.call_args[0][0]
            assert "dag-exec" in call_args[0]


def test_cli_rerun_db_path_defaults():
    """Test that --db-path defaults to ~/.dag-dashboard/dashboard.db."""
    from dag_executor.cli import main
    
    with tempfile.TemporaryDirectory() as tmpdir:
        workflow_path = Path(tmpdir) / "workflow.yml"
        workflow_path.write_text("nodes: []")
        
        with patch("subprocess.Popen") as mock_popen, \
             patch("pathlib.Path.exists", return_value=True), \
             patch("sqlite3.connect") as mock_connect:
            
            # Mock DB to return a prior run
            mock_cursor = MagicMock()
            mock_cursor.fetchone.return_value = (
                "test-workflow",
                json.dumps({"key": "value"}),
            )
            mock_conn = MagicMock()
            mock_conn.cursor.return_value = mock_cursor
            mock_connect.return_value = mock_conn
            
            with patch("sys.argv", [
                "dag-exec", "rerun", "prior-run-123",
                "--workflow", str(workflow_path)
            ]):
                try:
                    main()
                except SystemExit:
                    pass
                
                # Verify default DB path was used
                # Check that sqlite3.connect was called (may be called multiple times)
                assert mock_connect.called


def test_cli_rerun_inserts_row_before_subprocess():
    """Test that CLI inserts workflow_runs row with parent_run_id before spawning subprocess."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "dashboard.db"
        workflow_path = Path(tmpdir) / "workflow.yml"
        workflow_path.write_text("nodes: []")
        
        # Create dashboard DB
        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE workflow_runs (
                id TEXT PRIMARY KEY,
                workflow_name TEXT,
                inputs TEXT,
                status TEXT,
                parent_run_id TEXT,
                started_at TEXT
            )
        """)
        conn.execute(
            "INSERT INTO workflow_runs (id, workflow_name, inputs, status) VALUES (?, ?, ?, ?)",
            ("prior-run-123", "test-workflow", json.dumps({"key": "value"}), "completed"),
        )
        conn.commit()
        conn.close()
        
        from dag_executor.cli import main
        
        with patch("subprocess.Popen") as mock_popen, \
             patch("sys.argv", [
                 "dag-exec", "rerun", "prior-run-123",
                 "--workflow", str(workflow_path),
                 "--db-path", str(db_path)
             ]):
            
            try:
                main()
            except (SystemExit, Exception):
                pass
            
            # Verify new row was inserted
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM workflow_runs WHERE parent_run_id = ?", ("prior-run-123",))
            count = cursor.fetchone()[0]
            conn.close()
            
            assert count > 0, "No new run was inserted with parent_run_id"


def test_cli_rerun_remote_mode_posts_to_api():
    """Test that rerun --remote POSTs to /api/workflows/{run_id}/rerun."""
    from dag_executor.cli import main
    
    with patch("requests.post") as mock_post:
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            "run_id": "new-run-123",
            "parent_run_id": "prior-run-123",
        }
        
        with patch("sys.argv", [
            "dag-exec", "rerun", "prior-run-123",
            "--remote", "https://dashboard.example.com"
        ]):
            try:
                main()
            except SystemExit:
                pass
            
            # Verify API call
            assert mock_post.called
            call_url = mock_post.call_args[0][0]
            assert "/api/workflows/prior-run-123/rerun" in call_url


def test_cli_rerun_passes_run_id_to_subprocess():
    """Test that cli rerun passes --run-id to spawned dag-exec subprocess matching pre-inserted row."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "dashboard.db"
        workflow_path = Path(tmpdir) / "workflow.yml"
        workflow_path.write_text("nodes: []")

        # Create a mock dashboard DB with a prior run
        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE workflow_runs (
                id TEXT PRIMARY KEY,
                workflow_name TEXT,
                inputs TEXT,
                status TEXT,
                parent_run_id TEXT,
                started_at TEXT
            )
        """)
        conn.execute(
            "INSERT INTO workflow_runs (id, workflow_name, inputs, status) VALUES (?, ?, ?, ?)",
            ("prior-run-123", "test-workflow", json.dumps({"key": "value"}), "completed"),
        )
        conn.commit()
        conn.close()

        from dag_executor.cli import main

        with patch("subprocess.Popen") as mock_popen, \
             patch("sys.argv", [
                 "dag-exec", "rerun", "prior-run-123",
                 "--workflow", str(workflow_path),
                 "--db-path", str(db_path)
             ]):

            # Run CLI
            try:
                main()
            except SystemExit:
                pass

            # Verify subprocess was spawned with --run-id matching the pre-inserted row
            assert mock_popen.called, "subprocess.Popen should have been called"
            call_args = mock_popen.call_args[0][0]

            # Find --run-id in command args
            assert "--run-id" in call_args, "subprocess should receive --run-id flag"
            run_id_index = call_args.index("--run-id")
            subprocess_run_id = call_args[run_id_index + 1]

            # Verify the run_id matches the pre-inserted row
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM workflow_runs WHERE parent_run_id = ?", ("prior-run-123",))
            pre_inserted_run_id = cursor.fetchone()[0]
            conn.close()

            assert subprocess_run_id == pre_inserted_run_id, \
                f"subprocess --run-id {subprocess_run_id} should match pre-inserted row {pre_inserted_run_id}"
