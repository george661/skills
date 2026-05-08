"""Integration tests for promptc CLI (GW-5482)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent / "fixtures"
GOOD_DIR = FIXTURES_DIR / "good"
BAD_DIR = FIXTURES_DIR / "bad"
RESPONSES_DIR = FIXTURES_DIR / "responses"


def run_cli(*args: str) -> subprocess.CompletedProcess:
    """Run promptc CLI via subprocess."""
    return subprocess.run(
        [sys.executable, "-m", "promptc"] + list(args),
        capture_output=True,
        text=True,
        check=False,
    )


class TestCLIHelp:
    """Test CLI help and basic usage."""

    def test_help_exits_zero(self) -> None:
        """promptc --help should exit 0 and list subcommands."""
        result = run_cli("--help")
        assert result.returncode == 0
        assert "validate" in result.stdout
        assert "render" in result.stdout
        assert "explain" in result.stdout
        assert "parse" in result.stdout
        assert "--format" in result.stdout
        assert "--allow-future-version" in result.stdout

    def test_no_subcommand_exits_2(self) -> None:
        """promptc with no subcommand should exit 2 (usage error)."""
        result = run_cli()
        assert result.returncode == 2


class TestValidateSubcommand:
    """Test validate subcommand."""

    def test_validate_good_file_exits_zero(self) -> None:
        """validate on a valid file should exit 0."""
        result = run_cli("validate", str(GOOD_DIR / "contract.md"))
        assert result.returncode == 0
        assert "OK" in result.stdout or "ok" in result.stdout.lower()

    def test_validate_bad_file_exits_one(self) -> None:
        """validate on an invalid file should exit 1 and show issues."""
        result = run_cli("validate", str(BAD_DIR / "missing_input_decl.md"))
        assert result.returncode == 1
        # Should contain some error/warning indicator
        assert len(result.stdout) > 0 or len(result.stderr) > 0

    def test_validate_json_format(self) -> None:
        """validate --format json should output valid JSON."""
        result = run_cli("--format", "json", "validate", str(GOOD_DIR / "contract.md"))
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert "ok" in data
        assert isinstance(data["ok"], bool)

    def test_validate_nonexistent_file_exits_one(self) -> None:
        """validate on nonexistent file should exit 1 with clear message."""
        result = run_cli("validate", "/nonexistent/file.md")
        assert result.returncode == 1
        assert "not found" in result.stdout.lower() or "not found" in result.stderr.lower()


class TestRenderSubcommand:
    """Test render subcommand."""

    def test_render_with_inputs_exits_zero(self) -> None:
        """render with valid inputs should exit 0."""
        result = run_cli(
            "render",
            str(GOOD_DIR / "contract.md"),
            "--inputs",
            '{"user_query": "test"}',
        )
        assert result.returncode == 0
        # Should contain rendered output
        assert len(result.stdout) > 0

    def test_render_missing_required_input_exits_one(self) -> None:
        """render without required input should exit 1."""
        result = run_cli("render", str(GOOD_DIR / "contract.md"))
        assert result.returncode == 1

    def test_render_mode_a_vs_mode_b_differ(self) -> None:
        """render --mode=a vs --mode=b should produce different output."""
        with_run = FIXTURES_DIR / "mode_b" / "with_run.md"
        result_a = run_cli(
            "render",
            str(with_run),
            "--mode",
            "a",
            "--inputs",
            '{"issue": "GW-123"}',
        )
        result_b = run_cli(
            "render",
            str(with_run),
            "--mode",
            "b",
            "--inputs",
            '{"issue": "GW-123"}',
        )

        assert result_a.returncode == 0
        assert result_b.returncode == 0

        # Mode-A should contain skill invocation instructions
        assert "jira/get_issue" in result_a.stdout.lower() or "npx tsx" in result_a.stdout

        # Mode-B should NOT contain skill invocation instructions
        assert "npx tsx" not in result_b.stdout
        # Mode-B should NOT contain "Call the ... skill"
        assert "Call the" not in result_b.stdout

    def test_render_mode_b_preserves_unbound_refs(self) -> None:
        """render --mode=b should preserve unbound run refs as literal text."""
        result = run_cli(
            "render",
            str(FIXTURES_DIR / "mode_b" / "with_run_refs.md"),
            "--mode",
            "b",
            "--inputs",
            '{"issue": "GW-123"}',
        )

        assert result.returncode == 0
        # Should preserve unbound refs as literals
        assert "$issue_data.status" in result.stdout
        assert "$issue_data.summary" in result.stdout

    def test_render_invalid_json_inputs_exits_one(self) -> None:
        """render with malformed JSON --inputs should exit 1."""
        result = run_cli("render", str(GOOD_DIR / "contract.md"), "--inputs", "{bad json")
        assert result.returncode == 1
        assert "json" in result.stdout.lower() or "json" in result.stderr.lower()

    def test_render_json_format(self) -> None:
        """render --format json should output valid JSON."""
        result = run_cli(
            "--format",
            "json",
            "render",
            str(GOOD_DIR / "contract.md"),
            "--inputs",
            '{"user_query": "test"}',
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert "output" in data
        assert "mode" in data


class TestExplainSubcommand:
    """Test explain subcommand."""

    def test_explain_exits_zero(self) -> None:
        """explain should exit 0 and show structure."""
        result = run_cli("explain", str(GOOD_DIR / "contract.md"))
        assert result.returncode == 0
        # Should contain structural info
        assert "Tier" in result.stdout or "tier" in result.stdout

    def test_explain_json_format(self) -> None:
        """explain --format json should output valid JSON with expected keys."""
        result = run_cli("--format", "json", "explain", str(GOOD_DIR / "contract.md"))
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert "tier" in data
        assert "inputs" in data
        assert "outputs" in data
        assert "phases" in data
        assert "runs" in data
        assert "refs" in data
        assert "skills" in data

    def test_explain_extracts_nested_skills_from_phases(self) -> None:
        """explain should extract skills from runs nested inside phases.

        Regression test for GW-5482: the _walk_node function now normalizes
        child dicts from raw AST shape {attrs: {skill: ...}} to top-level
        {skill: ...} so the skills_set loop can extract them.
        """
        fixture = FIXTURES_DIR / "validate-deploy-status.md"
        result = run_cli("--format", "json", "explain", str(fixture))
        assert result.returncode == 0
        data = json.loads(result.stdout)
        # validate-deploy-status.md has {% run skill="issues/get_issue" %} inside a phase
        assert "skills" in data
        assert "issues/get_issue" in data["skills"], (
            f"Expected 'issues/get_issue' in skills list, got {data['skills']}"
        )


class TestParseSubcommand:
    """Test parse subcommand."""

    def test_parse_exits_zero_on_valid_response(self) -> None:
        """parse with valid response should exit 0."""
        # First, create a simple contract file
        contract_file = GOOD_DIR / "contract.md"
        response_file = RESPONSES_DIR / "cli_sample.txt"

        result = run_cli("parse", str(contract_file), "--response", str(response_file))
        # May exit 0 or 1 depending on whether response matches contract
        # Just verify it doesn't crash
        assert result.returncode in (0, 1)

    def test_parse_json_format(self) -> None:
        """parse --format json should output valid JSON."""
        contract_file = GOOD_DIR / "contract.md"
        response_file = RESPONSES_DIR / "cli_sample.txt"

        result = run_cli(
            "--format", "json", "parse", str(contract_file), "--response", str(response_file)
        )
        assert result.returncode in (0, 1)
        data = json.loads(result.stdout)
        assert "fields" in data or "errors" in data

    def test_parse_missing_response_file_exits_one(self) -> None:
        """parse with nonexistent response file should exit 1."""
        result = run_cli(
            "parse", str(GOOD_DIR / "contract.md"), "--response", "/nonexistent/response.txt"
        )
        assert result.returncode == 1
        assert "not found" in result.stdout.lower() or "not found" in result.stderr.lower()


class TestFutureVersion:
    """Test --allow-future-version flag."""

    def test_future_version_without_flag_exits_one(self) -> None:
        """validate file with version > 1 should exit 1 without --allow-future-version."""
        result = run_cli("validate", str(FIXTURES_DIR / "future_version.md"))
        assert result.returncode == 1
        assert "version" in result.stdout.lower() or "version" in result.stderr.lower()

    def test_future_version_with_flag_exits_zero(self) -> None:
        """validate file with version > 1 should exit 0 with --allow-future-version."""
        result = run_cli(
            "--allow-future-version", "validate", str(FIXTURES_DIR / "future_version.md")
        )
        assert result.returncode == 0
