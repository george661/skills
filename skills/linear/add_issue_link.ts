#!/usr/bin/env npx tsx
// add_issue_link - Create a relation between two Linear issues.
import { linearQuery } from './linear-client.js';

interface Input {
  from_issue: string;  // issue id or identifier
  to_issue: string;    // issue id or identifier
  type?: 'related' | 'blocks' | 'blocked_by' | 'duplicate';
}

interface Result {
  issueRelationCreate: {
    success: boolean;
    issueRelation: {
      id: string;
      type: string;
    };
  };
}

const createRelationMutation = `mutation($issueId: String!, $relatedIssueId: String!, $type: IssueRelationType) {
  issueRelationCreate(input: {
    issueId: $issueId
    relatedIssueId: $relatedIssueId
    type: $type
  }) {
    success
    issueRelation { id type }
  }
}`;

async function execute(params: Input) {
  const type = params.type || 'related';
  return linearQuery<Result>(createRelationMutation, {
    issueId: params.from_issue,
    relatedIssueId: params.to_issue,
    type,
  });
}

const input = JSON.parse(process.argv[2] || '{}') as Input;
execute(input)
  .then((r) => console.log(JSON.stringify(r, null, 2)))
  .catch((e) => { console.error(e.message); process.exit(1); });
