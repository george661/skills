---
name: jira:add_attachment
description: Upload a file attachment to a Jira issue.
---

# add_attachment

Upload a file as an attachment to a Jira issue. This is useful for attaching evidence artifacts such as screenshots, API response captures, terraform plans, or log files.

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `issue_key` | string | Yes | The issue key (e.g., "PROJ-123") |
| `file_path` | string | Yes | Absolute path to the file to upload |
| `filename` | string | No | Override filename for the attachment (defaults to the file's basename) |

## Example

```typescript
// Upload a screenshot as evidence
npx tsx ~/.claude/skills/jira/add_attachment.ts '{"issue_key": "PROJ-123", "file_path": "/tmp/validate-PROJ-123-dashboard.png", "filename": "dashboard-screenshot.png"}'

// Upload an API response capture
npx tsx ~/.claude/skills/jira/add_attachment.ts '{"issue_key": "PROJ-123", "file_path": "/tmp/api-response.json"}'

// Upload a terraform plan
npx tsx ~/.claude/skills/jira/add_attachment.ts '{"issue_key": "PROJ-123", "file_path": "/tmp/tfplan.txt", "filename": "terraform-plan.txt"}'
```

## Notes

- Uses multipart/form-data upload per Jira REST API v2 requirements
- Supports PNG, JSON, TXT, HTML, and other file types
- The `X-Atlassian-Token: no-check` header is set automatically (required by Jira for attachment uploads)
- Returns the attachment metadata including ID and self URL
- File size limits are determined by Jira server configuration
