<!-- MODEL_TIER: haiku -->
---
description: >
  View, add to, and update the product roadmap. Shows current initiatives by status,
  lets stakeholders add new ideas, update priorities, and link Jira epics.
  Validates JSON schema before committing any changes.
arguments:
  - name: action
    description: "What to do: view (default), add, update, or status"
    required: false
  - name: --add
    description: Name of new initiative to add to the roadmap
    required: false
  - name: --id
    description: Initiative ID to update (e.g. INI-012)
    required: false
  - name: --status
    description: New status to set (Proposed|Planned|In Progress|Done|Deferred)
    required: false
  - name: --jira
    description: Jira key to link to an initiative (e.g. PROJ-2400)
    required: false
agent-invokeable: true
---

> **Skill references:**
> - [discover/roadmap-editor](.claude/skills/discover/roadmap-editor.skill.md)
> - [discover/platform-context](.claude/skills/discover/platform-context.skill.md)

**Announce:** "Running /discover:roadmap."

---

## Routing

| Arguments | Action |
|-----------|--------|
| No arguments | View roadmap grouped by status |
| `view` | View roadmap grouped by status |
| `--add "{name}"` | Add new initiative |
| `--id INI-XXX --status X` | Update initiative status |
| `--id INI-XXX --jira PROJ-XXXX` | Link Jira key to initiative |
| `status` | Show summary counts by status |

---

## View Mode (default)

Run `discover/roadmap-editor.skill.md` view operation.

Format output for human reading:

```
## Roadmap

### In Progress
  - [INI-003] Marketplace search (PROJ-1902)
  - [INI-007] Dataset wizard UI validation (PROJ-2108)

### Planned
  - [INI-009] Stripe sandbox E2E validation (PROJ-2201)
  - [INI-011] Revealable secrets (PROJ-2301)

### Proposed
  - [INI-012] {New initiative}

### Deferred
  - [INI-004] WhisperNet integration — deferred pending partner decision

### Done (recent)
  - [INI-001] User referral links (PROJ-1701) ✓
  - [INI-002] Developer section RBAC (PROJ-1821) ✓
```

After display, ask: "Would you like to update any of these, or add a new initiative?"

---

## Add Mode (`--add`)

Prompt for missing details if not provided:
1. "What's a one-sentence description of this initiative?"
2. "What domain does it touch?" (show list: marketplace, sessions, tokens, etc.)
3. "How would you prioritize it?" (Critical / High / Medium / Low)
4. "Is there a feature brief for this?" (if yes, ask for filename)

Run roadmap-editor add operation.

Validate JSON:
```bash
python3 -c "import json; json.load(open('${TENANT_ROADMAP_PATH:-${PROJECT_ROOT}/${DOCS_REPO}/initiatives/roadmap.json}')); print('valid')"
```

Commit:
```bash
cd "${PROJECT_ROOT}"
git add "${TENANT_ROADMAP_PATH:-${PROJECT_ROOT}/${DOCS_REPO}/initiatives/roadmap.json}"
git commit -m "chore(roadmap): add {initiative name}"
```

---

## Update Mode (`--id`, `--status`, `--jira`)

Load the initiative by ID. Show current values. Confirm change:
"Updating INI-XXX from '{current}' to '{new}'. Confirm? [Y/n]"

Run roadmap-editor update operation.

Validate and commit.

---

## Status Summary Mode (`status`)

Show counts only:

```
Roadmap summary:
  In Progress:  3
  Planned:      5
  Proposed:     2
  Deferred:     1
  Done:         14
  Total:        25
```
