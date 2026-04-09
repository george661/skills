<!-- MODEL_TIER: sonnet -->
---
description: >
  Convert an approved Feature Brief into a Jira Epic, PRP seed, and roadmap update.
  Bridges discovery (stakeholder language) to engineering planning (/plan).
  Requires a stakeholder-approved brief (status: evergreen).
arguments:
  - name: input
    description: >
      Brief filename (e.g. "2026-03-20-marketplace-search-brief.md"), session ID,
      or feature title. Will search for the brief if a full path is not provided.
    required: true
agent-invokeable: true
---

> **Skill references:**
> - [discover/epic-synthesizer](.claude/skills/discover/epic-synthesizer.skill.md)
> - [discover/roadmap-editor](.claude/skills/discover/roadmap-editor.skill.md)

**Announce:** "Running /discover:epic — creating Jira Epic from feature brief."

---

## Step 1: Locate the Brief

**If `$ARGUMENTS.input` is a filename:**
- Look for `${PROJECT_ROOT}/${DOCS_REPO}/features/{filename}`
- Also try `${PROJECT_ROOT}/${DOCS_REPO}/features/{filename}.md`

**If it looks like a session ID:**
- Load `${PROJECT_ROOT}/${DOCS_REPO}/features/sessions/{id}/state.json`
- Get the brief path from `phases.brief.output`

**If it's a title/description:**
- Search: `grep -ri "{input}" "${PROJECT_ROOT}/${DOCS_REPO}/features/" --include="*.md" -l`
- Present matches and ask which one

---

## Step 2: Verify Brief is Approved

Read the brief frontmatter. Check `status: evergreen`.

If `status: draft`:
```
This brief hasn't been stakeholder-approved yet. Please review and approve it first:

  Brief: ${PROJECT_ROOT}/${DOCS_REPO}/features/{filename}

Once you've confirmed it's correct, update the status to "evergreen" and re-run
/discover:epic.

Or run /discover:brief --session {session-id} to review it now.
```

Stop. Do not create an epic from an unapproved brief.

---

## Step 3: Check for Existing Epic

```bash
# Check if epic already exists for this brief
TITLE="{title from brief}"
cd "${PROJECT_ROOT}" && npx tsx .claude/skills/issues/search_issues.ts '{
  "jql": "project = '"${TENANT_PROJECT}"' AND issuetype = Epic AND summary ~ \"'"${TITLE}"'\"",
  "fields": ["key", "summary", "status"]
}'
```

If a matching epic exists:
"An epic already exists for this feature: {PROJ-XXXX} — {title}. Would you like to
link this brief to it instead of creating a new one? [Y/n]"

---

## Step 4: Run Epic Synthesizer

Run `discover/epic-synthesizer.skill.md` with the brief contents.

The synthesizer will:
1. Create the Jira Epic
2. Write the PRP seed file
3. Update the roadmap
4. Link PRP to the Jira epic

---

## Step 5: Commit Artifacts

```bash
cd "${PROJECT_ROOT}"

# Stage all new files
git add "${PROJECT_ROOT}/${DOCS_REPO}/prps/{domain}/{PRP-filename}"
git add "${TENANT_ROADMAP_PATH:-${PROJECT_ROOT}/${DOCS_REPO}/initiatives/roadmap.json}"

git commit -m "discover: create epic {PROJ-XXXX} — {feature title}"
```

---

## Step 6: Final Summary

Show a clean handoff summary:

```
Discovery → Engineering handoff complete.

Feature:  {title}
Brief:    ${PROJECT_ROOT}/${DOCS_REPO}/features/{brief-filename}
Epic:     {PROJ-XXXX} in Jira (status: Grooming)
PRP seed: ${PROJECT_ROOT}/${DOCS_REPO}/prps/{domain}/{PRP-filename}
Roadmap:  {INI-XXX} — {name} → Planned

For engineers:
  /plan {PROJ-XXXX}          Build the full PRP
  /design {feature title}  Design phase (after PRP is done)
  /groom {PROJ-XXXX}         Create implementation issues
```

---

## Error Handling

| Error | Response |
|-------|----------|
| Brief not found | "I couldn't find a brief matching '{input}'. Run /discover:brief to create one, or /discover:roadmap to see what exists." |
| Brief not approved | Show approval instructions (Step 2 above) |
| Jira create fails | Show error, offer to retry or create manually |
| Roadmap not found | Show path, offer to create roadmap.json |
| PRP directory missing | Create the directory and continue |
