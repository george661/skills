"""
Provider-swap test: verify workflows use unified skill paths.

This test ensures all 5 DAG workflows (work, review, plan, validate, implement)
use provider-agnostic skill paths (skills/vcs/, skills/issues/, skills/ci/)
rather than provider-specific paths (skills/bitbucket/, skills/jira/, etc.).
"""

import re
from pathlib import Path
from typing import List, Set
import yaml
import pytest

# Known gaps — provider-specific paths that haven't been migrated yet
KNOWN_GAPS = [
    "skills/fly/wait-for-ci.ts",  # work.yaml:287 — CI router doesn't cover this yet
]

# Unified skill path prefixes (provider-agnostic)
UNIFIED_PREFIXES = [
    "skills/vcs/",
    "skills/issues/",
    "skills/ci/",
]

# Provider-specific skill paths (should NOT be used)
PROVIDER_SPECIFIC_PREFIXES = [
    "skills/bitbucket/",
    "skills/jira/",
    "skills/concourse/",
    "skills/fly/",  # allowed only for KNOWN_GAPS
    "skills/github/",
    "skills/github-mcp/",
    "skills/github-actions/",
    "skills/linear/",
]

WORKFLOW_DIR = Path(__file__).parent.parent / "workflows"
WORKFLOW_NAMES = ["work", "review", "plan", "validate", "implement"]


def load_workflow(name: str) -> dict:
    """Load workflow YAML file."""
    yaml_path = WORKFLOW_DIR / f"{name}.yaml"
    if not yaml_path.exists():
        pytest.skip(f"Workflow {name}.yaml not found at {yaml_path}")
    
    with open(yaml_path) as f:
        return yaml.safe_load(f)


def extract_bash_scripts(workflow: dict) -> List[str]:
    """Extract all bash script content from workflow nodes."""
    scripts = []

    nodes = workflow.get("nodes", [])
    for node in nodes:
        node_type = node.get("type", "")
        if node_type != "bash":
            continue

        # Bash scripts can be in 'script' or 'scriptPath'
        if "script" in node:
            scripts.append(node["script"])
        elif "scriptPath" in node:
            # scriptPath references an external file — not tested here
            pass

    return scripts


def find_skill_paths(scripts: List[str]) -> Set[str]:
    """Find all skill paths referenced in bash scripts."""
    skill_paths = set()
    
    # Pattern: ~/.claude/skills/<path>/<file>.ts
    pattern = r'~/\.claude/skills/([a-z0-9_/-]+\.ts)'
    
    for script in scripts:
        matches = re.findall(pattern, script)
        for match in matches:
            # Reconstruct as skills/<path>
            skill_paths.add(f"skills/{match}")
    
    return skill_paths


def categorize_skill_paths(skill_paths: Set[str]) -> dict:
    """Categorize skill paths as unified, provider-specific, or other."""
    categorized: dict = {
        "unified": [],
        "provider_specific": [],
        "known_gaps": [],
        "other": [],
    }
    
    for path in skill_paths:
        if path in KNOWN_GAPS:
            categorized["known_gaps"].append(path)
        elif any(path.startswith(prefix) for prefix in UNIFIED_PREFIXES):
            categorized["unified"].append(path)
        elif any(path.startswith(prefix) for prefix in PROVIDER_SPECIFIC_PREFIXES):
            categorized["provider_specific"].append(path)
        else:
            categorized["other"].append(path)
    
    return categorized


@pytest.mark.parametrize("workflow_name", WORKFLOW_NAMES)
def test_workflow_uses_unified_skill_paths(workflow_name):
    """Verify workflow uses only unified skill paths (no provider-specific)."""
    workflow = load_workflow(workflow_name)
    scripts = extract_bash_scripts(workflow)
    skill_paths = find_skill_paths(scripts)
    categorized = categorize_skill_paths(skill_paths)
    
    # All provider-specific paths should be in KNOWN_GAPS
    unexpected_provider_specific = [
        p for p in categorized["provider_specific"]
        if p not in KNOWN_GAPS
    ]
    
    assert not unexpected_provider_specific, (
        f"Workflow {workflow_name} uses provider-specific skill paths "
        f"that are not in KNOWN_GAPS: {unexpected_provider_specific}"
    )


def test_known_gaps_exist():
    """Verify KNOWN_GAPS are actually present in the workflows."""
    all_skill_paths = set()
    
    for workflow_name in WORKFLOW_NAMES:
        workflow = load_workflow(workflow_name)
        scripts = extract_bash_scripts(workflow)
        skill_paths = find_skill_paths(scripts)
        all_skill_paths.update(skill_paths)
    
    found_gaps = [gap for gap in KNOWN_GAPS if gap in all_skill_paths]
    
    # At least one known gap should exist (otherwise test expectation is stale)
    assert found_gaps, (
        f"KNOWN_GAPS are documented but not found in workflows. "
        f"Expected gaps: {KNOWN_GAPS}, Found: {found_gaps}"
    )


def test_all_workflows_parse():
    """Verify all workflow YAML files parse correctly."""
    for workflow_name in WORKFLOW_NAMES:
        workflow = load_workflow(workflow_name)
        assert workflow.get("name"), f"Workflow {workflow_name} missing 'name' field"
        assert workflow.get("nodes"), f"Workflow {workflow_name} missing 'nodes' field"


def test_skill_path_coverage():
    """Verify we found at least some skill paths to test."""
    all_skill_paths = set()
    
    for workflow_name in WORKFLOW_NAMES:
        workflow = load_workflow(workflow_name)
        scripts = extract_bash_scripts(workflow)
        skill_paths = find_skill_paths(scripts)
        all_skill_paths.update(skill_paths)
    
    # Should find at least 5 skill invocations across all workflows
    assert len(all_skill_paths) >= 5, (
        f"Expected at least 5 skill paths across workflows, found {len(all_skill_paths)}: "
        f"{sorted(all_skill_paths)}"
    )


def test_unified_paths_are_used():
    """Verify at least one workflow uses unified skill paths."""
    all_skill_paths = set()
    
    for workflow_name in WORKFLOW_NAMES:
        workflow = load_workflow(workflow_name)
        scripts = extract_bash_scripts(workflow)
        skill_paths = find_skill_paths(scripts)
        all_skill_paths.update(skill_paths)
    
    categorized = categorize_skill_paths(all_skill_paths)
    
    # At least one unified path should be used
    assert categorized["unified"], (
        f"No unified skill paths found. This suggests workflows haven't adopted "
        f"the router pattern yet. Found: {sorted(all_skill_paths)}"
    )
