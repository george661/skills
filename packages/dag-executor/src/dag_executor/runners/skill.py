"""Skill runner for executing skill nodes."""
import json
import subprocess
from pathlib import Path

from dag_executor.schema import NodeResult, NodeStatus
from dag_executor.runners.base import BaseRunner, RunnerContext, register_runner


@register_runner("skill")
class SkillRunner(BaseRunner):
    """Runner for skill execution nodes.
    
    Validates skill path is within skills directory and executes via subprocess.
    """
    
    def run(self, ctx: RunnerContext) -> NodeResult:
        """Execute a skill node.
        
        Args:
            ctx: Runner execution context
            
        Returns:
            NodeResult with execution status and output
        """
        # Extract skill configuration from validated NodeDef
        skill_path = ctx.node_def.skill
        if skill_path is None:
            raise ValueError("skill field is required for type=skill")
        params = ctx.node_def.params or {}
        
        # Validate skill path
        if ctx.skills_dir is None:
            return NodeResult(
                status=NodeStatus.FAILED,
                error="skills_dir not configured in runner context"
            )
        
        try:
            resolved_path = self._validate_skill_path(skill_path, ctx.skills_dir)
        except ValueError as e:
            return NodeResult(
                status=NodeStatus.FAILED,
                error=str(e)
            )
        
        # Execute skill via subprocess using Popen for subprocess registry support
        try:
            proc = subprocess.Popen(
                ["python3", str(resolved_path)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )

            # Register with subprocess registry if available
            if ctx.subprocess_registry is not None:
                ctx.subprocess_registry.register(proc)

            try:
                stdout, stderr = proc.communicate(
                    input=json.dumps(params),
                    timeout=ctx.node_def.timeout or 300
                )
                returncode = proc.returncode
            finally:
                # Deregister from registry
                if ctx.subprocess_registry is not None:
                    ctx.subprocess_registry.deregister(proc)

            # Parse output
            if returncode != 0:
                return NodeResult(
                    status=NodeStatus.FAILED,
                    error=stderr or f"Skill exited with code {returncode}"
                )

            # Try to parse JSON output
            try:
                output = json.loads(stdout)
            except json.JSONDecodeError:
                # Non-JSON output, return as raw text
                output = {"stdout": stdout}

            return NodeResult(
                status=NodeStatus.COMPLETED,
                output=output
            )
            
        except subprocess.TimeoutExpired:
            return NodeResult(
                status=NodeStatus.FAILED,
                error=f"Skill execution timed out after {ctx.node_def.timeout} seconds"
            )
        except Exception as e:
            return NodeResult(
                status=NodeStatus.FAILED,
                error=f"Skill execution failed: {str(e)}"
            )
    
    def _validate_skill_path(self, skill_path: str, skills_dir: Path) -> Path:
        """Validate and resolve skill path.
        
        Args:
            skill_path: Relative path to skill file
            skills_dir: Root skills directory
            
        Returns:
            Resolved absolute path
            
        Raises:
            ValueError: If path is invalid or outside skills directory
        """
        # Resolve the candidate path
        if Path(skill_path).is_absolute():
            resolved = Path(skill_path).resolve()
        else:
            resolved = (skills_dir / skill_path).resolve()

        skills_dir_resolved = skills_dir.resolve()

        # Verify resolved path is within skills_dir (prevents .. traversal and sibling-dir attacks)
        if not resolved.is_relative_to(skills_dir_resolved):
            raise ValueError(f"Path traversal detected - skill path outside skills directory: {skill_path}")

        return resolved
