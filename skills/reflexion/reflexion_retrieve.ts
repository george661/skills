#!/usr/bin/env npx tsx
/**
 * Unified Reflexion Retrieve — CLI wrapper for reflexion-router
 *
 * Retrieves relevant episodes from the reflexion/knowledge-store provider.
 *
 * Usage:
 *   npx tsx reflexion_retrieve.ts '{"session_id": "test", "task": "my-task", "k": 5}'
 *   REFLEXION_PROVIDER=pinecone npx tsx reflexion_retrieve.ts '{"session_id": "test", "task": "my-task", "k": 5}'
 */

import { resolveReflexionProvider, delegateReflexion } from './reflexion-router.js';

const args = process.argv.slice(2);
if (args.length === 0) {
  console.error('Usage: npx tsx reflexion_retrieve.ts \'{"session_id": "...", "task": "...", "k": 5}\'');
  process.exit(1);
}

const params = JSON.parse(args[0]);

// Extract explicit provider if specified in params
const explicitProvider = params.provider as string | undefined;
const provider = resolveReflexionProvider(explicitProvider);

// Delegate to provider skill
const result = delegateReflexion(provider, 'reflexion_retrieve', params);

// Output result
console.log(typeof result === 'string' ? result : JSON.stringify(result, null, 2));
