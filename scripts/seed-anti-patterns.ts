#!/usr/bin/env npx tsx
/**
 * Seed anti-patterns into AgentDB from base + tenant config files.
 *
 * Reads base seed config from base/.claude/config/seed-anti-patterns.json,
 * reads tenant seed config from config/seed-anti-patterns.json (if exists),
 * merges tenant on top of base by task_type, and stores each pattern
 * idempotently (checks if exists first via pattern_search).
 *
 * Usage:
 *   npx tsx base/scripts/seed-anti-patterns.ts
 *   npx tsx base/scripts/seed-anti-patterns.ts --write-cache
 */

import { readFileSync, existsSync, mkdirSync, writeFileSync } from 'fs';
import { join } from 'path';
import { homedir } from 'os';
import { agentdbRequest } from '../.claude/skills/agentdb/agentdb-client.js';

interface SeedPattern {
  task_type: string;
  approach: string;
  success_rate: number;
  tags: string[];
}

interface SeedConfig {
  version: number;
  patterns: SeedPattern[];
}

interface SearchResult {
  task_type: string;
  approach: string;
  success_rate: number;
  similarity?: number;
}

interface SearchResponse {
  success: boolean;
  results: SearchResult[];
}

interface StoreResponse {
  success: boolean;
  patternId?: string;
}

function loadConfig(filePath: string): SeedConfig | null {
  if (!existsSync(filePath)) {
    return null;
  }
  try {
    return JSON.parse(readFileSync(filePath, 'utf-8'));
  } catch (err) {
    console.error(`Failed to parse ${filePath}:`, err);
    return null;
  }
}

function mergeConfigs(base: SeedConfig, tenant: SeedConfig | null): SeedPattern[] {
  const byType = new Map<string, SeedPattern>();

  for (const p of base.patterns) {
    byType.set(p.task_type, p);
  }

  if (tenant) {
    for (const p of tenant.patterns) {
      byType.set(p.task_type, p);
    }
  }

  return Array.from(byType.values());
}

async function main(): Promise<void> {
  const writeCache = process.argv.includes('--write-cache');

  // Resolve paths relative to the script location
  // Script is at base/scripts/seed-anti-patterns.ts
  // Base config is at base/.claude/config/seed-anti-patterns.json
  const scriptDir = import.meta.dirname || __dirname;
  const baseDir = join(scriptDir, '..');
  const repoRoot = join(baseDir, '..');

  const baseConfigPath = join(baseDir, '.claude', 'config', 'seed-anti-patterns.json');
  const tenantConfigPath = join(repoRoot, 'config', 'seed-anti-patterns.json');

  console.log('[seed] Loading base config:', baseConfigPath);
  const baseConfig = loadConfig(baseConfigPath);
  if (!baseConfig) {
    console.error('[seed] Base config not found or invalid. Aborting.');
    process.exit(1);
  }

  console.log('[seed] Loading tenant config:', tenantConfigPath);
  const tenantConfig = loadConfig(tenantConfigPath);
  if (tenantConfig) {
    console.log(`[seed] Tenant config loaded: ${tenantConfig.patterns.length} patterns`);
  } else {
    console.log('[seed] No tenant config found (optional)');
  }

  const merged = mergeConfigs(baseConfig, tenantConfig);
  console.log(`[seed] Merged ${merged.length} patterns total`);

  let seeded = 0;
  let skipped = 0;
  let failed = 0;

  for (const pattern of merged) {
    try {
      // Check if pattern already exists
      const searchResult = await agentdbRequest<SearchResponse>(
        'POST',
        '/api/v1/pattern/search',
        { task: pattern.task_type, k: 1 }
      );

      const existing = searchResult?.results?.find(
        (r) => r.task_type === pattern.task_type && (r.similarity ?? 0) > 0.95
      );

      if (existing) {
        console.log(`[seed] SKIP: ${pattern.task_type} (already exists)`);
        skipped++;
        continue;
      }

      // Store the pattern
      const storeResult = await agentdbRequest<StoreResponse>(
        'POST',
        '/api/v1/pattern/store',
        {
          task_type: pattern.task_type,
          approach: pattern.approach,
          success_rate: pattern.success_rate,
          tags: pattern.tags,
        }
      );

      if (storeResult?.success) {
        console.log(`[seed] STORED: ${pattern.task_type}`);
        seeded++;
      } else {
        console.error(`[seed] FAILED: ${pattern.task_type} - unexpected response`);
        failed++;
      }
    } catch (err) {
      console.error(`[seed] FAILED: ${pattern.task_type} -`, err instanceof Error ? err.message : String(err));
      failed++;
    }
  }

  console.log(`\n[seed] Results: ${seeded} seeded, ${skipped} skipped, ${failed} failed`);

  // Write cache if requested
  if (writeCache) {
    const cacheDir = join(homedir(), '.claude', 'cache');
    mkdirSync(cacheDir, { recursive: true });

    const cachePath = join(cacheDir, 'anti-patterns.json');
    const cacheData = merged.map((p) => ({
      task_type: p.task_type,
      approach: p.approach,
      success_rate: p.success_rate,
      tags: p.tags,
    }));

    writeFileSync(cachePath, JSON.stringify(cacheData, null, 2));
    console.log(`[seed] Cache written to ${cachePath}`);
  }
}

main().catch((err) => {
  console.error('[seed] Fatal error:', err);
  process.exit(1);
});
