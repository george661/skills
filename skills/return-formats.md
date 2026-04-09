# MCP Tool Return Formats

Quick reference for parsing MCP tool results in programmatic orchestration.

## Jira MCP

### search_issues

```typescript
interface SearchIssuesResponse {
  issues: Array<{
    key: string;              // "PROJ-123"
    id: string;               // "10001"
    self: string;             // API URL
    fields: {
      summary: string;
      status: {
        name: string;         // "To Do", "In Progress", "Done"
        id: string;
      };
      priority?: {
        name: string;         // "Critical", "High", "Medium", "Low"
        id: string;
      };
      issuetype: {
        name: string;         // "Bug", "Task", "Story", "Epic"
      };
      assignee?: {
        displayName: string;
        accountId: string;
      } | null;
      created: string;        // "2025-01-08T10:30:00.000+0000"
      updated: string;
      parent?: {              // Only if subtask or under epic
        key: string;
        fields: { summary: string; };
      };
    };
  }>;
  startAt: number;
  maxResults: number;
  total: number;              // Total matching (may exceed returned)
}
```

**Access patterns:**
```typescript
const firstIssue = response.issues[0];
const issueKey = firstIssue.key;
const status = firstIssue.fields.status.name;
const hasMore = response.total > response.startAt + response.maxResults;
```

### get_issue

```typescript
interface GetIssueResponse {
  key: string;
  id: string;
  fields: {
    summary: string;
    description?: string | null;
    status: { name: string; id: string; };
    priority: { name: string; id: string; };
    issuetype: { name: string; id: string; };
    assignee?: { displayName: string; accountId: string; } | null;
    reporter?: { displayName: string; accountId: string; };
    created: string;
    updated: string;
    labels: string[];
    parent?: { key: string; fields: { summary: string; }; };
    subtasks?: Array<{ key: string; fields: { summary: string; status: { name: string; }; }; }>;
  };
}
```

### list_transitions

```typescript
interface TransitionsResponse {
  transitions: Array<{
    id: string;               // "21", "31", etc.
    name: string;             // "In Progress", "Done"
    to: {
      name: string;
      id: string;
    };
  }>;
}
```

**Access pattern:**
```typescript
const toInProgress = response.transitions.find(t => t.name === 'In Progress');
const transitionId = toInProgress?.id;
```

### create_issue / update_issue

```typescript
interface IssueResponse {
  id: string;
  key: string;                // "PROJ-124"
  self: string;
}
```

---

## Bitbucket MCP

### list_pull_requests

```typescript
interface ListPRsResponse {
  values: Array<{
    id: number;
    title: string;
    state: "OPEN" | "MERGED" | "DECLINED" | "SUPERSEDED";
    source: {
      branch: { name: string; };
      commit?: { hash: string; };
    };
    destination: {
      branch: { name: string; };
    };
    author: {
      display_name: string;
      uuid: string;
    };
    created_on: string;       // ISO 8601
    updated_on: string;
    comment_count: number;
    links: {
      html: { href: string; };
    };
  }>;
  size: number;
  page: number;
  pagelen: number;
  next?: string;              // Pagination URL
}
```

**Access patterns:**
```typescript
const openPRs = response.values.filter(pr => pr.state === 'OPEN');
const prForBranch = response.values.find(pr => pr.source.branch.name === branchName);
const prUrl = prForBranch?.links.html.href;
```

### get_pull_request

```typescript
interface PRResponse {
  id: number;
  title: string;
  description: string;
  state: "OPEN" | "MERGED" | "DECLINED" | "SUPERSEDED";
  source: {
    branch: { name: string; };
    commit: { hash: string; };
  };
  destination: {
    branch: { name: string; };
  };
  merge_commit?: { hash: string; };  // Only if merged
  author: { display_name: string; };
  created_on: string;
  updated_on: string;
  links: {
    html: { href: string; };
    diff: { href: string; };
  };
}
```

### fly/list_builds

```typescript
interface ListBuildsResponse {
  target: string;              // "my-concourse"
  count: number;               // Number of builds returned
  filters: {
    pipeline: string;          // "api-service"
    job: string | null;
    requested_count: number;   // 25
  };
  builds: Array<{
    id: number;                // 42
    team_name: string;         // "main"
    name: string;              // "42"
    status: "succeeded" | "failed" | "aborted" | "pending" | "started";
    job_name: string;          // "build"
    pipeline_name: string;     // "api-service"
    start_time: number;        // Unix timestamp
    end_time: number;          // Unix timestamp
  }>;
}
```

**Access patterns:**
```typescript
const latestBuild = response.builds[0];
const isSuccess = latestBuild.status === 'succeeded';
const isFailed = latestBuild.status === 'failed';
const isRunning = latestBuild.status === 'started';
const durationSec = latestBuild.end_time - latestBuild.start_time;
```

### concourse/list_jobs

```typescript
type ListJobsResponse = Array<{
  name: string;                // "build"
  pipeline_name: string;       // "api-service"
  team_name: string;           // "main"
  finished_build: {
    id: number;                // 42
    name: string;              // "42"
    status: "succeeded" | "failed" | "aborted" | "errored";
    start_time: number;        // Unix timestamp
    end_time: number;          // Unix timestamp
  } | null;
  next_build: {
    id: number;
    name: string;
    status: "pending" | "started";
    start_time: number;
    end_time: number;
  } | null;
}>;
```

**Access pattern (find failed job):**
```typescript
const failedJob = response.find(j => j.finished_build?.status === 'failed');
const failedJobName = failedJob?.name;
const isRunning = response.some(j => j.next_build !== null);
```

### create_pull_request

```typescript
interface CreatePRResponse {
  id: number;
  title: string;
  state: "OPEN";
  links: {
    html: { href: string; };
  };
}
```

### merge_pull_request

```typescript
interface MergeResponse {
  id: number;
  state: "MERGED";
  merge_commit: {
    hash: string;
  };
}
```

---

## AgentDB REST Skills

### pattern_search

```typescript
interface PatternSearchResponse {
  results: Array<{
    task: string;
    pattern: object;
    score: number;
  }>;
}
```

**Access pattern:**
```typescript
const topPattern = response.results[0];
const approach = topPattern.pattern;
```

### reflexion_store_episode

```typescript
interface StoreEpisodeResponse {
  success: boolean;
  episode_id: string;
}
```

### reflexion_retrieve_relevant

```typescript
interface RetrieveRelevantResponse {
  episodes: Array<{
    task: string;
    reward: number;
    success: boolean;
    session_id: string;
  }>;
}
```

---

## Common Patterns

### Null Checks

Many fields can be null or undefined:

```typescript
// Safe access
const assignee = issue.fields.assignee?.displayName ?? 'Unassigned';
const parentKey = issue.fields.parent?.key;
const mergeCommit = pr.merge_commit?.hash;
```

### Pagination Check

```typescript
// Jira
const hasMoreIssues = response.total > response.startAt + response.maxResults;

// Bitbucket
const hasMorePages = response.next !== undefined;
```

### Status Checks

```typescript
// Build status (Concourse)
const isRunning = build.status === 'started';
const isSuccess = build.status === 'succeeded';
const isFailed = build.status === 'failed';

// PR status
const canMerge = pr.state === 'OPEN';
const wasMerged = pr.state === 'MERGED';
```

### Date Parsing

All dates are ISO 8601 format:

```typescript
const created = new Date(issue.fields.created);
const ageHours = (Date.now() - created.getTime()) / (1000 * 60 * 60);
```
