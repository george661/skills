"""Runtime-correctness invariants that apply to ALL workflows.

Bug classes these catch (origin: GW-5056 code review):

1. Edge targets without depends_on become dangling root nodes — they execute
   in parallel with real entry points instead of after the source node.

2. Fan-in nodes that default to ALL_SUCCESS silently skip themselves when a
   conditional branch upstream is SKIPPED (ALL_SUCCESS requires every dep
   COMPLETED; SKIPPED does not count).

3. Bash scripts that embed ${ENV_VAR} inside single-quoted JSON ship
   unexpanded literal "${ENV_VAR}" to the downstream skill because single
   quotes suppress shell variable expansion.

4. Bash scripts emitting JSON via string interpolation of shell output (e.g.
   newline-delimited find output) produce syntactically invalid JSON.

Run via the existing `pytest packages/dag-executor/tests/` step in CI.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional, Set

import pytest

from dag_executor.parser import load_workflow
from dag_executor.schema import NodeDef, TriggerRule, WorkflowDef

WORKFLOWS_DIR = Path(__file__).parent.parent / "workflows"


def _workflow_files() -> List[Path]:
    """All .yaml workflow files shipped with the package."""
    return sorted(WORKFLOWS_DIR.glob("*.yaml"))


def _workflow_ids() -> List[str]:
    return [p.name for p in _workflow_files()]


@pytest.fixture(params=_workflow_files(), ids=_workflow_ids())
def workflow(request: pytest.FixtureRequest) -> WorkflowDef:
    """Load each workflow YAML in the package for invariant checks."""
    return load_workflow(str(request.param))


def _nodes_by_id(workflow: WorkflowDef) -> Dict[str, NodeDef]:
    return {n.id: n for n in workflow.nodes}


def _edge_targets(node: NodeDef) -> Set[str]:
    """All node IDs reachable from a node's `edges` field."""
    targets: Set[str] = set()
    if not node.edges:
        return targets
    for edge in node.edges:
        if edge.target:
            targets.add(edge.target)
        if edge.targets:
            targets.update(edge.targets)
    return targets


def _ancestors(
    node_id: str, by_id: Dict[str, NodeDef], seen: Set[str] | None = None
) -> Set[str]:
    """Transitive closure of depends_on, for checking topological ordering."""
    if seen is None:
        seen = set()
    node = by_id.get(node_id)
    if node is None or node_id in seen:
        return seen
    seen.add(node_id)
    for dep in node.depends_on or []:
        _ancestors(dep, by_id, seen)
    return seen


class TestEdgeTargetsHaveTopologicalOrdering:
    """INVARIANT 1: every edge target must be topologically AFTER its edge source.

    Edges influence runtime routing but the executor builds the DAG topology
    from `depends_on`. For edge-based skipping to actually prevent an edge
    target from running, the edge source MUST complete first — meaning the
    edge source (or a descendant of it) must appear in the edge target's
    transitive depends_on chain. Otherwise the target may start before the
    source completes, the skip mark arrives too late, and the workflow
    diverges from the author's intent.

    The simplest pattern: edge target declares depends_on: [edge_source]
    directly. Equivalent: declares depends_on on any node whose ancestry
    includes the edge source.
    """

    def test_edge_targets_depend_on_edge_source_transitively(
        self, workflow: WorkflowDef
    ) -> None:
        by_id = _nodes_by_id(workflow)
        violations: List[str] = []

        for source in workflow.nodes:
            if not source.edges:
                continue
            for target_id in _edge_targets(source):
                target = by_id.get(target_id)
                if target is None:
                    violations.append(
                        f"{workflow.name}: edge target '{target_id}' from "
                        f"'{source.id}' does not exist in workflow"
                    )
                    continue
                # The target's ancestor set must include the edge source.
                target_ancestors = _ancestors(target.id, by_id)
                if source.id not in target_ancestors:
                    violations.append(
                        f"{workflow.name}: edge target '{target.id}' is not "
                        f"topologically after edge source '{source.id}'. Add "
                        f"'{source.id}' to {target.id}.depends_on (or depend "
                        f"on a node that transitively depends on it)."
                    )

        assert not violations, "\n".join(violations)


class TestFanInNodesUseCompatibleTriggerRule:
    """INVARIANT 2: a fan-in node that collects multiple conditional branches
    from the same source must not use the default ALL_SUCCESS trigger rule.

    Pattern: source S emits edges [A, B]. A or B runs, the other is SKIPPED.
    A fan-in node F has depends_on: [A, B]. With ALL_SUCCESS, F is never
    reachable because one of A/B is always SKIPPED. Use one_success or
    all_done on F.

    Scope: we only flag the strict fan-in case (node depends on multiple
    children of the SAME edge source). A single edge-target dep can be
    legitimately modeled with ALL_SUCCESS if the workflow author actually
    wants the node to skip when that branch doesn't fire — that's a design
    choice, not a bug.
    """

    def _edge_source_of(
        self, node_id: str, by_id: Dict[str, NodeDef]
    ) -> Optional[str]:
        """Return the node whose `edges:` list contains node_id as a target."""
        for source in by_id.values():
            if node_id in _edge_targets(source):
                return source.id
        return None

    def test_fan_in_across_conditional_branches_uses_permissive_trigger(
        self, workflow: WorkflowDef
    ) -> None:
        by_id = _nodes_by_id(workflow)
        violations: List[str] = []

        for node in workflow.nodes:
            deps = node.depends_on or []
            if len(deps) < 2:
                continue

            # Bucket this node's edge-target dependencies by their edge source.
            sources_to_deps: Dict[str, List[str]] = {}
            for dep_id in deps:
                src = self._edge_source_of(dep_id, by_id)
                if src is not None:
                    sources_to_deps.setdefault(src, []).append(dep_id)

            # Find any source with 2+ sibling branches in this node's deps —
            # at least one of those branches is always SKIPPED.
            siblings_from_same_source = [
                (src, sibs) for src, sibs in sources_to_deps.items()
                if len(sibs) >= 2
            ]
            if not siblings_from_same_source:
                continue

            if node.trigger_rule == TriggerRule.ALL_SUCCESS:
                details = "; ".join(
                    f"source={src} branches={sibs}"
                    for src, sibs in siblings_from_same_source
                )
                violations.append(
                    f"{workflow.name}: node '{node.id}' fans in conditional "
                    f"sibling branches ({details}) but uses trigger_rule "
                    f"ALL_SUCCESS. One branch is always SKIPPED, which "
                    f"fails ALL_SUCCESS. Use one_success or all_done."
                )

        assert not violations, "\n".join(violations)


class TestBashScriptsEnvVarExpansion:
    """INVARIANT 3: env vars inside single-quoted JSON literals never expand.

    `npx tsx .../create_issue.ts '{"project": "${TENANT_PROJECT}", ...}'`
    ships the literal string `${TENANT_PROJECT}` to the tool — shell never
    looks inside single quotes.
    """

    # Common env vars agents reference inside JSON payloads
    _ENV_VAR_PATTERN = re.compile(
        r"\$\{?(TENANT_PROJECT|TENANT_NAMESPACE|TENANT_DOMAIN_PATH|PROJECT_ROOT|DOCS_REPO)\}?"
    )

    def test_env_vars_not_inside_single_quoted_json(
        self, workflow: WorkflowDef
    ) -> None:
        violations: List[str] = []

        for node in workflow.nodes:
            script = getattr(node, "script", None)
            if not script:
                continue

            # Scan for '{ ... }' single-quoted JSON literals passed as args
            for match in re.finditer(r"'(\{[^']*\})'", script):
                payload = match.group(1)
                env_refs = self._ENV_VAR_PATTERN.findall(payload)
                if env_refs:
                    violations.append(
                        f"{workflow.name}: node '{node.id}' embeds env "
                        f"var(s) {env_refs} inside single-quoted JSON. "
                        f"Shell will ship literal '${{VAR}}'. Build the "
                        f"payload with jq --arg (see other workflows for "
                        f"pattern)."
                    )

        assert not violations, "\n".join(violations)


class TestBashScriptsUseJqForJsonOutput:
    """INVARIANT 4: bash nodes with output_format=json must not emit JSON via
    string interpolation of unbounded shell output.

    Why: `echo "{\\"features\\": \\"$(find ... | xargs basename)\\"}"` emits
    literal newlines inside the JSON string when find returns multiple files,
    producing invalid JSON the executor cannot parse.

    The safe pattern is `jq -n --arg ... --argjson ...`.
    """

    # Commands whose output commonly contains newlines/special chars
    _RISKY_SUBSHELL_PATTERN = re.compile(
        r'"[^"]*\$\(\s*(?:find|grep|rg|ls|cat|awk|sed|jq\s+-r)[^)]*\)[^"]*"'
    )

    def test_bash_json_output_built_with_jq(
        self, workflow: WorkflowDef
    ) -> None:
        violations: List[str] = []

        for node in workflow.nodes:
            if getattr(node, "type", "") != "bash":
                continue
            if getattr(node, "output_format", None) is None:
                continue
            script = getattr(node, "script", None)
            if not script:
                continue
            # Only flag if the script declares output_format: json
            if not str(node.output_format).lower().endswith("json"):
                continue

            # Look for risky interpolation in the final echo/printf statement
            # (heuristic: the last `echo "{...}"` line with $(...) inside)
            final_echo_match = re.search(
                r'echo\s+"(\{[^"]*\$\([^)]*\)[^"]*\})"\s*$',
                script,
                re.MULTILINE,
            )
            if final_echo_match and "jq" not in final_echo_match.group(1):
                violations.append(
                    f"{workflow.name}: node '{node.id}' has output_format=json "
                    f"but emits JSON via echo with $(...) substitution. This "
                    f"breaks when the subshell output contains newlines or "
                    f"quotes. Use `jq -n --arg ...` instead."
                )

        assert not violations, "\n".join(violations)


class TestStateChannelsHaveReducers:
    """INVARIANT 5: every declared state channel must have a reducer.

    Why: None reducer falls back to LastValueChannel which raises on any
    parallel write. Most workflows want overwrite/append/merge_dict semantics.
    This catches accidental omission.
    """

    def test_state_channels_have_reducers(
        self, workflow: WorkflowDef
    ) -> None:
        # ReducerDef shorthand (bare "reducer:" at top level) is also valid.
        # Accept any non-None value.
        violations: List[str] = []
        for key, field in workflow.state.items():
            # `state` values can be ChannelFieldDef OR ReducerDef. Only
            # ChannelFieldDef has a .reducer attribute — if it's a ReducerDef
            # directly, the channel IS the reducer.
            from dag_executor.schema import ChannelFieldDef, ReducerDef
            if isinstance(field, ChannelFieldDef):
                if field.reducer is None:
                    violations.append(
                        f"{workflow.name}: state channel '{key}' has no "
                        f"reducer. Parallel writes will raise. Specify "
                        f"reducer: overwrite|append|merge_dict|..."
                    )
            elif isinstance(field, ReducerDef):
                continue  # already a reducer, by construction has strategy
            else:
                violations.append(
                    f"{workflow.name}: state channel '{key}' has unexpected "
                    f"type {type(field).__name__}"
                )

        assert not violations, "\n".join(violations)
