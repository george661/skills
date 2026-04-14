#!/usr/bin/env python3
"""
PreToolUse hook that checks for P1 alerts from the heartbeat engine.

Reads ~/.claude/second-brain/alerts.json and if fresh P1 alerts exist,
blocks the tool call with an alert message so the user is notified.

Staleness: alerts older than 5 minutes are ignored.
"""

import json
import time
from pathlib import Path
from typing import Any, Dict

ALERTS_FILE = Path.home() / ".claude" / "second-brain" / "alerts.json"
STALENESS_THRESHOLD_S = 300  # 5 minutes


def check_alerts() -> Dict[str, Any]:
    """Check for fresh P1 alerts.

    Returns:
        Hook result dict. If alerts found, blocks with a message.
        Otherwise allows the tool call to proceed.
    """
    if not ALERTS_FILE.exists():
        return {"proceed": True}

    try:
        with open(ALERTS_FILE, "r") as f:
            alerts_data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"proceed": True}

    # Check staleness
    timestamp = alerts_data.get("timestamp", "")
    if not timestamp:
        return {"proceed": True}

    # Parse ISO timestamp to epoch
    try:
        from datetime import datetime

        if timestamp.endswith("Z"):
            timestamp = timestamp[:-1] + "+00:00"
        dt = datetime.fromisoformat(timestamp)
        alert_epoch = dt.timestamp()
    except (ValueError, TypeError):
        # Try epoch int
        try:
            alert_epoch = float(timestamp)
        except (ValueError, TypeError):
            return {"proceed": True}

    age = time.time() - alert_epoch
    if age > STALENESS_THRESHOLD_S:
        return {"proceed": True}

    # Check for P1 alerts (key is p1_alerts, not alerts)
    p1_alerts = alerts_data.get("p1_alerts", [])
    if not p1_alerts:
        return {"proceed": True}

    # Format alert summary
    alert_lines = [f"⚠ {len(p1_alerts)} P1 ALERT(S) from heartbeat:"]
    for alert in p1_alerts[:3]:  # Show max 3
        alert_type = alert.get("type", "unknown")
        integration = alert.get("integration", "unknown")
        synthesis = alert.get("synthesis", "No details")
        alert_lines.append(f"  [{alert_type}] {integration}: {synthesis[:100]}")

    if len(p1_alerts) > 3:
        alert_lines.append(f"  ... and {len(p1_alerts) - 3} more")

    return {
        "proceed": False,
        "reason": "\n".join(alert_lines),
    }


def main() -> None:
    """Hook entry point."""
    result = check_alerts()
    print(json.dumps(result))


if __name__ == "__main__":
    main()
