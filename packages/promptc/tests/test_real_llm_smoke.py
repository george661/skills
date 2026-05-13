"""GW-5491: opt-in real-LLM smoke test for the validate-deploy-status
contract-tier prompt.

Exercises the full chain end-to-end against a real LLM:
   commands/validate-deploy-status.md
       --[promptc.render]--> rendered prompt body
                          --[Bedrock haiku via dag-exec]--> response
                                       --[promptc.parse_output]--> fields

If `promptc.parse_output` extracts all 7 declared fields cleanly from the
real model response, AC #4 is satisfied: end-to-end + parse_output works.

Gated on PROMPTC_REAL_LLM_E2E=1 + AWS_REGION (mirrors test_promptc_e2e.py
in dag-executor). Skipped by default to avoid Bedrock cost on every PR.
The CI workflow has an opt-in `promptc-real-llm-smoke` job that runs this
test only when a PR is labeled `real-llm-smoke`.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest


REQUIRED_FIELDS = (
    "DEPLOY_STATUS",
    "REPO",
    "PIPELINE",
    "BUILD_ID",
    "BUILD_STATUS",
)


@pytest.mark.skipif(
    os.environ.get("PROMPTC_REAL_LLM_E2E") != "1",
    reason="Opt-in smoke — set PROMPTC_REAL_LLM_E2E=1 (and AWS creds) to run",
)
def test_validate_deploy_status_real_llm_extracts_all_fields(tmp_path: Path) -> None:
    """Run the validate-deploy-status workflow against a real Bedrock model
    and assert promptc.parse_output extracts the always-required fields.

    The test invokes `dag-exec` as a subprocess (matching how /validate
    invokes it in production) and parses the artifact lines from stdout.
    """
    if not os.environ.get("AWS_REGION"):
        pytest.fail(
            "AWS_REGION not set. Configure AWS credentials and region "
            "before running this opt-in smoke test."
        )

    # Locate the workflow YAML (sibling to packages/promptc/tests/)
    test_dir = Path(__file__).resolve().parent
    repo_root = test_dir.parent.parent.parent
    workflow_path = (
        repo_root
        / "packages/dag-executor/workflows/validate-deploy-status.yaml"
    )
    assert workflow_path.exists(), f"Workflow not found at {workflow_path}"

    # Pick a known-merged issue for the smoke run. Even if the model
    # returns NEEDS_DEPLOY or FAILED for this key, the test still passes
    # — we're verifying parse_output can extract structured fields, not
    # any specific deploy outcome.
    issue_key = os.environ.get("PROMPTC_SMOKE_ISSUE", "GW-5491")

    cmd = [
        sys.executable,
        "-m",
        "dag_executor",
        str(workflow_path),
        f"issue_key={issue_key}",
    ]

    package_root = repo_root / "packages/dag-executor"
    result = subprocess.run(
        cmd,
        cwd=package_root,
        capture_output=True,
        text=True,
        timeout=300,
    )

    if result.returncode != 0:
        pytest.fail(
            f"dag-exec failed with exit code {result.returncode}\n"
            f"STDOUT:\n{result.stdout}\n"
            f"STDERR:\n{result.stderr}"
        )

    stdout = result.stdout
    # Verify all always-required fields appear in the artifacts section.
    # Output format from dag-exec is `field_name: value` (one per line).
    for field in REQUIRED_FIELDS:
        # Match the Pydantic-snake-cased version of the workflow output
        # name (deploy_status, repo, etc.) — that's what dag-exec emits.
        snake_name = field.lower()
        match = re.search(rf"\b{snake_name}:\s*(\S.*?)(?:\n|$)", stdout)
        assert match, (
            f"Field '{snake_name}' missing from dag-exec stdout.\n"
            f"STDOUT:\n{stdout}\n"
        )
        value = match.group(1).strip()
        assert value, f"Field '{snake_name}' was extracted but empty"

    print("\n✓ Real-LLM smoke passed for validate-deploy-status")
    print(f"  Issue: {issue_key}")
    print(f"  All {len(REQUIRED_FIELDS)} always-required fields extracted")
