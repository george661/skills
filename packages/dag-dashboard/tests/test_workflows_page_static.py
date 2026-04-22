"""Tests for workflows page static file serving."""
from pathlib import Path


STATIC_DIR = Path(__file__).parents[1] / "src" / "dag_dashboard" / "static"


def test_workflows_js_exists() -> None:
    """Test that workflows.js exists and contains expected functions."""
    workflows_js = STATIC_DIR / "js" / "workflows.js"
    assert workflows_js.exists()

    content = workflows_js.read_text()
    assert "renderWorkflowsList" in content
    assert "renderWorkflowDetail" in content


def test_index_html_includes_workflows_script() -> None:
    """Test that index.html includes workflows.js script tag."""
    html = (STATIC_DIR / "index.html").read_text()
    assert "/js/workflows.js" in html


def test_index_html_includes_workflows_nav_link() -> None:
    """Test that index.html includes #/workflows nav link."""
    html = (STATIC_DIR / "index.html").read_text()
    assert "#/workflows" in html


def test_styles_css_includes_workflows_list_container() -> None:
    """Test that styles.css includes .workflows-list-container rule."""
    css = (STATIC_DIR / "css" / "styles.css").read_text()
    assert ".workflows-list-container" in css
