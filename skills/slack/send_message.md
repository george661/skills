---
name: slack:send_message
description: Send a message to a Slack channel
---

# send_message

Send a message to a Slack channel using the Slack API. Supports plain text messages, Block Kit rich formatting, thread replies, and link unfurling options.

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `channel` | `string` | No | Channel ID to send the message to (e.g., `C1234567890`). Falls back to `SLACK_DEFAULT_CHANNEL` from settings if not provided. |
| `text` | `string` | No | Plain text message content. Used as fallback text for notifications when blocks are provided. |
| `blocks` | `unknown[]` | No | Array of Block Kit blocks for rich message formatting. See [Block Kit reference](https://api.slack.com/reference/block-kit/blocks). |
| `thread_ts` | `string` | No | Timestamp of parent message to reply in thread. Format: `1234567890.123456`. |
| `reply_broadcast` | `boolean` | No | When replying in a thread, also post to the channel. Only valid when `thread_ts` is provided. |
| `unfurl_links` | `boolean` | No | Enable unfurling of primarily text-based content. |
| `unfurl_media` | `boolean` | No | Enable unfurling of media content. |

## Example

```typescript
// Simple text message
npx tsx ~/.claude/skills/slack/send_message.ts '{"text": "Hello world!"}'

// Message to specific channel
npx tsx ~/.claude/skills/slack/send_message.ts '{"channel": "C1234567890", "text": "Hello team!"}'

// Thread reply
npx tsx ~/.claude/skills/slack/send_message.ts '{"channel": "C1234567890", "text": "Reply in thread", "thread_ts": "1234567890.123456"}'

// With Block Kit formatting
npx tsx ~/.claude/skills/slack/send_message.ts '{"text": "Notification", "blocks": [{"type": "header", "text": {"type": "plain_text", "text": "Deployment Complete"}}]}'
```

## Notes

- Requires `SLACK_BOT_TOKEN` to be configured in `~/.claude/settings.json` under `mcpServers.slack.env`.
- If `channel` is not provided, the message is sent to `SLACK_DEFAULT_CHANNEL` from settings.
- When using `blocks`, always provide `text` as a fallback for notifications and accessibility.
- The script returns the Slack API response as JSON.
