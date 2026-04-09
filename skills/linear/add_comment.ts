#!/usr/bin/env npx tsx
// add_comment - Add a comment to a Linear issue.
import { linearQuery } from './linear-client.js';

interface Input {
  input: Record<string, unknown>;
}

interface Result {
  commentCreate: {
    success: boolean;
    comment: {
      id: string;
      body: string;
    };
  };
}

const query = `mutation($input: CommentCreateInput!) {
  commentCreate(input: $input) {
    success
    comment { id body }
  }
}`;

async function execute(params: Input) {
  return linearQuery<Result>(query, { input: params.input });
}

const input = JSON.parse(process.argv[2] || '{}') as Input;
execute(input)
  .then((r) => console.log(JSON.stringify(r, null, 2)))
  .catch((e) => { console.error(e.message); process.exit(1); });
