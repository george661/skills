#!/usr/bin/env npx tsx
// add_issue_link - Create a relation between two Linear issues.
import { linearQuery } from './linear-client.js';

interface Input {
  from_issue: string;  // issue UUID (identifiers will be resolved to UUIDs)
  to_issue: string;    // issue UUID (identifiers will be resolved to UUIDs)
  type?: 'related' | 'blocks' | 'blocked_by' | 'duplicate';
}

interface IssueQueryResult {
  issue: {
    id: string;
    identifier: string;
  } | null;
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

const issueByIdentifierQuery = `query($identifier: String!) {
  issue(id: $identifier) {
    id
    identifier
  }
}`;

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

async function resolveIssueId(issueIdOrIdentifier: string): Promise<string> {
  // If it looks like a UUID, use it directly
  if (/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(issueIdOrIdentifier)) {
    return issueIdOrIdentifier;
  }

  // Otherwise, query Linear to resolve identifier → id
  const result = await linearQuery<IssueQueryResult>(issueByIdentifierQuery, { identifier: issueIdOrIdentifier });
  if (!result.issue) {
    throw new Error(`Issue with identifier "${issueIdOrIdentifier}" not found`);
  }
  return result.issue.id;
}

async function execute(params: Input) {
  const type = params.type || 'related';

  // Resolve both issue identifiers to UUIDs
  const fromIssueId = await resolveIssueId(params.from_issue);
  const toIssueId = await resolveIssueId(params.to_issue);

  return linearQuery<Result>(createRelationMutation, {
    issueId: fromIssueId,
    relatedIssueId: toIssueId,
    type,
  });
}

const input = JSON.parse(process.argv[2] || '{}') as Input;
execute(input)
  .then((r) => console.log(JSON.stringify(r, null, 2)))
  .catch((e) => { console.error(e.message); process.exit(1); });
