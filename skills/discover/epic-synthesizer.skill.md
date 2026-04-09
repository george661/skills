---
name: discover-epic-synthesizer
description: >
  Converts an approved Feature Brief into a Jira Epic and a PRP seed document.
  Updates the roadmap with the Jira key. Produces the minimal structure needed
  to hand off to /plan for full PRP development.
---

# Epic Synthesizer Skill

## Purpose

Bridges discovery and engineering. Takes a Feature Brief (human-readable) and
produces:
1. A Jira Epic with enough context for engineers to understand the scope
2. A PRP seed file — pre-populated frontmatter and problem statement, ready for `/plan`
3. A roadmap update linking the initiative to the Jira key

---

## Input Requirements

Before running, verify:
- [ ] Feature brief exists at `${PROJECT_ROOT}/${DOCS_REPO}/features/YYYY-MM-DD-slug-brief.md`
- [ ] Brief `status` is `evergreen` (stakeholder-approved)
- [ ] Domain is classified in brief frontmatter

If brief is still `draft`, stop and ask the stakeholder to review and approve first.

---

## Step 1: Create Jira Epic

### Epic Fields

| Field | Value |
|-------|-------|
| `issuetype` | `Epic` |
| `project` | `${TENANT_PROJECT}` |
| `summary` | `[EPIC] {Feature Title}` |
| `description` | See template below |
| `priority` | Mapped from brief (`Critical/High/Medium/Low`) |
| `labels` | `["repo-project-docs", "discovery", "{domain}"]` |

### Epic Description Template

```
## Problem

{problem from brief — verbatim}

## Who Benefits

{personas table from brief}

## What This Enables

{capability statement from brief}

## Success Criteria

{success criteria from brief}

## Scope

{in scope / out of scope from brief}

## Constraints

{constraints from brief}

## Dependencies

{dependencies from brief}

## Discovery Brief

${PROJECT_ROOT}/${DOCS_REPO}/features/{brief-filename}.md

## Next Steps

1. Run `/plan {EPIC-KEY}` to create the full PRP
2. Run `/design {feature-title}` after PRP is complete
3. Run `/groom {EPIC-KEY}` to break into implementation issues
```

### Create via Skill

```bash
cd "${PROJECT_ROOT}" && npx tsx .claude/skills/jira/create_issue.ts '{
  "project_key": "${TENANT_PROJECT}",
  "summary": "[EPIC] {Feature Title}",
  "issue_type": "Epic",
  "description": "{description}",
  "priority": "{priority}",
  "labels": ["discovery", "{domain}"]
}'
```

Capture the returned issue key (e.g., `PROJ-2400`).

---

## Step 2: Create PRP Seed

Write a minimal PRP to `${PROJECT_ROOT}/${DOCS_REPO}/prps/{domain}/PRP-{phase}-{number}-{slug}.md`.

**PRP numbering:** Check existing PRPs in the domain directory to find the next available number.

### PRP Seed Template

```markdown
---
title: "{Feature Title}"
status: draft
type: prp
domain: {domain}
created: YYYY-MM-DD
jira_epic: {PROJ-XXXX}
brief: features/YYYY-MM-DD-{slug}-brief.md
---

# {Feature Title}

**Status**: Draft — Awaiting `/plan {PROJ-XXXX}` for full development
**Jira Epic**: {PROJ-XXXX}
**Created from brief**: `features/YYYY-MM-DD-{slug}-brief.md`
**Affects**: TBD (determine during /plan)
**Dependencies**: TBD (determine during /plan)

---

## Problem Statement

{problem statement from brief — plain language}

---

## Requirements

> This section is a seed. Run `/plan {PROJ-XXXX}` to develop full requirements
> through domain analysis, stakeholder interview, and architectural review.

### Functional Requirements (Seed)

Based on the discovery brief, the following capabilities are needed:

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-1 | {Derived from "What This Enables" in brief} | MUST |

### Success Criteria (from brief)

{success criteria list}

---

## Next Steps

1. Run `/plan {PROJ-XXXX}` — develop full PRP with domain analysis and validation criteria
2. After PRP is complete, run `/validate-prp {PROJ-XXXX}` to validate coverage
3. Run `/groom {PROJ-XXXX}` to create implementation issues
```

---

## Step 3: Update Roadmap

Use `roadmap-editor.skill.md` to:
1. Find the initiative matching this brief (by name or brief path)
2. Update `status` → `"Planned"`
3. Set `jira` → `"{PROJ-XXXX}"`
4. Set `brief` → `"features/{brief-filename}.md"`

---

## Step 4: Link PRP to Jira

Add a comment to the Jira epic:

```bash
cd "${PROJECT_ROOT}" && npx tsx .claude/skills/jira/add_comment.ts '{
  "issue_key": "{PROJ-XXXX}",
  "body": "PRP seed created: ${PROJECT_ROOT}/${DOCS_REPO}/prps/{domain}/{PRP-filename}\n\nRun /plan {PROJ-XXXX} to develop the full PRP."
}'
```

---

## Step 5: Transition Epic to Grooming

```bash
# Resolve GROOMING transition ID dynamically (transition_issue.ts requires numeric ID)
EPIC_KEY="{PROJ-XXXX}"
GROOMING_ID=$(cd "${PROJECT_ROOT}" && npx tsx .claude/skills/jira/list_transitions.ts   "{"issue_key": "$EPIC_KEY"}" |   python3 -c "import sys,json; d=json.load(sys.stdin); t=[x for x in d if x.get('name','').upper()=='GROOMING']; print(t[0]['id'] if t else '5')" 2>/dev/null || echo "5")
cd "${PROJECT_ROOT}" && npx tsx .claude/skills/jira/transition_issue.ts   "{"issue_key": "$EPIC_KEY", "transition_id": "$GROOMING_ID"}"
```

---

## Completion Output

Show a clear summary:

```
Epic created: {PROJ-XXXX} — {Feature Title}
PRP seed:     ${PROJECT_ROOT}/${DOCS_REPO}/prps/{domain}/{PRP-filename}
Roadmap:      Updated (INI-XXX → Planned, jira: {PROJ-XXXX})

Next step: /plan {PROJ-XXXX}
```
