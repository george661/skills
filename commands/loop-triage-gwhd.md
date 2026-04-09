---
description: Hourly INTAKE intake triage loop - fetch open issues, triage each, notify #eng of new TODO items
---

# INTAKE Hourly Triage Loop

## Overview

This command is designed to run on a recurring schedule (hourly). It:

1. Fetches all open INTAKE issues (To Do + In Progress)
2. Detects newly discovered To Do issues (not seen in previous runs)
3. Sends a Slack notification to #eng for any new To Do issues
4. Runs `/triage` on every open issue

---

## Step 1: Fetch Open INTAKE Issues

```bash
cd $PROJECT_ROOT && npx tsx .claude/skills/issues/search_issues.ts '{"jql": "project = ${INTAKE_PROJECT} AND status in (\"To Do\", \"In Progress\") ORDER BY created ASC", "fields": ["key", "summary", "status", "created", "reporter"]}'
```

Parse the result into two buckets:
- `todoIssues`: issues with status "To Do"
- `inProgressIssues`: issues with status "In Progress"

If no issues are found in either bucket, output "No open INTAKE issues found" and exit cleanly.

---

## Step 2: Detect New To Do Issues

Retrieve the previously known set of INTAKE issue keys from AgentDB:

```bash
cd $PROJECT_ROOT && npx tsx .claude/skills/agentdb/recall_query.ts '{"query": "gwhd-triage-loop known-issue-keys", "k": 1}'
```

Compare `todoIssues` keys against the stored set. Issues whose keys are NOT in the stored set are **new**.

Build `newTodoIssues` = todo issues not previously seen.

---

## Step 3: Notify #eng of New To Do Issues

If `newTodoIssues` is non-empty, send a Slack message to #eng:

```bash
cd $PROJECT_ROOT && npx tsx .claude/skills/slack/send_message.ts '{
  "channel": "C07SGBQ96MS",
  "text": "New INTAKE intake issues need triage",
  "blocks": [
    {
      "type": "header",
      "text": { "type": "plain_text", "text": ":inbox_tray: New INTAKE Intake Issues" }
    },
    {
      "type": "section",
      "text": {
        "type": "mrkdwn",
        "text": "*${newTodoIssues.length} new issue(s) arrived since last triage run:*\n${newTodoIssues.map(i => `• <https://your-org.atlassian.net/browse/${i.key}|${i.key}> — ${i.summary}`).join('\n')}"
      }
    },
    {
      "type": "context",
      "elements": [{ "type": "mrkdwn", "text": "Triage is running automatically via the hourly loop." }]
    }
  ]
}'
```

If `newTodoIssues` is empty, skip this step silently.

---

## Step 4: Update Known Issue Keys in AgentDB

Store the current full set of open issue keys so the next run can detect new ones:

```bash
cd $PROJECT_ROOT && npx tsx .claude/skills/agentdb/reflexion_store_episode.ts '{
  "session_id": "gwhd-triage-loop",
  "task": "gwhd-triage-loop known-issue-keys",
  "input": "hourly scan",
  "output": "${JSON.stringify({ knownKeys: [...todoIssues, ...inProgressIssues].map(i => i.key), lastRunAt: new Date().toISOString() })}",
  "reward": 1.0,
  "success": true,
  "critique": "Updated known INTAKE issue key set. ${newTodoIssues.length} new To Do issue(s) detected."
}'
```

---

## Step 5: Triage All Open Issues

For each issue in `[...todoIssues, ...inProgressIssues]`, run the triage command sequentially:

```typescript
for (const issue of [...todoIssues, ...inProgressIssues]) {
  Skill("triage", issue.key)
}
```

Process issues in order: To Do issues first (oldest first), then In Progress issues.

After each triage completes, output a brief status line:
```
✓ Triaged ${issue.key}: ${issue.summary}
```

---

## Step 6: Summary

After all issues are processed, output:

```
## INTAKE Triage Loop Complete

- To Do issues processed: ${todoIssues.length}
- In Progress issues processed: ${inProgressIssues.length}
- New issues detected (notified #eng): ${newTodoIssues.length}
- Total triaged: ${todoIssues.length + inProgressIssues.length}
```

---

## Error Handling

- If Jira search fails: log the error and exit without running triage
- If AgentDB recall fails: treat all current To Do issues as new (safe default — may over-notify but won't miss new issues)
- If Slack send fails: log the error but continue with triage
- If a single `/triage` call fails: log the error, continue to the next issue (do not abort the loop)
