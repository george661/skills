#!/usr/bin/env npx tsx
// create_issue - Create a new Linear issue.
import { linearQuery } from './linear-client.js';

interface Input {
  input: Record<string, unknown>;
}

interface Result {
  issueCreate: {
    success: boolean;
    issue: {
      id: string;
      identifier: string;
      title: string;
    };
  };
}

const query = `mutation($input: IssueCreateInput!) {
  issueCreate(input: $input) {
    success
    issue { id identifier title }
  }
}`;

async function execute(params: Input) {
  return linearQuery<Result>(query, { input: params.input });
}

const input = JSON.parse(process.argv[2] || '{}') as Input;
execute(input)
  .then((r) => console.log(JSON.stringify(r, null, 2)))
  .catch((e) => { console.error(e.message); process.exit(1); });
