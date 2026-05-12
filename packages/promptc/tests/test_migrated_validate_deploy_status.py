"""
Tests for the hand-polished production validate-deploy-status command file.

This validates that the migrated production file (commands/validate-deploy-status.md)
adheres to the promptc contract-tier expectations. It is NOT a replacement for the
T7 fixture tests (test_validate_deploy_status_fixture.py) — those remain unchanged
and test the narrower reference fixture.
"""

import pytest
from pathlib import Path
from promptc import load, render, validate
from promptc.contract import parse_output


@pytest.fixture
def production_file_path():
    """Path to the production validate-deploy-status command file."""
    repo_root = Path(__file__).parent.parent.parent.parent
    return repo_root / "commands" / "validate-deploy-status.md"


@pytest.fixture
def production_doc(production_file_path):
    """Load and parse the production file."""
    return load(production_file_path)


def test_production_file_loads_as_contract_tier(production_doc):
    """Verify the production file loads as contract-tier."""
    assert production_doc.tier == "contract", f"Expected tier='contract', got tier='{production_doc.tier}'"
    assert len(production_doc.outputs) == 7, f"Expected 7 output declarations, got {len(production_doc.outputs)}"


def test_production_file_validates(production_file_path):
    """Verify the production file passes promptc validation."""
    doc = load(production_file_path)
    report = validate(doc)

    # Filter to only critical errors (C_* rules)
    critical_errors = [e for e in report.issues if e.code.startswith("C_")]
    assert len(critical_errors) == 0, f"Validation failed with critical errors: {critical_errors}"


def test_production_file_renders_deterministic(production_doc):
    """Verify the production file renders deterministically."""
    inputs = {"issue": "GW-5189"}
    
    # Render 10 times
    renders = []
    for _ in range(10):
        rendered = render(production_doc, inputs)
        renders.append(rendered)
    
    # All renders should be byte-identical
    assert all(r == renders[0] for r in renders), "Renders are not deterministic"


def test_production_file_substitutes_issue_key(production_doc):
    """Verify the issue key is substituted in rendered output."""
    inputs = {"issue": "GW-5189"}
    rendered = render(production_doc, inputs)
    
    # Should contain the literal issue key
    assert "GW-5189" in rendered, "Rendered output does not contain the issue key 'GW-5189'"
    
    # Should NOT contain unsubstituted template syntax
    assert "{% $inputs.issue %}" not in rendered, "Rendered output contains unsubstituted template syntax"


def test_production_file_emits_output_contract(production_doc):
    """Verify the rendered output contains the OUTPUT CONTRACT heading and all 7 fields."""
    inputs = {"issue": "GW-5189"}
    rendered = render(production_doc, inputs)
    
    # Check for OUTPUT CONTRACT section
    assert "## OUTPUT CONTRACT" in rendered or "OUTPUT CONTRACT" in rendered, \
        "Rendered output does not contain OUTPUT CONTRACT heading"
    
    # Check for all 7 output field names
    expected_fields = ["DEPLOY_STATUS", "REPO", "PIPELINE", "BUILD_ID", "BUILD_STATUS", "ENV_URL", "DEPLOY_GAP_REASON"]
    for field in expected_fields:
        assert field in rendered, f"Rendered output does not contain output field '{field}'"


def test_production_file_parse_output_extracts_all_fields(production_doc):
    """Verify that parse_output can extract all declared output fields from a canned response."""
    # NOTE: Using an inline canned response instead of packages/promptc/tests/fixtures/responses/validate-deploy-status-DEPLOYED.txt
    # because the fixture preamble shape differs from the actual LLM response format. This test proves parse_output
    # can extract declared fields from a clean response but does NOT prove it handles real LLM response variance
    # (e.g., extra preamble text, markdown formatting, etc.). This is the narrowest feasible substitute today,
    # as packages/dag-executor/workflows/validate-deploy-status.yaml is a bash pipeline that does NOT load
    # commands/validate-deploy-status.md via promptc.render or parse_output.
    # Canned DEPLOYED response fixture
    canned_response = """
## Phase 3: Output Result

DEPLOY_STATUS: DEPLOYED
REPO: skills
PIPELINE: skills
BUILD_ID: 12345
BUILD_STATUS: succeeded
ENV_URL: https://api.dev.generalwisdom.com
DEPLOY_GAP_REASON: N/A
"""

    result = parse_output(canned_response, production_doc.outputs)
    parsed = result.fields

    # All declared outputs should be present (even if conditionally emitted, parse_output should handle None)
    assert "DEPLOY_STATUS" in parsed, "parse_output did not extract DEPLOY_STATUS"
    assert "REPO" in parsed, "parse_output did not extract REPO"
    assert "PIPELINE" in parsed, "parse_output did not extract PIPELINE"
    assert "BUILD_ID" in parsed, "parse_output did not extract BUILD_ID"
    assert "BUILD_STATUS" in parsed, "parse_output did not extract BUILD_STATUS"
    assert "ENV_URL" in parsed, "parse_output did not extract ENV_URL"
    # DEPLOY_GAP_REASON may be None if not present, but key should exist
    assert "DEPLOY_GAP_REASON" in parsed, "parse_output did not extract DEPLOY_GAP_REASON"

    # Verify extracted values
    assert parsed["DEPLOY_STATUS"] == "DEPLOYED"
    assert parsed["REPO"] == "skills"
    assert parsed["PIPELINE"] == "skills"
    assert parsed["BUILD_ID"] == "12345"
    assert parsed["BUILD_STATUS"] == "succeeded"
    assert parsed["ENV_URL"] == "https://api.dev.generalwisdom.com"
