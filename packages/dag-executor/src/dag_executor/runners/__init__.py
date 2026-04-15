"""Runner registry for workflow node execution.

Runners implement the execution logic for different node types (bash, skill, prompt, gate, command).
"""

from dag_executor.runners.base import (
    BaseRunner,
    RunnerContext,
    register_runner,
    get_runner,
    get_runner_registry,
)

# Import all runners to trigger registration
from dag_executor.runners.bash import BashRunner
from dag_executor.runners.command import CommandRunner
from dag_executor.runners.gate import GateRunner
from dag_executor.runners.interrupt import InterruptRunner
from dag_executor.runners.prompt import PromptRunner
from dag_executor.runners.skill import SkillRunner

# Re-export the registry accessor (populated by @register_runner decorators)
RUNNER_REGISTRY = get_runner_registry()

__all__ = [
    "BaseRunner",
    "RunnerContext",
    "register_runner",
    "get_runner",
    "get_runner_registry",
    "RUNNER_REGISTRY",
    "BashRunner",
    "CommandRunner",
    "GateRunner",
    "InterruptRunner",
    "PromptRunner",
    "SkillRunner",
]
