#!/usr/bin/env python3
"""
Pattern Retrieval Utility for AgentDB.

Provides functions to retrieve reasoning patterns and past episodes
from AgentDB for use in workflow commands. This closes the self-reinforcing
loop by enabling proactive pattern lookup before command execution.

Usage:
    from pattern_retrieval import retrieve_and_format

    context = {'issue_key': 'PROJ-123', 'issue_type': 'Task', 'repo': 'my-service'}
    output = retrieve_and_format('implement', context)

CLI:
    python3 pattern_retrieval.py <command> '{"issue_key": "PROJ-123"}'
"""

import json
import sys
from typing import Dict, List, Any, Optional

# Import from sibling module
from agentdb_client import agentdb_request


def search_patterns(task: str, k: int = 5, threshold: float = 0.6,
                   filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """
    Search AgentDB for reasoning patterns matching a task.

    Args:
        task: Description of the task to search for
        k: Maximum number of patterns to return
        threshold: Minimum similarity threshold (0.0-1.0)
        filters: Optional filters like {'namespace': 'default', 'task_type': 'implement'}

    Returns:
        List of pattern dicts with keys: task_type, pattern, score
        Empty list if AgentDB unavailable or no matches
    """
    try:
        body = {
            'task': task,
            'k': k,
            'threshold': threshold
        }
        if filters:
            body['filters'] = filters

        result = agentdb_request('POST', '/api/v1/pattern/search', body=body)

        if result is None:
            return []

        return result.get('patterns', [])

    except Exception:
        return []


def retrieve_episodes(query: str, k: int = 3, success_only: bool = False,
                     namespace: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Retrieve past episodes from AgentDB reflexion memory.

    Args:
        query: Query string to find relevant episodes
        k: Maximum number of episodes to return
        success_only: If True, only return successful episodes
        namespace: Optional namespace to filter by

    Returns:
        List of episode dicts with keys: session_id, task, reward, success, trajectory
        Empty list if AgentDB unavailable or no matches
    """
    try:
        body = {
            'query': query,
            'k': k,
            'success_only': success_only
        }
        if namespace:
            body['namespace'] = namespace

        result = agentdb_request('POST', '/api/v1/reflexion/retrieve-relevant', body=body)

        if result is None:
            return []

        return result.get('episodes', [])

    except Exception:
        return []


def _generate_recommendations(patterns: List[Dict], episodes: List[Dict]) -> List[str]:
    """
    Generate recommendations from patterns and episodes.

    Args:
        patterns: List of retrieved patterns
        episodes: List of retrieved episodes

    Returns:
        List of recommendation strings
    """
    recommendations = []

    # Extract recommendations from high-scoring patterns
    for pattern in patterns:
        if pattern.get('score', 0) >= 0.8:
            pattern_data = pattern.get('pattern', {})
            if isinstance(pattern_data, dict):
                reasoning = pattern_data.get('reasoning')
                if reasoning:
                    recommendations.append(f"Pattern: {reasoning}")

    # Extract lessons from successful episodes
    for episode in episodes:
        if episode.get('success'):
            trajectory = episode.get('trajectory', [])
            for step in trajectory[:2]:  # First 2 steps only
                if isinstance(step, dict) and step.get('outcome'):
                    recommendations.append(f"Previous: {step.get('action', 'action')} -> {step['outcome']}")

    return recommendations


def retrieve_for_command(command: str, context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Combined retrieval for command execution context.

    Args:
        command: Command name (e.g., 'implement', 'validate', 'work')
        context: Context dict with keys:
            - issue_key: Issue key (e.g., 'PROJ-123')
            - issue_type: Issue type (e.g., 'Task', 'Bug', 'Story')
            - repo: Repository name (e.g., 'my-service')
            - namespace: Memory namespace (e.g., 'default')

    Returns:
        Dict with keys:
            - patterns: List of relevant patterns
            - episodes: List of relevant episodes
            - recommendations: List of recommendation strings
    """
    issue_key = context.get('issue_key', '')
    issue_type = context.get('issue_type', '')
    repo = context.get('repo', '')
    namespace = context.get('namespace')

    # Build search query combining command and context
    search_task = f"{command} {issue_type} {repo}".strip()

    # Search for patterns related to this command type
    patterns = search_patterns(
        task=search_task,
        k=5,
        threshold=0.6,
        filters={'task_type': command} if command else None
    )

    # Retrieve episodes for similar tasks
    episode_query = f"{command} {issue_type}"
    episodes = retrieve_episodes(
        query=episode_query,
        k=3,
        success_only=True,  # Prefer successful examples
        namespace=namespace
    )

    # Generate recommendations from retrieved data
    recommendations = _generate_recommendations(patterns, episodes)

    return {
        'patterns': patterns,
        'episodes': episodes,
        'recommendations': recommendations
    }


def format_patterns_for_output(command: str, context: Dict[str, Any],
                               patterns: List[Dict], episodes: List[Dict],
                               recommendations: List[str]) -> str:
    """
    Format retrieved patterns as markdown for Claude output.

    Args:
        command: Command name
        context: Context dict with issue_key, etc.
        patterns: List of pattern dicts
        episodes: List of episode dicts
        recommendations: List of recommendation strings

    Returns:
        XML-style block string, or empty string if no content
    """
    # Return empty if nothing to show
    if not patterns and not episodes and not recommendations:
        return ''

    issue_key = context.get('issue_key', 'unknown')
    total_count = len(patterns) + len(episodes)

    lines = [
        f'<retrieved-patterns command="{command}" issue="{issue_key}" count="{total_count}">',
        ''
    ]

    # Add recommendations section
    if recommendations:
        lines.append('## Recommendations')
        lines.append('')
        for rec in recommendations:
            lines.append(f'- {rec}')
        lines.append('')

    # Add patterns section
    if patterns:
        lines.append('## Relevant Patterns')
        lines.append('')
        for i, pattern in enumerate(patterns[:3], 1):  # Top 3
            score = pattern.get('score', 0)
            task_type = pattern.get('task_type', 'unknown')
            pattern_data = pattern.get('pattern', {})
            reasoning = pattern_data.get('reasoning', str(pattern_data)[:100])
            lines.append(f'{i}. [{task_type}] (score: {score:.2f}): {reasoning}')
        lines.append('')

    # Add episodes section
    if episodes:
        lines.append('## Similar Past Tasks')
        lines.append('')
        for i, episode in enumerate(episodes[:3], 1):  # Top 3
            task = episode.get('task', 'unknown task')
            success = 'success' if episode.get('success') else 'failed'
            reward = episode.get('reward', 0)
            lines.append(f'{i}. {task} ({success}, reward: {reward:.2f})')
        lines.append('')

    lines.append('</retrieved-patterns>')

    return '\n'.join(lines)


def retrieve_and_format(command: str, context: Dict[str, Any]) -> str:
    """
    Main entry point: retrieve patterns and format for output.

    This combines retrieve_for_command() and format_patterns_for_output()
    into a single call for convenience.

    Args:
        command: Command name (e.g., 'implement')
        context: Context dict with issue_key, issue_type, repo, namespace

    Returns:
        Formatted XML-style block string, or empty string if nothing found
    """
    result = retrieve_for_command(command, context)

    return format_patterns_for_output(
        command=command,
        context=context,
        patterns=result['patterns'],
        episodes=result['episodes'],
        recommendations=result['recommendations']
    )


def main():
    """CLI entry point for testing."""
    if len(sys.argv) < 3:
        print("Usage: python3 pattern_retrieval.py <command> '<context_json>'")
        print("Example: python3 pattern_retrieval.py implement '{\"issue_key\": \"PROJ-123\"}'")
        sys.exit(1)

    command = sys.argv[1]
    try:
        context = json.loads(sys.argv[2])
    except json.JSONDecodeError as e:
        print(f"Error parsing context JSON: {e}")
        sys.exit(1)

    output = retrieve_and_format(command, context)

    if output:
        print(output)
    else:
        print("No patterns or episodes found.")


if __name__ == '__main__':
    main()
