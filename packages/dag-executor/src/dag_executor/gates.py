"""Gate management utilities for CLI and API."""
from datetime import datetime, timezone
from typing import Any, Dict, Optional


def build_approval_resolved_event(
    run_id: str,
    node_id: str,
    decision: str,
    decided_by: str,
    source: str,
    resume_key: Optional[str] = None,
    resume_value: Optional[bool] = None,
    comment: Optional[str] = None,
) -> Dict[str, Any]:
    """Build canonical approval_resolved event.

    Args:
        run_id: Workflow run ID
        node_id: Node name/ID
        decision: "approved" or "rejected"
        decided_by: User/system identifier
        source: "cli", "api", or "slack"
        resume_key: Resume key for interrupt nodes (None for gate-type nodes)
        resume_value: True for approved, False for rejected (None for gate-type nodes)
        comment: Optional comment

    Returns:
        Event dict matching the canonical shape
    """
    now = datetime.now(timezone.utc).isoformat()

    return {
        "event_type": "approval_resolved",
        "payload": {
            "run_id": run_id,
            "node_id": node_id,
            "resume_key": resume_key,
            "decision": decision,
            "resume_value": resume_value,
            "decided_by": decided_by,
            "decided_at": now,
            "comment": comment,
            "source": source,
        },
        "created_at": now,
    }


def emit_approval_resolved_ndjson(
    events_file: str,
    run_id: str,
    node_id: str,
    decision: str,
    decided_by: str,
    source: str,
    resume_key: Optional[str] = None,
    resume_value: Optional[bool] = None,
    comment: Optional[str] = None,
) -> None:
    """Write approval_resolved event to NDJSON file.

    Args:
        events_file: Path to {events_dir}/{run_id}.ndjson
        run_id: Workflow run ID
        node_id: Node name/ID
        decision: "approved" or "rejected"
        decided_by: User/system identifier
        source: "cli", "api", or "slack"
        resume_key: Resume key for interrupt nodes
        resume_value: True for approved, False for rejected
        comment: Optional comment
    """
    import json
    from pathlib import Path

    event = build_approval_resolved_event(
        run_id=run_id,
        node_id=node_id,
        decision=decision,
        decided_by=decided_by,
        source=source,
        resume_key=resume_key,
        resume_value=resume_value,
        comment=comment,
    )

    # Append to NDJSON file
    Path(events_file).parent.mkdir(parents=True, exist_ok=True)
    with open(events_file, "a") as f:
        f.write(json.dumps(event) + "\n")
