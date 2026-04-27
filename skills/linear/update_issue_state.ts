#!/usr/bin/env npx tsx
// update_issue_state - Transition a Linear issue to a different workflow state.
import { linearQuery } from './linear-client.js';

interface Input {
  id?: string;
  identifier?: string;
  stateId: string;
}

interface Result {
  issueUpdate: {
    success: boolean;
    issue: {
      id: string;
      identifier: string;
      title: string;
    };
  };
}

interface IssueQueryResult {
  issue: {
    id: string;
    identifier: string;
  };
}

const updateMutation = `mutation($id: String!, $input: IssueUpdateInput!) {
  issueUpdate(id: $id, input: $input) {
    success
    issue { id identifier title }
  }
}`;

const issueByIdentifierQuery = `query($identifier: String!) {
  issue(id: $identifier) {
    id
    identifier
  }
}`;

async function execute(params: Input) {
  let issueId = params.id;

  // If identifier provided but not id, resolve identifier → id
  if (!issueId && params.identifier) {
    const result = await linearQuery<IssueQueryResult>(issueByIdentifierQuery, { identifier: params.identifier });
    if (!result.issue) {
      throw new Error(`Issue with identifier "${params.identifier}" not found`);
    }
    issueId = result.issue.id;
  }

  if (!issueId) {
    throw new Error('Either id or identifier must be provided');
  }

  return linearQuery<Result>(updateMutation, { id: issueId, input: { stateId: params.stateId } });
}

const input = JSON.parse(process.argv[2] || '{}') as Input;
execute(input)
  .then((r) => console.log(JSON.stringify(r, null, 2)))
  .catch((e) => { console.error(e.message); process.exit(1); });
