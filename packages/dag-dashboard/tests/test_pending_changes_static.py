"""Tests for pending changes static file packaging."""
from pathlib import Path


def test_pending_changes_js_is_packaged() -> None:
    """Test pending-changes.js exists and contains required exports."""
    js_file = Path("packages/dag-dashboard/src/dag_dashboard/static/js/pending-changes.js")
    assert js_file.exists(), "pending-changes.js must exist"

    content = js_file.read_text()
    assert "window.PendingChanges" in content, "Must export window.PendingChanges"
    assert "mount" in content, "Must have mount function"
    assert "unmount" in content, "Must have unmount function"


def test_pending_changes_script_loaded_in_index_html() -> None:
    """Test index.html includes pending-changes.js script."""
    html_file = Path("packages/dag-dashboard/src/dag_dashboard/static/index.html")
    assert html_file.exists(), "index.html must exist"

    content = html_file.read_text()
    assert '<script src="/js/pending-changes.js">' in content, "Must load pending-changes.js"

    # Verify it loads before app.js
    pc_idx = content.index('pending-changes.js')
    app_idx = content.index('/js/app.js')
    assert pc_idx < app_idx, "pending-changes.js must load before app.js"


def test_app_js_mounts_pending_changes_section() -> None:
    """Test app.js contains mount call for pending-workspace-changes."""
    app_file = Path("packages/dag-dashboard/src/dag_dashboard/static/js/app.js")
    assert app_file.exists(), "app.js must exist"

    content = app_file.read_text()
    assert "pending-workspace-changes" in content, "Must reference pending-workspace-changes id"
    assert "PendingChanges.mount" in content or "PendingChanges.refresh" in content, "Must call mount or refresh"


def test_pending_changes_css_present() -> None:
    """Test styles.css contains pending-workspace-changes styling."""
    css_file = Path("packages/dag-dashboard/src/dag_dashboard/static/css/styles.css")
    assert css_file.exists(), "styles.css must exist"

    content = css_file.read_text()
    assert ".pending-workspace-changes" in content, "Must have pending-workspace-changes class"
