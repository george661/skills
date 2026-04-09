---
name: jira:get_config
description: Get the current MCP server configuration (host, projects).
---

# get_config

Get the current Jira MCP server configuration, including the host and configured projects.

## Parameters

This function takes no parameters.

## Example

```typescript
// Get current configuration
npx tsx ~/.claude/skills/jira/get_config.ts '{}'
```

## Notes

- Useful for verifying your Jira connection is properly configured
- Returns server information including the Jira host URL
