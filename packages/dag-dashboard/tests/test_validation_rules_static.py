"""Static tests for validation-rules.js - verifies file exists and exports rule functions."""
import pytest
from fastapi.testclient import TestClient


def test_validation_rules_js_served(client: TestClient):
    """Test that validation-rules.js is served at /js/builder/validation-rules.js."""
    response = client.get("/js/builder/validation-rules.js")
    assert response.status_code == 200
    assert "javascript" in response.headers.get("content-type", "").lower()


def test_validation_rules_has_all_four_rules(client: TestClient):
    """Test that validation-rules.js contains all four rule function names."""
    response = client.get("/js/builder/validation-rules.js")
    assert response.status_code == 200
    content = response.text
    
    # Check for all four rule functions
    assert "requiredFields" in content, "Missing requiredFields rule"
    assert "uniqueNodeIds" in content, "Missing uniqueNodeIds rule"
    assert "detectCycles" in content, "Missing detectCycles rule"
    assert "referenceIntegrity" in content, "Missing referenceIntegrity rule"


def test_validation_rules_returns_issue_array(client: TestClient):
    """Test that validation-rules.js documents ValidationIssue return type."""
    response = client.get("/js/builder/validation-rules.js")
    assert response.status_code == 200
    content = response.text
    
    # Check for ValidationIssue shape documentation (JSDoc or comments)
    assert "ValidationIssue" in content or "severity" in content, \
        "Missing ValidationIssue type documentation"
