"""Tests for artifacts CLI command."""
import json
import pytest
from unittest.mock import Mock, patch
import sqlite3
from pathlib import Path


def test_cli_artifacts_argparse_defaults():
    """Test artifacts command parses with defaults."""
    from dag_executor.cli import main

    with patch('dag_executor.cli.run_artifacts') as mock_artifacts:
        main(['artifacts', 'run_123'])
        mock_artifacts.assert_called_once()
        # Verify it was called with argv=['run_123']
        call_args = mock_artifacts.call_args[0][0]
        assert call_args == ['run_123']


def _seed_artifacts_db(db_path: Path, run_id: str = "run_abc123") -> None:
    """Create minimal schema + seed artifacts data.
    
    Populates workflow_runs, node_executions, and artifacts tables
    with all 4 artifact types (pr, commit, branch, file).
    """
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE workflow_runs (
            id TEXT PRIMARY KEY,
            workflow_name TEXT NOT NULL,
            status TEXT NOT NULL,
            started_at TEXT NOT NULL
        );
        CREATE TABLE node_executions (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            node_name TEXT NOT NULL,
            status TEXT NOT NULL,
            started_at TEXT NOT NULL
        );
        CREATE TABLE artifacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            execution_id TEXT NOT NULL,
            name TEXT NOT NULL,
            artifact_type TEXT NOT NULL,
            path TEXT,
            content TEXT,
            created_at TEXT NOT NULL,
            url TEXT,
            FOREIGN KEY (execution_id) REFERENCES node_executions(id)
        );
        """
    )
    # Insert workflow run
    conn.execute(
        "INSERT INTO workflow_runs (id, workflow_name, status, started_at) VALUES (?, ?, ?, ?)",
        (run_id, "test_workflow", "completed", "2026-04-22T10:00:00Z"),
    )
    # Insert node executions
    conn.execute(
        "INSERT INTO node_executions (id, run_id, node_name, status, started_at) VALUES (?, ?, ?, ?, ?)",
        ("exec_1", run_id, "deploy_node", "completed", "2026-04-22T10:01:00Z"),
    )
    conn.execute(
        "INSERT INTO node_executions (id, run_id, node_name, status, started_at) VALUES (?, ?, ?, ?, ?)",
        ("exec_2", run_id, "test_node", "completed", "2026-04-22T10:02:00Z"),
    )
    # Insert artifacts - all 4 types
    conn.execute(
        "INSERT INTO artifacts (execution_id, name, artifact_type, created_at, url) VALUES (?, ?, ?, ?, ?)",
        ("exec_1", "PR #42", "pr", "2026-04-22T10:03:00Z", "https://github.com/repo/pull/42"),
    )
    conn.execute(
        "INSERT INTO artifacts (execution_id, name, artifact_type, created_at, url) VALUES (?, ?, ?, ?, ?)",
        ("exec_1", "abc123", "commit", "2026-04-22T10:04:00Z", "https://github.com/repo/commit/abc123"),
    )
    conn.execute(
        "INSERT INTO artifacts (execution_id, name, artifact_type, created_at, url) VALUES (?, ?, ?, ?, ?)",
        ("exec_2", "feature/test", "branch", "2026-04-22T10:05:00Z", "https://github.com/repo/tree/feature/test"),
    )
    conn.execute(
        "INSERT INTO artifacts (execution_id, name, artifact_type, path, created_at) VALUES (?, ?, ?, ?, ?)",
        ("exec_2", "output.txt", "file", "/tmp/output.txt", "2026-04-22T10:06:00Z"),
    )
    conn.commit()
    conn.close()


def test_cli_artifacts_local_mode_pretty(tmp_path, capsys):
    """Test local mode queries DB and prints tabular output."""
    from dag_executor.cli import main

    db_path = tmp_path / "test.db"
    _seed_artifacts_db(db_path, run_id="run_abc123")

    main(['artifacts', 'run_abc123', '--db', str(db_path)])

    captured = capsys.readouterr()
    # Verify all 4 artifact names appear in output
    assert "PR #42" in captured.out
    assert "abc123" in captured.out
    assert "feature/test" in captured.out
    assert "output.txt" in captured.out
    # Verify node names appear
    assert "deploy_node" in captured.out or "test_node" in captured.out


def test_cli_artifacts_local_mode_json(tmp_path, capsys):
    """Test --json emits valid JSON with all artifact rows."""
    from dag_executor.cli import main

    db_path = tmp_path / "test.db"
    _seed_artifacts_db(db_path, run_id="run_test")

    main(['artifacts', 'run_test', '--db', str(db_path), '--json'])

    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert "artifacts" in data
    assert len(data["artifacts"]) == 4
    # Verify types
    types = {a["artifact_type"] for a in data["artifacts"]}
    assert types == {"pr", "commit", "branch", "file"}


def test_cli_artifacts_type_filter_pr(tmp_path, capsys):
    """Test --type pr filters to only PR artifacts."""
    from dag_executor.cli import main

    db_path = tmp_path / "test.db"
    _seed_artifacts_db(db_path, run_id="run_filter")

    main(['artifacts', 'run_filter', '--db', str(db_path), '--type', 'pr'])

    captured = capsys.readouterr()
    assert "PR #42" in captured.out
    # Should NOT contain other types
    assert "abc123" not in captured.out
    assert "feature/test" not in captured.out
    assert "output.txt" not in captured.out


def test_cli_artifacts_type_filter_invalid():
    """Test --type bogus exits with code 2 (argparse error)."""
    from dag_executor.cli import main

    with pytest.raises(SystemExit) as exc_info:
        main(['artifacts', 'run_123', '--type', 'bogus'])
    
    assert exc_info.value.code == 2


def test_cli_artifacts_empty_state(tmp_path, capsys):
    """Test zero artifacts prints message to stderr, exits 0."""
    from dag_executor.cli import main

    db_path = tmp_path / "test.db"
    # Create schema but no artifacts
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE workflow_runs (
            id TEXT PRIMARY KEY,
            workflow_name TEXT NOT NULL,
            status TEXT NOT NULL,
            started_at TEXT NOT NULL
        );
        CREATE TABLE node_executions (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            node_name TEXT NOT NULL,
            status TEXT NOT NULL,
            started_at TEXT NOT NULL
        );
        CREATE TABLE artifacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            execution_id TEXT NOT NULL,
            name TEXT NOT NULL,
            artifact_type TEXT NOT NULL,
            path TEXT,
            content TEXT,
            created_at TEXT NOT NULL,
            url TEXT
        );
        """
    )
    conn.execute(
        "INSERT INTO workflow_runs (id, workflow_name, status, started_at) VALUES (?, ?, ?, ?)",
        ("run_empty", "test_workflow", "completed", "2026-04-22T10:00:00Z"),
    )
    conn.execute(
        "INSERT INTO node_executions (id, run_id, node_name, status, started_at) VALUES (?, ?, ?, ?, ?)",
        ("exec_1", "run_empty", "node1", "completed", "2026-04-22T10:01:00Z"),
    )
    conn.commit()
    conn.close()

    with pytest.raises(SystemExit) as exc_info:
        main(['artifacts', 'run_empty', '--db', str(db_path)])

    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert "No artifacts" in captured.err or "No artifacts" in captured.out


def test_cli_artifacts_run_not_found(tmp_path, capsys):
    """Test unknown run_id prints error to stderr, exits 1."""
    from dag_executor.cli import main

    db_path = tmp_path / "test.db"
    # Create empty schema
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE workflow_runs (
            id TEXT PRIMARY KEY,
            workflow_name TEXT NOT NULL,
            status TEXT NOT NULL,
            started_at TEXT NOT NULL
        );
        CREATE TABLE node_executions (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            node_name TEXT NOT NULL,
            status TEXT NOT NULL,
            started_at TEXT NOT NULL
        );
        CREATE TABLE artifacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            execution_id TEXT NOT NULL,
            name TEXT NOT NULL,
            artifact_type TEXT NOT NULL,
            path TEXT,
            content TEXT,
            created_at TEXT NOT NULL,
            url TEXT
        );
        """
    )
    conn.commit()
    conn.close()

    with pytest.raises(SystemExit) as exc_info:
        main(['artifacts', 'run_nonexistent', '--db', str(db_path)])
    
    assert exc_info.value.code == 1


def test_cli_artifacts_remote_mode():
    """Test remote mode hits httpx.get with bearer header."""
    from dag_executor.cli import main
    
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "artifacts": [
            {"name": "PR #1", "artifact_type": "pr", "node_name": "deploy", "created_at": "2026-04-22T10:00:00Z", "url": "https://example.com/pr/1"}
        ]
    }
    
    with patch('httpx.get', return_value=mock_response) as mock_get:
        with patch('sys.stdout', new_callable=lambda: Mock(write=lambda x: None)):
            result = main(['artifacts', 'run_001', '--remote', 'http://localhost:8100', '--token', 'SECRET'])
    
    mock_get.assert_called_once()
    call_kwargs = mock_get.call_args.kwargs
    assert call_kwargs['headers']['Authorization'] == 'Bearer SECRET'
    assert 'http://localhost:8100/api/workflows/run_001/artifacts' in mock_get.call_args.args[0]


def test_cli_artifacts_remote_mode_missing_token():
    """Test --remote without token or env var exits 2."""
    from dag_executor.cli import main

    with pytest.raises(SystemExit) as exc_info:
        main(['artifacts', 'run_123', '--remote', 'http://localhost:8100'])
    
    assert exc_info.value.code == 2


def test_cli_artifacts_db_not_found(capsys):
    """Test --db with nonexistent path exits 1."""
    from dag_executor.cli import main

    with pytest.raises(SystemExit) as exc_info:
        main(['artifacts', 'run_123', '--db', '/nonexistent/path.db'])
    
    assert exc_info.value.code == 1
