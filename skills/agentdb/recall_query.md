# recall_query

Search AgentDB for relevant past context and episodes.

## Usage

```bash
npx tsx recall_query.ts '{"query": "deploy Lambda function", "k": 5}'
```

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| query | string | Yes | Search query - what context to find |
| k | number | No | Max results to return (default: 5) |
| success_only | boolean | No | Only return successful episodes |
| namespace | string | No | Filter by namespace (e.g., "${TENANT_NAMESPACE}") |

## Response

```json
{
  "episodes": [
    {
      "session_id": "abc123",
      "task": "Deploy Lambda function to AWS",
      "reward": 0.9,
      "success": true,
      "output": "Successfully deployed...",
      "similarity": 0.87
    }
  ],
  "count": 1
}
```

## Examples

Search for validation context:
```bash
npx tsx recall_query.ts '{"query": "validate PROJ-123", "k": 3, "success_only": true}'
```

Search within namespace:
```bash
npx tsx recall_query.ts '{"query": "fix pipeline", "namespace": "${TENANT_NAMESPACE}"}'
```

## Credential Resolution

Credentials are resolved in order:
1. Environment variables: `AGENTDB_API_KEY`, `AGENTDB_URL`
2. `~/.claude/settings.json` → `credentials.agentdb`
3. `~/.claude/settings.json` → `mcpServers.agentdb` (legacy)
4. AWS Secrets Manager: `agentdb-dev-api-key`
