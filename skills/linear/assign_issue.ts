#!/usr/bin/env npx tsx
// assign_issue - Assign a Linear issue to a user.
import { linearQuery } from './linear-client.js';

interface Input {
  issue_id: string;  // issue UUID (identifiers will be resolved to UUIDs)
  assignee_id: string;  // user id
}

interface IssueQueryResult {
  issue: {
    id: string;
    identifier: string;
  } | null;
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

const issueByIdentifierQuery = `query($identifier: String!) {
  issue(id: $identifier) {
    id
    identifier
  }
}`;

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
  let issueId = params.issue_id;

  // If it doesn't look like a UUID, resolve identifier → id
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(issueId)) {
    const result = await linearQuery<IssueQueryResult>(issueByIdentifierQuery, { identifier: issueId });
    if (!result.issue) {
      throw new Error(`Issue with identifier "${issueId}" not found`);
    }
    issueId = result.issue.id;
  }

  return linearQuery<Result>(mutation, {
    id: issueId,
    input: { assigneeId: params.assignee_id },
  });
}

const input = JSON.parse(process.argv[2] || '{}') as Input;
execute(input)
  .then((r) => console.log(JSON.stringify(r, null, 2)))
  .catch((e) => { console.error(e.message); process.exit(1); });
