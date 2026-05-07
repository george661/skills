"""Integration test for validate-deploy-status fixture.

This test validates that promptc can render a real-world command fixture
(validate-deploy-status.md) deterministically. The fixture exercises:
- Input/output declarations (contract tier)
- Phase blocks with nested content
- {% run skill="..." %} tags (Mode-A rendering)
- {% $inputs.issue %} variable substitution

Python version coverage: This test runs on both Python 3.9 and 3.12 via the
CI matrix job (python-packages in .github/workflows/ci.yml). The golden file
locks byte-identical output across both versions.
"""
from pathlib import Path

from promptc import load, render

# Fixture paths
FIXTURE_DIR = Path(__file__).parent / "fixtures"
FIXTURE_PATH = FIXTURE_DIR / "validate-deploy-status.md"
EXPECTED_PATH = FIXTURE_DIR / "validate-deploy-status.expected.md"


def test_fixture_loads():
    """Test that the fixture loads without raising and has correct tier."""
    doc = load(FIXTURE_PATH)
    assert doc.tier == "contract", f"Expected tier='contract', got tier='{doc.tier}'"
    assert len(doc.outputs) > 0, "Contract-tier doc must declare at least one output"


def test_render_matches_expected():
    """Test that render output matches the golden file byte-for-byte."""
    doc = load(FIXTURE_PATH)
    render_output = render(doc, {"issue": "GW-5189"})

    # Read expected output with explicit encoding
    expected_output = EXPECTED_PATH.read_text(encoding="utf-8")

    # Direct string equality — no strip/rstrip to catch trailing-newline divergence
    assert render_output == expected_output, (
        "Render output does not match expected golden file. "
        "If this is intentional, regenerate the golden file."
    )


def test_render_deterministic_10x():
    """Test that 10 consecutive renders produce identical output."""
    doc = load(FIXTURE_PATH)
    outputs = [render(doc, {"issue": "GW-5189"}) for _ in range(10)]

    # All outputs must be identical to the first
    assert all(out == outputs[0] for out in outputs), (
        "Render is non-deterministic: 10 runs produced different outputs"
    )


def test_render_substitutes_issue_key():
    """Test that {% $inputs.issue %} is substituted correctly."""
    doc = load(FIXTURE_PATH)
    output = render(doc, {"issue": "GW-5189"})

    # Substitution occurred
    assert "GW-5189" in output, "Expected 'GW-5189' in rendered output"

    # No unsubstituted template variables remain
    assert "{% $inputs.issue %}" not in output, (
        "Unsubstituted variable {% $inputs.issue %} found in output"
    )


def test_render_appends_output_contract():
    """Test that OUTPUT CONTRACT block is appended for contract-tier docs."""
    doc = load(FIXTURE_PATH)
    output = render(doc, {"issue": "GW-5189"})

    # OUTPUT CONTRACT heading present
    assert "## OUTPUT CONTRACT" in output, "Expected OUTPUT CONTRACT heading in output"

    # All declared outputs listed
    for out_decl in doc.outputs:
        assert out_decl.name in output, (
            f"Expected output '{out_decl.name}' to appear in OUTPUT CONTRACT"
        )


def test_render_mode_a_run_shape():
    """Test that {% run skill="..." %} renders in Mode-A format."""
    doc = load(FIXTURE_PATH)
    output = render(doc, {"issue": "GW-5189"})

    # Mode-A run node produces "Call the {skill} skill:" heading
    assert "Call the issues/get_issue skill:" in output, (
        "Expected Mode-A run heading 'Call the issues/get_issue skill:' in output"
    )

    # Mode-A run node produces bash code block with npx tsx invocation
    assert "npx tsx ~/.claude/skills/issues/get_issue.ts" in output, (
        "Expected Mode-A bash invocation in output"
    )
