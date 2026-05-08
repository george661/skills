"""Tests for /api/definitions routes."""
import pytest
from fastapi.testclient import TestClient
from pathlib import Path
from dag_dashboard.server import create_app


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    """Create test client with temporary database."""
    app = create_app(tmp_path)
    return TestClient(app)


def test_get_definition_detail_includes_layout(tmp_path: Path) -> None:
    """Test that get_definition_detail returns layout field."""
    # Create a test workflow with nodes
    workflow_yaml = """
name: test-workflow
description: Test workflow for layout
inputs:
  param1:
    type: string
    required: true
nodes:
  - id: node1
    type: command
    command: echo "hello"
  - id: node2
    type: command
    command: echo "world"
    depends_on:
      - node1
"""
    workflows_dir = tmp_path / "workflows"
    workflows_dir.mkdir()
    workflow_file = workflows_dir / "test-workflow.yaml"
    workflow_file.write_text(workflow_yaml)

    # Create app with this workflows dir
    app = create_app(tmp_path, workflows_dirs=[workflows_dir])
    client = TestClient(app)

    response = client.get("/api/definitions/test-workflow")
    assert response.status_code == 200

    data = response.json()
    assert "layout" in data
    assert "nodes" in data["layout"]
    assert "edges" in data["layout"]
    assert len(data["layout"]["nodes"]) == 2
    assert len(data["layout"]["edges"]) == 1


def test_list_definitions_includes_metadata(tmp_path: Path) -> None:
    """Test that list_definitions returns description, inputs, and last_run."""
    # Create a test workflow with metadata
    workflow_yaml = """
name: test-metadata
description: A workflow with metadata
inputs:
  input1:
    type: string
    required: true
  input2:
    type: integer
    required: false
    default: 42
nodes:
  - id: task1
    type: command
    command: echo "test"
"""
    workflows_dir = tmp_path / "workflows"
    workflows_dir.mkdir()
    workflow_file = workflows_dir / "test-metadata.yaml"
    workflow_file.write_text(workflow_yaml)

    # Create app with this workflows dir
    app = create_app(tmp_path, workflows_dirs=[workflows_dir])
    client = TestClient(app)

    response = client.get("/api/definitions")
    assert response.status_code == 200

    definitions = response.json()
    assert len(definitions) == 1

    workflow = definitions[0]
    assert workflow["name"] == "test-metadata"
    assert workflow["description"] == "A workflow with metadata"
    assert "inputs" in workflow
    assert "input1" in workflow["inputs"]
    assert "input2" in workflow["inputs"]
    assert workflow["inputs"]["input1"]["required"] is True
    assert workflow["inputs"]["input2"]["default"] == 42


def test_get_definition_detail_parse_error(tmp_path: Path) -> None:
    """Test that get_definition_detail returns 500 for YAML parse errors."""
    # Create an invalid YAML file
    workflows_dir = tmp_path / "workflows"
    workflows_dir.mkdir()
    workflow_file = workflows_dir / "invalid-yaml.yaml"
    workflow_file.write_text("""
name: test
nodes:
  - id: task1
    invalid: [unclosed bracket
""")

    # Create app with this workflows dir
    app = create_app(tmp_path, workflows_dirs=[workflows_dir])
    client = TestClient(app)

    response = client.get("/api/definitions/invalid-yaml")
    assert response.status_code == 500
    assert "parse error" in response.json()["detail"].lower()


def test_definitions_reflect_db_persisted_workflows_dir(tmp_path: Path) -> None:
    """/api/definitions respects a DB-persisted workflows_dir override.

    Regression guard for GW-5770: when workflows_dir is persisted via the
    Settings UI (dashboard_settings table), the reload_from_db path must
    propagate to app.state.workflows_dirs before routes read it. Previously
    app.state.workflows_dirs was pinned from settings.workflows_dirs BEFORE
    reload_from_db ran, so DB overrides were invisible to /api/definitions.
    """
    from dag_dashboard.config import Settings
    from dag_dashboard.database import init_db
    from dag_dashboard.settings_store import put_setting

    # Create a real workflows dir with one YAML
    real_workflows = tmp_path / "custom-workflows"
    real_workflows.mkdir()
    (real_workflows / "hello.yaml").write_text("""
name: hello
config:
  checkpoint_prefix: test
nodes:
  - id: greet
    name: Greet
    type: bash
    script: 'echo hello'
""".lstrip())

    # Persist workflows_dir in the DB (simulating a Settings UI save)
    db_path = tmp_path / "dashboard.db"
    init_db(db_path)
    put_setting(db_path, "workflows_dir", str(real_workflows), updated_by="test")

    # Settings() sees the default; reload_from_db (inside lifespan) must
    # propagate. Use TestClient as a context manager so lifespan fires.
    settings = Settings()
    app = create_app(db_path=db_path, settings=settings)
    with TestClient(app) as client:
        response = client.get("/api/definitions")
        assert response.status_code == 200
        definitions = response.json()
        names = [d.get("name") for d in definitions]
        assert "hello" in names, (
            f"Expected /api/definitions to reflect DB-persisted workflows_dir, "
            f"got {names}"
        )
