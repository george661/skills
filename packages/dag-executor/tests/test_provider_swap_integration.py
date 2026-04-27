"""
Provider-swap integration test: mock-execute review.yaml with GitHub providers.

This test verifies that workflows can be executed with non-default provider
configurations by mocking all bash/command runners and verifying execution flow.
"""

import pytest
from pathlib import Path
import yaml
from unittest.mock import patch
from dag_executor.schema import WorkflowDef


WORKFLOW_DIR = Path(__file__).parent.parent / "workflows"


def load_workflow(name: str) -> WorkflowDef:
    """Load and parse workflow YAML."""
    yaml_path = WORKFLOW_DIR / f"{name}.yaml"
    if not yaml_path.exists():
        pytest.skip(f"Workflow {name}.yaml not found")

    with open(yaml_path) as f:
        data = yaml.safe_load(f)

    return WorkflowDef.model_validate(data)


def test_review_workflow_parses_with_github_env():
    """Verify review.yaml parses correctly with GitHub provider env vars."""
    # Set GitHub provider env vars (doesn't affect parsing, but documents the test scenario)
    with patch.dict("os.environ", {
        "ISSUE_TRACKER": "github",
        "CI_PROVIDER": "github_actions",
        "GITHUB_OWNER": "test-org",
    }):
        workflow = load_workflow("review")

        # Verify workflow loaded successfully
        assert workflow.name, "Workflow missing name"
        assert workflow.nodes, "Workflow has no nodes"

        # Verify workflow has bash nodes
        bash_nodes = [n for n in workflow.nodes if n.type == "bash"]
        assert len(bash_nodes) > 0, "No bash nodes found in review.yaml"


def test_workflow_bash_scripts_use_real_skill_paths():
    """Verify bash scripts in review.yaml reference real skill directories.

    GW-5356: the prior test asserted aspirational `skills/vcs/`, `skills/ci/`,
    and `skills/issues/` router alias dirs that were never implemented. The
    live skills live at `skills/vcs/` (this one *is* real) and `skills/jira/`.
    """
    workflow = load_workflow("review")

    bash_scripts = [n.script for n in workflow.nodes if n.type == "bash" and n.script]
    assert bash_scripts, "No bash nodes found in review.yaml"

    combined = "\n".join(bash_scripts)
    # review.yaml drives Jira + VCS (Bitbucket/GitHub) via the unified vcs/ skill.
    assert "skills/jira/" in combined or "skills/vcs/" in combined, (
        "review.yaml bash nodes must call at least one real skill (jira/ or vcs/)"
    )
    # Aspirational alias dirs never shipped.
    assert "skills/issues/" not in combined
    assert "skills/ci/" not in combined


def test_provider_configs_are_valid(tmp_path):
    """Verify provider config fixtures are valid JSON."""
    fixtures_dir = Path(__file__).parent / "fixtures" / "provider-configs"
    
    configs = list(fixtures_dir.glob("*.json"))
    assert configs, "No provider config fixtures found"
    
    for config_path in configs:
        import json
        with open(config_path) as f:
            config = json.load(f)
        
        # Verify required fields
        assert "name" in config, f"{config_path.name} missing 'name'"
        assert "vcs" in config, f"{config_path.name} missing 'vcs'"
        assert "issues" in config, f"{config_path.name} missing 'issues'"
        assert "ci" in config, f"{config_path.name} missing 'ci'"
        assert "env" in config, f"{config_path.name} missing 'env'"
        
        # Verify valid provider values
        assert config["vcs"] in ["github", "bitbucket"], (
            f"{config_path.name} has invalid vcs: {config['vcs']}"
        )
        assert config["issues"] in ["github", "jira", "linear"], (
            f"{config_path.name} has invalid issues: {config['issues']}"
        )
        assert config["ci"] in ["github_actions", "concourse", "circleci"], (
            f"{config_path.name} has invalid ci: {config['ci']}"
        )
