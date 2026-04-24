#!/usr/bin/env npx tsx
/**
 * reflexion_retrieve_relevant - Semantic search for relevant past episodes
 *
 * Returns episodes similar to the given task description.
 */

import { agentdbRequest } from './agentdb-client.js';

interface Input {
  [key: string]: unknown;
  task: string;
  k: number;
  threshold?: number;
  filters?: Record<string, unknown>;
}

interface Episode {
  session_id: string;
  task: string;
  reward: number;
  success: boolean;
  input?: string;
  output?: string;
  critique?: string;
  similarity?: number;
}

interface RetrieveResponse {
  success: boolean;
  results: Episode[];
}

async function main(): Promise<void> {
  const inputArg = process.argv[2];

  if (!inputArg) {
    console.error('Usage: npx tsx reflexion_retrieve_relevant.ts \'{"task": "...", "k": 5}\'');
    process.exit(1);
  }

  let input: Input;
  try {
    input = JSON.parse(inputArg);
  } catch {
    console.error('Invalid JSON input');
    process.exit(1);
  }

  if (!input.task || !input.k) {
    console.error('Required fields: task, k');
    process.exit(1);
  }

  try {
    const response = await agentdbRequest<RetrieveResponse>('POST', '/api/v1/reflexion/retrieve-relevant', input);
    console.log(JSON.stringify(response, null, 2));
  } catch (error) {
    console.error('Error:', error instanceof Error ? error.message : String(error));
    process.exit(1);
  }
}

main();
