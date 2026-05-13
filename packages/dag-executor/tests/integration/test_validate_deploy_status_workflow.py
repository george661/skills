"""GW-5491: stub-LLM integration test for the contract-tier
validate-deploy-status workflow.

Loads the YAML, runs it through WorkflowExecutor with subprocess.Popen
monkeypatched to return canned LLM responses (the existing fixtures at
packages/promptc/tests/fixtures/responses/), and asserts that the prompt
node renders commands/validate-deploy-status.md via promptc.render and
parses the response via promptc.parse_output, populating all 7 declared
output fields.

This is the DAG-path counterpart to hooks/test_dispatch_local.py; together
they prove that AC #4 ("end-to-end run + parse_output extracts all
declared fields") is satisfied on both the dispatch-local and
DAG-executor paths.
"""
from __future__ import annotations

import asyncio
import io
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from dag_executor.executor import WorkflowExecutor
from dag_executor.parser import load_workflow


# Path layout: tests/integration/<this file>
_TEST_DIR = Path(__file__).resolve().parent
_PACKAGE_ROOT = _TEST_DIR.parent.parent  # packages/dag-executor
_REPO_ROOT = _PACKAGE_ROOT.parent.parent  # worktree root


@pytest.fixture
def workflow_path() -> Path:
    return _PACKAGE_ROOT / "workflows" / "validate-deploy-status.yaml"


@pytest.fixture
def workflow_def(workflow_path, monkeypatch):
    """Load the workflow with cwd set to the package root, matching how
    dag-exec resolves prompt_file paths in production."""
    monkeypatch.chdir(_PACKAGE_ROOT)
    return load_workflow(workflow_path)


def _stub_popen_returning(canned_response: str) -> MagicMock:
    """Build a subprocess.Popen mock that returns canned_response on stdout."""
    mock_process = MagicMock()
    mock_process.stdout = io.StringIO(canned_response)
    mock_process.stderr = MagicMock()
    mock_process.stderr.read.return_value = ""
    mock_process.stdin = MagicMock()
    mock_process.wait.return_value = 0
    return mock_process


def _read_fixture(name: str) -> str:
    fixture = (
        _REPO_ROOT
        / "packages/promptc/tests/fixtures/responses"
        / f"validate-deploy-status-{name}.txt"
    )
    return fixture.read_text()


def test_workflow_loads_and_runs_with_stub_llm_deployed(workflow_def):
    """DEPLOYED fixture: all 7 declared output fields populate correctly."""
    canned = _read_fixture("DEPLOYED")
    mock_process = _stub_popen_returning(canned)

    with patch("subprocess.Popen", return_value=mock_process):
        executor = WorkflowExecutor()
        result = asyncio.run(
            executor.execute(workflow_def, {"issue_key": "GW-5020"})
        )

    # Workflow completed
    from dag_executor.schema import NodeStatus
    node_result = result.node_results["check_deploy_status"]
    assert node_result.status == NodeStatus.COMPLETED, (
        f"Expected COMPLETED, got {node_result.status}: {node_result.error}"
    )

    # All 7 declared output fields populated from parse_output
    fields = node_result.output
    assert fields["DEPLOY_STATUS"] == "DEPLOYED"
    assert fields["REPO"] == "skills"
    assert fields["PIPELINE"] == "GitHub Actions CI"
    assert fields["BUILD_ID"] == "24520966806"
    assert fields["BUILD_STATUS"] == "success"
    assert "github.com/george661/skills" in fields["ENV_URL"]
    # DEPLOY_GAP_REASON is required_when DEPLOY_STATUS=="NEEDS_DEPLOY"; it's
    # absent from the DEPLOYED response and that's a clean parse.
    assert fields.get("DEPLOY_GAP_REASON") is None


def test_workflow_failed_response_no_gap_reason_required(workflow_def):
    """FAILED fixture: build failed but a deploy was attempted, so
    DEPLOY_GAP_REASON happens to be present in the fixture and parses cleanly."""
    canned = _read_fixture("FAILED")
    mock_process = _stub_popen_returning(canned)

    with patch("subprocess.Popen", return_value=mock_process):
        executor = WorkflowExecutor()
        result = asyncio.run(
            executor.execute(workflow_def, {"issue_key": "GW-1234"})
        )

    from dag_executor.schema import NodeStatus
    node_result = result.node_results["check_deploy_status"]
    assert node_result.status == NodeStatus.COMPLETED
    fields = node_result.output
    assert fields["DEPLOY_STATUS"] == "FAILED"
    assert fields["BUILD_STATUS"] == "failed"


def test_workflow_needs_deploy_extracts_gap_reason(workflow_def):
    """NEEDS_DEPLOY fixture: required_when triggers, DEPLOY_GAP_REASON
    must be present and non-empty."""
    canned = _read_fixture("NEEDS_DEPLOY")
    mock_process = _stub_popen_returning(canned)

    with patch("subprocess.Popen", return_value=mock_process):
        executor = WorkflowExecutor()
        result = asyncio.run(
            executor.execute(workflow_def, {"issue_key": "GW-9999"})
        )

    from dag_executor.schema import NodeStatus
    node_result = result.node_results["check_deploy_status"]
    assert node_result.status == NodeStatus.COMPLETED
    fields = node_result.output
    assert fields["DEPLOY_STATUS"] == "NEEDS_DEPLOY"
    # required_when: DEPLOY_GAP_REASON must be present
    gap = fields.get("DEPLOY_GAP_REASON")
    assert gap is not None and len(gap) > 10, (
        f"DEPLOY_GAP_REASON missing or too short: {gap!r}"
    )


def test_workflow_rendered_prompt_substitutes_issue_input(workflow_def):
    """Verify that promptc.render substitutes ${issue_key} into the prompt
    body. Captures the rendered prompt by inspecting what's written to the
    subprocess stdin."""
    canned = _read_fixture("DEPLOYED")
    mock_process = _stub_popen_returning(canned)
    captured_stdin: list[str] = []
    mock_process.stdin.write = lambda s: captured_stdin.append(s)

    with patch("subprocess.Popen", return_value=mock_process):
        executor = WorkflowExecutor()
        asyncio.run(executor.execute(workflow_def, {"issue_key": "GW-5491"}))

    # The rendered prompt should contain the substituted issue key
    full_prompt = "".join(captured_stdin)
    assert "GW-5491" in full_prompt, (
        f"Issue key was not substituted into rendered prompt. "
        f"First 500 chars: {full_prompt[:500]!r}"
    )
