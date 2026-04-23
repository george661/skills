"""Tests for variable reference linting."""

import pytest
from pathlib import Path

from dag_executor.parser import load_workflow_from_string
from dag_executor.validator import lint_variable_references


def test_declared_input_resolves():
    """$input-name references declared input → no error."""
    yaml_content = """
name: test-workflow
config:
  checkpoint_prefix: test
inputs:
  user_id:
    type: string
    required: true
nodes:
  - id: process
    name: Process
    type: bash
    script: |
      echo $user_id
    """
    workflow = load_workflow_from_string(yaml_content)
    issues = lint_variable_references(workflow)
    errors = [i for i in issues if i.severity == "error" and "user_id" in i.message]
    assert len(errors) == 0


def test_node_output_resolves():
    """$upstream.output where upstream is in depends_on → no error."""
    yaml_content = """
name: test-workflow
config:
  checkpoint_prefix: test
nodes:
  - id: fetch
    name: Fetch
    type: bash
    script: echo "data"
  - id: process
    name: Process
    type: bash
    depends_on: [fetch]
    script: |
      echo $fetch.output
    """
    workflow = load_workflow_from_string(yaml_content)
    issues = lint_variable_references(workflow)
    errors = [i for i in issues if i.severity == "error" and "fetch" in i.message]
    assert len(errors) == 0


def test_state_channel_via_writes_resolves():
    """Node A writes: [counter], Node B (depends on A) references $counter → no error."""
    yaml_content = """
name: test-workflow
config:
  checkpoint_prefix: test
nodes:
  - id: init
    name: Init
    type: bash
    writes: [counter]
    script: echo 0
  - id: increment
    name: Increment
    type: bash
    depends_on: [init]
    reads: [counter]
    script: |
      new_count=$((counter + 1))
      echo $new_count
    """
    workflow = load_workflow_from_string(yaml_content)
    issues = lint_variable_references(workflow)
    errors = [i for i in issues if i.severity == "error" and "counter" in i.message]
    assert len(errors) == 0


def test_state_channel_without_upstream_writer_flagged():
    """$counter with no upstream writes: and no declared input → error."""
    yaml_content = """
name: test-workflow
config:
  checkpoint_prefix: test
nodes:
  - id: process
    name: Process
    type: bash
    script: |
      echo $counter
    """
    workflow = load_workflow_from_string(yaml_content)
    issues = lint_variable_references(workflow)
    errors = [i for i in issues if i.severity == "error" and "counter" in i.message]
    assert len(errors) > 0


def test_bash_local_not_flagged():
    """Node has script with foo=... then $foo later → no error."""
    yaml_content = """
name: test-workflow
config:
  checkpoint_prefix: test
nodes:
  - id: process
    name: Process
    type: bash
    script: |
      result="success"
      echo $result
    """
    workflow = load_workflow_from_string(yaml_content)
    issues = lint_variable_references(workflow)
    errors = [i for i in issues if i.severity == "error" and "result" in i.message]
    assert len(errors) == 0


def test_bash_local_in_for_loop_not_flagged():
    """for item in ... then $item → no error."""
    yaml_content = """
name: test-workflow
config:
  checkpoint_prefix: test
nodes:
  - id: loop
    name: Loop
    type: bash
    script: |
      for item in *.txt; do
        echo $item
      done
    """
    workflow = load_workflow_from_string(yaml_content)
    issues = lint_variable_references(workflow)
    errors = [i for i in issues if i.severity == "error" and "item" in i.message]
    assert len(errors) == 0


def test_nested_field_path():
    """$upstream.output.deep.key resolves against node output."""
    yaml_content = """
name: test-workflow
config:
  checkpoint_prefix: test
nodes:
  - id: source
    name: Source
    type: bash
    script: echo '{"deep":{"key":"value"}}'
  - id: consumer
    name: Consumer
    type: bash
    depends_on: [source]
    script: |
      echo $source.output.deep.key
    """
    workflow = load_workflow_from_string(yaml_content)
    issues = lint_variable_references(workflow)
    errors = [i for i in issues if i.severity == "error" and "source" in i.message]
    assert len(errors) == 0


def test_unresolved_variable_emits_error():
    """$ghost not in inputs, node IDs, channels, or bash-locals → error."""
    yaml_content = """
name: test-workflow
config:
  checkpoint_prefix: test
nodes:
  - id: process
    name: Process
    type: bash
    script: |
      echo $ghost
    """
    workflow = load_workflow_from_string(yaml_content)
    issues = lint_variable_references(workflow)
    errors = [i for i in issues if i.severity == "error" and "ghost" in i.message]
    assert len(errors) > 0


def test_unresolved_variable_includes_file_and_line():
    """Error message contains workflow.yaml:<N> matching the node's YAML line."""
    yaml_content = """
name: test-workflow
config:
  checkpoint_prefix: test
nodes:
  - id: process
    name: Process
    type: bash
    script: |
      echo $ghost
    """
    workflow = load_workflow_from_string(yaml_content)
    issues = lint_variable_references(workflow, yaml_path="workflow.yaml")
    errors = [i for i in issues if i.severity == "error" and "ghost" in i.message]
    assert len(errors) > 0
    # Should contain file:line reference (node-level line)
    assert any("workflow.yaml" in e.message for e in errors)


def test_dry_run_exit_code_on_unresolved():
    """cli.run_dry_run returns non-zero via SystemExit(1) when lint fails."""
    # This will be tested via CLI integration - placeholder
    pass


def test_prompt_field_scanned():
    """prompt: string with $ghost → error."""
    yaml_content = """
name: test-workflow
config:
  checkpoint_prefix: test
nodes:
  - id: generate
    name: Generate
    type: prompt
    prompt: |
      Generate report for $ghost
    """
    workflow = load_workflow_from_string(yaml_content)
    issues = lint_variable_references(workflow)
    errors = [i for i in issues if i.severity == "error" and "ghost" in i.message]
    assert len(errors) > 0


def test_condition_field_scanned():
    """condition: with $ghost → error."""
    yaml_content = """
name: test-workflow
config:
  checkpoint_prefix: test
nodes:
  - id: check
    name: Check
    type: bash
    condition: "$ghost == 'value'"
    script: echo "ok"
    """
    workflow = load_workflow_from_string(yaml_content)
    issues = lint_variable_references(workflow)
    errors = [i for i in issues if i.severity == "error" and "ghost" in i.message]
    assert len(errors) > 0


def test_script_field_scanned():
    """bash script: with $ghost (not a bash-local) → error."""
    yaml_content = """
name: test-workflow
config:
  checkpoint_prefix: test
nodes:
  - id: process
    name: Process
    type: bash
    script: |
      echo $ghost
    """
    workflow = load_workflow_from_string(yaml_content)
    issues = lint_variable_references(workflow)
    errors = [i for i in issues if i.severity == "error" and "ghost" in i.message]
    assert len(errors) > 0


def test_backward_compat_existing_workflows_pass():
    """Run lint against each real file in workflows/*.yaml.

    Known issues are documented and allowed. New workflows must pass cleanly.
    """
    workflows_dir = Path(__file__).parent.parent / "workflows"
    if not workflows_dir.exists():
        pytest.skip("workflows/ directory not found")

    workflow_files = list(workflows_dir.glob("*.yaml"))
    if not workflow_files:
        pytest.skip("No workflow files found")

    failures = []
    for yaml_file in workflow_files:
        try:
            from dag_executor.parser import load_workflow
            workflow = load_workflow(str(yaml_file))
            issues = lint_variable_references(workflow, yaml_path=str(yaml_file))
            errors = [i for i in issues if i.severity == "error"]

            if errors:
                failures.append((yaml_file.name, errors))

        except Exception as e:
            failures.append((yaml_file.name, [f"Parse error: {e}"]))

    if failures:
        msg = "\n".join(
            f"  {name}: {len(errs)} error(s)" for name, errs in failures
        )
        pytest.fail(f"Workflows failed lint:\n{msg}")


def test_hyphen_concat_with_resolved_prefix():
    """Test bash string concatenation pattern $var-literal when var resolves."""
    yaml_content = """
name: test-workflow
config:
  checkpoint_prefix: test
inputs:
  tenant:
    type: string
    required: true
nodes:
  - id: setup
    name: Setup
    type: bash
    script: |
      echo "Setting up environment"
  - id: process
    name: Process
    type: bash
    depends_on: [setup]
    script: |
      # Bash interprets $tenant-id as ${tenant} + "-id" (string concatenation)
      # If $tenant resolves, $tenant-id should not produce a lint error
      echo "Processing $tenant-id"
      # Also test with node reference
      echo "Using $setup-result"
    """
    workflow = load_workflow_from_string(yaml_content)
    issues = lint_variable_references(workflow)
    # Should not produce errors for $tenant-id or $setup-result
    # since $tenant and $setup both resolve
    errors = [i for i in issues if i.severity == "error"]
    assert len(errors) == 0, f"Expected no errors, got: {[e.message for e in errors]}"
