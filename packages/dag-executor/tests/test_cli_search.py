"""Tests for search CLI command."""
import json
import pytest
from unittest.mock import Mock, patch
import sqlite3
from pathlib import Path


def test_cli_search_argparse_defaults():
    """Test 14: search command parses with defaults."""
    from dag_executor.cli import main

    with patch('dag_executor.cli.run_search') as mock_search:
        main(['search', 'foo'])
        mock_search.assert_called_once()
        # Verify it was called with argv=['foo']
        call_args = mock_search.call_args[0][0]
        assert call_args == ['foo']


def test_cli_search_local_mode(tmp_path):
    """Test 15: local mode queries DB directly."""
    from dag_executor.cli import main
    from dag_executor.search_local import search_all
    
    # Create and seed a test DB
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE workflow_runs (
            id TEXT PRIMARY KEY,
            workflow_name TEXT NOT NULL,
            status TEXT NOT NULL,
            started_at TEXT NOT NULL
        )
    """)
    conn.execute(
        "INSERT INTO workflow_runs (id, workflow_name, status, started_at) VALUES (?, ?, ?, ?)",
        ("run_abc123", "deploy", "completed", "2026-04-22T10:00:00Z")
    )
    conn.commit()
    conn.close()
    
    # Run CLI in local mode
    with patch('sys.stdout', new_callable=lambda: Mock(write=lambda x: None)):
        result = main(['search', 'abc', '--db', str(db_path)])
        # Just verify it doesn't crash


def test_cli_search_remote_mode():
    """Test 16: remote mode hits httpx.get with bearer header."""
    from dag_executor.cli import main
    
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "query": "test",
        "total": 1,
        "results": [{"kind": "run", "run_id": "run_001", "snippet": "test"}]
    }
    
    with patch('httpx.get', return_value=mock_response) as mock_get:
        with patch('sys.stdout', new_callable=lambda: Mock(write=lambda x: None)):
            result = main(['search', 'test', '--remote', 'http://localhost:8100', '--token', 'SECRET'])
    
    mock_get.assert_called_once()
    call_kwargs = mock_get.call_args.kwargs
    assert call_kwargs['headers']['Authorization'] == 'Bearer SECRET'
    assert 'http://localhost:8100/api/search' in mock_get.call_args.args[0]


def test_cli_search_json_output(tmp_path):
    """Test 17: --json emits valid JSON."""
    from dag_executor.cli import main
    import io
    import sys
    
    # Create test DB
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE workflow_runs (
            id TEXT PRIMARY KEY,
            workflow_name TEXT NOT NULL,
            status TEXT NOT NULL,
            started_at TEXT NOT NULL
        )
    """)
    conn.execute(
        "INSERT INTO workflow_runs (id, workflow_name, status, started_at) VALUES (?, ?, ?, ?)",
        ("run_test", "deploy", "completed", "2026-04-22T10:00:00Z")
    )
    conn.commit()
    conn.close()
    
    # Capture stdout
    captured = io.StringIO()
    with patch('sys.stdout', captured):
        main(['search', 'test', '--db', str(db_path), '--json'])

    output = captured.getvalue()
    data = json.loads(output)  # Should not raise
    assert 'total' in data or isinstance(data, list)


def test_cli_search_token_sources():
    """Test 18: --token wins over env var."""
    from dag_executor.cli import main
    import os
    
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"query": "test", "total": 0, "results": []}
    
    # Test --token flag wins
    with patch('httpx.get', return_value=mock_response) as mock_get:
        with patch('sys.stdout', new_callable=lambda: Mock(write=lambda x: None)):
            with patch.dict(os.environ, {'DAG_EXEC_SEARCH_TOKEN': 'env_token'}):
                main(['search', 'test', '--remote', 'http://localhost:8100', '--token', 'flag_token'])
    
    call_kwargs = mock_get.call_args.kwargs
    assert call_kwargs['headers']['Authorization'] == 'Bearer flag_token'
