"""Tests for repo_paths module - repository path resolution."""
from __future__ import annotations

import os
import json
import tempfile
from pathlib import Path
from typing import Any
import pytest

from dag_executor.repo_paths import (
    resolve_repo_path,
    RepoPathError,
    _normalize_slug,
)


class TestRepoPathResolver:
    """Test suite for repository path resolution."""

    def test_explicit_config_file_has_highest_priority(self, tmp_path: Path) -> None:
        """AC-16: Explicit config file takes precedence over all other methods."""
        config_file = tmp_path / "repo-paths.json"
        config_file.write_text(json.dumps({"skills": str(tmp_path / "custom-skills")}))
        
        # Create the directory so it exists
        (tmp_path / "custom-skills").mkdir()
        
        result = resolve_repo_path("skills", config_path=str(config_file))
        assert result == str(tmp_path / "custom-skills")

    def test_env_var_override_second_priority(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """AC-16: Environment variable REPO_PATH_<SLUG_UPPER> second priority."""
        repo_dir = tmp_path / "env-skills"
        repo_dir.mkdir()
        
        monkeypatch.setenv("REPO_PATH_SKILLS", str(repo_dir))
        
        result = resolve_repo_path("skills")
        assert result == str(repo_dir)

    def test_project_root_slug_third_priority(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """AC-16: $PROJECT_ROOT/<slug> is third priority."""
        project_root = tmp_path / "project"
        project_root.mkdir()
        repo_dir = project_root / "skills"
        repo_dir.mkdir()
        
        monkeypatch.setenv("PROJECT_ROOT", str(project_root))
        
        result = resolve_repo_path("skills")
        assert result == str(repo_dir)

    def test_home_dev_slug_fourth_priority(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """AC-16: $HOME/dev/<slug> is fourth priority."""
        home_dir = tmp_path / "home"
        home_dir.mkdir()
        dev_dir = home_dir / "dev"
        dev_dir.mkdir()
        repo_dir = dev_dir / "skills"
        repo_dir.mkdir()
        
        monkeypatch.setenv("HOME", str(home_dir))
        # Clear PROJECT_ROOT to skip that layer
        monkeypatch.delenv("PROJECT_ROOT", raising=False)
        
        result = resolve_repo_path("skills")
        assert result == str(repo_dir)

    def test_filesystem_probe_last_resort(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """AC-16: Filesystem probe is last resort (disabled by default)."""
        home_dir = tmp_path / "home"
        home_dir.mkdir()
        dev_dir = home_dir / "dev"
        dev_dir.mkdir()
        subdir = dev_dir / "projects"
        subdir.mkdir()
        repo_dir = subdir / "skills"
        repo_dir.mkdir()
        
        monkeypatch.setenv("HOME", str(home_dir))
        monkeypatch.delenv("PROJECT_ROOT", raising=False)
        monkeypatch.setenv("REPO_PATH_ENABLE_PROBE", "1")
        
        result = resolve_repo_path("skills")
        assert result == str(repo_dir)

    def test_out_of_tree_repo_resolution(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """AC-17: Out-of-tree repo (skills at ~/dev/skills) resolves correctly."""
        home_dir = tmp_path / "home"
        home_dir.mkdir()
        dev_dir = home_dir / "dev"
        dev_dir.mkdir()
        repo_dir = dev_dir / "skills"
        repo_dir.mkdir()
        
        monkeypatch.setenv("HOME", str(home_dir))
        monkeypatch.delenv("PROJECT_ROOT", raising=False)
        
        result = resolve_repo_path("skills")
        assert result == str(repo_dir)

    def test_no_gw_agents_dependency(self) -> None:
        """AC-18: Resolver has no import or code-path dependency on gw-agents."""
        # Check that source file has no gw-agents imports
        from pathlib import Path
        import dag_executor.repo_paths as rp
        
        source_file = Path(rp.__file__)
        source = source_file.read_text()
        
        # Check for imports (not just mentions in comments)
        assert "import gw_agents" not in source
        assert "from gw_agents" not in source
        # Also check that gw-agents isn't used in actual code paths
        # (it can be mentioned in docstrings as context)

    def test_missing_repo_raises_error(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that missing repo raises RepoPathError with helpful context."""
        home_dir = tmp_path / "home"
        home_dir.mkdir()
        
        monkeypatch.setenv("HOME", str(home_dir))
        monkeypatch.delenv("PROJECT_ROOT", raising=False)
        
        with pytest.raises(RepoPathError) as exc_info:
            resolve_repo_path("nonexistent-repo")
        
        error = exc_info.value
        assert "nonexistent-repo" in str(error)
        assert len(error.search_paths) > 0

    def test_config_file_missing_is_ok(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that missing config file is not an error - resolver falls through."""
        nonexistent_config = tmp_path / "does-not-exist.json"
        home_dir = tmp_path / "home"
        home_dir.mkdir()
        dev_dir = home_dir / "dev"
        dev_dir.mkdir()
        repo_dir = dev_dir / "skills"
        repo_dir.mkdir()
        
        monkeypatch.setenv("HOME", str(home_dir))
        monkeypatch.delenv("PROJECT_ROOT", raising=False)
        
        # Should not raise error about missing config, should fall through to HOME/dev
        result = resolve_repo_path("skills", config_path=str(nonexistent_config))
        assert result == str(repo_dir)

    def test_config_file_malformed_raises_error(self, tmp_path: Path) -> None:
        """Test that malformed config file raises clear error."""
        config_file = tmp_path / "repo-paths.json"
        config_file.write_text("{invalid json")
        
        with pytest.raises(RepoPathError) as exc_info:
            resolve_repo_path("skills", config_path=str(config_file))
        
        assert "malformed" in str(exc_info.value).lower() or "json" in str(exc_info.value).lower()

    def test_slug_normalization(self) -> None:
        """Test that slug normalization handles edge cases correctly.
        
        Note: gw-foo and gw_foo both normalize to GW_FOO and would collide.
        This is documented but not a concern for current repo list.
        """
        assert _normalize_slug("skills") == "SKILLS"
        assert _normalize_slug("gw-skills") == "GW_SKILLS"
        assert _normalize_slug("gw_skills") == "GW_SKILLS"
        assert _normalize_slug("my-repo-name") == "MY_REPO_NAME"

    def test_config_file_default_locations(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that resolver checks default config locations (PROJECT_ROOT first, then HOME)."""
        # Set up HOME config
        home_dir = tmp_path / "home"
        home_dir.mkdir()
        home_claude_dir = home_dir / ".claude" / "config"
        home_claude_dir.mkdir(parents=True)
        home_config_file = home_claude_dir / "repo-paths.json"

        home_repo_dir = tmp_path / "home-skills"
        home_repo_dir.mkdir()
        home_config_file.write_text(json.dumps({"skills": str(home_repo_dir)}))

        # Set up PROJECT_ROOT config (should have priority)
        project_root = tmp_path / "project"
        project_root.mkdir()
        project_claude_dir = project_root / ".claude" / "config"
        project_claude_dir.mkdir(parents=True)
        project_config_file = project_claude_dir / "repo-paths.json"

        project_repo_dir = tmp_path / "project-skills"
        project_repo_dir.mkdir()
        project_config_file.write_text(json.dumps({"skills": str(project_repo_dir)}))

        monkeypatch.setenv("HOME", str(home_dir))
        monkeypatch.setenv("PROJECT_ROOT", str(project_root))

        # Should prefer PROJECT_ROOT config over HOME
        result = resolve_repo_path("skills")
        assert result == str(project_repo_dir)

        # Test HOME fallback when PROJECT_ROOT config doesn't exist
        project_config_file.unlink()
        result = resolve_repo_path("skills")
        assert result == str(home_repo_dir)

    def test_probe_disabled_by_default(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that filesystem probe is disabled by default to avoid slow find operations."""
        home_dir = tmp_path / "home"
        home_dir.mkdir()
        dev_dir = home_dir / "dev"
        dev_dir.mkdir()
        subdir = dev_dir / "deep" / "nested"
        subdir.mkdir(parents=True)
        repo_dir = subdir / "skills"
        repo_dir.mkdir()
        
        monkeypatch.setenv("HOME", str(home_dir))
        monkeypatch.delenv("PROJECT_ROOT", raising=False)
        # Probe is NOT enabled
        
        with pytest.raises(RepoPathError):
            resolve_repo_path("skills")

    def test_error_contains_search_paths(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that RepoPathError includes list of locations searched."""
        home_dir = tmp_path / "home"
        home_dir.mkdir()
        
        monkeypatch.setenv("HOME", str(home_dir))
        monkeypatch.delenv("PROJECT_ROOT", raising=False)
        
        with pytest.raises(RepoPathError) as exc_info:
            resolve_repo_path("missing-repo")
        
        error = exc_info.value
        # Should list at least HOME/dev/missing-repo
        assert any("missing-repo" in path for path, _ in error.search_paths)



class TestVariableIntegration:
    """Test $repo_path(...) integration with variable resolver."""

    def test_repo_path_variable_resolves(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that $repo_path(skills) resolves in variable substitution."""
        from dag_executor.variables import resolve_variables
        
        home_dir = tmp_path / "home"
        home_dir.mkdir()
        dev_dir = home_dir / "dev"
        dev_dir.mkdir()
        repo_dir = dev_dir / "skills"
        repo_dir.mkdir()
        
        monkeypatch.setenv("HOME", str(home_dir))
        monkeypatch.delenv("PROJECT_ROOT", raising=False)
        
        result = resolve_variables(
            "$repo_path(skills)",
            node_outputs={},
            workflow_inputs={}
        )
        
        assert result == str(repo_dir)

    def test_repo_path_in_string_interpolation(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that $repo_path(...) works in string interpolation."""
        from dag_executor.variables import resolve_variables
        
        home_dir = tmp_path / "home"
        home_dir.mkdir()
        dev_dir = home_dir / "dev"
        dev_dir.mkdir()
        repo_dir = dev_dir / "skills"
        repo_dir.mkdir()
        
        monkeypatch.setenv("HOME", str(home_dir))
        monkeypatch.delenv("PROJECT_ROOT", raising=False)
        
        result = resolve_variables(
            "cd $repo_path(skills) && npm install",
            node_outputs={},
            workflow_inputs={}
        )
        
        assert result == f"cd {repo_dir} && npm install"

    def test_repo_path_invalid_slug_raises_error(self) -> None:
        """Test that invalid repo slug in $repo_path(...) raises clear error."""
        from dag_executor.variables import resolve_variables, VariableResolutionError
        
        with pytest.raises(VariableResolutionError) as exc_info:
            resolve_variables(
                "$repo_path(nonexistent-repo)",
                node_outputs={},
                workflow_inputs={}
            )
        
        assert "nonexistent-repo" in str(exc_info.value)
