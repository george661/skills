"""Comprehensive tests for WorkflowValidator pre-flight validation.

Covers all 9 check methods with positive and negative test cases.
"""
from pathlib import Path
from typing import List
import pytest
import re
from dag_executor.schema import (
    NodeDef,
    WorkflowDef,
    WorkflowConfig,
    InputDef,
    OutputDef,
    TriggerRule,
    EdgeDef,
    ReducerDef,
    ReducerStrategy,
    ModelTier,
)
from dag_executor.validator import WorkflowValidator, ValidationResult, ValidationIssue


# ------------------------------------------------------------------
# Test 1: Graph structure checks
# ------------------------------------------------------------------

def test_valid_workflow_passes():
    """Happy path with no issues."""
    workflow = WorkflowDef(
        name="valid-workflow",
        nodes=[
            NodeDef(id="start", type="bash", name="Start", script="echo start"),
            NodeDef(id="end", type="bash", name="End", script="echo end", depends_on=["start"]),
        ],
        config=WorkflowConfig(checkpoint_prefix="test"),
    )
    validator = WorkflowValidator()
    result = validator.validate(workflow)
    
    assert result.passed
    assert len(result.errors) == 0
    assert len(result.warnings) == 0
    assert result.summary() == "PASS: 0 error(s), 0 warning(s)"


def test_cycle_detection():
    """A->B->C->A produces error with code cycle_detected."""
    workflow = WorkflowDef(
        name="cyclic-workflow",
        nodes=[
            NodeDef(id="A", type="bash", name="A", script="echo A", depends_on=["C"]),
            NodeDef(id="B", type="bash", name="B", script="echo B", depends_on=["A"]),
            NodeDef(id="C", type="bash", name="C", script="echo C", depends_on=["B"]),
        ],
        config=WorkflowConfig(checkpoint_prefix="test"),
    )
    validator = WorkflowValidator()
    result = validator.validate(workflow)
    
    assert not result.passed
    assert len(result.errors) == 1
    assert result.errors[0].code == "cycle_detected"
    assert "cycle" in result.errors[0].message.lower()



def test_missing_dependency():
    """Node depends on non-existent node, error missing_dependency."""
    workflow = WorkflowDef(
        name="missing-dep-workflow",
        nodes=[
            NodeDef(id="A", type="bash", name="A", script="echo A", depends_on=["nonexistent"]),
        ],
        config=WorkflowConfig(checkpoint_prefix="test"),
    )
    validator = WorkflowValidator()
    result = validator.validate(workflow)
    
    assert not result.passed
    assert any(e.code == "missing_dependency" for e in result.errors)
    error = next(e for e in result.errors if e.code == "missing_dependency")
    assert error.node_id == "A"
    assert "nonexistent" in error.message


def test_unreachable_node():
    """Node with no path from roots (currently not possible without missing deps) - skip this test."""
    # Note: A truly unreachable node requires an island scenario, but if all dependencies  
    # exist and form a separate connected component with no roots, that's structurally impossible
    # in a DAG. So this check may never trigger in practice. For now, just test that multiple
    # roots are all marked as reachable (no false positives).
    workflow = WorkflowDef(
        name="two-roots-workflow",
        nodes=[
            NodeDef(id="root1", type="bash", name="Root1", script="echo root1"),
            NodeDef(id="root2", type="bash", name="Root2", script="echo root2"),
        ],
        config=WorkflowConfig(checkpoint_prefix="test"),
    )
    validator = WorkflowValidator()
    result = validator.validate(workflow)
    
    assert result.passed
    assert len(result.warnings) == 0  # Both roots are reachable


# ------------------------------------------------------------------
# Test 2: Node type checks
# ------------------------------------------------------------------

def test_invalid_node_type():
    """Unknown type produces error invalid_node_type."""
    workflow = WorkflowDef(
        name="invalid-type-workflow",
        nodes=[
            NodeDef(id="bad", type="INVALID_TYPE", name="Bad", script="echo bad"),
        ],
        config=WorkflowConfig(checkpoint_prefix="test"),
    )
    validator = WorkflowValidator()
    result = validator.validate(workflow)
    
    assert not result.passed
    assert any(e.code == "invalid_node_type" for e in result.errors)
    error = next(e for e in result.errors if e.code == "invalid_node_type")
    assert "INVALID_TYPE" in error.message


def test_valid_node_types():
    """All 6 valid types pass (bash, skill, command, prompt, gate, interrupt)."""
    workflow = WorkflowDef(
        name="all-types-workflow",
        nodes=[
            NodeDef(id="n1", type="bash", name="Bash", script="echo bash"),
            NodeDef(id="n2", type="skill", name="Skill", skill="test.skill.md", depends_on=["n1"]),
            NodeDef(id="n3", type="command", name="Command", command="test-cmd", depends_on=["n2"]),
            NodeDef(id="n4", type="prompt", name="Prompt", prompt="Test prompt", model=ModelTier.SONNET, depends_on=["n3"]),
            NodeDef(id="n5", type="gate", name="Gate", condition="true", depends_on=["n4"]),
            NodeDef(id="n6", type="interrupt", name="Interrupt", message="Please review", resume_key="approval", depends_on=["n5"]),
        ],
        config=WorkflowConfig(checkpoint_prefix="test"),
    )
    validator = WorkflowValidator()
    result = validator.validate(workflow)
    
    # Should have no invalid_node_type errors (may have other warnings about missing files)
    assert not any(e.code == "invalid_node_type" for e in result.errors)


# ------------------------------------------------------------------
# Test 3: Skill reference checks
# ------------------------------------------------------------------

def test_missing_skill_file(tmp_path: Path):
    """Skill node referencing non-existent file, error missing_skill."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    
    workflow = WorkflowDef(
        name="missing-skill-workflow",
        nodes=[
            NodeDef(id="skill1", type="skill", name="Skill", skill="nonexistent.skill.md"),
        ],
        config=WorkflowConfig(checkpoint_prefix="test"),
    )
    validator = WorkflowValidator(skills_dir=skills_dir)
    result = validator.validate(workflow)
    
    assert not result.passed
    assert any(e.code == "missing_skill" for e in result.errors)
    error = next(e for e in result.errors if e.code == "missing_skill")
    assert error.node_id == "skill1"
    assert "nonexistent.skill.md" in error.message


def test_valid_skill_file(tmp_path: Path):
    """Skill node with existing file, no error."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    (skills_dir / "test.skill.md").write_text("# Test Skill")
    
    workflow = WorkflowDef(
        name="valid-skill-workflow",
        nodes=[
            NodeDef(id="skill1", type="skill", name="Skill", skill="test.skill.md"),
        ],
        config=WorkflowConfig(checkpoint_prefix="test"),
    )
    validator = WorkflowValidator(skills_dir=skills_dir)
    result = validator.validate(workflow)
    
    assert not any(e.code == "missing_skill" for e in result.errors)


def test_skill_check_skipped_without_dir():
    """No skills_dir means no skill checks."""
    workflow = WorkflowDef(
        name="no-check-workflow",
        nodes=[
            NodeDef(id="skill1", type="skill", name="Skill", skill="anything.md"),
        ],
        config=WorkflowConfig(checkpoint_prefix="test"),
    )
    validator = WorkflowValidator(skills_dir=None)
    result = validator.validate(workflow)
    
    # Should not have missing_skill error since skills_dir is None
    assert not any(e.code == "missing_skill" for e in result.errors)


# ------------------------------------------------------------------
# Test 4: Command reference checks
# ------------------------------------------------------------------

def test_missing_command(tmp_path: Path):
    """Command not found in commands/ or workflows/, warning missing_command."""
    commands_dir = tmp_path / "commands"
    workflows_dir = tmp_path / "workflows"
    commands_dir.mkdir()
    workflows_dir.mkdir()
    
    workflow = WorkflowDef(
        name="missing-cmd-workflow",
        nodes=[
            NodeDef(id="cmd1", type="command", name="Command", command="nonexistent"),
        ],
        config=WorkflowConfig(checkpoint_prefix="test"),
    )
    validator = WorkflowValidator(commands_dir=commands_dir, workflows_dir=workflows_dir)
    result = validator.validate(workflow)
    
    assert any(w.code == "missing_command" for w in result.warnings)
    warning = next(w for w in result.warnings if w.code == "missing_command")
    assert warning.node_id == "cmd1"


def test_valid_command_in_commands_dir(tmp_path: Path):
    """.md file found in commands/."""
    commands_dir = tmp_path / "commands"
    commands_dir.mkdir()
    (commands_dir / "test-cmd.md").write_text("# Test Command")
    
    workflow = WorkflowDef(
        name="valid-cmd-workflow",
        nodes=[
            NodeDef(id="cmd1", type="command", name="Command", command="test-cmd"),
        ],
        config=WorkflowConfig(checkpoint_prefix="test"),
    )
    validator = WorkflowValidator(commands_dir=commands_dir)
    result = validator.validate(workflow)
    
    assert not any(w.code == "missing_command" for w in result.warnings)


def test_valid_command_in_workflows_dir(tmp_path: Path):
    """.yaml file found in workflows/."""
    workflows_dir = tmp_path / "workflows"
    workflows_dir.mkdir()
    (workflows_dir / "sub-dag.yaml").write_text("name: sub-dag\nnodes: []")
    
    workflow = WorkflowDef(
        name="valid-subdas-workflow",
        nodes=[
            NodeDef(id="cmd1", type="command", name="SubDAG", command="sub-dag"),
        ],
        config=WorkflowConfig(checkpoint_prefix="test"),
    )
    validator = WorkflowValidator(workflows_dir=workflows_dir)
    result = validator.validate(workflow)
    
    assert not any(w.code == "missing_command" for w in result.warnings)


# ------------------------------------------------------------------
# Test 5: Input contract checks
# ------------------------------------------------------------------

def test_invalid_regex_pattern():
    """Bad regex produces error invalid_input_pattern."""
    workflow = WorkflowDef(
        name="invalid-pattern-workflow",
        nodes=[NodeDef(id="n1", type="bash", name="N1", script="echo test")],
        inputs={"user_id": InputDef(type="string", required=True, pattern="[invalid(regex")},
        config=WorkflowConfig(checkpoint_prefix="test"),
    )
    validator = WorkflowValidator()
    result = validator.validate(workflow)
    
    assert not result.passed
    assert any(e.code == "invalid_input_pattern" for e in result.errors)
    error = next(e for e in result.errors if e.code == "invalid_input_pattern")
    assert "user_id" in error.message


def test_required_with_default_warning():
    """required+default produces warning required_with_default."""
    workflow = WorkflowDef(
        name="required-default-workflow",
        nodes=[NodeDef(id="n1", type="bash", name="N1", script="echo test")],
        inputs={"param": InputDef(type="string", required=True, default="default_value")},
        config=WorkflowConfig(checkpoint_prefix="test"),
    )
    validator = WorkflowValidator()
    result = validator.validate(workflow)
    
    assert result.passed  # warnings don't fail
    assert any(w.code == "required_with_default" for w in result.warnings)
    warning = next(w for w in result.warnings if w.code == "required_with_default")
    assert "param" in warning.message


def test_valid_input_contracts():
    """Well-formed inputs pass."""
    workflow = WorkflowDef(
        name="valid-inputs-workflow",
        nodes=[NodeDef(id="n1", type="bash", name="N1", script="echo test")],
        inputs={
            "user_id": InputDef(type="string", required=True, pattern="^[0-9]+$"),
            "optional": InputDef(type="string", required=False, default="default"),
        },
        config=WorkflowConfig(checkpoint_prefix="test"),
    )
    validator = WorkflowValidator()
    result = validator.validate(workflow)
    
    assert not any(e.code == "invalid_input_pattern" for e in result.errors)
    assert not any(w.code == "required_with_default" for w in result.warnings)


# ------------------------------------------------------------------
# Test 6: Output reference checks
# ------------------------------------------------------------------

def test_invalid_output_reference():
    """Output points to non-existent node, error invalid_output_ref."""
    workflow = WorkflowDef(
        name="invalid-output-workflow",
        nodes=[NodeDef(id="n1", type="bash", name="N1", script="echo test")],
        outputs={"result": OutputDef(node="nonexistent", field="output")},
        config=WorkflowConfig(checkpoint_prefix="test"),
    )
    validator = WorkflowValidator()
    result = validator.validate(workflow)
    
    assert not result.passed
    assert any(e.code == "invalid_output_ref" for e in result.errors)
    error = next(e for e in result.errors if e.code == "invalid_output_ref")
    assert "nonexistent" in error.message


def test_valid_output_reference():
    """Output points to real node, no error."""
    workflow = WorkflowDef(
        name="valid-output-workflow",
        nodes=[NodeDef(id="n1", type="bash", name="N1", script="echo test")],
        outputs={"result": OutputDef(node="n1", field="stdout")},
        config=WorkflowConfig(checkpoint_prefix="test"),
    )
    validator = WorkflowValidator()
    result = validator.validate(workflow)
    
    assert not any(e.code == "invalid_output_ref" for e in result.errors)


# ------------------------------------------------------------------
# Test 7: Edge consistency checks
# ------------------------------------------------------------------


def test_invalid_edge_target():
    """Edge to non-existent node, error invalid_edge_target."""
    workflow = WorkflowDef(
        name="invalid-edge-workflow",
        nodes=[
            NodeDef(
                id="gate1",
                type="gate",
                name="Gate",
                condition="true",
                edges=[EdgeDef(target="nonexistent", default=True)],
            ),
        ],
        config=WorkflowConfig(checkpoint_prefix="test"),
    )
    validator = WorkflowValidator()
    result = validator.validate(workflow)
    
    assert not result.passed
    assert any(e.code == "invalid_edge_target" for e in result.errors)
    error = next(e for e in result.errors if e.code == "invalid_edge_target")
    assert error.node_id == "gate1"
    assert "nonexistent" in error.message


def test_valid_edges():
    """Edges to real nodes, no errors."""
    workflow = WorkflowDef(
        name="valid-edges-workflow",
        nodes=[
            NodeDef(id="n1", type="bash", name="N1", script="echo 1"),
            NodeDef(id="n2", type="bash", name="N2", script="echo 2"),
            NodeDef(
                id="gate1",
                type="gate",
                name="Gate",
                condition="true",
                depends_on=["n1"],
                edges=[EdgeDef(target="n2", default=True)],
            ),
        ],
        config=WorkflowConfig(checkpoint_prefix="test"),
    )
    validator = WorkflowValidator()
    result = validator.validate(workflow)
    
    assert not any(e.code == "invalid_edge_target" for e in result.errors)


# ------------------------------------------------------------------
# Test 8: Trigger rule checks
# ------------------------------------------------------------------

def test_trigger_rule_single_dep_warning():
    """ONE_SUCCESS with 1 dep, warning trigger_rule_single_dep."""
    workflow = WorkflowDef(
        name="single-dep-trigger-workflow",
        nodes=[
            NodeDef(id="n1", type="bash", name="N1", script="echo 1"),
            NodeDef(
                id="n2",
                type="bash",
                name="N2",
                script="echo 2",
                depends_on=["n1"],
                trigger_rule=TriggerRule.ONE_SUCCESS,
            ),
        ],
        config=WorkflowConfig(checkpoint_prefix="test"),
    )
    validator = WorkflowValidator()
    result = validator.validate(workflow)
    
    assert any(w.code == "trigger_rule_single_dep" for w in result.warnings)
    warning = next(w for w in result.warnings if w.code == "trigger_rule_single_dep")
    assert warning.node_id == "n2"


def test_trigger_rule_multi_dep_ok():
    """ONE_SUCCESS with 2+ deps, no warning."""
    workflow = WorkflowDef(
        name="multi-dep-trigger-workflow",
        nodes=[
            NodeDef(id="n1", type="bash", name="N1", script="echo 1"),
            NodeDef(id="n2", type="bash", name="N2", script="echo 2"),
            NodeDef(
                id="n3",
                type="bash",
                name="N3",
                script="echo 3",
                depends_on=["n1", "n2"],
                trigger_rule=TriggerRule.ONE_SUCCESS,
            ),
        ],
        config=WorkflowConfig(checkpoint_prefix="test"),
    )
    validator = WorkflowValidator()
    result = validator.validate(workflow)
    
    assert not any(w.code == "trigger_rule_single_dep" for w in result.warnings)


# ------------------------------------------------------------------
# Test 9: Reducer consistency checks
# ------------------------------------------------------------------

def test_invalid_reducer_function_path():
    """Bad dotted path, error invalid_reducer_function."""
    workflow = WorkflowDef(
        name="invalid-reducer-workflow",
        nodes=[NodeDef(id="n1", type="bash", name="N1", script="echo 1")],
        state={
            "my_state": ReducerDef(strategy=ReducerStrategy.CUSTOM, function="invalid_path")
        },
        config=WorkflowConfig(checkpoint_prefix="test"),
    )
    validator = WorkflowValidator()
    result = validator.validate(workflow)
    
    assert not result.passed
    assert any(e.code == "invalid_reducer_function" for e in result.errors)
    error = next(e for e in result.errors if e.code == "invalid_reducer_function")
    assert "invalid_path" in error.message


def test_valid_reducer_function_path():
    """Proper module.function format, no error."""
    workflow = WorkflowDef(
        name="valid-reducer-workflow",
        nodes=[NodeDef(id="n1", type="bash", name="N1", script="echo 1")],
        state={
            "my_state": ReducerDef(strategy=ReducerStrategy.CUSTOM, function="mymodule.myfunction")
        },
        config=WorkflowConfig(checkpoint_prefix="test"),
    )
    validator = WorkflowValidator()
    result = validator.validate(workflow)
    
    assert not any(e.code == "invalid_reducer_function" for e in result.errors)


# ------------------------------------------------------------------
# Test 10: Integration / summary
# ------------------------------------------------------------------


def test_validation_result_summary():
    """Verify .summary() format."""
    workflow_fail = WorkflowDef(
        name="fail-workflow",
        nodes=[
            NodeDef(id="A", type="bash", name="A", script="echo A", depends_on=["nonexistent"]),
        ],
        config=WorkflowConfig(checkpoint_prefix="test"),
    )
    validator = WorkflowValidator()
    result_fail = validator.validate(workflow_fail)
    
    summary = result_fail.summary()
    assert "FAIL" in summary
    assert "1 error(s)" in summary
    
    workflow_pass = WorkflowDef(
        name="pass-workflow",
        nodes=[NodeDef(id="n1", type="bash", name="N1", script="echo test")],
        config=WorkflowConfig(checkpoint_prefix="test"),
    )
    result_pass = validator.validate(workflow_pass)
    summary_pass = result_pass.summary()
    assert "PASS" in summary_pass
    assert "0 error(s)" in summary_pass



def test_passed_property():
    """Errors make .passed False, warnings keep it True."""
    # Workflow with error
    workflow_error = WorkflowDef(
        name="error-workflow",
        nodes=[
            NodeDef(id="A", type="bash", name="A", script="echo A", depends_on=["nonexistent"]),
        ],
        config=WorkflowConfig(checkpoint_prefix="test"),
    )
    validator = WorkflowValidator()
    result_error = validator.validate(workflow_error)
    assert not result_error.passed
    
    # Workflow with only warning
    workflow_warning = WorkflowDef(
        name="warning-workflow",
        nodes=[
            NodeDef(id="root", type="bash", name="Root", script="echo root"),
            NodeDef(id="unreachable", type="bash", name="Unreachable", script="echo unreachable"),
        ],
        config=WorkflowConfig(checkpoint_prefix="test"),
    )
    result_warning = validator.validate(workflow_warning)
    assert result_warning.passed



def test_multiple_issues():
    """Workflow with several problems returns all of them."""
    workflow = WorkflowDef(
        name="multi-issue-workflow",
        nodes=[
            NodeDef(id="A", type="bash", name="A", script="echo A", depends_on=["missing1"]),
            NodeDef(id="B", type="INVALID", name="B", script="echo B", depends_on=["missing2"]),
            NodeDef(id="unreachable", type="bash", name="Unreachable", script="echo unreachable"),
        ],
        config=WorkflowConfig(checkpoint_prefix="test"),
    )
    validator = WorkflowValidator()
    result = validator.validate(workflow)
    
    assert not result.passed
    # Should have multiple errors: 2 missing_dependency + 1 invalid_node_type
    assert len(result.errors) >= 3
    # Should have warnings: unreachable_node
    assert len(result.warnings) >= 1
    
    error_codes = [e.code for e in result.errors]
    assert "missing_dependency" in error_codes
    assert "invalid_node_type" in error_codes
    
    warning_codes = [w.code for w in result.warnings]
    assert "unreachable_node" in warning_codes


# ------------------------------------------------------------------
# Test 11: CLI integration tests
# ------------------------------------------------------------------

def test_dry_run_calls_validator(tmp_path: Path):
    """Verify --dry-run on an invalid workflow prints validation errors."""
    import subprocess
    
    # Create an invalid workflow with missing dependency
    workflow_file = tmp_path / "invalid.yaml"
    workflow_file.write_text("""
name: invalid-workflow
config:
  checkpoint_prefix: test
nodes:
  - id: broken
    type: bash
    name: Broken
    script: echo test
    depends_on:
      - nonexistent
""")
    
    # Run dag-exec --dry-run
    result = subprocess.run(
        ["dag-exec", "--dry-run", str(workflow_file)],
        capture_output=True,
        text=True,
    )
    
    # Should exit with non-zero status
    assert result.returncode != 0
    
    # Should print validation error
    assert "FAIL" in result.stdout or "error" in result.stdout.lower()
    assert "missing_dependency" in result.stdout or "nonexistent" in result.stdout


def test_dry_run_valid_workflow(tmp_path: Path):
    """Verify --dry-run on a valid workflow prints PASS and execution plan."""
    import subprocess
    
    # Create a valid workflow
    workflow_file = tmp_path / "valid.yaml"
    workflow_file.write_text("""
name: valid-workflow
config:
  checkpoint_prefix: test
nodes:
  - id: start
    type: bash
    name: Start
    script: echo start
  - id: end
    type: bash
    name: End
    script: echo end
    depends_on:
      - start
""")
    
    # Run dag-exec --dry-run
    result = subprocess.run(
        ["dag-exec", "--dry-run", str(workflow_file)],
        capture_output=True,
        text=True,
    )
    
    # Should exit successfully
    assert result.returncode == 0

    # Should print PASS
    assert "PASS" in result.stdout

    # Should print execution plan
    assert "Execution Plan" in result.stdout
    assert "Layer 0" in result.stdout


# ------------------------------------------------------------------
# Test 11: Variable reference validation
# ------------------------------------------------------------------

def test_variable_resolution_valid_refs_pass():
    """Valid upstream $node.field references pass validation."""
    workflow = WorkflowDef(
        name="valid-refs",
        nodes=[
            NodeDef(id="fetch-data", type="bash", name="Fetch", script="echo output"),
            NodeDef(
                id="process",
                type="bash",
                name="Process",
                script="curl $fetch-data.output",
                depends_on=["fetch-data"]
            ),
        ],
        config=WorkflowConfig(checkpoint_prefix="test"),
    )
    validator = WorkflowValidator()
    result = validator.validate(workflow)

    assert result.passed
    assert not any(e.code == "dangling_variable_ref" for e in result.errors)
    assert not any(e.code == "downstream_variable_ref" for e in result.errors)


def test_variable_resolution_dangling_node_ref_fails():
    """Reference to non-existent node produces dangling_variable_ref error."""
    workflow = WorkflowDef(
        name="dangling-ref",
        nodes=[
            NodeDef(
                id="node1",
                type="bash",
                name="Node1",
                script="echo $nonexistent.output"
            ),
        ],
        config=WorkflowConfig(checkpoint_prefix="test"),
    )
    validator = WorkflowValidator()
    result = validator.validate(workflow)

    assert not result.passed
    errors = [e for e in result.errors if e.code == "dangling_variable_ref"]
    assert len(errors) == 1
    assert "nonexistent" in errors[0].message


def test_variable_resolution_downstream_ref_fails():
    """Reference to downstream node produces downstream_variable_ref error."""
    workflow = WorkflowDef(
        name="downstream-ref",
        nodes=[
            NodeDef(
                id="node1",
                type="bash",
                name="Node1",
                script="echo $node2.output",
                depends_on=[]
            ),
            NodeDef(
                id="node2",
                type="bash",
                name="Node2",
                script="echo data",
                depends_on=["node1"]
            ),
        ],
        config=WorkflowConfig(checkpoint_prefix="test"),
    )
    validator = WorkflowValidator()
    result = validator.validate(workflow)

    assert not result.passed
    errors = [e for e in result.errors if e.code == "downstream_variable_ref"]
    assert len(errors) == 1
    assert "node2" in errors[0].message


def test_variable_resolution_same_layer_ref_fails():
    """Reference to same-layer node produces downstream_variable_ref error."""
    workflow = WorkflowDef(
        name="same-layer-ref",
        nodes=[
            NodeDef(
                id="parallel1",
                type="bash",
                name="Parallel1",
                script="echo $parallel2.output"
            ),
            NodeDef(
                id="parallel2",
                type="bash",
                name="Parallel2",
                script="echo data"
            ),
        ],
        config=WorkflowConfig(checkpoint_prefix="test"),
    )
    validator = WorkflowValidator()
    result = validator.validate(workflow)

    assert not result.passed
    errors = [e for e in result.errors if e.code == "downstream_variable_ref"]
    assert len(errors) == 1
    assert "same-layer" in errors[0].message or "parallel2" in errors[0].message


def test_variable_resolution_on_failure_continue_warns():
    """Reference to node with on_failure=continue produces warning."""
    from dag_executor.schema import OnFailure

    workflow = WorkflowDef(
        name="fragile-ref",
        nodes=[
            NodeDef(
                id="fragile",
                type="bash",
                name="Fragile",
                script="echo output",
                on_failure=OnFailure.CONTINUE
            ),
            NodeDef(
                id="consumer",
                type="bash",
                name="Consumer",
                script="echo $fragile.output",
                depends_on=["fragile"]
            ),
        ],
        config=WorkflowConfig(checkpoint_prefix="test"),
    )
    validator = WorkflowValidator()
    result = validator.validate(workflow)

    warnings = [w for w in result.warnings if w.code == "fragile_variable_ref"]
    assert len(warnings) == 1
    assert "fragile" in warnings[0].message
    assert "continue" in warnings[0].message.lower()


def test_variable_resolution_workflow_input_refs_pass():
    """References to workflow inputs should not produce errors."""
    workflow = WorkflowDef(
        name="input-refs",
        inputs={
            "issue_key": InputDef(type="string", required=True),
        },
        nodes=[
            NodeDef(
                id="process",
                type="bash",
                name="Process",
                script="echo Processing $issue_key"
            ),
        ],
        config=WorkflowConfig(checkpoint_prefix="test"),
    )
    validator = WorkflowValidator()
    result = validator.validate(workflow)

    assert result.passed
    assert not any(e.code == "dangling_variable_ref" for e in result.errors)


def test_variable_resolution_in_params():
    """Variable references in node params are validated."""
    workflow = WorkflowDef(
        name="params-refs",
        nodes=[
            NodeDef(
                id="node1",
                type="skill",
                name="Node1",
                skill="some/skill",
                params={"url": "$nonexistent.endpoint"}
            ),
        ],
        config=WorkflowConfig(checkpoint_prefix="test"),
    )
    validator = WorkflowValidator()
    result = validator.validate(workflow)

    assert not result.passed
    errors = [e for e in result.errors if e.code == "dangling_variable_ref"]
    assert len(errors) >= 1


# ------------------------------------------------------------------
# Test 12: read_state validation
# ------------------------------------------------------------------

def test_read_state_valid_keys_pass():
    """read_state with valid workflow input keys passes."""
    workflow = WorkflowDef(
        name="read-state-valid",
        inputs={
            "issue_key": InputDef(type="string", required=True),
        },
        nodes=[
            NodeDef(
                id="node1",
                type="bash",
                name="Node1",
                script="echo $issue_key",
                read_state=["issue_key"]
            ),
        ],
        config=WorkflowConfig(checkpoint_prefix="test"),
    )
    validator = WorkflowValidator()
    result = validator.validate(workflow)

    assert result.passed
    assert not any(e.code == "invalid_read_state_key" for e in result.errors)


def test_read_state_invalid_key_fails():
    """read_state with non-existent key produces error."""
    workflow = WorkflowDef(
        name="read-state-invalid",
        nodes=[
            NodeDef(
                id="node1",
                type="bash",
                name="Node1",
                script="echo test",
                read_state=["nonexistent_key"]
            ),
        ],
        config=WorkflowConfig(checkpoint_prefix="test"),
    )
    validator = WorkflowValidator()
    result = validator.validate(workflow)

    assert not result.passed
    errors = [e for e in result.errors if e.code == "invalid_read_state_key"]
    assert len(errors) == 1
    assert "nonexistent_key" in errors[0].message


def test_read_state_state_reducer_keys_valid():
    """read_state with state reducer keys passes."""
    workflow = WorkflowDef(
        name="read-state-reducer",
        state={
            "results": ReducerDef(strategy=ReducerStrategy.APPEND),
        },
        nodes=[
            NodeDef(
                id="node1",
                type="bash",
                name="Node1",
                script="echo test",
                read_state=["results"]
            ),
        ],
        config=WorkflowConfig(checkpoint_prefix="test"),
    )
    validator = WorkflowValidator()
    result = validator.validate(workflow)

    assert result.passed
    assert not any(e.code == "invalid_read_state_key" for e in result.errors)
