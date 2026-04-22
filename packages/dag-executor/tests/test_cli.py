"""Tests for CLI entry point."""
import json
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from dag_executor.cli import parse_args, parse_inputs, main, run_dry_run, run_visualize, run_list, run_info
from dag_executor.schema import WorkflowDef, WorkflowConfig, NodeDef, EdgeDef, WorkflowStatus, NodeStatus, NodeResult
from dag_executor.executor import WorkflowResult

FIXTURES_DIR = Path(__file__).parent / "fixtures"


class TestParseArgs:
    """Test CLI argument parsing."""

    def test_parse_workflow_path_only(self) -> None:
        """Parse with only positional workflow path."""
        args = parse_args(["workflow.yaml"])
        assert args.workflow == "workflow.yaml"
        assert args.inputs == []
        assert args.resume is False
        assert args.dry_run is False
        assert args.visualize is False
        assert args.concurrency == 10

    def test_parse_with_key_value_inputs(self) -> None:
        """Parse with key=value input pairs."""
        args = parse_args(["workflow.yaml", "user_id=123", "dry_run=true"])
        assert args.workflow == "workflow.yaml"
        assert args.inputs == ["user_id=123", "dry_run=true"]

    def test_parse_with_json_input(self) -> None:
        """Parse with JSON input string."""
        args = parse_args(["workflow.yaml", '{"user_id": "123", "dry_run": true}'])
        assert args.workflow == "workflow.yaml"
        assert args.inputs == ['{"user_id": "123", "dry_run": true}']

    def test_parse_with_resume_flag(self) -> None:
        """Parse with --resume flag."""
        args = parse_args(["workflow.yaml", "--resume", "--run-id", "abc123"])
        assert args.resume is True
        assert args.run_id == "abc123"

    def test_parse_with_dry_run_flag(self) -> None:
        """Parse with --dry-run flag."""
        args = parse_args(["workflow.yaml", "--dry-run"])
        assert args.dry_run is True

    def test_parse_with_visualize_flag(self) -> None:
        """Parse with --visualize flag."""
        args = parse_args(["workflow.yaml", "--visualize"])
        assert args.visualize is True

    def test_parse_with_checkpoint_dir(self) -> None:
        """Parse with --checkpoint-dir override."""
        args = parse_args(["workflow.yaml", "--checkpoint-dir", "/tmp/checkpoints"])
        assert args.checkpoint_dir == "/tmp/checkpoints"

    def test_parse_with_concurrency(self) -> None:
        """Parse with --concurrency."""
        args = parse_args(["workflow.yaml", "--concurrency", "5"])
        assert args.concurrency == 5


class TestDryRun:
    """Test dry-run mode."""

    def test_dry_run_validates_and_prints_plan(self, capsys) -> None:
        """Dry-run validates YAML and prints execution plan with layers."""
        workflow_path = FIXTURES_DIR / "valid_workflow.yaml"
        with patch("dag_executor.cli.load_workflow") as mock_load:
            # Create a simple workflow def
            workflow_def = WorkflowDef(
                name="test",
                config=WorkflowConfig(checkpoint_prefix="test"),
                nodes=[
                    NodeDef(id="A", name="Node A", type="bash", script="echo A"),
                    NodeDef(id="B", name="Node B", type="bash", script="echo B", depends_on=["A"]),
                ],
            )
            mock_load.return_value = workflow_def

            run_dry_run(str(workflow_path))
            
            captured = capsys.readouterr()
            assert "Execution Plan" in captured.out
            assert "Layer 0" in captured.out
            assert "Layer 1" in captured.out
            assert "Node A" in captured.out
            assert "Node B" in captured.out

    def test_dry_run_with_invalid_yaml(self) -> None:
        """Dry-run with invalid YAML raises clear error."""
        workflow_path = FIXTURES_DIR / "invalid_missing_config.yaml"
        with pytest.raises(ValueError, match="workflow definition is invalid"):
            with patch("dag_executor.cli.load_workflow") as mock_load:
                mock_load.side_effect = ValueError("workflow definition is invalid")
                run_dry_run(str(workflow_path))


class TestVisualize:
    """Test visualize mode."""

    def test_visualize_outputs_mermaid(self, capsys) -> None:
        """Visualize outputs mermaid DAG diagram."""
        with patch("dag_executor.cli.load_workflow") as mock_load:
            workflow_def = WorkflowDef(
                name="test",
                config=WorkflowConfig(checkpoint_prefix="test"),
                nodes=[
                    NodeDef(id="A", name="Node A", type="bash", script="echo A"),
                    NodeDef(id="B", name="Node B", type="bash", script="echo B", depends_on=["A"]),
                ],
            )
            mock_load.return_value = workflow_def

            run_visualize("workflow.yaml")
            
            captured = capsys.readouterr()
            assert "graph TD" in captured.out
            assert "A[Node A]" in captured.out
            assert "B[Node B]" in captured.out
            assert "A --> B" in captured.out


class TestMainIntegration:
    """Test main CLI entry point."""

    def test_main_executes_workflow_success(self, capsys) -> None:
        """Main executes workflow and prints summary on success."""
        with patch("dag_executor.cli.load_workflow") as mock_load, \
             patch("dag_executor.cli.execute_workflow") as mock_exec, \
             patch("sys.argv", ["dag-exec", str(FIXTURES_DIR / "valid_workflow.yaml"), "user_id=123"]):
            
            workflow_def = WorkflowDef(
                name="test",
                config=WorkflowConfig(checkpoint_prefix="test"),
                nodes=[NodeDef(id="A", name="Node A", type="bash", script="echo A")],
            )
            mock_load.return_value = workflow_def
            mock_exec.return_value = WorkflowResult(
                status=WorkflowStatus.COMPLETED,
                node_results={"A": NodeResult(status=NodeStatus.COMPLETED, output={"result": "test"})},
                run_id="test-run",
            )

            with pytest.raises(SystemExit) as exc_info:
                main()

            assert exc_info.value.code == 0
            captured = capsys.readouterr()
            assert "Workflow completed" in captured.out
            assert "Status: completed" in captured.out

    def test_main_with_missing_file(self, capsys) -> None:
        """Main with missing YAML file produces clear error and exit code 1."""
        with patch("sys.argv", ["dag-exec", "nonexistent.yaml"]), \
             patch("dag_executor.cli.load_workflow") as mock_load:
            
            mock_load.side_effect = FileNotFoundError("nonexistent.yaml")
            
            with pytest.raises(SystemExit) as exc_info:
                main()
            
            assert exc_info.value.code == 1
            captured = capsys.readouterr()
            assert "Error" in captured.err
            assert "nonexistent.yaml" in captured.err

    def test_main_with_invalid_yaml(self, capsys) -> None:
        """Main with invalid YAML produces clear error and exit code 1."""
        with patch("sys.argv", ["dag-exec", "invalid.yaml"]), \
             patch("dag_executor.cli.load_workflow") as mock_load:
            
            mock_load.side_effect = ValueError("Invalid workflow: missing required field 'name'")
            
            with pytest.raises(SystemExit) as exc_info:
                main()
            
            assert exc_info.value.code == 1
            captured = capsys.readouterr()
            assert "Error" in captured.err
            assert "Invalid workflow" in captured.err

    def test_main_dry_run_mode(self, capsys) -> None:
        """Main with --dry-run validates and prints plan without executing."""
        with patch("sys.argv", ["dag-exec", "workflow.yaml", "--dry-run"]), \
             patch("dag_executor.cli.load_workflow") as mock_load, \
             patch("dag_executor.cli.execute_workflow") as mock_exec:
            
            workflow_def = WorkflowDef(
                name="test",
                config=WorkflowConfig(checkpoint_prefix="test"),
                nodes=[NodeDef(id="A", name="Node A", type="bash", script="echo A")],
            )
            mock_load.return_value = workflow_def

            with pytest.raises(SystemExit) as exc_info:
                main()
            
            assert exc_info.value.code == 0
            # Should NOT call execute_workflow in dry-run mode
            mock_exec.assert_not_called()
            captured = capsys.readouterr()
            assert "Execution Plan" in captured.out

    def test_main_resume_mode(self, capsys) -> None:
        """Main with --resume calls resume_workflow."""
        with patch("sys.argv", ["dag-exec", "workflow.yaml", "--resume", "--run-id", "abc123"]), \
             patch("dag_executor.cli.load_workflow") as mock_load, \
             patch("dag_executor.cli.resume_workflow") as mock_resume, \
             patch("dag_executor.cli.CheckpointStore") as mock_store_class:
            
            workflow_def = WorkflowDef(
                name="test",
                config=WorkflowConfig(checkpoint_prefix="test"),
                nodes=[NodeDef(id="A", name="Node A", type="bash", script="echo A")],
            )
            mock_load.return_value = workflow_def
            mock_resume.return_value = WorkflowResult(
                status=WorkflowStatus.COMPLETED,
                node_results={"A": NodeResult(status=NodeStatus.COMPLETED, output={"result": "test"})},
                run_id="abc123",
            )

            with pytest.raises(SystemExit) as exc_info:
                main()

            assert exc_info.value.code == 0
            mock_resume.assert_called_once()
            captured = capsys.readouterr()
            assert "Resuming workflow" in captured.out


class TestStreamFlag:
    """Test --stream flag."""

    def test_parse_stream_flag_default(self) -> None:
        """--stream without value defaults to 'all'."""
        args = parse_args(["workflow.yaml", "--stream"])
        assert args.stream == "all"

    def test_parse_stream_state_updates(self) -> None:
        """--stream state_updates parses correctly."""
        args = parse_args(["workflow.yaml", "--stream", "state_updates"])
        assert args.stream == "state_updates"

    def test_stream_creates_event_emitter(self, capsys) -> None:
        """--stream creates an EventEmitter and passes it to execute_workflow."""
        with patch("sys.argv", ["dag-exec", str(FIXTURES_DIR / "valid_workflow.yaml"), "--stream"]), \
             patch("dag_executor.cli.load_workflow") as mock_load, \
             patch("dag_executor.cli.execute_workflow") as mock_exec:

            workflow_def = WorkflowDef(
                name="test",
                config=WorkflowConfig(checkpoint_prefix="test"),
                nodes=[NodeDef(id="A", name="Node A", type="bash", script="echo A")],
            )
            mock_load.return_value = workflow_def
            mock_exec.return_value = WorkflowResult(
                status=WorkflowStatus.COMPLETED,
                node_results={"A": NodeResult(status=NodeStatus.COMPLETED, output={"result": "test"})},
                run_id="test-run",
            )

            with pytest.raises(SystemExit) as exc_info:
                main()

            assert exc_info.value.code == 0
            # Verify event_emitter was passed (not None)
            call_kwargs = mock_exec.call_args
            assert call_kwargs.kwargs.get("event_emitter") is not None


class TestConditionalEdges:
    """Test conditional edge rendering in dry-run and visualize."""

    def _workflow_with_edges(self) -> WorkflowDef:
        return WorkflowDef(
            name="test",
            config=WorkflowConfig(checkpoint_prefix="test"),
            nodes=[
                NodeDef(
                    id="A", name="Node A", type="bash", script="echo A",
                    edges=[
                        EdgeDef(target="B", condition="status == 'ok'"),
                        EdgeDef(target="C", default=True),
                    ],
                ),
                NodeDef(id="B", name="Node B", type="bash", script="echo B", depends_on=["A"]),
                NodeDef(id="C", name="Node C", type="bash", script="echo C", depends_on=["A"]),
            ],
        )

    def test_dry_run_shows_conditional_edges(self, capsys) -> None:
        """Dry-run displays conditional edges with conditions."""
        with patch("dag_executor.cli.load_workflow") as mock_load:
            mock_load.return_value = self._workflow_with_edges()
            run_dry_run("workflow.yaml")

            captured = capsys.readouterr()
            assert "-> B (when: status == 'ok')" in captured.out
            assert "-> C (default)" in captured.out

    def test_visualize_shows_conditional_edges(self, capsys) -> None:
        """Visualize renders conditional edges in mermaid syntax."""
        with patch("dag_executor.cli.load_workflow") as mock_load:
            mock_load.return_value = self._workflow_with_edges()
            run_visualize("workflow.yaml")

            captured = capsys.readouterr()
            assert "A -->|status == 'ok'| B" in captured.out
            assert "A -->|default| C" in captured.out


class TestParseListArgs:
    """Test parsing of 'list' subcommand arguments."""

    def test_parse_list_default_dir(self) -> None:
        """Parse list subcommand with default directory."""
        args = parse_args(["list"])
        assert args.subcommand == "list"
        assert args.directory == "."
        assert args.json_output is False

    def test_parse_list_with_directory(self) -> None:
        """Parse list subcommand with explicit directory."""
        args = parse_args(["list", "/some/dir"])
        assert args.subcommand == "list"
        assert args.directory == "/some/dir"

    def test_parse_list_json_flag(self) -> None:
        """Parse list subcommand with --json flag."""
        args = parse_args(["list", "--json"])
        assert args.subcommand == "list"
        assert args.json_output is True
        assert args.directory == "."  # Still uses default


class TestParseInfoArgs:
    """Test parsing of 'info' subcommand arguments."""

    def test_parse_info_workflow(self) -> None:
        """Parse info subcommand with workflow path."""
        args = parse_args(["info", "wf.yaml"])
        assert args.subcommand == "info"
        assert args.workflow == "wf.yaml"


class TestRunList:
    """Test run_list function for workflow catalog."""

    def test_list_valid_directory(self, tmp_path: Path, capsys) -> None:
        """List valid workflows in a directory."""
        # Create test workflow YAMLs

        wf1 = tmp_path / "workflow1.yaml"
        wf1.write_text("""
name: Test Workflow 1
config:
  checkpoint_prefix: test1
inputs:
  user_id:
    type: string
    required: true
nodes:
  - id: A
    name: Node A
    type: bash
    script: echo hello
  - id: B
    name: Node B
    type: bash
    script: echo world
""")

        wf2 = tmp_path / "workflow2.yaml"
        wf2.write_text("""
name: Test Workflow 2
config:
  checkpoint_prefix: test2
nodes:
  - id: X
    name: Node X
    type: bash
    script: echo test
""")

        run_list(str(tmp_path))

        captured = capsys.readouterr()
        assert "Test Workflow 1" in captured.out
        assert "Test Workflow 2" in captured.out
        assert "workflow1.yaml" in captured.out
        assert "workflow2.yaml" in captured.out
        assert "user_id" in captured.out
        assert "(none)" in captured.out  # workflow2 has no inputs

    def test_list_empty_directory(self, tmp_path: Path, capsys) -> None:
        """List empty directory shows no workflows found message."""
        run_list(str(tmp_path))

        captured = capsys.readouterr()
        assert "No workflows found." in captured.out

    def test_list_json_output(self, tmp_path: Path, capsys) -> None:
        """List with --json outputs valid JSON array."""
        wf = tmp_path / "test.yaml"
        wf.write_text("""
name: JSON Test
config:
  checkpoint_prefix: json_test
inputs:
  param1:
    type: string
    required: true
  param2:
    type: integer
    required: false
nodes:
  - id: A
    name: Node A
    type: bash
    script: echo test
  - id: B
    name: Node B
    type: bash
    script: echo test2
""")

        run_list(str(tmp_path), json_output=True)

        captured = capsys.readouterr()
        import json
        data = json.loads(captured.out)
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["file"] == "test.yaml"
        assert data[0]["name"] == "JSON Test"
        assert data[0]["nodes"] == 2
        assert data[0]["inputs"] == ["param1", "param2"]
        assert data[0]["checkpoint_prefix"] == "json_test"

    def test_list_skips_invalid_yaml(self, tmp_path: Path, capsys) -> None:
        """List skips invalid YAML files silently."""
        # Valid workflow
        valid = tmp_path / "valid.yaml"
        valid.write_text("""
name: Valid Workflow
config:
  checkpoint_prefix: valid
nodes:
  - id: A
    name: Node A
    type: bash
    script: echo test
""")

        # Invalid YAML (missing required fields)
        invalid = tmp_path / "invalid.yaml"
        invalid.write_text("""
name: Missing Config
nodes:
  - id: A
""")

        # Not a workflow YAML
        random = tmp_path / "random.yaml"
        random.write_text("some: random\ndata: here")

        run_list(str(tmp_path))

        captured = capsys.readouterr()
        assert "Valid Workflow" in captured.out
        assert "Missing Config" not in captured.out
        assert "random" not in captured.out

    def test_list_invalid_directory(self, capsys) -> None:
        """List with non-existent directory prints error and exits."""
        with pytest.raises(SystemExit) as exc_info:
            run_list("/nonexistent/directory")

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "Error" in captured.err
        assert "not a directory" in captured.err


class TestRunInfo:
    """Test run_info function for workflow details."""

    def test_info_shows_workflow_details(self, tmp_path: Path, capsys) -> None:
        """Info shows comprehensive workflow details."""
        wf = tmp_path / "detail_test.yaml"
        wf.write_text("""
name: Detail Test Workflow
config:
  checkpoint_prefix: detail_test
  worktree: true
inputs:
  user_id:
    type: string
    required: true
  debug:
    type: boolean
    required: false
    default: false
nodes:
  - id: A
    name: Node A
    type: bash
    script: echo A
  - id: B
    name: Node B
    type: python
    script: print('B')
    depends_on: [A]
  - id: C
    name: Node C
    type: bash
    script: echo C
    depends_on: [A]
outputs:
  result:
    node: B
    field: output
""")

        run_info(str(wf))

        captured = capsys.readouterr()
        # Check workflow metadata
        assert "Detail Test Workflow" in captured.out
        assert "detail_test.yaml" in captured.out
        assert "detail_test" in captured.out

        # Check inputs
        assert "Inputs:" in captured.out
        assert "user_id: string (required)" in captured.out
        assert "debug: boolean (optional)" in captured.out
        assert "default: False" in captured.out

        # Check node summary by type
        assert "Nodes: 3 total" in captured.out
        assert "bash: 2" in captured.out
        assert "python: 1" in captured.out

        # Check execution plan
        assert "Execution Plan:" in captured.out
        assert "Layer 0" in captured.out
        assert "Layer 1" in captured.out
        assert "Node A" in captured.out
        assert "Node B" in captured.out
        assert "Node C" in captured.out

        # Check outputs
        assert "Outputs:" in captured.out
        assert "result: from B.output" in captured.out

    def test_info_shows_exit_hooks(self, tmp_path: Path, capsys) -> None:
        """Info shows exit hooks when present."""
        wf = tmp_path / "hooks_test.yaml"
        wf.write_text("""
name: Hooks Test
config:
  checkpoint_prefix: hooks
  on_exit:
    - id: cleanup
      type: bash
      script: rm -rf /tmp/test
      run_on: [completed, failed]
nodes:
  - id: A
    name: Node A
    type: bash
    script: echo A
""")

        run_info(str(wf))

        captured = capsys.readouterr()
        assert "Exit Hooks:" in captured.out
        assert "cleanup: bash (runs on: completed, failed)" in captured.out

    def test_info_with_no_inputs(self, tmp_path: Path, capsys) -> None:
        """Info works with workflows that have no inputs."""
        wf = tmp_path / "no_inputs.yaml"
        wf.write_text("""
name: No Inputs Workflow
config:
  checkpoint_prefix: no_inputs
nodes:
  - id: A
    name: Node A
    type: bash
    script: echo A
""")

        run_info(str(wf))

        captured = capsys.readouterr()
        assert "No Inputs Workflow" in captured.out
        assert "Nodes: 1 total" in captured.out
        # Should not have an "Inputs:" section
        lines = captured.out.split("\n")
        input_line_exists = any("Inputs:" in line for line in lines)
        assert not input_line_exists


class TestMainListInfo:
    """Test main entry point with list and info subcommands."""

    def test_main_list_subcommand(self, tmp_path: Path, capsys) -> None:
        """Main with list subcommand exits successfully."""
        wf = tmp_path / "test.yaml"
        wf.write_text("""
name: Test
config:
  checkpoint_prefix: test
nodes:
  - id: A
    name: Node A
    type: bash
    script: echo A
""")

        with patch("sys.argv", ["dag-exec", "list", str(tmp_path)]):
            with pytest.raises(SystemExit) as exc_info:
                main()

            assert exc_info.value.code == 0
            captured = capsys.readouterr()
            assert "Test" in captured.out

    def test_main_info_subcommand(self, tmp_path: Path, capsys) -> None:
        """Main with info subcommand exits successfully."""
        wf = tmp_path / "test.yaml"
        wf.write_text("""
name: Info Test
config:
  checkpoint_prefix: info_test
nodes:
  - id: A
    name: Node A
    type: bash
    script: echo A
""")

        with patch("sys.argv", ["dag-exec", "info", str(wf)]):
            with pytest.raises(SystemExit) as exc_info:
                main()

            assert exc_info.value.code == 0
            captured = capsys.readouterr()
            assert "Info Test" in captured.out
            assert "Execution Plan:" in captured.out

    def test_original_syntax_still_works(self, tmp_path: Path, capsys) -> None:
        """Original dag-exec workflow.yaml syntax still works."""
        wf = tmp_path / "original.yaml"
        wf.write_text("""
name: Original Syntax
config:
  checkpoint_prefix: original
nodes:
  - id: A
    name: Node A
    type: bash
    script: echo A
""")

        with patch("sys.argv", ["dag-exec", str(wf), "--dry-run"]), \
             patch("dag_executor.cli.load_workflow") as mock_load:

            from dag_executor.schema import WorkflowDef, WorkflowConfig, NodeDef
            mock_load.return_value = WorkflowDef(
                name="Original Syntax",
                config=WorkflowConfig(checkpoint_prefix="original"),
                nodes=[NodeDef(id="A", name="Node A", type="bash", script="echo A")],
            )

            with pytest.raises(SystemExit) as exc_info:
                main()

            assert exc_info.value.code == 0
            captured = capsys.readouterr()
            assert "Execution Plan" in captured.out


def test_list_scans_multiple_dirs_from_env_var(tmp_path: Path, monkeypatch: Any, capsys) -> None:
    """Test that 'dag-exec list' scans multiple directories from DAG_DASHBOARD_WORKFLOWS_DIR."""
    import os

    # Create two directories with workflows
    dir1 = tmp_path / "dir1"
    dir1.mkdir()
    wf1 = dir1 / "workflow-a.yaml"
    wf1.write_text("""
name: workflow-a
config:
  checkpoint_prefix: wa
nodes:
  - id: task1
    name: Task 1
    type: bash
    script: echo "a"
""")

    dir2 = tmp_path / "dir2"
    dir2.mkdir()
    wf2 = dir2 / "workflow-b.yaml"
    wf2.write_text("""
name: workflow-b
config:
  checkpoint_prefix: wb
nodes:
  - id: task2
    name: Task 2
    type: bash
    script: echo "b"
""")

    # Collision: dir2 also defines workflow-a (should be shadowed by dir1)
    wf1_collision = dir2 / "workflow-a.yaml"
    wf1_collision.write_text("""
name: workflow-a
config:
  checkpoint_prefix: wa-shadow
nodes:
  - id: task3
    name: Task 3
    type: bash
    script: echo "collision"
""")

    # Set env var with both directories
    monkeypatch.setenv("DAG_DASHBOARD_WORKFLOWS_DIR", f"{dir1}{os.pathsep}{dir2}")

    # Call run_list directly (directory="." triggers env-var lookup)
    run_list(".", json_output=True)
    captured = capsys.readouterr()
    workflows = json.loads(captured.out)

    assert len(workflows) == 2
    names = {wf["name"] for wf in workflows}
    assert names == {"workflow-a", "workflow-b"}

    # Verify first-dir-wins: workflow-a source_dir is dir1, not dir2
    wf_a = next(wf for wf in workflows if wf["name"] == "workflow-a")
    assert wf_a["source_dir"] == str(dir1)

    # Verify workflow-a comes from dir1
    wf_a = next(wf for wf in workflows if wf["name"] == "workflow-a")
    assert wf_a["source_dir"] == str(dir1)


def test_model_override_flag_injected_into_inputs(tmp_path):
    """--model-override sonnet injects into inputs as __model_override__."""
    workflow_yaml = tmp_path / "test.yaml"
    workflow_yaml.write_text("""
name: test_workflow
config:
  checkpoint_prefix: test
default_model: local
nodes:
  - id: node1
    name: Test
    type: prompt
    prompt: "test"
""")
    
    # Run with --model-override
    args = parse_args([str(workflow_yaml), "--model-override", "sonnet"])
    inputs = parse_inputs(args.inputs)
    
    # Inject model override as CLI does
    if args.model_override:
        inputs["__model_override__"] = args.model_override
    
    assert inputs["__model_override__"] == "sonnet"


def test_model_override_invalid_value_rejected():
    """--model-override with invalid value is rejected by argparse."""
    workflow_yaml = Path("test.yaml")
    
    # This should fail during argument parsing
    with pytest.raises(SystemExit):
        parse_args([str(workflow_yaml), "--model-override", "invalid"])
