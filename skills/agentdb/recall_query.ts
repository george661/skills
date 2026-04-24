#!/usr/bin/env npx tsx
/**
 * recall_query - Search AgentDB for relevant past context
 *
 * Simplified wrapper around reflexion_retrieve_relevant for common use cases.
 * Returns past episodes matching the query with optional success filtering.
 */

import { agentdbRequest } from './agentdb-client.js';

interface RecallInput {
  query: string;           // Required: What to search for
  k?: number;              // Optional: Max results (default: 5)
  success_only?: boolean;  // Optional: Only return successful episodes
  namespace?: string;      // Optional: Namespace filter
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

interface RecallResponse {
  success: boolean;
  results: Episode[];
}

async function main(): Promise<void> {
  const inputArg = process.argv[2];

  if (!inputArg) {
    console.error('Usage: npx tsx recall_query.ts \'{"query": "search term", "k": 5}\'');
    process.exit(1);
  }

  let input: RecallInput;
  try {
    input = JSON.parse(inputArg);
  } catch {
    console.error('Invalid JSON input');
    process.exit(1);
  }

  if (!input.query) {
    console.error('query is required');
    process.exit(1);
  }

  const filters: Record<string, unknown> = {};
  if (input.success_only) {
    filters.success = true;
  }
  if (input.namespace) {
    filters.namespace = input.namespace;
  }

  try {
    const response = await agentdbRequest<RecallResponse>('POST', '/api/v1/reflexion/retrieve-relevant', {
      task: input.query,
      k: input.k || 5,
      filters: Object.keys(filters).length > 0 ? filters : undefined,
    });

    console.log(JSON.stringify(response, null, 2));
  } catch (error) {
    console.error('Error:', error instanceof Error ? error.message : String(error));
    process.exit(1);
  }
}

main();
