<!-- MODEL_TIER: opus -->
---
description: >
  Capture and explore a product idea through a stakeholder-friendly interview.
  Loads current platform context, runs the 8-question idea interview, checks for
  duplicate or related work, and saves the session state for downstream commands.
  Non-technical — no engineering jargon. Designed for product owners and stakeholders.
arguments:
  - name: prompt
    description: Seed description of the idea. Can be vague — the interview will clarify.
    required: false
  - name: --session
    description: Resume an existing idea session
    required: false
agent-invokeable: true
---

> **Skill references:**
> - [discover/platform-context](.claude/skills/discover/platform-context.skill.md)
> - [discover/idea-interview](.claude/skills/discover/idea-interview.skill.md)

**Announce:** "Running /discover:idea — let's explore your idea."

---

## Step 1: Load Platform Context

Run `discover/platform-context.skill.md`.

Display a brief (3-4 sentence) summary of what the platform does today and what's
actively in development. This helps the stakeholder calibrate their idea against
what already exists.

---

## Step 2: Resume or Start Session

**If `--session` provided:**
- Load `${PROJECT_ROOT}/${DOCS_REPO}/features/sessions/{session}/state.json`
- If interview phase is complete, ask: "Your idea was: '{prompt}'. Want to continue to the brief, or revisit the interview?"
- Resume from the appropriate point

**If no session:**
- Initialize session:
  ```bash
  SESSION_DATE=$(date +%Y%m%d)
  SESSION_SLUG=$(echo "$ARGUMENTS_PROMPT" | tr '[:upper:]' '[:lower:]' | tr ' ' '-' | cut -c1-40)
  SESSION_ID="${SESSION_DATE}-${SESSION_SLUG:-idea}"
  SESSION_DIR="${PROJECT_ROOT}/${DOCS_REPO}/features/sessions/${SESSION_ID}"
  mkdir -p "$SESSION_DIR"
  ```
- Save initial state with `status: started`

---

## Step 3: Run Idea Interview

Run `discover/idea-interview.skill.md` with `$ARGUMENTS.prompt` as the seed.

The interview asks one question at a time, waits for the answer, and follows up
naturally. Do not rush through all 8 questions — some answers will make later
questions unnecessary or reveal new ones.

When all 8 questions are answered (or the session reaches natural completion):
1. Write interview output to `${SESSION_DIR}/interview.json`
2. Summarize back to the user in plain language
3. Ask: "Does that capture it? Anything to add or change?"

---

## Step 4: Duplicate Check

Search for overlapping work before proceeding:

```bash
# Extract 2-3 key terms from the idea
KEYWORD1="{term1}"
KEYWORD2="{term2}"

# Check open epics
cd "${PROJECT_ROOT}" && npx tsx .claude/skills/issues/search_issues.ts "{
  \"jql\": \"project = ${TENANT_PROJECT} AND issuetype = Epic AND status != Done AND (summary ~ \\\"${KEYWORD1}\\\" OR summary ~ \\\"${KEYWORD2}\\\")\",
  \"fields\": [\"key\", \"summary\", \"status\"]
}"

# Check PRPs
grep -ri "${KEYWORD1}" "${PROJECT_ROOT}/${DOCS_REPO}/prps/" 2>/dev/null | grep "^.*\.md:" | head -5
```

**If duplicates found:**
Present them plainly: "I found some related work already in progress: [list].
Is your idea different from these, or related?"

Let the stakeholder clarify. Document their response in the interview JSON under
`existing_similarity`.

**If no duplicates:** Continue.

---

## Step 5: Save and Offer Next Steps

Update `${SESSION_DIR}/state.json` with phase `idea: complete`.

Offer next steps:
```
Idea captured. Here's what you can do next:

1. Write a feature brief: /discover:brief --session {SESSION_ID}
2. Ask questions about the platform: /discover:qa "how does X work?"
3. Start over with a different angle: /discover:idea "different description"
```
