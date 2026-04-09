<!-- MODEL_TIER: haiku -->
<!-- DISPATCH: Spawn a Task subagent with model: "haiku" to execute this command. -->

---
description: Show all blocking and in-flight Jira issues for release readiness assessment
---

# Jira Blockers Dashboard

## Step 1: Fetch Blocking Issues

```bash
npx tsx .claude/skills/jira/jira_blockers.ts '{}'
```

## Step 2: Present Results

Parse the JSON and display grouped sections.

### Priority Icons

| priority | Icon |
|----------|------|
| Highest / Blocker | 🔴 |
| Critical | 🟠 |
| High | 🟡 |
| Medium / Low | ⚪ |

### Output Format

```
Jira Blockers
══════════════════════════════════════════

🔴 CRITICAL IN PROGRESS ({count})            ← Gate 3: score impact
  {key}  [{priority}]  [{status}]
  {summary}
  Labels: {labels}

🟠 CRITICAL NOT STARTED ({count})            ← Gate 3: score impact
  {key}  [{priority}]  [{status}]
  {summary}

⚠️ NEEDS HUMAN / BLOCKED ({count})           ← Advisory
  {key}  [{status}]
  {summary}
  Labels: {labels}

📋 ALL IN-FLIGHT ({count} total)             ← Cross-repo dependency input
  {key}  [{priority}]  [{status}]  {summary}

──────────────────────────────────────────
Gate 3 score:
  0 critical in progress + 0 not started  →  25 pts  ✅
  0 in progress, N not started            →  15 pts
  1 in progress                           →   5 pts  ⚠️
  2+ in progress                          →   0 pts  ❌

Current: critical_in_progress={count}, critical_not_started={count}  →  {score}/25
```

If all lists are empty, output: "No blocking or in-flight issues found. Gate 3: 25/25."

### Gate 3 Scoring Reference

Apply automatically from `critical_in_progress` count:

| critical_in_progress | critical_not_started | Score |
|---------------------|---------------------|-------|
| 0 | 0 | 25 |
| 0 | >0 | 15 |
| 1 | any | 5 |
| 2+ | any | 0 |
```
