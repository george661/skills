#!/usr/bin/env python3
"""
Session-end hook for self-reflection and pattern learning.

Triggers on:
- /clear command (via PreUserPromptSubmit)
- Claude Code exit (via atexit handler)
- SIGTERM/SIGINT signals

Stores session metrics and learned patterns to AgentDB.
"""

import atexit
import json
import os
import signal
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

# Import shared AgentDB client
AGENTDB_CLIENT_AVAILABLE = False
try:
    from agentdb_client import store_episode as _store_episode_client, store_pattern as _store_pattern_client
    AGENTDB_CLIENT_AVAILABLE = True
except ImportError:
    pass


def store_episode(session_id: str, task: str, reward: float, success: bool,
                  trajectory: list = None, namespace: str = None, **kwargs) -> bool:
    """Store episode - uses agentdb_client if available, else REST skill"""
    if AGENTDB_CLIENT_AVAILABLE:
        return _store_episode_client(session_id, task, reward, success, trajectory, namespace)

    # Fallback to REST skill
    skill_path = Path(__file__).parent.parent / "skills" / "agentdb" / "reflexion_store_episode.ts"
    if skill_path.exists():
        data = {
            "session_id": session_id,
            "task": task,
            "reward": reward,
            "success": success,
            "trajectory": trajectory or [],
            "namespace": namespace or os.environ.get("TENANT_NAMESPACE", "${TENANT_NAMESPACE}")
        }
        data.update(kwargs)  # Include any additional metadata
        subprocess.run(
            ["npx", "tsx", str(skill_path), json.dumps(data)],
            capture_output=True,
            cwd=os.environ.get("WORKSPACE_ROOT", os.getcwd())
        )
        return True
    return False


def store_pattern(pattern_type: str, pattern: Dict[str, Any], namespace: str = None) -> bool:
    """Store pattern - uses agentdb_client if available, else REST skill"""
    if AGENTDB_CLIENT_AVAILABLE:
        return _store_pattern_client(pattern_type, pattern, namespace)

    # Fallback to REST skill
    skill_path = Path(__file__).parent.parent / "skills" / "agentdb" / "pattern_store.ts"
    if skill_path.exists():
        data = {
            "pattern_type": pattern_type,
            "pattern": pattern,
            "namespace": namespace or os.environ.get("TENANT_NAMESPACE", "${TENANT_NAMESPACE}")
        }
        subprocess.run(
            ["npx", "tsx", str(skill_path), json.dumps(data)],
            capture_output=True,
            cwd=os.environ.get("WORKSPACE_ROOT", os.getcwd())
        )
        return True
    return False


class SessionEndHandler:
    """Handles session end self-reflection"""

    def __init__(self):
        self.session_id = os.environ.get("SESSION_ID", f"session-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}")
        self.tenant_namespace = os.environ.get("TENANT_NAMESPACE", "${TENANT_NAMESPACE}")
        self.commands_executed = []
        self.successes = 0
        self.failures = 0
        self.patterns_learned = []
        self._registered = False

    def register_handlers(self):
        """Register atexit and signal handlers"""
        if self._registered:
            return

        atexit.register(self.on_session_end)
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        self._registered = True

    def _signal_handler(self, signum, frame):
        """Handle termination signals"""
        self.on_session_end(f"signal-{signum}")
        sys.exit(0)

    def record_command(self, command: str, success: bool):
        """Record a command execution"""
        self.commands_executed.append({
            "command": command,
            "success": success,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
        if success:
            self.successes += 1
        else:
            self.failures += 1

    def record_pattern(self, pattern: Dict[str, Any]):
        """Record a learned pattern"""
        self.patterns_learned.append(pattern)

    def on_session_end(self, trigger: str = "exit"):
        """Execute self-reflection on session end"""
        if not self.commands_executed:
            return  # No activity to reflect on

        total = self.successes + self.failures
        success_rate = self.successes / total if total > 0 else 0.0

        # Generate self-reflection
        critique = self._generate_critique(success_rate)

        # Build trajectory from executed commands
        trajectory = [
            {
                "action": "command",
                "command": cmd["command"],
                "success": cmd["success"],
                "timestamp": cmd["timestamp"]
            }
            for cmd in self.commands_executed
        ]

        # Store session episode
        try:
            store_episode(
                session_id=self.tenant_namespace,
                task=f"session-end:{self.session_id}",
                reward=success_rate,
                success=success_rate >= 0.8,
                trajectory=trajectory,
                namespace=self.tenant_namespace,
                critique=critique,
                trigger=trigger,
                commands_executed=len(self.commands_executed),
                successes=self.successes,
                failures=self.failures,
                patterns_learned=len(self.patterns_learned),
                ended_at=datetime.now(timezone.utc).isoformat()
            )
        except Exception as e:
            print(f"Warning: Failed to store session episode: {e}", file=sys.stderr)

        # Store any learned patterns
        for pattern in self.patterns_learned:
            try:
                store_pattern(
                    pattern_type=pattern.get("type", "learned"),
                    pattern=pattern,
                    namespace=self.tenant_namespace
                )
            except Exception as e:
                print(f"Warning: Failed to store pattern: {e}", file=sys.stderr)

    def _generate_critique(self, success_rate: float) -> str:
        """Generate self-reflection critique"""
        parts = [
            f"Session completed {len(self.commands_executed)} commands with {success_rate:.0%} success rate."
        ]

        if self.failures > 0:
            failed_commands = [c["command"] for c in self.commands_executed if not c["success"]]
            parts.append(f"Failed commands: {', '.join(failed_commands[:3])}")

        if self.patterns_learned:
            parts.append(f"Learned {len(self.patterns_learned)} new patterns.")

        if success_rate >= 0.9:
            parts.append("High success rate - approaches working well.")
        elif success_rate >= 0.7:
            parts.append("Moderate success - some approaches need refinement.")
        else:
            parts.append("Low success rate - significant improvements needed.")

        return " ".join(parts)


# Global handler instance
_handler: Optional[SessionEndHandler] = None


def get_handler() -> SessionEndHandler:
    """Get or create the session end handler"""
    global _handler
    if _handler is None:
        _handler = SessionEndHandler()
        _handler.register_handlers()
    return _handler


def on_clear_command(context: Dict[str, Any]) -> Dict[str, Any]:
    """Hook callback for /clear command detection"""
    user_input = context.get("user_input", "").strip().lower()

    if user_input == "/clear":
        handler = get_handler()
        handler.on_session_end("clear-command")

    return {"proceed": True}


# Main execution for testing
if __name__ == "__main__":
    handler = get_handler()
    handler.record_command("/plan PROJ-123", True)
    handler.record_command("/validate-plan PROJ-123", True)
    handler.record_command("/groom PROJ-123", False)
    handler.on_session_end("test")
    print("Session end hook test completed")
