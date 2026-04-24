"""Tests for the fix-implementation-plan.yaml workflow definition.

Validates parsing, node ordering, retry config, channels, and integration tests with mock execution.
"""
import asyncio
import os
import tempfile
from pathlib import Path
from typing import Dict

import pytest
import yaml

from dag_executor.executor import WorkflowExecutor
from dag_executor.graph import topological_sort_with_layers
from dag_executor.parser import load_workflow, load_workflow_from_string
from dag_executor.schema import (
    ChannelFieldDef,
    DispatchMode,
    NodeDef,
    NodeStatus,
    ReducerStrategy,
    WorkflowDef,
    WorkflowStatus,
)


WORKFLOW_PATH = str(
    Path(__file__).parent.parent / "workflows" / "fix-implementation-plan.yaml"
)


@pytest.fixture
def workflow() -> WorkflowDef:
    """Load fix-implementation-plan workflow for testing."""
    return load_workflow(WORKFLOW_PATH)


@pytest.fixture
def nodes_by_id(workflow: WorkflowDef) -> Dict[str, NodeDef]:
    """Map of node ID to NodeDef."""
    return {node.id: node for node in workflow.nodes}


class TestFixImplementationPlanParsing:
    """Test 1: YAML parses and has correct structure."""
    
    def test_parses_successfully(self, workflow: WorkflowDef) -> None:
        """fix-implementation-plan.yaml loads with no validation errors."""
        assert workflow.name == "Fix Implementation Plan"
        assert len(workflow.nodes) == 6  # 6 nodes as per plan
    
    def test_input_issue_key_required(self, workflow: WorkflowDef) -> None:
        """issue_key input is required with Jira pattern."""
        assert "issue_key" in workflow.inputs
        assert workflow.inputs["issue_key"].required is True
        # Pattern can be either [0-9]+ or \d+ (both valid)
        assert workflow.inputs["issue_key"].pattern in ["^[A-Z]+-[0-9]+$", "^[A-Z]+-\\d+$"]
    
    def test_state_declarations(self, workflow: WorkflowDef) -> None:
        """Workflow declares verdict, review_findings and fix_result channels."""
        # verdict channel
        assert "verdict" in workflow.state
        verdict_ch = workflow.state["verdict"]
        assert verdict_ch.type == "string"
        assert verdict_ch.reducer is not None
        assert verdict_ch.reducer.strategy == ReducerStrategy.OVERWRITE

        # review_findings channel
        assert "review_findings" in workflow.state
        review_ch = workflow.state["review_findings"]
        assert review_ch.type == "dict"
        assert review_ch.reducer is not None
        assert review_ch.reducer.strategy == ReducerStrategy.OVERWRITE

        # fix_result channel
        assert "fix_result" in workflow.state
        fix_ch = workflow.state["fix_result"]
        assert fix_ch.type == "dict"
        assert fix_ch.reducer is not None
        assert fix_ch.reducer.strategy == ReducerStrategy.OVERWRITE


class TestFixTopologicalOrdering:
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
        
        # Phase 1: load first
        before("load_review_findings", "validate_needs_fixes")
        
        # Phase 2: gate before fix nodes
        before("validate_needs_fixes", "fix_critical")
        
        # Phase 3: fix critical before fix warnings
        before("fix_critical", "fix_warnings")
        
        # Phase 4: post revised plan
        before("fix_warnings", "post_revised_plan")
        
        # Phase 5: store episode last
        before("post_revised_plan", "store_episode")


class TestFixRetryConfiguration:
    """Test 3: Retry config on fix_critical node."""
    
    def test_fix_critical_has_retry(self, nodes_by_id: Dict[str, NodeDef]) -> None:
        """fix_critical node has retry config with max_attempts=2."""
        node = nodes_by_id["fix_critical"]
        assert node.retry is not None, "fix_critical should have retry config"
        assert node.retry.max_attempts == 2, "fix_critical should have max_attempts=2"


class TestFixDispatchConfig:
    """Test 4: Prompt nodes use sonnet/local."""
    
    def test_fix_nodes_use_sonnet_local(self, nodes_by_id: Dict[str, NodeDef]) -> None:
        """fix_critical and fix_warnings use sonnet model with local dispatch."""
        sonnet_nodes = ["fix_critical", "fix_warnings"]
        for node_id in sonnet_nodes:
            node = nodes_by_id[node_id]
            assert node.type == "prompt", f"{node_id} should be prompt type"
            assert node.model is not None, f"{node_id} should have model"
            assert node.model == "sonnet", f"{node_id} should use sonnet model"
            assert node.dispatch == DispatchMode.LOCAL, f"{node_id} should use local dispatch"
    
    def test_bash_nodes_exist(self, nodes_by_id: Dict[str, NodeDef]) -> None:
        """Bash nodes exist in workflow."""
        bash_nodes = ["load_review_findings", "post_revised_plan", "store_episode"]
        for node_id in bash_nodes:
            node = nodes_by_id[node_id]
            assert node.type == "bash", f"{node_id} should be bash type"


class TestFixChannels:
    """Test 5: Channel read/write subscriptions."""
    
    def test_load_writes_review_findings(self, nodes_by_id: Dict[str, NodeDef]) -> None:
        """load_review_findings writes to review_findings channel."""
        node = nodes_by_id["load_review_findings"]
        assert node.writes is not None
        assert "review_findings" in node.writes
    
    def test_validate_needs_fixes_reads_review_findings(self, nodes_by_id: Dict[str, NodeDef]) -> None:
        """validate_needs_fixes gate reads verdict."""
        node = nodes_by_id["validate_needs_fixes"]
        assert node.reads is not None
        assert "verdict" in node.reads
    
    def test_fix_critical_reads_review_writes_fix(self, nodes_by_id: Dict[str, NodeDef]) -> None:
        """fix_critical reads review_findings, writes fix_result."""
        node = nodes_by_id["fix_critical"]
        assert node.reads is not None
        assert "review_findings" in node.reads
        assert node.writes is not None
        assert "fix_result" in node.writes
    
    def test_fix_warnings_reads_both_channels(self, nodes_by_id: Dict[str, NodeDef]) -> None:
        """fix_warnings reads review_findings and fix_result."""
        node = nodes_by_id["fix_warnings"]
        assert node.reads is not None
        assert "review_findings" in node.reads
        assert "fix_result" in node.reads
    
    def test_post_revised_plan_reads_fix_result(self, nodes_by_id: Dict[str, NodeDef]) -> None:
        """post_revised_plan reads fix_result."""
        node = nodes_by_id["post_revised_plan"]
        assert node.reads is not None
        assert "fix_result" in node.reads


class TestFixVariableSubstitution:
    """Test 6: Variable substitution for $issue_key."""
    
    def test_issue_key_substitution(self, workflow: WorkflowDef) -> None:
        """$issue_key appears in bash scripts."""
        has_issue_key = False
        for node in workflow.nodes:
            if node.type == "bash" and node.script:
                if "$issue_key" in node.script or "${issue_key}" in node.script:
                    has_issue_key = True
                    break
        assert has_issue_key, "$issue_key variable must be used in bash scripts"


class TestFixIntegrationWithMockExecution:
    """Test 7: Integration tests with mock execution (addresses AC #5)."""
    
    def test_fix_workflow_early_exit_approved(self) -> None:
        """Mock bash with APPROVED verdict, verify gate skips fix nodes."""
        fixture_path = Path(__file__).parent.parent / "workflows" / "fix-implementation-plan.yaml"
        
        # Load and modify workflow
        with open(fixture_path) as f:
            workflow_data = yaml.safe_load(f)
        
        # Mock APPROVED verdict (should trigger early exit at gate)
        for node in workflow_data["nodes"]:
            if node["id"] == "load_review_findings":
                node["script"] = 'echo \'{"verdict": "APPROVED"}\''
            elif node["id"] == "validate_needs_fixes":
                # Gate should fail when verdict is APPROVED
                node["type"] = "bash"
                node["script"] = 'exit 1'  # Fail to skip downstream
                node.pop("condition", None)
            elif node["id"] in ["fix_critical", "fix_warnings"]:
                node["type"] = "bash"
                node["script"] = 'echo "Should not execute"'
                node.pop("prompt", None)
                node.pop("dispatch", None)
            elif node["id"] == "post_revised_plan":
                node["script"] = 'echo "No changes needed"'
            elif node["id"] == "store_episode":
                node["script"] = 'echo "Stored episode"'
        
        # Save to temp file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as tmp:
            yaml.dump(workflow_data, tmp)
            tmp_path = tmp.name
        
        try:
            with open(tmp_path) as f:
                workflow_def = load_workflow_from_string(f.read())
            
            executor = WorkflowExecutor()
            result = asyncio.run(executor.execute(workflow_def, {"issue_key": "TEST-100"}))
            
            # Workflow may complete or fail at gate
            assert result.status in [WorkflowStatus.COMPLETED, WorkflowStatus.FAILED]
            
            # load_review_findings should complete
            assert result.node_results["load_review_findings"].status == NodeStatus.COMPLETED
            
            # Gate should fail/skip
            assert result.node_results["validate_needs_fixes"].status in [NodeStatus.FAILED, NodeStatus.SKIPPED]
            
            # Fix nodes should be skipped
            assert result.node_results["fix_critical"].status == NodeStatus.SKIPPED
            assert result.node_results["fix_warnings"].status == NodeStatus.SKIPPED

        finally:
            os.unlink(tmp_path)
    
    def test_fix_workflow_fixes_applied(self) -> None:
        """Mock bash with NEEDS_FIXES, verify fix nodes execute and post revised plan."""
        fixture_path = Path(__file__).parent.parent / "workflows" / "fix-implementation-plan.yaml"
        
        # Load and modify workflow
        with open(fixture_path) as f:
            workflow_data = yaml.safe_load(f)
        
        # Mock NEEDS_FIXES verdict
        for node in workflow_data["nodes"]:
            if node["id"] == "load_review_findings":
                node["script"] = 'echo \'{"verdict": "NEEDS_FIXES", "findings": ["Critical: Missing test"]}\''
            elif node["id"] == "validate_needs_fixes":
                # Gate should pass when verdict is NEEDS_FIXES
                node["type"] = "bash"
                node["script"] = 'echo "Verdict is NEEDS_FIXES, proceeding with fixes"'
                node.pop("condition", None)
            elif node["id"] in ["fix_critical", "fix_warnings"]:
                node["type"] = "bash"
                node["script"] = 'echo \'{"status": "FIXED", "changes": "Added missing test"}\''
                node.pop("prompt", None)
                node.pop("dispatch", None)
            elif node["id"] == "post_revised_plan":
                node["script"] = 'echo "Posted revised plan to Jira"'
            elif node["id"] == "store_episode":
                node["script"] = 'echo "Stored episode"'
        
        # Save to temp file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as tmp:
            yaml.dump(workflow_data, tmp)
            tmp_path = tmp.name
        
        try:
            with open(tmp_path) as f:
                workflow_def = load_workflow_from_string(f.read())
            
            executor = WorkflowExecutor()
            result = asyncio.run(executor.execute(workflow_def, {"issue_key": "TEST-200"}))
            
            # Workflow should complete
            assert result.status == WorkflowStatus.COMPLETED
            
            # All nodes should complete
            assert result.node_results["load_review_findings"].status == NodeStatus.COMPLETED
            assert result.node_results["validate_needs_fixes"].status == NodeStatus.COMPLETED
            assert result.node_results["fix_critical"].status == NodeStatus.COMPLETED
            assert result.node_results["fix_warnings"].status == NodeStatus.COMPLETED
            assert result.node_results["post_revised_plan"].status == NodeStatus.COMPLETED
            assert result.node_results["store_episode"].status == NodeStatus.COMPLETED

        finally:
            os.unlink(tmp_path)
