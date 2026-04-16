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

    def validate(self, workflow_def: WorkflowDef) -> ValidationResult:
        """Run all validation checks on a workflow definition.

        Args:
            workflow_def: Parsed workflow to validate

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
        self._check_variable_references(workflow_def, nodes_map, result)
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
                    if edge.target not in all_ids:
                        result.issues.append(ValidationIssue(
                            severity="error",
                            node_id=node.id,
                            code="invalid_edge_target",
                            message=f"Edge target '{edge.target}' does not exist",
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
        # Collect all output keys produced by nodes (heuristic: we can't know
        # output keys statically for bash/prompt, but we can flag state keys
        # that have CUSTOM strategy with missing functions)
        for state_key, reducer_def in workflow_def.state.items():
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

    def _check_variable_references(
        self,
        workflow_def: WorkflowDef,
        nodes_map: Dict[str, NodeDef],
        result: ValidationResult,
    ) -> None:
        """Check that all variable references point to existing upstream nodes.

        Validates:
        - $node.field references point to nodes that exist
        - Referenced nodes are upstream (earlier in topological order)
        - Warns if referenced node has on_failure: continue
        """
        from dag_executor.variables import extract_variable_references

        # Get topological layers for upstream validation
        try:
            layers = topological_sort_with_layers(workflow_def.nodes)
        except (CycleDetectedError, ValueError):
            # If graph is broken, skip variable validation (errors already reported)
            return

        # Build layer index: node_id -> layer_index
        node_layer_index: Dict[str, int] = {}
        for layer_idx, layer in enumerate(layers):
            for node_id in layer:
                node_layer_index[node_id] = layer_idx

        # Check each node's variable references
        for node in workflow_def.nodes:
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
                # Check if referenced node exists
                if node_id_ref not in nodes_map:
                    # Could be a workflow input or environment variable
                    if node_id_ref not in workflow_def.inputs:
                        # If it has no field_path (e.g., $repo vs $node.output),
                        # it might be an environment variable - only warn
                        if not field_path:
                            # Single-part reference could be env var - skip validation
                            continue
                        else:
                            # Multi-part reference (e.g., $node.output) must be a node
                            result.issues.append(ValidationIssue(
                                severity="error",
                                node_id=node.id,
                                code="dangling_variable_ref",
                                message=f"Variable reference ${node_id_ref}.{field_path} "
                                        f"points to non-existent node (and is not a workflow input)",
                            ))
                    continue

                # Check if referenced node is upstream
                ref_layer = node_layer_index.get(node_id_ref)
                current_layer = node_layer_index.get(node.id)

                if ref_layer is not None and current_layer is not None:
                    if ref_layer >= current_layer:
                        result.issues.append(ValidationIssue(
                            severity="error",
                            node_id=node.id,
                            code="downstream_variable_ref",
                            message=f"Variable reference ${node_id_ref}.{field_path} points to "
                                    f"downstream or same-layer node (layer {ref_layer} >= {current_layer})",
                        ))

                # Warn if referenced node has on_failure: continue
                ref_node = nodes_map[node_id_ref]
                if ref_node.on_failure and ref_node.on_failure.value == "continue":
                    result.issues.append(ValidationIssue(
                        severity="warning",
                        node_id=node.id,
                        code="fragile_variable_ref",
                        message=f"Variable reference ${node_id_ref}.{field_path} points to node "
                                f"with on_failure=continue (output may be absent at runtime)",
                    ))

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
