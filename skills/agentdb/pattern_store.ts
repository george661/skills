#!/usr/bin/env npx tsx
/**
 * pattern_store - Store a reasoning pattern
 *
 * Records successful approaches for task types.
 */

import { agentdbRequest } from './agentdb-client.js';

interface Input {
  [key: string]: unknown;
  task_type: string;
  approach: string;
  success_rate: number;
  metadata?: Record<string, unknown>;
  tags?: string[];
}

interface StoreResponse {
  success: boolean;
  patternId: string;
}

async function main(): Promise<void> {
  const inputArg = process.argv[2];

  if (!inputArg) {
    console.error('Usage: npx tsx pattern_store.ts \'{"task_type": "...", "approach": "...", "success_rate": 0.9}\'');
    process.exit(1);
  }

  let input: Input;
  try {
    input = JSON.parse(inputArg);
  } catch {
    console.error('Invalid JSON input');
    process.exit(1);
  }

  if (!input.task_type || !input.approach || input.success_rate === undefined) {
    console.error('Required fields: task_type, approach, success_rate');
    process.exit(1);
  }

  try {
    const response = await agentdbRequest<StoreResponse>('POST', '/api/v1/pattern/store', input);
    console.log(JSON.stringify(response, null, 2));
  } catch (error) {
    console.error('Error:', error instanceof Error ? error.message : String(error));
    process.exit(1);
  }
}

main();
