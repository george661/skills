#!/usr/bin/env npx tsx
/**
 * rx -- Project Workstation Readiness Prescription
 *
 * Diagnoses and fixes workstation configuration issues.
 *
 * Usage:
 *   npx tsx rx.ts [--dry-run] [--json] [--verbose] [--category <name>]
 */

import {
  loadPreviousLog,
  appendLogEntries,
  writeLastRun,
  generateRunId,
  formatResult,
  formatCategory,
  formatSummary,
  resolveProjectRoot,
  resolveAgentsRoot,
  acquireLock,
  releaseLock,
  rotateLog,
} from './rx-client.js';
import { ALL_CHECKS } from './checks/index.js';
import { CheckResult, RunOpts, RunSummary } from './types.js';

interface CliArgs {
  dryRun: boolean;
  json: boolean;
  verbose: boolean;
  category?: string;
}

export function parseArgs(argv: string[]): CliArgs {
  const args: CliArgs = { dryRun: false, json: false, verbose: false };
  for (let i = 0; i < argv.length; i++) {
    switch (argv[i]) {
      case '--dry-run': args.dryRun = true; break;
      case '--json': args.json = true; break;
      case '--verbose': args.verbose = true; break;
      case '--help': case '-h':
        console.log(`Usage: rx [--dry-run] [--json] [--verbose] [--category <name>] [--help]`);
        console.log(`Categories: ${ALL_CHECKS.map(c => c.name).join(', ')}`);
        process.exit(0);
      case '--category': {
        const nextArg = argv[i + 1];
        if (!nextArg || nextArg.startsWith('--')) {
          console.error('--category requires a value');
          process.exit(2);
        }
        args.category = argv[++i];
        break;
      }
    }
  }
  return args;
}

async function main(): Promise<void> {
  const args = parseArgs(process.argv.slice(2));
  const runId = generateRunId();
  const projectRoot = resolveProjectRoot();
  const agentsRoot = resolveAgentsRoot();

  if (!acquireLock()) {
    console.error('Another rx instance is running. Remove ~/.claude/rx/rx.lock if this is stale.');
    process.exit(2);
  }
  process.on('exit', releaseLock);
  process.on('SIGINT', () => { releaseLock(); process.exit(130); });

  rotateLog();

  const previousLog = loadPreviousLog();

  const opts: RunOpts = {
    dryRun: args.dryRun,
    verbose: args.verbose,
    json: args.json,
    category: args.category,
    previousLog,
    projectRoot,
    agentsRoot,
  };

  // Filter checks by category if specified
  const checks = args.category
    ? ALL_CHECKS.filter(c => c.name === args.category)
    : ALL_CHECKS;

  if (checks.length === 0) {
    console.error(`Unknown category: ${args.category}`);
    console.error(`Available: ${ALL_CHECKS.map(c => c.name).join(', ')}`);
    process.exit(2);
  }

  if (!args.json) {
    console.log(`\nProject Workstation Rx -- Diagnosing...${args.dryRun ? ' (dry-run)' : ''}\n`);
  }

  const allResults: CheckResult[] = [];
  let currentCategory = '';
  let criticalFailure = false;

  for (const check of checks) {
    // Skip downstream checks if prerequisites failed
    if (criticalFailure && check.name !== 'prereqs') {
      allResults.push({
        check: `${check.name}:skipped`,
        category: check.category,
        status: 'skipped',
        message: 'Skipped -- prerequisite checks failed',
      });
      if (!args.json) {
        console.log(formatCategory(check.category));
        console.log(formatResult(allResults[allResults.length - 1]));
      }
      continue;
    }

    try {
      const results = await check.run(opts);
      allResults.push(...results);

      // Check if this category had critical failures
      if (check.name === 'prereqs' && results.some(r => r.status === 'fail')) {
        criticalFailure = true;
      }

      if (!args.json) {
        for (const result of results) {
          if (result.category !== currentCategory) {
            currentCategory = result.category;
            console.log(formatCategory(currentCategory));
          }
          console.log(formatResult(result));
        }
      }
    } catch (err) {
      const errorResult: CheckResult = {
        check: `${check.name}:error`,
        category: check.category,
        status: 'fail',
        message: `Check "${check.name}" threw an error`,
        error: err instanceof Error ? err.message : String(err),
      };
      allResults.push(errorResult);
      if (!args.json) {
        if (check.category !== currentCategory) {
          currentCategory = check.category;
          console.log(formatCategory(currentCategory));
        }
        console.log(formatResult(errorResult));
      }
    }
  }

  // Compute summary
  const summary: RunSummary = {
    runId,
    timestamp: new Date().toISOString(),
    summary: {
      total: allResults.length,
      pass: allResults.filter(r => r.status === 'pass').length,
      fixed: allResults.filter(r => r.status === 'fixed').length,
      fail: allResults.filter(r => r.status === 'fail').length,
      skipped: allResults.filter(r => r.status === 'skipped').length,
    },
    results: allResults,
    logFile: '~/.claude/rx/rx-log.jsonl',
  };

  // Persist
  appendLogEntries(runId, allResults);
  writeLastRun(summary);

  // Output
  if (args.json) {
    console.log(JSON.stringify(summary, null, 2));
  } else {
    console.log(formatSummary(summary.summary));
    console.log(`Log: ~/.claude/rx/rx-log.jsonl\n`);
  }

  // Exit code
  const exitCode = summary.summary.fail > 0 ? 1 : 0;
  process.exit(exitCode);
}

// Only run main() when executed directly, not when imported by tests
if (!process.env.VITEST) {
  main().catch(err => {
    console.error('rx orchestrator error:', err);
    process.exit(2);
  });
}
