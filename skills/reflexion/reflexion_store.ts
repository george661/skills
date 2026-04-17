#!/usr/bin/env npx tsx
/**
 * Unified Reflexion Store — CLI wrapper for reflexion-router
 *
 * Stores an episode in the reflexion/knowledge-store provider.
 *
 * Usage:
 *   npx tsx reflexion_store.ts '{"session_id": "test", "task": "my-task", "input": {...}, "output": "...", "reward": 1, "success": true}'
 *   REFLEXION_PROVIDER=pinecone npx tsx reflexion_store.ts '{"session_id": "test", "task": "my-task", ...}'
 */

import { resolveReflexionProvider, delegateReflexion } from './reflexion-router.js';

const args = process.argv.slice(2);
if (args.length === 0) {
  console.error('Usage: npx tsx reflexion_store.ts \'{"session_id": "...", "task": "...", "input": {...}, "output": "...", "reward": 1, "success": true}\'');
  process.exit(1);
}

const params = JSON.parse(args[0]);

// Extract explicit provider if specified in params
const explicitProvider = params.provider as string | undefined;
const provider = resolveReflexionProvider(explicitProvider);

// Delegate to provider skill
const result = delegateReflexion(provider, 'reflexion_store', params);

// Output result
console.log(typeof result === 'string' ? result : JSON.stringify(result, null, 2));
