"""GW-5497: trigger endpoint must create a conversation and wire it to the spawned executor.

Without this wiring, `workflow_runs.conversation_id` is NULL for every run triggered
from the dashboard, which makes the GW-5492 long-lived orchestrator unreachable
(chat_routes.py skips `orchestrator_manager.route_message` when
`get_conversation_id_from_run` returns None).
"""
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from dag_dashboard.config import Settings
from dag_dashboard.database import init_db
from dag_dashboard.queries import get_conversation_row, get_run
from dag_dashboard.server import create_app


@pytest.fixture
def test_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "dashboard.db"
    init_db(db_path)
    return db_path


@pytest.fixture
def events_dir(tmp_path: Path) -> Path:
    events = tmp_path / "dag-events"
    events.mkdir(exist_ok=True)
    return events


@pytest.fixture
def workflows_dir(tmp_path: Path) -> Path:
    workflows = tmp_path / "workflows"
    workflows.mkdir(exist_ok=True)
    (workflows / "test-workflow.yaml").write_text(
        "name: test-workflow\n"
        "config:\n"
        "  checkpoint_prefix: test\n"
        "inputs:\n"
        "  issue_key:\n"
        "    type: string\n"
        "    required: true\n"
        "nodes:\n"
        "  - id: test-node\n"
        "    name: Test Node\n"
        "    type: command\n"
        "    command: echo test\n"
    )
    return workflows


@pytest.fixture
def client(tmp_path: Path, test_db: Path, events_dir: Path, workflows_dir: Path) -> TestClient:
    settings = Settings(trigger_enabled=True, workflows_dir=str(workflows_dir))
    app = create_app(tmp_path, events_dir=events_dir, settings=settings)
    return TestClient(app, raise_server_exceptions=True)


def _trigger(client: TestClient, *, conversation_id: str | None = None) -> str:
    payload = {
        "workflow": "test-workflow",
        "inputs": {"issue_key": "TEST-1"},
        "source": "test",
    }
    if conversation_id is not None:
        payload["conversation_id"] = conversation_id
    response = client.post("/api/trigger", json=payload)
    assert response.status_code == 200, response.text
    return response.json()["run_id"]


def test_trigger_creates_conversation_row(client: TestClient, test_db: Path) -> None:
    """POST /api/trigger must create a new `conversations` row when none is supplied."""
    with patch(
        "dag_dashboard.trigger.asyncio.create_subprocess_exec", new_callable=AsyncMock
    ) as mock_subprocess:
        mock_subprocess.return_value = AsyncMock(pid=12345)
        run_id = _trigger(client)

    run = get_run(test_db, run_id)
    assert run is not None
    conv_id = run["conversation_id"]
    assert conv_id, "workflow_runs.conversation_id must not be NULL after trigger"

    conv = get_conversation_row(test_db, conv_id)
    assert conv is not None, "conversations row should exist"
    assert conv["origin"] == "dashboard"
    assert conv["closed_at"] is None


def test_trigger_response_includes_conversation_id(client: TestClient) -> None:
    """Trigger response should surface the conversation_id so clients can display it."""
    with patch(
        "dag_dashboard.trigger.asyncio.create_subprocess_exec", new_callable=AsyncMock
    ) as mock_subprocess:
        mock_subprocess.return_value = AsyncMock(pid=12345)
        response = client.post(
            "/api/trigger",
            json={
                "workflow": "test-workflow",
                "inputs": {"issue_key": "TEST-1"},
                "source": "test",
            },
        )
    assert response.status_code == 200
    body = response.json()
    assert "conversation_id" in body
    assert isinstance(body["conversation_id"], str) and body["conversation_id"]


def test_trigger_spawns_executor_with_conversation_and_db_flags(
    client: TestClient, test_db: Path
) -> None:
    """The spawned dag-exec must receive --conversation <id> and --db <path>.

    Without these flags, `execute_workflow` is called with conversation_id=None
    and prompt runners skip all session-continuity logic.
    """
    with patch(
        "dag_dashboard.trigger.asyncio.create_subprocess_exec", new_callable=AsyncMock
    ) as mock_subprocess:
        mock_subprocess.return_value = AsyncMock(pid=12345)
        run_id = _trigger(client)

    args = list(mock_subprocess.call_args.args)
    assert "--conversation" in args, f"--conversation missing from argv: {args}"
    conv_idx = args.index("--conversation")
    spawned_conv_id = args[conv_idx + 1]

    run = get_run(test_db, run_id)
    assert run is not None
    assert spawned_conv_id == run["conversation_id"], (
        "Spawned --conversation id must match the id persisted on workflow_runs"
    )

    assert "--db" in args, f"--db missing from argv: {args}"
    db_idx = args.index("--db")
    assert args[db_idx + 1] == str(test_db)


def test_trigger_accepts_explicit_conversation_id_for_continuation(
    client: TestClient, test_db: Path
) -> None:
    """When a client passes conversation_id, two runs in that conversation share the id.

    This is the hook future UI will use to continue an existing conversation across
    multiple runs (the infrastructure for this already exists in the executor via
    GW-5305, just not on the trigger path).
    """
    with patch(
        "dag_dashboard.trigger.asyncio.create_subprocess_exec", new_callable=AsyncMock
    ) as mock_subprocess:
        mock_subprocess.return_value = AsyncMock(pid=12345)
        run_id_1 = _trigger(client)
        conv_id = get_run(test_db, run_id_1)["conversation_id"]

        # Second trigger reusing the same conversation id
        run_id_2 = _trigger(client, conversation_id=conv_id)

    assert get_run(test_db, run_id_2)["conversation_id"] == conv_id, (
        "Explicit conversation_id on second trigger must be reused, not replaced"
    )
    # Still only one conversations row
    conv = get_conversation_row(test_db, conv_id)
    assert conv is not None


def test_trigger_rejects_unknown_conversation_id(client: TestClient) -> None:
    """Passing a conversation_id that doesn't exist should 400 — don't silently create.

    If we silently minted the row, a typo could fragment conversations.
    """
    response = client.post(
        "/api/trigger",
        json={
            "workflow": "test-workflow",
            "inputs": {"issue_key": "TEST-1"},
            "source": "test",
            "conversation_id": "00000000-0000-0000-0000-000000000000",
        },
    )
    assert response.status_code == 400
    assert "conversation" in response.json()["detail"].lower()


def test_orchestrator_reachable_after_trigger(client: TestClient, test_db: Path) -> None:
    """End-to-end gate: after trigger, get_conversation_id_from_run must return truthy.

    This is the exact check chat_routes.py uses to decide whether to route a message
    to the orchestrator. If this returns None, the orchestrator is unreachable.
    """
    from dag_dashboard.queries import get_conversation_id_from_run

    with patch(
        "dag_dashboard.trigger.asyncio.create_subprocess_exec", new_callable=AsyncMock
    ) as mock_subprocess:
        mock_subprocess.return_value = AsyncMock(pid=12345)
        run_id = _trigger(client)

    assert get_conversation_id_from_run(test_db, run_id) is not None
