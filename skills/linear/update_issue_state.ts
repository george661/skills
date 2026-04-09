#!/usr/bin/env npx tsx
// update_issue_state - Transition a Linear issue to a different workflow state.
import { linearQuery } from './linear-client.js';

interface Input {
  id: string;
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

const query = `mutation($id: String!, $input: IssueUpdateInput!) {
  issueUpdate(id: $id, input: $input) {
    success
    issue { id identifier title }
  }
}`;

async function execute(params: Input) {
  return linearQuery<Result>(query, { id: params.id, input: { stateId: params.stateId } });
}

const input = JSON.parse(process.argv[2] || '{}') as Input;
execute(input)
  .then((r) => console.log(JSON.stringify(r, null, 2)))
  .catch((e) => { console.error(e.message); process.exit(1); });
