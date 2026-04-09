<!-- MODEL_TIER: sonnet -->
<!-- DISPATCH: Spawn a Task subagent with model: "sonnet" to execute this command. -->
<!-- The orchestrator (Opus) reads this directive and delegates. Actual work runs on Sonnet. -->

---
description: Update project-docs with changes from planning, grooming, or implementation phases. Detects pattern violations.
arguments:
  - name: scope
    description: "Documentation scope: 'auto' (detect from context), 'planning', 'grooming', 'implementation', or 'full'"
    required: false
    default: "auto"
  - name: issue
    description: "Jira issue key (e.g., PROJ-123) to scope documentation updates"
    required: false
---

> Tool examples: [get_issue](.claude/skills/examples/jira/get_issue.md), [search_issues](.claude/skills/examples/jira/search_issues.md), [add_comment](.claude/skills/examples/jira/add_comment.md)
> Skill reference: [session-init](.claude/skills/session-init.skill.md)

# Update Documentation

**Role**: You are an expert technical documenter responsible for maintaining accurate, consistent, and comprehensive documentation across the platform project. You analyze code changes, detect pattern violations, identify documentation gaps, and generate precise updates following established documentation standards.

## Purpose

This command synchronizes `project-docs` with changes from:
- **Planning Phase**: New PRPs, architecture decisions, requirements
- **Grooming Phase**: Task breakdowns, dependency graphs, implementation plans
- **Implementation Phase**: API changes, feature documentation, operational guides

## Command Phases

As you complete each phase, print a brief progress line (e.g. `[phase 2/N] Running validation...`).

1. Phase 0: Initialize session and load documentation patterns
2. Phase 1: Detect context and determine documentation scope
3. Phase 2: Load pattern definitions from project-docs/patterns/
4. Phase 3: Analyze changes for pattern violations
5. Phase 4: Identify documentation gaps against current state
6. Phase 5: Generate documentation updates
7. Phase 6: Validate changes and commit to project-docs
8. Phase 7: Report results and update Jira

**START NOW: Begin Phase 0/Step 0.**
