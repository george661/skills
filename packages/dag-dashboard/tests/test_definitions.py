"""Tests for workflow definitions listing and retrieval."""
from pathlib import Path
from typing import List
import pytest
from dag_dashboard.definitions import list_definitions, get_definition


def test_list_definitions_single_dir(tmp_path: Path) -> None:
    """List workflows from a single directory."""
    workflows_dir = tmp_path / "workflows"
    workflows_dir.mkdir()
    
    # Create a simple workflow YAML
    (workflows_dir / "test-workflow.yaml").write_text("""
nodes:
  - id: step1
    type: command
    command: echo "hello"
""")
    
    definitions = list_definitions([workflows_dir])
    assert len(definitions) == 1
    assert definitions[0]["name"] == "test-workflow"
    assert definitions[0]["source_dir"] == str(workflows_dir)


def test_list_definitions_multi_dir(tmp_path: Path) -> None:
    """List workflows from multiple directories."""
    dir1 = tmp_path / "workflows1"
    dir2 = tmp_path / "workflows2"
    dir1.mkdir()
    dir2.mkdir()
    
    (dir1 / "workflow-a.yaml").write_text("nodes: []")
    (dir2 / "workflow-b.yaml").write_text("nodes: []")
    
    definitions = list_definitions([dir1, dir2])
    assert len(definitions) == 2
    names = {d["name"] for d in definitions}
    assert names == {"workflow-a", "workflow-b"}


def test_list_definitions_name_collision_first_wins(tmp_path: Path) -> None:
    """When same name exists in multiple dirs, first dir wins."""
    dir1 = tmp_path / "workflows1"
    dir2 = tmp_path / "workflows2"
    dir1.mkdir()
    dir2.mkdir()
    
    (dir1 / "duplicate.yaml").write_text("nodes:\n  - id: from-dir1")
    (dir2 / "duplicate.yaml").write_text("nodes:\n  - id: from-dir2")
    
    definitions = list_definitions([dir1, dir2])
    # Should only return one entry for "duplicate"
    duplicates = [d for d in definitions if d["name"] == "duplicate"]
    assert len(duplicates) == 1
    assert duplicates[0]["source_dir"] == str(dir1)
    # Should have a collision warning
    assert "collisions" in duplicates[0] or "shadowed_by" in duplicates[0]


def test_list_definitions_skips_invalid_yaml(tmp_path: Path) -> None:
    """Invalid YAML files should be skipped, not raise."""
    workflows_dir = tmp_path / "workflows"
    workflows_dir.mkdir()
    
    (workflows_dir / "valid.yaml").write_text("nodes: []")
    (workflows_dir / "invalid.yaml").write_text("{ invalid yaml syntax [")
    
    definitions = list_definitions([workflows_dir])
    # Should only return the valid one
    names = {d["name"] for d in definitions}
    assert names == {"valid"}


def test_list_definitions_skips_missing_dir(tmp_path: Path) -> None:
    """Missing directories should be skipped, not raise."""
    existing_dir = tmp_path / "exists"
    missing_dir = tmp_path / "missing"
    existing_dir.mkdir()
    
    (existing_dir / "workflow.yaml").write_text("nodes: []")
    
    definitions = list_definitions([existing_dir, missing_dir])
    assert len(definitions) == 1
    assert definitions[0]["name"] == "workflow"


def test_get_definition_returns_yaml_and_parsed(tmp_path: Path) -> None:
    """get_definition should return YAML source and parsed workflow."""
    workflows_dir = tmp_path / "workflows"
    workflows_dir.mkdir()
    
    yaml_content = """
nodes:
  - id: step1
    type: command
    command: echo "test"
"""
    (workflows_dir / "test.yaml").write_text(yaml_content)
    
    definition = get_definition([workflows_dir], "test")
    assert definition is not None
    assert definition["name"] == "test"
    assert definition["yaml_source"] == yaml_content.strip()
    assert "nodes" in definition["parsed"]
    assert len(definition["parsed"]["nodes"]) == 1


def test_get_definition_not_found(tmp_path: Path) -> None:
    """get_definition returns None for missing workflow."""
    workflows_dir = tmp_path / "workflows"
    workflows_dir.mkdir()
    
    definition = get_definition([workflows_dir], "nonexistent")
    assert definition is None


def test_get_definition_rejects_traversal_attempt(tmp_path: Path) -> None:
    """get_definition should reject path traversal attempts."""
    workflows_dir = tmp_path / "workflows"
    workflows_dir.mkdir()
    
    # Try to access parent directory
    with pytest.raises(ValueError, match="Invalid workflow name"):
        get_definition([workflows_dir], "../etc/passwd")
    
    with pytest.raises(ValueError, match="Invalid workflow name"):
        get_definition([workflows_dir], "foo/../../passwd")
