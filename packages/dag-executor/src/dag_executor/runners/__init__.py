"""Runner registry for workflow node execution.

Runners implement the execution logic for different node types (bash, python, http, etc.).
"""
from typing import Any, Dict

# Runner registry will be implemented in future iterations
RUNNER_REGISTRY: Dict[str, Any] = {}
