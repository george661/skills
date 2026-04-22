"""Tests for /api/definitions endpoints."""
from pathlib import Path
import pytest
from unittest.mock import Mock


@pytest.fixture
def mock_request_with_workflows(tmp_path: Path):
    """Create a mock request with workflows_dirs in app.state."""
    workflows_dir = tmp_path / "workflows"
    workflows_dir.mkdir()

    (workflows_dir / "test-workflow.yaml").write_text("""
nodes:
  - id: step1
    type: command
    command: echo "hello"
""")

    # Create a mock request with app.state.workflows_dirs
    mock_request = Mock()
    mock_request.app.state.workflows_dirs = [workflows_dir]
    return mock_request


async def test_get_definitions_list(mock_request_with_workflows):
    """GET /api/definitions returns list of workflows."""
    from dag_dashboard.routes import get_definitions_list

    result = await get_definitions_list(mock_request_with_workflows)
    assert isinstance(result, list)
    assert len(result) >= 1
    assert result[0]["name"] == "test-workflow"
    assert "source_dir" in result[0]


async def test_get_definition_detail(mock_request_with_workflows):
    """GET /api/definitions/{name} returns YAML + parsed definition."""
    from dag_dashboard.routes import get_definition_detail

    result = await get_definition_detail("test-workflow", mock_request_with_workflows)
    assert result["name"] == "test-workflow"
    assert "yaml_source" in result
    assert "parsed" in result
    assert "nodes" in result["parsed"]


async def test_get_definition_not_found(mock_request_with_workflows):
    """GET /api/definitions/{name} raises 404 for missing workflow."""
    from dag_dashboard.routes import get_definition_detail
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        await get_definition_detail("nonexistent", mock_request_with_workflows)
    assert exc_info.value.status_code == 404


async def test_get_definition_rejects_traversal(mock_request_with_workflows):
    """GET /api/definitions/{name} raises 400 for path traversal attempt."""
    from dag_dashboard.routes import get_definition_detail
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        await get_definition_detail("../etc/passwd", mock_request_with_workflows)
    assert exc_info.value.status_code == 400
