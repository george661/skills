"""Static tests for use-builder-validation.js - verifies file exists and exports validation hook."""
import pytest
from fastapi.testclient import TestClient


def test_use_builder_validation_js_served(client: TestClient):
    """Test that use-builder-validation.js is served at /js/builder/use-builder-validation.js."""
    response = client.get("/js/builder/use-builder-validation.js")
    assert response.status_code == 200
    assert "javascript" in response.headers.get("content-type", "").lower()


def test_use_builder_validation_exports_hook(client: TestClient):
    """Test that use-builder-validation.js contains useBuilderValidation function."""
    response = client.get("/js/builder/use-builder-validation.js")
    assert response.status_code == 200
    content = response.text
    
    # Check for hook function
    assert "useBuilderValidation" in content, "Missing useBuilderValidation function"


def test_use_builder_validation_returns_shape(client: TestClient):
    """Test that use-builder-validation.js documents errors/warnings return shape."""
    response = client.get("/js/builder/use-builder-validation.js")
    assert response.status_code == 200
    content = response.text
    
    # Check for expected return keys
    assert "errors" in content, "Missing 'errors' in return shape"
    assert "warnings" in content, "Missing 'warnings' in return shape"
