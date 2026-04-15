"""Discovery-based validation for all workflow YAML files.

Automatically finds every *.yaml file in the workflows/ directory and
validates it against the DAG schema via load_workflow(). This ensures
that new workflows cannot be merged without passing schema validation,
even if no per-workflow test file exists yet.
"""
from pathlib import Path
from typing import List

import pytest

from dag_executor.graph import topological_sort_with_layers
from dag_executor.parser import load_workflow
from dag_executor.schema import WorkflowDef


WORKFLOWS_DIR = Path(__file__).parent.parent / "workflows"


def discover_workflows() -> List[Path]:
    """Find all YAML workflow files in the workflows directory."""
    return sorted(WORKFLOWS_DIR.glob("*.yaml"))


@pytest.fixture(params=discover_workflows(), ids=lambda p: p.stem)
def workflow_path(request: pytest.FixtureRequest) -> Path:
    """Parametrized fixture yielding each discovered workflow path."""
    return request.param


@pytest.fixture
def workflow(workflow_path: Path) -> WorkflowDef:
    """Load and return the workflow definition."""
    return load_workflow(str(workflow_path))


class TestSchemaValidation:
    """Every workflow YAML must parse and pass Pydantic schema validation."""

    def test_loads_without_error(self, workflow: WorkflowDef) -> None:
        """Workflow loads through load_workflow() with no exceptions."""
        assert workflow.name, "Workflow must have a name"
        assert len(workflow.nodes) >= 1, "Workflow must have at least one node"

    def test_config_present(self, workflow: WorkflowDef) -> None:
        """Workflow has required config with checkpoint_prefix."""
        assert workflow.config.checkpoint_prefix, (
            "Workflow config must define checkpoint_prefix"
        )


class TestNodeIntegrity:
    """Node references must be internally consistent."""

    def test_no_duplicate_node_ids(self, workflow: WorkflowDef) -> None:
        """All node IDs are unique within the workflow."""
        ids = [n.id for n in workflow.nodes]
        assert len(ids) == len(set(ids)), (
            f"Duplicate node IDs: {[x for x in ids if ids.count(x) > 1]}"
        )

    def test_depends_on_references_exist(
        self, workflow: WorkflowDef
    ) -> None:
        """Every depends_on reference points to a node that exists."""
        valid_ids = {n.id for n in workflow.nodes}
        for node in workflow.nodes:
            for dep in node.depends_on:
                assert dep in valid_ids, (
                    f"Node '{node.id}' depends on '{dep}' which does not exist"
                )

    def test_no_cycles(self, workflow: WorkflowDef) -> None:
        """DAG has no circular dependencies."""
        # topological_sort_with_layers raises CycleDetectedError on cycles
        layers = topological_sort_with_layers(workflow.nodes)
        assert len(layers) >= 1, "Topological sort must produce at least one layer"


class TestOutputReferences:
    """Workflow outputs must reference valid nodes and fields."""

    def test_output_nodes_exist(self, workflow: WorkflowDef) -> None:
        """Every output references a node that exists in the workflow."""
        valid_ids = {n.id for n in workflow.nodes}
        for name, out_def in workflow.outputs.items():
            assert out_def.node in valid_ids, (
                f"Output '{name}' references node '{out_def.node}' "
                f"which does not exist"
            )
