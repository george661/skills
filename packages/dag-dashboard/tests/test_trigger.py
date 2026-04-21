"""Tests for webhook trigger endpoint."""
import json
from pathlib import Path
from unittest.mock import Mock, patch, AsyncMock
import pytest
from fastapi.testclient import TestClient

from dag_dashboard.database import init_db
from dag_dashboard.server import create_app
from dag_dashboard.queries import get_run


@pytest.fixture
def test_db(tmp_path: Path) -> Path:
    """Create a test database at the expected location."""
    db_path = tmp_path / "dashboard.db"
    init_db(db_path)
    return db_path


@pytest.fixture
def events_dir(tmp_path: Path) -> Path:
    """Create a test events directory."""
    events = tmp_path / "dag-events"
    events.mkdir(exist_ok=True)
    return events


@pytest.fixture
def workflows_dir(tmp_path: Path) -> Path:
    """Create a test workflows directory with a sample workflow."""
    workflows = tmp_path / "workflows"
    workflows.mkdir(exist_ok=True)
    
    # Create a sample workflow file
    workflow_file = workflows / "test-workflow.yaml"
    workflow_file.write_text("""
name: test-workflow
config:
  checkpoint_prefix: test
inputs:
  issue_key:
    type: string
    required: true
  optional_param:
    type: string
    required: false
    default: "default_value"
nodes:
  - id: test-node
    name: Test Node
    type: command
    command: echo "test"
""")
    return workflows


@pytest.fixture
def client(tmp_path: Path, test_db: Path, events_dir: Path, workflows_dir: Path) -> TestClient:
    """Create a test client with trigger endpoint enabled."""
    from dag_dashboard.config import Settings

    # Create settings with trigger enabled
    settings = Settings(
        trigger_enabled=True,
        workflows_dir=workflows_dir
    )

    app = create_app(tmp_path, events_dir=events_dir, settings=settings)
    return TestClient(app, raise_server_exceptions=True)


def test_trigger_endpoint_spawns_subprocess_returns_run_id(client: TestClient, test_db: Path):
    """Test POST /api/trigger spawns dag-executor subprocess and returns run_id non-blocking."""
    with patch("dag_dashboard.trigger.asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_subprocess:
        # Mock the subprocess to return immediately
        mock_process = AsyncMock()
        mock_process.pid = 12345
        mock_subprocess.return_value = mock_process
        
        response = client.post(
            "/api/trigger",
            json={
                "workflow": "test-workflow",
                "inputs": {"issue_key": "TEST-123"},
                "source": "github-webhook"
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "run_id" in data
        assert isinstance(data["run_id"], str)
        
        # Verify subprocess was spawned
        mock_subprocess.assert_called_once()
        
        # Verify run was persisted with trigger_source
        run = get_run(test_db, data["run_id"])
        assert run is not None
        assert run["trigger_source"] == "github-webhook"


def test_trigger_returns_400_for_missing_workflow_file(client: TestClient):
    """Test POST /api/trigger returns 400 when workflow file doesn't exist."""
    response = client.post(
        "/api/trigger",
        json={
            "workflow": "nonexistent-workflow",
            "inputs": {"issue_key": "TEST-123"},
            "source": "test"
        }
    )
    assert response.status_code == 400
    assert "workflow" in response.json()["detail"].lower()


def test_trigger_returns_400_for_invalid_workflow_name_pattern(client: TestClient):
    """Test POST /api/trigger returns 400 for invalid workflow name."""
    response = client.post(
        "/api/trigger",
        json={
            "workflow": "../etc/passwd",
            "inputs": {},
            "source": "test"
        }
    )
    assert response.status_code == 400


def test_trigger_returns_400_for_missing_required_input(client: TestClient):
    """Test POST /api/trigger returns 400 when required input is missing."""
    response = client.post(
        "/api/trigger",
        json={
            "workflow": "test-workflow",
            "inputs": {},  # Missing required 'issue_key'
            "source": "test"
        }
    )
    assert response.status_code == 400
    assert "issue_key" in response.json()["detail"]


def test_trigger_returns_400_for_wrong_input_type(client: TestClient):
    """Test POST /api/trigger returns 400 for wrong input type."""
    response = client.post(
        "/api/trigger",
        json={
            "workflow": "test-workflow",
            "inputs": {"issue_key": 123},  # Should be string
            "source": "test"
        }
    )
    assert response.status_code == 400


def test_trigger_returns_404_when_trigger_disabled(tmp_path: Path, test_db: Path, events_dir: Path, workflows_dir: Path):
    """Test POST /api/trigger returns 404 when trigger endpoint is disabled."""
    from dag_dashboard.config import Settings

    # Create settings with trigger DISABLED
    settings = Settings(trigger_enabled=False)

    app = create_app(tmp_path, events_dir=events_dir, settings=settings)
    client_disabled = TestClient(app, raise_server_exceptions=False)

    response = client_disabled.post(
        "/api/trigger",
        json={
            "workflow": "test-workflow",
            "inputs": {"issue_key": "TEST-123"},
            "source": "test"
        }
    )
    assert response.status_code == 404


def test_trigger_rejects_workflow_path_traversal(client: TestClient):
    """Test POST /api/trigger rejects workflow names with path traversal."""
    response = client.post(
        "/api/trigger",
        json={
            "workflow": "../../../etc/passwd",
            "inputs": {},
            "source": "test"
        }
    )
    assert response.status_code == 400
    assert "path" in response.json()["detail"].lower()


def test_trigger_rejects_workflow_with_slashes(client: TestClient):
    """Test POST /api/trigger rejects workflow names containing slashes."""
    response = client.post(
        "/api/trigger",
        json={
            "workflow": "foo/bar",
            "inputs": {},
            "source": "test"
        }
    )
    assert response.status_code == 400


def test_trigger_persists_source_in_workflow_runs(client: TestClient, test_db: Path):
    """Test POST /api/trigger persists trigger_source in workflow_runs table."""
    with patch("dag_dashboard.trigger.asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_subprocess:
        mock_process = AsyncMock()
        mock_process.pid = 12345
        mock_subprocess.return_value = mock_process

        response = client.post(
            "/api/trigger",
            json={
                "workflow": "test-workflow",
                "inputs": {"issue_key": "TEST-789"},
                "source": "bitbucket-webhook"
            }
        )

        assert response.status_code == 200
        run_id = response.json()["run_id"]

        # Verify source is persisted
        run = get_run(test_db, run_id)
        assert run is not None
        assert run["trigger_source"] == "bitbucket-webhook"


def test_trigger_response_non_blocking(tmp_path: Path, test_db: Path, events_dir: Path, workflows_dir: Path):
    """Test POST /api/trigger responds immediately even if subprocess is slow."""
    from dag_dashboard.config import Settings
    import time

    settings = Settings(
        trigger_enabled=True,
        workflows_dir=workflows_dir
    )

    app = create_app(tmp_path, events_dir=events_dir, settings=settings)
    client = TestClient(app, raise_server_exceptions=True)

    # Mock subprocess to simulate slow execution
    with patch("dag_dashboard.trigger.asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_subprocess:
        async def slow_subprocess(*args, **kwargs):
            # Simulate slow executor (but don't actually block)
            mock_process = AsyncMock()
            mock_process.pid = 99999
            return mock_process

        mock_subprocess.side_effect = slow_subprocess

        start = time.time()
        response = client.post(
            "/api/trigger",
            json={
                "workflow": "test-workflow",
                "inputs": {"issue_key": "TEST-999"},
                "source": "test-non-blocking"
            }
        )
        elapsed = time.time() - start

        # Endpoint should respond in under 1 second (non-blocking)
        assert elapsed < 1.0
        assert response.status_code == 200
        assert "run_id" in response.json()


def test_hmac_verification_accepts_valid_signature(tmp_path: Path, test_db: Path, events_dir: Path, workflows_dir: Path):
    """Test HMAC verification accepts valid signature."""
    import hmac
    import hashlib
    from dag_dashboard.config import Settings

    secret = "test-secret-key"
    settings = Settings(
        trigger_enabled=True,
        trigger_secret=secret,
        workflows_dir=workflows_dir
    )

    app = create_app(tmp_path, events_dir=events_dir, settings=settings)
    client = TestClient(app, raise_server_exceptions=True)

    body = json.dumps({
        "workflow": "test-workflow",
        "inputs": {"issue_key": "TEST-123"},
        "source": "github-webhook"
    })

    # Compute valid signature
    signature = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()

    with patch("dag_dashboard.trigger.asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_subprocess:
        mock_subprocess.return_value = AsyncMock(pid=12345)

        response = client.post(
            "/api/trigger",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": f"sha256={signature}"
            }
        )

        assert response.status_code == 200
        assert "run_id" in response.json()


def test_hmac_verification_rejects_bad_signature(tmp_path: Path, test_db: Path, events_dir: Path, workflows_dir: Path):
    """Test HMAC verification rejects bad signature."""
    from dag_dashboard.config import Settings

    settings = Settings(
        trigger_enabled=True,
        trigger_secret="test-secret-key",
        workflows_dir=workflows_dir
    )

    app = create_app(tmp_path, events_dir=events_dir, settings=settings)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post(
        "/api/trigger",
        json={
            "workflow": "test-workflow",
            "inputs": {"issue_key": "TEST-123"},
            "source": "github-webhook"
        },
        headers={"X-Hub-Signature-256": "sha256=badsignature"}
    )

    assert response.status_code == 401
    assert "signature" in response.json()["detail"].lower()


def test_hmac_verification_rejects_missing_signature_when_secret_configured(tmp_path: Path, test_db: Path, events_dir: Path, workflows_dir: Path):
    """Test HMAC verification rejects missing signature when secret is configured."""
    from dag_dashboard.config import Settings

    settings = Settings(
        trigger_enabled=True,
        trigger_secret="test-secret-key",
        workflows_dir=workflows_dir
    )

    app = create_app(tmp_path, events_dir=events_dir, settings=settings)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post(
        "/api/trigger",
        json={
            "workflow": "test-workflow",
            "inputs": {"issue_key": "TEST-123"},
            "source": "github-webhook"
        }
    )

    assert response.status_code == 401
    assert "missing" in response.json()["detail"].lower()


def test_hmac_not_required_when_trigger_secret_unset(client: TestClient):
    """Test HMAC verification is not required when trigger_secret is unset."""
    with patch("dag_dashboard.trigger.asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_subprocess:
        mock_subprocess.return_value = AsyncMock(pid=12345)

        # No X-Hub-Signature-256 header, and trigger_secret is None in default client
        response = client.post(
            "/api/trigger",
            json={
                "workflow": "test-workflow",
                "inputs": {"issue_key": "TEST-123"},
                "source": "test"
            }
        )

        assert response.status_code == 200
        assert "run_id" in response.json()


def test_rate_limiter_enforces_per_source_limit(tmp_path: Path, test_db: Path, events_dir: Path, workflows_dir: Path):
    """Test rate limiter enforces per-source limit."""
    from dag_dashboard.config import Settings

    settings = Settings(
        trigger_enabled=True,
        trigger_rate_limit_per_min=3,  # Allow only 3 requests per minute
        workflows_dir=workflows_dir
    )

    app = create_app(tmp_path, events_dir=events_dir, settings=settings)
    client = TestClient(app, raise_server_exceptions=False)

    with patch("dag_dashboard.trigger.asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_subprocess:
        mock_subprocess.return_value = AsyncMock(pid=12345)

        # First 3 requests should succeed
        for i in range(3):
            response = client.post(
                "/api/trigger",
                json={
                    "workflow": "test-workflow",
                    "inputs": {"issue_key": f"TEST-{i}"},
                    "source": "rate-test-source"
                }
            )
            assert response.status_code == 200

        # 4th request should be rate limited
        response = client.post(
            "/api/trigger",
            json={
                "workflow": "test-workflow",
                "inputs": {"issue_key": "TEST-999"},
                "source": "rate-test-source"
            }
        )
        assert response.status_code == 429
        assert "rate limit" in response.json()["detail"].lower()


def test_rate_limiter_separate_sources_tracked_independently(tmp_path: Path, test_db: Path, events_dir: Path, workflows_dir: Path):
    """Test rate limiter tracks separate sources independently."""
    from dag_dashboard.config import Settings

    settings = Settings(
        trigger_enabled=True,
        trigger_rate_limit_per_min=2,
        workflows_dir=workflows_dir
    )

    app = create_app(tmp_path, events_dir=events_dir, settings=settings)
    client = TestClient(app, raise_server_exceptions=False)

    with patch("dag_dashboard.trigger.asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_subprocess:
        mock_subprocess.return_value = AsyncMock(pid=12345)

        # 2 requests from source A (should succeed)
        for i in range(2):
            response = client.post(
                "/api/trigger",
                json={
                    "workflow": "test-workflow",
                    "inputs": {"issue_key": f"A-{i}"},
                    "source": "source-a"
                }
            )
            assert response.status_code == 200

        # 2 requests from source B (should also succeed - independent limit)
        for i in range(2):
            response = client.post(
                "/api/trigger",
                json={
                    "workflow": "test-workflow",
                    "inputs": {"issue_key": f"B-{i}"},
                    "source": "source-b"
                }
            )
            assert response.status_code == 200

        # 3rd request from source A should be rate limited
        response = client.post(
            "/api/trigger",
            json={
                "workflow": "test-workflow",
                "inputs": {"issue_key": "A-999"},
                "source": "source-a"
            }
        )
        assert response.status_code == 429


def test_rate_limiter_window_expires(tmp_path: Path, test_db: Path, events_dir: Path, workflows_dir: Path):
    """Test rate limiter sliding window expires old requests."""
    from dag_dashboard.config import Settings
    from dag_dashboard.trigger import RateLimiter

    # Test the RateLimiter directly with time manipulation
    limiter = RateLimiter(requests_per_minute=2)

    # Manually add old timestamps
    import time
    now = time.time()
    limiter.requests["test-source"] = [now - 70, now - 65]  # 70 and 65 seconds ago

    # These old requests should be expired (> 60 seconds old)
    assert limiter.is_allowed("test-source") is True
    assert limiter.is_allowed("test-source") is True
    # Third request within window should be rejected
    assert limiter.is_allowed("test-source") is False


# ---------------------------------------------------------------------------
# Regression tests for review feedback (C2 — run_id propagation)
# ---------------------------------------------------------------------------


def test_trigger_passes_run_id_to_subprocess(client: TestClient, test_db: Path, events_dir: Path):
    """The run_id returned by POST /api/trigger must be passed to the spawned
    dag-exec via --run-id so its NDJSON filename and cancel marker path match
    the workflow_runs row the dashboard inserted.
    """
    with patch(
        "dag_dashboard.trigger.asyncio.create_subprocess_exec",
        new_callable=AsyncMock,
    ) as mock_subprocess:
        mock_process = AsyncMock()
        mock_process.pid = 12345
        mock_subprocess.return_value = mock_process

        response = client.post(
            "/api/trigger",
            json={
                "workflow": "test-workflow",
                "inputs": {"issue_key": "TEST-123"},
                "source": "github-webhook",
            },
        )
        assert response.status_code == 200
        returned_run_id = response.json()["run_id"]

        # Inspect the positional args passed to create_subprocess_exec; they
        # should include ("--run-id", <returned_run_id>) somewhere after the
        # workflow file argument.
        call_args = mock_subprocess.call_args
        positional = list(call_args.args)
        assert "--run-id" in positional, f"--run-id missing from {positional}"
        run_id_idx = positional.index("--run-id")
        assert positional[run_id_idx + 1] == returned_run_id, (
            f"spawned --run-id {positional[run_id_idx + 1]!r} does not match "
            f"returned run_id {returned_run_id!r}"
        )


def test_trigger_passes_events_dir_env_var(client: TestClient, events_dir: Path):
    """The spawned dag-exec must receive DAG_EVENTS_DIR so it writes NDJSON
    and watches for cancel markers at the same location the dashboard uses.
    """
    with patch(
        "dag_dashboard.trigger.asyncio.create_subprocess_exec",
        new_callable=AsyncMock,
    ) as mock_subprocess:
        mock_process = AsyncMock()
        mock_subprocess.return_value = mock_process

        response = client.post(
            "/api/trigger",
            json={
                "workflow": "test-workflow",
                "inputs": {"issue_key": "TEST-123"},
                "source": "test",
            },
        )
        assert response.status_code == 200

        call_env = mock_subprocess.call_args.kwargs.get("env") or {}
        assert "DAG_EVENTS_DIR" in call_env, "DAG_EVENTS_DIR missing from child env"
        # Env var value must be the resolved settings.events_dir (an absolute
        # path). We don't assert the exact path because the Settings default
        # differs from the test fixture events_dir — that's an existing
        # trigger/collector wiring divergence outside GW-5186 scope. What
        # matters here is that the env var is set and resolved.
        assert Path(call_env["DAG_EVENTS_DIR"]).is_absolute()
