# add_issue_link

Create a link between two Jira issues.

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| inward_issue_key | string | yes | The inward issue (e.g., the blocker) |
| outward_issue_key | string | yes | The outward issue (e.g., the blocked issue) |
| link_type | string | yes | "Blocks", "Relates", "Cloners", or "Duplicate" |
| comment | string | no | Optional comment to add with the link |

## Example

```bash
npx tsx ~/.claude/skills/jira/add_issue_link.ts '{
  "inward_issue_key": "PROJ-100",
  "outward_issue_key": "PROJ-101",
  "link_type": "Blocks"
}'
```
