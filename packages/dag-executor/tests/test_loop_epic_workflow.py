"""Tests for the loop-epic.yaml workflow definition.

Validates that the YAML-based loop-epic workflow parses correctly, has proper
progress channels, and iterator pattern.
"""
from pathlib import Path
from typing import Dict

import pytest

from dag_executor.graph import topological_sort_with_layers
from dag_executor.parser import load_workflow
from dag_executor.schema import (
    NodeDef,
    ReducerStrategy,
    TriggerRule,
    WorkflowDef,
)


WORKFLOW_PATH = str(
    Path(__file__).parent.parent / "workflows" / "loop-epic.yaml"
)


@pytest.fixture
def workflow() -> WorkflowDef:
    """Load and return the loop-epic.yaml workflow definition."""
    return load_workflow(WORKFLOW_PATH)


@pytest.fixture
def nodes_by_id(workflow: WorkflowDef) -> Dict[str, NodeDef]:
    """Return workflow nodes indexed by ID."""
    return {n.id: n for n in workflow.nodes}


class TestWorkflowParsing:
    """Test 1: YAML parses without errors and has correct structure."""

    def test_parses_successfully(self, workflow: WorkflowDef) -> None:
        """loop-epic.yaml loads with no validation errors."""
        assert workflow.name == "Loop Epic Workflow"
        assert len(workflow.nodes) >= 5  # At least core nodes

    def test_checkpoint_prefix(self, workflow: WorkflowDef) -> None:
        """Workflow config has correct checkpoint prefix."""
        assert workflow.config.checkpoint_prefix == "loop-epic"


class TestStateChannels:
    """Test 2: epic_issues and progress channels correct."""

    def test_epic_issues_channel(self, workflow: WorkflowDef) -> None:
        """epic_issues channel is list with overwrite."""
        ch = workflow.state["epic_issues"]
        assert ch.type == "list"
        assert ch.reducer.strategy == ReducerStrategy.OVERWRITE

    def test_completed_issues_channel(self, workflow: WorkflowDef) -> None:
        """completed_issues channel is list with append."""
        ch = workflow.state["completed_issues"]
        assert ch.type == "list"
        assert ch.reducer.strategy == ReducerStrategy.APPEND
        assert ch.default == []

    def test_blocked_issues_channel(self, workflow: WorkflowDef) -> None:
        """blocked_issues channel is list with append."""
        ch = workflow.state["blocked_issues"]
        assert ch.type == "list"
        assert ch.reducer.strategy == ReducerStrategy.APPEND
        assert ch.default == []

    def test_waiting_issues_channel(self, workflow: WorkflowDef) -> None:
        """waiting_issues channel is list with append."""
        ch = workflow.state["waiting_issues"]
        assert ch.type == "list"
        assert ch.reducer.strategy == ReducerStrategy.APPEND
        assert ch.default == []

    def test_progress_channel(self, workflow: WorkflowDef) -> None:
        """progress channel is dict with overwrite."""
        ch = workflow.state["progress"]
        assert ch.type == "dict"
        assert ch.reducer.strategy == ReducerStrategy.OVERWRITE

    def test_epic_status_channel(self, workflow: WorkflowDef) -> None:
        """epic_status channel is string with overwrite."""
        ch = workflow.state["epic_status"]
        assert ch.type == "string"
        assert ch.reducer.strategy == ReducerStrategy.OVERWRITE


class TestNodeChannelUsage:
    """Test 3: iterate_issues reads epic_issues, writes to completed/blocked/waiting."""

    def test_fetch_epic_children_writes_epic_issues(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """fetch_epic_children writes epic_issues."""
        node = nodes_by_id["fetch_epic_children"]
        assert "epic_issues" in node.writes

    def test_iterate_issues_reads_epic_issues(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """iterate_issues reads epic_issues."""
        node = nodes_by_id["iterate_issues"]
        assert "epic_issues" in node.reads

    def test_iterate_issues_writes_progress_channels(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """iterate_issues writes to completed_issues, blocked_issues, waiting_issues."""
        node = nodes_by_id["iterate_issues"]
        assert "completed_issues" in node.writes
        assert "blocked_issues" in node.writes
        assert "waiting_issues" in node.writes


class TestValidateEpicCompletionDependency:
    """Test 4: validate_epic_completion depends on iterate_issues."""

    def test_validate_epic_completion_depends_on_iterate_issues(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """validate_epic_completion depends on iterate_issues."""
        node = nodes_by_id["validate_epic_completion"]
        assert "iterate_issues" in node.depends_on


class TestTopologicalOrdering:
    """Test 5: Topological sort produces correct ordering."""

    def test_phase_ordering(self, workflow: WorkflowDef) -> None:
        """Phases execute in correct order: fetch → confidence → iterate → validate → summary."""
        layers = topological_sort_with_layers(workflow.nodes)
        flat_order = [nid for layer in layers for nid in layer]

        def before(a: str, b: str) -> None:
            assert flat_order.index(a) < flat_order.index(b), (
                f"{a} must execute before {b}"
            )

        before("fetch_epic_children", "confidence_check")
        before("confidence_check", "iterate_issues")
        before("iterate_issues", "validate_epic_completion")
        before("validate_epic_completion", "print_summary")


class TestStoreEpisode:
    """Test 6: store_episode uses trigger_rule: all_done."""

    def test_store_episode_trigger_rule(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """store_episode uses trigger_rule: all_done."""
        node = nodes_by_id["store_episode"]
        assert node.trigger_rule == TriggerRule.ALL_DONE
