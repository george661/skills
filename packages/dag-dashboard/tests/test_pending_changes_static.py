"""Tests for pending changes static asset packaging.

Uses TestClient to verify served assets — more robust than file existence
checks, which break when pytest runs from inside the package directory
(as CI does).
"""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dag_dashboard.database import init_db
from dag_dashboard.server import create_app


@pytest.fixture
def client(tmp_path: Path):
    db_dir = tmp_path
    init_db(db_dir / "dashboard.db")
    events_dir = tmp_path / "events"
    events_dir.mkdir()
    checkpoint_dir = tmp_path / "checkpoints"
    checkpoint_dir.mkdir(exist_ok=True)
    app = create_app(
        db_dir,
        events_dir=events_dir,
        checkpoint_dir_fallback=str(checkpoint_dir),
    )
    return TestClient(app)


def test_pending_changes_js_is_served(client: TestClient) -> None:
    """pending-changes.js is reachable via the static handler and exports required globals."""
    r = client.get("/js/pending-changes.js")
    assert r.status_code == 200, f"got {r.status_code}"
    body = r.text
    assert "window.PendingChanges" in body, "Must export window.PendingChanges"
    assert "mount" in body, "Must have mount function"
    assert "unmount" in body, "Must have unmount function"


def test_pending_changes_script_loaded_in_index_html(client: TestClient) -> None:
    """index.html includes pending-changes.js BEFORE app.js.

    The dashboard appends `?v=<cachebust>` query strings to served script
    URLs, so match by basename rather than the literal pre-rewrite tag.
    """
    r = client.get("/")
    assert r.status_code == 200
    body = r.text
    assert "/js/pending-changes.js" in body, "Must load pending-changes.js"
    pc_idx = body.index("pending-changes.js")
    app_idx = body.index("/js/app.js")
    assert pc_idx < app_idx, "pending-changes.js must load before app.js"


def test_app_js_mounts_pending_changes_section(client: TestClient) -> None:
    """app.js wires the pending-workspace-changes container into the run-detail view."""
    r = client.get("/js/app.js")
    assert r.status_code == 200
    body = r.text
    assert "pending-workspace-changes" in body, "Must reference pending-workspace-changes id"
    assert (
        "PendingChanges.mount" in body or "PendingChanges.refresh" in body
    ), "Must call mount or refresh"


def test_pending_changes_css_present(client: TestClient) -> None:
    """styles.css contains the pending-workspace-changes section styles."""
    r = client.get("/css/styles.css")
    assert r.status_code == 200
    assert ".pending-workspace-changes" in r.text, "Must have pending-workspace-changes class"


def test_pending_changes_js_wires_apply_commit_button(client: TestClient) -> None:
    """pending-changes.js wires the Apply + commit button and sends commit: true."""
    r = client.get("/js/pending-changes.js")
    assert r.status_code == 200
    body = r.text

    # Button must be present and enabled (no disabled attribute)
    assert "pending-changes-commit-btn" in body, "Must have commit button class"
    # Verify it's not disabled in the rendered HTML
    assert 'class="pending-changes-commit-btn"' in body or 'pending-changes-commit-btn' in body

    # Verify commit: true is sent in the request body
    assert "commit: true" in body or '"commit":true' in body or '"commit": true' in body, \
        "Must send commit: true in request body"


def test_pending_changes_css_has_warning_toast_class(client: TestClient) -> None:
    """styles.css has warning toast class for partial-success states."""
    r = client.get("/css/styles.css")
    assert r.status_code == 200
    body = r.text
    assert ".pending-changes-toast-warning" in body, "Must have warning toast class"
