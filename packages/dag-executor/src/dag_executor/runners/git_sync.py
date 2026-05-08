"""Git sync runner for cloning/checking out repositories into workspace."""
import asyncio
import json
import logging
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from dag_executor.runners.base import BaseRunner, RunnerContext, register_runner
from dag_executor.schema import NodeResult, NodeStatus

logger = logging.getLogger(__name__)


@register_runner("git-sync")
class GitSyncRunner(BaseRunner):
    """Runner for git-sync nodes that clone/checkout repositories.
    
    Reads the workspace channel to determine destination directory,
    then clones or creates a worktree from a local mirror if available.
    """
    
    def run(self, ctx: RunnerContext) -> NodeResult:
        """Execute git clone/worktree operation.
        
        Args:
            ctx: Runner execution context
            
        Returns:
            NodeResult with execution status and output
        """
        return asyncio.run(self._run_async(ctx))
    
    async def _run_async(self, ctx: RunnerContext) -> NodeResult:
        """Async implementation of git-sync execution."""
        try:
            # Get git config from workflow config
            if not ctx.workflow_def or not ctx.workflow_def.config.git:
                return NodeResult(
                    status=NodeStatus.FAILED,
                    error="git-sync node requires workflow config.git to be set"
                )
            
            git_config = ctx.workflow_def.config.git
            
            # Get workspace path from channel
            workspace_path = self._get_workspace_path(ctx)
            if not workspace_path:
                return NodeResult(
                    status=NodeStatus.FAILED,
                    error="workspace channel not set - workspace must be created before git-sync"
                )
            
            src_path = Path(workspace_path) / "src"
            
            # Resolve variables in git config
            url = self._resolve_variable(git_config.url, ctx)
            ref = self._resolve_variable(git_config.ref, ctx)
            depth = git_config.depth
            
            self._log(ctx, f"Git sync: {url} @ {ref}")
            self._log(ctx, f"Destination: {src_path}")
            
            # Try worktree fast path first
            repo_name = self._extract_repo_name(url)
            local_mirror = Path.home() / "dev" / repo_name
            
            if local_mirror.exists() and (local_mirror / ".git").exists():
                # Check if origin URL matches
                try:
                    result = subprocess.run(
                        ["git", "-C", str(local_mirror), "remote", "get-url", "origin"],
                        capture_output=True,
                        text=True,
                        check=True,
                        timeout=10
                    )
                    origin_url = result.stdout.strip()
                    
                    if self._urls_match(origin_url, url):
                        self._log(ctx, f"Using worktree from local mirror: {local_mirror}")
                        return await self._worktree_path(ctx, local_mirror, src_path, ref)
                    else:
                        self._log(ctx, f"Local mirror URL mismatch (expected {url}, got {origin_url})")
                except subprocess.CalledProcessError as e:
                    self._log(ctx, f"Could not read origin URL from {local_mirror}: {e}")
                except subprocess.TimeoutExpired:
                    self._log(ctx, f"Timeout reading origin URL from {local_mirror}")
            
            # Fall back to clone
            self._log(ctx, f"Cloning {url} (shallow, depth={depth})")
            return await self._clone_path(ctx, url, src_path, ref, depth)
            
        except Exception as e:
            logger.exception("Git sync failed")
            return NodeResult(
                status=NodeStatus.FAILED,
                error=f"Git sync failed: {str(e)}"
            )
    
    def _get_workspace_path(self, ctx: RunnerContext) -> Optional[str]:
        """Get workspace path from channel state."""
        if not ctx.channel_store:
            return None

        try:
            value, _version = ctx.channel_store.read("workspace")
            return str(value) if value is not None else None
        except Exception:
            pass

        return None
    
    def _resolve_variable(self, value: str, ctx: RunnerContext) -> str:
        """Resolve variables in string using workflow inputs."""
        if "${" not in value:
            return value
        
        # Simple variable substitution from inputs
        resolved = value
        for key, val in ctx.workflow_inputs.items():
            resolved = resolved.replace(f"${{{key}}}", str(val))
        
        return resolved
    
    def _extract_repo_name(self, url: str) -> str:
        """Extract repository name from git URL."""
        # Handle various formats: https://..., git@..., etc.
        parts = url.rstrip("/").split("/")
        repo = parts[-1]
        if repo.endswith(".git"):
            repo = repo[:-4]
        return repo
    
    def _urls_match(self, url1: str, url2: str) -> bool:
        """Check if two git URLs refer to the same repository."""
        # Normalize URLs for comparison
        norm1 = url1.rstrip("/").replace(".git", "")
        norm2 = url2.rstrip("/").replace(".git", "")
        
        # Handle https vs ssh
        norm1 = norm1.replace("git@github.com:", "https://github.com/")
        norm2 = norm2.replace("git@github.com:", "https://github.com/")
        
        return norm1 == norm2
    
    async def _worktree_path(
        self, 
        ctx: RunnerContext,
        local_mirror: Path, 
        dest: Path, 
        ref: str
    ) -> NodeResult:
        """Create worktree from local mirror."""
        try:
            # Fetch the ref first
            self._run_git_command(
                ctx,
                ["git", "-C", str(local_mirror), "fetch", "origin", ref],
                f"Fetching {ref} from origin"
            )
            
            # Create worktree
            self._run_git_command(
                ctx,
                ["git", "-C", str(local_mirror), "worktree", "add", str(dest), "FETCH_HEAD"],
                f"Creating worktree at {dest}"
            )
            
            # Get resolved SHA
            result = subprocess.run(
                ["git", "-C", str(dest), "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                check=True,
                timeout=10
            )
            resolved_sha = result.stdout.strip()
            
            self._log(ctx, f"Worktree created successfully at {dest}")
            self._log(ctx, f"Resolved SHA: {resolved_sha}")
            
            return NodeResult(
                status=NodeStatus.COMPLETED,
                output={
                    "checkout_ref": ref,
                    "resolved_sha": resolved_sha,
                    "src_path": str(dest),
                    "method": "worktree"
                }
            )
            
        except subprocess.CalledProcessError as e:
            error_msg = f"Worktree creation failed: {e.stderr if hasattr(e, 'stderr') else str(e)}"
            self._log(ctx, error_msg)
            return NodeResult(
                status=NodeStatus.FAILED,
                error=error_msg
            )
    
    async def _clone_path(
        self, 
        ctx: RunnerContext,
        url: str, 
        dest: Path, 
        ref: str, 
        depth: Optional[int]
    ) -> NodeResult:
        """Clone repository (fallback path)."""
        try:
            # Build clone command
            clone_cmd: List[str] = ["git", "clone"]
            if depth is not None:
                clone_cmd.extend(["--depth", str(depth)])
            clone_cmd.extend([url, str(dest)])
            
            self._run_git_command(ctx, clone_cmd, f"Cloning {url}")
            
            # Fetch and checkout specific ref if not main/master
            if ref not in ["main", "master"]:
                self._run_git_command(
                    ctx,
                    ["git", "-C", str(dest), "fetch", "--depth", "1", "origin", ref],
                    f"Fetching {ref}"
                )
                self._run_git_command(
                    ctx,
                    ["git", "-C", str(dest), "checkout", "FETCH_HEAD"],
                    f"Checking out {ref}"
                )
            
            # Get resolved SHA
            result = subprocess.run(
                ["git", "-C", str(dest), "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                check=True,
                timeout=10
            )
            resolved_sha = result.stdout.strip()
            
            self._log(ctx, f"Clone completed successfully at {dest}")
            self._log(ctx, f"Resolved SHA: {resolved_sha}")
            
            return NodeResult(
                status=NodeStatus.COMPLETED,
                output={
                    "checkout_ref": ref,
                    "resolved_sha": resolved_sha,
                    "src_path": str(dest),
                    "method": "clone"
                }
            )
            
        except subprocess.CalledProcessError as e:
            error_msg = f"Clone failed: {e.stderr if hasattr(e, 'stderr') else str(e)}"
            self._log(ctx, error_msg)
            return NodeResult(
                status=NodeStatus.FAILED,
                error=error_msg
            )
    
    def _run_git_command(self, ctx: RunnerContext, cmd: List[str], description: str) -> None:
        """Run a git command and stream output."""
        self._log(ctx, f"{description}: {' '.join(cmd)}")
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True,
                timeout=300  # 5 minute timeout for git operations
            )
            
            if result.stdout:
                for line in result.stdout.strip().split("\n"):
                    if line:
                        self._log(ctx, line)
            
            if result.stderr:
                for line in result.stderr.strip().split("\n"):
                    if line:
                        self._log(ctx, line)
                        
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"Git command timed out: {' '.join(cmd)}")
        except subprocess.CalledProcessError as e:
            if e.stderr:
                for line in e.stderr.strip().split("\n"):
                    if line:
                        self._log(ctx, f"ERROR: {line}")
            raise
    
    def _log(self, ctx: RunnerContext, message: str) -> None:
        """Log a message using the progress callback if available."""
        if ctx.progress_callback:
            ctx.progress_callback("node_log_line", {"message": message})
        logger.info(message)
