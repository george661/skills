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


@pytest.mark.parametrize(
    "variant,expected_status,gap_reason_required",
    [
        ("DEPLOYED", "DEPLOYED", False),
        ("FAILED", "FAILED", False),
        ("IN_PROGRESS", "IN_PROGRESS", False),
        ("NEEDS_DEPLOY", "NEEDS_DEPLOY", True),
    ],
)
def test_production_file_parse_output_extracts_fields_from_real_fixtures(
    production_doc, variant, expected_status, gap_reason_required
):
    """parse_output extracts all declared fields from real captured Bedrock
    responses for each of the 4 status variants.

    This replaces the previous inline canned-response substitute. The
    fixtures here came from real LLM runs and exercise actual response
    variance (preamble prose, markdown formatting, tables, summaries
    after the field block). The wiring path that turns these fixtures
    into clean parses end-to-end is covered by:
      * hooks/test_dispatch_local.py (dispatch-local.py contract router)
      * packages/dag-executor/tests/integration/test_validate_deploy_status_workflow.py
        (DAG executor prompt node)
    """
    repo_root = Path(__file__).parent.parent.parent.parent
    fixture_path = (
        repo_root
        / "packages/promptc/tests/fixtures/responses"
        / f"validate-deploy-status-{variant}.txt"
    )
    response = fixture_path.read_text()

    result = parse_output(response, production_doc.outputs)

    # Clean parse — no errors against the contract
    assert result.errors == [], (
        f"{variant}: parse_output reported errors against real fixture: "
        f"{result.errors}"
    )

    parsed = result.fields
    # Always-required fields must be present in every variant
    for required_field in ("DEPLOY_STATUS", "REPO", "PIPELINE", "BUILD_ID", "BUILD_STATUS"):
        assert required_field in parsed, (
            f"{variant}: parse_output did not extract {required_field}"
        )
    assert parsed["DEPLOY_STATUS"] == expected_status

    # DEPLOY_GAP_REASON is required_when DEPLOY_STATUS == "NEEDS_DEPLOY"
    if gap_reason_required:
        assert parsed.get("DEPLOY_GAP_REASON"), (
            f"{variant}: DEPLOY_GAP_REASON missing or empty even though "
            f"required_when fired"
        )
