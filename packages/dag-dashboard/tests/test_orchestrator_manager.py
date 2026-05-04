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


# ---------------------------------------------------------------------------
# GW-5497: dead-relay detection + respawn, session status transitions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch('dag_dashboard.orchestrator_manager.OrchestratorRelay')
async def test_dead_relay_is_evicted_and_respawned(mock_relay_class, db_with_runs):
    """If the cached relay's subprocess has exited, route_message must evict
    it and spawn a fresh relay before sending. Without this, the second turn
    would queue into a zombie whose stdin_writer errors silently.
    """
    db_path = db_with_runs
    loop = asyncio.get_running_loop()
    broadcaster = AsyncMock()

    # First relay starts alive; after the first message we flip is_alive to
    # False to simulate a subprocess crash between turns.
    first_relay = MagicMock()
    first_relay.session_uuid = "session-1"
    first_relay.start = MagicMock()
    first_relay.send_message = MagicMock()
    first_relay.is_alive = MagicMock(return_value=True)
    first_relay.stop = MagicMock()

    second_relay = MagicMock()
    second_relay.session_uuid = "session-1"  # --resume reuses the UUID
    second_relay.start = MagicMock()
    second_relay.send_message = MagicMock()
    second_relay.is_alive = MagicMock(return_value=True)
    second_relay.stop = MagicMock()

    mock_relay_class.side_effect = [first_relay, second_relay]

    manager = OrchestratorManager(
        db_path=db_path, broadcaster=broadcaster, model=None,
        max_concurrent=8, idle_ttl_seconds=1800, dashboard_port=8080,
    )
    manager.set_loop(loop)

    await manager.route_message("conv-1", "run-1", "turn one")
    first_relay.send_message.assert_called_once_with("turn one")

    # Subprocess dies between turns.
    first_relay.is_alive = MagicMock(return_value=False)

    await manager.route_message("conv-1", "run-1", "turn two")

    # First relay was stopped (eviction), second relay was spawned and
    # received the message.
    first_relay.stop.assert_called_once()
    assert mock_relay_class.call_count == 2
    second_relay.send_message.assert_called_once_with("turn two")

    # Persisted status reflects the "exited" transition on the dead relay.
    row = get_connection(db_path).execute(
        "SELECT status FROM orchestrator_sessions WHERE conversation_id = ?",
        ("conv-1",),
    ).fetchone()
    assert row is not None
    # Last write wins; the respawn immediately upserts back to "alive".
    assert row[0] == "alive"


@pytest.mark.asyncio
@patch('dag_dashboard.orchestrator_manager.OrchestratorRelay')
async def test_sweeper_evicts_dead_relay_and_marks_exited(mock_relay_class, db_with_runs):
    """The TTL sweeper must treat a dead subprocess as evictable regardless
    of idle time, and mark orchestrator_sessions.status='exited'.
    """
    db_path = db_with_runs
    loop = asyncio.get_running_loop()
    broadcaster = AsyncMock()

    mock_relay = MagicMock()
    mock_relay.session_uuid = "session-dead"
    mock_relay.start = MagicMock()
    mock_relay.send_message = MagicMock()
    # Dead from the start of the sweep
    mock_relay.is_alive = MagicMock(return_value=False)
    mock_relay.get_idle_seconds = MagicMock(return_value=5.0)  # not idle
    mock_relay.stop = MagicMock()
    mock_relay_class.return_value = mock_relay

    manager = OrchestratorManager(
        db_path=db_path, broadcaster=broadcaster, model=None,
        max_concurrent=8, idle_ttl_seconds=1800, dashboard_port=8080,
    )
    manager.set_loop(loop)

    # Seed a relay into the pool by routing a message (is_alive check
    # happens BEFORE the send, but first-route sees no existing relay so
    # it still spawns).
    await manager.route_message("conv-1", "run-1", "seed")
    assert "conv-1" in manager.relays

    # Invoke the sweeper body directly — the background task sleeps 60s so
    # we short-circuit by calling the eviction logic as the sweeper would.
    async with manager.lock:
        to_evict_dead = [
            cid for cid, r in manager.relays.items() if not r.is_alive()
        ]
        for cid in to_evict_dead:
            manager._evict_locked(cid, new_status="exited")

    assert "conv-1" not in manager.relays
    mock_relay.stop.assert_called_once()

    row = get_connection(db_path).execute(
        "SELECT status FROM orchestrator_sessions WHERE conversation_id = ?",
        ("conv-1",),
    ).fetchone()
    assert row is not None
    assert row[0] == "exited"


@pytest.mark.asyncio
@patch('dag_dashboard.orchestrator_manager.OrchestratorRelay')
async def test_lru_eviction_marks_session_as_lru_evicted(mock_relay_class, db_with_runs):
    """When a relay is evicted to make room under the concurrency cap, its
    persisted status must transition to 'lru_evicted' — not stay 'alive'.
    """
    db_path = db_with_runs
    loop = asyncio.get_running_loop()
    broadcaster = AsyncMock()

    relays = []
    for i in range(3):
        m = MagicMock()
        m.session_uuid = f"session-{i}"
        m.start = MagicMock()
        m.send_message = MagicMock()
        m.is_alive = MagicMock(return_value=True)
        m.stop = MagicMock()
        relays.append(m)
    mock_relay_class.side_effect = relays

    manager = OrchestratorManager(
        db_path=db_path, broadcaster=broadcaster, model=None,
        max_concurrent=2, idle_ttl_seconds=1800, dashboard_port=8080,
    )
    manager.set_loop(loop)

    await manager.route_message("conv-1", "run-1", "a")
    await manager.route_message("conv-2", "run-2", "b")
    await manager.route_message("conv-3", "run-3", "c")

    row = get_connection(db_path).execute(
        "SELECT status FROM orchestrator_sessions WHERE conversation_id = ?",
        ("conv-1",),
    ).fetchone()
    assert row is not None
    assert row[0] == "lru_evicted"


@pytest.mark.asyncio
@patch('dag_dashboard.orchestrator_manager.OrchestratorRelay')
async def test_stop_all_marks_sessions_stopped(mock_relay_class, db_with_runs):
    """Shutdown must mark every persisted session as 'stopped' so debugging
    can tell a clean shutdown from a crash.
    """
    db_path = db_with_runs
    loop = asyncio.get_running_loop()
    broadcaster = AsyncMock()

    mock_relay = MagicMock()
    mock_relay.session_uuid = "session-a"
    mock_relay.start = MagicMock()
    mock_relay.send_message = MagicMock()
    mock_relay.is_alive = MagicMock(return_value=True)
    mock_relay.stop = MagicMock()
    mock_relay_class.return_value = mock_relay

    manager = OrchestratorManager(
        db_path=db_path, broadcaster=broadcaster, model=None,
        max_concurrent=8, idle_ttl_seconds=1800, dashboard_port=8080,
    )
    manager.set_loop(loop)
    await manager.route_message("conv-1", "run-1", "hi")

    await manager.stop_all()

    assert manager.relays == {}
    row = get_connection(db_path).execute(
        "SELECT status FROM orchestrator_sessions WHERE conversation_id = ?",
        ("conv-1",),
    ).fetchone()
    assert row is not None
    assert row[0] == "stopped"
