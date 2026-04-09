#!/usr/bin/env npx tsx
/**
 * read_build_cache - Read cached build status from .build-cache.json
 *
 * Checks for a cached Concourse build status entry with a 5-minute TTL.
 * Reduces redundant Concourse API calls when multiple commands check the
 * same build status within a short window (e.g., /review then /resolve-pr).
 *
 * Usage:
 *   npx tsx read_build_cache.ts '{"worktreePath": ".", "key": "pr-check-42"}'
 *   npx tsx read_build_cache.ts '{"key": "main-build"}'
 */

import { readFileSync, existsSync } from "fs";
import { resolve } from "path";

const input = JSON.parse(process.argv[2] || "{}");
const cachePath = resolve(input.worktreePath || ".", ".build-cache.json");
const TTL_MS = 5 * 60 * 1000; // 5 minutes

if (!existsSync(cachePath)) {
  console.log(JSON.stringify({ hit: false }));
  process.exit(0);
}

try {
  const raw = readFileSync(cachePath, "utf-8");
  const cache = JSON.parse(raw);
  const key = input.key || "default";
  const entry = cache[key];

  if (!entry || !entry.cachedAt) {
    console.log(JSON.stringify({ hit: false }));
    process.exit(0);
  }

  const age = Date.now() - new Date(entry.cachedAt).getTime();
  if (age > TTL_MS) {
    console.log(JSON.stringify({ hit: false, reason: "expired", ageMs: age }));
    process.exit(0);
  }

  console.log(JSON.stringify({ hit: true, ageMs: age, ...entry }));
} catch (e: unknown) {
  const message = e instanceof Error ? e.message : String(e);
  console.log(JSON.stringify({ hit: false, error: message }));
}
