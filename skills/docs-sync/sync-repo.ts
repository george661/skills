#!/usr/bin/env npx ts-node

/**
 * Sync Repo Skill
 * Commits staged changes to project-docs and pushes to remote repository
 *
 * Usage:
 *   # Validate and commit with auto-generated message
 *   npx tsx .claude/skills/project-docs/sync-repo.ts '{
 *     "validateOnly": false,
 *     "pushToRemote": true,
 *     "autoGenerateMessage": true
 *   }'
 *
 *   # Validate only (no commit)
 *   npx tsx .claude/skills/project-docs/sync-repo.ts '{"validateOnly": true}'
 *
 *   # Custom message
 *   npx tsx .claude/skills/project-docs/sync-repo.ts '{
 *     "message": "docs: add session management design doc",
 *     "pushToRemote": true
 *   }'
 */

import * as fs from 'fs';
import * as path from 'path';
import { exec } from 'child_process';
import { promisify } from 'util';

const execAsync = promisify(exec);

interface SyncRepoParams {
  message?: string;
  files?: string[];
  validateOnly?: boolean;
  pushToRemote?: boolean;
  autoGenerateMessage?: boolean;
}

interface SyncRepoResult {
  success: boolean;
  commitHash?: string;
  filesCommitted: string[];
  commitMessage: string;
  pushed: boolean;
  pushUrl?: string;
  validationPassed: boolean;
  errors: string[];
  timestamp: string;
}

async function validateEnvironment(): Promise<{
  docsPath: string;
  projectRoot: string;
}> {
  const docsPath = process.env.TENANT_DOCS_PATH;
  const projectRoot = process.env.PROJECT_ROOT;

  if (!docsPath) {
    throw new Error('TENANT_DOCS_PATH environment variable not set');
  }

  if (!projectRoot) {
    throw new Error('PROJECT_ROOT environment variable not set');
  }

  if (!fs.existsSync(docsPath)) {
    throw new Error(`TENANT_DOCS_PATH does not exist: ${docsPath}`);
  }

  return { docsPath, projectRoot };
}

async function validateGitRepository(docsPath: string): Promise<boolean> {
  try {
    await execAsync('git rev-parse --git-dir', { cwd: docsPath });
    return true;
  } catch (error) {
    console.error('Not a git repository:', docsPath);
    return false;
  }
}

async function getStagedFiles(docsPath: string): Promise<string[]> {
  try {
    const { stdout } = await execAsync('git diff --cached --name-only', {
      cwd: docsPath,
    });

    return stdout
      .trim()
      .split('\n')
      .filter((f) => f.length > 0);
  } catch (error) {
    console.warn('Could not get staged files:', error);
    return [];
  }
}

function generateCommitMessage(files: string[]): string {
  const timestamp = new Date().toISOString().split('T')[0];

  const designs = files.filter((f) => f.includes('designs/'));
  const implementations = files.filter((f) => f.includes('implementations/'));
  const repositories = files.filter((f) => f.includes('repositories/'));
  const planning = files.filter((f) => f.includes('planning/'));

  let message = `docs: centralize documentation artifacts [${timestamp}]\n\n`;

  if (designs.length > 0) {
    message += `Design Documents: ${designs.length} file(s)\n`;
  }

  if (implementations.length > 0) {
    message += `Implementation Plans: ${implementations.length} file(s)\n`;
  }

  if (repositories.length > 0) {
    message += `Repository References: ${repositories.length} file(s)\n`;
  }

  if (planning.length > 0) {
    message += `Planning Documents: ${planning.length} file(s)\n`;
  }

  message += `\nSkill: sync-repo.ts`;

  return message;
}

async function validateCommit(
  docsPath: string,
  files: string[]
): Promise<{ valid: boolean; errors: string[] }> {
  const errors: string[] = [];

  for (const file of files) {
    const filePath = path.join(docsPath, file);
    if (!fs.existsSync(filePath)) {
      errors.push(`File does not exist: ${file}`);
    }

    const ext = path.extname(file);
    if (!['.md', '.yaml', '.yml', '.json'].includes(ext)) {
      errors.push(`Unsupported file type: ${file}`);
    }

    try {
      const stats = fs.statSync(filePath);
      if (stats.size > 1024 * 1024) {
        errors.push(`File too large: ${file} (${stats.size} bytes)`);
      }
    } catch (error) {
      errors.push(`Cannot stat file: ${file}`);
    }
  }

  try {
    const { stdout } = await execAsync('git status --porcelain', {
      cwd: docsPath,
    });

    if (!stdout.trim()) {
      errors.push('No staged changes to commit');
    }
  } catch (error) {
    errors.push('Could not check git status');
  }

  return {
    valid: errors.length === 0,
    errors,
  };
}

async function commitChanges(
  docsPath: string,
  message: string
): Promise<{ hash: string; files: string[] }> {
  const files = await getStagedFiles(docsPath);

  if (files.length === 0) {
    throw new Error('No staged files to commit');
  }

  try {
    await execAsync(`git commit -m "${message.replace(/"/g, '\\"')}"`, {
      cwd: docsPath,
    });

    const { stdout } = await execAsync('git rev-parse HEAD', {
      cwd: docsPath,
    });

    const hash = stdout.trim();

    return { hash, files };
  } catch (error) {
    throw new Error(`Commit failed: ${error}`);
  }
}

async function pushToRemote(
  docsPath: string
): Promise<{ success: boolean; url?: string; error?: string }> {
  try {
    const { stdout: remoteStdout } = await execAsync('git remote -v', {
      cwd: docsPath,
    });

    if (!remoteStdout.includes('origin')) {
      return {
        success: false,
        error: 'No origin remote configured',
      };
    }

    const { stdout: branchStdout } = await execAsync(
      'git rev-parse --abbrev-ref HEAD',
      {
        cwd: docsPath,
      }
    );

    const currentBranch = branchStdout.trim();

    await execAsync(`git push origin ${currentBranch}`, {
      cwd: docsPath,
    });

    const { stdout: urlStdout } = await execAsync('git remote get-url origin', {
      cwd: docsPath,
    });

    const url = urlStdout.trim();

    return {
      success: true,
      url,
    };
  } catch (error) {
    return {
      success: false,
      error: `Push failed: ${error}`,
    };
  }
}

/**
 * Synchronize project-docs repository by committing staged changes and pushing to remote
 * @param params Sync options including message, validateOnly flag, and pushToRemote flag
 * @returns Result containing commit hash, files committed, push status, and validation errors
 */
async function syncRepo(params: SyncRepoParams): Promise<SyncRepoResult> {
  const errors: string[] = [];
  let validationPassed = false;
  let commitHash: string | undefined;
  let filesCommitted: string[] = [];
  let commitMessage = '';
  let pushed = false;
  let pushUrl: string | undefined;

  try {
    const { docsPath } = await validateEnvironment();

    const isGitRepo = await validateGitRepository(docsPath);
    if (!isGitRepo) {
      throw new Error('project-docs is not a git repository');
    }

    const stagedFiles = await getStagedFiles(docsPath);

    if (stagedFiles.length === 0) {
      errors.push('No staged files to commit');
      return {
        success: false,
        filesCommitted: [],
        commitMessage: 'No changes staged',
        pushed: false,
        validationPassed: false,
        errors,
        timestamp: new Date().toISOString(),
      };
    }

    const customMessage = params.message;
    const autoGenerate = params.autoGenerateMessage !== false;

    commitMessage =
      customMessage ||
      (autoGenerate ? generateCommitMessage(stagedFiles) : 'Update documentation');

    const validation = await validateCommit(docsPath, stagedFiles);
    validationPassed = validation.valid;

    if (!validationPassed) {
      errors.push(...validation.errors);

      if (params.validateOnly) {
        return {
          success: false,
          filesCommitted: stagedFiles,
          commitMessage,
          pushed: false,
          validationPassed: false,
          errors,
          timestamp: new Date().toISOString(),
        };
      }
    }

    if (params.validateOnly) {
      return {
        success: validationPassed,
        filesCommitted: stagedFiles,
        commitMessage,
        pushed: false,
        validationPassed,
        errors,
        timestamp: new Date().toISOString(),
      };
    }

    const commitResult = await commitChanges(docsPath, commitMessage);
    commitHash = commitResult.hash;
    filesCommitted = commitResult.files;

    const shouldPush = params.pushToRemote !== false;
    if (shouldPush) {
      const pushResult = await pushToRemote(docsPath);
      pushed = pushResult.success;
      pushUrl = pushResult.url;

      if (!pushed) {
        errors.push(pushResult.error || 'Push to remote failed');
      }
    }

    return {
      success: true,
      commitHash,
      filesCommitted,
      commitMessage,
      pushed,
      pushUrl,
      validationPassed: true,
      errors,
      timestamp: new Date().toISOString(),
    };
  } catch (error) {
    errors.push(error instanceof Error ? error.message : String(error));

    return {
      success: false,
      filesCommitted,
      commitMessage,
      pushed: false,
      validationPassed,
      errors,
      timestamp: new Date().toISOString(),
    };
  }
}

// Main execution
const params: SyncRepoParams = JSON.parse(process.argv[2] || '{}');

syncRepo(params)
  .then((result) => {
    console.log(JSON.stringify(result, null, 2));
    process.exit(result.success ? 0 : 1);
  })
  .catch((error) => {
    console.error(
      JSON.stringify(
        {
          success: false,
          error: error.message,
          validationPassed: false,
          errors: [error.message],
        },
        null,
        2
      )
    );
    process.exit(1);
  });
