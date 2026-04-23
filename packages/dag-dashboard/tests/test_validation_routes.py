"""Tests for POST /api/workflows/validate endpoint."""
import pytest
from fastapi.testclient import TestClient


def test_post_workflows_validate_valid_yaml_returns_passed(client: TestClient):
    """Test that valid YAML returns empty errors and warnings."""
    valid_yaml = """
name: test_workflow
config:
  checkpoint_prefix: test
nodes:
  - id: node1
    name: First Node
    type: command
    command: echo hello
  - id: node2
    name: Second Node
    type: command
    command: echo world
    depends_on:
      - node1
"""
    response = client.post(
        "/api/workflows/validate",
        json={"yaml": valid_yaml}
    )
    assert response.status_code == 200
    data = response.json()
    assert "errors" in data
    assert "warnings" in data
    # Note: May have warnings about missing command files, but no errors for structure
    assert len([e for e in data["errors"] if e["code"] in ["cycle_detected", "duplicate_id", "required_field"]]) == 0


def test_post_workflows_validate_cycle_returns_error(client: TestClient):
    """Test that cyclic dependencies are detected."""
    cyclic_yaml = """
name: cyclic_workflow
config:
  checkpoint_prefix: test
nodes:
  - id: nodeA
    name: Node A
    type: command
    command: echo A
    depends_on:
      - nodeB
  - id: nodeB
    name: Node B
    type: command
    command: echo B
    depends_on:
      - nodeA
"""
    response = client.post(
        "/api/workflows/validate",
        json={"yaml": cyclic_yaml}
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data["errors"]) > 0, "Expected cycle detection error"
    
    # Check that at least one error has code cycle_detected
    error_codes = [err["code"] for err in data["errors"]]
    assert "cycle_detected" in error_codes, f"Expected cycle_detected error, got: {error_codes}"


def test_post_workflows_validate_bad_yaml_returns_yaml_error(client: TestClient):
    """Test that malformed YAML returns yaml_error."""
    bad_yaml = """
name: test
config:
  checkpoint_prefix: test
nodes:
  - id: node1
    type: command
    [invalid yaml syntax here
"""
    response = client.post(
        "/api/workflows/validate",
        json={"yaml": bad_yaml}
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data["errors"]) > 0, "Expected YAML parse error"
    
    error_codes = [err["code"] for err in data["errors"]]
    # Accept yaml_error or parse_error (both indicate YAML parsing issues)
    assert any(code in ["yaml_error", "parse_error"] for code in error_codes), \
        f"Expected yaml_error or parse_error, got: {error_codes}"


def test_post_workflows_validate_missing_required_pydantic_field(client: TestClient):
    """Test that YAML missing required workflow-level field returns schema_error."""
    # Missing 'name' field
    missing_name_yaml = """
config:
  checkpoint_prefix: test
nodes:
  - id: node1
    name: Test Node
    type: command
    command: echo hello
"""
    response = client.post(
        "/api/workflows/validate",
        json={"yaml": missing_name_yaml}
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data["errors"]) > 0, "Expected schema validation error"
    
    error_codes = [err["code"] for err in data["errors"]]
    assert "schema_error" in error_codes, f"Expected schema_error, got: {error_codes}"


def test_post_workflows_validate_unknown_node_type(client: TestClient):
    """Test that unknown node type is caught."""
    unknown_type_yaml = """
name: test_workflow
config:
  checkpoint_prefix: test
nodes:
  - id: node1
    name: Bogus Node
    type: bogus
    command: echo hello
"""
    response = client.post(
        "/api/workflows/validate",
        json={"yaml": unknown_type_yaml}
    )
    assert response.status_code == 200
    data = response.json()
    
    # The validator may report this as invalid_node_type or schema_error
    # depending on how WorkflowValidator handles unknown types
    assert len(data["errors"]) > 0, "Expected validation error for unknown node type"
    
    error_codes = [err["code"] for err in data["errors"]]
    # Accept either invalid_node_type or schema_error
    assert any(code in ["invalid_node_type", "schema_error"] for code in error_codes), \
        f"Expected invalid_node_type or schema_error, got: {error_codes}"


def test_post_workflows_validate_missing_dependency(client: TestClient):
    """Test that node depending on non-existent node returns missing_dependency error."""
    missing_dep_yaml = """
name: test_workflow
config:
  checkpoint_prefix: test
nodes:
  - id: node1
    name: Test Node
    type: command
    command: echo hello
    depends_on:
      - ghost
"""
    response = client.post(
        "/api/workflows/validate",
        json={"yaml": missing_dep_yaml}
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data["errors"]) > 0, "Expected missing_dependency error"
    
    error_codes = [err["code"] for err in data["errors"]]
    assert "missing_dependency" in error_codes, f"Expected missing_dependency, got: {error_codes}"


def test_post_workflows_validate_duplicate_node_ids(client: TestClient):
    """Test that duplicate node IDs are detected (or YAML parser rejects them)."""
    duplicate_ids_yaml = """
name: test_workflow
config:
  checkpoint_prefix: test
nodes:
  - id: node1
    name: First Node
    type: command
    command: echo hello
  - id: node1
    name: Second Node
    type: command
    command: echo world
"""
    response = client.post(
        "/api/workflows/validate",
        json={"yaml": duplicate_ids_yaml}
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data["errors"]) > 0, "Expected duplicate_id or parse_error"
    
    error_codes = [err["code"] for err in data["errors"]]
    # YAML parser may reject this as parse_error, or validator may catch as duplicate_id
    assert any(code in ["duplicate_id", "parse_error"] for code in error_codes), \
        f"Expected duplicate_id or parse_error, got: {error_codes}"


def test_post_workflows_validate_missing_required_node_field(client: TestClient):
    """Test that node missing required field (name) returns required_field error."""
    missing_name_yaml = """
name: test_workflow
config:
  checkpoint_prefix: test
nodes:
  - id: node1
    type: command
    command: echo hello
"""
    response = client.post(
        "/api/workflows/validate",
        json={"yaml": missing_name_yaml}
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data["errors"]) > 0, "Expected required_field error"
    
    # May be reported as required_field or schema_error depending on validation order
    error_codes = [err["code"] for err in data["errors"]]
    assert any(code in ["required_field", "schema_error"] for code in error_codes), \
        f"Expected required_field or schema_error, got: {error_codes}"
