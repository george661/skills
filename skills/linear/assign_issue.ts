#!/usr/bin/env npx tsx
// assign_issue - Assign a Linear issue to a user.
import { linearQuery } from './linear-client.js';

interface Input {
  issue_id: string;  // issue id or identifier
  assignee_id: string;  // user id
}

interface Result {
  issueUpdate: {
    success: boolean;
    issue: {
      id: string;
      identifier: string;
      assignee: {
        id: string;
        name: string;
        email: string;
      } | null;
    };
  };
}

const mutation = `mutation($id: String!, $input: IssueUpdateInput!) {
  issueUpdate(id: $id, input: $input) {
    success
    issue {
      id
      identifier
      assignee {
        id
        name
        email
      }
    }
  }
}`;

async function execute(params: Input) {
  return linearQuery<Result>(mutation, {
    id: params.issue_id,
    input: { assigneeId: params.assignee_id },
  });
}

const input = JSON.parse(process.argv[2] || '{}') as Input;
execute(input)
  .then((r) => console.log(JSON.stringify(r, null, 2)))
  .catch((e) => { console.error(e.message); process.exit(1); });
