---
name: plan
description: Design domain model changes and create implementation plan from Epic or free-text. Agent-invokeable wrapper for /plan command.
agent-invokeable: true
---

# Plan Skill

## Purpose

Agent-invokeable skill for creating implementation plans. **Design starts in the domain model.** Before writing the PRP, the plan command proposes CML changes (new aggregates, entities, commands, events, flows) that inform the entire implementation plan.

Wraps the /plan command for use by subagents and automated workflows.

> **Skill reference:** [domain-context](.claude/skills/domain-context.skill.md)
> **CML skills:** [cml](.claude/skills/cml/)

## Usage

```typescript
// Via Task tool
Task tool:
  subagent_type: "planner"
  prompt: `
    Execute the plan skill for: [Epic key or description]

    Follow the /plan command workflow exactly.
    Design starts in the domain model — propose CML changes before writing the PRP.
  `

// Via direct invocation
/plan PROJ-123
/plan "Add dark mode toggle to settings page"
```

## Input Types

1. **Jira Epic Key** (e.g., `PROJ-123`)
   - Fetches Epic details from Jira
   - Designs domain model changes
   - Creates PRP in standard format

2. **Free-Text Description**
   - Triggers brainstorm phase
   - Creates Epic from description
   - Designs domain model changes
   - Then creates PRP

## Workflow

1. PRE: Search AgentDB for patterns
2. Input Detection (Epic vs free-text)
3. [If free-text] Brainstorm phases
4. [If free-text] Create Epic
5. **Domain Model Design** — load CML, identify affected bounded contexts, propose new/modified aggregates, commands, events, flows
6. Create PRP document (informed by domain design — includes Domain Model Design section)
7. Three-pass review (First, Architectural + Security, Second)
8. Commit PRP to DOCUMENT_REPO
9. Link to Epic in Jira
10. Auto-validate with /validate-plan
11. POST: Store episode in AgentDB

## Domain Model Design (Phase 1.5)

When a domain model is available (`TENANT_DOMAIN_PATH` set):

1. Load domain-index.json and identify affected bounded contexts
2. Propose CML changes: new aggregates, entities, commands, events, flows
3. Flag cross-context coordination with ContextMap relationships
4. Include Domain Model Design section in PRP with:
   - Bounded contexts affected (with justification)
   - Proposed CML changes table
   - Cross-context integration points
   - CML update required flag (always YES if changes proposed)

The domain design informs implementation tasks, acceptance criteria, and repository assignments.

## Output

- PRP document in `${DOCUMENT_REPO}/PRPs/MVP/PRP-XXX-{slug}.md`
- PRP includes Domain Model Design section with proposed CML changes
- Epic updated with PRP link
- Validation verdict

## Command Reference

See `.claude/commands/plan.md` for full implementation details.
