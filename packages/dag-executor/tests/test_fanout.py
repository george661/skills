"""Tests for multi-target fan-out edges."""
import asyncio
import pytest
from dag_executor.executor import WorkflowExecutor
from dag_executor.parser import load_workflow_from_string
from dag_executor.schema import NodeStatus, WorkflowStatus


class TestFanout:
    """Test multi-target fan-out edge functionality."""

    def test_multi_target_fanout_activates_both_targets(self) -> None:
        """Multi-target edge activates ALL targets simultaneously."""
        workflow_yaml = """
name: test-fanout
config:
  checkpoint_prefix: test
nodes:
  - id: source
    name: Source Node
    type: bash
    script: echo "test"
    edges:
      - targets: ["target_a", "target_b"]
        default: true
  
  - id: target_a
    name: Target A
    type: bash
    script: echo "A"
  
  - id: target_b
    name: Target B
    type: bash
    script: echo "B"
"""
        workflow_def = load_workflow_from_string(workflow_yaml)
        executor = WorkflowExecutor()
        result = asyncio.run(executor.execute(workflow_def, {}))
        
        assert result.status == WorkflowStatus.COMPLETED
        # Both targets should be executed
        assert result.node_results["target_a"].status == NodeStatus.COMPLETED
        assert result.node_results["target_b"].status == NodeStatus.COMPLETED

    def test_single_target_still_works(self) -> None:
        """Single-target edge still works (backwards compat)."""
        workflow_yaml = """
name: test-single-target
config:
  checkpoint_prefix: test
nodes:
  - id: source
    name: Source Node
    type: bash
    script: echo "test"
    edges:
      - target: "single_target"
        default: true
  
  - id: single_target
    name: Single Target
    type: bash
    script: echo "single"
"""
        workflow_def = load_workflow_from_string(workflow_yaml)
        executor = WorkflowExecutor()
        result = asyncio.run(executor.execute(workflow_def, {}))
        
        assert result.status == WorkflowStatus.COMPLETED
        assert result.node_results["single_target"].status == NodeStatus.COMPLETED

    def test_conditional_fanout(self) -> None:
        """Conditional fan-out combines condition + multi-target."""
        workflow_yaml = """
name: test-conditional-fanout
config:
  checkpoint_prefix: test
state:
  severity:
    strategy: overwrite
nodes:
  - id: assess
    name: Assess
    type: bash
    script: 'echo ''{"severity": "high"}'''
    output_format: json
    edges:
      - targets: ["alert", "escalate"]
        condition: assess.severity == "high"
      - target: "log"
        default: true
  
  - id: alert
    name: Alert
    type: bash
    script: echo "alert"
  
  - id: escalate
    name: Escalate
    type: bash
    script: echo "escalate"
  
  - id: log
    name: Log
    type: bash
    script: echo "log"
"""
        workflow_def = load_workflow_from_string(workflow_yaml)
        executor = WorkflowExecutor()
        result = asyncio.run(executor.execute(workflow_def, {}))
        
        assert result.status == WorkflowStatus.COMPLETED
        # High severity → both alert and escalate should execute
        assert result.node_results["alert"].status == NodeStatus.COMPLETED
        assert result.node_results["escalate"].status == NodeStatus.COMPLETED
        # Log should be skipped (not default branch)
        assert result.node_results["log"].status == NodeStatus.SKIPPED
