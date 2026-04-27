#!/usr/bin/env npx tsx
/**
 * Reflexion Router — resolves reflexion/knowledge-store provider (agentdb)
 * and delegates to the right backend skill.
 *
 * Provider resolution order:
 * 1. Explicit `provider` argument
 * 2. REFLEXION_PROVIDER environment variable
 * 3. Default: agentdb
 *
 * Note: Only agentdb is currently supported. To add new providers (e.g., pinecone, chroma),
 * create the skills/{provider}/ directory and add mappings to SKILL_MAP below.
 *
 * Usage from other reflexion/ skills:
 *   import { resolveReflexionProvider, translateParams, delegateReflexion } from './reflexion-router.js';
 *   const provider = resolveReflexionProvider();
 *   const result = delegateReflexion(provider, 'reflexion_retrieve', { session_id: 'test', task: 'my-task', k: 5 });
 */
import { spawnSync } from 'child_process';
import { existsSync } from 'fs';
import { join } from 'path';
import { homedir } from 'os';

// ---------------------------------------------------------------------------
// Debug
// ---------------------------------------------------------------------------

const DEBUG = !!process.env.REFLEXION_DEBUG;

function debug(...args: unknown[]) {
  if (DEBUG) process.stderr.write(`[reflexion-router] ${args.map(String).join(' ')}\n`);
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type ReflexionProvider = 'agentdb';

// ---------------------------------------------------------------------------
// Skill name mapping — unified name → provider-specific skill path
//
// AgentDB delegates to skills/agentdb/reflexion_*.ts.
// Future providers (pinecone, chroma) will have their own directories.
// ---------------------------------------------------------------------------

interface SkillMapping {
  dir: string;   // skill directory name under ~/.claude/skills/
  name: string;  // skill file name (without .ts)
}

const SKILL_MAP: Record<string, Partial<Record<ReflexionProvider, SkillMapping>>> = {
  reflexion_retrieve: {
    agentdb: { dir: 'agentdb', name: 'reflexion_retrieve_relevant' },
  },
  reflexion_store: {
    agentdb: { dir: 'agentdb', name: 'reflexion_store_episode' },
  },
};

// ---------------------------------------------------------------------------
// Provider → default skill directory mapping (fallback for unmapped skills)
// ---------------------------------------------------------------------------

const PROVIDER_DEFAULT_DIR: Record<ReflexionProvider, string> = {
  agentdb: 'agentdb',
};

// ---------------------------------------------------------------------------
// resolveReflexionProvider
// ---------------------------------------------------------------------------

/**
 * Resolve which reflexion provider to use.
 *
 * 1. Explicit argument (highest priority)
 * 2. REFLEXION_PROVIDER env var
 * 3. Default: agentdb
 */
export function resolveReflexionProvider(explicit?: string): ReflexionProvider {
  debug('resolveReflexionProvider called, explicit:', explicit);

  // 1. Explicit override
  if (explicit) {
    if (isValidProvider(explicit)) {
      debug('resolved via explicit arg:', explicit);
      return explicit;
    }
    throw new Error(`Invalid reflexion provider: "${explicit}". Valid providers: agentdb`);
  }

  // 2. Environment variable
  const envVal = process.env.REFLEXION_PROVIDER;
  if (envVal) {
    if (isValidProvider(envVal)) {
      debug('resolved via REFLEXION_PROVIDER env:', envVal);
      return envVal;
    }
    throw new Error(`Invalid reflexion provider in REFLEXION_PROVIDER env: "${envVal}". Valid providers: agentdb`);
  }

  // 3. Default
  debug('resolved via default: agentdb');
  return 'agentdb';
}

function isValidProvider(value: string): value is ReflexionProvider {
  return value === 'agentdb';
}

// ---------------------------------------------------------------------------
// translateParams
// ---------------------------------------------------------------------------

/**
 * Translate unified reflexion params to provider-specific params.
 *
 * - AgentDB: passthrough (no translation needed)
 */
export function translateParams(
  provider: ReflexionProvider,
  skill: string,
  params: Record<string, unknown>,
): Record<string, unknown> {
  debug('translateParams:', provider, skill, JSON.stringify(params));

  if (provider === 'agentdb') {
    return translateAgentDBParams(params);
  }

  // Fallback passthrough for pinecone/chroma (future)
  return { ...params };
}

function translateAgentDBParams(
  params: Record<string, unknown>,
): Record<string, unknown> {
  const out: Record<string, unknown> = { ...params };
  
  // AgentDB uses the same param schema as unified interface — passthrough
  // Clean provider field if present
  delete out.provider;
  
  return out;
}

// ---------------------------------------------------------------------------
// delegateReflexion
// ---------------------------------------------------------------------------

/**
 * Delegate to the appropriate provider skill.
 *
 * Resolves the skill directory and file, translates params,
 * then spawns the provider skill via `npx tsx`.
 */
export function delegateReflexion(
  provider: ReflexionProvider,
  skill: string,
  params: Record<string, unknown>,
): unknown {
  // Resolve provider-specific skill mapping
  const mapping = SKILL_MAP[skill]?.[provider];
  const skillDir = mapping?.dir ?? PROVIDER_DEFAULT_DIR[provider];
  const skillName = mapping?.name ?? skill;

  const translatedParams = translateParams(provider, skillName, params);

  // Resolve skill path
  const skillBase = join(homedir(), '.claude', 'skills', skillDir);
  const skillPath = join(skillBase, `${skillName}.ts`);

  if (!existsSync(skillPath)) {
    throw new Error(
      `Reflexion skill not found: ${skillPath} (provider: ${provider}, skill: ${skill} → ${skillName})`,
    );
  }

  debug('delegateReflexion:', provider, skill, '->', skillPath);
  debug('params:', JSON.stringify(translatedParams));

  // Use spawnSync to avoid shell escaping issues with JSON containing quotes
  const child = spawnSync('npx', ['tsx', skillPath, JSON.stringify(translatedParams)], {
    encoding: 'utf-8',
    stdio: ['pipe', 'pipe', 'pipe'],
    timeout: 60000,
  });

  if (child.error) throw child.error;
  if (child.status !== 0) {
    const stderr = child.stderr?.trim() || '';
    throw new Error(stderr || `Reflexion skill '${skillName}' exited with code ${child.status}`);
  }

  const result = child.stdout;
  try {
    return JSON.parse(result);
  } catch {
    return result; // plain text fallback
  }
}
