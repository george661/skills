#!/usr/bin/env npx tsx
/**
 * wait-for-ci.ts — Wait for a Concourse build to complete and return structured per-task output.
 *
 * Usage:
 *   npx tsx wait-for-ci.ts '{"url": "https://ci.dev.example.com/teams/main/pipelines/frontend-app/jobs/pr-check/builds/431"}'
 *   npx tsx wait-for-ci.ts '{"pipeline": "frontend-app", "job": "pr-check"}'
 *   npx tsx wait-for-ci.ts '{"pipeline": "frontend-app", "job": "pr-check", "build": 431, "timeout_seconds": 600}'
 *
 * Returns:
 *   {
 *     "run": "https://ci.dev.../teams/main/pipelines/frontend-app/jobs/pr-check/builds/431",
 *     "success": true,
 *     "build_id": 1234,
 *     "status": "succeeded",
 *     "output": {
 *       "build": { "success": true,  "logs": ["line1", "line2"] },
 *       "test":  { "success": false, "logs": ["FAIL: TestFoo"] }
 *     }
 *   }
 */
import { execSync } from 'child_process';
import { existsSync, readFileSync } from 'fs';
import { homedir } from 'os';
import { join } from 'path';
import { flyExecJson, getFlyTarget } from './fly-client.js';

interface Input {
  url?: string;
  pipeline?: string;
  job?: string;
  build?: string | number;
  timeout_seconds?: number;
  poll_interval?: number;
}

interface TaskOutput {
  success: boolean;
  logs: string[];
}

interface BuildResult {
  run: string;
  success: boolean;
  build_id: number;
  status: string;
  output: Record<string, TaskOutput>;
}

interface Build {
  id: number;
  name: string;
  status: string;
  team_name: string;
  pipeline_name: string;
  job_name: string;
  start_time?: number;
  end_time?: number;
}

/** Parse a Concourse UI URL → pipeline, job, build number */
function parseUrl(url: string): { pipeline: string; job: string; build: string } | null {
  const match = url.match(/\/pipelines\/([^/]+)\/jobs\/([^/]+)\/builds\/(\d+)/);
  if (!match) return null;
  return { pipeline: match[1], job: match[2], build: match[3] };
}

/** Read the Concourse base URL for a fly target from ~/.flyrc */
function getConcourseBaseUrl(target: string): string {
  const flyrcPath = join(homedir(), '.flyrc');
  if (existsSync(flyrcPath)) {
    const content = readFileSync(flyrcPath, 'utf-8');
    const targetIdx = content.indexOf(`${target}:`);
    if (targetIdx !== -1) {
      const section = content.slice(targetIdx, targetIdx + 300);
      const m = section.match(/api:\s*(\S+)/);
      if (m) return m[1].replace(/\/$/, '');
    }
  }
  return 'https://ci.dev.example.com';
}

/**
 * Fetch build events via `fly curl /api/v1/builds/{id}/events` (SSE format) and
 * return per-step output keyed by step name.
 */
function fetchBuildEvents(buildId: number): Record<string, TaskOutput> {
  const target = getFlyTarget();
  let rawOutput: string;
  try {
    rawOutput = execSync(
      `fly -t ${target} curl /api/v1/builds/${buildId}/events`,
      { stdio: ['pipe', 'pipe', 'pipe'], timeout: 60000, maxBuffer: 20 * 1024 * 1024 }
    ).toString();
  } catch (err: any) {
    rawOutput = err?.stdout?.toString() ?? '';
    if (!rawOutput) return {};
  }

  const taskOutputs: Record<string, TaskOutput> = {};
  const taskExitStatus: Record<string, number> = {};

  // Parse SSE: lines alternate between "event: <type>" and "data: <json>"
  let currentEventType = '';
  for (const line of rawOutput.split('\n')) {
    const trimmed = line.trim();
    if (trimmed.startsWith('event:')) {
      currentEventType = trimmed.slice(6).trim();
      continue;
    }
    if (!trimmed) {
      currentEventType = '';
      continue;
    }
    if (!trimmed.startsWith('data:')) continue;

    const jsonStr = trimmed.slice(5).trim();
    if (!jsonStr || jsonStr === 'end') continue;

    let data: any;
    try { data = JSON.parse(jsonStr); } catch { continue; }

    // Concourse sometimes wraps payload in a nested `data` key
    const evtType: string = currentEventType || data.event || '';
    const payload = data.data ?? data;

    if (evtType === 'log') {
      const stepName: string = payload.origin?.name ?? 'build';
      const text: string = payload.payload ?? '';
      if (!taskOutputs[stepName]) taskOutputs[stepName] = { success: true, logs: [] };
      if (text) {
        const clean = text.replace(/\x1b\[[0-9;]*[mGKHFABCDJfnsu]/g, '');
        taskOutputs[stepName].logs.push(...clean.split('\n').filter((l: string) => l.length > 0));
      }
    } else if (evtType === 'finish-task') {
      const stepName: string = payload.origin?.name ?? 'build';
      taskExitStatus[stepName] = payload.exit_status ?? 0;
      if (!taskOutputs[stepName]) taskOutputs[stepName] = { success: false, logs: [] };
    }
  }

  // Apply exit statuses collected from finish-task events
  for (const [name, exitStatus] of Object.entries(taskExitStatus)) {
    taskOutputs[name] = { ...taskOutputs[name] ?? { logs: [] }, success: exitStatus === 0 };
  }

  return taskOutputs;
}

/** Fallback: get raw fly watch output for a build and return as single "build" step */
function fetchWatchFallback(buildId: number, overallSuccess: boolean): Record<string, TaskOutput> {
  const target = getFlyTarget();
  let raw = '';
  try {
    raw = execSync(
      `fly -t ${target} watch -b ${buildId}`,
      { stdio: ['pipe', 'pipe', 'pipe'], timeout: 120000, maxBuffer: 10 * 1024 * 1024 }
    ).toString();
  } catch (err: any) {
    raw = err?.stdout?.toString() ?? '';
  }
  if (!raw.trim()) return {};
  const clean = raw.replace(/\x1b\[[0-9;]*[mGKHFABCDJfnsu]/g, '');
  return {
    build: {
      success: overallSuccess,
      logs: clean.split('\n').filter(l => l.length > 0),
    },
  };
}

function sleep(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms));
}

async function execute(input: Input): Promise<BuildResult> {
  let pipeline: string;
  let job: string;
  let buildName: string | undefined;

  if (input.url) {
    const parsed = parseUrl(input.url);
    if (!parsed) throw new Error(`Cannot parse Concourse build URL: ${input.url}`);
    pipeline = parsed.pipeline;
    job = parsed.job;
    buildName = parsed.build;
  } else {
    if (!input.pipeline) throw new Error('"pipeline" or "url" is required');
    if (!input.job) throw new Error('"job" or "url" is required');
    pipeline = input.pipeline;
    job = input.job;
    buildName = input.build !== undefined ? String(input.build) : undefined;
  }

  const timeoutSeconds = input.timeout_seconds ?? 900;
  const pollInterval = input.poll_interval ?? 30;
  const deadline = Date.now() + timeoutSeconds * 1000;
  const TERMINAL = new Set(['succeeded', 'failed', 'errored', 'aborted']);

  // Poll until the build reaches a terminal state
  let targetBuild: Build | undefined;
  while (Date.now() < deadline) {
    const builds = flyExecJson<Build[]>(['builds', '-j', `${pipeline}/${job}`, '--count', '10']);

    if (buildName !== undefined) {
      targetBuild = builds.find(b => String(b.name) === String(buildName));
      if (!targetBuild) throw new Error(`Build ${buildName} not found in ${pipeline}/${job}`);
    } else {
      targetBuild = builds[0];
    }

    if (targetBuild && TERMINAL.has(targetBuild.status)) break;

    if (Date.now() + pollInterval * 1000 > deadline) {
      throw new Error(`Timed out after ${timeoutSeconds}s waiting for ${pipeline}/${job} (status: ${targetBuild?.status ?? 'unknown'})`);
    }
    await sleep(pollInterval * 1000);
  }

  if (!targetBuild) throw new Error(`No builds found for ${pipeline}/${job}`);

  const flyTarget = getFlyTarget();
  const concourseUrl = getConcourseBaseUrl(flyTarget);
  const team = targetBuild.team_name ?? 'main';
  const runUrl = `${concourseUrl}/teams/${team}/pipelines/${pipeline}/jobs/${job}/builds/${targetBuild.name}`;
  const overallSuccess = targetBuild.status === 'succeeded';

  // Prefer structured event output; fall back to raw fly watch if empty
  let taskOutputs = fetchBuildEvents(targetBuild.id);
  if (Object.keys(taskOutputs).length === 0) {
    taskOutputs = fetchWatchFallback(targetBuild.id, overallSuccess);
  }

  return {
    run: runUrl,
    success: overallSuccess,
    build_id: targetBuild.id,
    status: targetBuild.status,
    output: taskOutputs,
  };
}

const input = JSON.parse(process.argv[2] || '{}') as Input;
execute(input)
  .then(r => console.log(JSON.stringify(r, null, 2)))
  .catch(e => { console.error(e.message); process.exit(1); });
