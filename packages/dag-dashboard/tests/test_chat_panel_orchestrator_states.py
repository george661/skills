"""GW-5492 AC-6/AC-7: workflow-level orchestrator chat UI state machine.

Static tests — assert chat-panel.js carries the 4-state truth table, the
streaming-token append path, and the new SSE event dispatcher; and that
app.js forwards orchestrator_ready / orchestrator_stopped / chat_message_token
into the panel.

Follows the same static-assertion pattern as test_chat_panel_lock_static.py.
"""
from pathlib import Path

STATIC_DIR = Path(__file__).parents[1] / "src" / "dag_dashboard" / "static"


def _chat_panel_js() -> str:
    return (STATIC_DIR / "js" / "chat-panel.js").read_text()


def _app_js() -> str:
    return (STATIC_DIR / "js" / "app.js").read_text()


def test_chat_panel_exposes_recompute_input_state() -> None:
    """The 4-state machine must be implemented as _recomputeInputState."""
    js = _chat_panel_js()
    assert "_recomputeInputState" in js


def test_chat_panel_tracks_orchestrator_alive_state() -> None:
    """State flag must be tracked so the machine has something to branch on."""
    js = _chat_panel_js()
    assert "_orchestratorAlive" in js


def test_chat_panel_hints_cover_all_four_states() -> None:
    """AC-6 enumerates four hint-text outcomes. Each must appear verbatim."""
    js = _chat_panel_js()
    # prompt-node-running → "Agent is thinking…" (preserved from GW-5423 AC-7)
    assert "Agent is thinking…" in js
    # no prompt + offline → "Reconnecting orchestrator…"
    assert "Reconnecting orchestrator…" in js
    # run terminal → "Orchestrator available for post-mortem questions."
    assert "Orchestrator available for post-mortem questions." in js
    # no prompt + alive has no hint text; the absence is covered by the
    # state-machine branch that clears the hint element.


def test_chat_panel_prompt_lock_wins_over_orchestrator_hint() -> None:
    """AC-9: prompt-node lock must short-circuit the orchestrator hint path."""
    js = _chat_panel_js()
    # The recompute method must guard on _lockingNodeId before mutating state.
    # Assert that both the method and the guard string appear in that order.
    recompute_start = js.index("_recomputeInputState")
    guard_idx = js.find("_lockingNodeId", recompute_start)
    assert guard_idx != -1, "guard must appear inside _recomputeInputState"


def test_chat_panel_routes_sse_events_by_type() -> None:
    """handleSSEMessage must branch on payload.type for the new events."""
    js = _chat_panel_js()
    for event_type in (
        "'orchestrator_ready'",
        "'orchestrator_stopped'",
        "'chat_message_token'",
    ):
        assert event_type in js, f"handleSSEMessage must handle {event_type}"


def test_chat_panel_streams_tokens_into_assistant_bubble() -> None:
    """AC-7: tokens must accumulate into a streaming assistant message."""
    js = _chat_panel_js()
    assert "_appendStreamingToken" in js
    assert "chat-message--streaming" in js
    # Tokens use textContent (not innerHTML) during streaming to avoid
    # injection via partial markup; the final message re-renders via marked.
    recompute_idx = js.index("_appendStreamingToken")
    # Assert textContent is used downstream of _appendStreamingToken.
    assert "textContent" in js[recompute_idx:recompute_idx + 2000]


def test_chat_panel_fetches_status_endpoint_on_mount() -> None:
    """AC-6: the panel must converge on real state via /orchestrator/status."""
    js = _chat_panel_js()
    assert "/orchestrator/status" in js
    assert "_fetchOrchestratorStatus" in js


def test_app_js_seeds_status_and_forwards_events() -> None:
    """app.js must forward the new SSE event types + seed initial status."""
    js = _app_js()
    # Status fetch is kicked off alongside ChatPanel construction.
    assert "/orchestrator/status" in js
    # SSE dispatcher branches on the new event types.
    assert "'chat_message_token'" in js
    assert "'orchestrator_ready'" in js
    assert "'orchestrator_stopped'" in js
