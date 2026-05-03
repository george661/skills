"""Simplified tests for OrchestratorManager."""
import asyncio
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock
from dag_dashboard.orchestrator_manager import OrchestratorManager
from dag_dashboard.database import init_db
from dag_dashboard.queries import insert_run, get_connection


@pytest.fixture
def db_with_runs(tmp_path: Path):
    """Create database with test runs."""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    
    from dag_dashboard.queries import insert_run
    for i in range(1, 4):
        insert_run(
            db_path=db_path,
            run_id=f"run-{i}",
            workflow_name="test-workflow",
            status="running",
            started_at="2026-05-03T12:00:00Z",
        )
    
    # Add conversation mappings
    conn = get_connection(db_path)
    cursor = conn.cursor()
    for i in range(1, 4):
        cursor.execute(
            "INSERT INTO conversations (id, created_at, origin) VALUES (?, ?, ?)",
            (f"conv-{i}", "2026-05-03T12:00:00Z", "test")
        )
        cursor.execute(
            "UPDATE workflow_runs SET conversation_id = ? WHERE id = ?",
            (f"conv-{i}", f"run-{i}")
        )
    conn.commit()
    conn.close()
    
    return db_path


@pytest.mark.asyncio
@patch('dag_dashboard.orchestrator_manager.OrchestratorRelay')
async def test_spawn_on_first_message(mock_relay_class, db_with_runs):
    """Test that route_message() triggers spawn."""
    db_path = db_with_runs
    loop = asyncio.get_running_loop()
    broadcaster = AsyncMock()
    
    # Mock relay instance with required attributes
    mock_relay = MagicMock()
    mock_relay.session_uuid = "test-session-uuid"
    mock_relay.start = MagicMock()
    mock_relay.send_message = MagicMock()
    mock_relay.is_alive = MagicMock(return_value=True)
    mock_relay_class.return_value = mock_relay
    
    manager = OrchestratorManager(
        db_path=db_path,
        broadcaster=broadcaster,
        model="claude-opus-4-7",
        max_concurrent=8,
        idle_ttl_seconds=1800,
        dashboard_port=8080,
    )
    manager.set_loop(loop)
    
    import time
    start_time = time.time()
    
    await manager.route_message(
        conversation_id="conv-1",
        run_id="run-1",
        message="Hello orchestrator",
    )
    
    elapsed = time.time() - start_time
    
    # Verify spawn happened quickly
    assert elapsed < 3.0
    # Verify relay was created and started
    mock_relay_class.assert_called_once()
    mock_relay.start.assert_called_once()
    mock_relay.send_message.assert_called_once_with("Hello orchestrator")


@pytest.mark.asyncio
@patch('dag_dashboard.orchestrator_manager.OrchestratorRelay')
async def test_reuses_existing_orchestrator_for_same_conversation(mock_relay_class, db_with_runs):
    """Test that second route_message with same conversation_id reuses relay."""
    db_path = db_with_runs
    loop = asyncio.get_running_loop()
    broadcaster = AsyncMock()
    
    mock_relay = MagicMock()
    mock_relay.session_uuid = "test-session-uuid"
    mock_relay.start = MagicMock()
    mock_relay.send_message = MagicMock()
    mock_relay.is_alive = MagicMock(return_value=True)
    mock_relay_class.return_value = mock_relay
    
    manager = OrchestratorManager(
        db_path=db_path,
        broadcaster=broadcaster,
        model="claude-opus-4-7",
        max_concurrent=8,
        idle_ttl_seconds=1800,
        dashboard_port=8080,
    )
    manager.set_loop(loop)
    
    # First message
    await manager.route_message("conv-1", "run-1", "First message")
    
    # Second message to same conversation
    await manager.route_message("conv-1", "run-1", "Second message")
    
    # Verify relay was created only once
    assert mock_relay_class.call_count == 1
    # But send_message was called twice
    assert mock_relay.send_message.call_count == 2


@pytest.mark.asyncio
@patch('dag_dashboard.orchestrator_manager.OrchestratorRelay')
async def test_lru_evicts_when_concurrency_cap_reached(mock_relay_class, db_with_runs):
    """Test LRU eviction when max_concurrent=2."""
    db_path = db_with_runs
    loop = asyncio.get_running_loop()
    broadcaster = AsyncMock()
    
    # Create separate mock relays
    relays = []
    for i in range(3):
        mock_relay = MagicMock()
        mock_relay.session_uuid = f"session-{i}"
        mock_relay.start = MagicMock()
        mock_relay.send_message = MagicMock()
        mock_relay.is_alive = MagicMock(return_value=True)
        mock_relay.stop = MagicMock()
        relays.append(mock_relay)
    
    mock_relay_class.side_effect = relays
    
    manager = OrchestratorManager(
        db_path=db_path,
        broadcaster=broadcaster,
        model="claude-opus-4-7",
        max_concurrent=2,  # Only 2 concurrent
        idle_ttl_seconds=1800,
        dashboard_port=8080,
    )
    manager.set_loop(loop)
    
    # Spawn 3 conversations
    await manager.route_message("conv-1", "run-1", "Message 1")
    await manager.route_message("conv-2", "run-2", "Message 2")
    await manager.route_message("conv-3", "run-3", "Message 3")
    
    # Verify first relay was stopped (LRU eviction)
    relays[0].stop.assert_called_once()
    
    # Verify orchestrator_sessions row still exists
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT COUNT(*) FROM orchestrator_sessions WHERE conversation_id = ?",
        ("conv-1",)
    )
    count = cursor.fetchone()[0]
    conn.close()
    assert count >= 1


@pytest.mark.asyncio
@patch('dag_dashboard.orchestrator_manager.OrchestratorRelay')
async def test_startup_does_not_prespawn(mock_relay_class, db_with_runs):
    """Test that __init__ does not spawn relays."""
    db_path = db_with_runs
    loop = asyncio.get_running_loop()
    broadcaster = AsyncMock()
    
    # Insert existing session
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO orchestrator_sessions (conversation_id, session_uuid, model, created_at, last_active, status) VALUES (?, ?, ?, ?, ?, ?)",
        ("conv-1", "session-existing", "claude-opus-4-7", "2026-05-03T12:00:00Z", "2026-05-03T12:00:00Z", "active")
    )
    conn.commit()
    conn.close()
    
    # Create manager
    manager = OrchestratorManager(
        db_path=db_path,
        broadcaster=broadcaster,
        model="claude-opus-4-7",
        max_concurrent=8,
        idle_ttl_seconds=1800,
        dashboard_port=8080,
    )
    manager.set_loop(loop)
    
    # Verify no relay was spawned during __init__ or set_loop
    mock_relay_class.assert_not_called()
