# AgentDB MCP Skills

Skills for interacting with the AgentDB memory service via REST API.

## Overview

AgentDB provides persistent memory for AI agents, including:
- **Reflexion episodes**: Store task attempts with outcomes for learning
- **Reasoning patterns**: Store successful approaches by task type

## API Credentials

The skills retrieve API credentials in this order:

1. **Environment variable**: `AGENTDB_API_KEY`
2. **AWS Secrets Manager**: `agentdb-dev-api-key` (requires AWS credentials)
3. **Claude MCP settings**: `~/.claude/settings.json` → `mcpServers.agentdb.headers.X-Api-Key`

### Getting the API Key

```bash
# Option 1: From AWS Secrets Manager (recommended for automation)
AWS_PROFILE=${AWS_PROFILE_DEV} aws secretsmanager get-secret-value \
  --secret-id agentdb-dev-api-key \
  --query 'SecretString' --output text | jq -r '.apiKey'

# Option 2: Export for current session
export AGENTDB_API_KEY="your-api-key-here"
```

### Claude MCP Settings Configuration

Add to `~/.claude/settings.json`:

```json
{
  "mcpServers": {
    "agentdb": {
      "type": "sse",
      "url": "https://YOUR_AGENTDB_HOST/sse",
      "headers": {
        "X-Api-Key": "YOUR_API_KEY_HERE"
      }
    }
  }
}
```

## REST API Endpoints

All skills use the REST API (not SSE/MCP protocol):

| Skill | Method | Endpoint |
|-------|--------|----------|
| `db_get_health` | GET | `/api/v1/db/health` |
| `db_get_stats` | GET | `/api/v1/db/stats` |
| `reflexion_store_episode` | POST | `/api/v1/reflexion/store-episode` |
| `reflexion_retrieve_relevant` | POST | `/api/v1/reflexion/retrieve-relevant` |
| `pattern_store` | POST | `/api/v1/pattern/store` |
| `pattern_search` | POST | `/api/v1/pattern/search` |

## Direct curl Examples

```bash
# Set API key
API_KEY=$(AWS_PROFILE=${AWS_PROFILE_DEV} aws secretsmanager get-secret-value \
  --secret-id agentdb-dev-api-key \
  --query 'SecretString' --output text | jq -r '.apiKey')

# Health check
curl -H "X-Api-Key: $API_KEY" https://YOUR_AGENTDB_HOST/api/v1/db/health

# Get stats
curl -H "X-Api-Key: $API_KEY" https://YOUR_AGENTDB_HOST/api/v1/db/stats

# Store episode
curl -X POST -H "X-Api-Key: $API_KEY" -H "Content-Type: application/json" \
  https://YOUR_AGENTDB_HOST/api/v1/reflexion/store-episode \
  -d '{"session_id":"test-123","task":"example task","reward":1.0,"success":true}'

# Search patterns
curl -X POST -H "X-Api-Key: $API_KEY" -H "Content-Type: application/json" \
  https://YOUR_AGENTDB_HOST/api/v1/pattern/search \
  -d '{"task":"implement authentication","k":5}'
```

## Available Skills

- [db_get_health](./db_get_health.md) - Health check
- [db_get_stats](./db_get_stats.md) - Database statistics
- [reflexion_store_episode](./reflexion_store_episode.md) - Store learning episodes
- [reflexion_retrieve_relevant](./reflexion_retrieve_relevant.md) - Search past episodes
- [pattern_store](./pattern_store.md) - Store reasoning patterns
- [pattern_search](./pattern_search.md) - Search patterns by task
