"""Tests for cross-DAG contract validation."""
import pytest
from pathlib import Path

from dag_executor.contracts import ContractValidator
from dag_executor.parser import load_workflow
from dag_executor.validator import ValidationIssue


@pytest.fixture
def fixtures_dir():
    """Return path to test fixtures directory."""
    return Path(__file__).parent / "fixtures"


def test_missing_child_workflow(fixtures_dir):
    """Child workflow file does not exist."""
    parent = load_workflow(str(fixtures_dir / "parent_with_missing_child.yaml"))
    validator = ContractValidator(workflows_dir=fixtures_dir)
    issues = validator.check_contracts(parent)
    # Missing child → should emit error
    assert len(issues) == 1
    assert issues[0].severity == "error"
    assert issues[0].code == "missing_child_workflow"
    assert "nonexistent_child" in issues[0].message


def test_missing_required_input_error(fixtures_dir):
    """Parent does not provide enough args for child's required inputs."""
    parent = load_workflow(str(fixtures_dir / "parent_insufficient_args.yaml"))
    validator = ContractValidator(workflows_dir=fixtures_dir)
    issues = validator.check_contracts(parent)
    assert len(issues) == 1
    assert issues[0].severity == "error"
    assert issues[0].code == "missing_child_inputs"
    assert "requires 2 inputs" in issues[0].message


def test_unresolvable_output_ref_warning(fixtures_dir):
    """Parent references child output field that doesn't exist."""
    parent = load_workflow(str(fixtures_dir / "parent_bad_output_ref.yaml"))
    validator = ContractValidator(workflows_dir=fixtures_dir)
    issues = validator.check_contracts(parent)
    assert len(issues) == 1
    assert issues[0].severity == "warning"
    assert issues[0].code == "unresolvable_child_output"
    assert "does not declare output 'nonexistent'" in issues[0].message


def test_valid_contract_no_issues(fixtures_dir):
    """Well-formed parent-child contract produces no issues."""
    parent = load_workflow(str(fixtures_dir / "parent_valid_contract.yaml"))
    validator = ContractValidator(workflows_dir=fixtures_dir)
    issues = validator.check_contracts(parent)
    assert len(issues) == 0


def test_child_no_outputs_skip_check(fixtures_dir):
    """Child with no outputs → skip output ref validation."""
    parent = load_workflow(str(fixtures_dir / "parent_child_no_outputs.yaml"))
    validator = ContractValidator(workflows_dir=fixtures_dir)
    issues = validator.check_contracts(parent)
    # No crash, no warnings — child has no outputs so we can't validate refs
    assert len(issues) == 0


def test_child_filter_specific_name(fixtures_dir):
    """Filter to specific child by name."""
    parent = load_workflow(str(fixtures_dir / "parent_multiple_children.yaml"))
    validator = ContractValidator(workflows_dir=fixtures_dir)
    issues = validator.check_contracts(parent, child_name="child_a")
    # Only child_a is checked
    assert all("child_a" in i.message or "call_child_a" in str(i.node_id) for i in issues)


def test_multiple_output_refs_same_node(fixtures_dir):
    """Multiple refs to child output in same parent node."""
    parent = load_workflow(str(fixtures_dir / "parent_multi_refs.yaml"))
    validator = ContractValidator(workflows_dir=fixtures_dir)
    issues = validator.check_contracts(parent)
    # Both bad refs should be caught
    error_codes = [i.code for i in issues]
    assert error_codes.count("unresolvable_child_output") == 2


def test_integration_with_workflow_validator(fixtures_dir):
    """WorkflowValidator.validate() includes contract checks."""
    from dag_executor.validator import WorkflowValidator
    
    parent = load_workflow(str(fixtures_dir / "parent_bad_output_ref.yaml"))
    validator = WorkflowValidator(workflows_dir=fixtures_dir)
    result = validator.validate(parent)
    
    # Should include contract validation issues
    contract_issues = [i for i in result.issues if i.code in ("missing_child_inputs", "unresolvable_child_output")]
    assert len(contract_issues) > 0


def test_no_workflows_dir_skips_validation(fixtures_dir):
    """If workflows_dir is None, contract validation is skipped."""
    parent = load_workflow(str(fixtures_dir / "parent_bad_output_ref.yaml"))
    validator = ContractValidator(workflows_dir=None)
    issues = validator.check_contracts(parent)
    assert len(issues) == 0  # No child can be loaded → skip validation


def test_output_refs_in_params(fixtures_dir):
    """Check that params field is scanned for variable references."""
    parent = load_workflow(str(fixtures_dir / "parent_refs_in_params.yaml"))
    validator = ContractValidator(workflows_dir=fixtures_dir)
    issues = validator.check_contracts(parent)
    # Should find the invalid reference in params
    assert len(issues) >= 1
    assert any(i.code == "unresolvable_child_output" and "bad_field" in i.message for i in issues)


def test_output_refs_in_args(fixtures_dir):
    """Check that args field is scanned for variable references."""
    parent = load_workflow(str(fixtures_dir / "parent_refs_in_args.yaml"))
    validator = ContractValidator(workflows_dir=fixtures_dir)
    issues = validator.check_contracts(parent)
    # Should find the invalid reference in args
    assert len(issues) >= 1
    assert any(i.code == "unresolvable_child_output" and "invalid_output" in i.message for i in issues)
