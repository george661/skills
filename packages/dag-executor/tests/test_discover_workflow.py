"""Tests for the discover.yaml workflow definition.

Validates that the YAML-based discover workflow DAG parses correctly,
has proper node ordering, interrupt node configuration, conditional edge logic,
state channels, and issues router usage.
"""
from pathlib import Path
from typing import Dict

import pytest

from dag_executor.graph import topological_sort_with_layers
from dag_executor.parser import load_workflow
from dag_executor.schema import (
    ChannelFieldDef,
    NodeDef,
    TriggerRule,
    WorkflowDef,
)


def _channel(workflow: WorkflowDef, key: str) -> ChannelFieldDef:
    """Fetch a ChannelFieldDef from workflow.state (narrows the union for type checkers)."""
    field = workflow.state[key]
    assert isinstance(field, ChannelFieldDef), f"{key} must be a ChannelFieldDef"
    return field


WORKFLOW_PATH = str(
    Path(__file__).parent.parent / "workflows" / "discover.yaml"
)


@pytest.fixture
def workflow() -> WorkflowDef:
    """Load and return the discover.yaml workflow definition."""
    return load_workflow(WORKFLOW_PATH)


@pytest.fixture
def nodes_by_id(workflow: WorkflowDef) -> Dict[str, NodeDef]:
    """Return workflow nodes indexed by ID."""
    return {n.id: n for n in workflow.nodes}


class TestWorkflowParsing:
    """Test 1-3: YAML parses without errors and has correct structure."""

    def test_parses_successfully(self, workflow: WorkflowDef) -> None:
        """discover.yaml loads with no validation errors and has >=8 nodes."""
        assert workflow.name == "Discover Command Workflow"
        assert len(workflow.nodes) >= 8  # At least the 8 planned nodes

    def test_config_valid(self, workflow: WorkflowDef) -> None:
        """Workflow config has correct checkpoint prefix."""
        assert workflow.config.checkpoint_prefix == "discover"

    def test_no_hardcoded_tenant_paths(self, workflow: WorkflowDef) -> None:
        """No literal gw-docs or hardcoded gw namespace in workflow."""
        # Check all node scripts and env for hardcoded paths
        for node in workflow.nodes:
            if hasattr(node, 'script') and node.script:
                assert 'gw-docs' not in node.script, \
                    f"Node {node.id} has hardcoded gw-docs path"
                assert not node.script.startswith('/gw/'), \
                    f"Node {node.id} has hardcoded /gw/ path"
            if hasattr(node, 'message') and node.message:
                assert 'gw-docs' not in node.message.lower(), \
                    f"Node {node.id} message has hardcoded gw-docs"


class TestTopologicalOrdering:
    """Test 4: Topological sort produces correct phase ordering."""

    def test_phase_ordering(self, workflow: WorkflowDef, nodes_by_id: Dict[str, NodeDef]) -> None:
        """Phases execute in correct order per the implementation plan."""
        layers = topological_sort_with_layers(workflow.nodes)
        flat_order = [nid for layer in layers for nid in layer]

        # Verify critical ordering constraints based on plan's node mapping
        def before(a: str, b: str) -> None:
            assert flat_order.index(a) < flat_order.index(b), (
                f"{a} must execute before {b}"
            )

        # Phase ordering: 0 → 1 → 2 → 3 → 4 → 4.5 → (conditional 5) → 6
        before("load_platform_context", "idea_interview")
        before("idea_interview", "duplicate_check")
        before("duplicate_check", "brief_writer")
        before("brief_writer", "roadmap_update")
        before("roadmap_update", "epic_decision")
        before("epic_decision", "finalize")
        before("create_epic", "finalize")

        # Verify finalize has trigger_rule: one_success for fan-in
        finalize = nodes_by_id["finalize"]
        assert finalize.trigger_rule == TriggerRule.ONE_SUCCESS, \
            "finalize must have trigger_rule: one_success for conditional fan-in"


class TestInterruptNode:
    """Test 5: Interrupt node for guided interview."""

    def test_idea_interview_is_interrupt(self, nodes_by_id: Dict[str, NodeDef]) -> None:
        """idea_interview node is interrupt type with resume_key and message."""
        interview = nodes_by_id["idea_interview"]
        assert interview.type == "interrupt", \
            "idea_interview must be interrupt type"
        assert hasattr(interview, 'resume_key') and interview.resume_key, \
            "idea_interview must have resume_key"
        assert interview.resume_key == "interview_answers", \
            "resume_key must be interview_answers"
        assert hasattr(interview, 'message') and interview.message, \
            "idea_interview must have non-empty message"
        assert hasattr(interview, 'channels') and interview.channels, \
            "idea_interview must specify channels"
        assert "terminal" in interview.channels, \
            "idea_interview must include terminal channel"


class TestConditionalEdge:
    """Test 6: Conditional edge for optional epic creation."""

    def test_epic_decision_has_conditional_edge(self, nodes_by_id: Dict[str, NodeDef]) -> None:
        """epic_decision has edges: conditional to create_epic and default to finalize."""
        epic_decision = nodes_by_id["epic_decision"]

        # Check that epic_decision has edges
        assert epic_decision.edges is not None, \
            "epic_decision must have edges for conditional routing"
        assert len(epic_decision.edges) >= 2, \
            "epic_decision must have at least 2 edges (conditional + default)"

        # Check for conditional edge to create_epic
        conditional_edge = next((e for e in epic_decision.edges
                                if hasattr(e, 'target') and e.target == "create_epic"
                                and hasattr(e, 'condition') and e.condition), None)
        assert conditional_edge is not None, \
            "Must have conditional edge from epic_decision to create_epic"

        # Verify condition uses Python-style boolean literals
        condition: str = conditional_edge.condition or ""
        assert "create_epic" in condition, \
            "Condition must reference create_epic field"
        # Check for Python-style True/False (not true/false or 1/0)
        assert "True" in condition or "False" in condition, \
            "Condition must use Python-style boolean literals (True/False)"

        # Check for default edge (to finalize)
        default_edge = next((e for e in epic_decision.edges
                           if hasattr(e, 'default') and e.default), None)
        assert default_edge is not None, \
            "Must have default edge from epic_decision"

        # Default edge should route to finalize
        assert (hasattr(default_edge, 'target') and default_edge.target == "finalize") or \
               (hasattr(default_edge, 'targets') and "finalize" in (default_edge.targets or [])), \
            "Default edge must route to finalize"


class TestSkillPaths:
    """Test 7: Skill invocations reference real skill directories.

    GW-5356: the prior test asserted a `skills/issues/` router alias that was
    never implemented. The live create_issue skill lives at
    `~/.claude/skills/jira/create_issue.ts`.
    """

    def test_create_epic_calls_real_skill(self, nodes_by_id: Dict[str, NodeDef]) -> None:
        create_epic = nodes_by_id["create_epic"]
        assert hasattr(create_epic, 'script') and create_epic.script, \
            "create_epic must have a script"
        assert "skills/jira/create_issue.ts" in create_epic.script, \
            "create_epic must call ~/.claude/skills/jira/create_issue.ts"
        assert "skills/issues/" not in create_epic.script, \
            "skills/issues/ alias was never implemented"


class TestExecutionWiring:
    """Test the runtime wiring of the conditional branch (execution-path correctness)."""

    def test_create_epic_has_explicit_dependency(self, nodes_by_id: Dict[str, NodeDef]) -> None:
        """create_epic must have depends_on so it is not a dangling root node.

        Regression: edges on the source node do not establish topological
        dependencies — depends_on is still required on the edge target.
        """
        create_epic = nodes_by_id["create_epic"]
        assert create_epic.depends_on, (
            "create_epic must declare depends_on; edges from epic_decision do "
            "not create topological dependencies by themselves"
        )
        assert "epic_decision" in create_epic.depends_on, (
            "create_epic must depend on epic_decision (its edge source)"
        )

    def test_finalize_dependencies_survive_default_branch(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """finalize must run on BOTH branches from epic_decision.

        Regression: if finalize depends only on create_epic with trigger_rule=one_success,
        the default branch (epic NOT created) skips create_epic and finalize runs never.
        finalize must depend on at least one node that is COMPLETED on the default branch.
        """
        finalize = nodes_by_id["finalize"]
        assert finalize.depends_on, "finalize must declare depends_on"
        assert "epic_decision" in finalize.depends_on, (
            "finalize must depend on epic_decision so it runs when the default "
            "edge (skip epic) is taken — otherwise one_success never fires"
        )

    def test_create_epic_script_uses_safe_json_construction(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """create_epic script must build JSON with jq, not via shell-quoted string concat.

        Regression: '{"project": "${TENANT_PROJECT}", "summary": "'"$x"'"}' is
        broken on two fronts: single quotes prevent env-var expansion, and
        string concat breaks on any special character in user input.
        """
        script: str = nodes_by_id["create_epic"].script or ""
        # Must invoke jq to build the request payload
        assert "jq -n" in script or "jq --arg" in script, (
            "create_epic must build request JSON with jq to safely escape user input"
        )
        # Must not embed ${TENANT_PROJECT} inside single-quoted JSON (single quotes
        # suppress shell variable expansion — the literal "${TENANT_PROJECT}" ends up
        # in the request payload).
        if "'{" in script and "}'" in script:
            single_quoted = script.split("'{", 1)[1].split("}'", 1)[0]
            assert "${TENANT_PROJECT}" not in single_quoted, (
                "TENANT_PROJECT must not be embedded inside single-quoted JSON "
                "(shell will not expand it)"
            )


class TestStateChannels:
    """Test 8: State channels have correct reducers."""

    def test_channels_have_correct_reducers(self, workflow: WorkflowDef) -> None:
        """State channels use correct reducer types per plan."""
        assert "interview_answers" in workflow.state
        assert "brief_output" in workflow.state
        assert "overlaps" in workflow.state

        interview_answers = _channel(workflow, "interview_answers")
        assert interview_answers.reducer is not None
        assert interview_answers.reducer.strategy.value == "overwrite", \
            "interview_answers must use overwrite reducer"

        brief_output = _channel(workflow, "brief_output")
        assert brief_output.reducer is not None
        assert brief_output.reducer.strategy.value == "overwrite", \
            "brief_output must use overwrite reducer"

        overlaps = _channel(workflow, "overlaps")
        assert overlaps.reducer is not None
        assert overlaps.reducer.strategy.value == "append", \
            "overlaps must use append reducer"
        assert overlaps.default == [], \
            "overlaps must have default empty list"
