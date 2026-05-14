"""Tests for .workflow/ seeding logic."""
import json
from pathlib import Path
import pytest
from dag_executor.schema import WorkflowDef, NodeDef
from dag_executor.seeding import seed_workspace, SeedingError


def _minimal_workflow_dict(nodes):
    """Create a minimal workflow dict with required fields."""
    return {
        "name": "test",
        "config": {"checkpoint_prefix": "test"},
        "nodes": nodes
    }


class TestSeedWorkspace:
    """Tests for seed_workspace function."""

    def test_seed_workspace_creates_workflow_yaml_copy(self, tmp_path):
        """Seeding should copy workflow.yaml to .workflow/workflow.yaml."""
        # Create a minimal workflow YAML
        workflow_yaml = tmp_path / "test.yaml"
        workflow_yaml.write_text("name: test\nnodes:\n  - id: n1\n    type: bash\n    script: echo hi")
        
        # Parse workflow and set _source_path
        workflow = WorkflowDef.model_validate(_minimal_workflow_dict([
            {"id": "n1", "name": "N1", "type": "bash", "script": "echo hi"}
        ]))
        workflow._source_path = workflow_yaml
        
        # Seed workspace
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        seed_workspace(workflow, workspace)
        
        # Verify .workflow/workflow.yaml exists and matches source
        seeded_yaml = workspace / ".workflow" / "workflow.yaml"
        assert seeded_yaml.exists()
        assert seeded_yaml.read_text() == workflow_yaml.read_text()

    def test_seed_workspace_copies_script_paths(self, tmp_path):
        """Seeding should copy script_path files to .workflow/scripts/."""
        # Create workflow with script_path
        workflow_dir = tmp_path / "workflows"
        workflow_dir.mkdir()
        script_dir = workflow_dir / "scripts"
        script_dir.mkdir()
        script_file = script_dir / "lint.sh"
        script_file.write_text("#!/bin/bash\necho lint")
        
        workflow_yaml = workflow_dir / "test.yaml"
        workflow_yaml.write_text("name: test\nnodes:\n  - id: n1\n    type: bash\n    script_path: scripts/lint.sh")
        
        workflow = WorkflowDef.model_validate(_minimal_workflow_dict([
            {"id": "n1", "name": "N1", "type": "bash", "script_path": "scripts/lint.sh"}
        ]))
        workflow._source_path = workflow_yaml
        
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        seed_workspace(workflow, workspace)
        
        seeded_script = workspace / ".workflow" / "scripts" / "lint.sh"
        assert seeded_script.exists()
        assert seeded_script.read_text() == "#!/bin/bash\necho lint"

    def test_seed_workspace_inline_script_not_seeded(self, tmp_path):
        """Inline script: should not be seeded to .workflow/scripts/."""
        workflow_yaml = tmp_path / "test.yaml"
        workflow_yaml.write_text("name: test\nnodes:\n  - id: n1\n    type: bash\n    script: echo inline")
        
        workflow = WorkflowDef.model_validate(_minimal_workflow_dict([
            {"id": "n1", "name": "N1", "type": "bash", "script": "echo inline"}
        ]))
        workflow._source_path = workflow_yaml
        
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        seed_workspace(workflow, workspace)
        
        # .workflow/scripts/ should not exist (no script_path nodes)
        scripts_dir = workspace / ".workflow" / "scripts"
        assert not scripts_dir.exists() or len(list(scripts_dir.iterdir())) == 0

    def test_seed_workspace_writes_manifest(self, tmp_path):
        """Seeding should write .workflow/.manifest.json with entries."""
        workflow_dir = tmp_path / "workflows"
        workflow_dir.mkdir()
        script_dir = workflow_dir / "scripts"
        script_dir.mkdir()
        script_file = script_dir / "test.sh"
        script_file.write_text("echo test")
        
        workflow_yaml = workflow_dir / "test.yaml"
        workflow_yaml.write_text("name: test\nnodes:\n  - id: n1\n    type: bash\n    script_path: scripts/test.sh")
        
        workflow = WorkflowDef.model_validate(_minimal_workflow_dict([
            {"id": "n1", "name": "N1", "type": "bash", "script_path": "scripts/test.sh"}
        ]))
        workflow._source_path = workflow_yaml
        
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        seed_workspace(workflow, workspace)
        
        manifest_file = workspace / ".workflow" / ".manifest.json"
        assert manifest_file.exists()
        manifest = json.loads(manifest_file.read_text())
        assert isinstance(manifest, list)
        assert len(manifest) >= 2  # workflow.yaml + test.sh
        
        # Find workflow.yaml entry
        workflow_entry = next((e for e in manifest if e["kind"] == "workflow_yaml"), None)
        assert workflow_entry is not None
        assert workflow_entry["workspace_path"] == ".workflow/workflow.yaml"
        assert workflow_entry["source_path"] == str(workflow_yaml)
        
        # Find script entry
        script_entry = next((e for e in manifest if e["kind"] == "bash_script"), None)
        assert script_entry is not None
        assert script_entry["workspace_path"] == ".workflow/scripts/test.sh"
        assert script_entry["source_path"] == str(script_file)

    def test_seed_workspace_missing_referenced_file_raises_at_start(self, tmp_path):
        """Missing script_path file should raise SeedingError at seed time."""
        workflow_yaml = tmp_path / "test.yaml"
        workflow_yaml.write_text("name: test\nnodes:\n  - id: n1\n    type: bash\n    script_path: scripts/missing.sh")
        
        workflow = WorkflowDef.model_validate(_minimal_workflow_dict([
            {"id": "n1", "name": "N1", "type": "bash", "script_path": "scripts/missing.sh"}
        ]))
        workflow._source_path = workflow_yaml
        
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        
        with pytest.raises(SeedingError, match="referenced file not found"):
            seed_workspace(workflow, workspace)

    def test_seed_workspace_relative_path_resolves_against_yaml_dir(self, tmp_path):
        """script_path: scripts/x.sh should resolve relative to workflow YAML directory."""
        workflow_dir = tmp_path / "foo"
        workflow_dir.mkdir()
        script_dir = workflow_dir / "scripts"
        script_dir.mkdir()
        script_file = script_dir / "relative.sh"
        script_file.write_text("echo relative")
        
        workflow_yaml = workflow_dir / "wf.yaml"
        workflow_yaml.write_text("name: test\nnodes:\n  - id: n1\n    type: bash\n    script_path: scripts/relative.sh")
        
        workflow = WorkflowDef.model_validate(_minimal_workflow_dict([
            {"id": "n1", "name": "N1", "type": "bash", "script_path": "scripts/relative.sh"}
        ]))
        workflow._source_path = workflow_yaml
        
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        seed_workspace(workflow, workspace)
        
        seeded = workspace / ".workflow" / "scripts" / "relative.sh"
        assert seeded.exists()
        assert seeded.read_text() == "echo relative"

    def test_seed_workspace_rejects_absolute_path(self, tmp_path):
        """Absolute paths in script_path should be rejected."""
        workflow_yaml = tmp_path / "test.yaml"
        workflow_yaml.write_text("name: test\nnodes:\n  - id: n1\n    type: bash\n    script_path: /etc/passwd")
        
        workflow = WorkflowDef.model_validate(_minimal_workflow_dict([
            {"id": "n1", "name": "N1", "type": "bash", "script_path": "/etc/passwd"}
        ]))
        workflow._source_path = workflow_yaml
        
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        
        with pytest.raises(SeedingError, match="absolute paths are not allowed"):
            seed_workspace(workflow, workspace)

    def test_seed_workspace_allows_dotdot_within_boundary(self, tmp_path):
        """Paths with .. that stay within boundary should be allowed."""
        # Create repo structure: repo/workflows/test.yaml and repo/commands/test.sh
        repo = tmp_path / "repo"
        repo.mkdir()
        workflows_dir = repo / "workflows"
        workflows_dir.mkdir()
        commands_dir = repo / "commands"
        commands_dir.mkdir()
        script_file = commands_dir / "test.sh"
        script_file.write_text("echo from commands")
        
        workflow_yaml = workflows_dir / "test.yaml"
        workflow_yaml.write_text("name: test\nnodes:\n  - id: n1\n    type: bash\n    script_path: ../commands/test.sh")
        
        workflow = WorkflowDef.model_validate(_minimal_workflow_dict([
            {"id": "n1", "name": "N1", "type": "bash", "script_path": "../commands/test.sh"}
        ]))
        workflow._source_path = workflow_yaml
        
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        seed_workspace(workflow, workspace)
        
        seeded = workspace / ".workflow" / "scripts" / "test.sh"
        assert seeded.exists()
        assert seeded.read_text() == "echo from commands"

    def test_seed_workspace_rejects_path_too_far_outside(self, tmp_path):
        """Paths that go too far outside (beyond boundary) should be rejected."""
        # Create a very deep structure to test the 4-level boundary
        # tmp_path/a/b/c/d/e/workflows/test.yaml trying to reach ../../../../../outside/bad.sh
        deep = tmp_path
        for _ in range(6):
            deep = deep / "level"
            deep.mkdir()
        
        workflows_dir = deep / "workflows"
        workflows_dir.mkdir()
        
        workflow_yaml = workflows_dir / "test.yaml"
        # This tries to go 6 levels up (beyond the 4-level boundary)
        workflow_yaml.write_text("name: test\nnodes:\n  - id: n1\n    type: bash\n    script_path: ../../../../../../../etc/passwd")
        
        workflow = WorkflowDef.model_validate(_minimal_workflow_dict([
            {"id": "n1", "name": "N1", "type": "bash", "script_path": "../../../../../../../etc/passwd"}
        ]))
        workflow._source_path = workflow_yaml
        
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        
        with pytest.raises(SeedingError, match="outside allowed safe roots"):
            seed_workspace(workflow, workspace)

    def test_seed_workspace_idempotent(self, tmp_path):
        """Calling seed_workspace twice should overwrite cleanly."""
        workflow_dir = tmp_path / "workflows"
        workflow_dir.mkdir()
        script_dir = workflow_dir / "scripts"
        script_dir.mkdir()
        script_file = script_dir / "test.sh"
        script_file.write_text("echo v1")
        
        workflow_yaml = workflow_dir / "test.yaml"
        workflow_yaml.write_text("name: test\nnodes:\n  - id: n1\n    type: bash\n    script_path: scripts/test.sh")
        
        workflow = WorkflowDef.model_validate(_minimal_workflow_dict([
            {"id": "n1", "name": "N1", "type": "bash", "script_path": "scripts/test.sh"}
        ]))
        workflow._source_path = workflow_yaml
        
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        
        # First seed
        seed_workspace(workflow, workspace)
        seeded = workspace / ".workflow" / "scripts" / "test.sh"
        assert seeded.read_text() == "echo v1"
        
        # Update source and re-seed
        script_file.write_text("echo v2")
        seed_workspace(workflow, workspace)
        assert seeded.read_text() == "echo v2"
