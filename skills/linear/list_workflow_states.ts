#!/usr/bin/env npx tsx
// list_workflow_states - List workflow states for a Linear team.
import { linearQuery, getLinearCredentials } from './linear-client.js';

interface Input {
  teamKey?: string;
}

interface Result {
  workflowStates: {
    nodes: Array<{
      id: string;
      name: string;
      type: string;
    }>;
  };
}

const query = `query($teamKey: String) {
  workflowStates(filter: { team: { key: { eq: $teamKey } } }) {
    nodes { id name type }
  }
}`;

async function execute(params: Input) {
  const { teamKey: defaultTeamKey } = getLinearCredentials();
  const teamKey = params.teamKey || defaultTeamKey;
  return linearQuery<Result>(query, { teamKey });
}

const input = JSON.parse(process.argv[2] || '{}') as Input;
execute(input)
  .then((r) => console.log(JSON.stringify(r, null, 2)))
  .catch((e) => { console.error(e.message); process.exit(1); });
