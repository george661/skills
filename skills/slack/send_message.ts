#!/usr/bin/env npx tsx
// send_message - Send a message to a Slack channel
import { slackRequest, getDefaultChannel } from './slack-client.js';

interface Input {
  channel?: string;
  text?: string;
  blocks?: unknown[];
  thread_ts?: string;
  reply_broadcast?: boolean;
  unfurl_links?: boolean;
  unfurl_media?: boolean;
}

async function execute(input: Input) {
  const channel = input.channel || getDefaultChannel();
  if (!channel) {
    throw new Error('No channel specified and no default channel configured');
  }

  return slackRequest('chat.postMessage', {
    channel,
    ...input,
  });
}

const input = JSON.parse(process.argv[2] || '{}') as Input;
execute(input)
  .then((r) => console.log(JSON.stringify(r, null, 2)))
  .catch((e) => { console.error(e.message); process.exit(1); });
