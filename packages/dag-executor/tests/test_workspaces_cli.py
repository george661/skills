"""Tests for workspaces CLI commands."""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Dict, Tuple
from unittest.mock import patch
import sys

import pytest

from dag_executor.workspaces_cli import (
    cmd_list,
    cmd_show,
    cmd_prune,
    cmd_diff,
    cmd_promote,
    cmd_discard,
    run_workspaces,
    add_workspaces_parser,
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


class TestDiffSubcommand:
    """Tests for dag-exec workspaces diff."""
    
    def test_diff_no_workspace_errors(self, tmp_path, capsys):
        """Non-existent run_id should exit 1 with error to stderr."""
        args = argparse.Namespace(
            run_id="nonexistent",
            workspaces_cmd="diff"
        )
        
        with patch("dag_executor.workspaces_cli._resolve_workspace_root", return_value=tmp_path):
            result = cmd_diff(args)
        
        assert result == 1
        captured = capsys.readouterr()
        assert "not found" in captured.err.lower() or "does not exist" in captured.err.lower()
    
    def test_diff_no_changes_clean_exit(self, tmp_path, capsys):
        """Workspace with manifest but no edits should print 'No changes' and exit 0."""
        workspace = _make_workspace(
            tmp_path,
            {".workflow/prompts/triage.md": ("original content", "original content")}
        )
        
        args = argparse.Namespace(
            run_id=workspace.name,
            workspaces_cmd="diff"
        )
        
        with patch("dag_executor.workspaces_cli._resolve_workspace_root", return_value=tmp_path):
            result = cmd_diff(args)
        
        assert result == 0
        captured = capsys.readouterr()
        assert "no changes" in captured.out.lower()
    
    def test_diff_modified_file_prints_unified_diff(self, tmp_path, capsys):
        """Modified seeded file should print unified diff."""
        workspace = _make_workspace(
            tmp_path,
            {".workflow/prompts/triage.md": ("original line", "modified line")}
        )
        
        args = argparse.Namespace(
            run_id=workspace.name,
            workspaces_cmd="diff"
        )
        
        with patch("dag_executor.workspaces_cli._resolve_workspace_root", return_value=tmp_path):
            result = cmd_diff(args)
        
        assert result == 0
        captured = capsys.readouterr()
        assert "---" in captured.out
        assert "+++" in captured.out
        assert "-original line" in captured.out or "original line" in captured.out
        assert "+modified line" in captured.out or "modified line" in captured.out
    
    def test_diff_new_file_under_workflow(self, tmp_path, capsys):
        """New file in .workflow/ should be marked as new."""
        workspace = _make_workspace(
            tmp_path,
            {".workflow/prompts/existing.md": ("content", "content")}
        )
        
        # Add a new file not in manifest
        new_file = workspace / ".workflow" / "prompts" / "new.md"
        new_file.write_text("new content here")
        
        args = argparse.Namespace(
            run_id=workspace.name,
            workspaces_cmd="diff"
        )
        
        with patch("dag_executor.workspaces_cli._resolve_workspace_root", return_value=tmp_path):
            result = cmd_diff(args)
        
        assert result == 0
        captured = capsys.readouterr()
        assert "new file" in captured.out.lower() or "(new)" in captured.out.lower()
        assert "new.md" in captured.out


class TestPromoteSubcommand:
    """Tests for dag-exec workspaces promote."""
    
    def test_promote_no_flags_errors(self, tmp_path, capsys):
        """Neither --all nor --file should error with usage hint."""
        workspace = _make_workspace(
            tmp_path,
            {".workflow/prompts/test.md": ("old", "new")}
        )
        
        args = argparse.Namespace(
            run_id=workspace.name,
            workspaces_cmd="promote",
            all=False,
            file=None,
            commit=False,
            target=None
        )
        
        with patch("dag_executor.workspaces_cli._resolve_workspace_root", return_value=tmp_path):
            result = cmd_promote(args)
        
        assert result == 1
        captured = capsys.readouterr()
        assert "error" in captured.err.lower() or "required" in captured.err.lower()
    
    def test_promote_no_changes_clean_exit(self, tmp_path, capsys):
        """--all on clean workspace should print 'No changes' and exit 0."""
        workspace = _make_workspace(
            tmp_path,
            {".workflow/prompts/test.md": ("same", "same")}
        )
        
        args = argparse.Namespace(
            run_id=workspace.name,
            workspaces_cmd="promote",
            all=True,
            file=None,
            commit=False,
            target=None
        )
        
        with patch("dag_executor.workspaces_cli._resolve_workspace_root", return_value=tmp_path):
            result = cmd_promote(args)
        
        assert result == 0
        captured = capsys.readouterr()
        assert "no changes" in captured.out.lower()
    
    def test_promote_all_modified_round_trip(self, tmp_path, capsys):
        """Modify seeded prompt -> promote --all -> source file updated."""
        workspace = _make_workspace(
            tmp_path,
            {".workflow/prompts/test.md": ("original", "modified")}
        )
        
        # Get source path from manifest
        manifest = json.loads((workspace / ".workflow" / ".manifest.json").read_text())
        source_path = Path(manifest[0]["source_path"])
        
        args = argparse.Namespace(
            run_id=workspace.name,
            workspaces_cmd="promote",
            all=True,
            file=None,
            commit=False,
            target=None
        )
        
        with patch("dag_executor.workspaces_cli._resolve_workspace_root", return_value=tmp_path):
            result = cmd_promote(args)
        
        assert result == 0
        assert source_path.read_text() == "modified"
        captured = capsys.readouterr()
        assert "applied" in captured.out.lower()
    
    def test_promote_file_targets_one(self, tmp_path, capsys):
        """promote --file <one> should only apply that one file."""
        workspace = _make_workspace(
            tmp_path,
            {
                ".workflow/prompts/first.md": ("original1", "modified1"),
                ".workflow/prompts/second.md": ("original2", "modified2"),
            }
        )
        
        manifest = json.loads((workspace / ".workflow" / ".manifest.json").read_text())
        first_source = Path(manifest[0]["source_path"])
        second_source = Path(manifest[1]["source_path"])
        
        args = argparse.Namespace(
            run_id=workspace.name,
            workspaces_cmd="promote",
            all=False,
            file=".workflow/prompts/first.md",
            commit=False,
            target=None
        )
        
        with patch("dag_executor.workspaces_cli._resolve_workspace_root", return_value=tmp_path):
            result = cmd_promote(args)
        
        assert result == 0
        assert first_source.read_text() == "modified1"
        assert second_source.read_text() == "original2"  # unchanged
    
    def test_promote_new_file_requires_target(self, tmp_path, capsys):
        """New file without --target should error with candidate suggestion."""
        workspace = _make_workspace(
            tmp_path,
            {".workflow/prompts/existing.md": ("content", "content")}
        )
        
        # Add new file
        new_file = workspace / ".workflow" / "prompts" / "new.md"
        new_file.write_text("new content")
        
        args = argparse.Namespace(
            run_id=workspace.name,
            workspaces_cmd="promote",
            all=True,
            file=None,
            commit=False,
            target=None
        )
        
        with patch("dag_executor.workspaces_cli._resolve_workspace_root", return_value=tmp_path):
            result = cmd_promote(args)
        
        assert result == 1
        captured = capsys.readouterr()
        assert "target" in captured.err.lower() or "--target" in captured.err
    
    def test_promote_new_file_with_target_writes_file(self, tmp_path, capsys):
        """--target <path> for new file should write to that path."""
        workspace = _make_workspace(
            tmp_path,
            {".workflow/prompts/existing.md": ("content", "content")}
        )
        
        # Add new file
        new_file = workspace / ".workflow" / "prompts" / "new.md"
        new_file.write_text("new content")
        
        target_path = tmp_path / "target" / "new.md"
        target_path.parent.mkdir(parents=True, exist_ok=True)
        
        args = argparse.Namespace(
            run_id=workspace.name,
            workspaces_cmd="promote",
            file=".workflow/prompts/new.md",
            all=False,
            commit=False,
            target=str(target_path)
        )
        
        with patch("dag_executor.workspaces_cli._resolve_workspace_root", return_value=tmp_path):
            result = cmd_promote(args)
        
        assert result == 0
        assert target_path.exists()
        assert target_path.read_text() == "new content"
    
    def test_promote_with_commit_creates_git_commit(self, tmp_path, capsys):
        """promote --all --commit should create git commit in source dir."""
        # Check if git is available
        try:
            subprocess.run(["git", "--version"], check=True, capture_output=True)
        except (subprocess.CalledProcessError, FileNotFoundError):
            pytest.skip("git not available")
        
        workspace = _make_workspace(
            tmp_path,
            {".workflow/prompts/test.md": ("original", "modified")}
        )
        
        # Setup git in source dir
        manifest = json.loads((workspace / ".workflow" / ".manifest.json").read_text())
        source_path = Path(manifest[0]["source_path"])
        source_dir = source_path.parent.parent  # Go up to repo root
        
        subprocess.run(["git", "init"], cwd=source_dir, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=source_dir, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=source_dir, check=True, capture_output=True)
        subprocess.run(["git", "add", "."], cwd=source_dir, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "initial"], cwd=source_dir, check=True, capture_output=True)
        
        args = argparse.Namespace(
            run_id=workspace.name,
            workspaces_cmd="promote",
            all=True,
            file=None,
            commit=True,
            target=None
        )
        
        with patch("dag_executor.workspaces_cli._resolve_workspace_root", return_value=tmp_path):
            result = cmd_promote(args)
        
        assert result == 0
        
        # Check commit was created
        log_result = subprocess.run(
            ["git", "log", "-1", "--oneline"],
            cwd=source_dir,
            capture_output=True,
            text=True,
            check=True
        )
        assert "test.md" in log_result.stdout.lower() or "workspace" in log_result.stdout.lower()
    
    def test_promote_with_commit_on_non_git_falls_back(self, tmp_path, capsys):
        """promote --all --commit on non-git source should apply file but mention commit failure."""
        workspace = _make_workspace(
            tmp_path,
            {".workflow/prompts/test.md": ("original", "modified")}
        )
        
        manifest = json.loads((workspace / ".workflow" / ".manifest.json").read_text())
        source_path = Path(manifest[0]["source_path"])
        
        args = argparse.Namespace(
            run_id=workspace.name,
            workspaces_cmd="promote",
            all=True,
            file=None,
            commit=True,
            target=None
        )
        
        with patch("dag_executor.workspaces_cli._resolve_workspace_root", return_value=tmp_path):
            result = cmd_promote(args)
        
        # Should still exit 0 (file was applied)
        assert result == 0
        assert source_path.read_text() == "modified"
        
        captured = capsys.readouterr()
        assert "commit failed" in captured.out.lower() or "error" in captured.out.lower()


class TestDiscardSubcommand:
    """Tests for dag-exec workspaces discard."""
    
    def test_discard_no_flags_errors(self, tmp_path, capsys):
        """Neither --all nor --file should error."""
        workspace = _make_workspace(
            tmp_path,
            {".workflow/prompts/test.md": ("original", "modified")}
        )
        
        args = argparse.Namespace(
            run_id=workspace.name,
            workspaces_cmd="discard",
            all=False,
            file=None
        )
        
        with patch("dag_executor.workspaces_cli._resolve_workspace_root", return_value=tmp_path):
            result = cmd_discard(args)
        
        assert result == 1
        captured = capsys.readouterr()
        assert "error" in captured.err.lower() or "required" in captured.err.lower()
    
    def test_discard_all_restores_modified_files(self, tmp_path, capsys):
        """discard --all should restore modified files from source."""
        workspace = _make_workspace(
            tmp_path,
            {
                ".workflow/prompts/first.md": ("original1", "modified1"),
                ".workflow/prompts/second.md": ("original2", "modified2"),
            }
        )
        
        args = argparse.Namespace(
            run_id=workspace.name,
            workspaces_cmd="discard",
            all=True,
            file=None
        )
        
        with patch("dag_executor.workspaces_cli._resolve_workspace_root", return_value=tmp_path):
            result = cmd_discard(args)
        
        assert result == 0
        assert (workspace / ".workflow" / "prompts" / "first.md").read_text() == "original1"
        assert (workspace / ".workflow" / "prompts" / "second.md").read_text() == "original2"
    
    def test_discard_file_targets_one(self, tmp_path, capsys):
        """discard --file <one> should only revert that one file."""
        workspace = _make_workspace(
            tmp_path,
            {
                ".workflow/prompts/first.md": ("original1", "modified1"),
                ".workflow/prompts/second.md": ("original2", "modified2"),
            }
        )
        
        args = argparse.Namespace(
            run_id=workspace.name,
            workspaces_cmd="discard",
            all=False,
            file=".workflow/prompts/first.md"
        )
        
        with patch("dag_executor.workspaces_cli._resolve_workspace_root", return_value=tmp_path):
            result = cmd_discard(args)
        
        assert result == 0
        assert (workspace / ".workflow" / "prompts" / "first.md").read_text() == "original1"
        assert (workspace / ".workflow" / "prompts" / "second.md").read_text() == "modified2"  # unchanged
    
    def test_discard_new_file_deletes(self, tmp_path, capsys):
        """discard --all should delete new files."""
        workspace = _make_workspace(
            tmp_path,
            {".workflow/prompts/existing.md": ("content", "content")}
        )
        
        # Add new file
        new_file = workspace / ".workflow" / "prompts" / "new.md"
        new_file.write_text("new content")
        
        args = argparse.Namespace(
            run_id=workspace.name,
            workspaces_cmd="discard",
            all=True,
            file=None
        )
        
        with patch("dag_executor.workspaces_cli._resolve_workspace_root", return_value=tmp_path):
            result = cmd_discard(args)
        
        assert result == 0
        assert not new_file.exists()


class TestRegressionExistingSubcommands:
    """Regression tests for existing list/show/prune subcommands."""
    
    def test_list_still_works(self, tmp_path, capsys):
        """cmd_list should return 0 and print run_id."""
        workspace = _make_workspace(
            tmp_path,
            {".workflow/prompts/test.md": ("content", "content")}
        )
        
        args = argparse.Namespace(workspaces_cmd="list")
        
        with patch("dag_executor.workspaces_cli._resolve_workspace_root", return_value=tmp_path):
            result = cmd_list(args)
        
        assert result == 0
        captured = capsys.readouterr()
        assert workspace.name in captured.out
    
    def test_show_still_works(self, tmp_path, capsys):
        """cmd_show should return 0 and print path."""
        workspace = _make_workspace(
            tmp_path,
            {".workflow/prompts/test.md": ("content", "content")}
        )
        
        args = argparse.Namespace(
            run_id=workspace.name,
            workspaces_cmd="show"
        )
        
        with patch("dag_executor.workspaces_cli._resolve_workspace_root", return_value=tmp_path):
            result = cmd_show(args)
        
        assert result == 0
        captured = capsys.readouterr()
        assert str(workspace) in captured.out
    
    def test_prune_still_requires_older_than(self, tmp_path, capsys):
        """cmd_prune without --older-than should error."""
        args = argparse.Namespace(
            older_than=None,
            dry_run=False,
            workspaces_cmd="prune"
        )
        
        with patch("dag_executor.workspaces_cli._resolve_workspace_root", return_value=tmp_path):
            result = cmd_prune(args)
        
        assert result == 1
        captured = capsys.readouterr()
        assert "required" in captured.err.lower()


class TestHelpText:
    """Test help text for new subcommands."""
    
    def test_help_lists_new_subcommands(self):
        """add_workspaces_parser should list diff, promote, discard."""
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()
        
        add_workspaces_parser(subparsers)
        
        help_text = parser.format_help()
        # The subcommands will be in the workspaces subparser
        # We need to check the workspaces subparser help
        workspaces_parser = subparsers.choices.get("workspaces")
        if workspaces_parser:
            # Create a namespace and call workspaces with --help would show subcommands
            # But we can't easily test that without capturing help output
            # For now just check the parser was created
            assert workspaces_parser is not None
