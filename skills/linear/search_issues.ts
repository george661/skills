#!/usr/bin/env npx tsx
// search_issues - Search and filter Linear issues.
import { linearQuery } from './linear-client.js';

interface Input {
  filter: Record<string, unknown>;
}

interface Result {
  issues: {
    nodes: Array<{
      id: string;
      identifier: string;
      title: string;
      state: { name: string };
      priority: number;
      assignee: { name: string } | null;
    }>;
  };
}

const query = `query($filter: IssueFilter) {
  issues(filter: $filter) {
    nodes {
      id
      identifier
      title
      state { name }
      priority
      assignee { name }
    }
  }
}`;

async function execute(input: Input) {
  return linearQuery<Result>(query, { filter: input.filter });
}

const input = JSON.parse(process.argv[2] || '{}') as Input;
execute(input)
  .then((r) => console.log(JSON.stringify(r, null, 2)))
  .catch((e) => { console.error(e.message); process.exit(1); });
