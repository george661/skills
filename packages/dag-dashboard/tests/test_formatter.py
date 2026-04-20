"""Tests for Slack Block Kit formatter functions.

Uses committed JSON fixtures in ``tests/fixtures/slack_cards/`` as snapshot
targets. Each test builds a card with deterministic inputs and asserts equality
against the corresponding fixture plus the invariants every card must uphold:

- ``text`` fallback non-empty
- ``blocks`` list non-empty
- At least one block is an ``actions`` block containing a button whose ``url``
  points at ``{dashboard_url}/runs/{run_id}``
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

import pytest

from dag_dashboard import formatter

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "slack_cards"
DASHBOARD_URL = "https://dash.example.com"


def _load_fixture(name: str) -> Dict[str, Any]:
    with open(FIXTURES_DIR / name) as f:
        loaded: Dict[str, Any] = json.load(f)
        return loaded


def _assert_card_invariants(card: Dict[str, Any], run_id: str) -> None:
    assert card["text"], "text fallback must be non-empty"
    assert isinstance(card["blocks"], list) and len(card["blocks"]) > 0
    action_blocks = [b for b in card["blocks"] if b.get("type") == "actions"]
    assert action_blocks, "card must include at least one actions block"
    buttons = [
        elem
        for block in action_blocks
        for elem in block.get("elements", [])
        if elem.get("type") == "button"
    ]
    assert buttons, "actions block must contain a button"
    dashboard_buttons = [
        b for b in buttons if b.get("url", "").endswith(f"/runs/{run_id}")
    ]
    assert dashboard_buttons, (
        f"card must include a button linking to /runs/{run_id}, got: {buttons}"
    )


def test_workflow_started_matches_fixture() -> None:
    card = formatter.format_workflow_started(
        "pipeline-a", "run-123", DASHBOARD_URL
    )
    _assert_card_invariants(card, "run-123")
    assert card == _load_fixture("workflow_started.json")


def test_workflow_completed_matches_fixture() -> None:
    card = formatter.format_workflow_completed(
        "pipeline-a", "run-123", 12345, DASHBOARD_URL
    )
    _assert_card_invariants(card, "run-123")
    assert card == _load_fixture("workflow_completed.json")


def test_workflow_failed_short_error_matches_fixture() -> None:
    card = formatter.format_workflow_failed(
        "pipeline-a", "run-123", "Boom: step 3 exited 1", DASHBOARD_URL
    )
    _assert_card_invariants(card, "run-123")
    assert card == _load_fixture("workflow_failed_short_error.json")


def test_workflow_failed_truncates_long_error() -> None:
    long_error = "X" * 500
    card = formatter.format_workflow_failed(
        "pipeline-a", "run-123", long_error, DASHBOARD_URL
    )
    _assert_card_invariants(card, "run-123")

    error_section = next(
        b
        for b in card["blocks"]
        if b.get("type") == "section" and "Error" in b.get("text", {}).get("text", "")
    )
    error_text = error_section["text"]["text"]
    # Truncated portion should be exactly 200 codepoints + ellipsis marker
    assert "X" * formatter.ERROR_TRUNCATE_CODEPOINTS in error_text
    assert "..." in error_text
    assert "X" * (formatter.ERROR_TRUNCATE_CODEPOINTS + 1) not in error_text

    assert card == _load_fixture("workflow_failed_long_error.json")


def test_workflow_failed_truncation_preserves_codepoints() -> None:
    # Multi-byte character: should truncate by codepoints, not bytes
    long_error = "\u2603" * 500  # snowmen
    card = formatter.format_workflow_failed(
        "pipeline-a", "run-123", long_error, DASHBOARD_URL
    )
    error_section = next(
        b
        for b in card["blocks"]
        if b.get("type") == "section" and "Error" in b.get("text", {}).get("text", "")
    )
    error_text = error_section["text"]["text"]
    assert "\u2603" * formatter.ERROR_TRUNCATE_CODEPOINTS in error_text
    assert "\u2603" * (formatter.ERROR_TRUNCATE_CODEPOINTS + 1) not in error_text


def test_gate_pending_matches_fixture() -> None:
    card = formatter.format_gate_pending(
        "pipeline-a", "run-123", "review-gate", "status == 'approved'", DASHBOARD_URL
    )
    _assert_card_invariants(card, "run-123")
    assert card == _load_fixture("gate_pending.json")


def test_gate_pending_without_condition_omits_condition_block() -> None:
    card = formatter.format_gate_pending(
        "pipeline-a", "run-123", "review-gate", "", DASHBOARD_URL
    )
    _assert_card_invariants(card, "run-123")
    condition_sections = [
        b
        for b in card["blocks"]
        if b.get("type") == "section"
        and "Condition" in b.get("text", {}).get("text", "")
    ]
    assert not condition_sections


@pytest.mark.parametrize(
    "dashboard_url",
    ["https://dash.example.com", "https://dash.example.com/"],
)
def test_trailing_slash_stripped_in_button_url(dashboard_url: str) -> None:
    card = formatter.format_workflow_started("p", "r1", dashboard_url)
    button = card["blocks"][-1]["elements"][0]
    assert button["url"] == "https://dash.example.com/runs/r1"
