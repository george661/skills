#!/usr/bin/env npx tsx
/**
 * reflexion_store_episode - Store a learning episode
 *
 * Records task execution with outcome for future pattern learning.
 */

import { agentdbRequest } from './agentdb-client.js';

interface Input {
  [key: string]: unknown;
  session_id: string;
  task: string;
  reward: number;
  success: boolean;
  critique?: string;
  input?: string;
  output?: string;
  latency_ms?: number;
  tokens_used?: number;
}

interface StoreResponse {
  success: boolean;
  id: string;
}

async function main(): Promise<void> {
  const inputArg = process.argv[2];

  if (!inputArg) {
    console.error('Usage: npx tsx reflexion_store_episode.ts \'{"session_id": "...", "task": "...", "reward": 0.9, "success": true}\'');
    process.exit(1);
  }

  let input: Input;
  try {
    input = JSON.parse(inputArg);
  } catch {
    console.error('Invalid JSON input');
    process.exit(1);
  }

  if (!input.session_id || !input.task || input.reward === undefined || input.success === undefined) {
    console.error('Required fields: session_id, task, reward, success');
    process.exit(1);
  }

  try {
    const response = await agentdbRequest<StoreResponse>('POST', '/api/v1/reflexion/store-episode', input);
    console.log(JSON.stringify(response, null, 2));
  } catch (error) {
    console.error('Error:', error instanceof Error ? error.message : String(error));
    process.exit(1);
  }
}

main();
