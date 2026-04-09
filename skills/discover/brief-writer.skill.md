---
name: discover-brief-writer
description: >
  Converts idea-interview output into a structured Feature Brief document.
  The brief is the bridge between stakeholder discovery and engineering planning —
  human-readable, jargon-free, and structured to feed directly into /plan.
---

# Brief Writer Skill

## Purpose

The Feature Brief is the output of discovery. It is:
- **Human-readable**: written for stakeholders and engineers equally
- **Structured enough** to drive `/plan` (PRP creation) and `/design`
- **Not a PRD**: it does not contain wire flows, technical specs, or acceptance criteria — those come later
- **Stored in project-docs**: at `${PROJECT_ROOT}/${DOCS_REPO}/features/` for discoverability

---

## Input

Takes output from `idea-interview.skill.md` (JSON session state) plus any
additional context gathered during the session.

---

## Brief Format

Write the brief to:
```
${PROJECT_ROOT}/${DOCS_REPO}/features/YYYY-MM-DD-{slug}-brief.md
```

Where `{slug}` is a 3-5 word dasherized version of the feature title.

---

### Brief Template

```markdown
---
title: "{Feature Title}"
status: draft
type: feature-brief
domain: {sessions|tokens|marketplace|auth|organizations|publishers|platform|infrastructure|general}
created: YYYY-MM-DD
personas: ["{primary persona}", "{secondary persona}"]
jira_epic: null
roadmap_status: Proposed
---

# {Feature Title}

## Problem

{1-3 sentences describing the problem in plain language. Who experiences it, when,
and what happens as a result. No technical framing.}

## Who Benefits

| Persona | How They Benefit |
|---------|-----------------|
| {persona 1} | {outcome in plain language} |
| {persona 2} | {outcome, if applicable} |

## What This Enables

{Describe what users can do after this is built that they cannot do today.
Written as a capability statement, not a user story. 2-4 sentences.}

## What Success Looks Like

{How we'll know this worked. Observable outcomes the stakeholder cares about.
Can be qualitative ("publishers no longer need to email support") or
quantitative ("X% reduction in..."). 2-4 bullet points.}

## Scope Notes

**In scope:**
- {key things this covers}

**Out of scope (for this effort):**
- {important exclusions that prevent scope creep}

## Constraints

{Any hard requirements: deadlines, compliance, must-work-with, must-avoid.
If none, write "None identified."}

## Dependencies

{Other features, decisions, or external things this idea relies on.
If none, write "None identified."}

## Related Work

{Links to related PRPs, existing features, or prior discovery sessions.
If none, write "No directly related work found."}

## Open Questions

{Questions that need answers before or during implementation. If none, write "None."}

## Suggested Next Steps

- [ ] Stakeholder review and sign-off on this brief
- [ ] Create Jira Epic: `/discover:epic {feature-title}`
- [ ] Full planning: `/plan {JIRA-KEY}` after epic is created
- [ ] Design phase: `/design {feature-title}` once PRP is complete
```

---

## Domain Classification

Classify the domain by asking: what part of the platform owns this feature?

| Domain | Owns |
|--------|------|
| `sessions` | Application session lifecycle, session purchase, session launch |
| `tokens` | SMART token balance, spending, transfers, ledger |
| `marketplace` | Application/dataset discovery, listing, search |
| `auth` | Login, identity, Cognito, permissions |
| `organizations` | Org management, membership, roles, budgets |
| `publishers` | Publisher onboarding, app management, revenue splits |
| `platform` | Admin tools, UI/UX, global features |
| `infrastructure` | CI/CD, testing, observability, data pipelines |
| `general` | Cross-cutting, unclear, or multiple domains |

---

## Completeness Check

Before saving, verify:

- [ ] Problem is stated in plain language (no tech jargon)
- [ ] At least one persona named
- [ ] Success criteria are observable (not "users like it")
- [ ] Scope notes explicitly exclude at least one thing
- [ ] Domain is classified
- [ ] File saved to `${PROJECT_ROOT}/${DOCS_REPO}/features/`

If any check fails, add an `<!-- INCOMPLETE: reason -->` comment in the brief
and flag it as `status: draft` so it surfaces for follow-up.

---

## After Writing

1. Display the brief to the stakeholder
2. Ask: "Does this capture the idea accurately? Anything to add or correct?"
3. On confirmation, set `status: draft` → keep as draft until stakeholder approves
4. On approval, update `status: evergreen`
5. Update `_index.yaml` in the features directory if one exists
