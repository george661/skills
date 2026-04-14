"""Base runner infrastructure for workflow node execution."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from dag_executor.schema import NodeDef, NodeResult


@dataclass
class RunnerContext:
    """Context for runner execution.
    
    Attributes:
        node_def: The node definition from the workflow YAML
        resolved_inputs: Variables already resolved by the executor
        node_outputs: Output from upstream nodes (keyed by node ID)
        workflow_inputs: Global workflow inputs
        skills_dir: Root directory for skill path validation
        max_output_bytes: Maximum output size limit (default 10MB)
    """
    node_def: NodeDef
    resolved_inputs: Dict[str, Any] = field(default_factory=dict)
    node_outputs: Dict[str, Any] = field(default_factory=dict)
    workflow_inputs: Dict[str, Any] = field(default_factory=dict)
    skills_dir: Optional[Path] = None
    max_output_bytes: int = 10 * 1024 * 1024  # 10MB


class BaseRunner(ABC):
    """Abstract base class for all node runners."""
    
    @abstractmethod
    def run(self, ctx: RunnerContext) -> NodeResult:
        """Execute the node and return result.
        
        Args:
            ctx: Runner execution context
            
        Returns:
            NodeResult with status, output, and optional error
        """
        pass


# Global runner registry
_RUNNER_REGISTRY: Dict[str, type[BaseRunner]] = {}


def register_runner(node_type: str) -> Callable[[type[BaseRunner]], type[BaseRunner]]:
    """Decorator to register a runner for a specific node type.
    
    Usage:
        @register_runner('bash')
        class BashRunner(BaseRunner):
            ...
    """
    def decorator(cls: type[BaseRunner]) -> type[BaseRunner]:
        _RUNNER_REGISTRY[node_type] = cls
        return cls
    return decorator


def get_runner(node_type: str) -> Optional[type[BaseRunner]]:
    """Get runner class for a node type."""
    return _RUNNER_REGISTRY.get(node_type)


def get_runner_registry() -> Dict[str, type[BaseRunner]]:
    """Get the full runner registry."""
    return _RUNNER_REGISTRY.copy()
