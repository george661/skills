<!-- MODEL_TIER: opus -->
---
description: >
  Orchestrate a full five-phase design session: domain model → diagrams → wireframes →
  mockups → contracts. Each phase uses interview, dual review, and confidence-gating.
  Can also invoke individual phases standalone. Uses interview techniques to fully
  explore the design space before generating outputs.
arguments:
  - name: prompt
    description: >
      What you want to design. Can be a feature, flow change, new entity, or UI pattern.
      The more specific the better, but the interview phase will clarify scope.
    required: true
  - name: --phase
    description: Run only a specific phase (domain-model|diagram|wireframe|mockup|contract)
    required: false
  - name: --session
    description: Resume an existing design session by ID
    required: false
  - name: --from
    description: Start from a specific phase, using prior session outputs (e.g. --from wireframe)
    required: false
agent-invokeable: true
---

> **Skill references:**
> - [design/SKILL](.claude/skills/design/SKILL.md)
> - [design/interview](.claude/skills/design/interview.skill.md)
> - [design/session-state](.claude/skills/design/session-state.skill.md)
> - [design/output-format](.claude/skills/design/output-format.skill.md)

**Announce:** "Starting /design session — exploring the design space for: $ARGUMENTS.prompt"

---

## Input Routing

**Check flags to determine execution mode:**

```
--phase only:     Run that single phase. Load/create session. Skip other phases.
--from only:      Start from that phase, use existing session data for prior phases.
--session only:   Resume session. Ask which phase to continue from.
--phase + --session: Run that phase within the existing session.
No flags:         Full orchestration — all 5 phases in sequence.
```

---

## Full Orchestration Mode (no flags)

### Pre-flight

1. Check environment variables are set:
   ```bash
   echo "DESIGN_DOCS_PATH: ${DESIGN_DOCS_PATH:-NOT SET}"
   echo "DESIGN_SPA_PATH: ${DESIGN_SPA_PATH:-NOT SET}"
   echo "DESIGN_CML_PATH: ${DESIGN_CML_PATH:-${TENANT_DOMAIN_PATH:-NOT SET}}"
   ```
   If any required variable is unset, show error and stop.

2. Check for existing sessions with similar prompts:
   ```bash
   grep -r "prompt" "${DESIGN_DOCS_PATH}/sessions/*/state.json" 2>/dev/null | head -5
   ```
   If similar session found, ask user: "Found existing session {id} for a similar prompt. Resume it? [Y/n/show]"

3. Initialize new session:
   ```bash
   SESSION_DATE=$(date +%Y%m%d)
   # Slug from first 5 words of prompt, lowercase, dasherized
   SESSION_ID="${SESSION_DATE}-{derived-slug}"
   mkdir -p "${DESIGN_DOCS_PATH}/sessions/${SESSION_ID}"/{diagrams,wireframes,mockups,contracts}
   ```

---

### Phase 0: Master Interview

Run the full design interview (`design/interview.skill.md`) for `$ARGUMENTS.prompt`.

The interview at the orchestrator level asks all 7 standard questions PLUS:
- "Which of the 5 design phases are relevant to this request? Skip any that don't apply."
- "Is this a brand-new feature or an evolution of something existing?"

Determine the **active phases** — some prompts don't need all 5 phases:
- Pure domain model fix → only domain-model phase
- Diagram update for existing feature → only diagram phase
- New UI screen (backend exists) → wireframe + mockup + contract phases
- Full new feature → all 5 phases

Document the active phases in session state. Present them to the user for confirmation.

---

### Phase Loop

For each active phase in order:

```
domain-model → diagram → wireframe → mockup → contract
```

```typescript
for (const phase of activePhases) {
  console.log(`\n── Starting Phase: ${phase} ──\n`);

  // Invoke the phase command
  await runPhase(phase, sessionId, prompt);

  // Read confidence from session state
  const state = readSessionState(sessionId);
  const phaseResult = state.phases[phase];

  if (phaseResult.confidence < 0.90) {
    // Phase returned below threshold (after 3 loops)
    console.log(`⚠️  Phase ${phase} confidence ${phaseResult.confidence} — needs resolution`);
    // Ask user: continue anyway or address issues?
    const decision = await askUser('Continue to next phase despite low confidence? [y/N]');
    if (!decision) {
      console.log('Pausing design session. Resume with: /design --session ${sessionId} --from ${phase}');
      return;
    }
  }

  console.log(`✅ Phase ${phase} complete — confidence: ${phaseResult.confidence}`);
}
```

---

### Completion

After all active phases complete:

1. Write design session summary:

**File:** `${DESIGN_DOCS_PATH}/sessions/${SESSION_ID}/design-complete.md`

```markdown
# Design Session Complete

**Session:** {session_id}
**Prompt:** {original prompt}
**Date:** {date}
**Phases completed:** {list}
**Overall confidence:** {average across phases}

## Summary of Outputs

### Domain Model
{summary from domain-model phase — bounded contexts affected, changes proposed}

### Diagrams
{list of diagrams created, flow names}

### Wireframes
{list of screens wireframed, new catalog components}

### Mockups
{list of React components generated, DRY findings}

### Contracts
{alignment status, misalignment remediation plan}

## Artifacts

| Artifact | Path |
|---|---|
| Session state | {DESIGN_DOCS_PATH}/sessions/{session_id}/state.json |
| Domain model diff | {DESIGN_DOCS_PATH}/sessions/{session_id}/domain-model.diff |
| Diagrams | {DESIGN_DIAGRAMS_PATH}/diagrams-index.json |
| Wireframes | {DESIGN_WIREFRAMES_PATH}/ |
| Components | sessions/{session_id}/mockups/ |
| Type alignment | {DESIGN_DOCS_PATH}/type-alignment.json |

## Suggested Next Steps (Jira Issues)

{List of suggested /issue or /work commands for implementation}

## Open Questions

{Any unresolved questions from the design session}

## Deferred Decisions

{Items explicitly deferred, with rationale}
```

2. Write session-complete JSON for agent consumption.

3. Commit everything:
```bash
cd "${PROJECT_ROOT}"
git add "${DESIGN_DOCS_PATH}/sessions/${SESSION_ID}/"
git commit -m "design(${SESSION_ID}): complete all phases — {summary}"
```

4. Display final summary to user.

---

## Output (Full Session)

```
🎨 Design Session Complete: {session_id}

📋 Phases Completed:
   ✅ domain-model — {N} bounded contexts, {M} CML changes proposed
   ✅ diagram      — {N} sequence diagrams, diagrams-index.json updated
   ✅ wireframe    — {N} screens × {M} states, {P} catalog components updated
   ✅ mockup       — {N} React components, {M} DRY refactor opportunities
   ✅ contract     — {N} types analyzed, {M} misalignments found

📁 Artifacts in: {DESIGN_DOCS_PATH}/sessions/{session_id}/

🔮 Suggested next steps:
   /issue "Implement {component} from design session {session_id}"
   /issue "Fix type alignment: ApplicationSession (2 misalignments)"
```

---

## Phase Confidence Summary

At the end, display a confidence table:

```
Phase          Confidence  Adversarial  Architect
────────────── ──────────  ───────────  ─────────
domain-model   97%         94%          98%
diagram        95%         93%          96%
wireframe      92%         90%          94%
mockup         96%         95%          97%
contract       93%         91%          95%

Overall        95%         ✅ All phases complete
```

---

## Error Handling

| Error | Recovery |
|-------|---------|
| DESIGN_DOCS_PATH not set | Stop, show setup instructions from `design/SKILL.md` |
| CML not found | Skip domain-model phase, warn user |
| frontend-app not found | Skip wireframe/mockup phases, warn user |
| Phase confidence < 70% after 3 loops | Pause session, ask user for guidance |
| User cancels mid-session | Save state, show resume command |
