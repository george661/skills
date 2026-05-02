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


def test_poll_derives_terminal_from_node_statuses() -> None:
    """Poll-path terminal detection must derive from node statuses, not a
    top-level layoutData.status field (which compute_layout does not emit).
    The AC-6 measurement (kill SSE mid-run → UI terminal within 6s) depends
    on the poll being able to detect terminal state on its own.
    """
    js = (STATIC_DIR / "js" / "app.js").read_text()
    # Must not rely on layoutData.status — layout.py doesn't emit it.
    # Must derive from a named set of node statuses that are NOT yet terminal.
    assert "waitingStatuses" in js or "activeStatuses" in js, (
        "Poll must track the set of non-terminal node statuses"
    )
    # At least the primary active states must be checked.
    assert "'running'" in js and "'pending'" in js


def test_poll_treats_escalated_and_interrupted_as_non_terminal() -> None:
    """escalated / interrupted nodes mean the workflow is paused-for-input,
    not terminal. Treating them as terminal caused the run-detail page to
    stop polling on paused runs — timeline / channels / DAG never refreshed
    after a resume until the user reloaded. The poll must keep running so
    the UI picks up downstream nodes once the user submits a resume value.
    """
    js = (STATIC_DIR / "js" / "app.js").read_text()
    # Find the status set used by the poll-path terminal-sweep heuristic.
    anchor = js.find("waitingStatuses")
    if anchor == -1:
        anchor = js.find("activeStatuses")
    assert anchor != -1, "Poll-path status set not found"
    # Look at the Set literal declaration that follows.
    set_start = js.find("new Set(", anchor)
    set_end = js.find(")", set_start)
    set_literal = js[set_start:set_end]
    assert "'escalated'" in set_literal, (
        "escalated must be treated as non-terminal (paused, awaiting input)"
    )
    assert "'interrupted'" in set_literal, (
        "interrupted must be treated as non-terminal (paused, awaiting input)"
    )
    # Pin that the named set is actually consulted by the terminal-sweep gate,
    # not just declared and then ignored. Look in a window after the Set decl
    # for a `.has(` membership test followed by a `runTerminalSweep()` call
    # inside the same if-block.
    after_decl = js[set_end:set_end + 1000]
    set_name = "waitingStatuses" if "waitingStatuses" in js[anchor:anchor + 50] else "activeStatuses"
    assert f"{set_name}.has(" in after_decl, (
        f"{set_name} must actually be consulted via .has(status) in the "
        "terminal-sweep gate; declaring the set without using it is a no-op."
    )
    assert "runTerminalSweep()" in after_decl, (
        "terminal-sweep gate must call runTerminalSweep() in the same block "
        "that consults the status set"
    )
