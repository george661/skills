#!/usr/bin/env npx tsx
/**
 * write_build_cache - Write build status to .build-cache.json
 *
 * Caches Concourse build status queries to reduce redundant API calls.
 * Merges new entries into the existing cache file (or creates it).
 * Each entry is keyed by a user-provided key (e.g., "pr-check-42")
 * and timestamped with cachedAt for TTL enforcement by read_build_cache.
 *
 * Usage:
 *   npx tsx write_build_cache.ts '{"worktreePath": ".", "key": "pr-check-42", "job": "pr-check", "status": "succeeded", "buildId": 100}'
 *   npx tsx write_build_cache.ts '{"key": "main-build", "status": "failed", "buildId": 201}'
 */

import { readFileSync, writeFileSync, existsSync } from "fs";
import { resolve } from "path";

const input = JSON.parse(process.argv[2] || "{}");
const cachePath = resolve(input.worktreePath || ".", ".build-cache.json");

let cache: Record<string, unknown> = {};
if (existsSync(cachePath)) {
  try {
    cache = JSON.parse(readFileSync(cachePath, "utf-8"));
  } catch {
    // Start fresh if corrupt
  }
}

const { worktreePath, key, ...data } = input;
const cacheKey = key || "default";
cache[cacheKey] = { ...data, cachedAt: new Date().toISOString() };

writeFileSync(cachePath, JSON.stringify(cache, null, 2) + "\n");
console.log(JSON.stringify({ written: true, key: cacheKey }));
