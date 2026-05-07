"""Integration test: parse_output against real Bedrock responses.

Loads the validate-deploy-status.md contract from the T7 fixture, then exercises
parse_output() against responses captured from real production runs of the
/validate-deploy-status command (see tests/fixtures/responses/).

Python version coverage: runs on both 3.9 and 3.12 via the python-packages
CI matrix job.
"""
from pathlib import Path

import pytest

from promptc import load
from promptc.contract import parse_output

FIXTURE_DIR = Path(__file__).parent / "fixtures"
CONTRACT_FIXTURE = FIXTURE_DIR / "validate-deploy-status.md"
RESPONSES_DIR = FIXTURE_DIR / "responses"

CONTRACT_FIELDS = {
    "DEPLOY_STATUS": str,
    "REPO": str,
    "PIPELINE": str,
    "BUILD_ID": str,
    "BUILD_STATUS": str,
    "ENV_URL": str,
}

EXPECTED_DEPLOY_STATUS = {
    "DEPLOYED": "DEPLOYED",
    "FAILED": "FAILED",
    "IN_PROGRESS": "IN_PROGRESS",
    "NEEDS_DEPLOY": "NEEDS_DEPLOY",
}


@pytest.fixture(scope="module")
def contract():
    doc = load(CONTRACT_FIXTURE)
    assert doc.tier == "contract"
    assert {d.name for d in doc.outputs} == set(CONTRACT_FIELDS), (
        "Contract fields drifted from test expectations"
    )
    return doc.outputs


@pytest.mark.parametrize("outcome", sorted(EXPECTED_DEPLOY_STATUS))
def test_parse_captured_response(contract, outcome):
    """Every captured response extracts all 6 contract fields with correct types."""
    response_path = RESPONSES_DIR / f"validate-deploy-status-{outcome}.txt"
    text = response_path.read_text(encoding="utf-8")

    result = parse_output(text, contract)

    assert result.errors == [], f"parse_output reported errors: {result.errors}"
    assert result.strategy in ("json", "line-scan"), (
        f"Unexpected strategy {result.strategy!r}"
    )

    for field_name, field_type in CONTRACT_FIELDS.items():
        assert field_name in result.fields, (
            f"[{outcome}] Missing contract field: {field_name}"
        )
        value = result.fields[field_name]
        assert isinstance(value, field_type), (
            f"[{outcome}] {field_name}={value!r} is {type(value).__name__}, "
            f"expected {field_type.__name__}"
        )
        assert value, f"[{outcome}] {field_name} extracted as empty"

    assert result.fields["DEPLOY_STATUS"] == EXPECTED_DEPLOY_STATUS[outcome], (
        f"[{outcome}] DEPLOY_STATUS did not round-trip"
    )


def test_all_outcomes_covered():
    """Sanity: every declared outcome has a response fixture on disk."""
    actual = {p.stem.replace("validate-deploy-status-", "")
              for p in RESPONSES_DIR.glob("validate-deploy-status-*.txt")}
    missing = set(EXPECTED_DEPLOY_STATUS) - actual
    assert not missing, f"Missing response fixtures for outcomes: {missing}"
