"""
End-to-end integration test for promptc with real Bedrock model.

This test verifies that:
1. Hoisted {% run %} blocks execute in document order before the prompt body
2. The model invocation succeeds against real AWS Bedrock
3. parse_output() extracts declared fields from model response
4. State channels contain the parsed values

Requirements:
- AWS credentials configured (AWS_PROFILE or AWS access keys)
- AWS_REGION set (e.g., us-east-1)
- PROMPTC_E2E=1 environment variable to opt in

Run with:
    source .venv/bin/activate
    PROMPTC_E2E=1 AWS_PROFILE=<profile> AWS_REGION=us-east-1 \
        pytest packages/dag-executor/tests/test_promptc_e2e.py -v

This test is SKIPPED by default in CI and local test runs to avoid:
- Real Bedrock API costs
- Dependency on AWS credentials
- Slow test execution
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest


@pytest.mark.skipif(
    os.environ.get("PROMPTC_E2E") != "1",
    reason="Opt-in integration test — set PROMPTC_E2E=1 to run",
)
def test_promptc_e2e_workflow_runs_against_bedrock(tmp_path: Path) -> None:
    """
    Execute the promptc-e2e workflow against real Bedrock.
    
    Verifies:
    - Hoisted run block captures timestamp
    - Model returns APPROVED or REJECTED verdict
    - Summary field is extracted and non-empty
    - State channels are populated
    """
    # Verify AWS region is configured
    if not os.environ.get("AWS_REGION"):
        pytest.fail(
            "AWS_REGION not set. Configure AWS credentials and region before running this test.\n"
            "Example: AWS_REGION=us-east-1 AWS_PROFILE=ghostdog-dev PROMPTC_E2E=1 pytest ..."
        )
    
    # Locate the workflow YAML relative to this test file
    test_dir = Path(__file__).parent
    workflow_path = test_dir.parent / "workflows" / "promptc-e2e.yaml"
    
    if not workflow_path.exists():
        pytest.fail(f"Workflow not found: {workflow_path}")
    
    # Invoke dag-exec using sys.executable to guarantee we use the venv's installation
    # (avoid stale dag-exec on PATH from miniconda or other envs)
    cmd = [
        sys.executable,
        "-m",
        "dag_executor",
        str(workflow_path),
        f"task_description=Review this e2e test task",
    ]

    # Run from the dag-executor directory so relative paths in the workflow resolve correctly
    # (prompt_file: workflows/promptc-e2e.prompt.md is relative to the package root)
    dag_executor_dir = test_dir.parent
    result = subprocess.run(
        cmd,
        cwd=dag_executor_dir,
        capture_output=True,
        text=True,
        env={**os.environ, "AWS_REGION": os.environ.get("AWS_REGION", "us-east-1")},
    )
    
    # Assert successful execution
    if result.returncode != 0:
        pytest.fail(
            f"dag-exec failed with exit code {result.returncode}\n"
            f"STDOUT:\n{result.stdout}\n"
            f"STDERR:\n{result.stderr}"
        )
    
    # Parse the final state from checkpoint or stdout
    # dag-exec emits a final state summary to stdout after completion
    # Look for workflow outputs in the output
    stdout = result.stdout

    # Extract outputs from stdout (dag-exec prints workflow outputs after execution)
    # The format is typically JSON or key-value pairs
    # The checkpoint is in the dag-executor directory (where we ran from)
    checkpoint_dir = dag_executor_dir / ".dag-checkpoints"
    if checkpoint_dir.exists():
        # Find the latest checkpoint file
        checkpoint_files = list(checkpoint_dir.glob("promptc-e2e-workflow-*.json"))
        if checkpoint_files:
            latest_checkpoint = max(checkpoint_files, key=lambda p: p.stat().st_mtime)
            with open(latest_checkpoint) as f:
                checkpoint_data = json.load(f)
            
            # Extract state channels
            state = checkpoint_data.get("state", {})
            verdict = state.get("verdict")
            summary = state.get("summary")
            
            # Assert verdict is one of the allowed enum values
            assert verdict in ["APPROVED", "REJECTED"], (
                f"Expected verdict to be APPROVED or REJECTED, got: {verdict}"
            )
            
            # Assert summary is non-empty string
            assert summary and isinstance(summary, str) and len(summary) > 0, (
                f"Expected non-empty summary string, got: {summary}"
            )
            
            # Verify timestamp was captured (check stdout for evidence of hoisted run)
            # The timestamp from the hoisted run should be substituted into the prompt
            # We can verify by checking if a YYYY-MM-DD pattern appears in stdout
            timestamp_pattern = r"\d{4}-\d{2}-\d{2}"
            assert re.search(timestamp_pattern, stdout) or re.search(timestamp_pattern, result.stderr), (
                f"Expected to find timestamp pattern YYYY-MM-DD in output, indicating hoisted run executed.\n"
                f"STDOUT: {stdout}\nSTDERR: {result.stderr}"
            )
            
            print(f"\n✓ E2E test passed!")
            print(f"  Verdict: {verdict}")
            print(f"  Summary: {summary}")
            print(f"  Timestamp pattern found in output")
        else:
            pytest.fail(f"No checkpoint files found in {checkpoint_dir}")
    else:
        # Fallback: try to parse from stdout if no checkpoint dir
        # dag-exec may emit final outputs in JSON format
        pytest.fail(
            f"No checkpoint directory found at {checkpoint_dir}\n"
            f"STDOUT:\n{stdout}\n"
            f"STDERR:\n{result.stderr}"
        )
