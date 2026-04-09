#!/usr/bin/env python3
"""
SessionEnd / PreCompact transcript capture hook.

Delegates to second-brain's transcript.py and flush.py when installed.
Reads session_id and transcript_path from stdin JSON, extracts turns,
checks dedup/min-turn thresholds, writes pending file, and spawns
background flush process.

Recursion guard: skips if CLAUDE_INVOKED_BY is set (prevents flush.py
Agent SDK -> Claude Code -> hook -> flush.py loops).
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Optional

# Min turn thresholds per hook event
MIN_TURNS = {
    "SessionEnd": 3,
    "PreCompact": 5,
}


def find_second_brain() -> Optional[Path]:
    """Find the second-brain installation path.

    Checks for second-brain as a pip-installed package first,
    then falls back to known workspace locations.

    Returns:
        Path to second-brain src directory, or None if not found.
    """
    # Check if installed as package (importable)
    try:
        import src.compiler.transcript  # noqa: F401
        import src.compiler.flush  # noqa: F401
        # Package is importable, return its parent
        return Path(src.compiler.transcript.__file__).parent.parent.parent
    except ImportError:
        pass

    # Check known workspace locations
    workspace_root = os.environ.get(
        "WORKSPACE_ROOT",
        os.environ.get("PROJECT_ROOT", ""),
    )
    if workspace_root:
        candidate = Path(workspace_root) / "second-brain"
        if (candidate / "src" / "compiler" / "transcript.py").exists():
            return candidate

    # Check home directory
    home_candidate = Path.home() / "dev" / "${TENANT_NAMESPACE}" / "second-brain"
    if (home_candidate / "src" / "compiler" / "transcript.py").exists():
        return home_candidate

    return None


def run_transcript_capture(
    hook_event: str,
    session_id: str,
    transcript_path: str,
) -> Dict[str, Any]:
    """Run transcript capture using second-brain's compiler modules.

    Args:
        hook_event: The hook event name (SessionEnd or PreCompact).
        session_id: Claude Code session ID.
        transcript_path: Path to the JSONL transcript file.

    Returns:
        Result dict with status and optional message.
    """
    # Recursion guard
    if os.environ.get("CLAUDE_INVOKED_BY"):
        return {"status": "skipped", "reason": "recursion guard"}

    # Find second-brain
    sb_path = find_second_brain()
    if not sb_path:
        return {"status": "skipped", "reason": "second-brain not installed"}

    # Verify transcript file exists
    if not Path(transcript_path).exists():
        return {"status": "skipped", "reason": "transcript file not found"}

    # Add second-brain to sys.path for imports
    sys.path.insert(0, str(sb_path))

    try:
        from src.compiler.transcript import (
            extract_turns,
            should_flush,
            turns_to_markdown,
            write_pending,
        )
    except ImportError as e:
        return {"status": "error", "reason": f"import failed: {e}"}

    # Get min turns threshold for this event
    min_turns = MIN_TURNS.get(hook_event, 3)

    # Extract turns from transcript
    turns = extract_turns(transcript_path, max_turns=30)

    if len(turns) < min_turns:
        return {
            "status": "skipped",
            "reason": f"insufficient turns ({len(turns)} < {min_turns})",
        }

    # Check dedup window
    if not should_flush(session_id, min_turns=min_turns, dedup_window_s=60):
        return {"status": "skipped", "reason": "within dedup window"}

    # Convert to markdown and write pending file
    markdown = turns_to_markdown(turns, max_chars=15000)
    pending_path = write_pending(session_id, markdown)

    # Spawn background flush process
    flush_script = sb_path / "src" / "compiler" / "flush.py"
    if flush_script.exists():
        env = os.environ.copy()
        env["CLAUDE_INVOKED_BY"] = "second-brain-flush"
        try:
            subprocess.Popen(
                [sys.executable, str(flush_script), pending_path],
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except Exception as e:
            print(
                f"Warning: Failed to spawn flush process: {e}",
                file=sys.stderr,
            )

    return {
        "status": "captured",
        "turns": len(turns),
        "pending_path": pending_path,
    }


def main() -> None:
    """Hook entry point — reads stdin JSON and runs transcript capture."""
    try:
        input_data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        input_data = {}

    hook_event = input_data.get("hook_event_name", "SessionEnd")
    session_id = input_data.get("session_id", "unknown")
    transcript_path = input_data.get("transcript_path", "")

    result = run_transcript_capture(hook_event, session_id, transcript_path)

    # Output result as JSON for hook-loader
    print(json.dumps(result))


if __name__ == "__main__":
    main()
