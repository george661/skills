<!-- MODEL_TIER: opus -->
---
description: >
  Orchestrate a full product discovery session: load platform context, capture
  and refine an idea, produce a feature brief, update the roadmap, and optionally
  create a Jira Epic that feeds into /plan. Designed for product stakeholders and
  non-technical users. Uses interview techniques and platform knowledge to ground
  every conversation in what already exists.
arguments:
  - name: prompt
    description: >
      What you want to explore. Can be a vague idea ("better search"), a problem
      ("publishers can't see their revenue"), or a question ("what can users do
      with tokens?"). The interview phase will clarify scope.
    required: false
  - name: --phase
    description: Run only a specific phase (context|idea|brief|roadmap|epic)
    required: false
  - name: --session
    description: Resume an existing discovery session by ID
    required: false
agent-invokeable: true
---

> **Skill references:**
> - [discover/platform-context](.claude/skills/discover/platform-context.skill.md)
> - [discover/idea-interview](.claude/skills/discover/idea-interview.skill.md)
> - [discover/brief-writer](.claude/skills/discover/brief-writer.skill.md)
> - [discover/roadmap-editor](.claude/skills/discover/roadmap-editor.skill.md)
> - [discover/epic-synthesizer](.claude/skills/discover/epic-synthesizer.skill.md)

**Announce:** "Starting /discover session — let's explore: $ARGUMENTS.prompt"

---

## Input Routing

```
--phase only:     Run that single phase.
--session only:   Resume session, ask which phase to continue.
--phase+--session: Run that phase within existing session.
No arguments:     Guided mode — ask what the user wants to explore.
```

---

## Guided Mode (no arguments)

If no prompt is provided, greet the user:

```
Welcome to /discover. I'll help you capture and refine a product idea, answer
questions about the platform, or update the roadmap.

What would you like to do today?
  1. Explore a new idea or feature
  2. Ask a question about the platform
  3. Review or update the roadmap
  4. Turn an existing idea into a Jira Epic

Just describe what's on your mind and I'll guide you from there.
```

Route based on response to the appropriate sub-command phase.

---

## Full Orchestration Mode

### Phase 0: Load Platform Context

Run `discover/platform-context.skill.md`.

Display a brief orientation (2-4 sentences) summarizing what the platform can do today,
what's actively being built, and what's on the roadmap. Keep it plain language.

---

### Phase 1: Idea Capture

Run `discover/idea-interview.skill.md` with `$ARGUMENTS.prompt` as the seed topic.

Interview the user through the 8 questions. When all questions are answered:
- Summarize back to the user
- Ask for confirmation

Initialize session state:
```bash
SESSION_DATE=$(date +%Y%m%d)
# Slug from first 4 words of prompt, lowercase, dasherized
SESSION_ID="${SESSION_DATE}-{derived-slug}"
SESSION_DIR="${PROJECT_ROOT}/${DOCS_REPO}/features/sessions/${SESSION_ID}"
mkdir -p "$SESSION_DIR"
```

Save interview output to `${SESSION_DIR}/interview.json`.

---

### Phase 2: Duplicate & Conflict Check

Before writing a brief, check if this idea overlaps with existing work:

```bash
# Search open epics for related terms
cd "${PROJECT_ROOT}" && npx tsx .claude/skills/issues/search_issues.ts '{
  "jql": "project = '"${TENANT_PROJECT}"' AND issuetype = Epic AND status != Done AND text ~ \"{keyword}\"",
  "fields": ["key", "summary", "status"]
}'

# Search existing PRPs
grep -ri "{keyword}" "${PROJECT_ROOT}/${DOCS_REPO}/prps/" 2>/dev/null | head -10

# Search roadmap
grep -i "{keyword}" "${TENANT_ROADMAP_PATH:-${PROJECT_ROOT}/${DOCS_REPO}/initiatives/roadmap.json}" 2>/dev/null
```

If overlaps are found, present them to the user:
"I found some related work: [list]. Is your idea different from these, or is it
building on / replacing one of them?"

---

### Phase 3: Feature Brief

Run `discover/brief-writer.skill.md` with interview output.

Write brief to `${PROJECT_ROOT}/${DOCS_REPO}/features/YYYY-MM-DD-{slug}-brief.md`.

Present the brief to the stakeholder. Ask:
"Does this capture your idea correctly? Any changes before we continue?"

Wait for approval. Set `status: evergreen` on approval.

---

### Phase 4: Roadmap Update

Run `discover/roadmap-editor.skill.md` to add the initiative as `status: Proposed`.

Show the user where the idea now sits in the roadmap:
"Your idea has been added to the roadmap as [initiative name] with status: Proposed."

Ask: "Would you like to create a Jira Epic now so engineers can start planning?"

---

### Phase 5 (Optional): Epic Creation

If user confirms, run `discover/epic-synthesizer.skill.md`.

After epic creation, show:
```
Discovery complete.

Brief:   ${PROJECT_ROOT}/${DOCS_REPO}/features/{brief-filename}.md
Epic:    {PROJ-XXXX} — {Feature Title}
Roadmap: {initiative name} → Planned

Next step for engineers: /plan {PROJ-XXXX}
```

If user declines epic creation:
```
Discovery complete.

Brief:   ${PROJECT_ROOT}/${DOCS_REPO}/features/{brief-filename}.md
Roadmap: {initiative name} → Proposed

When ready to start engineering: /discover:epic {brief-filename}
```

---

## Session State

Save session state to `${PROJECT_ROOT}/${DOCS_REPO}/features/sessions/{SESSION_ID}/state.json`:

```json
{
  "session_id": "{SESSION_ID}",
  "prompt": "{original prompt}",
  "created": "{ISO date}",
  "phases": {
    "context": { "status": "complete" },
    "idea": { "status": "complete", "output": "interview.json" },
    "brief": { "status": "complete", "output": "{brief-filename}" },
    "roadmap": { "status": "complete", "initiative_id": "{INI-XXX}" },
    "epic": { "status": "complete|skipped", "jira_key": "{PROJ-XXXX|null}" }
  }
}
```

Commit all outputs:
```bash
cd "${PROJECT_ROOT}"
git add "${PROJECT_ROOT}/${DOCS_REPO}/features/"
git add "${TENANT_ROADMAP_PATH:-${PROJECT_ROOT}/${DOCS_REPO}/initiatives/roadmap.json}"
git commit -m "discover(${SESSION_ID}): {brief title}"
```
