#!/usr/bin/env python3
"""
Memory Integration Utilities

Provides pre-execution and post-execution memory operations
for use in workflow commands.
"""

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


def get_workspace_root() -> Path:
    """Get workspace root from environment or current directory"""
    return Path(os.environ.get("WORKSPACE_ROOT", os.getcwd()))


def get_tenant_namespace() -> str:
    """Get tenant namespace from environment"""
    return os.environ.get("TENANT_NAMESPACE", "${TENANT_NAMESPACE}")


def pattern_search(task: str, k: int = 5) -> List[Dict[str, Any]]:
    """
    Search AgentDB for relevant patterns before command execution.

    Args:
        task: Task description to search for
        k: Number of results to return

    Returns:
        List of matching patterns
    """
    skill_path = get_workspace_root() / ".claude" / "skills" / "agentdb" / "pattern_search.ts"

    if not skill_path.exists():
        return []

    try:
        result = subprocess.run(
            ["npx", "tsx", str(skill_path), json.dumps({"task": task, "k": k})],
            capture_output=True,
            text=True,
            cwd=str(get_workspace_root()),
            timeout=30
        )

        if result.returncode == 0:
            return json.loads(result.stdout).get("results", [])
    except (subprocess.TimeoutExpired, json.JSONDecodeError, Exception):
        pass

    return []


def retrieve_relevant_episodes(task: str, k: int = 3) -> List[Dict[str, Any]]:
    """
    Retrieve relevant episodes from prior executions.

    Args:
        task: Task description to search for
        k: Number of results to return

    Returns:
        List of matching episodes
    """
    skill_path = get_workspace_root() / ".claude" / "skills" / "agentdb" / "reflexion_retrieve_relevant.ts"

    if not skill_path.exists():
        return []

    try:
        result = subprocess.run(
            ["npx", "tsx", str(skill_path), json.dumps({"task": task, "k": k})],
            capture_output=True,
            text=True,
            cwd=str(get_workspace_root()),
            timeout=30
        )

        if result.returncode == 0:
            return json.loads(result.stdout).get("results", [])
    except (subprocess.TimeoutExpired, json.JSONDecodeError, Exception):
        pass

    return []


def store_episode(
    task: str,
    reward: float,
    success: bool,
    critique: str,
    metadata: Optional[Dict[str, Any]] = None
) -> bool:
    """
    Store episode after command execution.

    Args:
        task: Task identifier
        reward: Success score (0.0 - 1.0)
        success: Whether task succeeded
        critique: Self-reflection text
        metadata: Additional metadata

    Returns:
        True if stored successfully
    """
    skill_path = get_workspace_root() / ".claude" / "skills" / "agentdb" / "reflexion_store_episode.ts"

    if not skill_path.exists():
        return False

    episode_data = {
        "session_id": get_tenant_namespace(),
        "task": task,
        "reward": reward,
        "success": success,
        "critique": critique,
        "metadata": metadata or {}
    }

    # Add timestamp
    episode_data["metadata"]["stored_at"] = datetime.now(timezone.utc).isoformat()

    try:
        result = subprocess.run(
            ["npx", "tsx", str(skill_path), json.dumps(episode_data)],
            capture_output=True,
            text=True,
            cwd=str(get_workspace_root()),
            timeout=30
        )

        return result.returncode == 0
    except (subprocess.TimeoutExpired, Exception):
        return False


def store_pattern(
    task_type: str,
    approach: str,
    success_rate: float,
    metadata: Optional[Dict[str, Any]] = None
) -> bool:
    """
    Store a learned pattern.

    Args:
        task_type: Type of task this pattern applies to
        approach: Description of the approach
        success_rate: Success rate of this approach
        metadata: Additional metadata

    Returns:
        True if stored successfully
    """
    skill_path = get_workspace_root() / ".claude" / "skills" / "agentdb" / "pattern_store.ts"

    if not skill_path.exists():
        return False

    pattern_data = {
        "taskType": task_type,
        "approach": approach,
        "successRate": success_rate,
        "metadata": metadata or {}
    }

    try:
        result = subprocess.run(
            ["npx", "tsx", str(skill_path), json.dumps(pattern_data)],
            capture_output=True,
            text=True,
            cwd=str(get_workspace_root()),
            timeout=30
        )

        return result.returncode == 0
    except (subprocess.TimeoutExpired, Exception):
        return False


def pre_command_memory_search(command: str, context: str) -> Dict[str, Any]:
    """
    Execute pre-command memory search.

    Call at the beginning of each command to retrieve relevant patterns.

    Args:
        command: Command name (e.g., "plan", "validate-plan")
        context: Additional context (e.g., Epic key, task description)

    Returns:
        Dict with patterns and episodes
    """
    search_task = f"{command} {context}"

    return {
        "patterns": pattern_search(search_task, k=5),
        "episodes": retrieve_relevant_episodes(search_task, k=3)
    }


def post_command_reflection(
    command: str,
    context: str,
    success: bool,
    details: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> bool:
    """
    Execute post-command self-reflection and storage.

    Call at the end of each command to store the outcome.

    Args:
        command: Command name
        context: Task context (e.g., Epic key)
        success: Whether command succeeded
        details: Additional details about outcome
        metadata: Additional metadata to store

    Returns:
        True if stored successfully
    """
    task = f"{command}:{context}"
    reward = 0.9 if success else 0.3

    critique_parts = [f"Command {command} {'completed successfully' if success else 'failed'}."]
    if details:
        critique_parts.append(details)

    return store_episode(
        task=task,
        reward=reward,
        success=success,
        critique=" ".join(critique_parts),
        metadata={
            "command": command,
            "context": context,
            **(metadata or {})
        }
    )


# Test execution
if __name__ == "__main__":
    print("Testing memory integration...")

    # Test pre-command search
    results = pre_command_memory_search("plan", "test-epic")
    print(f"Pre-command search: {len(results.get('patterns', []))} patterns, {len(results.get('episodes', []))} episodes")

    # Test post-command reflection
    success = post_command_reflection(
        command="test",
        context="memory-integration-test",
        success=True,
        details="Memory integration test completed"
    )
    print(f"Post-command reflection stored: {success}")
