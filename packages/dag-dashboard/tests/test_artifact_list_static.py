"""Static tests: verify artifact-list JS is wired into index.html."""
from pathlib import Path


STATIC_DIR = Path(__file__).parents[1] / "src" / "dag_dashboard" / "static"


def test_artifact_list_js_file_exists() -> None:
    assert (STATIC_DIR / "js" / "artifact-list.js").exists()


def test_index_html_includes_artifact_list_js() -> None:
    html = (STATIC_DIR / "index.html").read_text()
    assert "artifact-list.js" in html


def test_index_html_has_artifacts_container() -> None:
    # Container is dynamically created in app.js for SPA architecture
    app_js = (STATIC_DIR / "js" / "app.js").read_text()
    assert 'id="run-artifacts-container"' in app_js


def test_artifact_list_fetches_aggregate_endpoint() -> None:
    js = (STATIC_DIR / "js" / "artifact-list.js").read_text()
    assert "/api/workflows/" in js
    assert "/artifacts" in js
