"""Tests for CLI entry point."""
from pathlib import Path
from unittest.mock import patch

import pytest
from dag_executor.cli import parse_args, main, run_dry_run, run_visualize
from dag_executor.schema import WorkflowDef, WorkflowConfig, NodeDef, WorkflowStatus, NodeStatus, NodeResult
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
