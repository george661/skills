"""Static tests for node-inspector.js component."""

import pytest
from pathlib import Path
from fastapi.testclient import TestClient

from dag_dashboard.database import init_db
from dag_dashboard.server import create_app


@pytest.fixture
def client(tmp_path: Path):
    """Create test client."""
    db_dir = tmp_path
    init_db(db_dir / "dashboard.db")
    events_dir = tmp_path / "events"
    events_dir.mkdir()
    app = create_app(db_dir, events_dir=events_dir)
    with TestClient(app) as test_client:
        yield test_client


def test_node_inspector_js_served(client):
    """node-inspector.js should be served with class NodeInspector and window export."""
    response = client.get("/js/node-inspector.js")
    assert response.status_code == 200
    source = response.text
    
    # Should define class NodeInspector
    assert "class NodeInspector" in source
    
    # Should export to window
    assert "window.NodeInspector" in source


def test_node_inspector_escapes_html(client):
    """node-inspector.js should use escapeHtml helper and avoid raw innerHTML with user data."""
    response = client.get("/js/node-inspector.js")
    source = response.text
    
    # Should have escapeHtml function (defined or referenced)
    assert "escapeHtml" in source
    
    # Should not use innerHTML with string interpolation (dangerous pattern)
    # This is a heuristic check for common XSS patterns
    # OK: .innerHTML = '<div></div>' (static HTML)
    # NOT OK: .innerHTML = `<div>${userInput}</div>` or .innerHTML = '<div>' + var + '</div>'
    dangerous_patterns = [
        ".innerHTML = `",
        ".innerHTML = '",
        '.innerHTML = "',
        ".innerHTML +=",
    ]
    
    # Check each pattern - should be used minimally or with static content only
    for pattern in dangerous_patterns:
        # If innerHTML is used, verify it's not with obvious variable interpolation
        if pattern in source:
            lines_with_pattern = [line for line in source.split('\n') if pattern in line]
            for line in lines_with_pattern:
                # Check if line contains ${, +, or other concatenation
                if '${' in line or ' + ' in line:
                    pytest.fail(f"Potential XSS: innerHTML with interpolation found: {line[:100]}")


def test_node_inspector_renders_all_types(client):
    """node-inspector.js should define renderers for all six node types."""
    response = client.get("/js/node-inspector.js")
    source = response.text
    
    # Should have renderer methods/functions for each type
    expected_types = [
        "bash",
        "prompt",
        "skill",
        "command",
        "gate",
        "interrupt",
    ]
    
    for node_type in expected_types:
        # Check for render method names (renderBashFields, renderPromptFields, etc.)
        render_method = f"render{node_type.capitalize()}Fields"
        assert render_method in source or f'"{node_type}"' in source, \
            f"Missing renderer for {node_type} type"


def test_node_inspector_common_fields_present(client):
    """node-inspector.js should reference all common field names."""
    response = client.get("/js/node-inspector.js")
    source = response.text
    
    common_fields = [
        "id",
        "name",
        "depends_on",
        "when",
        "trigger_rule",
        "timeout",
        "label",
        "checkpoint",
    ]
    
    for field in common_fields:
        # Field should appear as string key or property access
        assert f'"{field}"' in source or f"'{field}'" in source or f".{field}" in source, \
            f"Common field '{field}' not found in source"


def test_node_inspector_id_regex_validation(client):
    """node-inspector.js should include regex validation for id field."""
    response = client.get("/js/node-inspector.js")
    source = response.text
    
    # Should contain the regex pattern for valid IDs
    assert "[a-zA-Z0-9_-]" in source or "[a-zA-Z0-9_\\\\-]" in source, \
        "ID regex pattern not found"


def test_node_inspector_readonly_mode(client):
    """node-inspector.js should check allowDestructive flag and apply readonly attribute."""
    response = client.get("/js/node-inspector.js")
    source = response.text
    
    # Should reference allowDestructive parameter
    assert "allowDestructive" in source
    
    # Should set readonly attribute based on flag
    assert "readonly" in source.lower()


def test_node_inspector_delete_confirm(client):
    """node-inspector.js should call window.showConfirmDialog before firing onDelete."""
    response = client.get("/js/node-inspector.js")
    source = response.text
    
    # Should call showConfirmDialog
    assert "showConfirmDialog" in source
    
    # Should have onDelete callback
    assert "onDelete" in source


def test_node_inspector_mutual_exclusion_prompt(client):
    """node-inspector.js should implement mutual exclusion for prompt/prompt_file fields."""
    response = client.get("/js/node-inspector.js")
    source = response.text
    
    # Should reference both prompt and prompt_file
    assert "prompt" in source
    assert "prompt_file" in source or "promptFile" in source


def test_node_inspector_json_params_validation(client):
    """node-inspector.js should parse JSON for params field with try/catch."""
    response = client.get("/js/node-inspector.js")
    source = response.text
    
    # Should have JSON.parse
    assert "JSON.parse" in source
    
    # Should have try/catch for error handling
    assert "try" in source and "catch" in source


def test_index_html_includes_inspector(client):
    """index.html should include node-inspector.js script tag."""
    response = client.get("/")
    assert response.status_code == 200
    html = response.text
    
    # Should include script tag for node-inspector.js
    assert "/js/node-inspector.js" in html


def test_inspector_demo_route_registered(client):
    """app.js should register #/inspector-demo route."""
    response = client.get("/js/app.js")
    assert response.status_code == 200
    source = response.text
    
    # Should register inspector-demo route
    assert "inspector-demo" in source or "inspectorDemo" in source or "/inspector-demo" in source
