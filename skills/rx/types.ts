export type CheckStatus = 'pass' | 'fail' | 'fixed' | 'skipped';

export interface CheckResult {
  check: string;
  category: string;
  status: CheckStatus;
  message: string;
  action?: string;
  error?: string;
}

export interface Check {
  name: string;
  category: string;
  run(opts: RunOpts): Promise<CheckResult[]>;
}

export interface RunOpts {
  dryRun: boolean;
  verbose: boolean;
  json: boolean;
  category?: string;
  previousLog: LogEntry[];
  projectRoot: string;
  agentsRoot: string;
}

export interface LogEntry {
  timestamp: string;
  runId: string;
  check: string;
  category: string;
  status: CheckStatus;
  message: string;
  action?: string;
  error?: string;
}

export interface RunSummary {
  runId: string;
  timestamp: string;
  summary: {
    total: number;
    pass: number;
    fixed: number;
    fail: number;
    skipped: number;
  };
  results: CheckResult[];
  logFile: string;
}

export interface BrewPackage {
  name: string;
  required: boolean;
  description: string;
  version_command: string;
}

export interface Repository {
  name: string;
  git_url: string;
  description: string;
  required: boolean;
}

export interface Plugin {
  name: string;
  marketplace: string;
  required: boolean;
}

export interface CredentialSet {
  jira?: { host: string; username: string; apiToken: string };
  bitbucket?: { workspace: string; username: string; token: string; default_branch: string };
  agentdb?: { apiKey: string; url: string };
  slack?: { botToken: string; defaultChannel: string };
  concourse?: { url: string; team: string; token: string };
}
