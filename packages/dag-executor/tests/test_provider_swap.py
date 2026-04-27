"""
Skill-path sanity test: verify shipped workflows only reference skill dirs
that actually exist in ~/.claude/skills.

GW-5356: earlier revisions asserted an aspirational unified-router scheme
(skills/issues/, skills/ci/) that was never implemented. The live tree is a
mix of provider-specific dirs (jira/, concourse/, bitbucket/) and some real
unified aliases (vcs/). This test enforces "reference a real dir" rather than
any particular architectural preference — callers that discover a workflow
should be able to invoke its skill commands without ERR_MODULE_NOT_FOUND.
"""

import re
from pathlib import Path
from typing import List, Set
import yaml
import pytest

# Skill directories that actually ship today. Kept in sync with the live
# tree under ~/.claude/skills and this repo's skills/ directory.
KNOWN_SKILL_DIRS = {
    "skills/jira/",
    "skills/bitbucket/",
    "skills/github-issues/",
    "skills/github-actions/",
    "skills/github-mcp/",
    "skills/concourse/",
    "skills/fly/",
    "skills/vcs/",        # real hybrid router (PR ops)
    "skills/ci/",         # real hybrid router (build/CI ops)
    "skills/playwright/",
    "skills/slack/",
    "skills/agentdb/",
    "skills/domain-map/",
    "skills/cml/",
    "skills/linear/",
}

# Aspirational alias dirs that were specified in prior tickets (GW-5045) but
# never shipped. References to these will hard-fail at runtime.
NEVER_SHIPPED_ALIASES = {
    "skills/issues/",
}

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


@pytest.mark.parametrize("workflow_name", WORKFLOW_NAMES)
def test_workflow_uses_real_skill_paths(workflow_name):
    """Every skill path referenced by a workflow must exist in KNOWN_SKILL_DIRS.

    Prevents the GW-5356 class of bug: a workflow compiles clean at lint time
    but calls `npx tsx ~/.claude/skills/<alias>/foo.ts` where <alias> is not
    a real directory, so the node silently fails at runtime.
    """
    workflow = load_workflow(workflow_name)
    scripts = extract_bash_scripts(workflow)
    skill_paths = find_skill_paths(scripts)

    unknown = [
        p for p in sorted(skill_paths)
        if not any(p.startswith(prefix) for prefix in KNOWN_SKILL_DIRS)
    ]
    never_shipped = [
        p for p in sorted(skill_paths)
        if any(p.startswith(prefix) for prefix in NEVER_SHIPPED_ALIASES)
    ]

    assert not never_shipped, (
        f"Workflow {workflow_name} references aliases that were never "
        f"implemented: {never_shipped}"
    )
    assert not unknown, (
        f"Workflow {workflow_name} references skill paths that aren't in "
        f"KNOWN_SKILL_DIRS: {unknown}. Either the path is wrong or the "
        f"registry in test_provider_swap.py needs updating."
    )


def test_known_skill_dirs_exist_on_disk():
    """Every entry in KNOWN_SKILL_DIRS must exist under ~/.claude/skills or
    this repo's skills/ tree. Keeps the registry honest."""
    home_skills = Path.home() / ".claude" / "skills"
    repo_skills = Path(__file__).parent.parent.parent.parent / "skills"

    missing = []
    for entry in sorted(KNOWN_SKILL_DIRS):
        dirname = entry.removeprefix("skills/").rstrip("/")
        if not ((home_skills / dirname).is_dir() or (repo_skills / dirname).is_dir()):
            missing.append(entry)

    assert not missing, (
        f"KNOWN_SKILL_DIRS contains entries that don't exist on disk: {missing}"
    )


def _legacy_known_gaps_placeholder():
    """Stub retained so any external harness that imports this module by
    attribute name (rare) doesn't crash. Can be deleted in a future pass."""
    all_skill_paths: Set[str] = set()

    for workflow_name in WORKFLOW_NAMES:
        workflow = load_workflow(workflow_name)
        scripts = extract_bash_scripts(workflow)
        skill_paths = find_skill_paths(scripts)
        all_skill_paths.update(skill_paths)
    # Body retained only for symbol stability; no assertion.
    _ = all_skill_paths


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


# test_unified_paths_are_used removed in GW-5356: it asserted the existence
# of a unified-router scheme that never shipped in full. The `skills/vcs/`
# and `skills/ci/` routers that did ship are counted by
# test_workflow_uses_real_skill_paths via KNOWN_SKILL_DIRS.
