#!/usr/bin/env npx tsx
// get_issue - Get detailed information about a specific Linear issue by identifier.
import { linearQuery } from './linear-client.js';

interface Input {
  id: string;
}

interface Result {
  issue: {
    id: string;
    identifier: string;
    title: string;
    description: string | null;
    state: { name: string };
    priority: number;
    assignee: { name: string } | null;
    labels: { nodes: Array<{ name: string }> };
  };
}

const query = `query($id: String!) {
  issue(id: $id) {
    id
    identifier
    title
    description
    state { name }
    priority
    assignee { name }
    labels { nodes { name } }
  }
}`;

async function execute(input: Input) {
  return linearQuery<Result>(query, { id: input.id });
}

const input = JSON.parse(process.argv[2] || '{}') as Input;
execute(input)
  .then((r) => console.log(JSON.stringify(r, null, 2)))
  .catch((e) => { console.error(e.message); process.exit(1); });
