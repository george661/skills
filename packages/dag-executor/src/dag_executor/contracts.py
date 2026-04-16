"""Cross-DAG variable contracts — type-check inputs/outputs between parent and sub-DAGs.

When work.yaml invokes implement.yaml as a sub-DAG via a command node,
the parent expects certain output keys from the child. If the child
changes its output schema, this should fail at validation time, not runtime.

Inspired by:
- Dagster asset checks / data contracts
- Flyte's typed inputs/outputs
- TypeScript interface contracts

Usage:
    from dag_executor.contracts import ContractValidator

    validator = ContractValidator(workflows_dir=Path("workflows/"))
    issues = validator.check_contracts(parent_def, child_name="implement")
"""
from pathlib import Path
from typing import Any, Dict, List, Optional

from dag_executor.parser import load_workflow as _load_workflow
from dag_executor.schema import WorkflowDef
from dag_executor.validator import ValidationIssue


class ContractValidator:
    """Validates input/output contracts between parent and sub-DAG workflows.

    Checks:
        1. Parent command nodes that invoke sub-DAGs → child workflow exists
        2. Parent variable refs ($child_node.field) → child outputs declare that field
        3. Child required inputs → parent provides matching args
        4. Output type compatibility (future: JSON Schema-based)
    """

    def __init__(self, workflows_dir: Optional[Path] = None):
        self.workflows_dir = workflows_dir
        self._cache: Dict[str, WorkflowDef] = {}

    def _load_child(self, command_name: str) -> Optional[WorkflowDef]:
        """Attempt to load a child workflow YAML by command name."""
        if self.workflows_dir is None:
            return None

        yaml_path = self.workflows_dir / f"{command_name}.yaml"
        if not yaml_path.exists():
            return None

        if command_name not in self._cache:
            self._cache[command_name] = _load_workflow(str(yaml_path))
        return self._cache[command_name]

    def check_contracts(
        self,
        parent: WorkflowDef,
        child_name: Optional[str] = None,
    ) -> List[ValidationIssue]:
        """Validate contracts between a parent workflow and its sub-DAGs.

        If child_name is provided, only checks that specific sub-DAG.
        Otherwise checks all command nodes that reference loadable workflows.

        Args:
            parent: Parent workflow definition
            child_name: Optional specific child to check

        Returns:
            List of validation issues found
        """
        issues: List[ValidationIssue] = []

        for node in parent.nodes:
            if node.type != "command" or not node.command:
                continue

            # Filter to specific child if requested
            if child_name and node.command != child_name:
                continue

            child_def = self._load_child(node.command)
            if child_def is None:
                # Not a sub-DAG (might be a markdown command) — skip
                continue

            # Check 1: Child required inputs are provided by parent args
            self._check_required_inputs(node.id, node.args or [], child_def, issues)

            # Check 2: Parent variable refs to child outputs are valid
            self._check_output_refs(parent, node.id, child_def, issues)

        return issues

    def _check_required_inputs(
        self,
        parent_node_id: str,
        parent_args: List[Any],
        child: WorkflowDef,
        issues: List[ValidationIssue],
    ) -> None:
        """Verify child's required inputs are satisfied by parent's args."""
        required_inputs = [
            name for name, inp in child.inputs.items()
            if inp.required and inp.default is None
        ]

        # Command nodes pass args as positional (arg0, arg1, ...)
        # so we can only check count, not names
        if len(parent_args) < len(required_inputs):
            issues.append(ValidationIssue(
                severity="error",
                node_id=parent_node_id,
                code="missing_child_inputs",
                message=(
                    f"Sub-DAG '{child.name}' requires {len(required_inputs)} inputs "
                    f"({', '.join(required_inputs)}) but parent provides {len(parent_args)} args"
                ),
            ))

    def _check_output_refs(
        self,
        parent: WorkflowDef,
        command_node_id: str,
        child: WorkflowDef,
        issues: List[ValidationIssue],
    ) -> None:
        """Check that parent variable refs ($command_node.field) match child outputs."""
        child_output_fields = set(child.outputs.keys())
        if not child_output_fields:
            return  # Child has no declared outputs — can't validate

        # Scan parent nodes for variable references to this command node's output
        prefix = f"${command_node_id}."
        for node in parent.nodes:
            # Check script, prompt, condition fields for variable refs
            for field_value in [node.script, node.prompt, node.condition]:
                if field_value and prefix in field_value:
                    # Extract referenced field names
                    import re
                    refs = re.findall(
                        rf"\${re.escape(command_node_id)}\.(\w+)",
                        field_value,
                    )
                    for ref_field in refs:
                        if ref_field not in child_output_fields:
                            issues.append(ValidationIssue(
                                severity="warning",
                                node_id=node.id,
                                code="unresolvable_child_output",
                                message=(
                                    f"References ${command_node_id}.{ref_field} but "
                                    f"sub-DAG '{child.name}' does not declare output '{ref_field}' "
                                    f"(available: {', '.join(sorted(child_output_fields))})"
                                ),
                            ))
