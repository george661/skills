#!/usr/bin/env python3
"""
AgentDB REST API Client for Python hooks.

Provides a simple HTTP client for AgentDB REST API endpoints.
Retrieves credentials from (in order):
1. Environment variables (AGENTDB_API_KEY, AGENTDB_URL)
2. $PROJECT_ROOT/.env file
3. ~/.claude/settings.json credentials.agentdb
"""

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Optional, Dict, Any
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
import threading
import sys

DEFAULT_AGENTDB_URL = os.environ.get('AGENTDB_URL', 'https://YOUR_AGENTDB_URL')
DEFAULT_NAMESPACE = 'default'


def validate_issue_key(issue_key: str) -> str:
    """Validate and sanitize issue key to prevent injection attacks."""
    if not issue_key:
        raise ValueError("Issue key cannot be empty")

    # Allow only alphanumeric, hyphens, underscores
    if not re.match(r'^[A-Za-z0-9_-]+$', issue_key):
        raise ValueError(f"Invalid issue key format: {issue_key}")

    # Limit length
    if len(issue_key) > 50:
        raise ValueError(f"Issue key too long (max 50 chars): {issue_key}")

    return issue_key.upper()


def get_namespace() -> str:
    """Get namespace from environment with automatic detection fallback."""
    namespace = os.environ.get('TENANT_NAMESPACE')

    if not namespace:
        # Try to infer from PROJECT_ROOT
        project_root = os.environ.get('PROJECT_ROOT', os.getcwd())
        project_root.lower()

        # Use TENANT_NAMESPACE from env, fall back to TENANT_PROJECT lowercase
        namespace = os.environ.get('TENANT_NAMESPACE', os.environ.get('TENANT_PROJECT', 'default')).lower()
        if namespace == 'default':
            print(
                f"[agentdb] TENANT_NAMESPACE not set, using '{namespace}'. "
                "Set TENANT_NAMESPACE for proper data isolation.",
                file=sys.stderr
            )

    return namespace


def load_env_file(file_path: str) -> Dict[str, str]:
    """Load environment variables from a .env file."""
    env = {}
    path = Path(file_path)
    if not path.exists():
        return env

    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if '=' in line:
                    key, value = line.split('=', 1)
                    key = key.strip()
                    value = value.strip()
                    # Remove surrounding quotes
                    if (value.startswith('"') and value.endswith('"')) or \
                       (value.startswith("'") and value.endswith("'")):
                        value = value[1:-1]
                    env[key] = value
    except Exception:
        pass
    return env


def get_credentials() -> Dict[str, str]:
    """Get AgentDB credentials from environment, settings, or AWS."""

    # 1. Check environment variables
    if os.environ.get('AGENTDB_API_KEY'):
        return {
            'apiKey': os.environ['AGENTDB_API_KEY'],
            'url': os.environ.get('AGENTDB_URL', DEFAULT_AGENTDB_URL)
        }

    # 2. Check .env file in PROJECT_ROOT
    project_root = os.environ.get('PROJECT_ROOT', os.getcwd())
    env_path = os.path.join(project_root, '.env')
    env = load_env_file(env_path)
    if env.get('AGENTDB_API_KEY'):
        return {
            'apiKey': env['AGENTDB_API_KEY'],
            'url': env.get('AGENTDB_URL', DEFAULT_AGENTDB_URL)
        }

    # 3. Check ~/.claude/settings.json
    settings_path = Path.home() / '.claude' / 'settings.json'
    if settings_path.exists():
        try:
            with open(settings_path) as f:
                settings = json.load(f)

            # 3a. New credentials location
            creds = settings.get('credentials', {}).get('agentdb', {})
            if creds.get('apiKey'):
                return {
                    'apiKey': creds['apiKey'],
                    'url': creds.get('url', DEFAULT_AGENTDB_URL)
                }

            # 3b. Legacy mcpServers location
            config = settings.get('mcpServers', {}).get('agentdb-mcp', {})
            if config.get('headers', {}).get('X-Api-Key'):
                url = config.get('url', DEFAULT_AGENTDB_URL)
                if url.endswith('/sse'):
                    url = url[:-4]
                return {
                    'apiKey': config['headers']['X-Api-Key'],
                    'url': url
                }
        except Exception:
            pass

    # 4. Try AWS Secrets Manager (optional, may fail)
    try:
        aws_profile = os.environ.get('AWS_PROFILE', 'dev-profile')
        # Validate profile name to prevent injection
        if not re.match(r'^[A-Za-z0-9_-]+$', aws_profile):
            raise ValueError(f"Invalid AWS profile name: {aws_profile}")

        # Use list form instead of shell=True for security
        env = os.environ.copy()
        env['AWS_PROFILE'] = aws_profile
        result = subprocess.run(
            [
                'aws', 'secretsmanager', 'get-secret-value',
                '--secret-id', 'agentdb-mcp-dev-api-key',
                '--query', 'SecretString',
                '--output', 'text'
            ],
            capture_output=True, text=True, timeout=10, env=env
        )
        if result.returncode == 0 and result.stdout.strip():
            secret = json.loads(result.stdout.strip())
            if secret.get('apiKey'):
                return {
                    'apiKey': secret['apiKey'],
                    'url': os.environ.get('AGENTDB_URL', DEFAULT_AGENTDB_URL)
                }
    except Exception as e:
        print(f"[agentdb] AWS Secrets Manager lookup failed: {e}", file=sys.stderr)

    return {}


def agentdb_request(method: str, path: str, body: Optional[Dict] = None, timeout: int = 15) -> Optional[Dict]:
    """Make a REST API request to AgentDB. Returns None on failure.

    Args:
        method: HTTP method (GET, POST)
        path: API path (e.g., '/api/v1/pattern/store')
        body: Request body as dict
        timeout: Request timeout in seconds (default 15s for synchronous ops)
    """
    try:
        creds = get_credentials()
        if not creds.get('apiKey'):
            print("[agentdb] No API key found", file=sys.stderr)
            return None

        url = f"{creds['url']}{path}"
        data = json.dumps(body).encode() if body else None

        req = Request(
            url,
            data=data,
            headers={
                'Content-Type': 'application/json',
                'X-Api-Key': creds['apiKey']
            },
            method=method
        )

        with urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode())

    except HTTPError as e:
        print(f"[agentdb] HTTP error {e.code}: {e.reason}", file=sys.stderr)
        return None
    except URLError as e:
        print(f"[agentdb] URL error: {e.reason}", file=sys.stderr)
        return None
    except json.JSONDecodeError as e:
        print(f"[agentdb] JSON decode error: {e}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"[agentdb] Request error: {e}", file=sys.stderr)
        return None


def store_pattern(task_type: str, pattern: Dict[str, Any], namespace: str = None) -> bool:
    """Store a pattern in AgentDB. Returns True on success.

    Args:
        task_type: Type of task (e.g., 'session-cost', 'workflow-pattern')
        pattern: Dict containing required fields:
            - approach: str - Description of the pattern/approach
            - success_rate: float - Success rate (0.0-1.0)
            - metadata: dict (optional) - Additional metadata
        namespace: Namespace for the pattern (defaults to TENANT_NAMESPACE)
    """
    if namespace is None:
        namespace = get_namespace()

    # Build request body with required top-level fields
    body = {
        'task_type': task_type,
        'approach': pattern.get('approach', str(pattern)),
        'success_rate': pattern.get('success_rate', 0.5),
        'namespace': namespace,
    }

    # Add optional metadata if present
    if 'metadata' in pattern:
        body['metadata'] = pattern['metadata']

    result = agentdb_request('POST', '/api/v1/pattern/store', body)
    return result is not None


def store_episode(session_id: str, task: str, reward: float, success: bool,
                  trajectory: Optional[list] = None, namespace: str = None) -> bool:
    """Store an episode in AgentDB reflexion memory. Returns True on success.

    Args:
        session_id: Unique session identifier
        task: Task description
        reward: Reward value (0.0-1.0)
        success: Whether the task succeeded
        trajectory: List of action records
        namespace: Namespace (defaults to TENANT_NAMESPACE)
    """
    if namespace is None:
        namespace = get_namespace()

    result = agentdb_request('POST', '/api/v1/reflexion/store', {
        'session_id': session_id,
        'task': task,
        'reward': reward,
        'success': success,
        'trajectory': trajectory or [],
        'namespace': namespace
    })
    return result is not None


def store_async(func, *args, **kwargs):
    """Run a storage function asynchronously (fire and forget)."""
    thread = threading.Thread(target=func, args=args, kwargs=kwargs, daemon=True)
    thread.start()
    return thread


# Convenience functions for async storage
def store_pattern_async(task_type: str, pattern: Dict[str, Any], namespace: str = None):
    """Store a pattern asynchronously."""
    return store_async(store_pattern, task_type, pattern, namespace)


def store_episode_async(session_id: str, task: str, reward: float, success: bool,
                       trajectory: Optional[list] = None, namespace: str = None):
    """Store an episode asynchronously."""
    return store_async(store_episode, session_id, task, reward, success, trajectory, namespace)


class AgentDBClient:
    """Class-based wrapper around AgentDB REST functions.

    Used by hooks like session-cleanup.py that need an object-oriented interface.
    """

    def __init__(self):
        self._creds = get_credentials()

    def recall_query(self, query: str, namespace: str = None, k: int = 5,
                     filters: Optional[Dict] = None) -> Optional[list]:
        """Search AgentDB reflexion memory for relevant past context.

        Args:
            query: Search query string
            namespace: Namespace to search in
            k: Maximum number of results
            filters: Additional filter criteria

        Returns:
            List of matching entries, or None on failure
        """
        if namespace is None:
            namespace = get_namespace()

        body: Dict[str, Any] = {
            'task': query,
            'k': k,
        }

        if filters:
            body['filters'] = filters
        if namespace:
            body.setdefault('filters', {})
            body['filters']['namespace'] = namespace

        result = agentdb_request('POST', '/api/v1/reflexion/retrieve-relevant', body)
        if result and 'results' in result:
            return result['results']
        return result

    def delete_memory(self, namespace: str, key: str) -> bool:
        """Delete a memory entry by key.

        Note: Uses the AgentDB store endpoint to overwrite with a tombstone marker,
        since no dedicated delete endpoint exists.

        Args:
            namespace: Namespace containing the key
            key: Memory key to delete

        Returns:
            True if the operation succeeded
        """
        result = agentdb_request('POST', '/api/v1/pattern/store', {
            'task_type': key,
            'approach': '__deleted__',
            'success_rate': 0.0,
            'namespace': namespace,
            'metadata': {'deleted': True, 'original_key': key}
        })
        if result is None:
            print(f"[agentdb] Could not delete key '{key}' in namespace '{namespace}'",
                  file=sys.stderr)
            return False
        return True

    def store_pattern(self, task_type: str, pattern: Dict[str, Any],
                      namespace: str = None) -> bool:
        """Store a pattern. Delegates to module-level function."""
        return store_pattern(task_type, pattern, namespace)

    def store_episode(self, session_id: str, task: str, reward: float, success: bool,
                      trajectory: Optional[list] = None, namespace: str = None) -> bool:
        """Store an episode. Delegates to module-level function."""
        return store_episode(session_id, task, reward, success, trajectory, namespace)
