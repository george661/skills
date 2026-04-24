#!/usr/bin/env npx tsx
/**
 * pattern_search - Search for relevant patterns
 *
 * Returns patterns similar to the given task description.
 */

import { agentdbRequest } from './agentdb-client.js';

interface Input {
  [key: string]: unknown;
  task: string;
  k: number;
  threshold?: number;
  filters?: Record<string, unknown>;
}

interface Pattern {
  task_type: string;
  approach: string;
  success_rate: number;
  metadata?: Record<string, unknown>;
  tags?: string[];
  similarity?: number;
}

interface SearchResponse {
  success: boolean;
  results: Pattern[];
}

async function main(): Promise<void> {
  const inputArg = process.argv[2];

  if (!inputArg) {
    console.error('Usage: npx tsx pattern_search.ts \'{"task": "...", "k": 5}\'');
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
    const response = await agentdbRequest<SearchResponse>('POST', '/api/v1/pattern/search', input);
    console.log(JSON.stringify(response, null, 2));
  } catch (error) {
    console.error('Error:', error instanceof Error ? error.message : String(error));
    process.exit(1);
  }
}

main();
