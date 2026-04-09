---
name: discover-platform-context
description: >
  Loads authoritative platform knowledge to ground a discovery session. Reads the
  domain model, active roadmap, recent PRPs, and open Jira epics to give a complete
  picture of the platform's current state, capabilities, and in-flight work.
---

# Platform Context Skill

## Purpose

Before any discovery conversation, load the platform's current state so answers
are grounded in what actually exists — not assumptions. This prevents proposing
features that are already built, already planned, or impossible given current architecture.

---

## Load Sequence

Run each step in order. Collect results into a working context object.

### Step 1 — Domain Model Summary

```bash
DOMAIN_INDEX="${TENANT_DOMAIN_PATH:-${PROJECT_ROOT}/${DOCS_REPO}/domain}/domain-index.json"

if [ -f "$DOMAIN_INDEX" ]; then
  python3 -c "
import json
d = json.load(open('$DOMAIN_INDEX'))
contexts = list(d.get('contexts', {}).keys())
entities  = list(d.get('entities', {}).keys())
events    = list(d.get('events', {}).keys())
print('Bounded contexts:', ', '.join(contexts))
print('Key entities:', ', '.join(entities[:20]), '...' if len(entities) > 20 else '')
print('Key events:', ', '.join(events[:15]), '...' if len(events) > 15 else '')
"
else
  echo "Domain index not found at $DOMAIN_INDEX"
fi
```

Summarize: what capabilities exist (sessions, tokens, marketplace, organizations, etc.)

---

### Step 2 — Active Roadmap

```bash
ROADMAP="${TENANT_ROADMAP_PATH:-${PROJECT_ROOT}/${DOCS_REPO}/initiatives/roadmap.json}"

if [ -f "$ROADMAP" ]; then
  python3 -c "
import json
r = json.load(open('$ROADMAP'))
initiatives = r.get('initiatives', r if isinstance(r, list) else [])
for item in initiatives:
  status = item.get('status', '?')
  name   = item.get('name', item.get('title', '?'))
  jira   = item.get('jira', '')
  print(f'  [{status}] {name}' + (f' ({jira})' if jira else ''))
"
else
  echo "Roadmap not found. Checked: $ROADMAP"
fi
```

Identify: what is Planned, In Progress, or Done. Surface themes.

---

### Step 3 — Active PRPs

```bash
PRP_DIR="${PROJECT_ROOT}/${DOCS_REPO}/prps"

if [ -d "$PRP_DIR" ]; then
  # List all active (non-archived) PRPs with their domain
  find "$PRP_DIR" -name "*.md" | head -40 | while read f; do
    domain=$(dirname "$f" | xargs basename)
    title=$(head -10 "$f" | grep "^title:" | sed 's/title: *//' | tr -d '"')
    status=$(head -10 "$f" | grep "^status:" | sed 's/status: *//')
    [ -n "$title" ] && echo "  [$domain/$status] $title"
  done
else
  echo "PRP directory not found at $PRP_DIR"
fi
```

---

### Step 4 — Open Epics in Jira

```bash
cd "${PROJECT_ROOT}" && npx tsx .claude/skills/jira/search_issues.ts '{
  "jql": "project = '"${TENANT_PROJECT}"' AND issuetype = Epic AND status != Done",
  "fields": ["key", "summary", "status", "priority"]
}'
```

---

### Step 5 — Repository Inventory

Load the repository table from CLAUDE.md or memory:

Key repositories the stakeholder may ask about:
- **frontend-app** — Marketplace UI (what users see)
- **api-service / lambda-functions** — Core business logic (sessions, tokens, marketplace)
- **auth-service** — Login and identity
- **e2e-tests** — Automated testing
- **dashboard** — Operator dashboard

---

## Output Format

Produce a structured context block for use in the discovery session:

```
## Platform Context

**What users can do today:**
[1-paragraph plain-language summary of current capabilities]

**Active work (in progress):**
[Bullet list of epics currently being built]

**Planned work (roadmap):**
[Bullet list of planned initiatives]

**Key domains:**
[Brief list of bounded contexts and what they own]

**Gaps / known limitations:**
[Any known gaps relevant to the discovery topic, if applicable]
```

---

## Usage Notes

- Run this skill at the start of every `/discover` session
- Re-run if the conversation shifts to a significantly different domain
- For `/discover:qa` sessions, re-run whenever the question involves capabilities not yet in context
- Always phrase the output in plain language — no DDD/technical jargon for stakeholder sessions
