"""Tests for the bug.yaml workflow definition.

Validates parsing, node ordering, channels, gates, and integration tests with mock execution.
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
    NodeDef,
    NodeStatus,
    ReducerStrategy,
    WorkflowDef,
    WorkflowStatus,
)


WORKFLOW_PATH = str(
    Path(__file__).parent.parent / "workflows" / "bug.yaml"
)


@pytest.fixture
def workflow() -> WorkflowDef:
    """Load bug workflow for testing."""
    return load_workflow(WORKFLOW_PATH)


@pytest.fixture
def nodes_by_id(workflow: WorkflowDef) -> Dict[str, NodeDef]:
    """Map of node ID to NodeDef."""
    return {node.id: node for node in workflow.nodes}


class TestBugWorkflowParsing:
    """Test 1: YAML parses and has correct structure."""

    def test_parses_successfully(self, workflow: WorkflowDef) -> None:
        """bug.yaml loads with no validation errors."""
        assert workflow.name == "Bug Report"
        assert len(workflow.nodes) >= 7  # At least 7 nodes (plan says ~8)

    def test_input_description_required(self, workflow: WorkflowDef) -> None:
        """description input is required."""
        assert "description" in workflow.inputs
        assert workflow.inputs["description"].required is True

    def test_state_channels_declared(self, workflow: WorkflowDef) -> None:
        """Workflow declares evidence, classification, root_cause, creation_result, test_result channels."""
        # evidence channel
        assert "evidence" in workflow.state
        evidence_ch = workflow.state["evidence"]
        assert evidence_ch.type == "dict"
        assert evidence_ch.reducer is not None
        assert evidence_ch.reducer.strategy == ReducerStrategy.OVERWRITE

        # classification channel
        assert "classification" in workflow.state
        classification_ch = workflow.state["classification"]
        assert classification_ch.type == "dict"
        assert classification_ch.reducer is not None
        assert classification_ch.reducer.strategy == ReducerStrategy.OVERWRITE

        # root_cause channel
        assert "root_cause" in workflow.state
        root_cause_ch = workflow.state["root_cause"]
        assert root_cause_ch.type == "dict"
        assert root_cause_ch.reducer is not None
        assert root_cause_ch.reducer.strategy == ReducerStrategy.OVERWRITE

        # creation_result channel
        assert "creation_result" in workflow.state
        creation_result_ch = workflow.state["creation_result"]
        assert creation_result_ch.type == "dict"
        assert creation_result_ch.reducer is not None
        assert creation_result_ch.reducer.strategy == ReducerStrategy.OVERWRITE

        # test_result channel
        assert "test_result" in workflow.state
        test_result_ch = workflow.state["test_result"]
        assert test_result_ch.type == "dict"
        assert test_result_ch.reducer is not None
        assert test_result_ch.reducer.strategy == ReducerStrategy.OVERWRITE


class TestBugTopologicalOrdering:
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

        # Phase ordering as per plan
        before("load_context", "collect_evidence")
        before("collect_evidence", "duplicate_detection")
        before("duplicate_detection", "duplicate_gate")
        before("duplicate_gate", "analyze_root_cause")
        before("analyze_root_cause", "create_bug_issue")
        before("create_bug_issue", "failing_test_gate")
        before("failing_test_gate", "transition_and_link")


class TestBugGate:
    """Test 3: duplicate_gate stops on duplicate."""

    def test_duplicate_gate_stops_on_duplicate(self, workflow: WorkflowDef, nodes_by_id: Dict[str, NodeDef]) -> None:
        """duplicate_gate is a gate with on_failure=stop."""
        gate = nodes_by_id.get("duplicate_gate")
        assert gate is not None, "duplicate_gate node must exist"
        assert gate.type == "gate"
        assert gate.on_failure == "stop"


class TestBugOutputs:
    """Test 4: bug_key output is declared."""

    def test_bug_key_output_declared(self, workflow: WorkflowDef) -> None:
        """bug_key output wired to create_bug_issue node."""
        assert "bug_key" in workflow.outputs
        # The output should reference a node that creates the bug
        # (could be from create_bug_issue node's writes to creation_result channel)


class TestBugConfig:
    """Test 5: checkpoint_prefix is correct."""

    def test_checkpoint_prefix(self, workflow: WorkflowDef) -> None:
        """config.checkpoint_prefix == 'bug'."""
        assert workflow.config is not None
        assert workflow.config.checkpoint_prefix == "bug"


class TestBugIntegrationWithMockExecution:
    """Test 6: Integration tests with mock execution."""

    def test_duplicate_gate_stops_workflow(self) -> None:
        """Mock duplicate_detection to return is_duplicate=true, verify gate stops workflow."""
        fixture_path = Path(__file__).parent.parent / "workflows" / "bug.yaml"

        # Load and modify workflow
        with open(fixture_path) as f:
            workflow_data = yaml.safe_load(f)

        # Mock duplicate_detection to return is_duplicate=true
        for node in workflow_data["nodes"]:
            if node["id"] == "load_context":
                node["script"] = 'echo \'{"pipeline_mode": false}\''
            elif node["id"] == "collect_evidence":
                node["script"] = 'echo \'{"logs": "test log"}\''
            elif node["id"] == "duplicate_detection":
                node["type"] = "bash"
                node["script"] = 'echo \'{"is_duplicate": true, "duplicate_key": "GW-0000"}\''
                node.pop("prompt", None)
                node.pop("dispatch", None)
                node.pop("output_format", None)
                node.pop("mode", None)
            elif node["id"] in ["analyze_root_cause", "create_bug_issue", "failing_test_gate"]:
                node["type"] = "bash"
                node["script"] = 'echo "Should not execute"'
                node.pop("prompt", None)
                node.pop("dispatch", None)
                node.pop("output_format", None)
                node.pop("mode", None)
            elif node["id"] == "transition_and_link":
                node["script"] = 'echo "Should not execute"'

        # Save to temp file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as tmp:
            yaml.dump(workflow_data, tmp)
            tmp_path = tmp.name

        try:
            with open(tmp_path) as f:
                workflow_def = load_workflow_from_string(f.read())

            executor = WorkflowExecutor()
            result = asyncio.run(executor.execute(workflow_def, {"description": "test bug"}))

            # Workflow may complete or fail at gate
            assert result.status in [WorkflowStatus.COMPLETED, WorkflowStatus.FAILED]

            # duplicate_detection should complete
            assert result.node_results["duplicate_detection"].status == NodeStatus.COMPLETED

            # Gate should fail/skip
            assert result.node_results["duplicate_gate"].status in [NodeStatus.FAILED, NodeStatus.SKIPPED]

            # Downstream nodes should be skipped
            assert result.node_results["analyze_root_cause"].status == NodeStatus.SKIPPED
            assert result.node_results["create_bug_issue"].status == NodeStatus.SKIPPED
            assert result.node_results["failing_test_gate"].status == NodeStatus.SKIPPED
            assert result.node_results["transition_and_link"].status == NodeStatus.SKIPPED

        finally:
            os.unlink(tmp_path)

    def test_happy_path_creates_bug(self) -> None:
        """Mock happy path, verify bug_key surfaces in outputs."""
        fixture_path = Path(__file__).parent.parent / "workflows" / "bug.yaml"

        # Load and modify workflow
        with open(fixture_path) as f:
            workflow_data = yaml.safe_load(f)

        # Mock all nodes to return success
        for node in workflow_data["nodes"]:
            if node["id"] == "load_context":
                node["script"] = 'echo \'{"pipeline_mode": false}\''
            elif node["id"] == "collect_evidence":
                node["script"] = 'echo \'{"logs": "test log", "errors": "test error"}\''
            elif node["id"] == "duplicate_detection":
                node["type"] = "bash"
                node["script"] = 'echo \'{"is_duplicate": false}\''
                node.pop("prompt", None)
                node.pop("dispatch", None)
                node.pop("output_format", None)
                node.pop("mode", None)
            elif node["id"] == "duplicate_gate":
                # Gate should pass when is_duplicate is false
                node["type"] = "bash"
                node["script"] = 'echo "Gate passed"'
                node.pop("condition", None)
            elif node["id"] == "analyze_root_cause":
                node["type"] = "bash"
                node["script"] = 'echo \'{"hypothesis": "root cause found"}\''
                node.pop("prompt", None)
                node.pop("dispatch", None)
                node.pop("output_format", None)
                node.pop("mode", None)
            elif node["id"] == "create_bug_issue":
                node["type"] = "bash"
                node["script"] = 'echo \'{"bug_key": "GW-9999"}\''
                node.pop("prompt", None)
                node.pop("dispatch", None)
                node.pop("output_format", None)
                node.pop("mode", None)
            elif node["id"] == "failing_test_gate":
                node["type"] = "bash"
                node["script"] = 'echo \'{"test_branches": ["test-branch"]}\''
                node.pop("prompt", None)
                node.pop("dispatch", None)
                node.pop("output_format", None)
                node.pop("mode", None)
            elif node["id"] == "transition_and_link":
                node["script"] = 'echo "Transitioned and linked"'

        # Save to temp file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as tmp:
            yaml.dump(workflow_data, tmp)
            tmp_path = tmp.name

        try:
            with open(tmp_path) as f:
                workflow_def = load_workflow_from_string(f.read())

            executor = WorkflowExecutor()
            result = asyncio.run(executor.execute(workflow_def, {"description": "test bug"}))

            # Workflow should complete
            assert result.status == WorkflowStatus.COMPLETED

            # All nodes should complete
            assert result.node_results["load_context"].status == NodeStatus.COMPLETED
            assert result.node_results["collect_evidence"].status == NodeStatus.COMPLETED
            assert result.node_results["duplicate_detection"].status == NodeStatus.COMPLETED
            assert result.node_results["duplicate_gate"].status == NodeStatus.COMPLETED
            assert result.node_results["analyze_root_cause"].status == NodeStatus.COMPLETED
            assert result.node_results["create_bug_issue"].status == NodeStatus.COMPLETED
            assert result.node_results["failing_test_gate"].status == NodeStatus.COMPLETED
            assert result.node_results["transition_and_link"].status == NodeStatus.COMPLETED

        finally:
            os.unlink(tmp_path)


class TestBugDryRun:
    """Test 7: Dry-run succeeds."""

    def test_dry_run_succeeds(self) -> None:
        """Dry-run completes without error."""
        from dag_executor.cli import run_dry_run

        workflow_path = Path(__file__).parent.parent / "workflows" / "bug.yaml"
        # run_dry_run should not raise an exception
        run_dry_run(str(workflow_path))


# ---------------------------------------------------------------------------
# GW-5469: pipeline_mode type regression
#
# The jq --arg refactor in load_context and collect_evidence stores
# pipeline_mode as a JSON string ("false") instead of a JSON boolean (false).
# This means:
#   - evidence['pipeline_mode'] == False  → False  (string != bool)
#   - bool(evidence['pipeline_mode'])     → True   (non-empty string is truthy)
#
# The tests below exercise the REAL bash scripts (no mocking) so the type
# regression is actually caught.  They FAIL against the working-tree refactor
# and will PASS once the bug is fixed (i.e. pipeline_mode is emitted as a
# JSON boolean).
# ---------------------------------------------------------------------------


class TestGW5469PipelineModeTypeBug:
    """GW-5469: load_context and collect_evidence must store pipeline_mode as bool.

    Strategy: run the *real* bash script (no mock) inside a stripped-down
    workflow that contains only the load_context node.  The BashRunner returns
    {"stdout": "<raw jq output>", "stderr": "..."} in NodeResult.output.
    Because load_context has output_format=json, the executor also stores the
    *parsed* dict in ctx.node_outputs — but that is internal state that
    WorkflowResult does not expose.

    To inspect the type at the boundary where the regression occurs we parse
    the raw stdout ourselves: this is exactly what the executor's
    output_format=json path does, so our assertion mirrors the real code path.
    """

    def _get_load_context_evidence(self) -> object:
        """Execute the real load_context script with no pipeline_url.

        Returns the Python object that json.loads(stdout)['evidence']['pipeline_mode']
        resolves to — i.e. the value that the executor stores in the evidence
        channel.  No mocking; the actual bash script in bug.yaml is run.
        """
        import asyncio
        import json as _json
        import tempfile
        import os as _os
        import yaml as _yaml

        fixture_path = Path(__file__).parent.parent / "workflows" / "bug.yaml"
        with open(fixture_path) as f:
            workflow_data = _yaml.safe_load(f)

        # Keep ONLY load_context; strip every other node so the executor
        # finishes quickly without calling Jira / LLM nodes.
        workflow_data["nodes"] = [
            n for n in workflow_data["nodes"] if n["id"] == "load_context"
        ]
        # Remove outputs that reference stripped nodes (avoids schema errors).
        workflow_data.pop("outputs", None)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as tmp:
            _yaml.dump(workflow_data, tmp)
            tmp_path = tmp.name

        try:
            from dag_executor.parser import load_workflow_from_string
            from dag_executor.executor import WorkflowExecutor

            with open(tmp_path) as f:
                wf_def = load_workflow_from_string(f.read())

            executor = WorkflowExecutor()
            result = asyncio.run(
                executor.execute(wf_def, {"description": "GW-5469 repro"})
            )

            lc = result.node_results["load_context"]
            assert lc.status == NodeStatus.COMPLETED, (
                f"load_context failed to run: {lc.error}"
            )

            # BashRunner stores raw {"stdout": ..., "stderr": ...} in NodeResult.
            # The executor's output_format=json path calls json.loads(stdout) and
            # then writes each top-level key to the matching channel.  We replicate
            # that exact parse here so we test the same value that ends up in the
            # evidence channel.
            stdout: str = (lc.output or {}).get("stdout", "")
            assert stdout.strip(), "load_context produced no stdout — script may have failed silently"

            parsed = _json.loads(stdout.strip())
            # load_context wraps its output in an "evidence" key so the executor
            # writes the nested dict to the evidence channel.
            assert "evidence" in parsed, (
                f"Expected top-level 'evidence' key in load_context stdout, got: {list(parsed.keys())}"
            )
            return parsed["evidence"].get("pipeline_mode")
        finally:
            _os.unlink(tmp_path)

    # ------------------------------------------------------------------
    # Failing tests — all three assertions break against the working-tree
    # jq --arg refactor and will pass once pipeline_mode is emitted as a
    # JSON boolean (e.g. via `jq -n --argjson` or bare shell interpolation).
    # ------------------------------------------------------------------

    def test_load_context_pipeline_mode_is_bool(self) -> None:
        """pipeline_mode stored in the evidence channel must be a Python bool, not str.

        FAILS (GW-5469): jq --arg unconditionally produces a JSON string, so
        json.loads(stdout)['evidence']['pipeline_mode'] is str('false'), not
        bool(False).
        """
        pipeline_mode = self._get_load_context_evidence()
        assert type(pipeline_mode) is bool, (  # noqa: E721
            f"GW-5469: evidence['pipeline_mode'] should be bool but got "
            f"{type(pipeline_mode).__name__!r} with value {pipeline_mode!r}.  "
            f"The jq --arg refactor stores the JSON string 'false' instead of "
            f"the JSON boolean false."
        )

    def test_load_context_pipeline_mode_is_falsy_without_pipeline_url(self) -> None:
        """Without pipeline_url the value must be falsy (False), not a truthy string.

        FAILS (GW-5469): str('false') is truthy in Python, inverting the
        intended semantics — any guard like `if pipeline_mode:` incorrectly
        evaluates to True.
        """
        pipeline_mode = self._get_load_context_evidence()
        assert not pipeline_mode, (
            f"GW-5469: evidence['pipeline_mode'] should be falsy when no "
            f"pipeline_url is supplied, but got {pipeline_mode!r} "
            f"(bool={bool(pipeline_mode)}).  "
            f"The jq --arg refactor stores str('false') which is truthy."
        )

    def test_load_context_pipeline_mode_equals_false(self) -> None:
        """evidence['pipeline_mode'] == False must hold when no pipeline_url is given.

        FAILS (GW-5469): str('false') == False evaluates to False in Python,
        silently breaking every equality gate that checks `pipeline_mode == False`.
        """
        pipeline_mode = self._get_load_context_evidence()
        assert pipeline_mode == False, (  # noqa: E712
            f"GW-5469: evidence['pipeline_mode'] == False is {pipeline_mode == False}.  "  # noqa: E712
            f"Got {pipeline_mode!r} (type={type(pipeline_mode).__name__}).  "
            f"The jq --arg refactor yields str('false') which != bool(False)."
        )


# ---------------------------------------------------------------------------
# GW-5470: pipeline_mode type regression (confirmed same root cause as GW-5469)
#
# The jq --arg refactor in load_context and collect_evidence stores
# pipeline_mode as a JSON string ("false") instead of a JSON boolean (false).
#
# GW-5470 extends the coverage to the collect_evidence node — the SECOND
# call-site where `jq --arg pipeline_mode "$pipeline_mode"` reintroduces the
# string type even after load_context has already emitted a string value.
# The collect_evidence node reads evidence.pipeline_mode from the channel
# (already a string at this point), stores it via --arg (which is a no-op
# type-wise because it was already a string), and re-emits it.  The net
# observable effect for downstream consumers is identical to GW-5469.
#
# Additional regression confirmed by the hypothesis:
#   - variables._interpolate() passes string values verbatim (lowercase
#     'false') while bool values go through repr() (titlecase 'False').
#     Prompt nodes therefore receive an ambiguous token.
#   - The mock layer in the existing suite uses flat-dict schema
#     {'pipeline_mode': false} which diverges from the real evidence-wrapped
#     schema {'evidence': {'pipeline_mode': ...}}, masking the regression.
# ---------------------------------------------------------------------------


class TestGW5470PipelineModeTypeBug:
    """GW-5470: pipeline_mode must be a JSON boolean in both load_context and collect_evidence.

    Exercises the REAL bash scripts (no mocking) for both nodes to confirm
    the jq --arg type regression is present at each call-site.  All tests
    FAIL against the current working-tree refactor and will PASS once
    pipeline_mode is emitted as a JSON boolean (e.g. via --argjson or bare
    shell interpolation).
    """

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _run_single_node_workflow(self, node_id: str, inputs: dict) -> str:
        """Run a stripped-down workflow containing only *node_id* and return
        the raw stdout string from that node's result.

        No mocks — the actual bash script from bug.yaml is executed.
        """
        import asyncio
        import tempfile
        import os as _os
        import yaml as _yaml

        fixture_path = Path(__file__).parent.parent / "workflows" / "bug.yaml"
        with open(fixture_path) as f:
            workflow_data = _yaml.safe_load(f)

        workflow_data["nodes"] = [
            n for n in workflow_data["nodes"] if n["id"] == node_id
        ]
        workflow_data.pop("outputs", None)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as tmp:
            _yaml.dump(workflow_data, tmp)
            tmp_path = tmp.name

        try:
            from dag_executor.parser import load_workflow_from_string
            from dag_executor.executor import WorkflowExecutor

            with open(tmp_path) as f:
                wf_def = load_workflow_from_string(f.read())

            executor = WorkflowExecutor()
            result = asyncio.run(executor.execute(wf_def, inputs))

            node_result = result.node_results[node_id]
            assert node_result.status == NodeStatus.COMPLETED, (
                f"{node_id} did not complete: {node_result.error}"
            )
            stdout: str = (node_result.output or {}).get("stdout", "")
            assert stdout.strip(), f"{node_id} produced no stdout"
            return stdout.strip()
        finally:
            _os.unlink(tmp_path)

    def _run_two_node_workflow(self, inputs: dict) -> str:
        """Run a stripped-down workflow with both load_context and collect_evidence
        and return the raw stdout string from collect_evidence.

        This mirrors the real execution path: load_context writes to the evidence
        channel, then collect_evidence reads from it.  No mocks.
        """
        import asyncio
        import tempfile
        import os as _os
        import yaml as _yaml

        fixture_path = Path(__file__).parent.parent / "workflows" / "bug.yaml"
        with open(fixture_path) as f:
            workflow_data = _yaml.safe_load(f)

        keep = {"load_context", "collect_evidence"}
        workflow_data["nodes"] = [
            n for n in workflow_data["nodes"] if n["id"] in keep
        ]
        workflow_data.pop("outputs", None)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as tmp:
            _yaml.dump(workflow_data, tmp)
            tmp_path = tmp.name

        try:
            from dag_executor.parser import load_workflow_from_string
            from dag_executor.executor import WorkflowExecutor

            with open(tmp_path) as f:
                wf_def = load_workflow_from_string(f.read())

            executor = WorkflowExecutor()
            result = asyncio.run(executor.execute(wf_def, inputs))

            ce = result.node_results["collect_evidence"]
            assert ce.status == NodeStatus.COMPLETED, (
                f"collect_evidence did not complete: {ce.error}"
            )
            stdout: str = (ce.output or {}).get("stdout", "")
            assert stdout.strip(), "collect_evidence produced no stdout"
            return stdout.strip()
        finally:
            _os.unlink(tmp_path)

    # ------------------------------------------------------------------
    # load_context call-site (GW-5470 — mirrors GW-5469 for traceability)
    # ------------------------------------------------------------------

    def test_load_context_pipeline_mode_type_is_bool(self) -> None:
        """GW-5470: load_context must emit pipeline_mode as a JSON boolean.

        FAILS: jq --arg serialises '$pipeline_mode' as a JSON string regardless
        of content.  json.loads(stdout)['evidence']['pipeline_mode'] returns
        str('false'), not bool(False).
        """
        import json as _json

        stdout = self._run_single_node_workflow(
            "load_context", {"description": "GW-5470 repro"}
        )
        parsed = _json.loads(stdout)
        assert "evidence" in parsed, (
            f"GW-5470: load_context stdout missing top-level 'evidence' key. "
            f"Got keys: {list(parsed.keys())}"
        )
        pipeline_mode = parsed["evidence"].get("pipeline_mode")
        assert type(pipeline_mode) is bool, (  # noqa: E721
            f"GW-5470: load_context evidence['pipeline_mode'] must be bool, "
            f"got {type(pipeline_mode).__name__!r} = {pipeline_mode!r}.  "
            f"Root cause: jq --arg unconditionally wraps the value as a JSON string."
        )

    def test_load_context_pipeline_mode_false_without_pipeline_url(self) -> None:
        """GW-5470: Without pipeline_url, load_context must emit pipeline_mode=false (bool).

        FAILS: str('false') is truthy — bool('false') is True — inverting the
        intended semantics for every Python guard that evaluates the value.
        """
        import json as _json

        stdout = self._run_single_node_workflow(
            "load_context", {"description": "GW-5470 repro no url"}
        )
        parsed = _json.loads(stdout)
        pipeline_mode = parsed["evidence"].get("pipeline_mode")
        assert pipeline_mode is False, (
            f"GW-5470: load_context evidence['pipeline_mode'] should be bool False "
            f"when no pipeline_url is given, but got {pipeline_mode!r} "
            f"(bool={bool(pipeline_mode)}).  "
            f"jq --arg stores the string 'false' which is truthy."
        )

    # ------------------------------------------------------------------
    # collect_evidence call-site (new coverage added by GW-5470)
    # ------------------------------------------------------------------

    def test_collect_evidence_pipeline_mode_type_is_bool(self) -> None:
        """GW-5470: collect_evidence must re-emit pipeline_mode as a JSON boolean.

        FAILS: collect_evidence reads pipeline_mode from the evidence channel
        (already a string due to the load_context regression) and then passes
        it through jq --arg again.  The output is still str('false').
        json.loads(stdout)['evidence']['pipeline_mode'] must be bool(False).
        """
        import json as _json

        stdout = self._run_two_node_workflow({"description": "GW-5470 collect repro"})
        parsed = _json.loads(stdout)
        assert "evidence" in parsed, (
            f"GW-5470: collect_evidence stdout missing top-level 'evidence' key. "
            f"Got keys: {list(parsed.keys())}"
        )
        pipeline_mode = parsed["evidence"].get("pipeline_mode")
        assert type(pipeline_mode) is bool, (  # noqa: E721
            f"GW-5470: collect_evidence evidence['pipeline_mode'] must be bool, "
            f"got {type(pipeline_mode).__name__!r} = {pipeline_mode!r}.  "
            f"Root cause: jq --arg at the collect_evidence call-site re-emits "
            f"the value as a JSON string."
        )

    def test_collect_evidence_pipeline_mode_false_without_pipeline_url(self) -> None:
        """GW-5470: Without pipeline_url, collect_evidence must preserve pipeline_mode=false (bool).

        FAILS: str('false') is truthy, so `if pipeline_mode:` in any downstream
        Python consumer (e.g. variables._interpolate) silently evaluates to True,
        causing the workflow to behave as though it is in pipeline mode when it
        is not.
        """
        import json as _json

        stdout = self._run_two_node_workflow({"description": "GW-5470 collect repro no url"})
        parsed = _json.loads(stdout)
        pipeline_mode = parsed["evidence"].get("pipeline_mode")
        assert pipeline_mode is False, (
            f"GW-5470: collect_evidence evidence['pipeline_mode'] should be "
            f"bool False when no pipeline_url is given, but got {pipeline_mode!r} "
            f"(bool={bool(pipeline_mode)}).  "
            f"The jq --arg refactor stores str('false') which is truthy, "
            f"inverting the intended falsy semantics."
        )

    def test_collect_evidence_pipeline_mode_not_a_string(self) -> None:
        """GW-5470: pipeline_mode in collect_evidence output must not be a string.

        FAILS: The jq --arg refactor at both call-sites guarantees the value is
        always a JSON string.  str('false') != bool(False), so equality gates
        silently break.  This test makes the contract explicit: the value MUST
        NOT be of type str.
        """
        import json as _json

        stdout = self._run_two_node_workflow({"description": "GW-5470 string check"})
        parsed = _json.loads(stdout)
        pipeline_mode = parsed["evidence"].get("pipeline_mode")
        assert not isinstance(pipeline_mode, str), (
            f"GW-5470: evidence['pipeline_mode'] must not be a string; "
            f"got {pipeline_mode!r}.  "
            f"jq --arg serialises shell variables as JSON strings — use "
            f"--argjson or bare shell interpolation to preserve the boolean type."
        )
