"""Static tests for validation-panel.js - verifies file exists and exports React component."""
import pytest
from fastapi.testclient import TestClient


def test_validation_panel_js_served(client: TestClient):
    """Test that validation-panel.js is served at /js/builder/validation-panel.js."""
    response = client.get("/js/builder/validation-panel.js")
    assert response.status_code == 200
    assert "javascript" in response.headers.get("content-type", "").lower()


def test_validation_panel_has_component_class(client: TestClient):
    """Test that validation-panel.js contains ValidationPanel component definition."""
    response = client.get("/js/builder/validation-panel.js")
    assert response.status_code == 200
    content = response.text
    
    # Check for ValidationPanel component (function-based or class-based)
    assert "function ValidationPanel" in content or "class ValidationPanel" in content, \
        "Missing ValidationPanel component definition"


def test_validation_panel_exports_to_global(client: TestClient):
    """Test that validation-panel.js exports to window.DAGDashboardValidation."""
    response = client.get("/js/builder/validation-panel.js")
    assert response.status_code == 200
    content = response.text
    
    # Check for global namespace export
    assert "window.DAGDashboardValidation" in content, \
        "Missing global namespace export"


def test_validation_panel_has_collapse_toggle(client: TestClient):
    """Test that validation-panel.js has collapsible UI logic."""
    response = client.get("/js/builder/validation-panel.js")
    assert response.status_code == 200
    content = response.text
    
    # Check for collapse/expand logic (case-insensitive)
    content_lower = content.lower()
    assert "collaps" in content_lower, "Missing collapse/expand UI logic"
