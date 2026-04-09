#!/usr/bin/env python3
"""
Hook Loader — thin wrapper that adds circuit breaker and time budget
to Claude Code hooks without reimplementing the matcher system.

Usage (from settings.json):
  python3 ~/.claude/hooks/hook-loader.py <hook-name>

The loader:
  1. Reads hook config from manifest.json
  2. Checks circuit breaker (auto-disables after N failures)
  3. Checks session time budget
  4. Delegates to the actual hook file in hooks/ directory
  5. Passes stdin through, returns stdout (the JSON decision)
  6. Records success/failure for circuit breaker

State is stored in ~/.claude/cache/hook-state.json (reset per session).
"""

import json
import os
import select
import subprocess
import sys
import time
from pathlib import Path

HOOKS_DIR = Path(__file__).parent
MANIFEST_PATH = HOOKS_DIR / "manifest.json"
STATE_PATH = Path.home() / ".claude" / "cache" / "hook-state.json"

# Defaults
DEFAULT_TIMEOUT_S = 10
MAX_FAILURES = 3
TIME_BUDGET_MS = 30000  # 30s total hook time per session


def load_manifest():
    try:
        with open(MANIFEST_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"hooks": {}}


def load_state():
    try:
        with open(STATE_PATH) as f:
            state = json.load(f)
        # Reset state if session changed (file older than 1 hour)
        mtime = os.path.getmtime(STATE_PATH)
        if time.time() - mtime > 3600:
            return new_state()
        return state
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return new_state()


def new_state():
    return {
        "failures": {},
        "total_time_ms": 0,
        "started": time.time(),
    }


def save_state(state):
    try:
        os.makedirs(STATE_PATH.parent, exist_ok=True)
        with open(STATE_PATH, "w") as f:
            json.dump(state, f)
    except OSError:
        pass


def allow():
    """Default: allow the tool use (PreToolUse/PostToolUse only).
    Exit 0 with no output = implicit allow. Avoids spurious 'hook error'
    labels in the Claude Code UI caused by any hook stdout output.
    """
    pass


def noop():
    """Silent success for lifecycle hooks (SessionStart/SessionEnd)."""
    pass


# Hook events where {"decision":"allow"} is invalid
# Events where {"decision":"allow"} is NOT a valid response.
# Only PreToolUse and PostToolUse accept {"decision":"allow"/"block"}.
# All other events (UserPromptSubmit, Notification, SessionStart, SessionEnd)
# should produce no output (noop) when allowing.
DECISION_EVENTS = {"PreToolUse", "PostToolUse"}
LIFECYCLE_EVENTS = {"SessionStart", "SessionEnd"}  # kept for reference


DEBUG_LOG = Path.home() / ".claude" / "cache" / "hook-loader-trace.log"


def _trace(msg):
    """Append a debug line — remove once hook errors are resolved."""
    try:
        with open(DEBUG_LOG, "a") as f:
            f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
    except Exception:
        pass


def main():
    if len(sys.argv) < 2:
        return

    hook_name = sys.argv[1]

    # Read stdin (Claude Code hook input) — we'll pass it through.
    # Use select() with short timeout to avoid blocking if stdin isn't piped.
    try:
        if select.select([sys.stdin], [], [], 0.5)[0]:
            stdin_data = sys.stdin.read()
        else:
            stdin_data = "{}"
    except Exception:
        stdin_data = "{}"

    # Detect hook event type — only PreToolUse/PostToolUse accept {"decision":"allow"}
    # All other events (UserPromptSubmit, Notification, SessionStart, SessionEnd)
    # must produce no output when allowing.
    try:
        hook_event = json.loads(stdin_data).get("hook_event_name", "")
    except (json.JSONDecodeError, AttributeError):
        hook_event = ""
    is_decision_event = hook_event in DECISION_EVENTS
    skip = allow if is_decision_event else noop

    _trace(f"ENTER hook={hook_name} event={hook_event} is_decision={is_decision_event} stdin_len={len(stdin_data)}")

    # Load manifest and state
    manifest = load_manifest()
    state = load_state()
    hook_config = manifest.get("hooks", {}).get(hook_name)

    if not hook_config:
        # Hook not in manifest — run it directly as a fallback
        # This handles hooks that haven't been added to manifest yet
        hook_file = HOOKS_DIR / f"{hook_name}.py"
        if not hook_file.exists():
            hook_file = HOOKS_DIR / f"{hook_name}.sh"
        if not hook_file.exists():
            skip()
            return
        hook_config = {
            "file": hook_file.name,
            "timeout": DEFAULT_TIMEOUT_S,
        }

    # --- Circuit breaker check ---
    failures = state.get("failures", {}).get(hook_name, 0)
    max_failures = hook_config.get("max_failures", MAX_FAILURES)
    if failures >= max_failures:
        # Hook is tripped — skip it silently
        skip()
        return

    # --- Time budget check ---
    total_time = state.get("total_time_ms", 0)
    budget = manifest.get("time_budget_ms", TIME_BUDGET_MS)
    if total_time >= budget:
        skip()
        return

    # --- Resolve hook file ---
    hook_file = hook_config.get("file", f"{hook_name}.py")
    hook_path = HOOKS_DIR / hook_file

    if not hook_path.exists():
        # Try with .py extension
        hook_path = HOOKS_DIR / f"{hook_name}.py"
    if not hook_path.exists():
        hook_path = HOOKS_DIR / f"{hook_name}.sh"
    if not hook_path.exists():
        skip()
        return

    # --- Determine interpreter ---
    timeout_s = hook_config.get("timeout", DEFAULT_TIMEOUT_S)
    if hook_path.suffix == ".py":
        cmd = ["python3", str(hook_path)]
    elif hook_path.suffix == ".sh":
        cmd = ["bash", str(hook_path)]
    else:
        cmd = [str(hook_path)]

    # --- Execute ---
    start = time.monotonic()
    try:
        proc = subprocess.run(
            cmd,
            input=stdin_data,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
        elapsed_ms = (time.monotonic() - start) * 1000

        # Update time budget
        state.setdefault("failures", {})
        state["total_time_ms"] = total_time + elapsed_ms

        _trace(f"  {hook_name} exit={proc.returncode} stdout={proc.stdout.strip()[:100]} stderr={proc.stderr.strip()[:100]} elapsed={elapsed_ms:.0f}ms")

        if proc.returncode != 0:
            # Record failure
            state["failures"][hook_name] = failures + 1
            save_state(state)

            # On failure, default to allow/noop (don't block on broken hooks)
            stderr_msg = proc.stderr.strip()[:200] if proc.stderr else ""
            if stderr_msg:
                print(
                    f"hook-loader: {hook_name} failed (attempt {failures + 1}/{max_failures}): {stderr_msg}",
                    file=sys.stderr,
                )
            _trace(f"  {hook_name} FAILED → skip()")
            skip()
            return

        # Success — reset failure count
        state["failures"][hook_name] = 0
        save_state(state)

        # Pass through the hook's stderr (guidance/log messages)
        if proc.stderr and proc.stderr.strip():
            print(proc.stderr.strip(), file=sys.stderr)

        # Pass through the hook's stdout (the JSON decision or result)
        output = proc.stdout.strip()
        if output:
            try:
                parsed = json.loads(output)
                if is_decision_event and isinstance(parsed, dict):
                    # Translate legacy {"continue":true} to {"decision":"allow"}
                    # for PreToolUse/PostToolUse hooks (Claude Code requirement)
                    if "continue" in parsed and "decision" not in parsed:
                        if parsed["continue"]:
                            _trace(f"  {hook_name} TRANSLATE continue→allow (silent)")
                            # No output — exit 0 is implicit allow
                        else:
                            _trace(f"  {hook_name} TRANSLATE continue=false→block")
                            print(json.dumps({"decision": "block", "reason": parsed.get("reason", "blocked by hook")}))
                    elif "error" in parsed and "decision" not in parsed:
                        _trace(f"  {hook_name} TRANSLATE error→block")
                        print(json.dumps({"decision": "block", "reason": parsed["error"]}))
                    else:
                        # Suppress explicit {"decision":"allow"} — silent exit 0 is equivalent
                        if parsed.get("decision") == "allow":
                            _trace(f"  {hook_name} PASSTHROUGH allow→silent")
                        else:
                            _trace(f"  {hook_name} PASSTHROUGH: {output[:80]}")
                            print(output)
                else:
                    # Non-decision events (UserPromptSubmit, SessionStart, etc.)
                    # Suppress legacy {"continue":true} — these events expect no output
                    if isinstance(parsed, dict) and "continue" in parsed:
                        noop()
                    else:
                        print(output)
            except json.JSONDecodeError:
                if is_decision_event:
                    print(output)
                # Non-decision events: suppress malformed output
        else:
            skip()

    except subprocess.TimeoutExpired:
        elapsed_ms = (time.monotonic() - start) * 1000
        state.setdefault("failures", {})
        state["failures"][hook_name] = failures + 1
        state["total_time_ms"] = total_time + elapsed_ms
        save_state(state)
        print(f"hook-loader: {hook_name} timed out after {timeout_s}s", file=sys.stderr)
        skip()

    except Exception as e:
        state.setdefault("failures", {})
        state["failures"][hook_name] = failures + 1
        save_state(state)
        print(f"hook-loader: {hook_name} error: {e}", file=sys.stderr)
        skip()


if __name__ == "__main__":
    main()
