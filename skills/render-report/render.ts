#!/usr/bin/env npx tsx
/**
 * render-report/render.ts
 *
 * Renders report markdown files to HTML and opens in browser.
 * No pandoc required — uses `marked` for Markdown → HTML conversion.
 *
 * Usage:
 *   npx tsx render.ts                                  # interactive: pick from unrendered
 *   npx tsx render.ts daily-reports/2026-03-25.md      # render specific file
 *   npx tsx render.ts daily-reports/insights/2026-W13.md
 */

import { createInterface } from 'readline';
import { execSync } from 'child_process';
import { existsSync, mkdirSync, readdirSync, readFileSync, statSync, writeFileSync } from 'fs';
import { homedir } from 'os';
import { basename, dirname, join, relative, resolve } from 'path';
import { marked } from 'marked';

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------

function loadEnvFile(filePath: string): Record<string, string> {
  const env: Record<string, string> = {};
  if (!existsSync(filePath)) return env;
  try {
    const content = readFileSync(filePath, 'utf-8');
    for (const line of content.split('\n')) {
      const trimmed = line.trim();
      if (!trimmed || trimmed.startsWith('#')) continue;
      const match = trimmed.match(/^([^=]+)=(.*)$/);
      if (match) {
        const key = match[1].trim();
        let value = match[2].trim();
        if ((value.startsWith('"') && value.endsWith('"')) ||
            (value.startsWith("'") && value.endsWith("'"))) {
          value = value.slice(1, -1);
        }
        env[key] = value;
      }
    }
  } catch { /* ignore */ }
  return env;
}

function resolveProjectRoot(): string {
  if (process.env.PROJECT_ROOT) return resolve(process.env.PROJECT_ROOT);
  let dir = resolve(process.cwd());
  for (let i = 0; i < 10; i++) {
    if (existsSync(join(dir, '.env'))) return dir;
    const parent = resolve(dir, '..');
    if (parent === dir) break;
    dir = parent;
  }
  const home = homedir();
  for (const candidate of [join(home, 'projects', 'workspace'), join(home, 'workspace')]) {
    if (existsSync(join(candidate, '.env'))) return candidate;
  }
  return resolve(process.cwd());
}

const projectRoot = resolveProjectRoot();
const envPath = [
  join(projectRoot, 'agents', '.env'),
  join(projectRoot, '.env'),
].find(p => existsSync(p)) ?? '';
const envFile = envPath ? loadEnvFile(envPath) : {};
function env(key: string, fallback = ''): string {
  return process.env[key] ?? envFile[key] ?? fallback;
}

const DAILY_REPORTS_PATH = env('DAILY_REPORTS_PATH', join(projectRoot, 'daily-reports'));

// ---------------------------------------------------------------------------
// HTML template (same styling as retired render.sh)
// ---------------------------------------------------------------------------

function htmlTemplate(title: string, body: string): string {
  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${escapeHtml(title)}</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap');

body {
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
  max-width: 800px;
  margin: 48px auto;
  padding: 0 32px;
  font-size: 14px;
  line-height: 1.65;
  color: #111;
  background: #fff;
}

h1 {
  font-size: 1.5em;
  font-weight: 600;
  letter-spacing: -0.02em;
  border-bottom: 1px solid #e5e5e5;
  padding-bottom: 10px;
  margin-bottom: 4px;
}

h2 {
  font-size: 0.95em;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: #555;
  margin-top: 2em;
  margin-bottom: 0.5em;
}

h3 {
  font-size: 0.9em;
  font-weight: 600;
  margin-top: 1.5em;
  margin-bottom: 0.4em;
}

blockquote {
  margin: 0 0 1.2em 0;
  padding: 0;
  border: none;
  color: #666;
  font-size: 0.88em;
}

blockquote p { margin: 0; }

ul {
  padding-left: 1.2em;
  margin: 0.4em 0;
}

li {
  margin-bottom: 0.45em;
  line-height: 1.55;
}

ul.task-list { list-style: none; padding-left: 0.2em; }
ul.task-list li { display: flex; align-items: baseline; gap: 8px; }
input[type="checkbox"] { flex-shrink: 0; margin-top: 2px; accent-color: #555; }

code {
  font-family: "SF Mono", "Fira Code", "Menlo", monospace;
  background: #f0f0f0;
  padding: 1px 5px;
  border-radius: 3px;
  font-size: 0.85em;
  color: #333;
}

pre {
  background: #f7f7f7;
  border: 1px solid #e5e5e5;
  border-radius: 4px;
  padding: 12px 16px;
  overflow-x: auto;
}

pre code {
  background: none;
  padding: 0;
  font-size: 0.83em;
}

em { color: #666; font-style: italic; }

table { border-collapse: collapse; width: 100%; margin: 0.8em 0; font-size: 0.9em; }
th, td { border: 1px solid #e0e0e0; padding: 5px 10px; text-align: left; }
th { background: #f7f7f7; font-weight: 600; }
tr:nth-child(even) { background: #fafafa; }

p { margin: 0.5em 0 0.8em; }

hr { border: none; border-top: 1px solid #e5e5e5; margin: 1.5em 0; }
</style>
</head>
<body>
${body}
</body>
</html>`;
}

function escapeHtml(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

// ---------------------------------------------------------------------------
// File selection
// ---------------------------------------------------------------------------

function findUnrenderedReports(reportsDir: string): string[] {
  const results: string[] = [];

  function scan(dir: string): void {
    if (!existsSync(dir)) return;
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      if (entry.isDirectory()) {
        scan(join(dir, entry.name));
      } else if (entry.name.endsWith('.md') && !entry.name.startsWith('.')) {
        const mdPath = join(dir, entry.name);
        const htmlPath = mdPath.replace(/\.md$/, '.html');
        if (!existsSync(htmlPath)) {
          results.push(mdPath);
        }
      }
    }
  }

  scan(reportsDir);
  return results.sort((a, b) => statSync(b).mtimeMs - statSync(a).mtimeMs);
}

function parseSelection(answer: string, files: string[]): string[] {
  const trimmed = answer.trim().toLowerCase();
  if (trimmed === 'all') return files;

  // Range: "1-3"
  const rangeMatch = trimmed.match(/^(\d+)-(\d+)$/);
  if (rangeMatch) {
    const from = parseInt(rangeMatch[1]) - 1;
    const to = parseInt(rangeMatch[2]) - 1;
    return files.slice(Math.max(0, from), Math.min(files.length - 1, to) + 1);
  }

  // Single number
  const n = parseInt(trimmed);
  if (!isNaN(n) && n >= 1 && n <= files.length) {
    return [files[n - 1]];
  }

  return [];
}

async function prompt(question: string): Promise<string> {
  const rl = createInterface({ input: process.stdin, output: process.stdout });
  return new Promise(res => rl.question(question, ans => { rl.close(); res(ans); }));
}

async function selectReports(arg?: string): Promise<string[]> {
  if (arg) {
    const resolved = resolve(arg);
    if (!existsSync(resolved)) {
      console.error(`File not found: ${resolved}`);
      process.exit(1);
    }
    return [resolved];
  }

  const unrendered = findUnrenderedReports(DAILY_REPORTS_PATH);

  if (unrendered.length === 0) {
    console.log('All reports already rendered.');
    process.exit(0);
  }

  if (unrendered.length === 1) {
    const answer = await prompt(`Render ${relative(DAILY_REPORTS_PATH, unrendered[0])}? [y/N] `);
    return answer.trim().toLowerCase() === 'y' ? unrendered : [];
  }

  console.log('\nUnrendered reports:');
  unrendered.forEach((f, i) => {
    console.log(`  ${String(i + 1).padStart(2)}. ${relative(DAILY_REPORTS_PATH, f)}`);
  });
  console.log();
  const answer = await prompt('Pick number, range (e.g. 1-3), or "all": ');
  const selected = parseSelection(answer, unrendered);
  if (selected.length === 0) {
    console.log('Nothing selected.');
    process.exit(0);
  }
  return selected;
}

// ---------------------------------------------------------------------------
// Render
// ---------------------------------------------------------------------------

async function renderFile(mdPath: string): Promise<void> {
  const md = readFileSync(mdPath, 'utf-8');
  const title = basename(mdPath, '.md');

  // Configure marked for GFM with task lists
  marked.setOptions({ gfm: true });
  const body = await marked.parse(md);

  const html = htmlTemplate(title, body);
  const outPath = mdPath.replace(/\.md$/, '.html');

  mkdirSync(dirname(outPath), { recursive: true });
  writeFileSync(outPath, html, 'utf-8');
  console.log(`Rendered: ${outPath}`);

  // Open in browser
  const opener = process.platform === 'darwin' ? 'open' : 'xdg-open';
  try {
    execSync(`${opener} "${outPath}"`, { stdio: 'ignore' });
  } catch { /* non-fatal if opener not available */ }
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

async function main(): Promise<void> {
  const arg = process.argv[2];
  const files = await selectReports(arg);

  for (const f of files) {
    await renderFile(f);
  }

  if (files.length > 1) {
    console.log(`\nRendered ${files.length} files.`);
  }
}

main().catch(e => {
  console.error('Error:', e instanceof Error ? e.message : String(e));
  process.exit(1);
});
