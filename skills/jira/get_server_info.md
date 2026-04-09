---
name: jira:get_server_info
description: Get Jira server information and version.
---

# get_server_info

Get information about the Jira server, including version, build number, and deployment type.

## Parameters

This function takes no parameters.

## Example

```typescript
// Get server information
npx tsx ~/.claude/skills/jira/get_server_info.ts '{}'
```

## Notes

- Useful for verifying connectivity to the Jira server
- Returns version information and server capabilities
