"""Tests for artifact detection from runner output."""
from dag_executor.artifacts import detect_artifacts


class TestDetectArtifacts:
    def test_detects_github_pr_url(self) -> None:
        text = "Opened PR: https://github.com/george661/skills/pull/42"
        artifacts = detect_artifacts(text)
        assert any(a["artifact_type"] == "pr" and "42" in a["name"] for a in artifacts)
        pr = next(a for a in artifacts if a["artifact_type"] == "pr")
        assert pr["url"] == "https://github.com/george661/skills/pull/42"

    def test_detects_bitbucket_pr_url(self) -> None:
        text = "Created PR https://bitbucket.org/ghostdogbase/gw-functions/pull-requests/123"
        artifacts = detect_artifacts(text)
        prs = [a for a in artifacts if a["artifact_type"] == "pr"]
        assert len(prs) == 1
        assert prs[0]["url"] == "https://bitbucket.org/ghostdogbase/gw-functions/pull-requests/123"

    def test_detects_commit_sha(self) -> None:
        text = "[main 1a2b3c4d] GW-5182 add thing"
        artifacts = detect_artifacts(text)
        commits = [a for a in artifacts if a["artifact_type"] == "commit"]
        assert len(commits) == 1
        assert commits[0]["name"] == "1a2b3c4d"

    def test_detects_branch_pushed(self) -> None:
        text = " * [new branch]      GW-5182-feature -> GW-5182-feature"
        artifacts = detect_artifacts(text)
        branches = [a for a in artifacts if a["artifact_type"] == "branch"]
        assert any(b["name"] == "GW-5182-feature" for b in branches)

    def test_detects_file_created(self) -> None:
        # Simulate a common "Created: path/to/file.py" marker emitted by agents
        text = "Created: packages/dag-executor/src/dag_executor/artifacts.py"
        artifacts = detect_artifacts(text)
        files = [a for a in artifacts if a["artifact_type"] == "file"]
        assert any("artifacts.py" in f["name"] for f in files)

    def test_empty_text_returns_empty_list(self) -> None:
        assert detect_artifacts("") == []

    def test_deduplicates_repeated_artifacts(self) -> None:
        text = (
            "https://github.com/george661/skills/pull/42\n"
            "https://github.com/george661/skills/pull/42\n"
        )
        artifacts = detect_artifacts(text)
        prs = [a for a in artifacts if a["artifact_type"] == "pr"]
        assert len(prs) == 1

    def test_returns_dicts_with_required_keys(self) -> None:
        text = "https://github.com/a/b/pull/1"
        artifacts = detect_artifacts(text)
        assert artifacts
        for a in artifacts:
            assert set(a.keys()) >= {"name", "artifact_type"}
            # Optional keys: url, path
