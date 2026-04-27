#!/usr/bin/env npx tsx
// list_comments - List comments on a Linear issue.
import { linearQuery } from './linear-client.js';

interface Input {
  issue_id: string;  // issue id or identifier
}

interface Result {
  issue: {
    id: string;
    identifier: string;
    comments: {
      nodes: Array<{
        id: string;
        body: string;
        createdAt: string;
        user: {
          id: string;
          name: string;
          email: string;
        };
      }>;
    };
  };
}

const query = `query($id: String!) {
  issue(id: $id) {
    id
    identifier
    comments {
      nodes {
        id
        body
        createdAt
        user {
          id
          name
          email
        }
      }
    }
  }
}`;

async function execute(params: Input) {
  return linearQuery<Result>(query, { id: params.issue_id });
}

const input = JSON.parse(process.argv[2] || '{}') as Input;
execute(input)
  .then((r) => console.log(JSON.stringify(r, null, 2)))
  .catch((e) => { console.error(e.message); process.exit(1); });
