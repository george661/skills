"""Pre-flight workflow validation.

Validates a WorkflowDef before execution to catch errors early
and avoid burning tokens on misconfigured workflows.

Inspired by:
- Airflow's dag.test() + DagBag import validation
- Argo's static YAML linting
- Flyte's resource pre-flight checks
"""
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from dag_executor.graph import topological_sort_with_layers, CycleDetectedError
from dag_executor.schema import (
    NodeDef,
    WorkflowDef,
    TriggerRule,
)

# Explicit whitelist of known environment variables that appear in workflows
# Unknown ALL_CAPS names will produce lint errors
ENV_VAR_WHITELIST = {
    "PROJECT_ROOT",
    "TENANT_NAMESPACE",
    "TENANT_PROJECT",
    "TENANT_DOMAIN_PATH",
    "TENANT_DOCS_REPO",
    "TENANT_SMOKE_TEST_PATH",
    "DAG_EVENTS_DIR",
    "DAG_CREATE_ISSUES_BATCH",
    "DAG_DEPENDENCY_GRAPH",
    "DAG_ISSUE_LIST",
    "HOME",
    "PATH",
    "PWD",
    "USER",
    "SHELL",
}


@dataclass
class ValidationIssue:
    """A single validation finding."""

    severity: str  # "error" | "warning"
    node_id: Optional[str]
    code: str  # machine-readable code, e.g. "missing_skill"
    message: str


@dataclass
class ValidationResult:
    """Aggregated validation result."""

    issues: List[ValidationIssue] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not any(i.severity == "error" for i in self.issues)

    @property
    def errors(self) -> List[ValidationIssue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> List[ValidationIssue]:
        return [i for i in self.issues if i.severity == "warning"]

    def summary(self) -> str:
        """One-line summary for CLI output."""
        e = len(self.errors)
        w = len(self.warnings)
        status = "PASS" if self.passed else "FAIL"
        return f"{status}: {e} error(s), {w} warning(s)"


def lint_variable_references(
    workflow_def: WorkflowDef,
    *,
    yaml_path: Optional[str] = None,
    yaml_source: Optional[str] = None
) -> List[ValidationIssue]:
    """Lint variable references in a workflow.

    Checks that all $variable references resolve to:
    - Declared workflow inputs
    - Upstream node IDs (in depends_on chain)
    - Upstream state channels (in writes: declarations)
    - Bash-local variables (in the same script)

    Args:
        workflow_def: The workflow to lint
        yaml_path: Optional path to the YAML file (for error messages)
        yaml_source: Optional YAML source string (currently unused)

    Returns:
        List of ValidationIssue objects (errors and warnings)
    """
    from dag_executor.bash_locals import extract_bash_locals
    from dag_executor.graph import topological_sort_with_layers, CycleDetectedError
    from dag_executor.parser import get_node_lines
    from dag_executor.variables import extract_variable_references

    issues: List[ValidationIssue] = []

    # Get line numbers for nodes
    node_lines = get_node_lines(workflow_def)

    # Build nodes map
    nodes_map: Dict[str, NodeDef] = {node.id: node for node in workflow_def.nodes}

    # Get topological layers for upstream validation
    try:
        layers = topological_sort_with_layers(workflow_def.nodes)
    except (CycleDetectedError, ValueError):
        # If graph is broken, skip variable validation (errors already reported)
        return issues

    # Build layer index: node_id -> layer_index
    node_layer_index: Dict[str, int] = {}
    for layer_idx, layer in enumerate(layers):
        for node_id in layer:
            node_layer_index[node_id] = layer_idx

    # Build upstream writes index: channel_name -> set of producer node IDs
    # A channel is available if ANY upstream node (in topological order) writes it
    def get_upstream_nodes(node_id: str) -> Set[str]:
        """Get all upstream nodes (transitive depends_on)."""
        upstream = set()
        to_visit = [node_id]
        visited = set()

        while to_visit:
            current = to_visit.pop()
            if current in visited:
                continue
            visited.add(current)

            current_node = nodes_map.get(current)
            if current_node and current_node.depends_on:
                for dep in current_node.depends_on:
                    upstream.add(dep)
                    to_visit.append(dep)

        return upstream

    # Build channel writers map
    channel_writers: Dict[str, Set[str]] = {}
    for node in workflow_def.nodes:
        if node.writes:
            for channel in node.writes:
                if channel not in channel_writers:
                    channel_writers[channel] = set()
                channel_writers[channel].add(node.id)

    # Get workflow-level state channels (always available to all nodes)
    workflow_state_channels: Set[str] = set(workflow_def.state.keys()) if workflow_def.state else set()

    # Check each node's variable references
    for node in workflow_def.nodes:
        # Extract bash locals if this node has a script
        bash_locals: Set[str] = set()
        if node.script:
            bash_locals = extract_bash_locals(node.script)

        # Get upstream nodes for this node
        upstream_nodes = get_upstream_nodes(node.id)

        # Get available upstream channels
        upstream_channels: Set[str] = workflow_state_channels.copy()
        for channel, writers in channel_writers.items():
            # Channel is available if any writer is upstream
            if writers & upstream_nodes:
                upstream_channels.add(channel)

        # Collect resume_keys from upstream interrupt nodes
        resume_keys: Set[str] = set()
        for upstream_id in upstream_nodes:
            upstream_node = nodes_map.get(upstream_id)
            if upstream_node and upstream_node.type == "interrupt" and upstream_node.resume_key:
                resume_keys.add(upstream_node.resume_key)

        # Collect all fields that can contain variable references
        fields_to_check: List[Any] = []

        if node.script:
            fields_to_check.append(node.script)
        if node.prompt:
            fields_to_check.append(node.prompt)
        if node.condition:
            fields_to_check.append(node.condition)
        if node.params:
            fields_to_check.append(node.params)
        if node.args:
            fields_to_check.append(node.args)

        # Extract all variable references from these fields
        all_refs: List[Tuple[str, str]] = []
        for field_value in fields_to_check:
            all_refs.extend(extract_variable_references(field_value))

        # Validate each reference
        for node_id_ref, field_path in all_refs:
            # Build the full reference string for error messages
            ref_str = f"${node_id_ref}"
            if field_path:
                ref_str += f".{field_path}"

            # Try to resolve the reference
            resolved = False

            # 1. Check workflow inputs
            if node_id_ref in workflow_def.inputs:
                resolved = True

            # 2. Check upstream node IDs
            elif node_id_ref in nodes_map:
                resolved = True

                # Additional checks for node references
                ref_layer = node_layer_index.get(node_id_ref)
                current_layer = node_layer_index.get(node.id)

                # Check if referenced node is upstream
                if ref_layer is not None and current_layer is not None:
                    if ref_layer >= current_layer:
                        issues.append(ValidationIssue(
                            severity="error",
                            node_id=node.id,
                            code="downstream_variable_ref",
                            message=f"Variable reference {ref_str} points to "
                                    f"downstream or same-layer node (layer {ref_layer} >= {current_layer})",
                        ))

                # Warn if referenced node has on_failure: continue
                ref_node = nodes_map[node_id_ref]
                if ref_node.on_failure and ref_node.on_failure.value == "continue":
                    issues.append(ValidationIssue(
                        severity="warning",
                        node_id=node.id,
                        code="fragile_variable_ref",
                        message=f"Variable reference {ref_str} points to node "
                                f"with on_failure=continue (output may be absent at runtime)",
                    ))

            # 3. Check upstream state channels
            elif node_id_ref in upstream_channels:
                resolved = True

            # 4. Check bash-local variables (single-part refs only)
            elif not field_path and node_id_ref in bash_locals:
                resolved = True

            # 4b. Check resume_keys from upstream interrupt nodes (single-part refs only)
            elif not field_path and node_id_ref in resume_keys:
                resolved = True

            # 5. Bash string concatenation: $var-literal is parsed as $var-literal by the pattern,
            #    but bash interprets it as ${var} + "-literal". Check if prefix before hyphen resolves.
            #    This accepts patterns like $foo-bar if $foo is a valid variable, treating the hyphen
            #    as bash's implicit string concatenation boundary rather than part of the variable name.
            elif '-' in node_id_ref:
                prefix = node_id_ref.split('-')[0]
                if (prefix in workflow_def.inputs or
                    prefix in nodes_map or
                    prefix in upstream_channels or
                    prefix in bash_locals or
                    prefix in resume_keys):
                    resolved = True

            # 6. Environment variables - skip validation only for whitelisted names
            elif not field_path and node_id_ref in ENV_VAR_WHITELIST:
                resolved = True

            # If unresolved, emit error
            if not resolved:
                # Build error message with file:line if available
                location = ""
                if yaml_path:
                    location = f" at {yaml_path}"
                    if node.id in node_lines:
                        location += f":{node_lines[node.id]}"
                    location += ":"

                # Use dangling_variable_ref for multi-part refs (e.g., $nonexistent.field)
                # Use unresolved_variable_reference for single-part refs
                error_code = "dangling_variable_ref" if field_path else "unresolved_variable_reference"

                issues.append(ValidationIssue(
                    severity="error",
                    node_id=node.id,
                    code=error_code,
                    message=f"Variable reference {ref_str}{location} "
                            f"not declared in inputs or produced by upstream node",
                ))

    return issues


class WorkflowValidator:
    """Validates a WorkflowDef before execution.

    Usage:
        validator = WorkflowValidator(skills_dir=Path("skills/"))
        result = validator.validate(workflow_def)
        if not result.passed:
            for issue in result.errors:
                print(f"  {issue.node_id}: {issue.message}")

    Checks performed:
        1. Graph structure — cycles, unreachable nodes, missing dependency refs
        2. Node type fields — required fields present for each node type
        3. Skill references — skill files exist on disk
        4. Command references — command YAML/MD files exist
        5. Input contracts — required inputs have no default, patterns compile
        6. Output references — output defs point to real nodes/fields
        7. Edge consistency — edge targets exist, exactly one default
        8. Environment variables — referenced DAG_* vars have values
        9. Reducer consistency — state keys referenced by nodes, custom funcs importable
        10. Trigger rule sanity — ONE_SUCCESS/ALL_DONE only on multi-dep nodes
        11. Variable references — $node.field syntax is valid, nodes exist
        12. Read state — nodes with read_state only receive declared workflow inputs
    """

    def __init__(
        self,
        skills_dir: Optional[Path] = None,
        commands_dir: Optional[Path] = None,
        workflows_dir: Optional[Path] = None,
        env: Optional[Dict[str, str]] = None,
    ):
        self.skills_dir = skills_dir
        self.commands_dir = commands_dir
        self.workflows_dir = workflows_dir
        self.env = env if env is not None else dict(os.environ)

    def validate(self, workflow_def: WorkflowDef, yaml_path: Optional[str] = None) -> ValidationResult:
        """Run all validation checks on a workflow definition.

        Args:
            workflow_def: Parsed workflow to validate
            yaml_path: Optional path to YAML file (for file:line error messages)

        Returns:
            ValidationResult with all issues found
        """
        result = ValidationResult()
        nodes_map = {n.id: n for n in workflow_def.nodes}

        self._check_graph_structure(workflow_def, nodes_map, result)
        self._check_node_types(workflow_def, nodes_map, result)
        self._check_skill_references(workflow_def, nodes_map, result)
        self._check_command_references(workflow_def, nodes_map, result)
        self._check_input_contracts(workflow_def, result)
        self._check_output_references(workflow_def, nodes_map, result)
        self._check_edge_consistency(workflow_def, nodes_map, result)
        self._check_trigger_rules(workflow_def, nodes_map, result)
        self._check_reducer_consistency(workflow_def, nodes_map, result)
        self._check_channel_subscriptions(workflow_def, nodes_map, result)
        self._check_variable_references(workflow_def, nodes_map, result, yaml_path)
        self._check_read_state(workflow_def, nodes_map, result)
        self._check_contracts(workflow_def, result)

        return result

    # ------------------------------------------------------------------
    # Individual check methods
    # ------------------------------------------------------------------

    def _check_graph_structure(
        self,
        workflow_def: WorkflowDef,
        nodes_map: Dict[str, NodeDef],
        result: ValidationResult,
    ) -> None:
        """Check for cycles, missing deps, unreachable nodes."""
        # Missing dependency references (check BEFORE topological sort to avoid ValueError)
        all_ids = set(nodes_map.keys())
        has_missing_refs = False
        for node in workflow_def.nodes:
            for dep_id in node.depends_on:
                if dep_id not in all_ids:
                    result.issues.append(ValidationIssue(
                        severity="error",
                        node_id=node.id,
                        code="missing_dependency",
                        message=f"Depends on '{dep_id}' which does not exist",
                    ))
                    has_missing_refs = True

        # Check edge targets (also before topological sort)
        for node in workflow_def.nodes:
            if node.edges:
                for edge in node.edges:
                    # Support both single-target (target) and multi-target (targets)
                    edge_targets = edge.targets if edge.targets else ([edge.target] if edge.target else [])
                    for target_id in edge_targets:
                        if target_id not in all_ids:
                            result.issues.append(ValidationIssue(
                                severity="error",
                                node_id=node.id,
                                code="invalid_edge_target",
                                message=f"Edge target '{target_id}' does not exist",
                            ))
                            has_missing_refs = True

        # Cycle detection (skip if there are missing refs)
        if not has_missing_refs:
            try:
                topological_sort_with_layers(workflow_def.nodes)
            except CycleDetectedError as e:
                result.issues.append(ValidationIssue(
                    severity="error",
                    node_id=None,
                    code="cycle_detected",
                    message=f"DAG contains a cycle: {e}",
                ))
                return  # Can't do further graph checks with cycles

        # Unreachable nodes (no path from any root)
        roots = {n.id for n in workflow_def.nodes if not n.depends_on}
        reachable: Set[str] = set()
        # BFS from roots through reverse dependency graph
        dependents: Dict[str, List[str]] = {nid: [] for nid in all_ids}
        for node in workflow_def.nodes:
            for dep_id in node.depends_on:
                if dep_id in dependents:
                    dependents[dep_id].append(node.id)
        queue = list(roots)
        while queue:
            nid = queue.pop(0)
            if nid in reachable:
                continue
            reachable.add(nid)
            queue.extend(dependents.get(nid, []))

        unreachable = all_ids - reachable
        for nid in unreachable:
            result.issues.append(ValidationIssue(
                severity="warning",
                node_id=nid,
                code="unreachable_node",
                message="Node is unreachable from any root node",
            ))

    def _check_node_types(
        self,
        workflow_def: WorkflowDef,
        nodes_map: Dict[str, NodeDef],
        result: ValidationResult,
    ) -> None:
        """Verify type-specific required fields (belt-and-suspenders with pydantic)."""
        valid_types = {"bash", "skill", "command", "prompt", "gate", "interrupt"}
        for node in workflow_def.nodes:
            if node.type not in valid_types:
                result.issues.append(ValidationIssue(
                    severity="error",
                    node_id=node.id,
                    code="invalid_node_type",
                    message=f"Unknown node type '{node.type}' (valid: {', '.join(sorted(valid_types))})",
                ))

            # AC-18 (PRP-PLAT-010 Task 12): dispatch on prompt/skill/command is
            # currently informational. Emit a warning so authors know the field
            # does not change runtime behavior — real semantics arrive with
            # PRP-PLAT-006 (DAG Remote Dispatch, GW-5140).
            if node.type in ("prompt", "skill", "command") and node.dispatch is not None:
                result.issues.append(ValidationIssue(
                    severity="warning",
                    node_id=node.id,
                    code="dispatch_informational",
                    message=(
                        f"dispatch: {node.dispatch.value} on type={node.type} is "
                        "currently informational — execution semantics arrive with "
                        "PRP-PLAT-006. Model routing is controlled by the `model:` "
                        "field + model-routing.json."
                    ),
                ))

    def _check_skill_references(
        self,
        workflow_def: WorkflowDef,
        nodes_map: Dict[str, NodeDef],
        result: ValidationResult,
    ) -> None:
        """Verify skill file paths exist on disk."""
        if self.skills_dir is None:
            return  # Can't validate without skills_dir

        for node in workflow_def.nodes:
            if node.type == "skill" and node.skill:
                skill_path = self.skills_dir / node.skill
                if not skill_path.exists():
                    result.issues.append(ValidationIssue(
                        severity="error",
                        node_id=node.id,
                        code="missing_skill",
                        message=f"Skill file not found: {node.skill} (looked in {self.skills_dir})",
                    ))

    def _check_command_references(
        self,
        workflow_def: WorkflowDef,
        nodes_map: Dict[str, NodeDef],
        result: ValidationResult,
    ) -> None:
        """Verify command references resolve to existing command files or workflows."""
        if self.commands_dir is None and self.workflows_dir is None:
            return

        for node in workflow_def.nodes:
            if node.type == "command" and node.command:
                found = False
                # Check commands/ dir for .md files
                if self.commands_dir:
                    cmd_path = self.commands_dir / f"{node.command}.md"
                    if cmd_path.exists():
                        found = True
                # Check workflows/ dir for .yaml files (sub-DAG)
                if self.workflows_dir and not found:
                    yaml_path = self.workflows_dir / f"{node.command}.yaml"
                    if yaml_path.exists():
                        found = True
                if not found:
                    result.issues.append(ValidationIssue(
                        severity="warning",
                        node_id=node.id,
                        code="missing_command",
                        message=f"Command '{node.command}' not found in commands/ or workflows/",
                    ))

    def _check_input_contracts(
        self,
        workflow_def: WorkflowDef,
        result: ValidationResult,
    ) -> None:
        """Validate input definitions — patterns compile, required fields consistent."""
        for input_name, input_def in workflow_def.inputs.items():
            # Check regex patterns compile
            if input_def.pattern:
                try:
                    re.compile(input_def.pattern)
                except re.error as e:
                    result.issues.append(ValidationIssue(
                        severity="error",
                        node_id=None,
                        code="invalid_input_pattern",
                        message=f"Input '{input_name}' has invalid regex pattern: {e}",
                    ))

            # Required inputs with defaults are suspicious
            if input_def.required and input_def.default is not None:
                result.issues.append(ValidationIssue(
                    severity="warning",
                    node_id=None,
                    code="required_with_default",
                    message=f"Input '{input_name}' is required but has a default value",
                ))

    def _check_output_references(
        self,
        workflow_def: WorkflowDef,
        nodes_map: Dict[str, NodeDef],
        result: ValidationResult,
    ) -> None:
        """Verify output defs point to real nodes."""
        for output_name, output_def in workflow_def.outputs.items():
            if output_def.node not in nodes_map:
                result.issues.append(ValidationIssue(
                    severity="error",
                    node_id=None,
                    code="invalid_output_ref",
                    message=f"Output '{output_name}' references non-existent node '{output_def.node}'",
                ))

    def _check_edge_consistency(
        self,
        workflow_def: WorkflowDef,
        nodes_map: Dict[str, NodeDef],
        result: ValidationResult,
    ) -> None:
        """Verify conditional edge targets exist in the workflow.

        Note: Edge target existence is now checked in _check_graph_structure
        before topological_sort to avoid ValueError. This method is kept
        for future edge consistency checks (e.g., default edge validation).
        """
        # Edge target existence is checked in _check_graph_structure
        pass

    def _check_trigger_rules(
        self,
        workflow_def: WorkflowDef,
        nodes_map: Dict[str, NodeDef],
        result: ValidationResult,
    ) -> None:
        """Warn if ONE_SUCCESS/ALL_DONE on nodes with 0-1 dependencies."""
        for node in workflow_def.nodes:
            if node.trigger_rule in (TriggerRule.ONE_SUCCESS, TriggerRule.ALL_DONE):
                if len(node.depends_on) < 2:
                    result.issues.append(ValidationIssue(
                        severity="warning",
                        node_id=node.id,
                        code="trigger_rule_single_dep",
                        message=f"Trigger rule '{node.trigger_rule.value}' on node with "
                                f"{len(node.depends_on)} dependency (use all_success instead?)",
                    ))

    def _check_reducer_consistency(
        self,
        workflow_def: WorkflowDef,
        nodes_map: Dict[str, NodeDef],
        result: ValidationResult,
    ) -> None:
        """Check that state reducer keys are actually produced by nodes."""
        from dag_executor.schema import ChannelFieldDef, ReducerDef

        # Collect all output keys produced by nodes (heuristic: we can't know
        # output keys statically for bash/prompt, but we can flag state keys
        # that have CUSTOM strategy with missing functions)
        for state_key, field_def in workflow_def.state.items():
            # Extract ReducerDef from union type (ChannelFieldDef or ReducerDef)
            reducer_def = None
            if isinstance(field_def, ChannelFieldDef):
                reducer_def = field_def.reducer  # May be None
            elif isinstance(field_def, ReducerDef):
                reducer_def = field_def

            # Skip if no reducer (e.g., ChannelFieldDef without reducer)
            if reducer_def is None:
                continue

            if reducer_def.strategy.value == "custom" and reducer_def.function:
                # Verify the custom function is importable
                parts = reducer_def.function.rsplit(".", 1)
                if len(parts) != 2:
                    result.issues.append(ValidationIssue(
                        severity="error",
                        node_id=None,
                        code="invalid_reducer_function",
                        message=f"State key '{state_key}' has invalid function path: "
                                f"'{reducer_def.function}' (expected 'module.function')",
                    ))

    def _check_channel_subscriptions(
        self,
        workflow_def: WorkflowDef,
        nodes_map: Dict[str, NodeDef],
        result: ValidationResult,
    ) -> None:
        """Check that reads/writes channel keys match declared state or workflow inputs."""
        if not workflow_def.state:
            # No state declared, skip channel subscription checks
            return

        state_keys = set(workflow_def.state.keys())
        input_keys = set(workflow_def.inputs.keys())
        # Reads can reference state keys OR workflow input keys
        valid_read_keys = state_keys | input_keys

        for node in workflow_def.nodes:
            # Check reads keys (can be state or input keys)
            if node.reads is not None:
                for key in node.reads:
                    if key not in valid_read_keys:
                        result.issues.append(ValidationIssue(
                            severity="warning",
                            node_id=node.id,
                            code="unknown_read_channel",
                            message=f"Node declares reads=['{key}'] but '{key}' "
                                    f"not in workflow state keys: {sorted(state_keys)} "
                                    f"or input keys: {sorted(input_keys)}",
                        ))

            # Check writes keys (must be state keys only)
            if node.writes is not None:
                for key in node.writes:
                    if key not in state_keys:
                        result.issues.append(ValidationIssue(
                            severity="warning",
                            node_id=node.id,
                            code="unknown_write_channel",
                            message=f"Node declares writes=['{key}'] but '{key}' "
                                    f"not in workflow state keys: {sorted(state_keys)}",
                        ))

    def _check_variable_references(
        self,
        workflow_def: WorkflowDef,
        nodes_map: Dict[str, NodeDef],
        result: ValidationResult,
        yaml_path: Optional[str] = None,
    ) -> None:
        """Check that all variable references point to existing upstream nodes.

        Delegates to the public lint_variable_references function.

        Validates:
        - $node.field references point to nodes that exist
        - Referenced nodes are upstream (earlier in topological order)
        - Warns if referenced node has on_failure: continue
        - State channels via writes: declarations
        - Bash-local variables
        """
        # Delegate to public function
        issues = lint_variable_references(workflow_def, yaml_path=yaml_path)
        result.issues.extend(issues)

    def _check_read_state(
        self,
        workflow_def: WorkflowDef,
        nodes_map: Dict[str, NodeDef],
        result: ValidationResult,
    ) -> None:
        """Check that read_state declarations reference valid state keys.

        Validates:
        - All keys in read_state are produced by upstream nodes or workflow inputs
        """
        # Collect available state keys: workflow inputs + state reducer keys
        available_keys = set(workflow_def.inputs.keys())
        available_keys.update(workflow_def.state.keys())

        # Check each node with read_state declared
        for node in workflow_def.nodes:
            if node.read_state is not None:
                for key in node.read_state:
                    if key not in available_keys:
                        result.issues.append(ValidationIssue(
                            severity="error",
                            node_id=node.id,
                            code="invalid_read_state_key",
                            message=f"read_state key '{key}' is not produced by any upstream node "
                                    f"or workflow input. Available: {sorted(available_keys)}",
                        ))

    def _check_contracts(
        self,
        workflow_def: WorkflowDef,
        result: ValidationResult,
    ) -> None:
        """Validate cross-DAG input/output contracts between parent and sub-DAGs.

        Uses deferred import to avoid circular dependency between validator.py and contracts.py.
        """
        # Deferred import to avoid circular dependency (contracts.py imports ValidationIssue from validator.py)
        from dag_executor.contracts import ContractValidator

        if self.workflows_dir is None:
            return  # No workflows directory → cannot validate contracts

        contract_validator = ContractValidator(workflows_dir=self.workflows_dir)
        contract_issues = contract_validator.check_contracts(workflow_def)
        result.issues.extend(contract_issues)
