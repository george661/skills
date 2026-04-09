<!-- MODEL_TIER: opus -->
---
description: >
  Analyze and evolve the domain model for a given design prompt. Identifies affected
  bounded contexts, proposes CML changes, detects gaps in the domain model, and
  produces a reviewed, confidence-gated domain model phase output.
arguments:
  - name: prompt
    description: What you want to design or change. Can be a feature, flow, or entity.
    required: true
  - name: --session
    description: Existing session ID to continue from (optional)
    required: false
agent-invokeable: true
---

> **Skill references:**
> - [design/interview](.claude/skills/design/interview.skill.md)
> - [design/dual-review](.claude/skills/design/dual-review.skill.md)
> - [design/design-confidence](.claude/skills/design/design-confidence.skill.md)
> - [design/session-state](.claude/skills/design/session-state.skill.md)
> - [design/output-format](.claude/skills/design/output-format.skill.md)
> - [domain-context](.claude/skills/domain-context.skill.md)
> - [cml/analyze](.claude/skills/cml/analyze.skill.md)

**Announce:** "Running /design:domain-model — analyzing domain model impact."

---

## Phase 0: Session Setup

**Check for existing session:**
```bash
# If --session provided, load it
STATE_FILE="${DESIGN_DOCS_PATH}/sessions/$ARGUMENTS.session/state.json"

# If not provided, look for most recent in-progress domain-model phase
ls -t "${DESIGN_DOCS_PATH}/sessions/" 2>/dev/null | head -5
```

If no session: run interview. If session exists: confirm resume with user.

---

## Phase 1: Interview

**Load skill:** `design/interview.skill.md`

Run the 7-question interview for the prompt: `$ARGUMENTS.prompt`

**Domain-model specific additional questions:**
- Q8 (domain only): "Are you introducing a new concept not yet in the domain model, extending an existing one, or correcting a misplacement?"
- Q9 (domain only): "Does this change affect how money, sessions, or tokens flow? If yes, flag for extra architect scrutiny."

After interview: initialize session state with interview output.

---

## Phase 2: Load Domain Model

```bash
# Load domain model if available; degrade gracefully if not configured
python3 -c "
import json, os, sys
path = os.environ.get('DESIGN_CML_PATH', os.environ.get('TENANT_DOMAIN_PATH', ''))
if not path:
    print('WARNING: Neither DESIGN_CML_PATH nor TENANT_DOMAIN_PATH is set', file=sys.stderr)
    print('Domain model features unavailable')
    exit(0)
idx_file = os.path.join(path, os.environ.get('TENANT_DOMAIN_INDEX', 'domain-index.json'))
if not os.path.exists(idx_file):
    print(f'WARNING: domain-index.json not found at {idx_file}', file=sys.stderr)
    print('Domain model features unavailable')
    exit(0)
idx = json.load(open(idx_file))
print('Contexts:', list(idx['contexts'].keys()))
for name, ctx in idx['contexts'].items():
    print(f'  {name}: {len(ctx.get(\"aggregates\",[]))} aggregates, {len(ctx.get(\"commands\",[]))} commands, {len(ctx.get(\"events\",[]))} events')
"
```

Also read the CML source file (for reference only — never modify directly):
```bash
cat "${DESIGN_CML_PATH}/general-wisdom.cml" 2>/dev/null || \
  cat "${DESIGN_CML_PATH}/"*.cml 2>/dev/null | head -200
```

---

## Phase 3: Domain Analysis (opus)

Using the interview outputs and domain model, perform:

### 3.1 — Identify Affected Bounded Contexts

Map every element of the prompt to a bounded context. Use `domain-index.json` as the source of truth.

Table: `{entity/concept} → {bounded context} → {justification}`

Flag any concept that doesn't map cleanly to an existing context — this is a domain model gap.

### 3.2 — Identify Domain Model Gaps

A gap is: a concept in the prompt that has no matching aggregate, entity, command, or event in any bounded context.

For each gap:
- Is this a new concept that belongs in an existing context? → Propose addition
- Is this a new concept that represents a new bounded context? → Flag for careful consideration (this is a large decision)
- Is this a concept that exists but is misnamed? → Propose rename with migration path

**Principle:** Do not expand terminology unnecessarily. Before proposing a new term, verify it doesn't already exist under a different name.

### 3.3 — Propose CML Changes

For each proposed change, produce a structured entry:

```
| Entity/Concept | Change Type | Bounded Context | Rationale |
|---|---|---|---|
| PurchaseIntent | Add aggregate | MarketplaceContext | Represents the intermediate state... |
| TokenReservation | Add entity | TokenLedgerContext | ... |
```

Then produce the actual CML diff:

```diff
// In MarketplaceContext:
+ Aggregate PurchaseIntent {
+   String intentId
+   String userId
+   String applicationId
+   Money reservedAmount
+   - placed a PurchaseIntentPlaced
+   - cancelled a PurchaseIntentCancelled
+ }
```

**IMPORTANT: This diff is proposed only. Do not write to CML files without explicit user confirmation.**

### 3.4 — Check Glossary Additions

Any new term introduced must be added to the ubiquitous language glossary (if one exists).

Check: `${DESIGN_CML_PATH}/README.md` or `REFERENCE.md` for existing glossary.

Propose additions for any new terms in the format:
```
**PurchaseIntent** — Represents the transient state between a user selecting an application
and completing the token payment. Owned by MarketplaceContext.
```

---

## Phase 4: Dual Review

**Load skill:** `design/dual-review.skill.md`

Run both reviewers against the Phase 3 outputs.

**Domain-model specific adversarial checks to add:**
- Does every new term justify its existence? (Occam's Razor)
- Is there a simpler way to model this with existing aggregates?
- Does this create a new bounded context when an existing one would suffice?

**Domain-model specific architect checks to add:**
- Do proposed aggregates respect the invariants of their bounded context?
- Do proposed events follow past tense naming convention?
- Are ContextMap relationships explicitly declared for cross-context communication?

Integrate all BLOCKER/MAJOR feedback into the outputs before proceeding.

---

## Phase 5: Confidence Check

**Load skill:** `design/design-confidence.skill.md`

Run the 5-check confidence assessment for the `domain-model` phase.

If confidence < 90%: resolve gaps and retry. Maximum 3 loops.
If confidence ≥ 90%: proceed to write outputs.

---

## Phase 6: Write Outputs

### Write human-readable document

**File:** `${DESIGN_DOCS_PATH}/sessions/{session_id}/domain-model.md`

Include per `output-format.skill.md` conventions.

### Update session state

**File:** `${DESIGN_DOCS_PATH}/sessions/{session_id}/state.json`

Update `phases.domain-model` with:
- status: "complete"
- confidence score
- bounded_contexts affected
- proposed_cml_changes (structured list)
- review results
- inputs/outputs file lists

### Commit

```bash
cd "${PROJECT_ROOT}"
git add "${DESIGN_DOCS_PATH}/sessions/{session_id}/"
git commit -m "design({session_id}): complete domain-model phase"
```

---

## Phase 7: Show Results

Display to user:
1. Affected bounded contexts summary
2. Proposed CML changes table
3. CML diff (for human review)
4. Any new glossary terms
5. Confidence score
6. Review notes summary

Ask: "Review the proposed CML changes above. Approve to apply them, or provide feedback to revise."

If user approves: write the CML changes to `${DESIGN_CML_PATH}/` files.
If user requests changes: loop back to Phase 3.

---

## Output

- `${DESIGN_DOCS_PATH}/sessions/{session_id}/domain-model.md` — human-readable
- `${DESIGN_DOCS_PATH}/sessions/{session_id}/domain-model.diff` — CML diff
- `${DESIGN_DOCS_PATH}/sessions/{session_id}/state.json` — updated with domain-model phase
- (if approved) Modified CML files in `${DESIGN_CML_PATH}/`
