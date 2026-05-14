"""Tests for workspaces_diff library."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Dict, Tuple

import pytest

from dag_executor.workspaces_diff import (
    Change,
    ApplyResult,
    iter_changes,
    apply_change,
    suggest_target,
)


def _make_workspace(
    tmp_path: Path,
    files: Dict[str, Tuple[str, str]],
) -> Path:
    """Create a fake workspace with seeded files.
    
    Args:
        tmp_path: pytest tmp_path fixture
        files: Dict mapping workspace_path -> (source_content, workspace_content)
               e.g. {".workflow/prompts/triage.md": ("original", "modified")}
    
    Returns:
        Path to the workspace root
    """
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    
    manifest_entries = []
    
    for workspace_path, (source_content, workspace_content) in files.items():
        # Create source file
        if source_content is not None:
            source_path = source_dir / workspace_path.lstrip("./")
            source_path.parent.mkdir(parents=True, exist_ok=True)
            source_path.write_text(source_content)
            
            # Add manifest entry
            kind = "workflow_yaml"
            if "prompts/" in workspace_path:
                kind = "prompt_file"
            elif "scripts/" in workspace_path:
                kind = "bash_script"
            
            manifest_entries.append({
                "workspace_path": workspace_path,
                "source_path": str(source_path.absolute()),
                "kind": kind,
            })
        
        # Create workspace file
        ws_file = workspace / workspace_path
        ws_file.parent.mkdir(parents=True, exist_ok=True)
        ws_file.write_text(workspace_content)
    
    # Write manifest
    manifest_path = workspace / ".workflow" / ".manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest_entries, indent=2))
    
    return workspace


class TestIterChanges:
    """Tests for iter_changes function."""
    
    def test_iter_changes_round_trip_modified(self, tmp_path):
        """iter_changes on workspace with edited prompt yields Change with diff."""
        workspace = _make_workspace(
            tmp_path,
            {".workflow/prompts/triage.md": ("# Original", "# Modified")},
        )
        
        changes = list(iter_changes(workspace))
        
        assert len(changes) == 1
        change = changes[0]
        assert change.kind == "modified"
        assert change.workspace_path == ".workflow/prompts/triage.md"
        assert change.source_path is not None
        assert change.diff != ""
        assert "Original" in change.diff
        assert "Modified" in change.diff
        assert change.manifest_kind == "prompt_file"
    
    def test_iter_changes_no_diff_when_identical(self, tmp_path):
        """iter_changes on unchanged workspace yields no changes."""
        workspace = _make_workspace(
            tmp_path,
            {".workflow/prompts/triage.md": ("# Same", "# Same")},
        )
        
        changes = list(iter_changes(workspace))
        
        assert len(changes) == 0
    
    def test_iter_changes_detects_new_files(self, tmp_path):
        """iter_changes detects new files under .workflow/ with no manifest entry."""
        workspace = _make_workspace(tmp_path, {})
        
        # Create new file without manifest entry
        new_file = workspace / ".workflow" / "prompts" / "new.md"
        new_file.parent.mkdir(parents=True, exist_ok=True)
        new_file.write_text("# New content")
        
        changes = list(iter_changes(workspace))
        
        assert len(changes) == 1
        change = changes[0]
        assert change.kind == "new"
        assert change.workspace_path == ".workflow/prompts/new.md"
        assert change.source_path is None
        assert change.manifest_kind is None
    
    def test_iter_changes_ignores_files_outside_workflow(self, tmp_path):
        """iter_changes ignores files outside .workflow/ and src/."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        
        # Create files outside .workflow/
        (workspace / "scratch.txt").write_text("ignore")
        (workspace / "foo").mkdir()
        (workspace / "foo" / "bar.txt").write_text("ignore")
        
        # Create manifest (empty)
        manifest = workspace / ".workflow" / ".manifest.json"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text("[]")
        
        changes = list(iter_changes(workspace))
        
        assert len(changes) == 0
    
    def test_iter_changes_empty_when_no_manifest(self, tmp_path):
        """iter_changes returns empty iterator when .manifest.json is absent."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        
        changes = list(iter_changes(workspace))
        
        assert len(changes) == 0
    
    def test_iter_changes_skips_missing_source(self, tmp_path, caplog):
        """iter_changes logs and skips when manifest entry points to missing source."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        
        # Create manifest with entry pointing to non-existent source
        manifest = workspace / ".workflow" / ".manifest.json"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(json.dumps([{
            "workspace_path": ".workflow/prompts/gone.md",
            "source_path": "/nonexistent/path.md",
            "kind": "prompt_file",
        }]))
        
        # Create workspace file
        ws_file = workspace / ".workflow" / "prompts" / "gone.md"
        ws_file.parent.mkdir(parents=True, exist_ok=True)
        ws_file.write_text("content")
        
        changes = list(iter_changes(workspace))
        
        # Should be skipped, not raised
        assert len(changes) == 0
        assert "does not exist" in caplog.text.lower() or "missing" in caplog.text.lower()

    def test_iter_changes_diff_format(self, tmp_path):
        """iter_changes produces well-formed unified diff (starts with ---, contains @@)."""
        workspace = _make_workspace(
            tmp_path,
            {".workflow/prompts/test.md": ("line 1\nline 2\n", "line 1\nmodified\n")},
        )

        changes = list(iter_changes(workspace))

        assert len(changes) == 1
        diff = changes[0].diff
        # Unified diff must start with --- (fromfile line)
        assert diff.startswith("---"), f"Diff should start with ---, got: {diff[:50]}"
        # Must contain @@ hunk header
        assert "@@" in diff, f"Diff should contain @@ hunk header, got: {diff}"
        # Should not have double newlines (regression test for "\n".join bug)
        assert "\n\n\n" not in diff, "Diff contains triple newlines (malformed)"


class TestApplyChange:
    """Tests for apply_change function."""
    
    def test_apply_change_modified(self, tmp_path):
        """apply_change for modified file copies workspace content to source."""
        source_file = tmp_path / "source" / "prompts" / "triage.md"
        source_file.parent.mkdir(parents=True, exist_ok=True)
        source_file.write_text("# Original")
        
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        ws_file = workspace / ".workflow" / "prompts" / "triage.md"
        ws_file.parent.mkdir(parents=True, exist_ok=True)
        ws_file.write_text("# Modified")
        
        change = Change(
            workspace_path=".workflow/prompts/triage.md",
            source_path=source_file,
            kind="modified",
            diff="fake diff",
            manifest_kind="prompt_file",
        )
        
        result = apply_change(change, workspace)
        
        assert result.applied is True
        assert result.source_path == source_file
        assert result.commit_sha is None
        assert result.error is None
        assert source_file.read_text() == "# Modified"
    
    def test_apply_change_new_file_with_target(self, tmp_path):
        """apply_change for new file writes to chosen target_path."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        ws_file = workspace / ".workflow" / "prompts" / "new.md"
        ws_file.parent.mkdir(parents=True, exist_ok=True)
        ws_file.write_text("# New")
        
        target_path = tmp_path / "target" / "prompts" / "new.md"
        target_path.parent.mkdir(parents=True, exist_ok=True)
        
        change = Change(
            workspace_path=".workflow/prompts/new.md",
            source_path=None,
            kind="new",
            diff="",
            manifest_kind=None,
        )
        
        result = apply_change(change, workspace, target_path=target_path)
        
        assert result.applied is True
        assert result.source_path == target_path
        assert target_path.read_text() == "# New"
    
    def test_apply_change_new_file_without_target_raises(self, tmp_path):
        """apply_change for new file without target_path raises ValueError."""
        change = Change(
            workspace_path=".workflow/prompts/new.md",
            source_path=None,
            kind="new",
            diff="",
            manifest_kind=None,
        )
        
        with pytest.raises(ValueError, match="target_path.*required"):
            workspace = tmp_path / "workspace"
            workspace.mkdir()
            apply_change(change, workspace)
    
    def test_apply_change_commit_true_on_git_repo(self, tmp_path):
        """apply_change(commit=True) on git repo returns commit_sha."""
        # Initialize git repo
        source_dir = tmp_path / "source"
        source_dir.mkdir()
        subprocess.run(["git", "init"], cwd=source_dir, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=source_dir, check=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=source_dir, check=True)
        
        source_file = source_dir / "prompts" / "triage.md"
        source_file.parent.mkdir(parents=True, exist_ok=True)
        source_file.write_text("# Original")
        subprocess.run(["git", "add", "."], cwd=source_dir, check=True)
        subprocess.run(["git", "commit", "-m", "Initial"], cwd=source_dir, check=True)
        
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        ws_file = workspace / ".workflow" / "prompts" / "triage.md"
        ws_file.parent.mkdir(parents=True, exist_ok=True)
        ws_file.write_text("# Modified")
        
        change = Change(
            workspace_path=".workflow/prompts/triage.md",
            source_path=source_file,
            kind="modified",
            diff="fake diff",
            manifest_kind="prompt_file",
        )
        
        result = apply_change(change, workspace, commit=True)
        
        assert result.applied is True
        assert result.commit_sha is not None
        assert len(result.commit_sha) == 40  # Git SHA-1
        assert result.error is None
    
    def test_apply_change_commit_true_on_non_git(self, tmp_path):
        """apply_change(commit=True) on non-git source: file copied, error set."""
        source_file = tmp_path / "source" / "prompts" / "triage.md"
        source_file.parent.mkdir(parents=True, exist_ok=True)
        source_file.write_text("# Original")
        
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        ws_file = workspace / ".workflow" / "prompts" / "triage.md"
        ws_file.parent.mkdir(parents=True, exist_ok=True)
        ws_file.write_text("# Modified")
        
        change = Change(
            workspace_path=".workflow/prompts/triage.md",
            source_path=source_file,
            kind="modified",
            diff="fake diff",
            manifest_kind="prompt_file",
        )
        
        result = apply_change(change, workspace, commit=True)
        
        assert result.applied is True
        assert result.commit_sha is None
        assert result.error is not None
        assert "not a git working tree" in result.error.lower()
        # File should still be copied
        assert source_file.read_text() == "# Modified"


class TestSuggestTarget:
    """Tests for suggest_target function."""
    
    def test_suggest_target_prompts(self, tmp_path):
        """suggest_target maps .workflow/prompts/foo.md to workflows_dir/prompts/foo.md."""
        workflows_dir = tmp_path / "workflows"
        
        change = Change(
            workspace_path=".workflow/prompts/foo.md",
            source_path=None,
            kind="new",
            diff="",
            manifest_kind=None,
        )
        
        target = suggest_target(change, workflows_dir=workflows_dir)
        
        assert target == workflows_dir / "prompts" / "foo.md"
    
    def test_suggest_target_scripts(self, tmp_path):
        """suggest_target maps .workflow/scripts/foo.sh to workflows_dir/scripts/foo.sh."""
        workflows_dir = tmp_path / "workflows"
        
        change = Change(
            workspace_path=".workflow/scripts/foo.sh",
            source_path=None,
            kind="new",
            diff="",
            manifest_kind=None,
        )
        
        target = suggest_target(change, workflows_dir=workflows_dir)
        
        assert target == workflows_dir / "scripts" / "foo.sh"
    
    def test_suggest_target_none_when_workflows_dir_none(self):
        """suggest_target returns None when workflows_dir is None."""
        change = Change(
            workspace_path=".workflow/prompts/foo.md",
            source_path=None,
            kind="new",
            diff="",
            manifest_kind=None,
        )
        
        target = suggest_target(change, workflows_dir=None)
        
        assert target is None
    
    def test_suggest_target_none_for_unmappable(self, tmp_path):
        """suggest_target returns None for paths that don't match patterns."""
        workflows_dir = tmp_path / "workflows"
        
        change = Change(
            workspace_path=".workflow/other/file.txt",
            source_path=None,
            kind="new",
            diff="",
            manifest_kind=None,
        )
        
        target = suggest_target(change, workflows_dir=workflows_dir)
        
        assert target is None


class TestNoDashboardImports:
    """Test that workspaces_diff doesn't import dashboard dependencies."""
    
    def test_no_dashboard_imports(self):
        """Importing workspaces_diff should not import fastapi or dag_dashboard."""
        import sys
        
        # Clear any prior imports
        for mod in list(sys.modules.keys()):
            if "workspaces_diff" in mod or "fastapi" in mod or "dag_dashboard" in mod:
                del sys.modules[mod]
        
        # Import the module
        from dag_executor import workspaces_diff  # noqa: F401
        
        # Check fastapi and dag_dashboard not in sys.modules
        assert "fastapi" not in sys.modules
        assert "dag_dashboard" not in sys.modules


class TestIterChangesEdgeCases:
    """Additional edge case tests for iter_changes."""
    
    def test_iter_changes_malformed_manifest(self, tmp_path, caplog):
        """iter_changes logs warning and returns empty for malformed manifest."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        
        # Create malformed manifest
        manifest = workspace / ".workflow" / ".manifest.json"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text("{invalid json")
        
        changes = list(iter_changes(workspace))
        
        assert len(changes) == 0
        assert "failed to read manifest" in caplog.text.lower()
    
    def test_iter_changes_missing_workspace_file(self, tmp_path):
        """iter_changes skips manifest entries with missing workspace files."""
        source_file = tmp_path / "source" / "prompts" / "triage.md"
        source_file.parent.mkdir(parents=True, exist_ok=True)
        source_file.write_text("# Original")
        
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        
        # Create manifest but no workspace file
        manifest = workspace / ".workflow" / ".manifest.json"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(json.dumps([{
            "workspace_path": ".workflow/prompts/triage.md",
            "source_path": str(source_file.absolute()),
            "kind": "prompt_file",
        }]))
        
        changes = list(iter_changes(workspace))

        # Should skip since workspace file doesn't exist
        assert len(changes) == 0

    def test_iter_changes_no_workflow_dir(self, tmp_path):
        """iter_changes handles workspace without .workflow/ directory."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        # No .workflow/ directory at all
        changes = list(iter_changes(workspace))

        assert len(changes) == 0


class TestApplyChangeEdgeCases:
    """Additional edge case tests for apply_change."""
    
    def test_apply_change_workspace_file_read_error(self, tmp_path):
        """apply_change handles workspace file read errors gracefully."""
        source_file = tmp_path / "source" / "prompts" / "triage.md"
        source_file.parent.mkdir(parents=True, exist_ok=True)
        source_file.write_text("# Original")
        
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        # Don't create workspace file - will cause read error
        
        change = Change(
            workspace_path=".workflow/prompts/triage.md",
            source_path=source_file,
            kind="modified",
            diff="fake diff",
            manifest_kind="prompt_file",
        )
        
        result = apply_change(change, workspace)
        
        assert result.applied is False
        assert result.error is not None
        assert "failed to read workspace file" in result.error.lower()
    
    def test_apply_change_destination_write_error(self, tmp_path):
        """apply_change handles destination write errors."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        ws_file = workspace / ".workflow" / "prompts" / "triage.md"
        ws_file.parent.mkdir(parents=True, exist_ok=True)
        ws_file.write_text("# Modified")
        
        # Create a destination that can't be written (e.g., directory exists with same name)
        dest_file = tmp_path / "dest"
        dest_file.mkdir()  # Make it a directory instead of a file
        
        change = Change(
            workspace_path=".workflow/prompts/triage.md",
            source_path=dest_file,
            kind="modified",
            diff="fake diff",
            manifest_kind="prompt_file",
        )
        
        result = apply_change(change, workspace)
        
        assert result.applied is False
        assert result.error is not None

class TestApplyChangeGitEdgeCases:
    """Git-specific edge cases for apply_change."""
    
    def test_apply_change_git_commit_nothing_to_commit(self, tmp_path):
        """apply_change handles case where git commit has nothing to commit."""
        # Initialize git repo
        source_dir = tmp_path / "source"
        source_dir.mkdir()
        subprocess.run(["git", "init"], cwd=source_dir, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=source_dir, check=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=source_dir, check=True)
        
        source_file = source_dir / "prompts" / "triage.md"
        source_file.parent.mkdir(parents=True, exist_ok=True)
        source_file.write_text("# Same")
        subprocess.run(["git", "add", "."], cwd=source_dir, check=True)
        subprocess.run(["git", "commit", "-m", "Initial"], cwd=source_dir, check=True)
        
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        ws_file = workspace / ".workflow" / "prompts" / "triage.md"
        ws_file.parent.mkdir(parents=True, exist_ok=True)
        ws_file.write_text("# Same")  # Same content, nothing to commit
        
        change = Change(
            workspace_path=".workflow/prompts/triage.md",
            source_path=source_file,
            kind="modified",
            diff="",
            manifest_kind="prompt_file",
        )
        
        result = apply_change(change, workspace, commit=True)

        # File copied but commit should fail (nothing to commit)
        assert result.applied is True
        # Specific check: no commit SHA and error message contains "nothing to commit"
        assert result.commit_sha is None
        assert result.error is not None
        assert "nothing to commit" in result.error.lower()
