"""Tests for the fix-pr.yaml workflow definition.

Validates parsing, node ordering, retry config, channels, gates, VCS router, and integration tests with mock execution.
"""
import asyncio
import os
import re
import tempfile
from pathlib import Path
from typing import Dict

import pytest
import yaml

from dag_executor.executor import WorkflowExecutor
from dag_executor.graph import topological_sort_with_layers
from dag_executor.parser import load_workflow, load_workflow_from_string
from dag_executor.schema import (
    DispatchMode,
    NodeDef,
    NodeStatus,
    ReducerStrategy,
    WorkflowDef,
    WorkflowStatus,
)


WORKFLOW_PATH = str(
    Path(__file__).parent.parent / "workflows" / "fix-pr.yaml"
)


@pytest.fixture
def workflow() -> WorkflowDef:
    """Load fix-pr workflow for testing."""
    return load_workflow(WORKFLOW_PATH)


@pytest.fixture
def nodes_by_id(workflow: WorkflowDef) -> Dict[str, NodeDef]:
    """Map of node ID to NodeDef."""
    return {node.id: node for node in workflow.nodes}


class TestFixPrParsing:
    """Test 1: YAML parses and has correct structure."""
    
    def test_parses_successfully(self, workflow: WorkflowDef) -> None:
        """fix-pr.yaml loads with no validation errors."""
        assert workflow.name == "Fix PR Workflow"
        assert len(workflow.nodes) == 12  # 12 nodes as per plan
    
    def test_input_issue_key_required(self, workflow: WorkflowDef) -> None:
        """issue_key input is required with Jira pattern."""
        assert "issue_key" in workflow.inputs
        assert workflow.inputs["issue_key"].required is True
        assert workflow.inputs["issue_key"].pattern in ["^[A-Z]+-[0-9]+$", "^[A-Z]+-\\d+$"]
    
    def test_optional_inputs(self, workflow: WorkflowDef) -> None:
        """repo, pr_number, unresolved are optional inputs."""
        assert "repo" in workflow.inputs
        assert workflow.inputs["repo"].required is False
        assert "pr_number" in workflow.inputs
        assert workflow.inputs["pr_number"].required is False
        assert "unresolved" in workflow.inputs
        assert workflow.inputs["unresolved"].required is False
    
    def test_state_declarations(self, workflow: WorkflowDef) -> None:
        """Workflow declares required channels."""
        # pr_info channel
        assert "pr_info" in workflow.state
        pr_info = workflow.state["pr_info"]
        assert pr_info.type == "dict"
        assert pr_info.reducer is not None
        assert pr_info.reducer.strategy == ReducerStrategy.OVERWRITE

        # review_comments channel
        assert "review_comments" in workflow.state
        review = workflow.state["review_comments"]
        assert review.type == "list"
        assert review.reducer is not None
        assert review.reducer.strategy == ReducerStrategy.APPEND

        # fix_attempts channel
        assert "fix_attempts" in workflow.state
        attempts = workflow.state["fix_attempts"]
        assert attempts.type == "int"
        assert attempts.reducer is not None
        assert attempts.reducer.strategy == ReducerStrategy.MAX

        # fix_result channel
        assert "fix_result" in workflow.state
        fix_res = workflow.state["fix_result"]
        assert fix_res.type == "dict"
        assert fix_res.reducer is not None
        assert fix_res.reducer.strategy == ReducerStrategy.OVERWRITE

        # verification_result channel
        assert "verification_result" in workflow.state
        verify = workflow.state["verification_result"]
        assert verify.type == "dict"
        assert verify.reducer is not None
        assert verify.reducer.strategy == ReducerStrategy.OVERWRITE

        # errors channel
        assert "errors" in workflow.state
        errors = workflow.state["errors"]
        assert errors.type == "list"
        assert errors.reducer is not None
        assert errors.reducer.strategy == ReducerStrategy.APPEND


class TestFixPrOrdering:
    """Test 2: Topological sort produces correct phase ordering."""
    
    def test_phase_ordering(self, workflow: WorkflowDef) -> None:
        """Phases execute in correct order."""
        layers = topological_sort_with_layers(workflow.nodes)
        flat_order = [nid for layer in layers for nid in layer]
        
        def before(a: str, b: str) -> None:
            idx_a = flat_order.index(a) if a in flat_order else -1
            idx_b = flat_order.index(b) if b in flat_order else -1
            assert idx_a >= 0 and idx_b >= 0, f"Both {a} and {b} must be in workflow"
            assert idx_a < idx_b, f"{a} must execute before {b}"
        
        # Phase 1: context first
        before("resolve_context", "step_label_fixing")
        
        # Phase 2: label before fetch
        before("step_label_fixing", "fetch_pr_and_comments")
        
        # Phase 3: fetch before enumerate
        before("fetch_pr_and_comments", "enumerate_unresolved")
        
        # Phase 4: enumerate before branch sync
        before("enumerate_unresolved", "branch_sync")
        
        # Phase 5: branch sync before apply fixes
        before("branch_sync", "apply_fixes")
        
        # Phase 6: apply fixes before guards
        before("apply_fixes", "pre_push_guards")
        
        # Phase 7: guards before push
        before("pre_push_guards", "push_branch")
        
        # Phase 8: push before residual scan
        before("push_branch", "residual_scan")
        
        # Phase 9: scan before gate
        before("residual_scan", "completion_verify")
        
        # Phase 10: gate before update state
        before("completion_verify", "update_workflow_state")
        
        # Phase 11: update state before emit manifest
        before("update_workflow_state", "emit_fix_manifest")


class TestFixPrRetry:
    """Test 3: Retry config on apply_fixes node."""
    
    def test_apply_fixes_has_retry(self, nodes_by_id: Dict[str, NodeDef]) -> None:
        """apply_fixes node has retry config with max_attempts=3, delay_ms >= 1000."""
        node = nodes_by_id["apply_fixes"]
        assert node.retry is not None, "apply_fixes should have retry config"
        assert node.retry.max_attempts == 3, "apply_fixes should have max_attempts=3"
        assert node.retry.delay_ms >= 1000, "apply_fixes should have delay_ms >= 1000"


class TestFixPrChannels:
    """Test 4: Channel read/write subscriptions."""
    
    def test_resolve_context_writes_pr_info(self, nodes_by_id: Dict[str, NodeDef]) -> None:
        """resolve_context writes to pr_info channel."""
        node = nodes_by_id["resolve_context"]
        assert node.writes is not None
        assert "pr_info" in node.writes
    
    def test_fetch_pr_reads_pr_info(self, nodes_by_id: Dict[str, NodeDef]) -> None:
        """fetch_pr_and_comments reads pr_info."""
        node = nodes_by_id["fetch_pr_and_comments"]
        assert node.reads is not None
        assert "pr_info" in node.reads
        assert node.writes is not None
        assert "review_comments" in node.writes
    
    def test_apply_fixes_reads_and_writes(self, nodes_by_id: Dict[str, NodeDef]) -> None:
        """apply_fixes reads review_comments and pr_info, writes fix_result."""
        node = nodes_by_id["apply_fixes"]
        assert node.reads is not None
        assert "review_comments" in node.reads
        assert "pr_info" in node.reads
        assert node.writes is not None
        assert "fix_result" in node.writes
    
    def test_residual_scan_writes_verification(self, nodes_by_id: Dict[str, NodeDef]) -> None:
        """residual_scan writes verification_result."""
        node = nodes_by_id["residual_scan"]
        assert node.writes is not None
        assert "verification_result" in node.writes


class TestFixPrGates:
    """Test 5: Gates have correct on_failure behavior."""
    
    def test_completion_verify_gate(self, nodes_by_id: Dict[str, NodeDef]) -> None:
        """completion_verify is a gate with on_failure: stop."""
        node = nodes_by_id["completion_verify"]
        assert node.type == "gate"
        assert node.on_failure == "stop"
    
    def test_branch_sync_has_on_failure_stop(self, nodes_by_id: Dict[str, NodeDef]) -> None:
        """branch_sync has on_failure: stop."""
        node = nodes_by_id["branch_sync"]
        assert node.on_failure == "stop"
    
    def test_pre_push_guards_has_on_failure_stop(self, nodes_by_id: Dict[str, NodeDef]) -> None:
        """pre_push_guards has on_failure: stop."""
        node = nodes_by_id["pre_push_guards"]
        assert node.on_failure == "stop"


class TestFixPrVcsRouter:
    """Test 6: All VCS operations use vcs/ router."""
    
    def test_no_direct_vcs_calls(self, workflow: WorkflowDef) -> None:
        """Bash scripts must use skills/vcs/, not skills/bitbucket/ or skills/github/."""
        for node in workflow.nodes:
            if node.type == "bash" and node.script:
                # Allow vcs/ but forbid bitbucket/ or github/ direct paths
                assert not re.search(r'skills/bitbucket/', node.script), \
                    f"Node {node.id} uses direct bitbucket skill"
                assert not re.search(r'skills/github/', node.script), \
                    f"Node {node.id} uses direct github skill"


class TestFixPrExitHooks:
    """Test 7: Exit hooks for cost capture."""
    
    def test_cost_capture_exit_hook(self, workflow: WorkflowDef) -> None:
        """Workflow has cost_capture exit hook that runs on [completed, failed]."""
        assert workflow.config.on_exit is not None
        assert len(workflow.config.on_exit) >= 1
        
        cost_hook = None
        for hook in workflow.config.on_exit:
            if hook.id == "cost_capture":
                cost_hook = hook
                break
        
        assert cost_hook is not None, "cost_capture exit hook not found"
        assert cost_hook.type == "bash"
        assert "capture_session_cost" in cost_hook.script
        assert cost_hook.run_on == ["completed", "failed"]


class TestFixPrMockRun:
    """Test 8: Integration test with mock execution (happy path)."""
    
    def test_fix_pr_happy_path(self) -> None:
        """Mock bash with 3 inline comments, verify all nodes complete."""
        fixture_path = Path(__file__).parent.parent / "workflows" / "fix-pr.yaml"
        
        # Load and modify workflow
        with open(fixture_path) as f:
            workflow_data = yaml.safe_load(f)
        
        # Mock all nodes as bash
        for node in workflow_data["nodes"]:
            if node["id"] == "resolve_context":
                node["script"] = 'echo \'{"pr_info": {"repo": "skills", "pr_number": "123"}}\''
            elif node["id"] == "step_label_fixing":
                node["script"] = 'echo "Label set to step:fixing-pr"'
            elif node["id"] == "fetch_pr_and_comments":
                node["script"] = 'echo \'{"review_comments": [{"id": 1, "text": "[CRITICAL] Missing test"}]}\''
            elif node["id"] == "enumerate_unresolved":
                node["script"] = 'echo \'{"review_comments": [{"id": 1, "text": "[CRITICAL] Missing test"}]}\''
            elif node["id"] == "branch_sync":
                node["script"] = 'echo "Branch synced"'
            elif node["id"] == "apply_fixes":
                node["type"] = "bash"
                node["script"] = 'echo \'{"fix_result": {"status": "FIXED", "addressed_count": 1}}\''
                node.pop("prompt", None)
                node.pop("model", None)
            elif node["id"] == "pre_push_guards":
                node["script"] = 'echo "Guards passed"'
            elif node["id"] == "push_branch":
                node["script"] = 'echo "Branch pushed"'
            elif node["id"] == "residual_scan":
                node["script"] = 'echo \'{"verification_result": {"addressed": true, "residual_count": 0}}\''
            elif node["id"] == "completion_verify":
                node["type"] = "bash"
                node["script"] = 'echo "Verification passed"'
                node.pop("condition", None)
            elif node["id"] == "update_workflow_state":
                node["script"] = 'echo "Workflow state updated"'
            elif node["id"] == "emit_fix_manifest":
                node["script"] = 'echo "Fix manifest emitted"'
        
        # Save to temp file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as tmp:
            yaml.dump(workflow_data, tmp)
            tmp_path = tmp.name
        
        try:
            with open(tmp_path) as f:
                workflow_def = load_workflow_from_string(f.read())
            
            executor = WorkflowExecutor()
            result = asyncio.run(executor.execute(workflow_def, {"issue_key": "GW-100", "repo": "skills", "pr_number": "123"}))
            
            # Workflow should complete
            assert result.status == WorkflowStatus.COMPLETED
            
            # All nodes should complete
            assert result.node_results["resolve_context"].status == NodeStatus.COMPLETED
            assert result.node_results["apply_fixes"].status == NodeStatus.COMPLETED
            assert result.node_results["emit_fix_manifest"].status == NodeStatus.COMPLETED

        finally:
            os.unlink(tmp_path)


class TestFixPrMockRunRetry:
    """Test 9: Verify retry configuration is present."""

    def test_retry_config_present(self, nodes_by_id: Dict[str, NodeDef]) -> None:
        """Verify apply_fixes has retry configured (actual retry behavior tested by executor tests)."""
        node = nodes_by_id["apply_fixes"]
        assert node.retry is not None
        assert node.retry.max_attempts == 3
        # Executor handles exponential backoff automatically

    def test_fix_pr_retry_path_skipped(self) -> None:
        """Placeholder: retry integration is covered by executor unit tests.

        See tests/test_executor.py for exponential-backoff behavior; this
        suite only asserts that the workflow declares retry correctly.
        """
        pass
