"""Skill runner for executing skill nodes."""
import json
import subprocess
from pathlib import Path
from typing import Any, Dict

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
        assert skill_path is not None, "skill field is required (validated by schema)"
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
        
        # Execute skill via subprocess
        try:
            result = subprocess.run(
                ["python3", str(resolved_path)],
                input=json.dumps(params),
                capture_output=True,
                text=True,
                timeout=ctx.node_def.timeout or 300  # Default 5 min timeout
            )
            
            # Parse output
            if result.returncode != 0:
                return NodeResult(
                    status=NodeStatus.FAILED,
                    error=result.stderr or f"Skill exited with code {result.returncode}"
                )
            
            # Try to parse JSON output
            try:
                output = json.loads(result.stdout)
            except json.JSONDecodeError:
                # Non-JSON output, return as raw text
                output = {"stdout": result.stdout}
            
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
        # Reject absolute paths
        if Path(skill_path).is_absolute():
            # Check if it's actually within skills_dir
            resolved = Path(skill_path).resolve()
            skills_resolved = skills_dir.resolve()
            if not str(resolved).startswith(str(skills_resolved)):
                raise ValueError(f"Skill path outside skills directory: {skill_path}")
            return resolved
        
        # Resolve relative path
        full_path = (skills_dir / skill_path).resolve()
        skills_dir_resolved = skills_dir.resolve()
        
        # Verify resolved path is within skills_dir (prevents .. traversal)
        if not str(full_path).startswith(str(skills_dir_resolved)):
            raise ValueError(f"Path traversal detected - skill path outside skills directory: {skill_path}")
        
        return full_path
