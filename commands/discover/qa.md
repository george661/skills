<!-- MODEL_TIER: sonnet -->
---
description: >
  Answer questions about the platform in plain language. Draws on the domain model,
  PRPs, roadmap, Jira issues, repository documentation, and architecture records
  to give accurate, grounded answers. Designed for both technical and non-technical
  users. No guessing — always cites sources.
arguments:
  - name: question
    description: Any question about the platform, its capabilities, status, or plans
    required: true
agent-invokeable: true
---

> **Skill references:**
> - [discover/platform-context](.claude/skills/discover/platform-context.skill.md)

**Announce:** "Running /discover:qa — researching your question."

---

## Question Classification

Classify the question into one of these types to determine the search strategy:

| Type | Keywords | Strategy |
|------|----------|----------|
| **Capability** | "can users", "does the platform", "is there a way to", "how does X work" | Load domain model + check PRPs |
| **Status** | "what's the status of", "is X done", "when will X", "is X being built" | Check Jira + roadmap |
| **Architecture** | "how is X built", "what handles X", "which service", "where does X live" | Check domain model + CLAUDE.md + project-docs |
| **History** | "why did we", "when did we add", "what changed", "previous version" | Search archived PRPs + git log |
| **Planning** | "what's next", "what's the priority", "what should we build" | Load roadmap + backlog |
| **Process** | "how do we deploy", "how do we test", "what's the process for" | Check TESTING.md + VALIDATION.md + project-docs |

---

## Search Strategy by Type

### Capability Questions

1. Load `discover/platform-context.skill.md`
2. Search domain model:
   ```bash
   python3 -c "
   import json
   d = json.load(open('${TENANT_DOMAIN_PATH:-${PROJECT_ROOT}/${DOCS_REPO}/domain}/domain-index.json'))
   # Search for relevant entities and events
   keyword = '{keyword from question}'
   for name, entity in d.get('entities', {}).items():
       if keyword.lower() in name.lower() or keyword.lower() in str(entity).lower():
           print(f'Entity: {name}')
   "
   ```
3. Search PRPs for feature descriptions:
   ```bash
   grep -ri "{keyword}" "${PROJECT_ROOT}/${DOCS_REPO}/prps/" --include="*.md" -l 2>/dev/null | head -5
   ```

### Status Questions

```bash
# Search Jira for relevant issues
cd "${PROJECT_ROOT}" && npx tsx .claude/skills/issues/search_issues.ts '{
  "jql": "project = '"${TENANT_PROJECT}"' AND text ~ \"{keyword}\" ORDER BY updated DESC",
  "fields": ["key", "summary", "status", "priority", "updated"]
}'

# Check roadmap
python3 -c "
import json
r = json.load(open('${TENANT_ROADMAP_PATH:-${PROJECT_ROOT}/${DOCS_REPO}/initiatives/roadmap.json}'))
for item in r.get('initiatives', []):
    if '{keyword}'.lower() in item.get('name', '').lower():
        print(f\"{item['name']}: {item['status']} (Jira: {item.get('jira', 'none')})\")
"
```

### Architecture Questions

```bash
# Check project-docs architecture directory
grep -ri "{keyword}" "${PROJECT_ROOT}/${DOCS_REPO}/architecture/" --include="*.md" -l 2>/dev/null

# Check repository CLAUDE.md files
grep -ri "{keyword}" "${PROJECT_ROOT}"/*/CLAUDE.md 2>/dev/null | head -10
```

### History Questions

```bash
# Search archived PRPs
grep -ri "{keyword}" "${PROJECT_ROOT}/${DOCS_REPO}/archive/" --include="*.md" -l 2>/dev/null | head -5

# Check git log for relevant commits (recent 90 days)
git -C "${PROJECT_ROOT}" log --oneline --since="90.days" --all --grep="{keyword}" | head -20
```

---

## Answer Format

Always structure the answer as:

**For capability questions:**
```
Yes / No / Partially — [direct answer in one sentence]

[2-4 sentences of detail in plain language]

Where this lives: [repository or component name]
Related: [link to PRP or Jira issue if relevant]
```

**For status questions:**
```
Current status: [Proposed / Planned / In Progress / Done]

[Detail: what's been done, what's left, Jira key]

Source: [roadmap entry or Jira issue]
```

**For architecture questions:**
```
[Component name] handles this.

[Plain-language explanation — no code unless asked]

More detail: [link to project-docs reference]
```

---

## Honesty Rules

- **Never guess.** If information is not found, say so: "I couldn't find a definitive answer — here's what I know: [partial info]. You may want to check [specific place]."
- **Always cite.** Every factual claim includes a source (PRP filename, Jira key, CLAUDE.md section, etc.)
- **Flag staleness.** If the best source is older than 60 days, say: "This is based on documentation from [date] and may not reflect recent changes."
- **Distinguish built vs. planned.** Never describe planned features as if they are built.

---

## Follow-up

After answering, offer:
- "Would you like more detail on any part of this?"
- "Would you like to capture this as a feature idea? /discover:idea"
- "Want to see the full roadmap? /discover:roadmap"
