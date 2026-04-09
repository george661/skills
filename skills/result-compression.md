# Result Compression

Automatic compression of large MCP tool results to reduce context consumption.

## How It Works

The `result-compressor.py` hook automatically processes results from:
- Jira REST skills (`npx tsx .claude/skills/jira/*.ts`)
- Bitbucket REST skills (`npx tsx .claude/skills/bitbucket/*.ts`)
- AgentDB REST skills (`npx tsx .claude/skills/agentdb/*.ts`)

## Compression Rules

| Pattern | Threshold | Action |
|---------|-----------|--------|
| Arrays (issues, values, results) | > 20 items | Show first 20 + metadata |
| Strings | > 2000 chars | Truncate with indicator |
| Total result | > 8000 chars | Recursive compression |

## Configuration

Set via environment variables:

```bash
# Maximum result size before compression (default: 8000)
RESULT_COMPRESS_MAX_CHARS=8000

# Maximum array items to keep (default: 20)
RESULT_COMPRESS_MAX_ITEMS=20

# Enable summary in compressed output (default: true)
RESULT_COMPRESS_SUMMARY=true
```

## Compressed Output Format

When compression occurs, the result includes:

```json
{
  "_compressed": true,
  "_savings": "45%",
  "tool_result": {
    "values": {
      "_compressed": true,
      "_type": "array",
      "_total": 150,
      "_showing": 20,
      "sample": [...first 20 items...],
      "_note": "Showing first 20 of 150 items. Use pagination or filtering for more."
    },
    "_compression": {
      "original_size": "45K chars",
      "tool": "npx tsx .claude/skills/jira-mcp/search_issues.ts"
    }
  }
}
```

## Metrics

Compression stats logged to: `~/.claude/result-compression.log`

Example log entries:
```
2025-01-08T11:30:00 - Compressed .claude/skills/jira-mcp/search_issues.ts: 45K chars -> 8K chars (82.2% reduction)
2025-01-08T11:30:05 - Compressed .claude/skills/bitbucket-mcp/list_pipelines.ts: 12K chars -> 4K chars (66.7% reduction)
```

## When to Disable

If you need full uncompressed results for a specific operation:

1. Use more specific queries with `fields` and `max_results` parameters
2. Paginate through results instead of fetching all at once
3. Temporarily increase thresholds via environment variables

## Expected Impact

Based on Anthropic engineering recommendations:
- **25-40% reduction** in tool result context consumption
- **Faster responses** due to smaller context windows
- **No loss of critical data** - summaries indicate what was truncated
