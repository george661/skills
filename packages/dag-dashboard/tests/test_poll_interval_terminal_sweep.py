"""GW-5423 AC-6: SSE + REST safety net with terminal-state final sweep.

Static tests — assert app.js uses a 3000ms poll, carries the isTerminal
guard + runTerminalSweep logic, and stops polling on terminal status.
"""
from pathlib import Path

STATIC_DIR = Path(__file__).parents[1] / "src" / "dag_dashboard" / "static"


def test_poll_interval_is_3000ms() -> None:
    """Poll interval must be 3000 (AC-6 measurement point)."""
    js = (STATIC_DIR / "js" / "app.js").read_text()
    # Look for setInterval with 3000 as the interval arg (as a round number,
    # inside setupLiveUpdates).
    assert "3000" in js, "3000ms poll must be present (AC-6)"
    # Make sure the old 2000 isn't lingering as the active interval.
    assert "Poll every 3 seconds" in js or ", 3000)" in js, (
        "setInterval must use 3000ms"
    )


def test_is_terminal_guard_present() -> None:
    """Terminal sweep must be guarded by an isTerminal flag so it fires once."""
    js = (STATIC_DIR / "js" / "app.js").read_text()
    assert "isTerminal" in js, "isTerminal guard required to prevent double-sweep"
    assert "runTerminalSweep" in js, "runTerminalSweep function required"


def test_terminal_sweep_fetches_layout_and_channels() -> None:
    """Final sweep must hit both /layout and /channels (per AC-6 plan)."""
    js = (STATIC_DIR / "js" / "app.js").read_text()
    # The sweep lives inside runTerminalSweep — check its body hits both paths.
    sweep_start = js.find("async function runTerminalSweep")
    assert sweep_start != -1, "runTerminalSweep declaration required"
    sweep_body = js[sweep_start:sweep_start + 2000]
    assert "/layout" in sweep_body, "Sweep must fetch /layout"
    assert "/channels" in sweep_body, "Sweep must fetch /channels"


def test_poll_stops_on_terminal() -> None:
    """Polling must be cleared once terminal state is detected."""
    js = (STATIC_DIR / "js" / "app.js").read_text()
    assert "clearInterval(pollInterval)" in js


def test_lifecycle_exposes_run_status() -> None:
    """Lifecycle object must expose getRunStatus so ChatPanel can re-derive lock."""
    js = (STATIC_DIR / "js" / "app.js").read_text()
    assert "getRunStatus" in js
    assert "setLifecycle" in js, "ChatPanel must receive lifecycle after construction"
