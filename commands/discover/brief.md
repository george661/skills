<!-- MODEL_TIER: sonnet -->
---
description: >
  Generate a structured Feature Brief from a completed idea session or free-text
  description. The brief is human-readable, stakeholder-approved, and structured
  to feed directly into /plan for engineering planning.
arguments:
  - name: input
    description: Session ID from /discover:idea, OR a brief free-text description to build a brief directly
    required: true
  - name: --session
    description: Explicit session ID if not passed as positional argument
    required: false
agent-invokeable: true
---

> **Skill references:**
> - [discover/brief-writer](.claude/skills/discover/brief-writer.skill.md)
> - [discover/platform-context](.claude/skills/discover/platform-context.skill.md)

**Announce:** "Running /discover:brief — generating feature brief."

---

## Step 1: Load Input

**If `$ARGUMENTS.input` looks like a session ID** (matches `YYYYMMDD-*` pattern):
- Load `${PROJECT_ROOT}/${DOCS_REPO}/features/sessions/{session-id}/interview.json`
- Load `${PROJECT_ROOT}/${DOCS_REPO}/features/sessions/{session-id}/state.json`
- If interview phase is not complete, stop: "Run /discover:idea --session {id} to complete the interview first."

**If `$ARGUMENTS.input` is free text:**
- Run a shortened interview (Q1 Problem, Q4 What Good Looks Like, Q7 Success Criteria)
- Use the free text as the seed for Q1
- Accept shorter answers — this is quick-capture mode

**If `--session` provided:** Use that session ID regardless of positional arg.

---

## Step 2: Check for Existing Brief

```bash
BRIEF_DIR="${PROJECT_ROOT}/${DOCS_REPO}/features"
EXISTING=$(ls "${BRIEF_DIR}"/*.md 2>/dev/null | xargs grep -l "{key phrase from idea}" 2>/dev/null | head -3)

if [ -n "$EXISTING" ]; then
  echo "Found possibly related briefs: $EXISTING"
fi
```

If a closely related brief exists, ask: "I found a related brief: [filename]. Should I
update that one, or create a new brief for a distinct feature?"

---

## Step 3: Generate Brief

Run `discover/brief-writer.skill.md` with the interview output.

Determine file path:
```bash
TODAY=$(date +%Y-%m-%d)
# Derive slug from feature title (4-5 words, dasherized, lowercase)
SLUG="{derived-from-title}"
BRIEF_PATH="${PROJECT_ROOT}/${DOCS_REPO}/features/${TODAY}-${SLUG}-brief.md"
```

Write the brief to that path.

---

## Step 4: Stakeholder Review

Display the full brief to the user.

Ask: "Does this capture the idea correctly? I can adjust any section."

Handle revisions:
- "Change the problem statement" → rewrite that section
- "Add another persona" → add to Who Benefits table
- "The success criteria isn't right" → revise that section
- "Looks good" → proceed

After approval:
- Update `status: draft` → `status: evergreen` in the brief frontmatter
- Save file

---

## Step 5: Update Session State

If a session exists, update `${SESSION_DIR}/state.json`:
```json
{
  "phases": {
    "brief": {
      "status": "complete",
      "output": "{brief-filename}",
      "approved": true,
      "approved_at": "{ISO datetime}"
    }
  }
}
```

---

## Step 6: Commit and Offer Next Steps

```bash
cd "${PROJECT_ROOT}"
git add "${PROJECT_ROOT}/${DOCS_REPO}/features/{brief-filename}.md"
git commit -m "discover: add feature brief — {feature title}"
```

Show next steps:
```
Brief saved: ${PROJECT_ROOT}/${DOCS_REPO}/features/{brief-filename}.md

Next steps:
1. Update roadmap: /discover:roadmap --add "{feature title}"
2. Create Jira Epic: /discover:epic {brief-filename}
3. Start engineering planning: /plan {PROJ-XXXX} (after epic exists)
```
