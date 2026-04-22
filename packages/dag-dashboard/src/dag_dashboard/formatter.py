"""Slack Block Kit card builders for workflow lifecycle events.

Each formatter returns a dict of the form::

    {"blocks": [...], "text": "<fallback>"}

ready to be POSTed to either an incoming webhook or `chat.postMessage`. Every
card embeds a "View in Dashboard" action button linking to
``{dashboard_url}/runs/{run_id}``.
"""
from __future__ import annotations

from typing import Any, Dict, List

ERROR_TRUNCATE_CODEPOINTS = 200


def _dashboard_button(dashboard_url: str, run_id: str) -> Dict[str, Any]:
    """Build the 'View in Dashboard' actions block linking to the run."""
    return {
        "type": "actions",
        "elements": [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "View in Dashboard"},
                "url": f"{dashboard_url.rstrip('/')}/runs/{run_id}",
                "action_id": f"view_run_{run_id}",
            }
        ],
    }


def _header(text: str) -> Dict[str, Any]:
    return {"type": "header", "text": {"type": "plain_text", "text": text}}


def _context_fields(fields: List[tuple[str, str]]) -> Dict[str, Any]:
    return {
        "type": "section",
        "fields": [
            {"type": "mrkdwn", "text": f"*{label}*\n{value}"}
            for label, value in fields
        ],
    }


def _truncate_error(error: str) -> str:
    """Truncate error message to ERROR_TRUNCATE_CODEPOINTS codepoints.

    Operates on codepoints (Python str indexing) rather than bytes so multi-byte
    characters are never split. Adds an ellipsis marker when truncated.
    """
    if len(error) <= ERROR_TRUNCATE_CODEPOINTS:
        return error
    return error[:ERROR_TRUNCATE_CODEPOINTS] + "..."


def format_workflow_started(
    workflow_name: str, run_id: str, dashboard_url: str
) -> Dict[str, Any]:
    """Build card for workflow_started event."""
    text = f"Workflow started: {workflow_name} ({run_id})"
    return {
        "text": text,
        "blocks": [
            _header(f":rocket: Workflow started: {workflow_name}"),
            _context_fields([("Run ID", f"`{run_id}`"), ("Status", "Running")]),
            _dashboard_button(dashboard_url, run_id),
        ],
    }


def format_workflow_completed(
    workflow_name: str, run_id: str, duration_ms: int, dashboard_url: str
) -> Dict[str, Any]:
    """Build card for workflow_completed event."""
    duration_s = duration_ms / 1000.0
    text = f"Workflow completed: {workflow_name} ({run_id}) in {duration_s:.2f}s"
    return {
        "text": text,
        "blocks": [
            _header(f":white_check_mark: Workflow completed: {workflow_name}"),
            _context_fields(
                [
                    ("Run ID", f"`{run_id}`"),
                    ("Duration", f"{duration_s:.2f}s"),
                ]
            ),
            _dashboard_button(dashboard_url, run_id),
        ],
    }


def format_workflow_failed(
    workflow_name: str, run_id: str, error: str, dashboard_url: str
) -> Dict[str, Any]:
    """Build card for workflow_failed event.

    ``error`` is truncated to ``ERROR_TRUNCATE_CODEPOINTS`` codepoints.
    """
    truncated = _truncate_error(error)
    text = f"Workflow failed: {workflow_name} ({run_id})"
    return {
        "text": text,
        "blocks": [
            _header(f":x: Workflow failed: {workflow_name}"),
            _context_fields([("Run ID", f"`{run_id}`")]),
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Error*\n```{truncated}```"},
            },
            _dashboard_button(dashboard_url, run_id),
        ],
    }


def format_gate_pending(
    workflow_name: str,
    run_id: str,
    node_name: str,
    condition: str,
    dashboard_url: str,
) -> Dict[str, Any]:
    """Build card for gate_pending event (human approval required)."""
    text = f"Gate pending: {workflow_name} / {node_name}"
    blocks: List[Dict[str, Any]] = [
        _header(f":hourglass: Gate pending: {workflow_name}"),
        _context_fields(
            [("Run ID", f"`{run_id}`"), ("Gate node", f"`{node_name}`")]
        ),
    ]
    if condition:
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Condition*\n`{condition}`"},
            }
        )
    blocks.append(_dashboard_button(dashboard_url, run_id))
    return {"text": text, "blocks": blocks}


def format_approval_resolved(
    workflow_name: str,
    run_id: str,
    node_name: str,
    decision: str,
    decided_by: str,
    source: str,
    dashboard_url: str,
) -> Dict[str, Any]:
    """Build card for approval_resolved event (gate approved/rejected)."""
    emoji = ":white_check_mark:" if decision == "approved" else ":x:"
    text = f"Gate {decision}: {workflow_name} / {node_name}"
    blocks: List[Dict[str, Any]] = [
        _header(f"{emoji} Gate {decision}: {workflow_name}"),
        _context_fields(
            [
                ("Run ID", f"`{run_id}`"),
                ("Gate node", f"`{node_name}`"),
                ("Decided by", decided_by),
                ("Source", source),
            ]
        ),
    ]
    blocks.append(_dashboard_button(dashboard_url, run_id))
    return {"text": text, "blocks": blocks}
