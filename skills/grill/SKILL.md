---
name: grill
description: >
  Interactive grilling protocol that stress-tests a plan or issue draft against
  the project's CML domain model, the actual code on disk, and concrete edge-case
  scenarios. Walks the design tree one question at a time — each with a
  recommended answer — until decisions are crisp enough to author or groom.
  Adapted from grill-with-docs (mattpocock/skills) for GW's CML-first workflow.
---

# Grill Skill

## Purpose

The brainstorm phase produces a *direction*. The PRP authoring phase produces a
*document*. Grilling is the part in between: it interrogates the proposal until
we know which decisions are real, which are fuzzy, and which boundary cases
will trip us up. Without it, plans get committed with terms that mean different
things to different readers, scope that overlaps a sibling Epic, and "we'll
figure it out in implementation" placeholders that fall over the first time
/work hits a real edge case.

This skill is invoked by:
- `/plan` — Phase 1.6, after Phase 1.5 (Domain Model Design) and before Phase 1.7 (Test Requirements). Inputs: Epic summary/description, brainstorm output, proposed CML changes. Output: `GRILL_RESULT` consumed by Phase 2 PRP authoring.
- `/groom` — Phase 3.7, lightweight per-issue clarify pass. Inputs: drafted issue title/description/AC. Output: refined issue draft + any deviation annotations.

## Hard Rules

1. **One question at a time.** Wait for the answer. Never dump a list.
2. **Always provide a recommended answer.** A grill that asks open-ended questions stalls; a grill that proposes "I'd recommend X because Y — agree?" makes progress.
3. **Prefer code over questions.** If a question can be answered by reading the codebase, the CML model, or an existing PRP, do that *first* and present the finding. Only ask the user when sources disagree or are silent.
4. **Cap the session.** Default budget: 6 questions in `/plan` mode, 2 questions per issue in `/groom` mode. If the budget is reached and material ambiguity remains, surface it as an Open Question in the output rather than continuing to grill.
5. **No bureaucratic ADRs.** ADRs are written only when all three apply: hard to reverse, surprising without context, and the result of a real trade-off. Most decisions don't need one.

## When NOT to grill

Skip grilling entirely when:
- `WORK_TYPE == non-functional` (no design surface to challenge)
- The Epic is a pure dependency bump, lint fix, or doc-only change
- The PRP/issue is replaying an already-shipped pattern (existing PRP cited verbatim, no new domain concepts)

In these cases emit `[grill] Skipped — {reason}` and proceed.

---

## The Decision Tree

The grill walks a fixed tree. Each branch is only entered if the prior level surfaces something worth pressing on.

```
1. Problem framing
   ├─ Is the problem statement falsifiable? (we'd know if it's wrong)
   └─ Does the persona match an existing CML actor?

2. Terminology / glossary
   ├─ Does any user-supplied term clash with an existing CML aggregate / command / event?
   └─ Are overloaded words ("search", "recommend", "result") collapsing distinct concepts?

3. Scope boundaries
   ├─ Which bounded context owns this? (look it up in domain-index.json)
   ├─ Does it cross a context boundary? If so, who orchestrates?
   └─ Is there a sibling open Epic / PRP touching the same context?

4. Solution shape
   ├─ What's the smallest version that delivers value? (walking skeleton)
   ├─ What's deferred and why?
   └─ What invariant must hold across all variants? (the thing we'd never break)

5. Edge-case stress test
   ├─ Invent 2-3 concrete scenarios that probe the boundary between concepts
   └─ Force a precise answer ("partial cancellation: same Order, or new RefundRequest?")

6. Code cross-reference
   └─ When the user states "X works like Y today", grep for it. Surface contradictions.

7. ADR candidacy
   └─ Did any decision in 1-6 meet the hard-to-reverse + surprising + real-trade-off bar?
```

---

## Phase 0: Pre-grill Context Load

Before asking any question, load:

```bash
# CML domain model (the canonical glossary)
python3 -c "
import json, os
idx = json.load(open(os.path.join(os.environ.get('TENANT_DOMAIN_PATH',''), os.environ.get('TENANT_DOMAIN_INDEX','domain-index.json'))))
print('Contexts:', list(idx['contexts'].keys()))
for name, ctx in idx['contexts'].items():
    print(f'\\n{name}:')
    for agg in ctx.get('aggregates', [])[:10]:
        print(f'  Aggregate: {agg[\"name\"]}')
    for cmd in ctx.get('commands', [])[:10]:
        print(f'  Command:   {cmd[\"name\"]}')
"

# Sibling PRPs / design sessions touching same scope
grep -rl "{affected_repos}" "${PROJECT_ROOT}/${DOCS_REPO}/prps/" 2>/dev/null | head -5
find "${DESIGN_DOCS_PATH}/sessions" -name state.json 2>/dev/null | xargs grep -l "{affected_repos}" 2>/dev/null | head -3
```

If `TENANT_DOMAIN_PATH` is unset, log `[grill] CML cross-reference unavailable — terminology challenges will be qualitative only` and continue with reduced rigor.

Store the loaded context as `GRILL_CONTEXT`. Every question that follows must be checked against it before being asked.

---

## Phase 1: Problem Framing

### Q1 — Falsifiability

Look at the Epic description. If the problem statement is "users want X" or "we should support Y" without an observable signal, ask:

> "How would we know this problem is real? What would we measure today that proves it — or that we'd see decrease after shipping?"
>
> **Recommended:** {propose a measurable signal based on the brainstorm output, e.g. "session-launch failure rate from search results" or "% of search queries returning zero clicks within 30s"}

Skip if the Epic already cites a metric, dashboard, or support-ticket count.

### Q2 — Persona match

Take the persona named in the brainstorm. Compare against CML actors. If it doesn't match exactly, ask:

> "You said '{user-supplied-persona}'. The CML model has these actors: {list from domain-index}. Is '{persona}' the same as one of these, or genuinely new?"
>
> **Recommended:** {best CML match, with one-sentence reason}

If user confirms a new actor, add to GRILL_RESULT.cml_changes as a proposed actor addition.

---

## Phase 2: Terminology Sharpening

For each user-supplied noun in the Epic description, check against `GRILL_CONTEXT`:

- **Exact match in CML** → no question.
- **Near-match (different aggregate, similar concept)** → ask the disambiguation question.
- **Overloaded word** (e.g. "search" could mean keyword search, semantic search, or recommendation) → ask the precision question.
- **Novel term** → propose a CML naming.

### Disambiguation pattern

> "Your description uses '{user-term}'. The model has '{cml-term-1}' (in {context-A}) and '{cml-term-2}' (in {context-B}). Which one do you mean, or is this a third thing?"
>
> **Recommended:** {best CML match} **because** {short reason from the surrounding sentence}.

### Precision pattern

> "'{overloaded-term}' is doing double duty here — it could mean {meaning-1} or {meaning-2}. For this Epic, I'd treat it as {meaning-1}. Right?"
>
> **Recommended:** {one of the meanings, picked from context}

Resolutions go into GRILL_RESULT.glossary as `{user_term, canonical_term, context, why}`. They are **not** written to a separate CONTEXT.md — CML is the canonical glossary.

---

## Phase 3: Scope Boundaries

### Q3 — Bounded context ownership

Always ask, even when it seems obvious — answers here drive repository assignment in the PRP.

> "I'm placing this in **{context-name}** (which owns {responsibility-1}, {responsibility-2}). Does that match how you think about it, or does part of it belong elsewhere?"
>
> **Recommended:** {context-name from CML lookup}

### Q4 — Cross-context coordination

Only ask if the brainstorm output names ≥2 contexts, OR if the proposed CML changes include events that cross a context map line.

> "This Epic touches {context-A} and {context-B}. The downstream side is {B}. I'd have {A} emit {EventName} and {B} subscribe via an ACL — is that the right direction, or does {B} drive and pull from {A}?"
>
> **Recommended:** the OHS/ACL direction inferred from the existing ContextMap

### Q5 — Sibling overlap (only if Phase 0 found one)

> "There's an open Epic **{KEY} — {summary}** that also touches {repo} / {context}. Skim: {1-line summary of sibling approach}. Does this Epic stack on top of that one, replace it, or run independently?"
>
> **Recommended:** stack-on-top / replace / independent — pick from skim of sibling PRP

If the user says "replace" or "independent" but the sibling has a merged PR or active /work session, escalate via `corpus-conflict` label per /plan Phase 0.5 Step 4 — do **not** proceed.

---

## Phase 4: Solution Shape

### Q6 — Walking skeleton

> "What's the smallest end-to-end version that's worth shipping? I'd suggest: {one-paragraph skeleton — single happy-path query + single result type}. Anything in there that should defer, or anything missing that's load-bearing?"
>
> **Recommended:** specific skeleton derived from the brainstorm output

### Q7 — Invariants

> "What must always be true, even in the deferred-scope cases? E.g. 'no search result is shown without a permission check' or 'recommendations never include disabled apps'. I'm proposing: {invariant inferred from domain model}. Want to add or change one?"
>
> **Recommended:** specific invariant tied to the CML model

Invariants land in GRILL_RESULT.invariants and become MUST acceptance criteria in the PRP.

---

## Phase 5: Edge-Case Stress Test

This is the part that catches "we'll figure it out in implementation" placeholders.

Invent 2 scenarios that probe a boundary between two concepts the user introduced. For each:

> "Concrete scenario: **{specific scenario, e.g. 'A user searches "find me apps that ingest GDELT" — three apps match by description but one is disabled in their org'}**. What should happen?
>
> **Recommended:** {specific behavior, e.g. 'Disabled apps are filtered from results; if a query has zero results post-filter, show "no apps you can access match — show 3 closest alternatives"'}"

Stress-test scenarios are stored in GRILL_RESULT.scenarios and become AC test cases in the PRP.

---

## Phase 6: Code Cross-Reference

When the user has stated "X works like Y today" anywhere in the conversation, verify before believing:

```bash
# Example: user says "search already supports boolean operators"
grep -r "boolean\|AND\|OR" "${PROJECT_ROOT}/{repo}/src" --include="*.ts" --include="*.go" -l | head -5
```

If the code contradicts the user's statement, surface it before continuing:

> "You mentioned {claim}. Looking at {file:line}, it actually does {observed-behavior}. Which is the source of truth — should the plan match the code, or does the code need to change?"
>
> **Recommended:** match the code (default), unless the user flags it as a known bug

Contradictions go into GRILL_RESULT.code_findings.

---

## Phase 7: ADR Candidacy

After all questions, scan the answers. For each decision, evaluate:

| Criterion | Met? |
|---|---|
| Hard to reverse — cost of changing > 1 sprint | Y/N |
| Surprising without context — a future reader will ask "why?" | Y/N |
| Real trade-off — there were genuine alternatives | Y/N |

Only if **all three** are Y, propose an ADR:

> "Decision: '{decision}'. This looks like it qualifies for an ADR because {hard-to-reverse reason}, {surprise reason}, {trade-off reason}. I'll write it to `{repo}/docs/adr/NNNN-{slug}.md` — OK?"
>
> **Recommended:** Yes, file the ADR

ADR location rule:
- **Tactical decision** (within one repo, e.g. "we use SQLite FTS5 over Postgres tsvector for search index") → `{repo}/docs/adr/`. Create the directory if absent.
- **Strategic / cross-repo decision** (e.g. "agentic search routes through MCP server, not the SPA") → `gw-docs/architecture/adr/`.

ADR template (minimal):

```markdown
# ADR-NNNN: {Decision Title}

**Status:** Accepted
**Date:** {YYYY-MM-DD}
**Epic:** {GW-XXXX}

## Context

{1-2 sentences — what was the situation that forced a decision}

## Decision

{1 sentence — the decision itself}

## Rationale

{1 paragraph — why this over the alternatives. Name the alternatives.}

## Consequences

{Bulleted list — what becomes easier, what becomes harder}
```

---

## Output Schema

The grill produces a single `GRILL_RESULT` object that downstream phases consume verbatim. Do not paraphrase it — paste it into the PRP / issue body.

```json
{
  "mode": "plan | groom",
  "epic_or_issue_key": "GW-XXXX",
  "questions_asked": 5,
  "budget_remaining": 1,
  "problem": {
    "statement": "...",
    "falsifiable_signal": "..."
  },
  "persona": {
    "user_supplied": "...",
    "canonical_cml_actor": "...",
    "is_new_actor": false
  },
  "glossary": [
    {"user_term": "...", "canonical_term": "...", "context": "...", "why": "..."}
  ],
  "scope": {
    "owning_context": "...",
    "crosses_contexts": ["..."],
    "orchestration_owner": "...",
    "sibling_overlap": [{"key": "GW-XXXX", "relationship": "stacks-on | replaces | independent"}]
  },
  "skeleton": "...",
  "invariants": ["..."],
  "deferred_scope": ["..."],
  "scenarios": [
    {"setup": "...", "expected_behavior": "..."}
  ],
  "code_findings": [
    {"claim": "...", "file": "...", "line": 0, "actual": "...", "resolution": "match-code | code-needs-change"}
  ],
  "adrs_filed": [
    {"path": "{repo}/docs/adr/NNNN-{slug}.md", "title": "..."}
  ],
  "open_questions": [
    "Anything unresolved when budget hit zero — surfaced for stakeholder follow-up"
  ]
}
```

---

## /groom Mode (Lightweight Per-Issue)

In groom mode, only Phases 2 (terminology) and 5 (one stress-test scenario) run, capped at 2 questions per issue. The decision tree shrinks to:

1. **Boundary question** — "This issue is labeled `repo-{X}` but the AC mentions `{Y}`. Does the work actually live in {X} or should it move?" Recommended answer = grep the AC against repo file paths.
2. **AC precision question** — "AC says '{vague-AC}'. I'd tighten to '{specific-AC}'. OK?" Recommended answer = the tightened version.

Skip both if the issue's AC is already concrete (names files, names commands, has measurable outcomes).

Output is appended to the issue description as a `> **Grill notes:**` block before `create_issue` is called.

---

## Anti-Patterns

| Don't | Do |
|---|---|
| Dump all questions in one message | Ask one, wait, then ask the next |
| Ask without proposing an answer | Always lead with the recommended answer |
| Ask questions code can answer | Read the code first, present the finding |
| File ADRs for every decision | File only when all three criteria are met |
| Maintain a parallel CONTEXT.md | CML domain-index.json is the glossary |
| Burn the whole budget on terminology | Budget caps prevent rabbit-holing |
| Continue when sibling-Epic conflict surfaces | Escalate via corpus-conflict label, stop |

---

## Reference

This skill is adapted from `mattpocock/skills/skills/engineering/grill-with-docs`.
Key adaptations for GW:
- CML domain-index.json replaces CONTEXT.md as the glossary source of truth
- Bounded-context ownership question is mandatory (CML model demands it)
- Sibling-Epic / sibling-PRP overlap detection added (GW has 5+ parallel Epics typically)
- Output schema is structured JSON for /plan and /groom to consume programmatically
- Code cross-reference uses ripgrep over the affected repos, not just the active one
