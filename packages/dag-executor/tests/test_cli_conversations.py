"""Golden-output tests for conversation CLI subcommands.

These tests verify the full CLI behavior including:
- dag-exec conversation <id> (list messages)
- dag-exec conversation append <id> <role> <content> (positional form)
- dag-exec run --conversation <id> (session reuse wiring)
"""
import json
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from dag_executor.conversation_cli import run_conversation
from dag_executor.conversations import append_message, mint_session, start_conversation


def test_conversation_list_prints_chronological_log(tmp_path: Path, capsys) -> None:
    """Verify 'dag-exec conversation <id>' prints messages in chronological order."""
    # Setup test database
    from dag_dashboard.database import init_db
    db_path = tmp_path / "test.db"
    init_db(db_path)
    
    # Create conversation and session
    conversation = start_conversation(db_path, origin="cli")
    session = mint_session(db_path, conversation.id)
    
    # Append two messages
    msg1 = append_message(
        db_path=db_path,
        role="user",
        content="First message",
        conversation_id=conversation.id,
        session_id=session.id,
        run_id=None,
        execution_id=None,
    )
    
    msg2 = append_message(
        db_path=db_path,
        role="assistant",
        content="Second message",
        conversation_id=conversation.id,
        session_id=session.id,
        run_id=None,
        execution_id=None,
    )
    
    # Run list command
    argv = [conversation.id, '--db', str(db_path)]
    
    with pytest.raises(SystemExit) as exc_info:
        run_conversation(argv)
    
    assert exc_info.value.code == 0, "Expected exit code 0"
    
    # Verify stdout contains both messages in order
    captured = capsys.readouterr()
    output = captured.out
    
    # Check messages appear in chronological order
    assert "user: First message" in output
    assert "assistant: Second message" in output
    
    # Verify order (user before assistant)
    user_pos = output.index("user: First message")
    assistant_pos = output.index("assistant: Second message")
    assert user_pos < assistant_pos, "Messages not in chronological order"


def test_conversation_list_json_output(tmp_path: Path, capsys) -> None:
    """Verify 'dag-exec conversation <id> --json' outputs structured JSON."""
    from dag_dashboard.database import init_db
    db_path = tmp_path / "test.db"
    init_db(db_path)
    
    # Create conversation and session
    conversation = start_conversation(db_path, origin="cli")
    session = mint_session(db_path, conversation.id)
    
    # Append message
    msg = append_message(
        db_path=db_path,
        role="user",
        content="Test content",
        conversation_id=conversation.id,
        session_id=session.id,
        run_id=None,
        execution_id=None,
    )
    
    # Run list command with --json
    argv = [conversation.id, '--db', str(db_path), '--json']
    
    with pytest.raises(SystemExit) as exc_info:
        run_conversation(argv)
    
    assert exc_info.value.code == 0
    
    # Verify JSON output
    captured = capsys.readouterr()
    messages = json.loads(captured.out)
    
    assert isinstance(messages, list)
    assert len(messages) == 1
    
    msg_data = messages[0]
    assert msg_data['role'] == 'user'
    assert msg_data['content'] == 'Test content'
    assert msg_data['conversation_id'] == conversation.id
    assert msg_data['session_id'] == session.id
    assert 'created_at' in msg_data
    assert 'id' in msg_data


def test_conversation_list_missing_conversation_exits_nonzero(tmp_path: Path, capsys) -> None:
    """Verify listing unknown conversation prints error and exits 1."""
    from dag_dashboard.database import init_db
    db_path = tmp_path / "test.db"
    init_db(db_path)
    
    argv = ['nonexistent-conv-id', '--db', str(db_path)]
    
    with pytest.raises(SystemExit) as exc_info:
        run_conversation(argv)
    
    assert exc_info.value.code == 1, "Expected exit code 1 for missing conversation"
    
    # Verify error message
    captured = capsys.readouterr()
    assert "not found" in captured.err.lower() or "no messages" in captured.err.lower()


def test_conversation_append_positional_form(tmp_path: Path) -> None:
    """Verify positional append form: dag-exec conversation append <id> <role> <content>."""
    from dag_dashboard.database import init_db
    db_path = tmp_path / "test.db"
    init_db(db_path)
    
    # Create conversation and session
    conversation = start_conversation(db_path, origin="cli")
    session = mint_session(db_path, conversation.id)
    
    # Run positional append command
    argv = [
        'append',
        conversation.id,
        'user',
        'Hello from positional form',
        '--db', str(db_path),
        '--session-id', session.id,
    ]
    
    with pytest.raises(SystemExit) as exc_info:
        run_conversation(argv)
    
    assert exc_info.value.code == 0
    
    # Verify message was inserted
    conn = sqlite3.connect(db_path)
    cursor = conn.execute(
        "SELECT conversation_id, role, content FROM chat_messages WHERE conversation_id = ?",
        (conversation.id,)
    )
    rows = cursor.fetchall()
    conn.close()
    
    assert len(rows) == 1
    conv_id, role, content = rows[0]
    assert conv_id == conversation.id
    assert role == 'user'
    assert content == 'Hello from positional form'


def test_run_with_conversation_flag_reuses_active_session(tmp_path: Path) -> None:
    """Verify 'dag-exec run --conversation <id>' passes conversation_id to execute_workflow."""
    from dag_dashboard.database import init_db
    from dag_executor import cli, WorkflowResult, WorkflowStatus
    from dag_executor.schema import WorkflowDef, WorkflowConfig, NodeDef

    db_path = tmp_path / "test.db"
    init_db(db_path)

    # Create conversation with active session
    conversation = start_conversation(db_path, origin="cli")
    session = mint_session(db_path, conversation.id)

    # Create a temporary workflow file
    workflow_path = tmp_path / "workflow.yaml"
    workflow_path.write_text("name: test\nconfig:\n  checkpoint_prefix: test\nnodes:\n  - id: test\n    name: test\n    type: bash\n    script: echo test")

    # Mock load_workflow to return a minimal WorkflowDef
    mock_workflow = WorkflowDef(
        name="test",
        config=WorkflowConfig(checkpoint_prefix="test"),
        nodes=[NodeDef(id="test", name="test", type="bash", script="echo test")]
    )

    # Mock execute_workflow to return a minimal result for post-execution summary
    mock_result = WorkflowResult(
        status=WorkflowStatus.COMPLETED,
        node_results={},
        run_id="test-run-id"
    )

    with patch.object(cli, 'load_workflow', return_value=mock_workflow) as mock_load, \
         patch.object(cli, 'execute_workflow', return_value=mock_result) as mock_execute:

        # Call cli.main() with argv (note: no 'run' prefix - dag-exec <workflow> is the syntax)
        argv = [
            str(workflow_path),
            '--conversation', conversation.id,
            '--db', str(db_path),
        ]

        with patch('sys.exit'):  # Prevent test from exiting
            cli.main(argv)

        # Assert execute_workflow was called with conversation_id and db_path
        assert mock_execute.called, "execute_workflow should have been called"
        call_kwargs = mock_execute.call_args.kwargs
        assert call_kwargs["conversation_id"] == conversation.id, \
            f"Expected conversation_id={conversation.id}, got {call_kwargs.get('conversation_id')}"
        assert str(call_kwargs["db_path"]) == str(db_path), \
            f"Expected db_path={db_path}, got {call_kwargs.get('db_path')}"


def test_run_without_conversation_flag_mints_new_conversation(tmp_path: Path) -> None:
    """Verify dag-exec run without --conversation flag works (backward compat)."""
    from dag_executor import cli, WorkflowResult, WorkflowStatus
    from dag_executor.schema import WorkflowDef, WorkflowConfig, NodeDef

    # Create a temporary workflow file
    workflow_path = tmp_path / "workflow.yaml"
    workflow_path.write_text("name: test\nconfig:\n  checkpoint_prefix: test\nnodes:\n  - id: test\n    name: test\n    type: bash\n    script: echo test")

    # Mock load_workflow to return a minimal WorkflowDef
    mock_workflow = WorkflowDef(
        name="test",
        config=WorkflowConfig(checkpoint_prefix="test"),
        nodes=[NodeDef(id="test", name="test", type="bash", script="echo test")]
    )

    # Mock execute_workflow to return a minimal result
    mock_result = WorkflowResult(
        status=WorkflowStatus.COMPLETED,
        node_results={},
        run_id="test-run-id"
    )

    with patch.object(cli, 'load_workflow', return_value=mock_workflow) as mock_load, \
         patch.object(cli, 'execute_workflow', return_value=mock_result) as mock_execute:

        # Call cli.main() without --conversation flag (note: no 'run' prefix)
        argv = [str(workflow_path)]

        with patch('sys.exit'):  # Prevent test from exiting
            cli.main(argv)

        # Assert execute_workflow was called with conversation_id=None and db_path=None
        assert mock_execute.called, "execute_workflow should have been called"
        call_kwargs = mock_execute.call_args.kwargs
        assert call_kwargs["conversation_id"] is None, \
            f"Expected conversation_id=None for backward compat, got {call_kwargs.get('conversation_id')}"
        assert call_kwargs["db_path"] is None, \
            f"Expected db_path=None for backward compat, got {call_kwargs.get('db_path')}"
