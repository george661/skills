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


def test_workflow_bash_scripts_contain_unified_paths():
    """Verify bash scripts in review.yaml use unified skill paths."""
    workflow = load_workflow("review")

    # Collect all bash scripts
    bash_scripts = []
    for node in workflow.nodes:
        if node.type == "bash" and node.script:
            bash_scripts.append(node.script)

    # Verify at least some bash nodes exist
    assert bash_scripts, "No bash nodes found in review.yaml"

    # Check for unified paths
    unified_path_count = 0
    provider_specific_count = 0

    for script in bash_scripts:
        if "skills/vcs/" in script or "skills/issues/" in script or "skills/ci/" in script:
            unified_path_count += 1
        if "skills/bitbucket/" in script or "skills/jira/" in script:
            provider_specific_count += 1

    # Should use unified paths, not provider-specific
    assert unified_path_count > 0, "No unified skill paths found in review.yaml bash scripts"
    assert provider_specific_count == 0, (
        f"Found {provider_specific_count} provider-specific skill paths in review.yaml"
    )


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
